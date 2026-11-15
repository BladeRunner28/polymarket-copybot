/**
 * research:source-supply-read — what does the sentiment layer's evidence set
 * actually contain, and does it contain a DIRECTION?
 *
 * READ-ONLY. Card `insidercat-source-audit` (2026-11-15). The card asks whether
 * a new source would add opinionated signals the three live sources miss. That
 * question has a prerequisite nobody had measured: what do the three live
 * sources supply today?
 *
 * Three arms, same window, same clock, same production code:
 *
 *   LIVE      aggregateSentimentForCategory(cat, 0.5) — exactly what
 *             scripts/score-trades.ts calls (7d window, |s| >= 0.3, minSignals 1).
 *   DEDUPED   the same aggregation over ONE row per distinct disclosure
 *             (buildEvidenceItems + aggregateEvidenceItems on dedupeByEvent).
 *   SIGNED    DEDUPED, minus every source that shows a single polarity value in
 *             that category. A source that can only ever print one direction has
 *             no direction to contribute; what survives is the evidence that
 *             could actually change the sign.
 *
 * BASES are printed with every number: population = non-demo RegulatorySignal
 * rows (the layer reads no demo rows), clock = processedAt UTC, level = one
 * signal row (LIVE) / one distinct disclosure (DEDUPED, SIGNED).
 *
 * Usage: npx tsx scripts/research-source-supply-read.ts [--days 7] [--json] [--self-test]
 */
import { prisma } from "../src/lib/db";
import {
  aggregateEvidenceItems,
  type AggregateResult,
} from "../src/lib/forecasting/index";
import { buildEvidenceItems } from "../src/lib/forecasting/sentiment";
import {
  DEFAULT_OPINIONATED_THRESHOLD,
  dedupeByEvent,
  eventKeyFor,
  polarityConcentration,
  supplyStats,
  type SupplyRow,
} from "../src/lib/research-source-supply";
import { writeFileSync } from "node:fs";

const args = process.argv.slice(2);
const JSON_OUT = args.includes("--json");
const SELF_TEST = args.includes("--self-test");
const daysIdx = args.indexOf("--days");
const WINDOW_DAYS = daysIdx >= 0 ? Number(args[daysIdx + 1]) : 7;
const PRIOR = 0.5;

const CATEGORIES = [
  "Crypto",
  "Tech/AI",
  "Defense/Geopolitics",
  "Healthcare",
  "Energy/Climate",
  "Finance",
  "Macro/Politics",
];

function pct(n: number, d: number): string {
  if (d === 0) return "n/a";
  return `${((100 * n) / d).toFixed(1)}%`;
}

function pp(delta: number): string {
  return `${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(2)}pp`;
}

