/**
 * apply:v29 — one-off activation of RuleSet v29 (inverted sizing + capital
 * recycling), drafted from the 2026-08-28 C-200 daily report and implemented
 * in src/lib/scoring/trade.ts, scripts/score-trades.ts, scripts/update-pnl.ts.
 *
 * Uses the versioned applyRuleChanges path: old set deactivated, new set
 * activated, RuleChange audit row written with before/after JSON.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v29.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges, type RuleChangeProposal, type Rules } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const REASON =
  "Invert sizing: cap ≥80 at $10 (worst bucket −$0.77/trade), 70–79 to $18 (+$0.27/trade only +EV band); minCopyScore 45→55 (45–59 tail −$1.12/trade); ≥80 drift ceiling 0.004 | Capital recycling: cap 100 opens + 72h/5% stale exit (276 opens stranding $1,529)";
const EVIDENCE =
  "Aug 28 report: score≥80 240 trades −$185.03; 70–79 358 trades +$95.78; 697 closed 48.9% win −$194.58 realized";

async function main() {
  const fieldValues: Array<{ field: keyof Rules; newValue: number }> = [
    { field: "minCopyScore", newValue: 55 },
    { field: "sweetSpotMinScore", newValue: 70 },
    { field: "sweetSpotMaxScore", newValue: 79 },
    { field: "sweetSpotSizeUsd", newValue: 18 },
    { field: "highScoreCapMin", newValue: 80 },
    { field: "highScoreCapUsd", newValue: 10 },
    { field: "highScoreMaxDrift", newValue: 0.004 },
    { field: "maxOpenPositions", newValue: 100 },
    { field: "staleExitHours", newValue: 72 },
    { field: "staleExitMinMove", newValue: 0.05 },
  ];

  const proposals: RuleChangeProposal[] = fieldValues.map((p) => ({
    ...p,
    reason: REASON,
    evidence: EVIDENCE,
  }));

  const result = await applyRuleChanges(proposals, "hermes-v29-daily-report");
  if (!result) {
    log("No changes applied (proposal list empty).");
    return;
  }
  log(`RuleSet v${result.newVersion} activated. RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v29 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
