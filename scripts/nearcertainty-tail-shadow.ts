/**
 * nearcertainty-tail-shadow — price the sub-0.05 candidates the near-certainty
 * clause refused. READ-ONLY. Evidence for roadmap card `nearcertainty-tail-shadow`.
 *
 * THE QUESTION
 *   `src/lib/scoring/trade.ts` hard-skips every entry priced above
 *   `rules.maxEntryPrice` (v71: 0.95) or below `1 - rules.maxEntryPrice` (0.05)
 *   with "price X near certainty — limited upside". The clause is symmetric, so
 *   the sub-0.05 arm refuses a token the market thinks will LOSE. Nobody had
 *   priced those refused legs until this instrument.
 *
 * PRE-REGISTERED DECISION RULE (written before the first run, 2026-11-05):
 *   The clause earns a Lane A relaxation proposal ONLY IF, on sole-blocker,
 *   label-aligned, live legs at the dust floor:
 *     (1) mean per-$1 return at mark + 1c is > 0,
 *     (2) ex-top-10 sum is > 0,
 *     (3) the market-clustered bootstrap CI on that mean excludes 0.
 *   Fail any one and this closes as "the rail was right", with NO proposal.
 *   The clause is Lane A either way: this instrument never proposes, it only
 *   measures, and any resulting change goes to the card as awaiting-approval.
 *
 * FOUR DEFECTS THE CARD WARNED ABOUT, EACH HANDLED EXPLICITLY
 *   1. POLLS. A refused market is re-journalled every scan (measured below: row
 *      count vs distinct market+outcome), so every rate is SIGNAL level.
 *   2. DUST. A 0.000–0.001 mark is a dead market at the tick floor, not a
 *      1-in-1000 longshot; its per-$1 "win" would be +999. `--floor` excludes it
 *      and the population at 0.005 / 0.01 / 0.02 is printed side by side.
 *   3. THE SIBLING-PRICE DEFECT (measured by `scripts/nearcert-mark-guard-read.py`,
 *      2026-10-29). The pipeline prices a token with `outcomePrices[0]` unless the
 *      label is literally "NO", so a decision on a market's SECOND token carries
 *      its sibling's price. A >=0.95 market read upside down looks exactly like a
 *      sub-0.05 longshot, and the clause refuses it from the other end. Those rows
 *      are NOT candidates; they are counted as `sibling` and priced at nothing.
 *   4. FILL. The C-200 sidecar books `entry = intent - 2c x reach` and p(fill)=1.
 *      On a 0.03 token a 2c credit is two thirds of the price, so the credit and
 *      the fill rate are printed as an EV sensitivity, never folded in silently.
 *
 * BASIS (stated, never implied):
 *   population = non-demo DecisionJournal rows whose risksJson carries the
 *                near-certainty clause AND whose operand is < 0.05
 *   level      = one market+outcome, priced at its FIRST live refusal
 *   clock      = decision createdAt in UTC; live = stamped before the market's
 *                venue closedTime (post-close rows are polls of settled markets)
 *   price      = the clause's own OPERAND (= the currentPrice score-trades.ts would
 *                have booked), label-alignment checked; the wallet's print is kept
 *                separate and the mark-vs-print divergence is printed
 *   settlement = the venue's own winning label on the closed market (never a PnL
 *                sign); fee 0, entry slippage printed per arm
 *
 *   npx tsx scripts/nearcertainty-tail-shadow.ts --days 30
 *   npx tsx scripts/nearcertainty-tail-shadow.ts --self-test
 */

import * as fs from "fs";
import { join } from "path";
import { createInterface } from "readline";
import { prisma } from "../src/lib/db";
import { didOutcomeWin } from "../src/lib/resolution";
import {
  NEARCERT_CHEAP_SIDE,
  NEARCERT_DUST_FLOOR,
  dedupeToSignal,
  evPerIntent,
  geometricMeanPerLeg,
  decisionLiveness,
  type Liveness,
  isSoleBlocker,
  legReturn,
  parseNearCertaintyOperand,
  parseVenueClock,
  priceBucket,
  riskEntries,
  summarizeCohort,
  topKShare,
  type PriceBucket,
} from "../src/lib/nearcertainty-tail";

