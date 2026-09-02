/**
 * apply:v30 — one-off tweak: raise maxOpenPositions 100 → 150 (user request
 * 2026-08-28). Same versioned, audited path as apply-v29.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v30.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const REASON =
  "Raise open-position cap 100→150 (user request): keep fresh 70–79 sweet-spot and short-TTR copies flowing while the v29 stale-exit sweep drains the book";
const EVIDENCE = "Cap 100 blocked all new BANKROLL_200 copies with ~276 open; 150 still bounds the book";

async function main() {
  const result = await applyRuleChanges(
    [{ field: "maxOpenPositions", newValue: 150, reason: REASON, evidence: EVIDENCE }],
    "hermes-v29-tweak"
  );
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (maxOpenPositions 100 → 150). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v30 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
