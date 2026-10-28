/**
 * apply:v69 — split v68's ">=72h" size bucket at 168h.
 *
 * Approved 2026-10-27: "approve standard-maturity-168h-split".
 *
 * WHAT THIS CHANGES (two fields, one boundary)
 *   standardMaturityHugeHours    1e9 -> 168   (1e9 = inert; 168 makes the 4th bucket real)
 *   standardMaturityFactorHuge   1.0 -> 1.0   (unchanged value, recorded so the bucket is explicit)
 *
 * Resulting schedule: 0.5 (<24h) / 1.0 (24-72h) / 1.5 (72-168h) / 1.0 (>=168h).
 * Nothing else moves — C-200's band map, Kelly, the v63 skip band, the v66 stale exit and the v67
 * long-shot floor are all untouched, and no admission gate changes.
 *
 * WHY (v68 shipped 2026-10-27 with 0.5/1.0/1.5 at 24/72h and put THREE cohorts in one 1.5x bucket)
 *   Measured, market-clustered CIs, 12,168 settled legs with a usable TTL join, TTL = hours to
 *   resolution AT ENTRY (decision-time variable, no lookahead):
 *     <6h   -8.6%  [-24.0, +7.6]     6-24h  -6.5%  [-17.8, +5.1]
 *     1-3d  +7.5%  [ -6.4,+25.8]     3-7d  +46.8%  [+12.8, +61.2]   <- the only CI excluding zero
 *     7-30d +19.9% [ -4.2,+53.1]     >30d  +12.8%  [ -3.6, +34.5]
 *   Per $1k-capital-day: 3-7d +127.85 vs >30d +2.88 — >30d holds a median 36.7 days, so 1.5x notional
 *   there buys exposure, not turnover. That is the whole argument: v68 gave the same up-weight to a
 *   four-day trade and a five-week trade.
 *
 * ROBUSTNESS (checked before quoting anything)
 *   The 3-7d bucket is dominated by will-spain-win-the-2026-fifa-world-cup (757 legs). Excluding it the
 *   bucket is still +29.5% on 1,357 legs across 286 markets, so the edge is not one match. It is,
 *   however, 287 markets — a few dozen independent draws, not 2,114 — which is why this ships with a
 *   forward refutation rather than as a settled conclusion.
 *
 * DECISION RULE (the rule it was approved against)
 *   Adopt iff moving the >=168h cohort from 1.5x to 1.0x raises $/1k-capital-day for the whole STANDARD
 *   book and costs <=2% of total PnL.
 *
 * PRE-REGISTERED REFUTATION (revert on either)
 *   (a) the >=168h cohort's $/1k-capital-day turns out >= the 3-7d cohort's on a 90d window, or
 *   (b) the split costs >2% of total PnL.
 *   Revert = standardMaturityHugeHours back to 1e9 (one field; the bucket goes inert again).
 *
 * HONEST LIMITS
 *   * This edits a schedule shipped four hours earlier. It is a separate pre-registration and a separate
 *     version rather than an edit-in-place, so the four-hour interval is visible in the audit trail.
 *   * 164 settled legs have no snapshot and are excluded from every cohort above rather than guessed.
 *   * Nothing already on the book is resized or closed; future sizing only, so no PnL is booked.
 *
 * Run dry:  DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v69.ts
 * Apply:    DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v69.ts --apply
 */

import { prisma } from "../src/lib/db";
import { getActiveRules, applyRuleChanges } from "../src/lib/rules";
import { log } from "../src/lib/redact";

const REASON =
  "v68 gave the same 1.5x up-weight to 3-7d, 7-30d and >30d. Those measure +46.8% / +19.9% / +12.8%, and " +
  ">30d earns +$2.88 per $1k-capital-day against 3-7d's +$127.85 because it holds a median 36.7 days. " +
  "Splitting the bucket at 168h sends the up-weight only to the window that recycles capital";
const EVIDENCE =
  "drafts/prereg-permarket-cap-and-ttl-window-20261027.md Part B; 12,168 settled legs with a TTL join from " +
  "the last MarketSnapshot within 15min of entry (no lookahead); market-clustered 95% CIs. <6h -8.6% " +
  "[-24.0,+7.6]; 6-24h -6.5% [-17.8,+5.1]; 1-3d +7.5% [-6.4,+25.8]; 3-7d +46.8% [+12.8,+61.2]; 7-30d " +
  "+19.9% [-4.2,+53.1]; >30d +12.8% [-3.6,+34.5]. $/1k-capital-day 3-7d +127.85 vs >30d +2.88. 3-7d " +
  "survives dropping its dominant market: +29.5% on 1,357 legs / 286 markets. Refutation: >=168h $/1k-cd " +
  ">= 3-7d on a 90d window, or the split costs >2% of total PnL";

async function main() {
  const apply = process.argv.includes("--apply");
  const beforeQ = await getActiveRules();
  const r: any = beforeQ.rules;
  const cur = {
    short: r.standardMaturityFactorShort ?? 1,
    medium: r.standardMaturityFactorMedium ?? 1,
    long: r.standardMaturityFactorLong ?? 1,
    shortHours: r.standardMaturityShortHours ?? 24,
    longHours: r.standardMaturityLongHours ?? 72,
    hugeHours: r.standardMaturityHugeHours ?? 1e9,
    huge: r.standardMaturityFactorHuge ?? 1,
  };
  log(
    `active rules v${beforeQ.version}: STANDARD maturity ${cur.short}/${cur.medium}/${cur.long} at ` +
      `${cur.shortHours}/${cur.longHours}h, huge ${cur.huge} at ${cur.hugeHours}h`
  );
  if (cur.hugeHours === 168) {
    log("hugeHours is already 168 — nothing to do.");
    return;
  }

  const open = await prisma.paperTrade.findMany({
    where: { isDemo: false, botId: "STANDARD", status: "open" },
    select: { simulatedPositionSize: true },
  });
  log("");
  log("PLANNED CHANGE (two fields, one boundary):");
  log("  standardMaturityHugeHours    1e9 -> 168   (1e9 was inert)");
  log("  standardMaturityFactorHuge   1.0 -> 1.0   (recorded so the bucket is explicit)");
  log("  schedule becomes: 0.5 (<24h) / 1.0 (24-72h) / 1.5 (72-168h) / 1.0 (>=168h)");
  log("  untouched: C-200 band map / Kelly, v63 skip band, v66 stale exit, v67 long-shot floor");
  log("  NOTHING on the book is resized or closed — future sizing only, no PnL booked");
  log("");
  log(`  open STANDARD legs at activation: ${open.length}, $${open.reduce((s, x) => s + x.simulatedPositionSize, 0).toFixed(2)}`);
  log("");
  log("  revert: standardMaturityHugeHours -> 1e9 (one field; the bucket goes inert, v68 behaviour returns)");
  log("");

  if (!apply) {
    log("DRY RUN — nothing written. Re-run with --apply to activate.");
    return;
  }

  const result = await applyRuleChanges(
    [
      { field: "standardMaturityHugeHours", newValue: 168, reason: REASON, evidence: EVIDENCE },
      { field: "standardMaturityFactorHuge", newValue: 1.0, reason: REASON, evidence: EVIDENCE },
    ],
    "hermes-v69-standard-maturity-168h-split"
  );
  if (!result) {
    log("no changes applied (empty proposal list).");
    return;
  }
  log(`RuleSet v${result.newVersion} activated; 4th maturity bucket live at 168h. Audit row written.`);
}

main()
  .catch((e) => {
    log(`FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
