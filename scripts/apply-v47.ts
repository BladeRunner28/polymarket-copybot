/**
 * apply:v47 — one-off activation of RuleSet v47 with the 2026-09-03 daily
 * report recommendation 2(b) (user-approved: "I approve of the
 * recommendations").
 *
 * v47 adds the C-200 high-side entry cap field:
 *   - c200MaxEntryPrice 0.80: per-leg BANKROLL_200 gate in score-trades.ts —
 *     entries ≥ 0.80 skip the C-200 book (main + short-TTR lanes). NOT via
 *     the shared maxEntryPrice (symmetric [1−max, max] — lowering it to 0.80
 *     would block <0.20 long-shots, the only +$ band, z=+4.05).
 * Daily-report rec 1 (20:00/23:00 ET gate) and rec 2(a)/(c) (dead-zone cap
 * cut ×0.5, long-shots at ×1.5 full cap) were ALREADY live (v41/v42) —
 * verified, no change. Watch item (Aug 25–27 zero trades) = known Aug 17–28
 * sidecar-outage tail (silent-skip strings under rules v25 in monitor log).
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v47.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "c200MaxEntryPrice" as const,
    newValue: 0.8,
    reason:
      "C-200 high-side entry cap (2026-09-03 daily report rec 2b, approved): hard-cap new copy entries at ≤0.80 — the 0.80–1.01 band is significant premium drag (z=−2.48, excess −8.5pp); per-leg gate so the symmetric maxEntryPrice (0.95) can't kill the <0.20 long-shot edge",
    evidence:
      "Calibration N=1,131 (2026-09-03 18:02 CDT): 0.80–1.01 excess −8.5pp z=−2.48 (paying ~85¢ for an 80% coin); <0.20 z=+4.05 (+$143.82) must stay open; STANDARD already capped at 0.85 (v44)",
  },
];

async function main() {
  const result = await applyRuleChanges(PROPOSALS, "hermes-v47-daily-report");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (c200MaxEntryPrice 0.80). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v47 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
