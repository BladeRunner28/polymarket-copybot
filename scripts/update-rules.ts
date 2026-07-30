/**
 * update:rules — run the self-improvement pass. Applies evidence-based rule
 * changes automatically (paper trading only) and logs every change.
 */

import { prisma } from "../src/lib/db";
import { runRuleUpdate } from "../src/lib/rule-updater";
import { log, logError } from "../src/lib/redact";

async function main() {
  const result = await runRuleUpdate();
  if (!result) {
    log("No rule changes warranted (insufficient evidence or performance within bounds).");
    return;
  }
  log(`Rules updated to v${result.newVersion}:`);
  for (const c of result.changes) {
    log(`  - ${String(c.field)} -> ${c.newValue}: ${c.reason} [${c.evidence}]`);
  }
}

main()
  .catch((e) => {
    logError("update:rules FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
