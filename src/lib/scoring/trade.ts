/**
 * Trade scoring: given an observed wallet trade + current market state +
 * wallet profile + active rules, decide paper_copy / watchlist / skip.
 * Pure function — easy to test.
 */

import { MarketState } from "../types";
import { Rules } from "../rules";
import { clampPaperSize } from "../safety";

export interface TradeScoreInput {
  walletGlobalScore: number; // 0..100
  walletCategoryWinRate?: number; // 0..1 for this market's category
  walletEntryPrice: number; // 0..1
  currentPrice: number; // 0..1
  spread?: number;
  liquidity?: number;
  timeToResolutionHours?: number;
  // Feature: Phase 1 - Orderbook Imbalance (OBI) 
  // Defines if the current L2 orderbook is severely tilted against our side.
  // A positive number means OBI is in our favor, heavily negative is dangerous.
  orderbookImbalance?: number; 
}

export interface TradeScoreResult {
  decision: "paper_copy" | "watchlist" | "skip";
  copyScore: number; // 0..100
  confidence: number; // 0..1
  simulatedPositionSize: number | null; // USD 5..20, only for paper_copy
  reasons: string[];
  risks: string[];
  breakdown: {
    walletQualityScore: number;
    categoryFitScore: number;
    entryTimingScore: number;
    spreadScore: number;
    liquidityScore: number;
    thesisScore: number;
  };
}

function clamp(v: number, lo = 0, hi = 100): number {
  return Math.min(hi, Math.max(lo, v));
}

