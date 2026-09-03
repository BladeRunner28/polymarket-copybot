/**
 * apply:v43 — one-off activation of RuleSet v43 with the 2026-09-01 daily
 * report recommendations (user-approved 2026-09-02: "Make all
 * recommendations, including the capacity recommendation").
 *
 * Context: RuleSet v42 was the AUTO rule-updater's overnight tighten (EOD
 * 2026-09-01 22:02 CDT): maxSpread 0.08→0.064, minLiquidity→750,
 * maxPriceDrift 0.0034→0.0025. The approved recommendations were computed
 * against the pre-v42 values and explicitly override the auto-tighten:
 *   - maxSpread 0.064 → 0.06  (Rec 2: protect the 0.20–0.40 positive-edge
 *     band z=+2.62 whose edge is eroded by spread costs)
 *   - maxPriceDrift 0.0025 → 0.004 (capacity rec: drift is the binding
 *     constraint on C-200 throughput — 30 open, $1.4k+ idle cash)
 * Dead-zone sizing ×0.75 → ×0.50 is a CODE change (paper.ts mapBankroll200Size,
 * labeled v42 change-set) — not a ruleset field.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v43.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "maxSpread" as const,
    newValue: 0.06,
    reason:
      "Tighten spread gate 0.064 → 0.06 (2026-09-01 daily report Rec 2): the 0.20–0.40 band has a significant positive price edge (z=+2.62, p=0.009) yet is dollar-negative (−$105.69) — sign-flip consistent with spread/premium eroding the edge",
    evidence:
      "Calibration N=1,124 (2026-09-01 18:02 CDT): v40 evidence wide-spread trades avg −$3.06 vs +$5.06 tight; spread-skips only 4.8% of skips at 0.08 → low throughput cost",
  },
  {
    field: "maxPriceDrift" as const,
    newValue: 0.004,
    reason:
      "Capacity rec (user-approved): loosen drift 0.0025 → 0.004 — signal flow (drift) is the binding constraint on C-200 throughput, not caps or capital (0 cap-skips, ~$1.4k idle cash); supersedes the RuleSet v42 auto-updater tighten of 2026-09-01 EOD",
    evidence:
      "Tuning review #12: 'loosen drift →0.004 only if C-200 stagnates' — C-200 open book 30/225 with idle cash; user approved making the capacity recommendation now (2026-09-02)",
  },
];

async function main() {
  const result = await applyRuleChanges(PROPOSALS, "hermes-v42-daily-report");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (maxSpread 0.06, maxPriceDrift 0.004). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v43 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
