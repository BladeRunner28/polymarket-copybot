/**
 * sentiment:edge-dryrun — if the sentiment layer stopped trusting a CONSTANT
 * polarity, what exactly changes? READ-ONLY: no RuleSet row, no prisma write,
 * no decision, no published figure. Card `sentiment-edge-single-polarity`
 * (Lane A proposal), dry run for option A vs option B.
 *
 * WHY. `aggregateSentimentForCategory` (src/lib/forecasting/sentiment.ts) reads
 * every opinionated RegulatorySignal row in a category's 7d window and turns it
 * into a copyScore delta. Measured 2026-11-15/16 (insidercat-source-audit): the
 * congress_gov_api feed assigns a per-CATEGORY CONSTANT polarity from a keyword
 * table, so within a category the "evidence" has exactly one sign by
 * construction. The resulting edge is a category prior — it can only ever push
 * every copy in that category the same way, never express a direction.
 *
 * THE TWO OPTIONS PRICED HERE (both reader-side filters, no threshold/size/lane/
 * gate change):
 *   A  dedupe by distinct disclosure, then DROP every source that shows a single
 *      polarity value WITHIN the category being scored.
 *   B  keep every row, but emit no edge at all unless the set holds >= 2 distinct
 *      polarity values (turn the minSignals check into a variance check).
 *   A+B  A, then B's variance gate as a final condition (the recommended shape:
 *      A alone still emits a constant edge if the one surviving source is itself
 *      constant).
 *
 * WHAT IT PRINTS, with the basis on every line:
 *   1 SUPPLY   per category, per source: distinct disclosures, distinct
 *              polarities and the modal share. population=RegulatorySignal rows,
 *              clock=processedAt UTC, level=one signal row / one disclosure.
 *   2 ARMS     LIVE / A / B / A+B delta (pp) per category, as of now.
 *   3 REPLAY   every historical decision that carried a sentiment edge, re-scored
 *              at ITS OWN asOf (window [createdAt-7d, createdAt]) under LIVE and
 *              under A, then run through the real sizing/admission arithmetic:
 *              band before/after, $ size before/after (STANDARD curve), copies
 *              lost/gained, and whether the size function reproduces the stored
 *              size (the verification that the replay is faithful).
 *   4 SHADOW   data/sentiment-ab.jsonl (LOCAL_SENTIMENT_MODEL vs the keyword
 *              rules): does the shadow find >= 2 directions on the same items?
 *              That is the card's own refutation condition.
 *   5 OUTCOME  on settled legs of the categories whose set A zeroes: did the leg's
 *              token beat its price? Both label arms printed (market outcome via
 *              OutcomeReview.finalOutcome, and realizedPnl>0), both populations.
 *
 * BASIS caveats printed with the numbers: the $ column is the STANDARD curve
 * (scoreTrade's own size), because C-200 Kelly sizing bypasses the copyScore band
 * map and prices off λ̂/price/bankroll — for C-200 this change is an ADMISSION
 * question only, so no dollar figure is claimed for it.
 *
 * Usage: npx tsx scripts/sentiment-edge-dryrun.ts [--days 7] [--json] [--self-test]
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { prisma } from "../src/lib/db";
import { aggregateEvidenceItems, type AggregateResult } from "../src/lib/forecasting/index";
import { buildEvidenceItems, type SignalRow } from "../src/lib/forecasting/sentiment";
import {
  DEFAULT_OPINIONATED_THRESHOLD,
  dedupeByEvent,
  polarityConcentration,
  signedEvidence,
  type SupplyRow,
} from "../src/lib/research-source-supply";
import { researchCategoryFor } from "../src/lib/research-categories";
import { getActiveRules, type Rules } from "../src/lib/rules";
import { clampPaperSize } from "../src/lib/safety";
import { didOutcomeWin } from "../src/lib/resolution";

const args = process.argv.slice(2);
const SELF_TEST = args.includes("--self-test");
const JSON_OUT = args.includes("--json");
const daysIdx = args.indexOf("--days");
const WINDOW_DAYS = daysIdx >= 0 ? Number(args[daysIdx + 1]) : 7;
const T = DEFAULT_OPINIONATED_THRESHOLD;
const DAY_MS = 86_400_000;

const CATEGORIES = [
  "Crypto",
  "Tech/AI",
  "Defense/Geopolitics",
  "Healthcare",
  "Energy/Climate",
  "Finance",
  "Macro/Politics",
];

type SigRow = SupplyRow & { marketCategory: string };

const round1 = (v: number) => Math.round(v * 10) / 10;
const pp = (d: number | null | undefined) =>
  d == null ? "none" : `${d >= 0 ? "+" : ""}${(d * 100).toFixed(2)}pp`;
const pct = (n: number, d: number) => (d === 0 ? "n/a" : `${((100 * n) / d).toFixed(1)}%`);
const usd = (v: number) => `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(2)}`;

/** Sources whose polarity has ONE distinct value inside this set. */
export function constantSources(rows: SupplyRow[]): string[] {
  const bySource = new Map<string, Set<number>>();
  for (const r of rows) {
    const set = bySource.get(r.source) ?? new Set<number>();
    set.add(r.sentimentScore);
    bySource.set(r.source, set);
  }
  return [...bySource.entries()].filter(([, s]) => s.size === 1).map(([src]) => src);
}

/** Option A: one row per distinct disclosure, minus sources constant in this set.
 *  Delegates to the shipped `signedEvidence` so the dry run prices the SAME
 *  function the patch would call — no second implementation to drift. */
export function armA(rows: SupplyRow[]): SupplyRow[] {
  return signedEvidence(rows);
}

/** Option B: keep every row, but a set with < 2 distinct polarities emits nothing. */
export function armB(rows: SupplyRow[]): SupplyRow[] | null {
  return polarityConcentration(rows).distinctValues >= 2 ? rows : null;
}