export function scoreTrade(input: TradeScoreInput, rules: Rules): TradeScoreResult {
  const reasons: string[] = [];
  const risks: string[] = [];

  const drift = Math.abs(input.currentPrice - input.walletEntryPrice);
  const spread = input.spread ?? 0.1; // unknown spread treated as bad
  const liquidity = input.liquidity ?? 0;
  const ttr = input.timeToResolutionHours;

  // --- Hard gates (rules) -> skip ---
  const hardSkips: string[] = [];
  if (input.walletGlobalScore < rules.minWalletGlobalScore)
    hardSkips.push(`wallet score ${input.walletGlobalScore.toFixed(0)} < min ${rules.minWalletGlobalScore}`);
  if (spread > rules.maxSpread)
    hardSkips.push(`spread ${spread.toFixed(3)} > max ${rules.maxSpread}`);
  if (liquidity < rules.minLiquidity)
    hardSkips.push(`liquidity $${liquidity.toFixed(0)} < min $${rules.minLiquidity}`);
  if (drift > rules.maxPriceDrift)
    hardSkips.push(`price drifted ${drift.toFixed(3)} since entry > max ${rules.maxPriceDrift} (too late)`);
  if (ttr !== undefined && ttr < rules.minTimeToResolutionHours)
    hardSkips.push(`resolves in ${ttr.toFixed(1)}h < min ${rules.minTimeToResolutionHours}h`);
  if (input.currentPrice > rules.maxEntryPrice || input.currentPrice < 1 - rules.maxEntryPrice)
    hardSkips.push(
      `price ${input.currentPrice.toFixed(3)} near certainty (band ${(1 - rules.maxEntryPrice).toFixed(2)}–${rules.maxEntryPrice.toFixed(2)}) — limited upside`
    );
  // Feature: Phase 1 - Orderbook Imbalance (OBI)
  // Protect against massive sell walls directly against our entry direction.
  if (input.orderbookImbalance !== undefined && input.orderbookImbalance < rules.minOrderbookImbalance) {
    hardSkips.push(`Orderbook Imbalance is severely hostile (${input.orderbookImbalance.toFixed(2)} < ${rules.minOrderbookImbalance.toFixed(2)}). Smart money sell-wall detected.`);
  }

  // --- Component scores ---
  const walletQualityScore = clamp(input.walletGlobalScore);
  const categoryFitScore =
    input.walletCategoryWinRate !== undefined
      ? clamp(input.walletCategoryWinRate * 130 - 15)
      : 50;
  const entryTimingScore = clamp(100 - (drift / Math.max(rules.maxPriceDrift, 0.001)) * 80);
  const spreadScore = clamp(100 - (spread / Math.max(rules.maxSpread, 0.001)) * 70);
  const liquidityScore = clamp((liquidity / (rules.minLiquidity * 5)) * 100);
  // Thesis clarity: prices near 0.5 = genuinely uncertain market where a
  // sharp wallet's opinion carries information; extreme prices = little edge left.
  const p = input.currentPrice;
  const thesisScore = clamp(100 - Math.abs(p - 0.5) * 160);

  const copyScore = clamp(
    walletQualityScore * 0.3 +
      categoryFitScore * 0.15 +
      entryTimingScore * 0.2 +
      spreadScore * 0.1 +
      liquidityScore * 0.15 +
      thesisScore * 0.1
  );

  const breakdown = {
    walletQualityScore,
    categoryFitScore,
    entryTimingScore,
    spreadScore,
    liquidityScore,
    thesisScore,
  };

  if (hardSkips.length > 0) {
    return {
      decision: "skip",
      copyScore: Math.round(copyScore * 10) / 10,
      confidence: 0,
      simulatedPositionSize: null,
      reasons: [],
      risks: hardSkips,
      breakdown,
    };
  }

  if (walletQualityScore >= 70) reasons.push("High-quality wallet");
  if (entryTimingScore >= 70) reasons.push("Entry still close to wallet's price");
  if (liquidityScore >= 60) reasons.push("Liquid market — realistic to copy");
  if (categoryFitScore >= 65) reasons.push("Wallet is strong in this category");
  if (thesisScore < 30) risks.push("Price already near certainty — limited upside");
  if (spreadScore < 40) risks.push("Spread eats into edge");
  if (ttr !== undefined && ttr > 24 * 30) risks.push("Very long time to resolution — capital parked");

  const confidence = Math.round(((copyScore - rules.watchlistScore) / (100 - rules.watchlistScore)) * 100) / 100;

  if (copyScore >= rules.minCopyScore) {
    // Higher confidence -> larger simulated size, always clamped to $.25..$20.
    const size = clampPaperSize(
      rules.baseSizeUsd + Math.max(0, confidence - 0.5) * rules.confidenceSizeBonus
    );
    return {
      decision: "paper_copy",
      copyScore: Math.round(copyScore * 10) / 10,
      confidence: Math.max(0, Math.min(1, confidence)),
      simulatedPositionSize: Math.round(size * 100) / 100,
      reasons: reasons.length ? reasons : ["Score cleared paper_copy threshold"],
      risks,
      breakdown,
    };
  }
  if (copyScore >= rules.watchlistScore) {
    return {
      decision: "watchlist",
      copyScore: Math.round(copyScore * 10) / 10,
      confidence: Math.max(0, Math.min(1, confidence)),
      simulatedPositionSize: null,
      reasons: reasons.length ? reasons : ["Interesting but below copy threshold"],
      risks: risks.length ? risks : ["Not clean enough to copy"],
      breakdown,
    };
  }
  return {
    decision: "skip",
    copyScore: Math.round(copyScore * 10) / 10,
    confidence: 0,
    simulatedPositionSize: null,
    reasons: [],
    risks: risks.length ? risks : ["Weak overall setup"],
    breakdown,
  };
}

export function marketStateToScoreInput(
  m: MarketState,
  walletEntryPrice: number,
  walletGlobalScore: number,
  walletCategoryWinRate?: number
): TradeScoreInput {
  return {
    walletGlobalScore,
    walletCategoryWinRate,
    walletEntryPrice,
    currentPrice: m.yesPrice ?? walletEntryPrice,
    spread: m.spread,
    liquidity: m.liquidity,
    timeToResolutionHours: m.timeToResolutionHours,
  };
}
