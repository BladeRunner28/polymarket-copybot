/**
 * apply:v66 — give STANDARD the scoped stale exit it has never had.
 * (profit-recs #2, carried from 2026-10-22, user-approved 2026-10-23: "All approved")
 *
 * WHAT THIS CHANGES
 *   standardStaleExitHours    0 -> 168      (0 = disabled; the code default)
 *   standardStaleExitBandMin  0.60 -> 0.60  (written explicitly so the scope is in the
 *                                            ruleset, not only in the code default)
 *
 * WHY STANDARD AND NOT C-200
 * The C-200 hard max-age (v33) is gated on `botId === "BANKROLL_200"` in
 * scripts/update-pnl.ts and no STANDARD equivalent has ever existed. STANDARD therefore
 * parks capital in markets that never resolve: open STANDARD accounts for ~1.07M
 * capital-days = 67.1% of all capital-time at +1.80 $/1k-capital-day, against +27.43
 * for finished legs — 1/15th the rate.
 *
 * WHY THE SCOPE IS >= 0.60 AND NOTHING ELSE
 * Measured on settlement truth (277 legs, 85 markets resolving >168h after entry):
 *   >= 0.60        +$68 to +$326   <- the scope this activates
 *   0.6-0.8 alone  turns negative on hold
 *   0.20-0.40      DESTROYS $1,064 on 135 legs
 * A (1-p)/p payoff cannot be time-stopped, which is why the cheap band is out of scope.
 * 0.40-0.60 is not a decision either way: v63 skips that band on STANDARD, so no leg can
 * reach the exit there. DO NOT widen this downward without a fresh measurement — the
 * 10-22 report says exactly that, and the 10-23 brief repeated it.
 *
 * WHAT IT WILL DO ON THE FIRST RUN AFTER ACTIVATION
 * Every open STANDARD position entered at >= 0.60 that is already past 168h closes at
 * the last mark. That is a STOCK clearing, not a flow change. The dry run below prints
 * the exact count and notional so the batch is seen before it is booked.
 *
 * PRE-REGISTERED REFUTATION (carried, and it stays binding)
 *   (a) the first 20 ORGANIC stopped legs realise worse than hold by >1.0% of notional
 *       => the marks lied, revert;
 *   (b) 0.6-0.8 hold-to-settlement turns positive on >=150 new settled legs => revert.
 * Revert is one field: standardStaleExitHours -> 0.
 *
 * Run dry:  DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v66.ts
 * Apply:    DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v66.ts --apply
 */

import { prisma } from "../src/lib/db";
import { getActiveRules, applyRuleChanges } from "../src/lib/rules";
import { log } from "../src/lib/redact";

const REASON =
  "STANDARD has never had a stale-exit rail (the v33 hard max-age is gated on BANKROLL_200 in update-pnl.ts), so it parks capital in markets that never resolve: ~1.07M open capital-days = 67.1% of all capital-time at +1.80 $/1k-cd vs +27.43 finished. Scope is entry >= 0.60 only: that is where settlement truth pays (+$68..+$326), while 0.20-0.40 destroys $1,064 on 135 legs and 0.40-0.60 is unreachable because v63 skips it";
const EVIDENCE =
  "profit-recs 2026-10-22 §V settlement truth: 277 settled legs on 85 markets that resolved >168h after entry; >=0.60 stop +$68 (4.1% of notional) to +$326 on the DB-mark basis; 0.6-0.8 alone turns negative on hold (+6.5% at 80% settled hit); 0.20-0.40 +$1,148 hold vs +$85 stopped = -$1,064 on 135 legs; capital-days at >=0.60 591,843 -> 113,106 (-81%), whole book 1,058,013 -> 189,745. Refutation: first 20 organic stopped legs worse than hold by >1.0% of notional, or 0.6-0.8 hold-to-settlement positive on >=150 new settled legs";

async function affectedPopulation(hours: number, bandMin: number) {
  const cutoff = new Date(Date.now() - hours * 3_600_000);
  const rows = await prisma.paperTrade.findMany({
    where: {
      isDemo: false,
      botId: "STANDARD",
      status: "open",
      entryPrice: { gte: bandMin },
      openedAt: { lte: cutoff },
    },
    select: { entryPrice: true, simulatedPositionSize: true },
  });
  const notional = rows.reduce((s, r) => s + r.simulatedPositionSize, 0);
  return { legs: rows.length, notional };
}

async function main() {
  const apply = process.argv.includes("--apply");
  const beforeQ = await getActiveRules();
  const before = beforeQ.rules;
  const hours = before.standardStaleExitHours ?? 0;
  const bandMin = before.standardStaleExitBandMin ?? 0.6;
  log(`active rules v${beforeQ.version}: standardStaleExitHours=${hours} standardStaleExitBandMin=${bandMin}`);

  if (hours === 168) {
    log("already 168 — nothing to do.");
    return;
  }

  const pop = await affectedPopulation(168, bandMin);
  log("");
  log("PLANNED CHANGE:");
  log("  standardStaleExitHours    0 -> 168");
  log("  standardStaleExitBandMin  -> 0.60 (written explicitly)");
  log("  effect: open STANDARD legs entered >= 0.60 close at the last mark once 168h old");
  log("");
  log("IMMEDIATE STOCK CLEARING on the first update-pnl run after activation:");
  log(`  ${pop.legs} open leg(s), $${pop.notional.toFixed(2)} notional`);
  log("");
  log("  revert: standardStaleExitHours -> 0");
  log("");

  if (!apply) {
    log("DRY RUN — nothing written. Re-run with --apply to activate.");
    return;
  }

  const result = await applyRuleChanges(
    [
      { field: "standardStaleExitHours", newValue: 168, reason: REASON, evidence: EVIDENCE },
      { field: "standardStaleExitBandMin", newValue: 0.6, reason: REASON, evidence: EVIDENCE },
    ],
    "hermes-v66-standard-scoped-stale-exit"
  );
  if (!result) {
    log("no changes applied (empty proposal list).");
    return;
  }
  log(`RuleSet v${result.newVersion} activated; standardStaleExitHours=168 scope>=0.60. Audit row written.`);
}

main()
  .catch((e) => {
    log(`FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
