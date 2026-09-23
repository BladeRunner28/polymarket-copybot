/**
 * edge-copy-cost — READ-ONLY: our EDGE and the measured COST OF COPYING, always
 * printed as a pair (roadmap card `polycopy-edge-cost-pair`, 2026-09-23).
 *
 * The daily report carries the same two numbers (src/lib/copy-cost.ts →
 * src/lib/report.ts); this script is the reviewer's re-runnable form, one line
 * per lane plus the ALL-LEGS variant that reconciles with the card's baseline.
 *
 * Definitions (see src/lib/copy-cost.ts for the full rationale):
 *   edge         = SUM(realizedPnl) / SUM(simulatedPositionSize) on settled legs
 *                  (status closed|resolved, booked at closedAt ?? resolvedAt)
 *   copy cost    = mean per leg of (PaperTrade.entryPrice − ObservedTrade
 *                  .walletEntryPrice) / walletEntryPrice. POSITIVE = we paid
 *                  above the wallet's own fill (a real cost). NEGATIVE = our
 *                  booked entry sat BELOW the wallet's fill, which is an
 *                  artefact of the fill model (the booked entry is a quote read
 *                  at scoring time, not a taker fill), never capture.
 *   detection drag = mean per leg of (detectedPrice − wallet fill)/wallet fill —
 *                  the latency move every copier pays; LOWER BOUND on the true
 *                  cost because no spread and no fee are in it.
 *
 * Writes nothing. Verify: this file's lifetime line equals the lifetime numbers
 * printed in the same day's daily report (DailyReport.summary), and the
 * ALL-LEGS line reproduces the card's 2026-09-23 baseline −3.03% (C-200,
 * 1,983 legs) / +0.84% (STANDARD, 9,863 legs) to 0.02pp.
 */
import { prisma } from "../src/lib/db";
import {
  TRAILING_WINDOW_DAYS,
  computeEdgeCostSnapshot,
  edgeCostLines,
  edgeCostLogLine,
  fetchCopyCostRows,
  localDay,
  pct1,
} from "../src/lib/copy-cost";

/** All-legs form (open + settled), the population the card's baseline used. */
const ALL_LEGS_SQL = `
SELECT p.botId                                        AS botId,
       COUNT(*)                                       AS legs,
       SUM(CASE WHEN o.walletEntryPrice > 0 THEN (p.entryPrice - o.walletEntryPrice) / o.walletEntryPrice ELSE NULL END) AS sum_cc,
       SUM(CASE WHEN o.walletEntryPrice > 0 THEN 1 ELSE 0 END)             AS n_cc,
       SUM(CASE WHEN o.walletEntryPrice > 0 THEN (o.detectedPrice - o.walletEntryPrice) / o.walletEntryPrice ELSE NULL END) AS sum_drag
FROM PaperTrade p
JOIN DecisionJournal d ON d.id = p.decisionJournalId
JOIN ObservedTrade o   ON o.id = d.observedTradeId
WHERE p.isDemo = 0
GROUP BY 1
ORDER BY 1`;

type AllLegsRow = {
  botId: string;
  legs: number | bigint;
  sum_cc: number | null;
  n_cc: number | bigint;
  sum_drag: number | null;
};

async function main() {
  const snap = await computeEdgeCostSnapshot();
  if (snap.totalSettledLegs === 0) {
    console.log("edge vs copy cost: no settled trades yet.");
    return;
  }

  console.log(edgeCostLogLine(snap));
  console.log(`  window: settled at >= ${localDay(snap.d30StartMs)} (last ${TRAILING_WINDOW_DAYS}d) vs lifetime from ${snap.lifetimeStartMs ? localDay(snap.lifetimeStartMs) : "—"}`);
  for (const line of edgeCostLines(snap)) {
    // Discord markdown → plain text: drop bold markers and the italics wrapper
    // (only at the line edges, so `maker_improvement` survives).
    console.log(`  ${line.replace(/\*\*/g, "").replace(/^_/, "").replace(/_$/, "")}`);
  }

  const all = await prisma.$queryRawUnsafe<AllLegsRow[]>(ALL_LEGS_SQL);
  const parts = all.map((r) => {
    const n = Number(r.n_cc);
    const cc = n > 0 ? (Number(r.sum_cc ?? 0) / n) * 100 : null;
    const drag = n > 0 ? (Number(r.sum_drag ?? 0) / n) * 100 : null;
    const label = r.botId === "BANKROLL_200" ? "C-200" : r.botId;
    return `${label} copy cost ${pct1(cc)}% (open+settled ${Number(r.legs).toLocaleString("en-US")} legs) · detected-vs-wallet ${pct1(drag)}%`;
  });
  console.log(`ALL LEGS (open + settled — the card's 2026-09-23 baseline population): ${parts.join(" | ")}`);
  console.log(
    `  reproduce: sqlite3 -readonly prisma/dev.db "SELECT p.botId, COUNT(*), ROUND(100.0*AVG((p.entryPrice-o.walletEntryPrice)/o.walletEntryPrice),3) FROM PaperTrade p JOIN DecisionJournal d ON d.id=p.decisionJournalId JOIN ObservedTrade o ON o.id=d.observedTradeId WHERE p.isDemo=0 GROUP BY 1" (dates are Unix-ms: datetime(col/1000,'unixepoch'))`
  );

  // The library query and the reconciliation query must agree on the join.
  const rows = await fetchCopyCostRows();
  if (rows.length === 0) console.log("WARN: library query returned no settled rows but snapshot had legs");
}

main()
  .catch((e) => {
    console.error("edge-copy-cost FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
