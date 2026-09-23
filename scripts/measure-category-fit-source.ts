/**
 * measure-category-fit-source — fetch (and cache) the wallet activity samples
 * the class-swap card needs, then measure what a category fit built on the REAL
 * class would be worth.
 *
 * WHY A FETCH IS NEEDED AT ALL: a wallet's per-category win rate is derived from
 * its resolved ACTIVITY SAMPLE (`WalletActivityTrade.won`) at scan time and is
 * never stored, so the token-vs-class comparison cannot be reconstructed from
 * SQLite. This script runs the SAME adapter call the scanner runs
 * (fetchWalletActivity, 30d) and records the bucket maps for three keys —
 * the raw event-slug token (what production reads today), the coarse class and
 * the fine class (src/lib/market-category.ts) — mirroring the bucket definition
 * in src/lib/scoring/wallet.ts:112-126 exactly (winRate = wins / ALL trades in
 * the bucket, unresolved included), and cross-checks the token map against
 * scoreWallet's own output so the mirror is verified, not assumed.
 *
 * READ-ONLY: no DB writes, no scoring changes. Cache is incremental and
 * resumable (re-running skips wallets already in the file).
 *
 *   npx tsx scripts/measure-category-fit-source.ts            # all 198 settles-bearing wallets
 *   npx tsx scripts/measure-category-fit-source.ts --limit 5  # smoke test
 *   npx tsx scripts/measure-category-fit-source.ts --refresh  # ignore the cache
 *
 * Output: data/category-fit-source.json
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { getActiveRules } from "../src/lib/rules";
import { scoreWallet } from "../src/lib/scoring/wallet";
import { WalletActivityTrade } from "../src/lib/types";
import * as fs from "fs";
import { join } from "path";

const ROOT = join(__dirname, "..");
const CACHE = join(ROOT, "data", "category-fit-source.json");
const LIMIT = Number((process.argv.find((a) => a.startsWith("--limit")) ?? "").split("=")[1] ?? 0) || 0;
const REFRESH = process.argv.includes("--refresh");

type Bucket = {
  trades: number;
  wins: number;
  winRate: number;
  resolvedTrades: number;
  resolvedWins: number;
  resolvedWinRate: number;
  pnl: number;
};

type WalletRecord = {
  address: string;
  fetchedAt: string;
  nTrades: number;
  nResolved: number;
  token: Record<string, Bucket>;
  coarse: Record<string, Bucket>;
  fine: Record<string, Bucket>;
  bucketDefinition: string;
};

/** Mirrors src/lib/scoring/wallet.ts:109-131 for an arbitrary key function. */
function buckets(trades: WalletActivityTrade[], key: (t: WalletActivityTrade) => string) {
  const acc: Record<string, { trades: number; wins: number; resolved: number; resolvedWins: number; pnl: number }> = {};
  for (const t of trades) {
    const k = key(t);
    acc[k] ??= { trades: 0, wins: 0, resolved: 0, resolvedWins: 0, pnl: 0 };
    acc[k].trades++;
    if (t.resolved) {
      acc[k].resolved++;
      if ((t.pnl ?? 0) > 0) {
        acc[k].wins++;
        acc[k].resolvedWins++;
      }
    }
    acc[k].pnl += t.pnl ?? 0;
  }
  const out: Record<string, Bucket> = {};
  for (const [k, v] of Object.entries(acc)) {
    out[k] = {
      trades: v.trades,
      wins: v.wins,
      winRate: v.trades ? v.wins / v.trades : 0,
      resolvedTrades: v.resolved,
      resolvedWins: v.resolvedWins,
      resolvedWinRate: v.resolved ? v.resolvedWins / v.resolved : 0,
      pnl: Math.round(v.pnl * 100) / 100,
    };
  }
  return out;
}

async function main() {
  const adapter = getAdapter();
  const { rules } = await getActiveRules();

  const legWallets = await prisma.paperTrade.findMany({
    where: { isDemo: false, status: { in: ["closed", "resolved"] }, realizedPnl: { not: null } },
    select: { walletAddress: true },
    distinct: ["walletAddress"],
  });
  const all = legWallets.map((w) => w.walletAddress).sort();
  const targets = LIMIT ? all.slice(0, LIMIT) : all;

  let cache: { generatedAt?: string; bucketDefinition?: string; wallets: Record<string, WalletRecord> } = {
    wallets: {},
  };
  if (!REFRESH && fs.existsSync(CACHE)) {
    cache = JSON.parse(fs.readFileSync(CACHE, "utf-8"));
    cache.wallets ??= {};
  }
  cache.bucketDefinition = "winRate = wins / ALL bucket trades (unresolved included) — mirrors src/lib/scoring/wallet.ts:112-126";

  const todo = targets.filter((a) => !cache.wallets[a]);
  console.log(
    `${all.length} wallet(s) hold a settled leg; ${todo.length} to fetch (${targets.length - todo.length} cached)${adapter.isDemo ? " [DEMO]" : ""}…`
  );

  let done = 0;
  let tokenMirrorMismatches = 0;
  let failed = 0;
  for (const address of todo) {
    try {
      const trades = await adapter.fetchWalletActivity(address, 30);
      const token = buckets(trades, (t) => t.marketCategory ?? "uncategorized");
      const coarse = buckets(trades, (t) => t.marketCategoryClass ?? "uncategorized");
      const fine = buckets(trades, (t) => t.marketCategoryFine ?? "uncategorized");

      // Cross-check the mirror against production's own computation.
      const score = scoreWallet(trades, rules);
      for (const [cat, v] of Object.entries(score.categoryStrengths)) {
        const mine = token[cat];
        if (!mine || Math.abs(mine.winRate - v.winRate) > 1e-9 || mine.trades !== v.trades) {
          tokenMirrorMismatches++;
        }
      }

      cache.wallets[address] = {
        address,
        fetchedAt: new Date().toISOString(),
        nTrades: trades.length,
        nResolved: trades.filter((t) => t.resolved).length,
        token,
        coarse,
        fine,
        bucketDefinition: cache.bucketDefinition,
      };
      done++;
      if (done % 10 === 0) {
        fs.writeFileSync(CACHE, JSON.stringify(cache, null, 1));
        console.log(`  ${done}/${todo.length} fetched…`);
      }
    } catch (e) {
      failed++;
      console.log(`  FAILED ${address}: ${e instanceof Error ? e.message : e}`);
    }
  }

  cache.generatedAt = new Date().toISOString();
  fs.writeFileSync(CACHE, JSON.stringify(cache, null, 1));
  console.log(
    `\nwrote ${CACHE}: ${Object.keys(cache.wallets).length} wallet(s) cached (${done} fetched this run, ${failed} failed)`
  );
  console.log(`token-mirror cross-check vs scoreWallet.categoryStrengths: ${tokenMirrorMismatches} mismatch(es)`);
  if (tokenMirrorMismatches > 0) process.exitCode = 1;
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
