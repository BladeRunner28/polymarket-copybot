/**
 * Wallet scoring: ROI, consistency, copyability, one-hit-wonder penalty,
 * category strengths. Pure functions — easy to test.
 */

import { WalletActivityTrade } from "../types";
import { Rules } from "../rules";

export interface WalletScore {
  roi30d: number;
  consistencyScore: number; // 0..100
  copyabilityScore: number; // 0..100
  oneHitWonderPenalty: number; // 0..100 (higher = worse)
  globalScore: number; // 0..100
  bestCategory: string | null;
  categoryStrengths: Record<string, { trades: number; winRate: number; pnl: number }>;
  averageTradeSize: number;
  tradeCount30d: number;
  resolvedTradeCount30d: number;
  winRate30d: number;
  averageLiquidity: number;
  averageSpread: number;
  averageEntryTiming: number;
  copyabilityNotes: string;
  riskNotes: string;
}

function clamp(v: number, lo = 0, hi = 100): number {
  return Math.min(hi, Math.max(lo, v));
}

/**
 * One-hit-wonder penalty: share of total positive PnL contributed by the
 * single best trade. If one trade made most of the money, the "edge" is
 * probably luck. 0 = evenly earned, 100 = all profit from one trade.
 */
export function oneHitWonderPenalty(trades: WalletActivityTrade[]): number {
  const wins = trades.filter((t) => t.resolved && (t.pnl ?? 0) > 0);
  if (wins.length === 0) return 100; // no proven wins at all
  if (wins.length === 1) return 90; // exactly one win — unproven
  const totalPos = wins.reduce((a, t) => a + (t.pnl ?? 0), 0);
  const best = Math.max(...wins.map((t) => t.pnl ?? 0));
  const share = totalPos > 0 ? best / totalPos : 1;
  // share 0.2 (even) -> ~0 penalty; share 0.9 -> heavy penalty
  return clamp(((share - 0.25) / 0.65) * 100);
}

/** Consistency: steadiness of win rate and PnL distribution across resolved trades. */
export function consistencyScore(trades: WalletActivityTrade[]): number {
  const resolved = trades.filter((t) => t.resolved && t.pnl !== undefined);
  if (resolved.length < 3) return 10;
  const winRate = resolved.filter((t) => (t.pnl ?? 0) > 0).length / resolved.length;
  const pnls = resolved.map((t) => t.pnl ?? 0);
  const mean = pnls.reduce((a, b) => a + b, 0) / pnls.length;
  const std = Math.sqrt(pnls.reduce((a, b) => a + (b - mean) ** 2, 0) / pnls.length);
  // Coefficient-of-variation style: lower relative volatility = more consistent.
  const cov = mean > 0 ? std / mean : 5;
  const covScore = clamp(100 - cov * 20);
  const wrScore = clamp(winRate * 130 - 20); // 50% wr -> 45, 70% -> 71
  const volumeBonus = clamp(resolved.length * 3, 0, 20);
  return clamp(covScore * 0.4 + wrScore * 0.5 + volumeBonus * 0.5);
}

/**
 * Copyability: can WE realistically follow this wallet? Penalizes illiquid
 * markets, wide spreads, and very late entries (entering near resolution
 * means we'd get worse prices).
 */
export function copyabilityScore(trades: WalletActivityTrade[], rules: Rules): number {
  if (trades.length === 0) return 0;
  const withLiq = trades.filter((t) => t.liquidity !== undefined);
  const withSpread = trades.filter((t) => t.spread !== undefined);
  const avgLiq = withLiq.length
    ? withLiq.reduce((a, t) => a + (t.liquidity ?? 0), 0) / withLiq.length
    : 0;
  const avgSpread = withSpread.length
    ? withSpread.reduce((a, t) => a + (t.spread ?? 0), 0) / withSpread.length
    : 0.1;
  const liqScore = clamp((avgLiq / (rules.minLiquidity * 4)) * 100);
  const spreadScore = clamp(100 - (avgSpread / rules.maxSpread) * 50);
  // Extreme prices (<0.05 or >0.95) are hard to copy profitably.
  const extremeShare =
    trades.filter((t) => t.price < 0.05 || t.price > 0.95).length / trades.length;
  const priceScore = clamp(100 - extremeShare * 120);
  return clamp(liqScore * 0.4 + spreadScore * 0.35 + priceScore * 0.25);
}

