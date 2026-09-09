/**
 * apply:v52 — revert of the RuleSet v51 AUTO-TUNE (tuning review #20 rec 2,
 * user-approved 2026-09-09 via clarify: "Revert to v50 + suppress auto-tuner
 * until Oct 8").
 *
 * Context: the EOD auto-tuner (runRuleUpdate, changedBy "hermes") fired at
 * 22:02 CDT Sep 8 — day 1 of the pre-registered Kelly window (Sep 8–Oct 8) —
 * once the 48h manual-change lockout after v50 expired. It tightened
 * maxPriceDrift 0.004→0.003 and minLiquidity 750→1125 on RESOLVED-ONLY
 * evidence (rule-updater.ts was still resolved-only — the same bug class
 * report.ts had; fixed in the same v52 change). That violated the standing
 * user approvals to hold thresholds through Oct 8 (tuning reviews #16–#20).
 *
 * This apply script:
 *   - restores the pre-registered v50 values (drift 0.004, minLiq 750) as
 *     RuleSet v52, changedBy "hermes-v52-tr20-approved" (user-approval
 *     marker; also resets the 48h auto lockout)
 *   - the auto-tuner is additionally suppressed outright until Oct 8 via
 *     KELLY_WINDOW_SUPPRESS_UNTIL in src/lib/rule-updater.ts (code change in
 *     the same v52 commit)
 *   - rule-updater.ts analysis queries now read status in [resolved, closed]
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v52.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "maxPriceDrift" as const,
    newValue: 0.004,
    reason:
      "v52 revert of the v51 auto-tune (tuning review #20 rec 2, user-approved): restore the pre-registered Kelly-window config — the auto-tuner tightened drift 0.004→0.003 at 22:02 Sep 8 (day 1 of the window) on resolved-only evidence, contradicting the approved holds through Oct 8",
    evidence:
      "v51 RuleChange changedBy=hermes, no user-approval marker; rule-updater.ts sample was status='resolved' only (fixed to resolved+closed in v52); Oct 8 gate compares the window against the pre-Kelly clean baseline measured under drift 0.004",
  },
  {
    field: "minLiquidity" as const,
    newValue: 750,
    reason:
      "v52 revert of the v51 auto-tune (rec 2): restore minLiquidity 750 (v50 baseline) for the same Kelly-window-purity reason",
    evidence: "Same v51 auto-tune; suppressed auto path until Oct 8 (KELLY_WINDOW_SUPPRESS_UNTIL).",
  },
];

async function main() {
  const result = await applyRuleChanges(PROPOSALS, "hermes-v52-tr20-approved");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (drift 0.004, minLiquidity 750 — v50 baseline restored). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v52 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
