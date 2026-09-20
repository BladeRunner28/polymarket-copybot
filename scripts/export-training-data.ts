import { prisma } from "../src/lib/db";
import * as fs from "fs";

/**
 * Phase 7: Predictive ML Training Data Exporter
 * Exports historical decisions and their final outcomes (wasDecisionGood)
 * along with macro market features for training a predictive model.
 *
 * ERA-AWARE (2026-09-20 tuning review #31 rec 4, user-approved): the label set spans
 * ruleSetVersion 1..59 while the live policy is v59, and two cohorts inside it have
 * OPPOSITE signs (pre-Sep-17 paper-copy labels avg -$0.98 at 62.2% good vs Sep-17+
 * +$0.81 at 52.8%). One undifferentiated file teaches the average of ~50 policies,
 * so the export carries the inputs a proper split needs:
 *   ruleSetVersion — the version the decision was scored under (blank when null)
 *   era            — coarse label derived from it (boundaries documented below)
 *   decision_at    — ISO timestamp, for TIME-ORDERED (never random-row) folds
 *   simulated_pnl  — the review's PnL figure, so a net-of-fee target is possible
 * Doctrine: time-ordered + era-aware splits, never random row folds
 * (card ml-doctrine-time-and-era-splits).
 */
/**
 * Era label from the RuleSet version the decision was scored under.
 * Boundaries are deliberate milestones, not tuned: v49 = the Kelly window opens
 * (Phase B, 2026-09-06), v58 = the per-wallet exposure rail lands (2026-09-19).
 * Anything unversioned stays 'unknown' rather than being assigned to a neighbour.
 */
function eraOf(ruleSetVersion: number | null): string {
  if (ruleSetVersion === null || ruleSetVersion === undefined) return "unknown";
  if (ruleSetVersion < 49) return "pre-kelly-v1-48";
  if (ruleSetVersion < 58) return "kelly-window-v49-57";
  return "exposure-v58plus";
}

async function main() {
  console.log("Exporting training data for predictive model...");
  const reviews = await prisma.outcomeReview.findMany({
    where: { finalOutcome: { not: null } },
    include: {
      decision: {
        include: { observedTrade: true }
      }
    }
  });

  const lines = [
    "review_id,decision,confidence,wallet_score,trade_size,spread,liquidity,ttr_hours,was_good,ruleSetVersion,era,decision_at,simulated_pnl"
  ];
  const byEra = new Map<string, { n: number; good: number; pnl: number; pnlN: number }>();

  for (const r of reviews) {
    const d = r.decision;
    const t = d.observedTrade;
    lines.push([
      r.id,
      d.decision,
      d.confidence.toFixed(3),
      d.walletQualityScore.toFixed(1),
      t.size.toFixed(2),
      d.spreadScore.toFixed(1),
      d.liquidityScore.toFixed(1),
      d.entryTimingScore.toFixed(1), // proxy for ttr
      r.wasDecisionGood ? 1 : 0,
      d.ruleSetVersion ?? "",
      eraOf(d.ruleSetVersion),
      d.createdAt.toISOString(),
      r.simulatedPnl === null || r.simulatedPnl === undefined ? "" : r.simulatedPnl.toFixed(2)
    ].join(","));
    const era = eraOf(d.ruleSetVersion);
    const e = byEra.get(era) ?? { n: 0, good: 0, pnl: 0, pnlN: 0 };
    e.n++;
    if (r.wasDecisionGood) e.good++;
    if (r.simulatedPnl !== null && r.simulatedPnl !== undefined) {
      e.pnl += r.simulatedPnl;
      e.pnlN++;
    }
    byEra.set(era, e);
  }

  fs.writeFileSync("training_data.csv", lines.join("\n"));
  console.log(`Exported ${reviews.length} labeled samples to training_data.csv`);
  // rec 4: a random-row fold mixes eras whose signs differ — print the split first.
  console.log("Per-era (era = rules era, boundaries documented in eraOf):");
  for (const [era, e] of [...byEra.entries()].sort((a, b) => b[1].n - a[1].n)) {
    console.log(
      `  ${era}: n=${e.n} good=${((100 * e.good) / e.n).toFixed(1)}% ` +
        `avgPnL=${e.pnlN ? `$${(e.pnl / e.pnlN).toFixed(2)} (n=${e.pnlN})` : "—"}`
    );
  }
}

main()
  .catch(console.error)
  .finally(() => prisma.$disconnect());
