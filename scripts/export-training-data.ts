import { prisma } from "../src/lib/db";
import * as fs from "fs";

/**
 * Phase 7: Predictive ML Training Data Exporter
 * Exports historical decisions and their final outcomes (wasDecisionGood)
 * along with macro market features for training a predictive model.
 */
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
    "review_id,decision,confidence,wallet_score,trade_size,spread,liquidity,ttr_hours,was_good"
  ];

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
      r.wasDecisionGood ? 1 : 0
    ].join(","));
  }

  fs.writeFileSync("training_data.csv", lines.join("\n"));
  console.log(`Exported ${reviews.length} labeled samples to training_data.csv`);
}

main()
  .catch(console.error)
  .finally(() => prisma.$disconnect());