/** A + B's variance gate: the recommended shape. */
export function armAB(rows: SupplyRow[]): SupplyRow[] | null {
  const a = armA(rows);
  if (a.length === 0) return null;
  return polarityConcentration(a).distinctValues >= 2 ? a : null;
}

function edgeOf(rows: SupplyRow[] | null, asOf: Date, prior: number): AggregateResult | null {
  if (!rows || rows.length === 0) return null;
  return aggregateEvidenceItems(buildEvidenceItems(rows as SignalRow[], asOf), prior);
}

/** scoreTrade's own size arithmetic (src/lib/scoring/trade.ts), STANDARD curve. */
export function stdSizeFor(
  score: number,
  walletQualityScore: number,
  confidence: number,
  price: number,
  r: Rules
): number {
  const sizeScore =
    r.walletQualityInSize === 0
      ? Math.min(100, Math.max(0, (score - walletQualityScore * 0.3) / 0.7))
      : score;
  const sizeConfidence =
    r.walletQualityInSize === 0
      ? Math.max(0, Math.min(1, (sizeScore - r.watchlistScore) / (100 - r.watchlistScore)))
      : confidence;
  let size: number;
  if (sizeScore >= r.highScoreCapMin) size = r.highScoreCapUsd;
  else if (sizeScore >= r.sweetSpotMinScore) size = r.sweetSpotSizeUsd;
  else size = r.baseSizeUsd + Math.max(0, sizeConfidence - 0.5) * r.confidenceSizeBonus;
  if (price >= r.deadZoneMinPrice && price <= r.deadZoneMaxPrice) size *= r.deadZoneSizeFactor;
  else if (price < r.longshotMaxPrice) size *= r.longshotSizeFactor;
  return Math.round(clampPaperSize(size) * 100) / 100;
}

export function bandOf(score: number, r: Rules): "high" | "sweet" | "base" | "none" {
  if (score >= r.highScoreCapMin) return "high";
  if (score >= r.sweetSpotMinScore) return "sweet";
  if (score >= 55) return "base";
  return "none";
}

export function floorFor(price: number, r: Rules): number {
  return price < r.longshotMaxPrice && r.longshotMinCopyScore > 0
    ? r.longshotMinCopyScore
    : r.minCopyScore;
}

/** The strings src/lib/scoring/trade.ts pushes into `hardSkips` (never risk text). */
const HARD_SKIP_RE =
  /^(wallet score |spread |liquidity \$|price drifted |resolves in |price \d|Orderbook Imbalance|confidence )/;

function hasScoreIndependentHardSkip(risksJson: string | null | undefined): boolean {
  if (!risksJson) return false;
  try {
    const arr = JSON.parse(risksJson);
    if (!Array.isArray(arr)) return false;
    return arr.some((s) => typeof s === "string" && HARD_SKIP_RE.test(s));
  } catch {
    return false;
  }
}

/** Wilson 95% interval for a proportion — printed beside every hit rate. */
function wilson(k: number, n: number): [number, number] {
  if (n === 0) return [0, 0];
  const z = 1.959964;
  const p = k / n;
  const den = 1 + (z * z) / n;
  const mid = p + (z * z) / (2 * n);
  const half = z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n));
  return [(mid - half) / den, (mid + half) / den];
}

