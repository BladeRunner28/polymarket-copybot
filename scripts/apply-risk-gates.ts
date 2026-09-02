/**
 * apply:risk-gates — one-off activation of RuleSet v41 with the v41 portfolio
 * risk gates (tuning review #12, 2026-09-01, user-approved: "approved").
 *
 * Adds the octagon-audit §4 gates that the per-market v40 gates lack:
 *   - maxCategoryPositions 40: max open C-200 positions per research category
 *     (Crypto, Tech/AI, Defense/Geopolitics, Healthcare, Energy/Climate,
 *     Finance, Macro/Politics). Unmapped markets ("Other") are heterogeneous
 *     and uncapped. 0 = disabled.
 *   - maxDrawdownPct 0.20: portfolio drawdown gate — halt new copies when
 *     (peak − net worth)/peak > 20%. Peak tracked in data/c200-drawdown.json.
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-risk-gates.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "maxCategoryPositions" as const,
    newValue: 40,
    reason:
      "Per-category concentration gate (octagon-audit §4): cap open C-200 positions per research category so a correlated bundle (all politics, all crypto) can't dominate the book; v40 gate is per-market only",
    evidence:
      "2026-09-01 open book (30 positions): Tech/AI 4, Defense/Geopolitics 3, Macro/Politics 3, Crypto 1, Finance 1, Other 18 (unmapped, heterogeneous, uncapped); 40 = ~18% of the 225 open cap, forces 3+ categories for a full book",
  },
  {
    field: "maxDrawdownPct" as const,
    newValue: 0.2,
    reason:
      "Portfolio drawdown gate (octagon-audit §4): hard pre-execution halt when C-200 net worth is >20% off peak — complements the v40 rate/volume circuit breaker",
    evidence:
      "2026-09-01: C-200 net worth $1,709.23 (principal 1900 + realized -288.63 + open unrealized +97.86) = 10.0% below start; peak seeded from principal in data/c200-drawdown.json",
  },
];

async function main() {
  const result = await applyRuleChanges(PROPOSALS, "hermes-v41-risk-gates");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (v41 risk gates: category concentration + drawdown). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:risk-gates FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
