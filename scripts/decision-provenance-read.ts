/**
 * decision:provenance-read — does the journal now carry the numbers a decision was
 * made on, and what did the missing ones cost?
 *
 * READ-ONLY. Card `data2-per-decision-provenance` (2026-11-14). Three questions:
 *
 *   1. COVERAGE — of the rows written since the provenance epoch, how many carry
 *      sentimentDelta / priceAtDecision / alreadyDecidedAtEntry, and how many carry
 *      each horizon price? Pre-epoch rows are NULL by design (nothing is derivable
 *      from them, and inventing it is the defect the card is about).
 *   2. THE ALREADY-DECIDED CLASS — how big is it, by decision, and how many rows
 *      would an exclusion remove from the training population? That number is the
 *      input to a Lane A proposal; this script does NOT exclude anything.
 *   3. THE SENTIMENT JOIN — the card's gate asks for a probe that joins sentiment per
 *      decision. Before this, sentiment existed only as English in reasonsJson; the
 *      join is now a column read. Reported, joined to the realised label, no writes.
 *
 * Usage: npx tsx scripts/decision-provenance-read.ts [--json]
 */
import { prisma } from "../src/lib/db";
import { log, logError } from "../src/lib/redact";
import {
  ALREADY_DECIDED_PRICE,
  HORIZON_MAX_STALENESS_MS,
  horizonReads,
  isAlreadyDecided,
  pickHorizonPrice,
  parsePricesHistory,
} from "../src/lib/decision-provenance";

const JSON_OUT = process.argv.includes("--json");

function pct(n: number, d: number): string {
  if (d === 0) return "n/a";
  return `${((100 * n) / d).toFixed(1)}%`;
}

/** Self-test: the horizon rule and the decided rule, proven on constructed tape. */
function selfTest(): void {
  const T0 = Date.parse("2026-11-01T00:00:00Z");
  const pts = parsePricesHistory({
    history: [
      { t: T0 / 1000 + 300, p: 0.4 },
      { t: T0 / 1000 + 3600, p: 0.55 },
      { t: T0 / 1000 + 6 * 3600, p: 1 }, // settlement mark at the 6h horizon
      { t: T0 / 1000 + 24 * 3600 + 60, p: 0.2 }, // AFTER the 24h horizon: must not be used
    ],
  });
  const r = horizonReads(pts, T0);
  const checks: Array<[string, boolean]> = [
    ["1h takes the print at the horizon", r["1h"].price === 0.55 && r["1h"].reason === "ok"],
    ["6h refuses a settlement print", r["6h"].price === null && r["6h"].reason === "terminal_print"],
    ["24h never reads the print past the horizon", r["24h"].price === null && r["24h"].reason === "stale"],
    ["empty tape is no_path", pickHorizonPrice([], T0).reason === "no_path"],
    ["no earlier print is no_print", pickHorizonPrice([{ t: T0 / 1000 + 60, p: 0.5 }], T0).reason === "no_print"],
    [
      "a print older than the tolerance is stale",
      pickHorizonPrice([{ t: T0 / 1000, p: 0.5 }], T0 + HORIZON_MAX_STALENESS_MS + 1).reason === "stale",
    ],
    ["out-of-range prices are dropped, not clamped", parsePricesHistory({ history: [{ t: 1, p: 1.4 }] }).length === 0],
    [
      "unsorted payload is sorted before the pick",
      parsePricesHistory({ history: [{ t: 2, p: 0.9 }, { t: 1, p: 0.1 }] })[0].p === 0.1,
    ],
    ["0.995 is decided", isAlreadyDecided(ALREADY_DECIDED_PRICE)],
    ["0.994 is not decided", !isAlreadyDecided(0.994)],
    ["null is never decided", !isAlreadyDecided(null)],
  ];
  const failed = checks.filter(([, ok]) => !ok);
  if (failed.length) {
    logError(`[SELF-TEST] FAILED ${failed.length}/${checks.length}: ${failed.map(([n]) => n).join(" | ")}`);
    process.exit(1);
  }
  log(`[SELF-TEST] ${checks.length}/${checks.length} passed`);
}

