/**
 * apply:v63 — STANDARD dead-zone band skip (user-approved in-thread 2026-10-20: "yes to both").
 *
 *   standardSkipBandRange   ""  → "0.4-0.6"   (NEW FIELD: hard-skip STANDARD copies entering 0.40–0.60)
 *
 * WHY THIS IS A SCOPING FIX AS MUCH AS A TUNING CHANGE. Every band rail written since v41 —
 * the v62 hard band skip, the whole stale-exit/capital-recycling block, the v55 per-market
 * ceiling, the v58 per-wallet ceiling, the concentration caps — is guarded
 * `botId === "BANKROLL_200"`. STANDARD, which carries 99% of the open book, got none of them.
 * The consequence is not subtle: STANDARD books $10.9–$13.7 in EVERY price band within 26%
 * (because the shared scorer's deadZoneSizeFactor/longshotSizeFactor are neutralised at 1.0
 * to stop C-200's band map double-applying, and STANDARD reads those 1.0s), so it allocates
 * capital in proportion to LEG COUNT — and leg count is highest exactly where edge is worst.
 *
 * EVIDENCE (deduped first leg per bot|wallet|market|outcome, status closed|resolved,
 * isDemo=0, cost basis = PaperTrade.simulatedPositionSize in DOLLARS, market-clustered
 * bootstrap — reproducible with `scripts/profit-band-report.py`, committed in 2147d4a):
 *
 *   STANDARD 0.40–0.60, trailing 90d:  1,027 legs (43.5% of lane legs), $13,785 (44.1% of
 *   lane notional), ROI −7.67%, 95% CI [−14.48, −0.89] — the ONLY band whose CI excludes
 *   zero, and it excludes zero on the downside. −$1,057.16 on the lane's simplest cut.
 *
 *   The share is GROWING, not stable: 30d 56.7% of legs at −1.45%, 14d 68.0% at −3.97%,
 *   7d 75.5% of legs AND notional at −17.91% (−$119.31). Over the last week three quarters of
 *   this lane's flow went into the one band that loses money.
 *
 *   Pure skip counterfactual on the 90d book: the lane moves from +2.69% to a positive ROI on
 *   the remaining 55.9% of notional; ~+$12.6/day at current flow (the profit review's figure,
 *   which assumes flow is unchanged — it will partly REDUCE flow, and that is the point:
 *   the skipped legs were spending maxCopiesPerCycle / maxCopiesPerWalletPerDay /
 *   maxOpenPositions that the +EV bands need).
 *
 * ARITHMETIC CAVEAT, recorded so this is not read as "the ladder advances": the dead zone is
 * a TAX REMOVAL, not a growth lever. At the cheap band's measured ROI the $1,750/day phase
 * gate needs ~22x today's cheap-band leg FLOW; no band change reaches it. The gate stays
 * unreachable by configuration and is reported as such.
 *
 * NOT INCLUDED, ON PURPOSE: the profit review bundled a x2.5 cheap-tail upweight (<0.20) with
 * this skip. It is NOT applied here. On STANDARD the <0.20 band reads +47.75% but with 95% CI
 * [−11.33, +112.91] — the interval INCLUDES ZERO — so the edge is established on
 * BANKROLL_200 (+94.18%, CI [+25.98, +170.47]) but not on the lane being changed. A C-200
 * cheap-tail boost is already live (c200LongshotBandFactor 3.5, v62).
 *
 * REVERT: set standardSkipBandRange back to "" — one field, and DEFAULT_RULES ships "" so a
 * ruleset lacking the field behaves exactly as pre-v63.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v63-standard-band-skip.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "standardSkipBandRange" as const,
    newValue: "0.4-0.6",
    reason:
      "v63 (user-approved 2026-10-20): hard-skip STANDARD copies entering 0.40–0.60 — the only CI-negative band, 44% of that lane's 90d notional and 75% of its last-7d notional, at −7.67% (90d) / −17.91% (7d)",
    evidence:
      "STANDARD 0.40–0.60, 90d deduped: 1,027 legs (43.5% of lane legs), $13,785 (44.1% of lane notional), ROI −7.67%, 95% CI [−14.48,−0.89] (only CI-negative band), −$1,057.16. Growing share: 30d 56.7% at −1.45%, 14d 68.0% at −3.97%, 7d 75.5% of legs and notional at −17.91%. STANDARD sizes flat across bands ($10.9–$13.7, within 26%) because the shared scorer's band factors are neutralised at 1.0 (v41). Reproduce: scripts/profit-band-report.py. Sizing is floored by clampPaperSize, so a 0 factor would still book a token leg — hence a skip.",
  },
];

async function main() {
  const before = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (before) {
    const j = JSON.parse(before.rulesJson) as Record<string, unknown>;
    log(
      `apply:v63 before — v${before.version} standardSkipBandRange=${j.standardSkipBandRange ?? "(unset→'')"} ` +
        `(C-200 unchanged: band skip "${j.c200SkipBandRange ?? ""}", long-shot x${j.c200LongshotBandFactor ?? "2.0"}, ` +
        `dead zone x${j.c200DeadZoneBandFactor ?? "0.25"})`
    );
  }
  const result = await applyRuleChanges(PROPOSALS, "hermes-v63-standard-band-approved-20261020");
  if (!result) {
    log("No changes applied.");
    return;
  }
  const active = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  const j = JSON.parse(active?.rulesJson ?? "{}") as Record<string, unknown>;
  log(
    `RuleSet v${result.newVersion} activated (STANDARD band skip "${j.standardSkipBandRange}"). ` +
      `RuleChange audit row written. Revert = "". C-200 rails untouched.`
  );
}

main()
  .catch((e) => {
    logError("apply:v63 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
