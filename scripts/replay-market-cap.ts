/**
 * replay-market-cap — the evidence the 2026-09-16 daily report asked for before
 * keeping Change 1 (per-market notional/leg ceiling): replay the last N days of
 * C-200 opens under the cap and show the delta.
 *
 * Counterfactual, not a backtest of strategy: entries are unchanged, we only ask
 * "which of the legs we actually booked would the ceiling have blocked, and what
 * did those legs cost or earn". PnL for a blocked leg is its realizedPnl when
 * finished, or its current unrealizedPnl when still open, valued at the run time
 * of this script (so re-run it later for a settled answer).
 *
 * Run: DATABASE_URL="file:./dev.db" npx tsx scripts/replay-market-cap.ts --days 7
 *      ... --pct 0.10 (default) --legs 2 (default) --cap-usd <override>
 */

import { prisma } from "../src/lib/db";
import { effectiveExposureCap } from "../src/lib/exposure-cap";
import { log } from "../src/lib/redact";
import * as fs from "fs";
import { join } from "path";

const OUT = join(__dirname, "..", "data", "market-cap-replay.json");

function arg(name: string, def: string): string {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

async function main() {
  const days = Number(arg("days", "7"));
  const pct = Number(arg("pct", "0.10"));
  const legsMax = Number(arg("legs", "2"));
  const capOverride = process.argv.includes("--cap-usd") ? Number(arg("cap-usd", "0")) : null;

  const bankroll = await prisma.botBankroll.findUnique({ where: { botId: "BANKROLL_200" } });
  const unreal = await prisma.paperTrade.aggregate({
    where: { botId: "BANKROLL_200", status: "open" },
    _sum: { unrealizedPnl: true },
  });
  const netWorth = (bankroll?.principal ?? 0) + (bankroll?.realizedPnl ?? 0) + (unreal._sum.unrealizedPnl ?? 0);
  const effCap = effectiveExposureCap(1000, netWorth, bankroll?.principal ?? 0);
  const notionalCap = capOverride && capOverride > 0 ? capOverride : pct * effCap;

  const since = new Date(Date.now() - days * 86_400_000);
  const rows = await prisma.paperTrade.findMany({
    where: { botId: "BANKROLL_200", venue: { not: "Kalshi" }, isDemo: false, openedAt: { gte: since } },
    orderBy: { openedAt: "asc" },
    select: {
      id: true,
      marketId: true,
      outcome: true,
      entryPrice: true,
      simulatedPositionSize: true,
      realizedPnl: true,
      unrealizedPnl: true,
      status: true,
      openedAt: true,
    },
  });

  const legs = new Map<string, number>();
  const notional = new Map<string, number>();
  let blocked = 0;
  let blockedLegs = 0;
  let blockedNotional = 0;
  let blockedPnl = 0;
  const blockedRows: Array<Record<string, unknown>> = [];
  const perMarket = new Map<string, { legs: number; notional: number; pnl: number }>();

  let keptPnl = 0;
  let keptNotional = 0;

  for (const r of rows) {
    const size = r.simulatedPositionSize ?? 0;
    const pnl = r.status === "open" ? (r.unrealizedPnl ?? 0) : (r.realizedPnl ?? 0);
    const l = (legs.get(r.marketId) ?? 0) + 1;
    const n = (notional.get(r.marketId) ?? 0) + size;
    const legHit = legsMax > 0 && l > legsMax;
    const notionalHit = notionalCap > 0 && n > notionalCap;
    if (legHit || notionalHit) {
      blocked++;
      blockedLegs++;
      blockedNotional += size;
      blockedPnl += pnl;
      blockedRows.push({
        marketId: r.marketId,
        outcome: r.outcome,
        entryPrice: r.entryPrice,
        size,
        pnl,
        status: r.status,
        why: legHit ? `leg ${l} > ${legsMax}` : `notional ${n.toFixed(2)} > ${notionalCap.toFixed(2)}`,
      });
      // blocked legs do NOT consume the budget
      continue;
    }
    legs.set(r.marketId, l);
    notional.set(r.marketId, n);
    keptPnl += pnl;
    keptNotional += size;
    const m = perMarket.get(r.marketId) ?? { legs: 0, notional: 0, pnl: 0 };
    m.legs = l;
    m.notional = n;
    m.pnl += pnl;
    perMarket.set(r.marketId, m);
  }

  const totalPnl = keptPnl + blockedPnl;
  const worst = [...perMarket.entries()].sort((a, b) => a[1].pnl - b[1].pnl).slice(0, 5);
  const worstBlocked = [...blockedRows].sort((a, b) => Number(a.pnl) - Number(b.pnl)).slice(0, 5);

  const out = {
    generatedAt: new Date().toISOString(),
    window: { days, since: since.toISOString() },
    thresholds: { maxMarketLegsPerMarketId: legsMax, maxMarketNotionalPctOfCap: pct, notionalCapUsd: Math.round(notionalCap * 100) / 100, effectiveCapUsd: Math.round(effCap * 100) / 100, netWorth: Math.round(netWorth * 100) / 100, capOverride },
    legs: rows.length,
    blockedLegs,
    blockedNotionalUsd: Math.round(blockedNotional * 100) / 100,
    blockedPnlUsd: Math.round(blockedPnl * 100) / 100,
    bookedPnlUsd: Math.round(keptPnl * 100) / 100,
    actualWindowPnlUsd: Math.round(totalPnl * 100) / 100,
    deltaUsd: Math.round(-blockedPnl * 100) / 100,
    marketsWithMultipleLegs: [...perMarket.values()].filter((m) => m.legs > 1).length,
    worstMarketsUnderCap: worst.map(([id, m]) => ({ marketId: id, ...m, pnl: Math.round(m.pnl * 100) / 100 })),
    blockedSample: worstBlocked,
  };
  fs.writeFileSync(OUT, JSON.stringify(out, null, 2));

  log(`replay-market-cap — last ${days}d, thresholds legs<=${legsMax}, notional<=$${notionalCap.toFixed(2)} (${(pct * 100).toFixed(0)}% of $${effCap.toFixed(0)} cap; NW $${netWorth.toFixed(0)})`);
  log(`  ${rows.length} legs booked in the window; ceiling would have blocked ${blockedLegs} legs across ${new Set(blockedRows.map((b) => b.marketId)).size} markets`);
  log(`  blocked notional $${blockedNotional.toFixed(2)} | blocked PnL $${blockedPnl.toFixed(2)} | actual window PnL $${totalPnl.toFixed(2)} -> counterfactual $${keptPnl.toFixed(2)} (delta $${(-blockedPnl).toFixed(2)})`);
  if (worstBlocked.length) {
    log(`  worst blocked legs:`);
    for (const b of worstBlocked) log(`    ${String(b.marketId).slice(0, 46)} $${Number(b.size).toFixed(2)} -> $${Number(b.pnl).toFixed(2)} (${b.status}) [${b.why}]`);
  }
  log(`  wrote ${OUT}`);
  process.exit(0);
}

main().catch((e) => {
  log(`replay-market-cap FAILED: ${e instanceof Error ? e.message : e}`);
  process.exit(1);
});