async function main() {
  if (process.argv.includes("--self-test")) {
    selfTest();
    return;
  }

  // ---- epoch: the first row that carries any provenance value -------------------
  const firstStamped = await prisma.decisionJournal.findFirst({
    where: { OR: [{ sentimentDelta: { not: null } }, { priceAtDecision: { not: null } }, { alreadyDecidedAtEntry: true }] },
    orderBy: { createdAt: "asc" },
    select: { createdAt: true },
  });
  const epoch = firstStamped?.createdAt ?? null;

  const allTime = await prisma.decisionJournal.count({ where: { isDemo: false } });
  const postEpoch = epoch
    ? await prisma.decisionJournal.count({ where: { isDemo: false, createdAt: { gte: epoch } } })
    : 0;
  const stamped = epoch
    ? await prisma.decisionJournal.count({ where: { isDemo: false, createdAt: { gte: epoch }, priceAtDecision: { not: null } } })
    : 0;
  const sentimentStamped = epoch
    ? await prisma.decisionJournal.count({ where: { isDemo: false, createdAt: { gte: epoch }, sentimentDelta: { not: null } } })
    : 0;

  // ---- the already-decided class, two bases ------------------------------------
  // (a) the column, post-epoch; (b) the legacy proxy = the observed wallet's own
  // print price, which is what any historical measurement had to use.
  const byDecision = await prisma.decisionJournal.groupBy({
    by: ["decision"],
    where: { isDemo: false },
    _count: { _all: true },
  });
  const decidedRows: Array<{ decision: string; n: number; decided: number; proxyDecided: number }> = [];
  for (const row of byDecision) {
    const n = row._count._all;
    const decided = await prisma.decisionJournal.count({
      where: { isDemo: false, decision: row.decision, alreadyDecidedAtEntry: true },
    });
    const proxy = await prisma.decisionJournal.count({
      where: {
        isDemo: false,
        decision: row.decision,
        alreadyDecidedAtEntry: false,
        observedTrade: { detectedPrice: { gte: ALREADY_DECIDED_PRICE } },
      },
    });
    decidedRows.push({ decision: row.decision, n, decided, proxyDecided: proxy });
  }
  const totalDecided = decidedRows.reduce((s, r) => s + r.decided, 0);
  const totalProxy = decidedRows.reduce((s, r) => s + r.proxyDecided, 0);

  // What a training exclusion would actually remove, on the resolved population.
  const resolvedWithReview = await prisma.outcomeReview.count({ where: { finalOutcome: { not: null } } });
  const resolvedDecided = await prisma.outcomeReview.count({
    where: { finalOutcome: { not: null }, decision: { alreadyDecidedAtEntry: true } },
  });
  const resolvedDecidedProxy = await prisma.outcomeReview.count({
    where: {
      finalOutcome: { not: null },
      decision: { alreadyDecidedAtEntry: false, observedTrade: { detectedPrice: { gte: ALREADY_DECIDED_PRICE } } },
    },
  });

  // ---- horizon coverage ---------------------------------------------------------
  const horizonRows = await prisma.outcomeReview.count();
  const h1 = await prisma.outcomeReview.count({ where: { priceAfter1h: { not: null } } });
  const h6 = await prisma.outcomeReview.count({ where: { priceAfter6h: { not: null } } });
  const h24 = await prisma.outcomeReview.count({ where: { priceAfter24h: { not: null } } });

  // ---- the sentiment join (the card's gate) -------------------------------------
  const sentiRows = await prisma.decisionJournal.findMany({
    where: { isDemo: false, sentimentDelta: { not: null } },
    select: {
      decision: true,
      sentimentDelta: true,
      outcomeReviews: { select: { wasDecisionGood: true } },
    },
  });
  const sentiByDecision = new Map<string, { n: number; nonZero: number; withLabel: number; good: number }>();
  for (const r of sentiRows) {
    const cur = sentiByDecision.get(r.decision) ?? { n: 0, nonZero: 0, withLabel: 0, good: 0 };
    cur.n++;
    if ((r.sentimentDelta ?? 0) !== 0) cur.nonZero++;
    const label = r.outcomeReviews.find((o) => o.wasDecisionGood !== null);
    if (label) {
      cur.withLabel++;
      if (label.wasDecisionGood) cur.good++;
    }
    sentiByDecision.set(r.decision, cur);
  }

  const payload = {
    generatedAt: new Date().toISOString(),
    epoch: epoch?.toISOString() ?? null,
    basis: {
      population: "DecisionJournal isDemo=0 / OutcomeReview all rows",
      clock: "journal createdAt UTC for the epoch; nothing else is time-filtered",
      level: "one decision row",
    },
    coverage: {
      allTimeRows: allTime,
      postEpochRows: postEpoch,
      priceAtDecisionStamped: stamped,
      sentimentDeltaStamped: sentimentStamped,
    },
    alreadyDecided: {
      threshold: ALREADY_DECIDED_PRICE,
      byDecision: decidedRows,
      totalFlagged: totalDecided,
      legacyProxyFlagged: totalProxy,
      resolvedWithReview,
      resolvedDecidedFlagged: resolvedDecided,
      resolvedLegacyProxy: resolvedDecidedProxy,
    },
    horizons: { rows: horizonRows, priceAfter1h: h1, priceAfter6h: h6, priceAfter24h: h24 },
    sentimentJoin: [...sentiByDecision.entries()].map(([decision, v]) => ({ decision, ...v })),
  };

  if (JSON_OUT) {
    log(JSON.stringify(payload, null, 2));
    return;
  }

  log("=== decision provenance read (READ-ONLY) ===");
  log(
    `BASIS: population=DecisionJournal isDemo=0 (${allTime} rows) + OutcomeReview (${horizonRows} rows); ` +
      `level=one decision; clock=createdAt UTC; epoch=${epoch?.toISOString() ?? "NONE — no row carries provenance yet"}`
  );
  log(
    `COVERAGE post-epoch: ${postEpoch} rows, priceAtDecision ${stamped} (${pct(stamped, postEpoch)}), ` +
      `sentimentDelta ${sentimentStamped} (${pct(sentimentStamped, postEpoch)}). Pre-epoch rows are NULL by design.`
  );
  for (const r of decidedRows) {
    log(
      `ALREADY-DECIDED (>=${ALREADY_DECIDED_PRICE}) ${r.decision}: column ${r.decided}/${r.n} (${pct(r.decided, r.n)}); ` +
        `legacy proxy (wallet print price) ${r.proxyDecided}/${r.n} (${pct(r.proxyDecided, r.n)})`
    );
  }
  log(
    `EXCLUSION SURFACE: on the ${resolvedWithReview} labelled reviews, ${resolvedDecided} would be excluded on the column ` +
      `and ${resolvedDecidedProxy} more on the legacy proxy. NOT applied — that changes the training population (Lane A).`
  );
  log(
    `HORIZONS: priceAfter1h ${h1}/${horizonRows} (${pct(h1, horizonRows)}), 6h ${h6}, 24h ${h24}. ` +
      `NULL means the tape cannot say (stale > ${HORIZON_MAX_STALENESS_MS / 60000}min, no print, or a settlement mark).`
  );
  if (sentiByDecision.size === 0) {
    log("SENTIMENT JOIN: 0 rows carry sentimentDelta — the join cannot be exercised yet.");
  } else {
    for (const [decision, v] of sentiByDecision) {
      log(
        `SENTIMENT JOIN ${decision}: ${v.n} decisions with a numeric delta (${v.nonZero} non-zero); ` +
          `${v.withLabel} carry a realised label, ${v.good} judged good (${pct(v.good, v.withLabel)})`
      );
    }
  }
}

main()
  .catch((e) => {
    logError("decision:provenance-read FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