function selfTest(): void {
  const T = (iso: string) => new Date(iso);
  const checks: Array<[string, boolean, string]> = [];

  // --- identity: same bill re-emitted three times is ONE event.
  const bill = (n: number, at: string, s = 0.5): SupplyRow => ({
    source: "congress_gov_api",
    sentimentScore: s,
    confidence: 0.7,
    processedAt: T(at),
    rawPayload: JSON.stringify({ type: "HR", number: String(n), title: "x" }),
  });
  const bills = [bill(1, "2026-11-01T00:00:00Z"), bill(1, "2026-11-02T00:00:00Z"), bill(2, "2026-11-03T00:00:00Z")];
  const db = dedupeByEvent(bills);
  checks.push(["bill identity merges re-emissions", db.length === 2, `got ${db.length}`]);
  checks.push([
    "dedupe keeps the LATEST processedAt",
    db[0].processedAt.toISOString() === "2026-11-02T00:00:00.000Z",
    db[0].processedAt.toISOString(),
  ]);

  // --- identity: two members trading the same ticker on the same day are TWO events.
  const trade = (member: string, ticker: string, at: string): SupplyRow => ({
    source: "quiver_congress_trade",
    sentimentScore: -0.8,
    confidence: 0.85,
    processedAt: T(at),
    rawPayload: JSON.stringify({
      BioGuideID: member,
      TransactionDate: "2026-11-01",
      Ticker: ticker,
      Transaction: "Sale (Partial)",
    }),
  });
  const trades = [trade("A1", "NVDA", "2026-11-02T00:00:00Z"), trade("B2", "NVDA", "2026-11-02T00:00:00Z")];
  checks.push(["distinct members are distinct events", dedupeByEvent(trades).length === 2, ""]);

  // --- identity: an unparseable payload is NOT merged with another one.
  const bad: SupplyRow[] = [
    { source: "congress_gov_api", sentimentScore: 0.5, confidence: 0.7, processedAt: T("2026-11-01T00:00:00Z"), rawPayload: "not json" },
    { source: "congress_gov_api", sentimentScore: 0.5, confidence: 0.7, processedAt: T("2026-11-02T00:00:00Z"), rawPayload: "also not json" },
  ];
  checks.push(["unparseable payloads stay separate", dedupeByEvent(bad).length === 2, ""]);
  checks.push(["eventKey prefixes the source scheme", eventKeyFor("congress_gov_api", JSON.stringify({ type: "S", number: "42" })) === "bill:S42", eventKeyFor("congress_gov_api", JSON.stringify({ type: "S", number: "42" }))]);

  // --- concentration: a constant set reports share 1 and one distinct value.
  const constant = polarityConcentration(bills);
  checks.push(["constant set: distinctValues 1", constant.distinctValues === 1, String(constant.distinctValues)]);
  checks.push(["constant set: modalShare 1", constant.modalShare === 1, String(constant.modalShare)]);

  // --- concentration: a mixed set does not.
  const mixed = polarityConcentration([
    { source: "s", sentimentScore: 0.5, confidence: 1, processedAt: T("2026-11-01T00:00:00Z") },
    { source: "s", sentimentScore: -0.5, confidence: 1, processedAt: T("2026-11-01T00:00:00Z") },
    { source: "s", sentimentScore: -0.5, confidence: 1, processedAt: T("2026-11-01T00:00:00Z") },
  ]);
  checks.push(["mixed set: distinctValues 2", mixed.distinctValues === 2, String(mixed.distinctValues)]);
  checks.push(["mixed set: modal is the majority sign", mixed.modal === -0.5 && mixed.modalShare === 2 / 3, `${mixed.modal}/${mixed.modalShare}`]);

  // --- stats: re-emission factor is rows/events, opinionated counted on both bases.
  const st = supplyStats(bills)[0];
  checks.push(["reEmission = rows/events", Math.abs(st.reEmission - 1.5) < 1e-9, String(st.reEmission)]);
  checks.push(["opinionated on both bases", st.opinionatedRows === 3 && st.opinionatedEvents === 2, `${st.opinionatedRows}/${st.opinionatedEvents}`]);

  // --- the aggregation arm: an empty set must produce no delta, and a one-value
  //     set must NOT flip sign when its rows are duplicated (rho already caps that).
  const one = aggregateEvidenceItems(buildEvidenceItems([bill(1, "2026-11-01T00:00:00Z")], new Date("2026-11-02T00:00:00Z")), PRIOR);
  const many = aggregateEvidenceItems(buildEvidenceItems(bills, new Date("2026-11-04T00:00:00Z")), PRIOR);
  checks.push(["one constant row gives a non-zero delta", one.delta > 0, String(one.delta)]);
  checks.push(["re-emission cannot flip the sign", many.delta > 0, String(many.delta)]);

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

  const asOf = new Date();
  const since = new Date(asOf.getTime() - WINDOW_DAYS * 86_400_000);

  console.log(
    `BASIS  population=RegulatorySignal rows (all sources; the layer reads no demo rows)  ` +
      `clock=processedAt UTC  level=one signal row  window=${WINDOW_DAYS}d to ${asOf.toISOString()}`
  );
  console.log(
    `       "opinionated" = |sentimentScore| >= ${DEFAULT_OPINIONATED_THRESHOLD} (module default)  prior=price=${PRIOR.toFixed(2)}\n`
  );

  // ---- ARM 0: what the source set is made of (all-time and in-window) ----
  const allRows = await prisma.regulatorySignal.findMany({
    select: { source: true, sentimentScore: true, confidence: true, processedAt: true, rawPayload: true },
  });
  const windowRows = allRows.filter((r) => r.processedAt >= since);

  const table = (rows: SupplyRow[], label: string) => {
    console.log(`-- ${label}: rows=${rows.length}  distinct disclosures=${supplyStats(rows).reduce((a, s) => a + s.distinctEvents, 0)}`);
    console.log(
      `   ${"source".padEnd(22)}${"rows".padStart(6)}${"events".padStart(8)}${"re-emit".padStart(9)}` +
        `${"opin".padStart(6)}${"op.ev".padStart(7)}${"polarities".padStart(11)}${"modal".padStart(7)}${"share".padStart(8)}  lastEmit`
    );
    for (const s of supplyStats(rows)) {
      console.log(
        `   ${s.source.padEnd(22)}${String(s.rows).padStart(6)}${String(s.distinctEvents).padStart(8)}` +
          `${s.reEmission.toFixed(2).padStart(9)}${String(s.opinionatedRows).padStart(6)}` +
          `${String(s.opinionatedEvents).padStart(7)}${String(s.distinctValues).padStart(11)}` +
          `${s.modal.toFixed(2).padStart(7)}${pct(s.modalShare, 1).padStart(8)}  ${s.lastEmit ?? "n/a"}`
      );
    }
  };
  table(allRows, "ALL-TIME");
  console.log();
  table(windowRows, `WINDOW ${WINDOW_DAYS}d`);
  console.log();

  // ---- ARMS 1-3 per category ----
  type CatRead = {
    category: string;
    live: AggregateResult | null;
    deduped: AggregateResult | null;
    signed: AggregateResult | null;
    rowsOpinionated: number;
    eventsOpinionated: number;
    signedEvents: number;
    constantSources: string[];
    signedSources: string[];
  };

  const reads: CatRead[] = [];
  for (const cat of CATEGORIES) {
    const rows = windowRows.filter(
      (r) => (r as unknown as { marketCategory?: string }).marketCategory === cat
    );
    // marketCategory was not selected above; re-read per category below.
    void rows;
    const catRows = await prisma.regulatorySignal.findMany({
      where: {
        marketCategory: cat,
        processedAt: { gte: since },
        OR: [
          { sentimentScore: { gte: DEFAULT_OPINIONATED_THRESHOLD } },
          { sentimentScore: { lte: -DEFAULT_OPINIONATED_THRESHOLD } },
        ],
      },
      orderBy: { processedAt: "asc" },
      select: { source: true, sentimentScore: true, confidence: true, processedAt: true, rawPayload: true },
    });

    const deduped = dedupeByEvent(catRows as SupplyRow[]);
    const perSource = supplyStats(catRows as SupplyRow[]);
    const constantSources = perSource.filter((s) => s.distinctValues === 1).map((s) => s.source);
    const signedRows = deduped.filter((r) => !constantSources.includes(r.source));

    const live = catRows.length
      ? aggregateEvidenceItems(buildEvidenceItems(catRows as SupplyRow[], asOf), PRIOR)
      : null;
    const ded = deduped.length
      ? aggregateEvidenceItems(buildEvidenceItems(deduped, asOf), PRIOR)
      : null;
    const sig = signedRows.length
      ? aggregateEvidenceItems(buildEvidenceItems(signedRows, asOf), PRIOR)
      : null;

    reads.push({
      category: cat,
      live,
      deduped: ded,
      signed: sig,
      rowsOpinionated: catRows.length,
      eventsOpinionated: deduped.length,
      signedEvents: signedRows.length,
      constantSources,
      signedSources: [...new Set(signedRows.map((r) => r.source))],
    });
  }

  console.log(`-- ARMS (prior ${PRIOR.toFixed(2)}; delta is YES-frame posterior − prior)`);
  console.log(
    `   ${"category".padEnd(22)}${"LIVE n/pp".padStart(16)}${"DEDUPED n/pp".padStart(16)}${"SIGNED n/pp".padStart(16)}  single-polarity sources dropped`
  );
  for (const r of reads) {
    const cell = (a: AggregateResult | null) =>
      a ? `${String(a.n).padStart(4)} ${pp(a.delta)}`.padStart(16) : "        none    ";
    console.log(
      `   ${r.category.padEnd(22)}${cell(r.live)}${cell(r.deduped)}${cell(r.signed)}  ` +
        (r.constantSources.length ? r.constantSources.join(",") : "—")
    );
  }

  const liveEdges = reads.filter((r) => r.live);
  const degenerate = liveEdges.filter((r) => r.signedEvents === 0);
  console.log(
    `\n[SUPPLY] categories with a live edge: ${liveEdges.length}/${CATEGORIES.length}; ` +
      `of those, ${degenerate.length} lose their ENTIRE set once single-polarity sources are removed` +
      (degenerate.length ? ` (${degenerate.map((r) => r.category).join(", ")})` : "")
  );

  await decisionsArm();


  if (JSON_OUT) {
    const out = {
      generatedAt: asOf.toISOString(),
      windowDays: WINDOW_DAYS,
      basis: {
        population: "RegulatorySignal rows (all sources)",
        clock: "processedAt UTC",
        level: "one signal row (live) / one distinct disclosure (deduped, signed)",
        opinionatedThreshold: DEFAULT_OPINIONATED_THRESHOLD,
        prior: PRIOR,
      },
      allTime: supplyStats(allRows as SupplyRow[]),
      window: supplyStats(windowRows as SupplyRow[]),
      categories: reads,
    };
    writeFileSync("data/research-source-supply.json", JSON.stringify(out, null, 2) + "\n");
    console.log("\nwrote data/research-source-supply.json");
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

/**
 * ARM 4 — how the live edge reached DECISIONS, and what removing a
 * single-polarity source would cost an admission.
 *
 * BASIS population = non-demo DecisionJournal rows whose reasonsJson carries the
 * "Sentiment evidence edge" line (pushed by src/lib/scoring/trade.ts whenever
 * |delta| >= 0.005, i.e. every decision the layer actually moved); category =
 * researchCategoryFor(observedTrade.marketQuestion) — the SAME mapping the
 * scorer used; level = one decision; clock = DecisionJournal.createdAt UTC.
 * The edge in that line is in probability points, and trade.ts adds
 * delta*sentimentScale = the same pp as copyScore points, so "pp" and "copyScore
 * points" are numerically equal.
 *
 * The ADMISSION floor is not the global one for every row: src/lib/scoring/trade.ts
 * admits a longshot (detectedPrice < longshotMaxPrice) on the relaxed
 * longshotMinCopyScore, and it CLAMPS any positively-boosted score down to
 * regulatoryScoreCap — which is why the boost can only ever admit inside the
 * longshot band and can only ever SIZE inside 70–79. This arm applies both rules
 * as they are written, so "admitted only because of the edge" and "band changed"
 * are counted on the live mechanics rather than on a naive 80 floor.
 */
async function decisionsArm() {
  const { researchCategoryFor } = await import("../src/lib/research-categories");
  const { getActiveRules } = await import("../src/lib/rules");
  const { rules, version } = await getActiveRules();
  const globalFloor = rules.minCopyScore;
  const longshotFloor = rules.longshotMinCopyScore > 0 ? rules.longshotMinCopyScore : globalFloor;
  const cap = rules.regulatoryScoreCap;
  const longshotMax = rules.longshotMaxPrice;

  const rows = await prisma.decisionJournal.findMany({
    where: { isDemo: false, reasonsJson: { contains: "Sentiment evidence edge" } },
    select: {
      decision: true,
      copyScore: true,
      reasonsJson: true,
      observedTrade: { select: { marketQuestion: true, marketCategory: true, detectedPrice: true } },
    },
  });

  type Acc = {
    n: number;
    copies: number;
    meanEdge: number;
    admittedOnlyByEdge: number;
    bandChanged: number;
  };
  const byCat = new Map<string, Acc>();
  let unparsed = 0;
  let copiesTotal = 0;
  let copiesAdmittedOnlyByEdge = 0;
  let copiesBandChanged = 0;

  for (const r of rows) {
    const m = /Sentiment evidence edge ([+-]?\d+(?:\.\d+)?)pp/.exec(r.reasonsJson);
    if (!m) {
      unparsed++;
      continue;
    }
    const edge = Number(m[1]);
    const cat =
      researchCategoryFor(r.observedTrade?.marketQuestion, r.observedTrade?.marketCategory) ??
      "unmapped";
    const a = byCat.get(cat) ?? { n: 0, copies: 0, meanEdge: 0, admittedOnlyByEdge: 0, bandChanged: 0 };
    a.n++;
    a.meanEdge += edge;

    if (r.decision === "paper_copy") {
      a.copies++;
      copiesTotal++;
      const price = r.observedTrade?.detectedPrice ?? 0.5;
      const floor = price < longshotMax ? longshotFloor : globalFloor;
      const withEdge = r.copyScore ?? 0;
      const without = withEdge - edge;

      // Admission: the stored score already includes the edge.
      if (withEdge >= floor && without < floor) {
        a.admittedOnlyByEdge++;
        copiesAdmittedOnlyByEdge++;
      }
      // Sizing band: 70–79 is the top-allocation sweet spot; >=80 the other top
      // allocation; 55–69 the base curve. Count a change of band.
      const band = (s: number) => (s >= 80 ? "top80" : s >= 70 ? "sweet" : s >= 55 ? "base" : "none");
      if (band(withEdge) !== band(without)) {
        a.bandChanged++;
        copiesBandChanged++;
      }
    }
    byCat.set(cat, a);
  }

  console.log(
    `\n-- ARM 4: the edge on decisions (RuleSet v${version}, sentimentScale=${rules.sentimentScale}, ` +
      `floors ${longshotFloor} longshot / ${globalFloor} global, boost clamp ${cap})`
  );
  console.log(
    `   ${"category".padEnd(22)}${"decisions".padStart(10)}${"copies".padStart(8)}${"mean pp".padStart(9)}` +
      `${"admitted only by edge".padStart(23)}${"band changed".padStart(14)}`
  );
  for (const [cat, a] of [...byCat.entries()].sort((x, y) => y[1].n - x[1].n)) {
    console.log(
      `   ${cat.padEnd(22)}${String(a.n).padStart(10)}${String(a.copies).padStart(8)}` +
        `${(a.meanEdge / a.n).toFixed(2).padStart(9)}${String(a.admittedOnlyByEdge).padStart(23)}` +
        `${String(a.bandChanged).padStart(14)}`
    );
  }
  console.log(
    `   [EDGE] ${rows.length} decisions carried a sentiment edge; ${copiesTotal} became paper copies; ` +
      `${copiesAdmittedOnlyByEdge} were admitted only because of the edge; ` +
      `${copiesBandChanged} changed sizing band. Unparseable: ${unparsed}.`
  );
}
