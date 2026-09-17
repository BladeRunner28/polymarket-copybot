/**
 * apply:v55 — per-market concentration ceiling (2026-09-16 C-200 daily report
 * Change 1, user-approved).
 *
 *   maxMarketLegsPerMarketId    0 → 2     (max open C-200 legs in one marketId)
 *   maxMarketNotionalPctOfCap   0 → 0.10  (ceiling = 10% of the effective cap)
 *
 * WHY: `maxMarketSlugPositions` counts the research CATEGORY, not the market — a
 * slug wraps many markets, so nothing capped legs inside one marketId. With v54's
 * 2.5x long-shot factor the <0.20 band's average clip is ~$33 (vs $2.48 in the
 * dead zone), so a single binary can now absorb $250+. The last 7 days' loss was
 * 76% two markets (−$218.19: fed-increase-25bps −$92.18, ucl-nap-ars-spread
 * −$126.01), each built from ~5 legs.
 *
 * EVIDENCE — scripts/replay-market-cap.ts, replaying the last 7 days of C-200
 * opens under legs<=2 / notional<=10% of the cap ($135.54):
 *   298 legs booked → the ceiling blocks 13 legs across 7 markets,
 *   blocked notional $283.12, blocked PnL −$144.01,
 *   window PnL −$441.53 → counterfactual −$297.52 (delta +$144.01).
 *   Every worst blocked leg is a leg-3+ accumulation: the Fed market (−$50.04,
 *   −$10.46), elon-musk-of-tweets (−$22.22, −$19.95), dtf-stpt-emmys (−$18.32).
 * Re-run: DATABASE_URL="file:./dev.db" npx tsx scripts/replay-market-cap.ts --days 7
 *
 * SCOPE: C-200 only (STANDARD's book is a different design and its own review).
 * The ceiling is checked on the FINAL size — after Kelly/band sizing — so a late
 * resize cannot slip past it, and it is enforced per leg (STANDARD's leg of the
 * same decision is unaffected).
 *
 * REVERT: set both fields to 0 (legacy semantics — the defaults in DEFAULT_RULES).
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v55.ts
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { log, logError } from "../src/lib/redact";

const PROPOSALS = [
  {
    field: "maxMarketLegsPerMarketId" as const,
    newValue: 2,
    reason:
      "v55 Change 1 (user-approved 2026-09-16): cap open C-200 legs per marketId at 2 — slug caps count categories, so nothing bounded accumulation inside one market",
    evidence:
      "7-day replay (scripts/replay-market-cap.ts): 298 legs → 13 blocked, all leg-3+ accumulations, blocked PnL −$144.01 → counterfactual window PnL −$297.52 vs actual −$441.53. The week's loss was 76% two markets (fed −$92.18, ucl-nap-ars −$126.01), each ~5 legs.",
  },
  {
    field: "maxMarketNotionalPctOfCap" as const,
    newValue: 0.1,
    reason:
      "v55 Change 1 (user-approved 2026-09-16): per-market notional ceiling at 10% of the effective exposure cap — expressed as a fraction so it scales with the cap instead of silently loosening as equity grows",
    evidence:
      "At today's $1,355 cap that is $135.54 per market. The replay's blocked set was driven by the leg count, so the notional ceiling is the second, independent backstop (it binds first on a single oversized clip). Revert = both fields 0.",
  },
];

async function main() {
  const before = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (before) {
    const j = JSON.parse(before.rulesJson) as Record<string, unknown>;
    log(
      `apply:v55 before — v${before.version} maxMarketLegsPerMarketId=${j.maxMarketLegsPerMarketId ?? "(unset→0)"} ` +
        `maxMarketNotionalPctOfCap=${j.maxMarketNotionalPctOfCap ?? "(unset→0)"} ` +
        `(maxMarketSlugPositions=${j.maxMarketSlugPositions}, category-level, unchanged)`
    );
  }
  const result = await applyRuleChanges(PROPOSALS, "hermes-v55-daily-rep-change1-approved");
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated (per-market ceiling: legs ≤ 2, notional ≤ 10% of the effective cap). RuleChange audit row written.`);
}

main()
  .catch((e) => {
    logError("apply:v55 FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
