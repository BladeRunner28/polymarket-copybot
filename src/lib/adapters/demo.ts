/**
 * DEMO adapter — deterministic synthetic data, CLEARLY LABELED as demo.
 * Used when DATA_MODE=demo or in tests. Everything it produces is flagged
 * isDemo=true downstream. It never touches the network.
 */

import {
  DataAdapter,
  LeaderboardEntry,
  MarketState,
  WalletActivityTrade,
} from "../types";

// Simple deterministic PRNG so demo data is stable across runs.
function mulberry32(seed: number) {
  return function () {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const CATEGORIES = ["politics", "sports", "crypto", "science", "pop-culture"];

const QUESTIONS = [
  "Will [DEMO] event A happen by end of month?",
  "Will [DEMO] candidate X win the primary?",
  "Will [DEMO] BTC close above $100k this week?",
  "Will [DEMO] team Y win the finals?",
  "Will [DEMO] launch Z occur before Q3?",
];

function marketSeedPrice(marketId: string): { yes: number; spread: number; liquidity: number; resolved: boolean } {
  const seed = marketId.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
  const rand = mulberry32(seed);
  const yes = 0.1 + rand() * 0.8;
  const spread = 0.005 + rand() * 0.05;
  const liquidity = 500 + rand() * 150_000;
  const resolved = rand() > 0.85;
  return { yes, spread, liquidity, resolved };
}

export class DemoAdapter implements DataAdapter {
  readonly source = "demo";
  readonly isDemo = true;

  async fetchLeaderboard(limit: number): Promise<LeaderboardEntry[]> {
    const rand = mulberry32(42);
    const out: LeaderboardEntry[] = [];
    for (let i = 0; i < limit; i++) {
      out.push({
        address: `0xdemo${String(i + 1).padStart(4, "0")}${"0".repeat(31)}`,
        label: `[DEMO] Trader ${i + 1}`,
        rank: i + 1,
        pnl: Math.round((rand() * 200000 - 20000) * 100) / 100,
        volume: Math.round(rand() * 2_000_000),
      });
    }
    return out;
  }

  async fetchWalletActivity(address: string, days: number): Promise<WalletActivityTrade[]> {
    const seed = address.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
    const rand = mulberry32(seed);
    const n = 5 + Math.floor(rand() * 40);
    const out: WalletActivityTrade[] = [];
    // A few demo wallets are deliberate "one-hit wonders" to exercise scoring.
    const oneHit = seed % 7 === 0;
    for (let i = 0; i < n; i++) {
      const daysAgo = rand() * days;
      const resolved = rand() > 0.35;
      const won = resolved ? rand() > (oneHit ? 0.6 : 0.42) : undefined;
      const size = 10 + rand() * 490;
      const q = Math.floor(rand() * QUESTIONS.length);
      const marketId = `demo-market-${q}-${Math.floor(rand() * 50)}`;
      const mkt = marketSeedPrice(marketId);
      // Entry price anchored near the market's demo price so drift is realistic.
      const outcome = rand() > 0.5 ? "YES" : "NO";
      const basePrice = outcome === "YES" ? mkt.yes : 1 - mkt.yes;
      const price = Math.min(0.97, Math.max(0.03, basePrice + (rand() - 0.5) * 0.06));
      const pnl = resolved
        ? won
          ? size * ((1 - price) / price) * (oneHit && i === 0 ? 8 : 0.5 + rand())
          : -size
        : undefined;
      out.push({
        marketId,
        marketQuestion: QUESTIONS[q],
        marketCategory: CATEGORIES[q % CATEGORIES.length],
        outcome,
        side: rand() > 0.2 ? "BUY" : "SELL",
        price,
        size,
        timestamp: new Date(Date.now() - daysAgo * 86400_000),
        resolved,
        won,
        pnl,
        liquidity: mkt.liquidity,
        spread: mkt.spread,
      });
    }
    return out;
  }

  async fetchMarket(marketId: string): Promise<MarketState> {
    const seed = marketId.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
    const rand = mulberry32(seed);
    const yes = 0.1 + rand() * 0.8;
    const spread = 0.005 + rand() * 0.05;
    const resolved = rand() > 0.85;
    return {
      marketId,
      question: `[DEMO] ${marketId}`,
      category: CATEGORIES[seed % CATEGORIES.length],
      yesPrice: yes,
      noPrice: 1 - yes,
      bestBid: Math.max(0.01, yes - spread / 2),
      bestAsk: Math.min(0.99, yes + spread / 2),
      spread,
      liquidity: 500 + rand() * 150_000,
      volume: rand() * 1_000_000,
      timeToResolutionHours: resolved ? 0 : 2 + rand() * 500,
      resolved,
      winningOutcome: resolved ? (yes > 0.5 ? "YES" : "NO") : undefined,
    };
  }
}
