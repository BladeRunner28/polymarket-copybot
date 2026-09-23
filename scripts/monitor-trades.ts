/**
 * monitor:trades — detect new trades from tracked wallets since the last
 * check and store them as ObservedTrade rows (deduped).
 */

import { prisma } from "../src/lib/db";
import { getAdapter } from "../src/lib/adapters";
import { log, logError } from "../src/lib/redact";
import {
  MAX_OBSERVE,
  MAX_TRACKED,
  OBSERVE_LOOKBACK_DAYS,
  copyWalletSet,
  observeEligibleCount,
  observeOnlyWallets,
  stampObserved,
} from "../src/lib/wallet-universe";

const MONITOR_HOURS = Number(process.env.MONITOR_HOURS ?? 24);

type MonitorWallet = { address: string; observationOnly: boolean };

async function main() {
  const adapter = getAdapter();
  // v61 (tuning review #33 rec 1, user-approved 2026-09-22): the monitored
  // universe is now COPY ∪ OBSERVE. COPY is the read-time top-N cap that already
  // existed (only these wallets can book a copy); OBSERVE adds the wallets the
  // hourly cap rotated out but that held `track` inside the trailing window —
  // their trades are stored with observationOnly=true and never scored.
  const copyWallets = await copyWalletSet(adapter.isDemo);
  if (copyWallets.length === 0) {
    log("No tracked wallets. Run scan:wallets first (wallets need status=track).");
    return;
  }
  const observeWallets = await observeOnlyWallets(adapter.isDemo);
  if (observeWallets.length >= MAX_OBSERVE) {
    // The sweep is bounded (a 7d window of hourly churn can list hundreds of
    // wallets); say so out loud rather than letting the tail look complete.
    // v62: the remainder is no longer starved — the sweep rotates, so a wallet
    // deferred this cycle is at the front of the next one.
    log(
      `[OBSERVE-CAP] observation set hit its ${MAX_OBSERVE}-wallet cap — the least-recently-observed remainder waits its turn in the rotation`
    );
  }

  log(
    `Monitoring ${copyWallets.length} copy-eligible tracked + ${observeWallets.length} observation-only ` +
      `(demoted within ${OBSERVE_LOOKBACK_DAYS}d, copy cap ${MAX_TRACKED}) wallets for new trades ` +
      `(last ${MONITOR_HOURS}h)${adapter.isDemo ? " [DEMO DATA]" : ""}…`
  );
  const since = Date.now() - MONITOR_HOURS * 3600_000;
  let newTrades = 0;
  let newObserved = 0;
  const failures: string[] = [];
  /** v62: observation wallets whose fetch completed this cycle — stamped after
   *  the pool drains so the next cycle starts from the least recently observed. */
  const sweptObserve: string[] = [];

  // v44 (tuning review #13, approved): bounded-concurrency wallet monitoring —
  // 5 clean 429 windows justified a 4-at-a-time pool (was strictly serial; run
  // duration is the cadence bind). Per-wallet work stays serial inside each
  // task so the API burst stays bounded.
  // tuning #32 rec 1 (user-approved 2026-09-21): 4 -> 2 after 10 data-api 429s
  // across 7 of 109 runs (the first non-clean window in 7). Each wallet in flight
  // is one `/activity` page fetch plus its market reads, so the pool IS the burst
  // width — API_DELAY_MS paces pagination inside one wallet, not across wallets.
  // The run is no longer the cadence bind (13.0 m median vs a 10 m schedule), so
  // trading burst width for headroom is the right side of that trade.
  const CONCURRENCY = Number(process.env.MONITOR_CONCURRENCY ?? 2);
  const processWallet = async (w: MonitorWallet) => {
    try {
      // Observation-only wallets pre-filter against the rows already stored: a
      // busy demoted wallet re-offers its whole 24h book every cycle, and
      // without this every fill would be an insert attempt that ends in a
      // unique-constraint rejection.
      let seen: Set<string> | null = null;
      if (w.observationOnly) {
        const existing = await prisma.observedTrade.findMany({
          where: { walletAddress: w.address, timestamp: { gte: new Date(since) } },
          select: { marketId: true, outcome: true, side: true, timestamp: true },
        });
        seen = new Set(
          existing.map((r) => `${r.marketId}|${r.outcome}|${r.side}|${r.timestamp.getTime()}`)
        );
      }
      const activity = await adapter.fetchWalletActivity(w.address, Math.ceil(MONITOR_HOURS / 24) || 1);
      for (const t of activity) {
        if (t.timestamp.getTime() < since) continue;
        if (t.side !== "BUY") continue; // copy entries only, not exits
        const dedupeKey = `${t.marketId}|${t.outcome}|${t.side}|${t.timestamp.getTime()}`;
        if (seen?.has(dedupeKey)) continue;
        try {
          // Detected price: current market price at detection time — COPY set
          // only. An observation-only row keeps the wallet's own fill price: the
          // market read plus its MarketSnapshot write is the per-fill cost that
          // makes a large sweep expensive, and these rows can never be copied.
          let detectedPrice = t.price;
          if (!w.observationOnly) {
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
          }
          await prisma.observedTrade.create({
            data: {
              walletAddress: w.address,
              marketId: t.marketId,
              conditionId: t.conditionId,
              marketQuestion: t.marketQuestion,
              marketCategory: t.marketCategory,
              // observed-trade-category-field (2026-09-23, approved): the token
              // above is the raw event-slug segment (v45 blacklist / per-slug cap
              // granularity); these two are the REAL category, so no reader has
              // to re-classify free text to get one.
              marketCategoryClass: t.marketCategoryClass,
              marketCategoryFine: t.marketCategoryFine,
              outcome: t.outcome,
              side: t.side,
              walletEntryPrice: t.price,
              detectedPrice,
              size: t.size,
              timestamp: t.timestamp,
              rawTradeJson: "{}",
              isDemo: adapter.isDemo,
              observationOnly: w.observationOnly,
            },
          });
          seen?.add(dedupeKey);
          if (w.observationOnly) newObserved++;
          else newTrades++;
        } catch (e) {
          // Unique constraint = already seen; anything else is real.
          if (!(e instanceof Error && e.message.includes("Unique constraint"))) throw e;
        }
      }
      if (w.observationOnly) sweptObserve.push(w.address);
    } catch (e) {
      failures.push(`${w.address}: ${e instanceof Error ? e.message : e}`);
    }
  };
  const queue: MonitorWallet[] = [
    ...copyWallets.map((w) => ({ address: w.address, observationOnly: false })),
    ...observeWallets.map((w) => ({ address: w.address, observationOnly: true })),
  ];
  const workers = Array.from({ length: Math.min(CONCURRENCY, queue.length) }, async () => {
    while (queue.length > 0) {
      const w = queue.shift()!;
      await processWallet(w);
    }
  });
  await Promise.all(workers);

  // v62 (tuning review #34 rec 1, user-approved 2026-09-23): stamp the wallets
  // this sweep covered, so the next cycle takes the LEAST recently observed
  // ones. Without the stamp the cap re-takes the newest demotions every cycle
  // and the trailing-7d window behaves as a ~4 h window (measured 09-23: 108 of
  // 175 eligible wallets observed zero rows in 24 h). Non-fatal: a stamp failure
  // must never fail a monitor run that already stored its trades.
  let stamped = 0;
  try {
    stamped = await stampObserved(sweptObserve);
  } catch (e) {
    logError(`OBSERVE stamp failed (rotation will re-sweep the same wallets): ${e instanceof Error ? e.message : e}`);
  }

  log(
    `Trade monitor complete: ${newTrades + newObserved} new observed trades ` +
      `(${newTrades} copy-eligible, ${newObserved} observation-only).`
  );
  if (sweptObserve.length > 0) {
    const eligible = await observeEligibleCount(adapter.isDemo);
    const cycles = Math.max(1, Math.ceil(eligible / MAX_OBSERVE));
    log(
      `[OBSERVE-ROTATION] swept ${sweptObserve.length}/${eligible} eligible (least-recently-observed first, ` +
        `stamped ${stamped}); full pool every ~${cycles} cycles ≈ ${cycles * 11} min`
    );
  }
  if (failures.length) {
    logError(`Failures (${failures.length}):\n` + failures.slice(0, 5).join("\n"));
    if (newTrades + newObserved === 0 && failures.length === queue.length) {
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
