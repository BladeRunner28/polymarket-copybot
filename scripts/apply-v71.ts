/**
 * apply:v71 — make the C-200 band map LANE-SCOPED.
 *
 * Approved 2026-11-03: "Money decisions - all approved", covering profit-recs #1 of that date
 * ("make the band factors lane-scoped").
 *
 * WHAT THIS CHANGES (two fields, both defaulting to today's shipped constants)
 *   shortTtrDeadZoneBandFactor   0.25 -> 0.5
 *   shortTtrPremiumBandFactor    0.5  -> 2.0
 * Both are read ONLY when `result.lane === "short_ttr"` (scripts/score-trades.ts, bandFactors).
 * The main lane keeps `c200DeadZoneBandFactor` (0.25) and the shipped premium constant (0.5),
 * so main-lane sizing is byte-identical to v70.
 *
 * WHY (the mechanism, not the point estimate)
 *   mapBankroll200Size applied ONE deadZone factor and ONE premium factor to both lanes. The two
 *   lanes carry OPPOSITE signs on exactly those bands, so the single pair was an average that fit
 *   neither:
 *     - 0.40-0.60:  main -7.1%   |  short-TTR +22.6%, CI [+10.2,+34.9], z=2.52, 290 markets
 *     - 0.60-0.80:  main premium drag z=-2.49/-2.42  |  short-TTR +24.4%, CI [+14.5,+32.6],
 *                              z=4.00, ex-top-5 keeps 86% of the cell, best market only 5%
 *   The deadZone factor (0.25) landed hardest on the only mid-band cell that clears its own CI.
 *   Slippage tolerance in those two cells is 8.4c and 13.5c of entry price before ROI hits zero,
 *   i.e. 8-13x any plausible tick — thin books are not the binding risk where this adds size.
 *
 * MEASURED EFFECT
 *   +$537.41 over the 57-day regime window = +$9.4/day (+17%), at clips of $3.46 / $15.00.
 *   That is the ENTIRE size prize on offer in this book: at $1.7-$15 clips no rule change is
 *   worth more than ~$10/day, while rung 1 ($250/day) is 4.5x the whole book.
 *
 * NOT INCLUDED (approved separately, deliberately NOT shipped here)
 *   profit-recs #2 — "no clip may exceed what its own -2SE Kelly supports" (main <0.20 $31.64 ->
 *   $7.50). It costs -$762 over the same window (-$13.3/day) in-sample and the proposal itself
 *   says "don't take it alone": paired with this change it nets -$225. It needs a per-band -2SE
 *   Kelly cap in the sizing path, which is a different and larger change than two rule fields.
 *
 * PRE-REGISTERED REFUTATION (reopen on this, and only this)
 *   Over the next 150 short-TTR bets: CI lower bound < 0, OR ex-top-5 < +8%, OR median entry
 *   slippage > 4c => revert both fields to 0.25 / 0.5.
 *
 * REVERT
 *   shortTtrDeadZoneBandFactor -> 0.25, shortTtrPremiumBandFactor -> 0.5 (one apply script, or
 *   the fields' defaults, which are exactly those values).
 */
import { prisma } from "../src/lib/db";
import { getActiveRules, applyRuleChanges } from "../src/lib/rules";

const REASON =
  "v71: the band map was lane-blind; 0.40-0.60 is -7.1% in main and +22.6% in short-TTR " +
  "(CI [+10.2,+34.9], z=2.52) while 0.60-0.80 is +24.4% in short-TTR (CI [+14.5,+32.6], z=4.00, " +
  "ex-top-5 keeps 86%), so one factor pair for both lanes fit neither.";

const EVIDENCE =
  "profit-recs 2026-11-03 (regime v49+, 1,168 bets / $13,111 / 57.4d): lane-scoped factors are " +
  "+$537.41 over the window (+$9.4/day, +17%) at clips $3.46/$15.00; slippage tolerance 8.4c/13.5c. " +
  "Refutation: next 150 short-TTR bets with CI low < 0, ex-top-5 < +8%, or median slippage > 4c.";

function log(s: string) {
  console.log(s);
}

async function main() {
  const apply = process.argv.includes("--apply");
  const active = await getActiveRules();
  const r = active.rules;
  const dz = r.shortTtrDeadZoneBandFactor;
  const pr = r.shortTtrPremiumBandFactor;

  log(`active rules v${active.version}: shortTtrDeadZoneBandFactor = ${dz}, shortTtrPremiumBandFactor = ${pr}`);
  log(`  main lane (unchanged): c200DeadZoneBandFactor = ${r.c200DeadZoneBandFactor}, premium = 0.5 (shipped const)`);

  if (dz === 0.5 && pr === 2.0) {
    log("already applied — nothing to do.");
    return;
  }

  log("");
  log("PLANNED CHANGE (two fields, short-TTR lane only):");
  log(`  shortTtrDeadZoneBandFactor  ${dz} -> 0.5`);
  log(`  shortTtrPremiumBandFactor   ${pr} -> 2.0`);
  log("  untouched: longshot factor + v67 floor, main-lane factors, Kelly rails, v63 skip band,");
  log("             v68/v69 maturity schedule, v70's stale-exit retirement, every risk gate");
  log("");
  log("  reopen ONLY on: next 150 short-TTR bets with CI low < 0, ex-top-5 < +8%, or slippage > 4c");
  log("  revert: 0.5 -> 0.25 and 2.0 -> 0.5 (also the field defaults)");
  log("");

  if (!apply) {
    log("DRY RUN — nothing written. Re-run with --apply to activate v71.");
    return;
  }

  const result = await applyRuleChanges(
    [
      { field: "shortTtrDeadZoneBandFactor", newValue: 0.5, reason: REASON, evidence: EVIDENCE },
      { field: "shortTtrPremiumBandFactor", newValue: 2.0, reason: REASON, evidence: EVIDENCE },
    ],
    "hermes-v71-lane-scoped-band-factors"
  );
  if (!result) {
    log("no changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated; the band map is lane-scoped (short-TTR 0.5 / 2.0).`);
}

main()
  .catch((e) => {
    log(`FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
