/**
 * apply:v68 — STANDARD maturity size factor (0.5 / 1.0 / 1.5 on time-to-resolution at entry).
 *
 * Approved 2026-10-27: "approve standard-maturity-size-factor".
 *
 * WHAT THIS CHANGES (five fields, one schedule)
 *   standardMaturityFactorShort   1.0 -> 0.5    entries with <24h to resolution
 *   standardMaturityFactorMedium  1.0 -> 1.0    (unchanged; 24-72h is the reference cohort)
 *   standardMaturityFactorLong    1.0 -> 1.5    entries with >=72h to resolution
 *   standardMaturityShortHours    24             (unchanged, recorded for completeness)
 *   standardMaturityLongHours     72             (unchanged)
 *
 * Nothing else. C-200's band map, Kelly, the v63 skip band, the v66 stale exit and the v67 long-shot
 * floor are all untouched, and no admission gate moves — a leg that would be skipped is still skipped.
 *
 * WHY
 *   STANDARD books the same clip in every maturity cohort. It does so because the two size factors on
 *   its path (deadZoneSizeFactor / longshotSizeFactor) were neutralised to 1.0 by v41 and Kelly is
 *   C-200-only, so no rule has ever touched STANDARD's size by maturity. The realised ROI spread on
 *   that untouched axis is >9x:
 *     <24h   1,845 legs  clip $11.20  -6.0%
 *     24-72h   704 legs  clip $10.00  +2.0%
 *     >=72h  3,338 legs  clip  $9.00 +21.4%
 *   i.e. the book puts its SMALLEST clip on its BEST cohort and its LARGEST clip on its worst.
 *
 * MEASURED (profit-velocity.py §AJ, TTL = hours remaining at entry from the last MarketSnapshot at
 * or before entry+15min — a decision-time variable with no lookahead; settled clock; STANDARD net of
 * the v63 skip band)
 *   schedule 0.5/1.0/1.5 : +$5,028 all-time, +$4,397 per 90d, 90d CI [+1,018, +8,275] excluding 0
 *   inverse 2.0/1.0/0.5  : -$6,939  (the falsification arm — it loses, so direction is not a coin flip)
 *   ex-top-10 ROI improves under the schedule as well as the headline
 *   The shadow applied BOT_LIMITS.STANDARD {0.25, 20.00} BEFORE quoting, because clampPaperSize runs
 *   after the factor; so an $18 leg at 1.5x books $20, and the quoted dollars already reflect that.
 *
 * DECISION RULE (the rule this was approved against)
 *   >=72h cohort ROI beats <24h by >=5pp on BOTH all-time and 90d; ex-top-10 on the sized book beats
 *   flat by >=3pp; the inverse control is not positive. All three held.
 *
 * PRE-REGISTERED REFUTATION (carried; revert on any one)
 *   On 150 forward STANDARD legs:
 *     (a) >=72h ex-top-10 ROI < 0%, or
 *     (b) <24h ROI >= +3%, or
 *     (c) median post-factor <24h clip < $2.00.
 *   Revert = set the three factors back to 1.0 (one field each; no code change, no redeploy).
 *
 * NOTES / HONEST LIMITS
 *   * Every CI on the headline spans zero in at least one window except the 90d sized-book one, which
 *     is why the shipped rule is a forward refutation rather than a permanent commitment.
 *   * A leg whose TTL cannot be resolved books UNCHANGED (never down-sized). The shadow drops those
 *     legs instead of guessing, so the live book will size a slightly larger population than the
 *     measurement covered — recorded rather than papered over.
 *   * This does NOT close, resize or re-open anything already on the book. Future sizing only, so no
 *     PnL is booked by activating it.
 *
 * Run dry:  DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v68.ts
 * Apply:    DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v68.ts --apply
 */

import { prisma } from "../src/lib/db";
import { getActiveRules, applyRuleChanges } from "../src/lib/rules";
import { log } from "../src/lib/redact";

const REASON =
  "STANDARD sizes flat across a maturity axis whose realised ROI spans 9x (<24h -6.0%, 24-72h +2.0%, " +
  ">=72h +21.4%) because v41 neutralised the two size factors on its path and Kelly is C-200-only. " +
  "0.5/1.0/1.5 measured +$5,028 all-time and +$4,397/90d (CI [+1,018,+8,275]), inverse control -$6,939";
const EVIDENCE =
  "profit-recs 2026-10-25/27 §AJ + §AN; TTL at entry from last MarketSnapshot within 15min of the fill " +
  "(no lookahead); settled clock; STANDARD net of the v63 skip. Schedule 0.5/1.0/1.5: +$5,028 all-time, " +
  "+$4,397/90d, 90d CI [+1,018,+8,275] excluding 0, ex-top-10 improves, inverse 2.0/1.0/0.5 loses $6,939. " +
  "Fillability §AN: 12/12 live books at 0.60-0.85 absorb 2x-4x the doubled $21.60 clip within +2c " +
  "(median +2c depth $4,317 vs 17.0c/sh break-even slippage). Refutation on 150 forward STANDARD legs: " +
  ">=72h ex-top-10 ROI <0%, or <24h ROI >=+3%, or median post-factor <24h clip <$2.00";

