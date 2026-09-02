/**
 * apply:v41 - one-off activation of the v41 calibration-band sizing change
 * (2026-08-31 report, user-approved: "Proceed with both changes").
 *
 * v41 moved the entry-band multipliers into the C-200 size mapping
 * (paper.ts mapBankroll200Size): <0.20 x1.5, 0.40-0.60 x0.75, >=0.60 x0.5,
 * overall cap $10 -> $20. The v37 rules-layer factors (deadZoneSizeFactor,
 * longshotSizeFactor) must be neutralized at 1.0 so the bands apply exactly
 * once - otherwise long-shots get x2.25 and the dead zone x0.375.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v41.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "deadZoneSizeFactor" as const,
    newValue: 1.0,
    reason:
      "v41: entry-band multipliers moved to the C-200 size mapping (paper.ts mapBankroll200Size) - neutralize the v37 rules-layer dead-zone factor so bands apply exactly once",
    evidence:
      "2026-08-31 calibration (N=1,076 C-200 trades): 0.40-0.60 dead zone -$305 (now x0.75 in paper.ts); >=0.60 premium drag z=-2.49/-2.42 (now x0.5); leaving 0.5 here would double-count to x0.375",
  },
  {
    field: "longshotSizeFactor" as const,
    newValue: 1.0,
    reason:
      "v41: same - long-shot x1.5 now applied in paper.ts mapBankroll200Size; neutralize the rules-layer factor to avoid x2.25",
    evidence:
      "2026-08-31 calibration: <0.20 the only significant positive edge (excess +0.31, z=+4.47, +$155) - sized at x1.5 exactly once, in the C-200 mapping",
  },
];

async function main() {
  const result = await applyRuleChanges(PROPOSALS, "hermes-v41-band-sizing");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (v41 band-sizing neutralization). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v41 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
