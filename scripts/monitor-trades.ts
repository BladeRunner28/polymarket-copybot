/**
 * monitor:trades — detect new trades from tracked wallets since the last
 * check and store them as ObservedTrade rows (deduped).
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { log, logError } from "../src/lib/redact";

const MONITOR_HOURS = Number(process.env.MONITOR_HOURS ?? 24);

async function main() {
  const adapter = getAdapter();
  // Read-time cap: only the top-N tracked wallets by score are monitored,
  // regardless of how many carry status=track (cap can drift between scans).
  const MAX_TRACKED = Number(process.env.MAX_TRACKED_WALLETS ?? 25);
  const tracked = await prisma.walletProfile.findMany({
    where: adapter.isDemo ? { status: "track" } : { status: "track", isDemo: false },
    orderBy: { globalScore: "desc" },
    take: MAX_TRACKED,
  });
  if (tracked.length === 0) {
    log("No tracked wallets. Run scan:wallets first (wallets need status=track).");
    return;
  }

  log(`Monitoring ${tracked.length} tracked wallets for new trades (last ${MONITOR_HOURS}h)${adapter.isDemo ? " [DEMO DATA]" : ""}…`);
  const since = Date.now() - MONITOR_HOURS * 3600_000;
  let newTrades = 0;
  const failures: string[] = [];

  for (const w of tracked) {
    try {
      const activity = await adapter.fetchWalletActivity(w.address, Math.ceil(MONITOR_HOURS / 24) || 1);
      for (const t of activity) {
        if (t.timestamp.getTime() < since) continue;
        if (t.side !== "BUY") continue; // copy entries only, not exits
        try {
          // Detected price: current market price at detection time.
          let detectedPrice = t.price;
          try {
            const m = await adapter.fetchMarket(t.marketId);
            const p = t.outcome === "NO" ? m.noPrice : m.yesPrice;
            if (p !== undefined) detectedPrice = p;
            await prisma.marketSnapshot.create({
              data: {
                marketId: m.marketId,
                conditionId: m.conditionId,
                question: m.question,
                category: m.category,
                yesPrice: m.yesPrice,
                noPrice: m.noPrice,
                bestBid: m.bestBid,
                bestAsk: m.bestAsk,
                spread: m.spread,
                liquidity: m.liquidity,
                volume: m.volume,
                timeToResolution: m.timeToResolutionHours,
                isDemo: adapter.isDemo,
                rawMarketJson: "{}",
              },
            });
          } catch {
            // Market lookup failure is non-fatal for detection; scoring will retry.
          }
          await prisma.observedTrade.create({
            data: {
              walletAddress: w.address,
              marketId: t.marketId,
              conditionId: t.conditionId,
              marketQuestion: t.marketQuestion,
              marketCategory: t.marketCategory,
              outcome: t.outcome,
              side: t.side,
              walletEntryPrice: t.price,
              detectedPrice,
              size: t.size,
              timestamp: t.timestamp,
              rawTradeJson: "{}",
              isDemo: adapter.isDemo,
            },
          });
          newTrades++;
        } catch (e) {
          // Unique constraint = already seen; anything else is real.
          if (!(e instanceof Error && e.message.includes("Unique constraint"))) throw e;
        }
      }
    } catch (e) {
      failures.push(`${w.address}: ${e instanceof Error ? e.message : e}`);
    }
  }

  log(`Trade monitor complete: ${newTrades} new observed trades.`);
  if (failures.length) {
    logError(`Failures (${failures.length}):\n` + failures.slice(0, 5).join("\n"));
    if (newTrades === 0 && failures.length === tracked.length) {
      throw new Error("All wallet activity fetches failed — see errors above.");
    }
  }
}

main()
  .catch((e) => {
    logError("monitor:trades FAILED:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