const ROOT = join(__dirname, "..");
const OUT = join(ROOT, "data", "nearcertainty-tail-shadow.json");
const CACHE = join(ROOT, "data", "nearcertainty-tail-meta.json");
/** Another instrument's cache, read-only: same gamma payload fields (closed,
 *  closedTime, outcomes, outcomePrices) for 4,004 markets scored before
 *  2026-10-29; saves ~89 of ~113 fetches. Never written by this script. */
const SEED_CACHE = join(ROOT, "data", "nearcert-market-meta.json");
const TAPE = join(ROOT, "data", "c200-printthrough.jsonl");
const GAMMA = "https://gamma-api.polymarket.com";

function arg(name: string, def: string): string {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}
const flag = (name: string) => process.argv.includes(`--${name}`);

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const money = (v: number) => `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(2)}`;
const num = (v: number, d = 2) => (v < 0 ? "-" : "") + Math.abs(v).toFixed(d);

type Meta = {
  closed?: boolean;
  closedTime?: string | null;
  outcomePrices?: string;
  outcomes?: string;
  question?: string;
  error?: string;
};

async function getJson(url: string): Promise<unknown> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      const r = await fetch(url, {
        headers: { accept: "application/json", "user-agent": "copybot-research/0.1 (paper-trading-only)" },
        signal: AbortSignal.timeout(20_000),
      });
      if (r.status === 429 || r.status === 502 || r.status === 503) {
        await new Promise((res) => setTimeout(res, 1200 * (attempt + 1)));
        lastErr = new Error(`HTTP ${r.status}`);
        continue;
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } catch (e) {
      lastErr = e;
      await new Promise((res) => setTimeout(res, 600 * (attempt + 1)));
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error(String(lastErr));
}

async function fetchMeta(marketId: string): Promise<Meta> {
  try {
    const m = (await getJson(`${GAMMA}/markets/slug/${encodeURIComponent(marketId)}`)) as any;
    return {
      closed: m?.closed === true,
      closedTime: m?.closedTime ?? null,
      outcomePrices: typeof m?.outcomePrices === "string" ? m.outcomePrices : JSON.stringify(m?.outcomePrices ?? []),
      outcomes: typeof m?.outcomes === "string" ? m.outcomes : JSON.stringify(m?.outcomes ?? []),
      question: m?.question,
    };
  } catch (e) {
    return { error: e instanceof Error ? e.message.slice(0, 100) : String(e).slice(0, 100) };
  }
}

/** Token index the pipeline actually priced (mirrors adapters/polymarket.ts:695-696
 *  and the `outcome === "NO" ? noPrice : yesPrice` call sites). */
function pricedIndex(outcome: string): number {
  return String(outcome).trim().toUpperCase() === "NO" ? 1 : 0;
}

const norm = (s: string) => String(s ?? "").replace(/[^a-z0-9]/gi, "").toLowerCase();

/** Is the price on this row OUR token's price, or its sibling's? */
function labelAlignment(outcome: string, labels: string[]): "aligned" | "sibling" | "unknown" {
  if (!labels || labels.length < 2) return "unknown";
  const idx = labels.findIndex((l) => norm(l) === norm(outcome));
  if (idx < 0) return "unknown";
  return idx === pricedIndex(outcome) ? "aligned" : "sibling";
}

type Leg = {
  marketId: string;
  outcome: string;
  question: string;
  decidedAt: string;
  decidedAtMs: number;
  decision: string;
  operand: number;
  /** the wallet print the pipeline observed (ObservedTrade.detectedPrice) */
  printPrice: number | null;
  /** the price the pipeline would have BOOKED: its own currentPrice (= operand) */
  entry: number;
  soleBlocker: boolean;
  side: "cheap" | "rich";
  bucket: PriceBucket;
  /** journal rows this signal was polled on inside the window */
  polls: number;
  alignment: "aligned" | "sibling" | "unknown";
  live: boolean;
  liveness: Liveness;
  settlement: "venue" | "undetermined";
  won: boolean | null;
  ret: number | null;
  retSlip1: number | null;
  retSlip2: number | null;
};

type PricedLeg = Leg & { ret: number };

