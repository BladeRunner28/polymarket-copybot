/**
 * apply:v46 — activation of RuleSet v46: gross-exposure base cap $250 → $400
 * (2026-09-03, user-approved: "raise base now anyway to $400 — paper-only,
 * faster signal sampling; accepts phase-streak/comparability risk").
 *
 * Context: the $250 base was a v40 (homerun-audit) conservative brake sized
 * to a smaller book; principal is now $1,900 (cap = 13% deployed) while the
 * 225-position cap is sized to ~100% of bankroll. The cap bound hard on
 * high-flow days (884 blocks Aug 31–Sep 1; opens collapsed 150/day → 14/day).
 *
 * v46 mechanics:
 *   1. maxGrossExposureUsd 250 → 400 (this file — flag-revertible).
 *   2. Equity-linked helper src/lib/exposure-cap.ts (shipped earlier same
 *      day): effective cap = stored base + 50% × max(0, net worth − principal).
 *      Symmetric; today net worth < principal → effective cap = $400.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v46.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "maxGrossExposureUsd" as const,
    newValue: 400,
    reason:
      "Gross-exposure base cap raised $250 → $400 (user-approved 2026-09-03): $250 was a v40-era brake sized to a smaller book; principal is $1,900 so $250 = 13% deployment vs the 225-position cap sized to ~100%. Paper-only — faster signal sampling at the cost of phase-streak comparability risk. Equity-link (v46 helper) stacks on top; effective cap today = $400 (net worth below principal).",
    evidence:
      "884 exposure-cap blocks Aug 31–Sep 1 with opens collapsing 150/day → 14/day (DecisionJournal risksJson). Zero blocks since (book shrank). v45 blacklists shipped same day remove the structural −EV slug set (−$801 recoverable) that dominated the early-exit bleed. Daily-loss (−$150), drawdown (20% peak), category (40) and slug (15) gates unchanged as the outer safety net.",
  },
];

async function main() {
  const result = await applyRuleChanges(PROPOSALS, "hermes-v46-exposure-cap-base-400");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(
    `RuleSet v${result.newVersion} activated: maxGrossExposureUsd=${PROPOSALS[0].newValue}. ` +
      `RuleChange audit row written.`
  );
}

main()
  .catch((e) => {
    logError("apply:v46 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
