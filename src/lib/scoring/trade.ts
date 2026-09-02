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
  
  // Phase 7: Predictive ML features
  swarmCount?: number; // Number of distinct top wallets taking this side in the last hour
  tradeSize?: number; // USD size of the observed trade (to detect whales)
  // Phase 8: Regulatory/Political sentiment agreement. Signed: positive when
  // the latest regulatory sentiment aligns with this trade's direction.
  // Legacy path (sentimentEvidenceEnabled = 0); superseded by sentimentDelta.
  regulatoryAgreement?: number; // -1..1
  // Phase A2 (v39): calibrated sentiment evidence edge, signed for THIS trade's
  // direction, in probability points (posterior − market). Active when
  // rules.sentimentEvidenceEnabled = 1; replaces the legacy fixed boost.
  sentimentDelta?: number; // -1..1
}

export interface TradeScoreResult {
  decision: "paper_copy" | "watchlist" | "skip";
  /** Short-TTR lane copies are still paper_copy but flagged for routing/measurement. */
  lane?: "short_ttr";
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

  // Short-TTR lane eligibility: market resolves inside the lane window and the
  // entry is not stale beyond the lane's relaxed drift cap. Requires the lane
  // to be enabled (shortTtrMaxHours > 0).
  const laneEligible =
    rules.shortTtrMaxHours > 0 &&
    ttr !== undefined &&
    ttr >= rules.shortTtrMinHours &&
    ttr <= rules.shortTtrMaxHours &&
    drift <= rules.shortTtrMaxDrift;

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

  let copyScore = clamp(
    walletQualityScore * 0.3 +
      categoryFitScore * 0.15 +
      entryTimingScore * 0.2 +
      spreadScore * 0.1 +
      liquidityScore * 0.15 +
      thesisScore * 0.1
  );

  // v37: confidence computed here (before the hard-skip gate) so the
  // minConfidence gate can use it. Lane-eligible signals are exempt: the
  // short-TTR lane has its own score bar and fixed size, and is the proven
  // +EV channel.
  const confidence = Math.round(((copyScore - rules.watchlistScore) / (100 - rules.watchlistScore)) * 100) / 100;
  if (confidence < rules.minConfidence && !laneEligible)
    hardSkips.push(`confidence ${confidence.toFixed(2)} < min ${rules.minConfidence}`);

  const breakdown = {
    walletQualityScore,
    categoryFitScore,
    entryTimingScore,
    spreadScore,
    liquidityScore,
    thesisScore,
  };

  // Phase 7: Predictive Features (Swarm, Whale Wake, Trend) — applied before
  // the hard-skip gate so lane rescues and stored copy scores use the final,
  // adjusted score.
  if (input.swarmCount && input.swarmCount >= 3) {
    copyScore += 25; // Massive boost for cluster signals
    reasons.push(`Swarm Detected: ${input.swarmCount} top wallets taking this side in the last hour`);
  }
  if (input.tradeSize && input.tradeSize > 10000) {
    reasons.push("Whale-Wake Front-Run: Deploying Maker limit order slightly ahead of flow");
  }
  if (ttr !== undefined && ttr > 168 && drift > 0.02) {
    reasons.push("Trend Following: Early macro signal gaining momentum");
  } else if (ttr !== undefined && ttr < 48 && input.currentPrice > 0.80) {
    risks.push("Mean Reversion Risk: High risk of late correction on expensive outcome");
    copyScore -= 10;
  }

  // Phase 8: Regulatory/Political Sentiment (C-200 research bot).
  // v39 (Phase A2): the calibrated evidence path replaces the fixed ±boost
  // when sentimentEvidenceEnabled. sentimentDelta is the trade-direction-signed
  // edge in probability points (posterior − market); scale converts it to
  // copyScore points. Sub-noise deltas (<0.005) are ignored. The legacy fixed
  // boost stays for the disabled path — revertible by one rule change.
  let regulatoryBoosted = false;
  if (rules.sentimentEvidenceEnabled === 1 && input.sentimentDelta !== undefined) {
    if (Math.abs(input.sentimentDelta) >= 0.005) {
      copyScore += input.sentimentDelta * rules.sentimentScale;
      // Only POSITIVE adjustments count as "boosted" for the v34 clamp — a
      // penalty that lands ≥ highScoreCapMin keeps its full (reduced) score.
      if (input.sentimentDelta > 0) regulatoryBoosted = true;
      reasons.push(
        `Sentiment evidence edge ${input.sentimentDelta >= 0 ? "+" : ""}${(input.sentimentDelta * 100).toFixed(1)}pp (calibrated)`
      );
    }
  } else if (input.regulatoryAgreement !== undefined) {
    if (input.regulatoryAgreement >= 0.7) {
      copyScore += 25;
      regulatoryBoosted = true;
      reasons.push("Regulatory sentiment aligns strongly");
    } else if (input.regulatoryAgreement >= 0.3) {
      copyScore += 10;
      regulatoryBoosted = true;
      reasons.push("Regulatory sentiment aligns");
    } else if (input.regulatoryAgreement <= -0.3) {
      copyScore -= 20;
      risks.push("Regulatory sentiment opposes");
    }
  }