/** Deterministic market-clustered bootstrap on the mean per-$1 return. */
function bootstrapCI(
  legs: Array<{ marketId: string; ret: number }>,
  iterations = 2000,
  seed = 20261105
): { lo: number; hi: number; pNegative: number; markets: number } | null {
  const byMarket = new Map<string, number[]>();
  for (const l of legs) {
    const a = byMarket.get(l.marketId) ?? [];
    a.push(l.ret);
    byMarket.set(l.marketId, a);
  }
  const clusters = [...byMarket.values()];
  if (clusters.length < 3) return null;
  let s = seed >>> 0;
  const rnd = () => {
    s ^= s << 13;
    s ^= s >>> 17;
    s ^= s << 5;
    return (s >>> 0) / 4294967296;
  };
  const means: number[] = [];
  for (let it = 0; it < iterations; it++) {
    let sum = 0;
    let n = 0;
    for (let k = 0; k < clusters.length; k++) {
      const c = clusters[Math.floor(rnd() * clusters.length)];
      for (const v of c) {
        sum += v;
        n++;
      }
    }
    means.push(sum / n);
  }
  means.sort((a, b) => a - b);
  return {
    lo: means[Math.floor(iterations * 0.025)],
    hi: means[Math.floor(iterations * 0.975)],
    pNegative: means.filter((m) => m <= 0).length / iterations,
    markets: clusters.length,
  };
}

/** Measured reach of the flat 2c level in the closest band the tape actually has.
 *  The sub-0.05 band itself has ZERO legs (min intent price printed), so its reach
 *  is unmeasured by construction — this is an UPPER BOUND borrowed from <0.10. */
async function tapeReach(): Promise<{ reach: number; n: number; total: number; minIntent: number } | null> {
  if (!fs.existsSync(TAPE)) return null;
  const rl = createInterface({ input: fs.createReadStream(TAPE), crlfDelay: Infinity });
  let n = 0;
  let reached = 0;
  let total = 0;
  let minIntent = Infinity;
  for await (const line of rl) {
    if (!line.trim()) continue;
    let o: any;
    try {
      o = JSON.parse(line);
    } catch {
      continue;
    }
    for (const leg of o?.legs ?? []) {
      if (typeof leg?.intentPrice !== "number" || leg?.reached5 === null || leg?.reached5 === undefined) continue;
      total++;
      if (leg.intentPrice < minIntent) minIntent = leg.intentPrice;
      if (leg.intentPrice < 0.1) {
        n++;
        if (leg.reached5 === true) reached++;
      }
    }
  }
  if (!n) return null;
  return { reach: reached / n, n, total, minIntent: Number.isFinite(minIntent) ? minIntent : 0 };
}

function block(title: string, s: ReturnType<typeof summarizeCohort>) {
  const ex10 = s.n >= 10 ? money(s.exTop10Sum).padStart(9) : "n<10: n/a".padStart(9);
  console.log(
    `  ${title.padEnd(24)} n=${String(s.n).padStart(3)}  win ${pct(s.winRate).padStart(6)}  ` +
      `need ${pct(s.breakevenWinRate).padStart(6)}  mean ${money(s.mean).padStart(8)}  med ${money(s.median).padStart(7)}  ` +
      `trim ${money(s.trimmedMean).padStart(8)}  ex10 ${ex10}  geom ${num(
        s.geometricMean ?? 0,
        3
      ).padStart(7)}`
  );
}

