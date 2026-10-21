/**
 * apply:v65 — wallet quality becomes an ADMISSION-only signal (profit-recs #3,
 * user-approved 2026-10-21: "Do recommendation").
 *
 * WHAT THIS CHANGES
 * `walletQualityInSize: 1 -> 0`. The size bucket stops including the 0.30-weight
 * wallet-quality term; the remaining 0.70 weights renormalise to the same 0-100
 * scale. Admission (`copyScore`, minCopyScore / confidence floors, the long-shot
 * relaxation) is UNCHANGED — it still uses the full composite including wallet.
 *
 * WHY
 * Per-wallet ROI has no forward information: Spearman -0.018 (p=0.942) between
 * first-half and second-half wallet ROI; the H1-WORST third earned +130% in H2
 * against +31.8% for the H1-best. Routing a 0.30-weight noise term into size is
 * sizing on noise. CAVEAT RECORDED: the pre-registered trigger asked for >=30
 * overlapping wallets; there are 16. This ships on the user's approval with the
 * gate unmet, and the refutation stands — at >=30 wallets, an H1->H2 correlation
 * above +0.30 means wallet selection is real and this should be reverted.
 *
 * MEASURED EFFECT (scripts/wallet-size-separation-read.py, 2026-10-21)
 * 9,043 historical STANDARD legs whose stored components reconstruct their
 * copyScore exactly, BOTH arms recomputed under the then-active v64 rules:
 *   notional $137,895.70 -> $130,697.91  (-5.2%, -$7,197.80)
 *   mean clip $15.25 -> $14.45
 *   1,738 legs down / 632 up / 6,673 unchanged; the $18 sweet-spot bucket
 *   drops 6,520 -> 5,801 legs.
 * NOT affected: C-200 (sizes through kellySizeForCopy, which never sees a wallet
 * score — the original recommendation's premise that wallet quality "routes into
 * Kelly sizes" was wrong), and short-TTR lane legs (fixed size).
 *
 * REVERT — one field:
 *   UPDATE RuleSet active row -> walletQualityInSize = 1
 *   (or re-run applyRuleChanges([{field:"walletQualityInSize", newValue:1, ...}]))
 * The CODE default is already 1, so any ruleset lacking the field is legacy.
 *
 * Run dry:  DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v65.ts
 * Apply:    DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v65.ts --apply
 */

import { prisma } from "../src/lib/db";
import { getActiveRules, applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const REASON =
  "Wallet quality is an ADMISSION signal, not a SIZE signal: per-wallet ROI has no forward information (Spearman -0.018, p=0.942; H1-worst third +130% vs +31.8% for H1-best), so a 0.30-weight wallet term was moving the size bucket on noise";
const EVIDENCE =
  "scripts/wallet-size-separation-read.py 2026-10-21: 9,043 STANDARD legs re-computed both arms under v64 -> notional $137,895.70 -> $130,697.91 (-5.2%), mean clip $15.25 -> $14.45, 1,738 down / 632 up / 6,673 unchanged, $18 bucket 6,520 -> 5,801. Trigger caveat: 16 overlapping wallets against a pre-registered bar of 30; refutation at >=30 wallets is H1->H2 correlation > +0.30";

async function main() {
  const apply = process.argv.includes("--apply");
  const beforeQ = await getActiveRules();
  const before = beforeQ.rules;
  log(`active rules v${beforeQ.version}: walletQualityInSize=${before.walletQualityInSize}`);

  if (before.walletQualityInSize === 0) {
    log("already 0 — nothing to do.");
    return;
  }

  log("");
  log("PLANNED CHANGE (single field):");
  log("  walletQualityInSize  1 -> 0");
  log("  effect: size score loses the 0.30 wallet term; admission unaffected");
  log("  measured: notional -5.2% on 9,043 historical STANDARD legs");
  log("  revert: set walletQualityInSize back to 1");
  log("");

  if (!apply) {
    log("DRY RUN — nothing written. Re-run with --apply to activate.");
    return;
  }

  const result = await applyRuleChanges(
    [{ field: "walletQualityInSize", newValue: 0, reason: REASON, evidence: EVIDENCE }],
    "hermes-v65-wallet-admission-only"
  );
  if (!result) {
    log("No changes applied.");
    return;
  }
  const afterQ = await getActiveRules();
  const after = afterQ.rules;
  log(`RuleSet v${result.newVersion} activated; walletQualityInSize=${after.walletQualityInSize}. Audit row written.`);
  if (after.walletQualityInSize !== 0) {
    throw new Error(`activation did not take: walletQualityInSize reads ${after.walletQualityInSize}`);
  }
}

main()
  .catch((e) => {
    logError("apply:v65 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