/** The book this schedule would act on, measured from live rows rather than asserted. */
async function populations() {
  const now = Date.now();
  const open = await prisma.paperTrade.findMany({
    where: { isDemo: false, botId: "STANDARD", status: "open" },
    select: { simulatedPositionSize: true, entryPrice: true },
  });
  const settled = await prisma.paperTrade.findMany({
    where: { isDemo: false, botId: "STANDARD", status: { in: ["closed", "resolved"] } },
    select: { simulatedPositionSize: true, realizedPnl: true, openedAt: true },
  });
  const d90 = settled.filter((r) => r.openedAt && now - new Date(r.openedAt).getTime() <= 90 * 86_400_000);
  const sum = (xs: { simulatedPositionSize: number }[]) =>
    xs.reduce((s, r) => s + r.simulatedPositionSize, 0);
  return {
    openLegs: open.length,
    openNotional: sum(open),
    openMedianClip: open.length
      ? open.map((r) => r.simulatedPositionSize).sort((a, b) => a - b)[Math.floor(open.length / 2)]
      : 0,
    settledLegs: settled.length,
    settledNotional: sum(settled),
    d90Legs: d90.length,
  };
}

async function main() {
  const apply = process.argv.includes("--apply");
  const beforeQ = await getActiveRules();
  const before = beforeQ.rules;
  const cur = {
    short: before.standardMaturityFactorShort ?? 1,
    medium: before.standardMaturityFactorMedium ?? 1,
    long: before.standardMaturityFactorLong ?? 1,
    shortHours: before.standardMaturityShortHours ?? 24,
    longHours: before.standardMaturityLongHours ?? 72,
  };
  log(
    `active rules v${beforeQ.version}: standardMaturity ${cur.short}/${cur.medium}/${cur.long} ` +
      `hours ${cur.shortHours}/${cur.longHours}`
  );
  if (cur.short === 0.5 && cur.long === 1.5) {
    log("already 0.5/1.0/1.5 — nothing to do.");
    return;
  }

  const p = await populations();
  log("");
  log("PLANNED CHANGE (five fields, one schedule):");
  log("  standardMaturityFactorShort   1.0 -> 0.5   (<24h to resolution)");
  log("  standardMaturityFactorMedium  1.0 -> 1.0   (24-72h, unchanged reference cohort)");
  log("  standardMaturityFactorLong    1.0 -> 1.5   (>=72h to resolution)");
  log("  standardMaturityShortHours    24           (unchanged, recorded)");
  log("  standardMaturityLongHours     72           (unchanged, recorded)");
  log("  effect: STANDARD's clip now follows maturity instead of being flat at $18");
  log("  clamp : applied DOWNSTREAM by clampPaperSize {0.25, 20.00} — an $18 leg at 1.5x books $20");
  log("  untouched: C-200 band map / Kelly, v63 skip band, v66 stale exit, v67 long-shot floor");
  log("  NOTHING already on the book is resized or closed — future sizing only, no PnL booked");
  log("");
  log("CURRENT STANDARD BOOK (context for the change):");
  log(`  open    : ${p.openLegs} leg(s), $${p.openNotional.toFixed(2)} notional, median clip $${p.openMedianClip.toFixed(2)}`);
  log(`  settled : ${p.settledLegs} leg(s), $${p.settledNotional.toFixed(2)} notional (${p.d90Legs} opened in the last 90d)`);
  log("");
  log("  revert: the three factors -> 1.0 (no code change, no redeploy)");
  log("");

  if (!apply) {
    log("DRY RUN — nothing written. Re-run with --apply to activate.");
    return;
  }

  const result = await applyRuleChanges(
    [
      { field: "standardMaturityFactorShort", newValue: 0.5, reason: REASON, evidence: EVIDENCE },
      { field: "standardMaturityFactorMedium", newValue: 1.0, reason: REASON, evidence: EVIDENCE },
      { field: "standardMaturityFactorLong", newValue: 1.5, reason: REASON, evidence: EVIDENCE },
      { field: "standardMaturityShortHours", newValue: 24, reason: REASON, evidence: EVIDENCE },
      { field: "standardMaturityLongHours", newValue: 72, reason: REASON, evidence: EVIDENCE },
    ],
    "hermes-v68-standard-maturity-factor"
  );
  if (!result) {
    log("no changes applied (empty proposal list).");
    return;
  }
  log(`RuleSet v${result.newVersion} activated; standardMaturity 0.5/1.0/1.5. Audit row written.`);
}

main()
  .catch((e) => {
    log(`FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