async function main() {
  const days = Number(arg("days", "30"));
  const floors = [NEARCERT_DUST_FLOOR, 0.01, 0.02];
  const since = new Date(Date.now() - days * 86_400_000);

  const rows = await prisma.decisionJournal.findMany({
    where: { isDemo: false, createdAt: { gte: since }, risksJson: { contains: "near certainty" } },
    select: {
      createdAt: true,
      risksJson: true,
      decision: true,
      ruleSetVersion: true,
      observedTrade: {
        select: {
          marketId: true,
          marketQuestion: true,
          outcome: true,
          side: true,
          detectedPrice: true,
          walletAddress: true,
          isDemo: true,
        },
      },
    },
    orderBy: { createdAt: "asc" },
  });

  // BOTH arms of the symmetric clause: the cheap arm is the card's population,
  // the rich arm (operand > 0.95) is its NEGATIVE CONTROL — a clause that refuses
  // near-certain WINNERS must still price them as winners, or the settlement path
  // is broken and "every refused leg lost" would be a property of the instrument.
  const nearRows = rows.filter((r) => {
    const op = parseNearCertaintyOperand(r.risksJson);
    if (op === null || r.observedTrade?.isDemo !== false) return false;
    return op < NEARCERT_CHEAP_SIDE || op > 1 - NEARCERT_CHEAP_SIDE;
  });
  const cheap = nearRows.filter((r) => (parseNearCertaintyOperand(r.risksJson) as number) < NEARCERT_CHEAP_SIDE);

  const marketIds = [...new Set(nearRows.map((r) => r.observedTrade?.marketId ?? "").filter((m) => m))];
  const meta: Record<string, Meta> = {};
  for (const f of [SEED_CACHE, CACHE]) {
    if (!fs.existsSync(f)) continue;
    try {
      Object.assign(meta, JSON.parse(fs.readFileSync(f, "utf8")));
    } catch {
      /* a corrupt cache must not stop the read */
    }
  }
  const missing = marketIds.filter((m) => !meta[m]);
  if (!flag("no-fetch") && missing.length) {
    const queue = [...missing];
    let done = 0;
    // Flush every 25 fetches: a killed run (a 90-day window is ~2,100 markets and
    // WILL outlive a cron slot) must not throw away the markets it already priced.
    const flush = () => fs.writeFileSync(CACHE, JSON.stringify(meta, null, 1));
    const workers = Array.from({ length: 6 }, async () => {
      for (;;) {
        const m = queue.shift();
        if (!m) return;
        meta[m] = await fetchMeta(m);
        if (++done % 25 === 0) flush();
      }
    });
    await Promise.all(workers);
    flush();
  }

  const legs: Leg[] = [];
  let unknownClock = 0;
  let noMarketId = 0;
  let undetermined = 0;
  for (const r of nearRows) {
    const ot = r.observedTrade;
    const marketId = ot?.marketId ?? "";
    if (!marketId) {
      if ((parseNearCertaintyOperand(r.risksJson) as number) < NEARCERT_CHEAP_SIDE) noMarketId++;
      continue;
    }
    const mm = meta[marketId] ?? {};
    const labels: string[] = (() => {
      try {
        return (JSON.parse(mm.outcomes ?? "[]") as unknown[]).map(String);
      } catch {
        return [];
      }
    })();
    const prices: number[] = (() => {
      try {
        return (JSON.parse(mm.outcomePrices ?? "[]") as unknown[]).map(Number);
      } catch {
        return [];
      }
    })();
    const liveness = decisionLiveness(r.createdAt.getTime(), mm.closed, mm.closedTime);
    if (liveness === "unknown") unknownClock++;
    const alignment = labelAlignment(ot?.outcome ?? "", labels);
    // ENTRY = the clause's own operand. score-trades.ts:432 starts from
    // `t.detectedPrice` and overrides it with the fetched market price, so the
    // operand IS the price a copy would have been booked at; detectedPrice is kept
    // only as the PRINT (the last real trade), never mixed into the same arm.
    const operand = parseNearCertaintyOperand(r.risksJson) as number;
    const entry = operand;
    const printPrice =
      typeof ot?.detectedPrice === "number" && Number.isFinite(ot.detectedPrice) ? ot.detectedPrice : null;

    // Settlement: the venue's own winning label, never a PnL sign.
    let won: boolean | null = null;
    if (mm.closed === true && labels.length && prices.length === labels.length) {
      let best = 0;
      for (let i = 1; i < prices.length; i++) if (prices[i] > prices[best]) best = i;
      const winningLabel = prices[best] > 0.5 ? labels[best] : undefined;
      const w = didOutcomeWin(ot?.outcome, { winningLabel });
      won = w === null ? null : w;
    }
    const ret = won === null ? null : legReturn(entry, won);
    if (won === null) undetermined++;

    legs.push({
      marketId,
      outcome: ot?.outcome ?? "",
      question: ot?.marketQuestion ?? "",
      decidedAt: r.createdAt.toISOString(),
      decidedAtMs: r.createdAt.getTime(),
      decision: r.decision,
      operand,
      printPrice,
      entry,
      soleBlocker: isSoleBlocker(riskEntries(r.risksJson)),
      side: entry < NEARCERT_CHEAP_SIDE ? "cheap" : "rich",
      bucket: priceBucket(entry),
      polls: 1,
      alignment,
      live: liveness === "live",
      liveness,
      settlement: won === null ? "undetermined" : "venue",
      won,
      ret,
      retSlip1: won === null ? null : legReturn(entry + 0.01, won),
      retSlip2: won === null ? null : legReturn(entry + 0.02, won),
    });
  }

  // --- populations -------------------------------------------------------
  const allLive = legs.filter((l) => l.live === true);
  const liveLegs = allLive.filter((l) => l.side === "cheap");
  const controlLegs = allLive.filter((l) => l.side === "rich");
  const deduped = dedupeToSignal(liveLegs);
  const control = dedupeToSignal(controlLegs);
  const signalLive = deduped.legs;
  {
    const counts = new Map<string, number>();
    for (const l of liveLegs) {
      const k = `${l.marketId}\u0000${l.outcome}`;
      counts.set(k, (counts.get(k) ?? 0) + 1);
    }
    for (const l of signalLive) l.polls = counts.get(`${l.marketId}\u0000${l.outcome}`) ?? 1;
  }
  const alignedLive = signalLive.filter((l) => l.alignment === "aligned");
  // CONTROL population is settlement-only: liveness is irrelevant to the question
  // "does the label path read a winner as a winner", so the rich arm is taken over
  // EVERY row, live or polled after the close. That is what gives it power (n≈200
  // rather than 7) — a control too small to fail is not a control.
  const controlAll = dedupeToSignal(legs.filter((l) => l.side === "rich")).legs;
  const controlAligned = controlAll.filter((l) => l.alignment === "aligned");
  const cheapPost = dedupeToSignal(legs.filter((l) => l.side === "cheap" && !l.live)).legs.filter(
    (l) => l.alignment === "aligned"
  );
  const soleAligned = alignedLive.filter((l) => l.soleBlocker);

  const priced = (xs: Leg[], floor: number): PricedLeg[] =>
    xs.filter((l) => l.ret !== null && l.entry >= floor && Number.isFinite(l.entry)) as PricedLeg[];

  const cohorts = (floor: number) => {
    const a = priced(alignedLive, floor);
    const s = priced(soleAligned, floor);
    return {
      aligned: a,
      sole: s,
      byBucket: (["0.005-0.02", "0.02-0.05"] as PriceBucket[]).map((b) => ({
        bucket: b,
        legs: a.filter((l) => l.bucket === b),
      })),
    };
  };
  const primary = cohorts(NEARCERT_DUST_FLOOR);
  const alignedLivePriced = priced(alignedLive, 0);
  const controlPriced = priced(controlAligned, 0);
  const ci = bootstrapCI(primary.sole.map((l) => ({ marketId: l.marketId, ret: l.ret })));
  const reach = await tapeReach();

  const alignedRows = liveLegs.filter((l) => l.alignment === "aligned").length;
  const head = summarizeCohort(primary.sole.map((l) => ({ entry: l.entry, ret: l.ret })));
  const s1 = summarizeCohort(primary.sole.map((l) => ({ entry: l.entry + 0.01, ret: l.retSlip1 as number })));
  const s2 = summarizeCohort(primary.sole.map((l) => ({ entry: l.entry + 0.02, ret: l.retSlip2 as number })));

  // CONSERVATIVE ARM: never claim a cheaper entry than a real print in the same
  // market. A 0.02 mark on a market whose last print was 0.54 is not a 50x
  // longshot, it is a mark nobody traded at (the card's "thinnest marks").
  const consEntry = (l: PricedLeg) => Math.max(l.entry, l.printPrice ?? 0);
  const cons = primary.sole.map((l) => ({ entry: consEntry(l), ret: legReturn(consEntry(l), l.won as boolean) as number }));
  const consMean = summarizeCohort(cons).mean;
  const divergent = alignedLivePriced.filter((l) => l.printPrice !== null && Math.abs(l.entry - (l.printPrice as number)) > 0.02);
  const absDiffs = alignedLivePriced
    .filter((l) => l.printPrice !== null)
    .map((l) => Math.abs(l.entry - (l.printPrice as number)))
    .sort((a, b) => a - b);

  console.log(
    `near-certainty sub-0.05 tail, last ${days}d (${since.toISOString().slice(0, 10)} -> ${new Date()
      .toISOString()
      .slice(0, 19)}Z)`
  );
  console.log(
    `BASIS population=non-demo journal skips carrying the near-certainty clause with operand<${NEARCERT_CHEAP_SIDE} | ` +
      `level=1 market+outcome (first live refusal) | clock=decision createdAt UTC | price=clause operand, label-checked | settlement=venue label`
  );
  console.log(
    `ROWS cheap-side ${cheap.length} (all near-certainty rows in window ${rows.length}) | no marketId ${noMarketId} -> unpriced`
  );
  const cheapLegs = legs.filter((l) => l.side === "cheap");
  console.log(
    `CLOCK (cheap arm): live ${cheapLegs.filter((l) => l.liveness === "live").length} | post-close ${
      cheapLegs.filter((l) => l.liveness === "post-close").length
    } | clock unknown ${cheapLegs.filter((l) => l.liveness === "unknown").length}`
  );
  console.log(
    `LABEL POSITION (live rows): aligned ${alignedRows} | sibling-priced ${
      liveLegs.filter((l) => l.alignment === "sibling").length
    } (NOT candidates — a >=0.95 market read upside down) | unknown ${
      liveLegs.filter((l) => l.alignment === "unknown").length
    }`
  );
  const ctrlPricedAny = controlAligned.filter((l) => l.won !== null);
  const ctrlWin = ctrlPricedAny.length ? ctrlPricedAny.filter((l) => l.won === true).length / ctrlPricedAny.length : 0;
  const postPricedAny = cheapPost.filter((l) => l.won !== null);
  const postWin = postPricedAny.length ? postPricedAny.filter((l) => l.won === true).length / postPricedAny.length : 0;
  const ctrlOk = ctrlPricedAny.length >= 10 && ctrlWin > 0.85;
  console.log(
    `CONTROL (rich arm >0.95, all settled): ${ctrlPricedAny.length} legs, win ${pct(ctrlWin)} — must read ~95%; ` +
      `${ctrlOk ? "settlement path DISCRIMINATES (a winner is read as a winner)" : "CONTROL FAILED — the cheap-arm result is an artifact, do not read it"}`
  );
  console.log(
    `CONTROL (cheap arm, post-close polls only): ${postPricedAny.length} legs, win ${pct(postWin)} — must read ~0% ` +
      `(these are settled markets being re-polled; it is where the 0.000 marks live)`
  );
  console.log(
    `POLL INFLATION: aligned live rows ${alignedRows} -> ${alignedLive.length} signal legs (${(
      alignedRows / Math.max(1, alignedLive.length)
    ).toFixed(1)}x); all live rows ${deduped.rows} -> ${signalLive.length} (${deduped.inflation.toFixed(1)}x)`
  );
  const awaiting = alignedLive.filter((l) => l.ret === null);
  console.log(
    `PRICED: ${alignedLive.filter((l) => l.ret !== null).length}/${alignedLive.length} aligned live legs to venue settlement ` +
      `(${awaiting.length} AWAITING settlement — unresolved markets, never counted as losses)`
  );
  if (awaiting.length) {
    const top = [...awaiting].sort((a, b) => b.polls - a.polls).slice(0, 4);
    console.log(
      `  awaiting: ${top
        .map((l) => `${l.marketId.slice(0, 34)} p=${l.entry.toFixed(4)} polls=${l.polls}`)
        .join(" | ")}`
    );
  }
  console.log("");
  for (const f of floors) {
    const c = cohorts(f);
    console.log(`DUST FLOOR ${f}  (admitted: aligned ${c.aligned.length}, sole-blocker ${c.sole.length})`);
    block("aligned live", summarizeCohort(c.aligned));
    block("sole-blocker", summarizeCohort(c.sole));
    for (const b of c.byBucket) block(`  ${b.bucket}`, summarizeCohort(b.legs));
    console.log("");
  }
  console.log(
    `SLIPPAGE on sole-blocker @floor ${NEARCERT_DUST_FLOOR}: mark ${money(head.mean)} | +1c ${money(s1.mean)} | +2c ${money(
      s2.mean
    )} | at max(mark,last print) ${money(consMean)} (mean per $1 staked, held to settlement)`
  );
  console.log(
    `MARK vs PRINT (aligned live legs, n=${absDiffs.length}): median |mark-print| ${absDiffs.length ? absDiffs[absDiffs.length >> 1].toFixed(3) : "n/a"} | ` +
      `${divergent.length} legs differ by >0.02 (${pct(absDiffs.length ? divergent.length / absDiffs.length : 0)}) — a mark with no print is not an entry`
  );
  if (ci) {
    console.log(
      `BOOTSTRAP market-clustered (${ci.markets} markets, 2000 draws): mean ${money(head.mean)} CI [${money(ci.lo)}, ${money(
        ci.hi
      )}]  P(mean<=0) ${pct(ci.pNegative)}`
    );
  } else {
    console.log(`BOOTSTRAP: not computable (<3 markets)`);
  }
  console.log("");
  if (reach) {
    console.log(
      `FILL BASIS: print-through tape ${reach.total} analysable legs, min intent price ${reach.minIntent.toFixed(
        3
      )} => the sub-0.05 band has ZERO tape legs, so its reach is unmeasured by construction`
    );
    console.log(
      `  nearest measured band <0.10: reach-at-flat-2c within 5m ${pct(reach.reach)} (${Math.round(reach.reach * reach.n)}/${
        reach.n
      }) — an UPPER BOUND, not a fill claim`
    );
    console.log(
      `  EV per intent @mark (taker, reach~1) ${money(head.mean)} | at the sidecar's 2c credit (reach ${pct(
        reach.reach
      )}) ${money(evPerIntent(reach.reach, s2.mean))}`
    );
  }
  console.log("");
  const verdict =
    head.n === 0
      ? "NO POPULATION — nothing to price"
      : head.n >= 10 && s1.mean > 0 && head.exTop10Sum > 0 && ci !== null && ci.lo > 0
      ? "PROPOSAL-WORTHY: all pre-registered conditions met — prepare a Lane A ask (NOT applied)"
      : "REFUSED CORRECTLY: at least one pre-registered condition failed — no proposal";
  console.log(`VERDICT ${verdict}`);
  console.log(
    `  conditions: n>=10 ${head.n >= 10} (n=${head.n}) | mean@+1c>0 ${s1.mean > 0} (${money(s1.mean)}) | ex-top-10>0 ${
      head.exTop10Sum > 0
    } (${money(head.exTop10Sum)}) | CI-lo>0 ${ci ? money(ci.lo) : "n/a"}`
  );
  console.log(
    `  top-5 winners carry ${pct(head.top5ShareOfWins)} of all positive return; win rate ${pct(
      head.winRate
    )} vs breakeven ${pct(head.breakevenWinRate)}`
  );

  fs.writeFileSync(
    OUT,
    JSON.stringify(
      {
        generatedAt: new Date().toISOString(),
        card: "nearcertainty-tail-shadow",
        basis: {
          population: `non-demo DecisionJournal rows carrying the near-certainty clause with operand < ${NEARCERT_CHEAP_SIDE}`,
          level: "one market+outcome, priced at its first live refusal",
          clock: "decision createdAt UTC; live = before the venue closedTime",
          price: "the clause's own operand (the currentPrice score-trades would have booked), label-alignment checked; print kept separate",
          settlement: "venue winning label on the closed market; fee 0; slippage arms printed",
        },
        window: { days, since: since.toISOString(), until: new Date().toISOString() },
        counts: {
          rows: rows.length,
          cheapRows: cheap.length,
          liveRows: liveLegs.length,
          noMarketId,
          unknownClock,
          alignment: {
            aligned: alignedRows,
            sibling: liveLegs.filter((l) => l.alignment === "sibling").length,
            unknown: liveLegs.filter((l) => l.alignment === "unknown").length,
          },
          pollInflation: deduped.inflation,
          alignedPollInflation: alignedRows / Math.max(1, alignedLive.length),
          awaitingSettlement: awaiting.length,
          control: { richSettled: ctrlPricedAny.length, richWinRate: ctrlWin, pass: ctrlOk, cheapPostSettled: postPricedAny.length, cheapPostWinRate: postWin },
          undetermined,
        },
        floors: Object.fromEntries(
          floors.map((f) => {
            const c = cohorts(f);
            return [
              String(f),
              {
                aligned: summarizeCohort(c.aligned),
                soleBlocker: summarizeCohort(c.sole),
                byBucket: Object.fromEntries(c.byBucket.map((b) => [b.bucket, summarizeCohort(b.legs)])),
              },
            ];
          })
        ),
        markVsPrint: {
          n: absDiffs.length,
          medianAbsDiff: absDiffs.length ? absDiffs[absDiffs.length >> 1] : null,
          beyond2c: divergent.length,
        },
        slippage: { mark: head, plus1c: s1, plus2c: s2, conservativeMean: consMean },
        bootstrap: ci,
        fill: reach
          ? { ...reach, band: "<0.10", metric: "reached5 (best ask at/below the flat 2c level within 5m)" }
          : null,
        verdict,
        legs: signalLive,
      },
      null,
      1
    )
  );
  console.log(`wrote ${OUT}`);
}

