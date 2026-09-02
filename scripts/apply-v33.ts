/**
 * apply:v33 — one-off activation of RuleSet v33 (hard max-age stale exit:
 * staleExitHardHours 168). Fixes v29 tier-1 recycling that can never fire
 * (every position surviving 72h has drifted ≥5%; the real drag is stuck
 * winners on non-resolving markets). Versioned, audited path.
 * See drafts/v33-draft.md.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v33.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const REASON =
  "Add staleExitHardHours 168 (hard max-age recycle): v29 tier-1 (72h + <5% move) cannot fire — all 80 open C-200 positions ≥72h have drifted ≥5% (avg +30%, some 37d old); tier-2 closes any C-200 hold older than 7 days at last price, freeing dead capital";
const EVIDENCE =
  "Aug 29 tuning review #4 (only 1 recycle all window). DB: 80 open >168h, $202.36 notional, +$112.08 unrealized, winMove +7.8%..+136.9%; 0/80 qualify under v29 tier-1";

async function main() {
  const result = await applyRuleChanges(
    [{ field: "staleExitHardHours", newValue: 168, reason: REASON, evidence: EVIDENCE }],
    "hermes-v33-stale-exit-fix"
  );
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (staleExitHardHours 168). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v33 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
