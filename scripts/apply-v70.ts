/**
 * apply:v70 — RETIRE v66's calendar-triggered STANDARD stale exit.
 *
 * Approved 2026-10-29: "all recs approved", covering profit-recs #2 ("Retire v66's calendar trigger,
 * don't gate it"). This SUPERSEDES the 10-28 proposal to gate the rail on cap pressure — that gate was
 * never built, so nothing has to be unwound.
 *
 * WHAT THIS CHANGES (one field)
 *   standardStaleExitHours    168 -> 0
 * `standardStaleExitFires()` returns false on `hours <= 0`, which is the documented rollback for v66, so
 * the rail goes inert while the field, the band and its history stay on the record. Nothing else moves:
 * the 404 dead-slug expiry path, C-200's recycle lane, the v63 skip band, v67's long-shot floor and the
 * v68/v69 maturity schedule are all untouched.
 *
 * WHY RETIRE RATHER THAN GATE (the premise, not the alpha estimate)
 *   The rail exists to recycle capital into fresh signals when the leg cap binds. For STANDARD that
 *   premise is false on both halves:
 *     - STANDARD has NO notional cap. The $1,000 gross base is C-200-only; open notional is 5.1x it.
 *     - Its only scarce resource is a leg count, `standardMaxOpenPositions` = 1,300, and it is not
 *       binding: 471 open at the time of this write with 829 headroom. The book is also SHRINKING in
 *       the sweep's wake (-4.73 legs/day, 133 opens vs 275 resolutions over the prior 30 days).
 *   A rail whose trigger is "the calendar" cannot be firing because of cap pressure if the cap has
 *   never bound. Gating it (the 10-28 proposal) would keep a rule that has no job, just less often.
 *
 * MEASURED COST OF LEAVING IT ON
 *   -$831.70 on the 24% of swept legs whose markets have settled (-48.36% of notional). One market is
 *   -$807.01: Bolsonaro, sold NO at a 0.204 mark that settled 1.000. Ex the 10 extreme-mark markets the
 *   alpha is -$0.39, and the CI is [-2,522, +48] — so this is NOT sold as a point estimate.
 *   THE CONTROL is what makes it a mechanism rather than noise: STANDARD's other non-resolution exit,
 *   the dead-slug 404 expiry, carries alpha +$210.73 across 6,503 exits with mark error median 0.000,
 *   p10/p90 -4.9c/+3.7c. Six thousand five hundred mark-based exits, calibrated to +/-5c. The 404s only
 *   fire on markets that stopped trading, which is why their marks are good; v66 fires into the opposite
 *   population — live, actively repricing, long-dated favourites at an arbitrary hour — and its 167 legs
 *   cost 3.9x the entire alpha of the 6,503 with the opposite sign.
 *
 * DECISION RULE (the rule it was approved against)
 *   Retire iff the rail's only function is protecting a cap that has never bound, i.e. the 90-day
 *   day-by-day backtest shows it firing on days when cap pressure did not exist.
 *
 * PRE-REGISTERED REFUTATION (reopen on this, and only this)
 *   If `[STANDARD] open-position cap` blocks >=20 copies within 30 days of this activation, cap pressure
 *   was real and the rail gets re-armed (standardStaleExitHours back to 168, or a pressure-conditioned
 *   version). Counted from DecisionJournal, not argued.
 *
 * HONEST LIMITS
 *   * 12 open legs / $112.60 were in scope at activation. These are NOT liquidated or resized — the rail
 *     simply stops firing on them. The profit review explicitly refused liquidating the open 0.4-0.60
 *     book (139 legs, +$519.68 unrealised): the legs still open are the ones whose marks rose, which is
 *     survivorship, not edge.
 *   * The alpha estimate rests on one market dominating; the case rests on the premise test above.
 *   * Reversibility is one field: standardStaleExitHours -> 168 restores v66 exactly.
 *
 * Run dry:  DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v70.ts
 * Apply:    DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v70.ts --apply
 */

import { prisma } from "../src/lib/db";
import { getActiveRules, applyRuleChanges } from "../src/lib/rules";
import { log } from "../src/lib/redact";

const REASON =
  "v66's standard stale exit recycles capital for a lane whose cap has never bound: STANDARD has no " +
  "notional cap (open notional is 5.1x the C-200-only $1,000 base) and its 1,300-leg cap sits at 471 open " +
  "with 829 headroom while the book shrinks -4.73 legs/day. A calendar trigger cannot be responding to cap " +
  "pressure that does not exist, and it fires into live repricing long-dated favourites where marks are " +
  "least calibrated (one market -$807.01)";
const EVIDENCE =
  "profit-recs 2026-10-29 #2. Swept legs: -$831.70 on the 24% whose markets settled (-48.36% of notional), " +
  "one market -$807.01 (Bolsonaro: sold NO at a 0.204 mark, settled 1.000), ex-top-10 -$0.39, CI " +
  "[-2522,+48]. Control: the 6,503 dead-slug 404 exits carry +$210.73 with mark error median 0.000 / p10 " +
  "-4.9c / p90 +3.7c, i.e. mark-based exits are calibrated when the market has stopped trading; v66's 167 " +
  "legs cost 3.9x that entire alpha with the opposite sign. 90-day day-by-day backtest: 92 scope-days, " +
  "gate allows 50 all in the Jul-Aug growth regime, last 30 days 0/30 including sweep day. Refutation: " +
  "`[STANDARD] open-position cap` blocking >=20 copies within 30 days of activation re-arms the rail";

async function main() {
  const apply = process.argv.includes("--apply");
  const q = await getActiveRules();
  const r: any = q.rules;
  const hours = r.standardStaleExitHours ?? 0;
  log(`active rules v${q.version}: standardStaleExitHours = ${hours} (band min ${r.standardStaleExitBandMin})`);
  if (!hours || hours <= 0) {
    log("already retired (hours <= 0) — nothing to do.");
    return;
  }

  const open = await prisma.paperTrade.findMany({
    where: { isDemo: false, botId: "STANDARD", status: "open" },
    select: { simulatedPositionSize: true },
  });
  const headroom = (r.standardMaxOpenPositions ?? 1300) - open.length;
  log("");
  log("PLANNED CHANGE (one field):");
  log(`  standardStaleExitHours  ${hours} -> 0   (standardStaleExitFires returns false on hours <= 0)`);
  log("  untouched: 404 dead-slug expiry, C-200 recycle lane, v63 skip band, v67 floor, v68/v69 maturity");
  log("");
  log(`  open STANDARD legs: ${open.length}, $${open.reduce((s, x) => s + x.simulatedPositionSize, 0).toFixed(2)}`);
  log(`  leg cap ${r.standardMaxOpenPositions} -> headroom ${headroom}  (the premise test)`);
  log("  NOTHING is liquidated, resized or re-booked — the rail simply stops firing");
  log("");
  log("  reopen ONLY if `[STANDARD] open-position cap` blocks >=20 copies within 30 days");
  log("  revert: standardStaleExitHours -> 168 (one field, restores v66 exactly)");
  log("");

  if (!apply) {
    log("DRY RUN — nothing written. Re-run with --apply to retire the rail.");
    return;
  }

  const result = await applyRuleChanges(
    [{ field: "standardStaleExitHours", newValue: 0, reason: REASON, evidence: EVIDENCE }],
    "hermes-v70-retire-standard-calendar-stale-exit"
  );
  if (!result) {
    log("no changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated; the STANDARD calendar stale exit is RETIRED (hours=0).`);
}

main()
  .catch((e) => {
    log(`FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