async function selfTest() {
  // The probe must be able to FAIL. Each case is a defect this instrument exists
  // to catch; if any stops being caught, exit 1.
  const cases: Array<[string, boolean]> = [
    [
      "operand parses",
      parseNearCertaintyOperand('["price 0.012 near certainty (band 0.05–0.95) — limited upside"]') === 0.012,
    ],
    ["operand absent", parseNearCertaintyOperand('["price drifted 0.390 since entry"]') === null],
    ["sole blocker true", isSoleBlocker(["price 0.012 near certainty (band 0.05–0.95) — limited upside"])],
    [
      "sole blocker false when co-blocked",
      !isSoleBlocker([
        "price drifted 0.390 since entry > max 0.15 (too late)",
        "price 0.012 near certainty (band 0.05–0.95) — limited upside",
      ]),
    ],
    ["dust bucket", priceBucket(0.001) === "floor"],
    ["half-cent is not dust", priceBucket(0.005) === "0.005-0.02"],
    ["sibling detected", labelAlignment("VITALITY", ["9Z", "VITALITY"]) === "sibling"],
    ["aligned detected", labelAlignment("9Z", ["9Z", "VITALITY"]) === "aligned"],
    ["NO is priced at index 1", labelAlignment("NO", ["Yes", "No"]) === "aligned"],
    ["YES on a No-first market is sibling", labelAlignment("YES", ["No", "Yes"]) === "sibling"],
    [
      "post-close recognised",
      decisionLiveness(Date.parse("2026-10-16T00:00:00Z"), true, "2026-10-15 21:00:00+00") === "post-close",
    ],
    ["open market is live even with no close time", decisionLiveness(Date.now(), false, null) === "live"],
    ["closed market with no clock is unknown, never live", decisionLiveness(Date.now(), true, null) === "unknown"],
    [
      "venue clock with microseconds parses",
      parseVenueClock("2026-10-20 21:50:22.228128+00") === Date.parse("2026-10-20T21:50:22.228Z"),
    ],
    ["dust entry unpriced", legReturn(0, true) === null],
    ["one wipe-out is a -1 geometric leg", geometricMeanPerLeg([30, -1]) === -1],
    ["venue clock +00 offset parses", parseVenueClock("2026-10-15 21:00:00+00") === Date.parse("2026-10-15T21:00:00Z")],
    ["unparseable clock is null, not live", parseVenueClock("not-a-date") === null],
    ["garbage risksJson is no blocker", isSoleBlocker(riskEntries("{not json")) === false],
    ["top-5 share is 100% on one winner", topKShare([5, -1, -1], 5) === 1],
  ];
  const failed = cases.filter(([, ok]) => !ok).map(([name]) => name);
  for (const [name, ok] of cases) console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}`);
  if (failed.length) {
    console.error(`SELF-TEST RED: ${failed.length} case(s) not caught: ${failed.join(", ")}`);
    process.exit(1);
  }
  console.log(`SELF-TEST GREEN (${cases.length} cases)`);
}

(flag("self-test") ? selfTest() : main())
  .catch((e) => {
    console.error(`FAILED: ${e instanceof Error ? e.stack ?? e.message : String(e)}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
