/**
 * apply:v31 — one-off activation of RuleSet v31 (sweet-spot-only main book:
 * minCopyScore 55 → 70). Versioned, audited path. See drafts/v31-draft.md.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v31.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const REASON =
  "Raise minCopyScore 55→70 (sweet-spot-only main book): 55–69 is the biggest leak, all-time −$0.99/trade (−24% edge) at ~25% of volume; v29 band sizing already favors 70–79";
const EVIDENCE =
  "BANKROLL_200 band PnL (all-time): 55–69 110 trades −$108.94; 70–79 396 trades +$45.46; 80+ 242 trades −$189.39. Post-v29 expected daily ≈ −$13/day → +$14/day";

async function main() {
  const result = await applyRuleChanges(
    [{ field: "minCopyScore", newValue: 70, reason: REASON, evidence: EVIDENCE }],
    "hermes-v31-sweet-spot-only"
  );
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (minCopyScore 55 → 70). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v31 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
