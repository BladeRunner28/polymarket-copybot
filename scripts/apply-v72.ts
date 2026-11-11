/**
 * apply:v72 — key the wallet category map on the REAL CLASS instead of the slug token.
 *
 * Approved by the operator via the approvals inbox 2026-11-11 (apr-wallet-category-fit-class-swap,
 * kanban t_eb3d3136), following the 2026-09-23 measurement on card
 * `wallet-category-fit-class-swap`.
 *
 * WHAT THIS CHANGES (one field)
 *   walletCategoryBasis   "token" -> "class"
 *
 * Read by src/lib/scoring/wallet.ts::scoreWallet, which decides which field the per-category
 * strength map (categoryStrengthsJson, bestCategory, categoryFitScore's win rate) is bucketed on:
 *   "token" = t.marketCategory, the RAW event-slug token. Defective as a category: the token
 *             `highest` alone wraps 14,879 marketIds, and 9.3% of wallets' bestCategory is a
 *             question fragment (`will`, `what`, `world`).
 *   "class" = t.marketCategoryClass, the real coarse category (src/lib/market-category.ts),
 *             stamped at ingest on every WalletActivityTrade/ObservedTrade row since 2026-09-23.
 * The FINE class is computed beside it and stored as a diagnostic; it never feeds the score.
 * NOT touched: the v45 per-bot blacklist and the per-slug position cap — both are token-granularity
 * BY DESIGN and keep reading marketCategory.
 *
 * MEASURED (2026-09-23, drafts/wallet-category-fit-class-swap-20260923.md, 198 wallets / 1,962
 * C-200 legs / 8,694 STANDARD legs)
 *   Structure — the class basis is what the card says it is: 3 buckets/wallet vs 14, 33 trades per
 *   bucket vs 2.5, 87-91% of legs get a defined fit vs 69-84%, and the strongest bucket carries
 *   72.6% of a wallet's sample vs 33.6%.
 *   Ranking — it does NOT rank leg outcomes better: C-200 coarse AUC 0.487 / fine 0.502, STANDARD
 *   coarse 0.493 / fine 0.522, every wallet-clustered CI includes 0.5, and the token basis is the
 *   same null (0.497 / 0.525). So this is a LABEL/CONSISTENCY change, not an edge claim — and the
 *   swap does move the component on 388 C-200 / 2,577 STANDARD legs (bases disagree by >10 win-rate
 *   points there), which is why it is a RuleSet version and not a silent code edit.
 *
 * REVERT
 *   npx tsx scripts/apply-v72.ts --apply --token      (one field, back to the shipped default)
 *   Or: set walletCategoryBasis = "token" on the active RuleSet. DEFAULT_RULES already carries
 *   "token", so every ruleset lacking the field scores byte-identically to pre-v72.
 */
import { prisma } from "../src/lib/db";
import { getActiveRules, applyRuleChanges } from "../src/lib/rules";

const TARGET = "class" as const;
const REVERT_TO = "token" as const;

const REASON =
  "v72: the wallet category map was keyed on the raw event-slug token (`highest` alone spans " +
  "14,879 marketIds; bestCategory reads will/what/world) while marketCategoryClass has been stamped " +
  "at ingest since 2026-09-23. Operator-approved swap to the real coarse class; fine class kept as a " +
  "diagnostic, token untouched for the v45 blacklist and per-slug cap.";

const EVIDENCE =
  "Measured 2026-09-23 (drafts/wallet-category-fit-class-swap-20260923.md, 198 wallets): class basis " +
  "is denser (3 buckets/wallet vs 14, 33 trades/bucket vs 2.5, 87-91% coverage vs 69-84%) and ranks " +
  "leg outcomes at chance (C-200 coarse 0.487 / fine 0.502; STANDARD coarse 0.493 / fine 0.522; all " +
  "clustered CIs include 0.5) — the same null as the token basis, i.e. a label/consistency change, " +
  "not an edge claim. Moves the component on 388 C-200 / 2,577 STANDARD legs.";

function log(s: string) {
  console.log(s);
}

async function main() {
  const apply = process.argv.includes("--apply");
  const wantRevert = process.argv.includes("--token");
  const target = wantRevert ? REVERT_TO : TARGET;

  const active = await getActiveRules();
  const current = active.rules.walletCategoryBasis;

  log(`active rules v${active.version}: walletCategoryBasis = ${current}`);

  if (current === target) {
    log(`already ${target} — nothing to do.`);
    return;
  }

  log("");
  log("PLANNED CHANGE (one field):");
  log(`  walletCategoryBasis  ${current} -> ${target}`);
  log("  effect: the per-wallet category strength map, bestCategory and the categoryFitScore win");
  log("          rate are bucketed on the COARSE CLASS (marketCategoryClass) instead of the slug");
  log("          token. Existing WalletProfile rows keep their own basis until the hourly scan");
  log("          re-scores them — the stored payload carries its basis, so both generations read");
  log("          correctly during the transition.");
  log("  untouched: v45 blacklist, per-slug cap (both token-granularity by design), every gate and");
  log("             sizing field, the fine-class diagnostic");
  log(`  revert: set walletCategoryBasis back to ${wantRevert ? TARGET : REVERT_TO} (field default is "token")`);
  log("");

  if (!apply) {
    log("DRY RUN — nothing written. Re-run with --apply to activate v72.");
    return;
  }

  const result = await applyRuleChanges(
    [
      {
        field: "walletCategoryBasis",
        newValue: target,
        reason: wantRevert ? `${REASON} | REVERT to the token basis.` : REASON,
        evidence: EVIDENCE,
      },
    ],
    wantRevert ? "hermes-v72-revert-category-basis" : "hermes-v72-wallet-category-basis"
  );
  if (!result) {
    log("no changes applied.");
    return;
  }
  // Verify through the same loader the scanner and scorer use, not the row we just wrote.
  const after = await getActiveRules();
  log(`RuleSet v${result.newVersion} activated; effective walletCategoryBasis = ${after.rules.walletCategoryBasis}`);
  if (after.rules.walletCategoryBasis !== target) {
    throw new Error(`post-apply read-back is ${after.rules.walletCategoryBasis}, expected ${target}`);
  }
}

main()
  .catch((e) => {
    log(`FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
