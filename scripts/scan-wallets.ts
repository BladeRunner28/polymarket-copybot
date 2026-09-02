/**
 * scan:wallets — profile wallets from the latest leaderboard scan: fetch 30d
 * activity, compute scores, set track/watch/ignore status.
 * WALLET_SCAN_LIMIT caps how many wallets are profiled per run (API-friendly).
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { getActiveRules } from "../src/lib/rules";
import { scoreWallet, walletStatus } from "../src/lib/scoring/wallet";
import { log, logError } from "../src/lib/redact";

const SCAN_LIMIT = Number(process.env.WALLET_SCAN_LIMIT ?? 25);
const LOOKBACK_DAYS = 30;

async function main() {
  const adapter = getAdapter();
  const { rules } = await getActiveRules();

  // Profile the least-recently-scanned wallets first. Demo wallets are never
  // profiled against the live API (their addresses don't exist on-chain).
  const wallets = await prisma.walletProfile.findMany({
    where: adapter.isDemo ? {} : { isDemo: false },
    orderBy: [{ lastScannedAt: { sort: "asc", nulls: "first" } }, { sourceRank: "asc" }],
    take: SCAN_LIMIT,
  });
  if (wallets.length === 0) {
    log("No wallets to scan. Run `npm run scan:leaderboard` first.");
    return;
  }

  log(`Profiling ${wallets.length} wallets (${LOOKBACK_DAYS}d activity)${adapter.isDemo ? " [DEMO DATA]" : ""}…`);
  let profiled = 0;
  const failures: string[] = [];

  for (const w of wallets) {
    try {
      const trades = await adapter.fetchWalletActivity(w.address, LOOKBACK_DAYS);
      const score = scoreWallet(trades, rules);
      const { status, reason } = walletStatus(score, rules);
      await prisma.walletProfile.update({
        where: { id: w.id },
        data: {
          status,
          roi30d: score.roi30d,
          consistencyScore: score.consistencyScore,
          copyabilityScore: score.copyabilityScore,
          oneHitWonderPenalty: score.oneHitWonderPenalty,
          globalScore: score.globalScore,
          bestCategory: score.bestCategory,
          categoryStrengthsJson: JSON.stringify(score.categoryStrengths),
          averageTradeSize: score.averageTradeSize,
          tradeCount30d: score.tradeCount30d,
          resolvedTradeCount30d: score.resolvedTradeCount30d,
          winRate30d: score.winRate30d,
          averageLiquidity: score.averageLiquidity,
          averageSpread: score.averageSpread,
          averageEntryTiming: score.averageEntryTiming,
          copyabilityNotes: `${reason}. ${score.copyabilityNotes}`,
          riskNotes: score.riskNotes,
          lastScannedAt: new Date(),
        },
      });
      profiled++;
    } catch (e) {
      failures.push(`${w.address}: ${e instanceof Error ? e.message : e}`);
    }
  }

  // Cap tracked wallets: keep only the strongest MAX_TRACKED as `track`,
  // demote the rest to `watch` (prevents monitor/score pipeline flooding).
  const MAX_TRACKED = Number(process.env.MAX_TRACKED_WALLETS ?? 25);
  const tracked = await prisma.walletProfile.findMany({
    where: { status: "track", ...(adapter.isDemo ? {} : { isDemo: false }) },
    orderBy: { globalScore: "desc" },
  });
  if (tracked.length > MAX_TRACKED) {
    const demote = tracked.slice(MAX_TRACKED);
    await prisma.walletProfile.updateMany({
      where: { id: { in: demote.map((w) => w.id) } },
      data: { status: "watch" },
    });
    log(`Tracked-wallet cap: kept top ${MAX_TRACKED}, demoted ${demote.length} to watch.`);
  }

  // v33 (tuning review #9): demo wallets are inert in live mode (monitor only
  // watches isDemo:false) but are excluded from the cap query above, so stale
  // demo `track` rows can accumulate and inflate the tracked count (observed:
  // 31 marked track vs 25 cap = 25 live + 6 demo). Demote them so the count is
  // truthful. Non-destructive — data is retained, just no longer "tracked".
  if (!adapter.isDemo) {
    const demoDemoted = await prisma.walletProfile.updateMany({
      where: { status: "track", isDemo: true },
      data: { status: "watch" },
    });
    if (demoDemoted.count > 0) {
      log(`Demo-track cleanup: demoted ${demoDemoted.count} demo wallets to watch.`);
    }
  }

  if (failures.length) {
    logError(`Failures (${failures.length}):\n` + failures.slice(0, 5).join("\n"));
    if (profiled === 0) {
      throw new Error("All wallet profile fetches failed — see errors above.");
    }
  }
  // Completion line last so `tail -N` log capture always includes it.
  log(`Wallet scan complete: ${profiled}/${wallets.length} profiled.`);
}

main()
  .catch((e) => {
    logError("scan:wallets FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