function selfTest(): void {
  const at = (iso: string) => new Date(iso);
  const sig = (
    source: string,
    score: number,
    iso: string,
    cat = "Macro/Politics",
    bill = "1"
  ): SigRow => ({
    marketCategory: cat,
    source,
    sentimentScore: score,
    confidence: 0.7,
    processedAt: at(iso),
    rawPayload: JSON.stringify({ type: "HR", number: bill }),
  });

  const checks: Array<[string, boolean, string]> = [];

  // A: a single-value source is dropped, a varying one is kept.
  const constSrc = [sig("c", 0.5, "2026-11-01T00:00:00Z", "Macro/Politics", "1"), sig("c", 0.5, "2026-11-02T00:00:00Z", "Macro/Politics", "1")];
  const varSrc = [sig("q", 0.5, "2026-11-01T00:00:00Z", "Macro/Politics", "2"), sig("q", -0.6, "2026-11-02T00:00:00Z", "Macro/Politics", "3")];
  checks.push(["A drops a constant source", armA(constSrc).length === 0, String(armA(constSrc).length)]);
  const constTwoBills = [
    sig("c", 0.5, "2026-11-01T00:00:00Z", "Macro/Politics", "20"),
    sig("c", 0.5, "2026-11-02T00:00:00Z", "Macro/Politics", "21"),
  ];
  checks.push([
    "A drops a source constant across DIFFERENT disclosures",
    armA(constTwoBills).length === 0,
    String(armA(constTwoBills).length),
  ]);
  checks.push([
    "A keeps a varying source",
    armA(varSrc).length === 2,
    String(armA(varSrc).length),
  ]);
  checks.push([
    "A keeps the varying source but not the constant one",
    armA([...constSrc, ...varSrc]).every((r) => r.source === "q"),
    armA([...constSrc, ...varSrc]).map((r) => r.source).join(","),
  ]);

  // A dedupes first: three re-emissions of one bill are one row before the test.
  const reEmit = [
    sig("c", 0.5, "2026-11-01T00:00:00Z", "Macro/Politics", "9"),
    sig("c", 0.5, "2026-11-02T00:00:00Z", "Macro/Politics", "9"),
    sig("c", 0.5, "2026-11-03T00:00:00Z", "Macro/Politics", "9"),
    sig("q", 0.4, "2026-11-03T00:00:00Z", "Macro/Politics", "10"),
    sig("q", -0.4, "2026-11-04T00:00:00Z", "Macro/Politics", "11"),
  ];
  checks.push(["A dedupes as well as filters", armA(reEmit).length === 2, String(armA(reEmit).length)]);

  // A is per-set, not global: the same source may be constant in one category and
  // varying in another — the filter must be evaluated on the set it is given.
  const crossCat = [
    sig("q", 0.5, "2026-11-01T00:00:00Z", "Crypto", "12"),
    sig("q", -0.5, "2026-11-01T00:00:00Z", "Crypto", "13"),
  ];
  checks.push(["A is evaluated on the given set", armA(crossCat).length === 2, String(armA(crossCat).length)]);

  // B: one distinct value → no edge; two → edge.
  checks.push(["B gates a constant set", armB(constSrc) === null, String(armB(constSrc))]);
  checks.push(["B passes a varying set", armB(varSrc) !== null, String(armB(varSrc)?.length)]);

  // A+B: A removes the constant, B still gates what remains.
  checks.push(["A+B gates a constant set", armAB(constSrc) === null, String(armAB(constSrc))]);
  const mixed = [sig("c", 0.5, "2026-11-01T00:00:00Z"), sig("q", 0.5, "2026-11-02T00:00:00Z")];
  checks.push(["A+B gates a single-signed mixed set", armAB(mixed) === null, String(armAB(mixed))]);
  checks.push(["A+B keeps a two-signed set", armAB(varSrc)?.length === 2, String(armAB(varSrc)?.length)]);

  // The aggregation arm: a dropped set must produce NO delta, not a zero delta item.
  const asOf = at("2026-11-05T00:00:00Z");
  checks.push(["dropped set → null edge", edgeOf(armA(constSrc), asOf, 0.5) === null, ""]);
  const edge = edgeOf(armB(varSrc), asOf, 0.5);
  checks.push(["kept set → non-zero edge", edge !== null && Math.abs(edge.delta) > 0.001, String(edge?.delta)]);

  // hard-skip detection must not fire on soft risk text.
  checks.push([
    "hard skip detected",
    hasScoreIndependentHardSkip(JSON.stringify(["spread 0.090 > max 0.08"])),
    "",
  ]);
  checks.push([
    "soft risk ignored",
    !hasScoreIndependentHardSkip(JSON.stringify(["Spread eats into edge", "Weak overall setup"])),
    "",
  ]);

  let failed = 0;
  for (const [name, ok, detail] of checks) {
    if (!ok) failed++;
    console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` (${detail})` : ""}`);
  }
  console.log(`\nself-test ${checks.length - failed}/${checks.length}`);
  if (failed > 0) process.exit(1);
}

async function main() {
  if (SELF_TEST) return selfTest();

  const { rules, version } = await getActiveRules();
  const asOf = new Date();

  console.log(
    `BASIS  population=RegulatorySignal rows (all sources)  clock=processedAt UTC  ` +
      `level=one signal row (LIVE) / one distinct disclosure (A, A+B)  window=${WINDOW_DAYS}d to ${asOf.toISOString()}`
  );
  console.log(
    `       "opinionated" = |sentimentScore| >= ${T}  RuleSet v${version}  ` +
      `floors ${floorFor(0.1, rules)} longshot / ${rules.minCopyScore} global  boost clamp ${rules.regulatoryScoreCap}  ` +
      `sentimentScale=${rules.sentimentScale}\n`
  );

  const all = (await prisma.regulatorySignal.findMany({
    select: {
      marketCategory: true,
      source: true,
      sentimentScore: true,
      confidence: true,
      processedAt: true,
      rawPayload: true,
    },
    orderBy: { processedAt: "asc" },
  })) as SigRow[];

  const byCat = new Map<string, SigRow[]>();
  for (const r of all) {
    const arr = byCat.get(r.marketCategory) ?? [];
    arr.push(r);
    byCat.set(r.marketCategory, arr);
  }

  const windowOf = (cat: string, until: Date) => {
    const since = new Date(until.getTime() - WINDOW_DAYS * DAY_MS);
    return (byCat.get(cat) ?? []).filter(
      (r) => r.processedAt >= since && r.processedAt <= until && Math.abs(r.sentimentScore) >= T
    );
  };

  // ---------------- 1. SUPPLY ----------------
  console.log(`-- 1. SUPPLY in the ${WINDOW_DAYS}d window, per category (opinionated rows only)`);
  console.log(
    `   ${"category".padEnd(20)}${"src".padEnd(20)}${"rows".padStart(6)}${"discl".padStart(7)}` +
      `${"polarities".padStart(11)}${"modal".padStart(7)}${"share".padStart(8)}`
  );
  const supplyRows: Array<Record<string, unknown>> = [];
  for (const cat of CATEGORIES) {
    const rows = windowOf(cat, asOf);
    if (rows.length === 0) continue;
    const deduped = dedupeByEvent(rows as SupplyRow[]);
    const sources = [...new Set(rows.map((r) => r.source))];
    for (const src of sources) {
      const srcRows = rows.filter((r) => r.source === src);
      const conc = polarityConcentration(srcRows as SupplyRow[], T);
      const discl = dedupeByEvent(srcRows as SupplyRow[]).length;
      console.log(
        `   ${cat.padEnd(20)}${src.padEnd(20)}${String(srcRows.length).padStart(6)}` +
          `${String(discl).padStart(7)}${String(conc.distinctValues).padStart(11)}` +
          `${conc.modal.toFixed(2).padStart(7)}${pct(conc.modalShare * rows.length, rows.length).padStart(8)}`
      );
      supplyRows.push({
        category: cat,
        source: src,
        rows: srcRows.length,
        disclosures: discl,
        distinctPolarities: conc.distinctValues,
        modal: conc.modal,
        modalShare: conc.modalShare,
      });
    }
    const setConc = polarityConcentration(rows as SupplyRow[], T);
    console.log(
      `   ${"  → set".padEnd(20)}${"".padEnd(20)}${String(rows.length).padStart(6)}` +
        `${String(deduped.length).padStart(7)}${String(setConc.distinctValues).padStart(11)}` +
        `${setConc.modal.toFixed(2).padStart(7)}${pct(setConc.modalShare, 1).padStart(8)}` +
        `   single-polarity sources: ${constantSources(rows as SupplyRow[]).join(",") || "—"}`
    );
  }
  console.log();

  // ---------------- 2. ARMS ----------------
  type ArmRead = {
    category: string;
    live: AggregateResult | null;
    a: AggregateResult | null;
    b: AggregateResult | null;
    ab: AggregateResult | null;
    setPolarities: number;
    rows: number;
    disclosures: number;
  };
  const arms: ArmRead[] = [];
  console.log(`-- 2. ARMS as of now (prior 0.50; delta = YES-frame posterior − prior)`);
  console.log(
    `   ${"category".padEnd(20)}${"LIVE n/pp".padStart(16)}${"A n/pp".padStart(16)}` +
      `${"B n/pp".padStart(16)}${"A+B n/pp".padStart(16)}  set polarities`
  );
  for (const cat of CATEGORIES) {
    const rows = windowOf(cat, asOf);
    if (rows.length === 0) continue;
    const live = edgeOf(rows, asOf, 0.5);
    const a = edgeOf(armA(rows), asOf, 0.5);
    const b = edgeOf(armB(rows), asOf, 0.5);
    const ab = edgeOf(armAB(rows), asOf, 0.5);
    const cell = (x: AggregateResult | null) => (x ? `${x.n} ${pp(x.delta)}` : "none").padStart(16);
    console.log(
      `   ${cat.padEnd(20)}${cell(live)}${cell(a)}${cell(b)}${cell(ab)}  ` +
        `${polarityConcentration(rows, T).distinctValues} (${rows.length} rows / ${dedupeByEvent(rows).length} disclosures)`
    );
    arms.push({
      category: cat,
      live,
      a,
      b,
      ab,
      setPolarities: polarityConcentration(rows, T).distinctValues,
      rows: rows.length,
      disclosures: dedupeByEvent(rows).length,
    });
  }
  console.log();

  // ---------------- 3. REPLAY ----------------
  const decisions = await prisma.decisionJournal.findMany({
    where: {
      isDemo: false,
      OR: [
        { sentimentDelta: { not: null } },
        { reasonsJson: { contains: "Sentiment evidence edge" } },
      ],
    },
    select: {
      id: true,
      decision: true,
      marketId: true,
      copyScore: true,
      confidence: true,
      rawConfidence: true,
      walletQualityScore: true,
      simulatedPositionSize: true,
      sentimentDelta: true,
      priceAtDecision: true,
      createdAt: true,
      reasonsJson: true,
      risksJson: true,
      observedTrade: {
        select: { marketQuestion: true, marketCategory: true, detectedPrice: true },
      },
      paperTrades: {
        select: {
          id: true,
          botId: true,
          outcome: true,
          entryPrice: true,
          simulatedPositionSize: true,
          status: true,
          realizedPnl: true,
          closedAt: true,
          resolvedAt: true,
          outcomeReviews: { select: { finalOutcome: true } },
        },
      },
    },
    orderBy: { createdAt: "asc" },
  });

  type ReplayRow = {
    id: string;
    category: string;
    marketId: string;
    decision: string;
    at: string;
    storedPp: number;
    scoreBefore: number;
    scoreAfter: number;
    bandBefore: string;
    bandAfter: string;
    sizeBefore: number;
    sizeAfter: number;
    setZeroed: boolean;
    clampBounded: boolean;
    admittedBefore: boolean;
    admittedAfter: boolean;
    hardSkip: boolean;
  };

  const replay: ReplayRow[] = [];
  let unparsed = 0;
  let verifyTried = 0;
  let verifyOk = 0;
  let sizeChecked = 0;
  let sizeMatched = 0;

  for (const d of decisions) {
    const parsed = /Sentiment evidence edge ([+-]?\d+(?:\.\d+)?)pp/.exec(d.reasonsJson ?? "");
    const storedPp = d.sentimentDelta != null ? d.sentimentDelta * 100 : parsed ? Number(parsed[1]) : null;
    if (storedPp == null || !Number.isFinite(storedPp)) {
      unparsed++;
      continue;
    }
    const cat = researchCategoryFor(d.observedTrade?.marketQuestion, d.observedTrade?.marketCategory) ?? "unmapped";
    const asOfD = d.createdAt;
    const rows = windowOf(cat, asOfD);
    const price = d.priceAtDecision ?? d.observedTrade?.detectedPrice ?? 0.5;

    // Fidelity check: does the replay reproduce the edge the scorer actually wrote?
    // The stored statement is trade-signed in pp; the replay is YES-frame, so compare
    // magnitudes and try both orientations (which one applies depends on the leg's
    // side, which the journal does not carry). This checks the replay; it is never an
    // input to it.
    const liveAt05 = edgeOf(rows, asOfD, 0.5);
    if (liveAt05) {
      verifyTried++;
      const fwd = edgeOf(rows, asOfD, price);
      const mir = edgeOf(rows, asOfD, 1 - price);
      if (fwd && mir) {
        const fwdErr = Math.abs(Math.abs(fwd.delta * 100) - Math.abs(storedPp));
        const mirErr = Math.abs(Math.abs(mir.delta * 100) - Math.abs(storedPp));
        if (Math.min(fwdErr, mirErr) < 0.15) verifyOk++;
      }
    }

    // Both arms are compared at the SAME prior, so the ratio isolates what the
    // filter removes rather than the price dependence of the posterior.
    const aAgg = edgeOf(armA(rows), asOfD, 0.5);
    const ratio =
      aAgg && liveAt05 && Math.abs(liveAt05.delta) > 1e-9 ? aAgg.delta / liveAt05.delta : 0;

    const scoreBefore = d.copyScore;
    const pre = scoreBefore - storedPp;
    const amount = storedPp * ratio;
    let scoreAfter = round1(pre + amount);
    if (amount > 0 && scoreAfter > rules.regulatoryScoreCap) scoreAfter = rules.regulatoryScoreCap;

    const conf = d.rawConfidence ?? d.confidence ?? 0;
    const bandBefore = bandOf(scoreBefore, rules);
    const bandAfter = bandOf(scoreAfter, rules);
    const sizeBefore = stdSizeFor(scoreBefore, d.walletQualityScore ?? 0, conf, price, rules);
    const sizeAfter = stdSizeFor(scoreAfter, d.walletQualityScore ?? 0, conf, price, rules);
    if (d.decision === "paper_copy" && d.simulatedPositionSize != null) {
      sizeChecked++;
      if (Math.abs(sizeBefore - d.simulatedPositionSize) < 0.011) sizeMatched++;
    }

    const floor = floorFor(price, rules);
    replay.push({
      id: d.id,
      category: cat,
      marketId: d.marketId,
      decision: d.decision,
      at: asOfD.toISOString(),
      storedPp,
      scoreBefore,
      scoreAfter,
      bandBefore,
      bandAfter,
      sizeBefore,
      sizeAfter,
      setZeroed: ratio === 0,
      clampBounded: storedPp > 0 && scoreBefore === rules.regulatoryScoreCap,
      admittedBefore: scoreBefore >= floor,
      admittedAfter: scoreAfter >= floor,
      hardSkip: hasScoreIndependentHardSkip(d.risksJson),
    });
  }

  console.log(`-- 3. REPLAY of every edged decision at its OWN asOf (option A applied)`);
  console.log(
    `   population=non-demo DecisionJournal rows carrying a sentiment edge  level=one decision  ` +
      `clock=createdAt UTC  n=${decisions.length} (unparseable ${unparsed})`
  );
  console.log(
    `   replay fidelity: reproduces the stored edge within 0.15pp on ${verifyOk}/${verifyTried} decisions ` +
      `(parsed from reasonsJson; no row in the book carries sentimentDelta — see the note below); ` +
      `size function reproduces the stored size on ${sizeMatched}/${sizeChecked} copies`
  );

  const byCat2 = new Map<string, ReplayRow[]>();
  for (const r of replay) {
    const arr = byCat2.get(r.category) ?? [];
    arr.push(r);
    byCat2.set(r.category, arr);
  }
  console.log(
    `   ${"category".padEnd(20)}${"dec".padStart(5)}${"copies".padStart(7)}${"set zeroed".padStart(11)}` +
      `${"zeroed copies".padStart(14)}${"mean pp".padStart(9)}${"band chg".padStart(9)}` +
      `${"size before".padStart(12)}${"size after".padStart(12)}${"$ delta".padStart(10)}`
  );
  const catTotals: Array<Record<string, unknown>> = [];
  let totDec = 0;
  let totCopies = 0;
  let totZeroed = 0;
  let totZeroedCopies = 0;
  let totBand = 0;
  let totSizeBefore = 0;
  let totSizeAfter = 0;
  for (const [cat, rows] of [...byCat2.entries()].sort((x, y) => y[1].length - x[1].length)) {
    const copies = rows.filter((r) => r.decision === "paper_copy");
    const zeroed = rows.filter((r) => r.setZeroed);
    const zeroedCopies = zeroed.filter((r) => r.decision === "paper_copy");
    const bandChg = copies.filter((r) => r.bandBefore !== r.bandAfter);
    const sizeBefore = copies.reduce((a, r) => a + r.sizeBefore, 0);
    const sizeAfter = copies.reduce((a, r) => a + r.sizeAfter, 0);
    console.log(
      `   ${cat.padEnd(20)}${String(rows.length).padStart(5)}${String(copies.length).padStart(7)}` +
        `${String(zeroed.length).padStart(11)}${String(zeroedCopies.length).padStart(14)}` +
        `${(rows.reduce((a, r) => a + r.storedPp, 0) / rows.length).toFixed(2).padStart(9)}` +
        `${String(bandChg.length).padStart(9)}${usd(sizeBefore).padStart(12)}` +
        `${usd(sizeAfter).padStart(12)}${usd(sizeAfter - sizeBefore).padStart(10)}`
    );
    totDec += rows.length;
    totCopies += copies.length;
    totZeroed += zeroed.length;
    totZeroedCopies += zeroedCopies.length;
    totBand += bandChg.length;
    totSizeBefore += sizeBefore;
    totSizeAfter += sizeAfter;
    catTotals.push({
      category: cat,
      decisions: rows.length,
      copies: copies.length,
      setZeroedDecisions: zeroed.length,
      setZeroedCopies: zeroedCopies.length,
      meanPp: rows.reduce((a, r) => a + r.storedPp, 0) / rows.length,
      bandChanges: bandChg.length,
      sizeBefore: round1(sizeBefore * 100) / 100,
      sizeAfter: round1(sizeAfter * 100) / 100,
    });
  }
  console.log(
    `   ${"TOTAL".padEnd(20)}${String(totDec).padStart(5)}${String(totCopies).padStart(7)}` +
      `${String(totZeroed).padStart(11)}${String(totZeroedCopies).padStart(14)}${"".padStart(9)}` +
      `${String(totBand).padStart(9)}${usd(totSizeBefore).padStart(12)}${usd(totSizeAfter).padStart(12)}` +
      `${usd(totSizeAfter - totSizeBefore).padStart(10)}`
  );

  const lostAdmits = replay.filter((r) => r.admittedBefore && !r.admittedAfter);
  const gainedAdmits = replay.filter((r) => !r.admittedBefore && r.admittedAfter && !r.hardSkip);
  const clampBounded = replay.filter((r) => r.clampBounded);
  const sizesUp = replay.filter((r) => r.decision === "paper_copy" && r.sizeAfter > r.sizeBefore);
  const sizesDown = replay.filter((r) => r.decision === "paper_copy" && r.sizeAfter < r.sizeBefore);
  // At v73 the sweet spot and the ≥80 band both pay the same clip, so only a
  // base↔sweet transition moves dollars. Counting them together would overstate
  // the reach of this change by an order of magnitude.
  const paidBand = (b: string) => (b === "base" || b === "none" ? "curve" : "top");
  const bandChangesPaid = replay.filter(
    (r) => r.decision === "paper_copy" && paidBand(r.bandBefore) !== paidBand(r.bandAfter)
  );
  const copiesUp = replay.filter((r) => r.decision === "paper_copy" && r.sizeAfter > r.sizeBefore);
  const copiesDown = replay.filter((r) => r.decision === "paper_copy" && r.sizeAfter < r.sizeBefore);
  const verifiedSubset = replay.filter(
    (r) => r.decision === "paper_copy" && r.sizeAfter !== r.sizeBefore && !r.clampBounded
  );
  console.log(
    `\n   [REACH] ${totDec} decisions carried an edge; ${totCopies} became copies; ` +
      `${totZeroed} lost their ENTIRE set (option A silent) of which ${totZeroedCopies} were copies; ` +
      `${totBand} copies change score band, but only ${bandChangesPaid.length} change the clip that pays ` +
      `(base↔sweet; sweet↔high is cosmetic at v73: both $${rules.sweetSpotSizeUsd.toFixed(0)}); ` +
      `size ${usd(totSizeBefore)} → ${usd(totSizeAfter)} (${usd(totSizeAfter - totSizeBefore)}) on the STANDARD curve.`
  );
  console.log(
    `   [ADMISSION] ${lostAdmits.length} rows drop below their floor, ${gainedAdmits.length} rows cross it ` +
      `with no score-independent hard skip (leg-level blocks — C-200 blacklist, slug cap — are NOT visible ` +
      `here). ${clampBounded.length} rows sat exactly on the boost clamp (${rules.regulatoryScoreCap}), so ` +
      `their pre-edge score is a LOWER bound; at v73 that is harmless for size (sweet $${rules.sweetSpotSizeUsd.toFixed(0)} ` +
      `and ≥${rules.highScoreCapMin} $${rules.highScoreCapUsd.toFixed(0)} are the same clip), and the ` +
      `${verifiedSubset.length} rows whose size moves without ambiguity are the $ figure's real support.`
  );
  console.log(
    `   [DIRECTION] ${copiesUp.length} copies size UP, ${copiesDown.length} size DOWN (${sizesUp.length}/${sizesDown.length} ` +
      `across all decisions) — removing a constant edge is not a uniform cut: a constant NEGATIVE polarity ` +
      `was a uniform PENALTY, so dropping it raises the score of everything it touched.`
  );

  // ---------------- 4. SHADOW ----------------
  const abPath = "data/sentiment-ab.jsonl";
  const shadow: Array<Record<string, unknown>> = [];
  if (existsSync(abPath)) {
    const lines = readFileSync(abPath, "utf8").split("\n").filter((l) => l.trim().length > 0);
    type Ab = {
      source: string;
      rule_sentiment: number | null;
      local_sentiment: number | null;
    };
    const parsed: Ab[] = [];
    for (const l of lines) {
      try {
        const o = JSON.parse(l) as Ab;
        if (o && typeof o.source === "string") parsed.push(o);
      } catch {
        /* skip a torn line */
      }
    }
    const bySrc = new Map<string, Ab[]>();
    for (const p of parsed) {
      const arr = bySrc.get(p.source) ?? [];
      arr.push(p);
      bySrc.set(p.source, arr);
    }
    console.log(`\n-- 4. SHADOW (data/sentiment-ab.jsonl: keyword rules vs LOCAL_SENTIMENT_MODEL)`);
    console.log(
      `   population=${parsed.length} scored items  level=one item  clock=the file's own ts  ` +
        `NOT a decision input (shadow arm only)`
    );
    console.log(
      `   ${"source".padEnd(22)}${"items".padStart(7)}${"rule values".padStart(13)}${"local values".padStart(14)}` +
        `${"opposite sign".padStart(15)}  local value counts`
    );
    for (const [src, items] of [...bySrc.entries()].sort((a, b) => b[1].length - a[1].length)) {
      const ruleVals = new Set(items.map((i) => i.rule_sentiment).filter((v): v is number => v != null));
      const localVals = new Map<number, number>();
      for (const i of items) {
        if (i.local_sentiment == null) continue;
        localVals.set(i.local_sentiment, (localVals.get(i.local_sentiment) ?? 0) + 1);
      }
      let opposite = 0;
      for (const i of items) {
        if (i.rule_sentiment == null || i.local_sentiment == null) continue;
        if (Math.abs(i.local_sentiment) < T) continue;
        if (Math.sign(i.rule_sentiment) !== 0 && Math.sign(i.rule_sentiment) !== Math.sign(i.local_sentiment))
          opposite++;
      }
      const counts = [...localVals.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([v, c]) => `${v.toFixed(2)}×${c}`)
        .join(" ");
      console.log(
        `   ${src.padEnd(22)}${String(items.length).padStart(7)}${String(ruleVals.size).padStart(13)}` +
          `${String(localVals.size).padStart(14)}${String(opposite).padStart(15)}  ${counts}`
      );
      shadow.push({
        source: src,
        items: items.length,
        ruleDistinct: ruleVals.size,
        localDistinct: localVals.size,
        oppositeSign: opposite,
        localCounts: Object.fromEntries(localVals),
      });
    }
    const congress = bySrc.get("congress_gov_api") ?? [];
    const congressOpposite = (shadow.find((s) => s.source === "congress_gov_api")?.oppositeSign as number) ?? 0;
    console.log(
      `\n   [REFUTATION (d)] the card is refuted if the shadow finds >= 2 directions on the same items. ` +
        `congress_gov_api: ${new Set(congress.map((c) => c.rule_sentiment ?? 0)).size} rule value(s), ` +
        `${new Set(congress.map((c) => c.local_sentiment).filter((v) => v != null)).size} local value(s), ` +
        `${congressOpposite} items opinionated in the OPPOSITE direction to the rule score.`
    );
  } else {
    console.log(`\n-- 4. SHADOW  ${abPath} absent — refutation arm (d) NOT answered.`);
  }

  // ---------------- 5. OUTCOME ----------------
  type Leg = {
    category: string;
    marketId: string;
    at: string;
    zeroed: boolean;
    /** Sign of the edge as the leg received it: +1 = pushed toward this leg, -1 = against it. */
    edgeSign: number;
    wonMarket: boolean | null;
    wonPnl: boolean | null;
    price: number;
    settled: boolean;
  };
  const legs: Leg[] = [];
  const decisionById = new Map(decisions.map((d) => [d.id, d]));
  for (const r of replay) {
    if (r.decision !== "paper_copy") continue;
    const d = decisionById.get(r.id);
    for (const pt of d?.paperTrades ?? []) {
      const finalOutcome = pt.outcomeReviews?.[0]?.finalOutcome ?? null;
      legs.push({
        category: r.category,
        marketId: r.marketId,
        at: r.at,
        zeroed: r.setZeroed,
        edgeSign: r.storedPp > 0 ? 1 : r.storedPp < 0 ? -1 : 0,
        wonMarket: didOutcomeWin(pt.outcome, { winningLabel: finalOutcome }),
        wonPnl: pt.realizedPnl == null ? null : pt.realizedPnl > 0,
        price: pt.entryPrice,
        settled: pt.resolvedAt != null || pt.closedAt != null,
      });
    }
  }
  const medianTs = (xs: Leg[]) => {
    if (xs.length === 0) return "n/a";
    const t = xs.map((l) => new Date(l.at).getTime()).sort((a, b) => a - b);
    return new Date(t[Math.floor(t.length / 2)]).toISOString().slice(0, 10);
  };
  /** Leg-level bootstrap of the mean per-share outcome edge (anti-conservative:
   *  legs cluster on markets, so this understates the interval). */
  const bootEdge = (xs: Leg[]): [number, number] => {
    const vals = xs.filter((l) => l.wonMarket != null).map((l) => (l.wonMarket ? 1 - l.price : -l.price));
    if (vals.length === 0) return [0, 0];
    const means: number[] = [];
    for (let i = 0; i < 2000; i++) {
      let s = 0;
      for (let j = 0; j < vals.length; j++) s += vals[Math.floor(Math.random() * vals.length)];
      means.push(s / vals.length);
    }
    means.sort((a, b) => a - b);
    return [means[Math.floor(means.length * 0.025)], means[Math.floor(means.length * 0.975)]];
  };

  console.log(`\n-- 5. OUTCOME on copies (does the constant direction beat its own price?)`);
  console.log(
    `   two label arms, both printed: MARKET = didOutcomeWin(OutcomeReview.finalOutcome); ` +
      `PNL = realizedPnl>0. level=one leg; price=PaperTrade.entryPrice`
  );
  console.log(
    `   "edge removed" = option A silenced this leg's set at its own asOf (the cohort this change ` +
      `touches). "edge kept" is an EARLIER-ERA cohort, not a control — compare the median dates.`
  );
  const outcomeArms: Array<Record<string, unknown>> = [];
  for (const cat of [...new Set(legs.map((l) => l.category))]) {
    for (const zeroed of [true, false]) {
      const set = legs.filter((l) => l.category === cat && l.zeroed === zeroed);
      if (set.length === 0) continue;
      const mkt = set.filter((l) => l.wonMarket != null);
      const hits = mkt.filter((l) => l.wonMarket === true).length;
      const meanPrice = set.reduce((a, l) => a + l.price, 0) / set.length;
      const ci = wilson(hits, mkt.length);
      const pnl = set.filter((l) => l.wonPnl != null);
      const pnlHits = pnl.filter((l) => l.wonPnl === true).length;
      const edgePerShare =
        mkt.length === 0
          ? null
          : mkt.reduce((a, l) => a + (l.wonMarket ? 1 - l.price : -l.price), 0) / mkt.length;
      const bci = bootEdge(set);
      console.log(
        `   ${cat.padEnd(18)}${zeroed ? "edge removed" : "edge kept   "}  legs ${String(set.length).padStart(3)}` +
          ` (settled ${String(set.filter((l) => l.settled).length).padStart(3)}), markets ` +
          `${String(new Set(set.map((l) => l.marketId)).size).padStart(3)}, median ${medianTs(set)}  ` +
          `price ${meanPrice.toFixed(3)}  MARKET ${hits}/${mkt.length} = ${mkt.length ? pct(hits, mkt.length) : "n/a"} ` +
          `CI[${(ci[0] * 100).toFixed(0)},${(ci[1] * 100).toFixed(0)}]  ` +
          `edge/share ${edgePerShare == null ? "n/a" : usd(edgePerShare)} boot[${usd(bci[0])},${usd(bci[1])}]  ` +
          `PNL ${pnlHits}/${pnl.length}`
      );
      outcomeArms.push({
        category: cat,
        edgeRemoved: zeroed,
        legs: set.length,
        markets: new Set(set.map((l) => l.marketId)).size,
        medianDate: medianTs(set),
        settledLegs: set.filter((l) => l.settled).length,
        meanPrice,
        marketHits: hits,
        marketN: mkt.length,
        marketHitRate: mkt.length ? hits / mkt.length : null,
        wilson: ci,
        edgePerShare,
        edgePerShareBoot: bci,
        pnlHits,
        pnlN: pnl.length,
      });
    }
  }
  // The direction test. A constant edge cannot be tested within a category (every leg
  // gets the same number), but the SIGN is per-leg — the same constant pushes a YES leg
  // toward and a NO leg against. If the polarity carried information, the legs it pushed
  // toward must beat their price more than the legs it pushed against.
  console.log(
    `\n   [SIGN TEST] the edge's own direction, pooled over every leg whose set option A silences:`
  );
  const signRows: Array<Record<string, unknown>> = [];
  for (const [label, sig] of [
    ["pushed toward (+)", 1],
    ["pushed against (−)", -1],
  ] as Array<[string, number]>) {
    const set = legs.filter((l) => l.zeroed && l.edgeSign === sig);
    if (set.length === 0) continue;
    const mkt = set.filter((l) => l.wonMarket != null);
    const hits = mkt.filter((l) => l.wonMarket === true).length;
    const meanPrice = set.reduce((a, l) => a + l.price, 0) / set.length;
    const ci = wilson(hits, mkt.length);
    const pnl = set.filter((l) => l.wonPnl != null);
    const edge =
      mkt.length === 0 ? null : mkt.reduce((a, l) => a + (l.wonMarket ? 1 - l.price : -l.price), 0) / mkt.length;
    const bci = bootEdge(set);
    console.log(
      `   ${label.padEnd(20)}legs ${String(set.length).padStart(3)} (markets ` +
        `${String(new Set(set.map((l) => l.marketId)).size).padStart(2)})  price ${meanPrice.toFixed(3)}  ` +
        `MARKET ${hits}/${mkt.length} = ${mkt.length ? pct(hits, mkt.length) : "n/a"} ` +
        `CI[${(ci[0] * 100).toFixed(0)},${(ci[1] * 100).toFixed(0)}]  ` +
        `edge/share ${edge == null ? "n/a" : usd(edge)} boot[${usd(bci[0])},${usd(bci[1])}]  ` +
        `PNL ${pnl.filter((l) => l.wonPnl === true).length}/${pnl.length}`
    );
    signRows.push({
      label,
      legs: set.length,
      markets: new Set(set.map((l) => l.marketId)).size,
      meanPrice,
      marketHits: hits,
      marketN: mkt.length,
      edgePerShare: edge,
      edgePerShareBoot: bci,
    });
  }

  console.log(
    `   [CAVEAT] n is small and legs cluster on markets; the Wilson and bootstrap intervals treat legs ` +
      `as independent, so both are anti-conservative. Read the sign and the size, not the third decimal.`
  );

  if (JSON_OUT) {
    const out = {
      generatedAt: asOf.toISOString(),
      ruleSetVersion: version,
      windowDays: WINDOW_DAYS,
      basis: {
        population: "RegulatorySignal rows (all sources)",
        clock: "processedAt UTC",
        level: "one signal row (LIVE) / one distinct disclosure (A, A+B)",
        opinionatedThreshold: T,
        sizeBasis: "scoreTrade STANDARD curve; C-200 Kelly sizing bypasses it",
      },
      rules: {
        minCopyScore: rules.minCopyScore,
        longshotMinCopyScore: rules.longshotMinCopyScore,
        regulatoryScoreCap: rules.regulatoryScoreCap,
        sentimentScale: rules.sentimentScale,
        sweetSpotMinScore: rules.sweetSpotMinScore,
        highScoreCapMin: rules.highScoreCapMin,
        sweetSpotSizeUsd: rules.sweetSpotSizeUsd,
        highScoreCapUsd: rules.highScoreCapUsd,
        baseSizeUsd: rules.baseSizeUsd,
      },
      supply: supplyRows,
      arms: arms.map((a) => ({
        category: a.category,
        rows: a.rows,
        disclosures: a.disclosures,
        setPolarities: a.setPolarities,
        livePp: a.live ? a.live.delta * 100 : null,
        liveN: a.live?.n ?? null,
        aPp: a.a ? a.a.delta * 100 : null,
        bPp: a.b ? a.b.delta * 100 : null,
        abPp: a.ab ? a.ab.delta * 100 : null,
      })),
      replay: {
        decisions: totDec,
        copies: totCopies,
        unparsed,
        verifyTried,
        verifyOk,
        sizeChecked,
        sizeMatched,
        setZeroedDecisions: totZeroed,
        setZeroedCopies: totZeroedCopies,
        bandChanges: totBand,
        sizeBefore: round1(totSizeBefore * 100) / 100,
        sizeAfter: round1(totSizeAfter * 100) / 100,
        sizeDelta: round1((totSizeAfter - totSizeBefore) * 100) / 100,
        admittedLost: lostAdmits.length,
        admittedGained: gainedAdmits.length,
        clampBounded: clampBounded.length,
        sizesUp: sizesUp.length,
        sizesDown: sizesDown.length,
        byCategory: catTotals,
      },
      shadow,
      outcome: outcomeArms,
      signTest: signRows,
    };
    writeFileSync("data/sentiment-edge-dryrun.json", JSON.stringify(out, null, 2) + "\n");
    console.log(`\nwrote data/sentiment-edge-dryrun.json`);
  }
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