export function scoreWallet(trades: WalletActivityTrade[], rules: Rules): WalletScore {
  const resolved = trades.filter((t) => t.resolved && t.pnl !== undefined);
  const invested = trades.reduce((a, t) => a + t.size, 0);
  const realized = resolved.reduce((a, t) => a + (t.pnl ?? 0), 0);
  const roi30d = invested > 0 ? realized / invested : 0;

  const cons = consistencyScore(trades);
  const copy = copyabilityScore(trades, rules);
  const penalty = oneHitWonderPenalty(trades);

  // ROI mapped to 0..100 (0% -> 40, +50% -> ~85, negative -> below 40)
  const roiScore = clamp(40 + roi30d * 90);

  let global =
    roiScore * rules.weightRoi + cons * rules.weightConsistency + copy * rules.weightCopyability;
  // Penalty scales global down by up to 60%.
  global = global * (1 - (penalty / 100) * 0.6);
  if (resolved.length < rules.minResolvedTrades) {
    global = Math.min(global, 40); // unproven wallets capped
  }

  // Category strengths
  const cats: Record<string, { trades: number; wins: number; pnl: number }> = {};
  for (const t of trades) {
    const c = t.marketCategory ?? "uncategorized";
    cats[c] ??= { trades: 0, wins: 0, pnl: 0 };
    cats[c].trades++;
    if (t.resolved && (t.pnl ?? 0) > 0) cats[c].wins++;
    cats[c].pnl += t.pnl ?? 0;
  }
  const categoryStrengths: WalletScore["categoryStrengths"] = {};
  let bestCategory: string | null = null;
  let bestPnl = -Infinity;
  for (const [c, v] of Object.entries(cats)) {
    categoryStrengths[c] = {
      trades: v.trades,
      winRate: v.trades ? v.wins / v.trades : 0,
      pnl: Math.round(v.pnl * 100) / 100,
    };
    if (v.pnl > bestPnl && v.trades >= 2) {
      bestPnl = v.pnl;
      bestCategory = c;
    }
  }

  const withLiq = trades.filter((t) => t.liquidity !== undefined);
  const withSpread = trades.filter((t) => t.spread !== undefined);

  const notes: string[] = [];
  const risks: string[] = [];
  if (penalty > 60) risks.push("Most profit came from one lucky trade");
  if (resolved.length < rules.minResolvedTrades) risks.push(`Only ${resolved.length} resolved trades — unproven`);
  if (copy < 40) risks.push("Trades markets that are hard to copy (illiquid or wide spread)");
  if (copy >= 60) notes.push("Trades liquid markets with tight spreads");
  if (cons >= 60) notes.push("Consistent win pattern across trades");
  if (bestCategory) notes.push(`Strongest category: ${bestCategory}`);

  return {
    roi30d,
    consistencyScore: Math.round(cons * 10) / 10,
    copyabilityScore: Math.round(copy * 10) / 10,
    oneHitWonderPenalty: Math.round(penalty * 10) / 10,
    globalScore: Math.round(clamp(global) * 10) / 10,
    bestCategory,
    categoryStrengths,
    averageTradeSize: trades.length ? invested / trades.length : 0,
    tradeCount30d: trades.length,
    resolvedTradeCount30d: resolved.length,
    winRate30d: resolved.length
      ? resolved.filter((t) => (t.pnl ?? 0) > 0).length / resolved.length
      : 0,
    averageLiquidity: withLiq.length
      ? withLiq.reduce((a, t) => a + (t.liquidity ?? 0), 0) / withLiq.length
      : 0,
    averageSpread: withSpread.length
      ? withSpread.reduce((a, t) => a + (t.spread ?? 0), 0) / withSpread.length
      : 0,
    averageEntryTiming: 0.5, // refined when we have per-market resolution times
    copyabilityNotes: notes.join("; ") || "No notable strengths yet",
    riskNotes: risks.join("; ") || "No major risks flagged",
  };
}

export function walletStatus(score: WalletScore, rules: Rules): { status: string; reason: string } {
  if (score.globalScore >= rules.minWalletGlobalScore + 10 && score.oneHitWonderPenalty < 50) {
    return { status: "track", reason: `Global score ${score.globalScore} with balanced profits — worth following` };
  }
  if (score.globalScore >= rules.minWalletGlobalScore - 15) {
    return { status: "watch", reason: `Global score ${score.globalScore} — promising but not proven enough to track` };
  }
  return {
    status: "ignore",
    reason:
      score.oneHitWonderPenalty > 60
        ? `One-hit-wonder penalty ${score.oneHitWonderPenalty} — profit not repeatable`
        : `Global score ${score.globalScore} below threshold`,
  };
}