  // Round once here so the late-entry filter, band sizing, and the stored
  // copyScore all agree on the same value. Without this, a raw 79.27 scores
  // "79.3" but falls through the 70–79 sweet-spot band (raw > 79) to the base
  // curve — a sizing hole at the top of the +EV band.
  copyScore = Math.round(copyScore * 10) / 10;

  // Lane rescue: the ONLY hard gates the lane may relax are price drift and
  // time-to-resolution (both replaced by the lane's own windows). Wallet,
  // spread, liquidity, price-band and OBI gates stay hard.
  const laneRescuesGateFailures =
    laneEligible &&
    hardSkips.length > 0 &&
    hardSkips.every((s) => s.includes("drift") || s.includes("resolves in")) &&
    copyScore >= rules.shortTtrMinCopyScore;

  if (hardSkips.length > 0 && !laneRescuesGateFailures) {
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

  // v29: late entries can't masquerade as high confidence — scores in the
  // capped band with drift beyond the strict ceiling are rejected. Lane-
  // eligible signals are exempt: the short-TTR lane has its own drift window.
  if (copyScore >= rules.highScoreCapMin && drift > rules.highScoreMaxDrift && !laneEligible) {
    return {
      decision: "skip",
      copyScore: Math.round(copyScore * 10) / 10,
      confidence: 0,
      simulatedPositionSize: null,
      reasons: [],
      risks: [
        `score ${copyScore.toFixed(0)} ≥ ${rules.highScoreCapMin} but drift ${drift.toFixed(3)} > ${rules.highScoreMaxDrift} — late entry`,
      ],
      breakdown,
    };
  }

  // v34: never let a positive regulatory adjustment manufacture a copy in the
  // ≥ highScoreCapMin band (historically the worst bucket; boosted trades were
  // running unvalidated). The late-entry filter above already ran on the
  // PRE-clamp score, so a boosted late entry is still rejected; the clamp then
  // lands boosted signals in the 70–79 sweet spot for sizing. Negative
  // adjustments (penalties) are never clamped upward — they keep their full
  // reduced score.
  if (regulatoryBoosted && copyScore > rules.regulatoryScoreCap) {
    copyScore = rules.regulatoryScoreCap;
  }

  if (copyScore >= rules.minCopyScore) {
    // Band sizing: 70–79 sweet spot and ≥80 (best bucket per 2026-08-29 30d
    // data) both take the top allocation; 55–69 keeps the base curve.
    // Clamped $.25–$20.
    let size: number;
    if (copyScore >= rules.highScoreCapMin) {
      size = rules.highScoreCapUsd;
    } else if (copyScore >= rules.sweetSpotMinScore && copyScore < rules.highScoreCapMin) {
      // Sweet spot is everything below the cap band (rounded scores 70–79.9);
      // `<= sweetSpotMaxScore` would leave 79.1–79.9 in a dead zone that
      // falls through to the base curve.
      size = rules.sweetSpotSizeUsd;
    } else {
      size = rules.baseSizeUsd + Math.max(0, confidence - 0.5) * rules.confidenceSizeBonus;
    }
    // v37: entry-band sizing (2026-08-30 report) — the 0.2–0.6 entry band is
    // the all-time drain (−$227 on 71% of volume): halve size there. Entries
    // below longshotMaxPrice (the only +EV bucket per the bucket data:
    // <0.20 +$185.75) carry more size.
    // v41 (2026-08-31, approved): band sizing moved to the C-200 size mapping
    // (paper.ts mapBankroll200Size) — these factors are neutralized at 1.0
    // (RuleSet v39) so the bands apply exactly once.
    if (input.currentPrice >= rules.deadZoneMinPrice && input.currentPrice <= rules.deadZoneMaxPrice) {
      size *= rules.deadZoneSizeFactor;
    } else if (input.currentPrice < rules.longshotMaxPrice) {
      size *= rules.longshotSizeFactor;
    }
    const clamped = clampPaperSize(size);
    return {
      decision: "paper_copy",
      copyScore: Math.round(copyScore * 10) / 10,
      confidence: Math.max(0, Math.min(1, confidence)),
      simulatedPositionSize: Math.round(clamped * 100) / 100,
      reasons: reasons.length ? reasons : ["Score cleared paper_copy threshold"],
      risks,
      breakdown,
    };
  }

  // Short-TTR lane copy: fixed size, zero confidence (routing stays on
  // Polymarket), flagged with lane="short_ttr" so the executor can scope it
  // to the compounding bot. Relaxed gates are surfaced in risks for review.
  if (laneEligible && copyScore >= rules.shortTtrMinCopyScore) {
    return {
      decision: "paper_copy",
      lane: "short_ttr",
      copyScore: Math.round(copyScore * 10) / 10,
      confidence: 0,
      simulatedPositionSize: Math.round(clampPaperSize(rules.shortTtrSizeUsd) * 100) / 100,
      reasons: [...reasons, `Short-TTR lane: resolves in ${ttr !== undefined ? ttr.toFixed(1) : "?"}h — daily PnL channel`],
      risks: [...risks, ...hardSkips, "short-ttr lane (relaxed drift & score bar)"],
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
