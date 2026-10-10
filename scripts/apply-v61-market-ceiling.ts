/**
 * apply:v61 — raise the v55 per-market notional ceiling 10% → 20% of the effective
 * exposure cap (2026-10-09 in-thread approval: `v55-ceiling-vs-kelly-decision`
 * option (a); the card's own note carried "RECOMMENDATION: (a) 0.20").
 *
 *   maxMarketNotionalPctOfCap  0.10 → 0.20
 *
 * APPROVED INTENT (card, 2026-09-19): the ceiling vetoed 11 of 12 Kelly admits
 * because two legs at `kellyMaxSizeUsd` $100 legally exceed 10% of the then-cap
 * $1,251.20 ($125.12), making the 2-leg allowance unusable on the only band with
 * a positive edge. (a) restores coherence at the cap FLOOR — 20% × $1,000 base =
 * $200 = exactly 2 × $100.
 *
 * MEASURED: THIS DELTA IS INERT TODAY, AND THE CARD'S PREMISE IS ALREADY RESOLVED.
 * The cap grew $1,251 → $3,971, so 10% = $397 > the $200 maximum notional two legs
 * can reach (maxMarketLegsPerMarketId 2 × kellyMaxSizeUsd $100). The notional clause
 * is therefore structurally unreachable and has fired ZERO times since 2026-09-19:
 *
 *   npx tsx scripts/replay-market-cap.ts --days 30 --pct 0.10 --legs 2
 *   npx tsx scripts/replay-market-cap.ts --days 30 --pct 0.20 --legs 2
 *     → IDENTICAL results: 16 legs blocked across 10 markets, every one
 *       `[leg 3 > 2]` (the LEGS clause), blocked notional $423.12.
 *   monitor log: 0 `v55 per-market cap (notional …)` lines since the cap rose
 *       (21 lifetime, all at the $125.12 ceiling, newest log line 49,028 vs the
 *       2026-10-07 window header at 96,877).
 *
 * So (a) ships for coherence, not for effect: it cannot move a single figure at the
 * current cap and it restores the approved intent if the cap ever contracts below
 * $2,000 (10% would re-bind, 20% would not).
 *
 * LIVE CONSTRAINT IS A DIFFERENT KNOB: the 56 lifetime / 16-in-30d vetoes are all
 * `legs 3 > max 2` (`maxMarketLegsPerMarketId`), which (a) does NOT touch, and those
 * blocked legs were net +$892.55 in the 30d window (replay: actual $4,795.31 vs
 * counterfactual $3,902.76). That is a separate rail relaxation and needs its own
 * approval — this script does not touch it.
 *
 * Run (apply):  cd ~/polymarket-copybot && DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v61-market-ceiling.ts
 * Run (probe):  … --dry-run     # prints the live consequence, writes NOTHING
 * Revert:       apply-v62 with maxMarketNotionalPctOfCap back to 0.10
 */

import { prisma } from "../src/lib/db";
import { applyRuleChanges } from "../src/lib/rules";
import { effectiveExposureCap } from "../src/lib/exposure-cap";
import { log } from "../src/lib/redact";

const DRY = process.argv.includes("--dry-run");
const PCT = 0.2;

async function main() {
  const rs = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (!rs) throw new Error("no active RuleSet");
  const rules = JSON.parse(rs.rulesJson) as Record<string, number | string>;
  const before = Number(rules.maxMarketNotionalPctOfCap ?? 0);
  const legsMax = Number(rules.maxMarketLegsPerMarketId ?? 0);
  const kellyMax = Number(rules.kellyMaxSizeUsd ?? 0);
  const maxReachable = legsMax * kellyMax;

  const bankroll = await prisma.botBankroll.findUnique({ where: { botId: "BANKROLL_200" } });
  const unreal = await prisma.paperTrade.aggregate({
    where: { botId: "BANKROLL_200", status: "open" },
    _sum: { unrealizedPnl: true },
  });
  const netWorth =
    (bankroll?.principal ?? 0) + (bankroll?.realizedPnl ?? 0) + (unreal._sum.unrealizedPnl ?? 0);
  const effCap = effectiveExposureCap(1000, netWorth, bankroll?.principal ?? 0);
  const ceilNow = before * effCap;
  const ceilNew = PCT * effCap;

  log(`apply:v61 before — RuleSet v${rs.version} maxMarketNotionalPctOfCap=${before}`);
  log(`  effective exposure cap $${effCap.toFixed(2)} (net worth $${netWorth.toFixed(2)})`);
  log(`  notional ceiling: 10% = $${ceilNow.toFixed(2)} → 20% = $${ceilNew.toFixed(2)}`);
  log(
    `  max notional two legs can reach: ${legsMax} × kellyMaxSizeUsd $${kellyMax} = $${maxReachable.toFixed(2)}`
  );
  log(
    `  reachable today? ${ceilNow >= maxReachable ? "NO — the notional clause cannot fire at either pct" : "YES at 10%, no at 20%"}`
  );
  log(`  replay 30d: identical at 0.10 and 0.20 (16 legs blocked, all [leg 3 > 2]; 0 by notional).`);
  log(
    `  blast radius: only C-200 per-market notional accumulation. Legs clause, v45/v47/v58 rails, ` +
      `Kelly sizing, STANDARD book and every reported figure are untouched.`
  );

  if (DRY) {
    log("--dry-run: nothing written.");
    return;
  }

  const result = await applyRuleChanges(
    [
      {
        field: "maxMarketNotionalPctOfCap" as const,
        newValue: PCT,
        reason:
          "v61 (user-approved 2026-10-09, v55-ceiling-vs-kelly-decision option (a)): raise the v55 per-market notional ceiling 0.10 -> 0.20 of the effective exposure cap, so the 2-leg allowance is coherent with kellyMaxSizeUsd at the cap floor (20% x $1,000 = $200 = 2 x $100)",
        evidence:
          `Measured INERT at the current cap — shipped for coherence, not effect. Cap $${effCap.toFixed(2)}: 10% = $${ceilNow.toFixed(2)} already exceeds the $${maxReachable.toFixed(2)} maximum two legs can reach (maxMarketLegsPerMarketId ${legsMax} x kellyMaxSizeUsd $${kellyMax}), so the notional clause is structurally unreachable; 0 notional-clause vetoes since 2026-09-19 (21 lifetime, all at the $125.12 ceiling) and replay-market-cap at 0.10 vs 0.20 is IDENTICAL (16 legs blocked, all [leg 3 > 2]). The card's live constraint is the LEGS clause (16 vetoes in 30d, blocked legs net +$892.55) and is NOT changed here. Effect if the cap contracts below $2,000: 10% would re-bind, 20% would not. Revert: v62 with 0.10.`,
      },
    ],
    "hermes-v61-market-ceiling-approved"
  );
  if (!result) {
    log("No changes applied.");
    return;
  }
  log(`RuleSet v${result.newVersion} activated — maxMarketNotionalPctOfCap ${before} → ${PCT}.`);
}

main()
  .catch((e) => {
    log(`apply:v61 FAILED: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
