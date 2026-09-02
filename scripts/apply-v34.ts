/**
 * apply:v34 — one-off activation of RuleSet v34 (regulatory-boost clamp:
 * regulatoryScoreCap 79). An unvalidated sentiment signal can no longer
 * manufacture copies in the ≥80 band (worst historical bucket; 0 boosted
 * trades ever resolved). Versioned, audited path. See drafts/v32-draft.md.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v34.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const REASON =
  "Clamp regulatory-boosted copyScore at 79: all 13 boosted copies (7d) landed in the ≥80 band (−$0.78/trade for C-200); 0 boosted trades resolved — signal unvalidated";
const EVIDENCE =
  "34 boosted decisions / 13 copies all ≥80; band PnL: 80+ −$0.78/trade (242), 70–79 +$0.115/trade (396)";

async function main() {
  const result = await applyRuleChanges(
    [{ field: "regulatoryScoreCap", newValue: 79, reason: REASON, evidence: EVIDENCE }],
    "hermes-v34-regulatory-clamp"
  );
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (regulatoryScoreCap 79). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v34 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
