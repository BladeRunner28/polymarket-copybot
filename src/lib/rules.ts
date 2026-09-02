/**
 * Versioned rule sets. Rules govern scoring thresholds and can be changed
 * automatically by the rule updater — but every change is recorded in
 * RuleChange with reason, evidence, and before/after values.
 */

import { prisma } from "./db";

export interface Rules {
  // Trade-level gates
  maxSpread: number; // skip if spread wider than this
  minLiquidity: number; // skip if market liquidity below this (USD)
  maxPriceDrift: number; // skip if price moved more than this since wallet entry
  minTimeToResolutionHours: number; // skip if resolving too soon to copy
  minCopyScore: number; // paper_copy threshold (0..100)
  watchlistScore: number; // watchlist threshold (0..100)
  maxEntryPrice: number; // skip if price beyond this certainty band (also mirrored low side)
  maxCopiesPerCycle: number; // per scoring-run cap on new paper copies
  maxCopiesPerWalletPerDay: number; // per-wallet daily paper-copy cap
  // Wallet-level gates
  minWalletGlobalScore: number; // ignore signals from wallets below this
  minResolvedTrades: number; // wallets with fewer resolved trades are unproven
  minOrderbookImbalance: number; // skip if OBI is below this (e.g., heavily negative)
  // Scoring weights (wallet)
  weightRoi: number;
  weightConsistency: number;
  weightCopyability: number;
  // Sizing
  baseSizeUsd: number; // base paper size
  confidenceSizeBonus: number; // extra USD per point of confidence above 0.5
  // Short-TTR lane (prototype): a second, more permissive copy channel for
  // markets resolving within a short window (shortTtrMinHours..shortTtrMaxHours)
  // so the book converts to realized PnL daily instead of parking capital for
  // months. Relaxes ONLY the drift and copy-score bars (wallet/spread/
  // liquidity/price gates still apply). shortTtrMaxHours 0 = lane disabled.
  shortTtrMaxHours: number;
  shortTtrMinHours: number;
  shortTtrMinCopyScore: number;
  shortTtrMaxDrift: number;
  shortTtrSizeUsd: number;
  shortTtrMaxCopiesPerCycle: number;
  // v29: inverted sizing — the +EV copy region per Aug 2026 data is the
  // 70–79 sweet spot; scores ≥ highScoreCapMin (worst bucket) get the flat
  // capped size instead of the largest one.
  sweetSpotMinScore: number;
  sweetSpotMaxScore: number;
  sweetSpotSizeUsd: number;
  highScoreCapMin: number;
  highScoreCapUsd: number;
  highScoreMaxDrift: number; // stricter drift ceiling for scores ≥ highScoreCapMin
  // v29: capital recycling — cap the open book and force-close stale positions
  // that haven't moved toward the winning outcome, so capital cycles through
  // fresh +EV signals instead of being stranded.
  maxOpenPositions: number;
  staleExitHours: number;
  staleExitMinMove: number;
  // v33: hard max-age — any BANKROLL_200 position open past this closes at
  // last price regardless of winMove. v29 tier-1 (72h + <5% move) can't fire
  // when every old position has drifted ≥5%; the real drag is winners that
  // never resolve. This is the "dead capital" recycle.
  staleExitHardHours: number;
  // v34: regulatory boosts are unvalidated (0 resolved boosted trades) — a
  // positive boost may never manufacture a copy in the ≥ highScoreCapMin band
  // (worst historical PnL bucket). The clamp lands boosted signals in the
  // sweet spot instead.
  regulatoryScoreCap: number;
  // v37 (2026-08-30 reports): quality gates + Kalshi venue gate + entry-band
  // sizing. minConfidence is a hard skip (short-TTR lane exempt — it has its
  // own score bar and fixed size). Kalshi routing requires copyScore/
  // confidence bars AND the venue's realized PnL above the circuit-breaker
  // floor (recent Kalshi leg bled −$223.80 over Aug 29–31). Entry-band sizing
  // rescales main-lane copies: the 0.2–0.6 entry band historically bleeds
  // (−$227 on 71% of volume), entries < 0.20 are the only +EV bucket (+$185).
  minConfidence: number;
  kalshiMinCopyScore: number;
  kalshiMinConfidence: number;
  kalshiCircuitBreakerPnl: number;
  deadZoneMinPrice: number;
  deadZoneMaxPrice: number;
  deadZoneSizeFactor: number;
  longshotMaxPrice: number;
  longshotSizeFactor: number;
  // v38 (Phase A, 2026-08-31): Wang-Transform premium overlay — measurement-
  // first. The calibrated λ̂ table (data/premium-calibration.json, refit
  // biweekly on the 1st & 15th) quantifies the systematic risk premium at entry per price band.
  // Overlay: size × clamp(1 − k·λ̂, min, max) on C-200 main-lane copies only
  // (λ̂<0 = info edge → boost; λ̂>0 = overpriced entry → shrink); risk tag on
  // all C-200 copies. Lane copies are tagged but NOT resized.
  premiumOverlayEnabled: number; // 1 = on, 0 = off
  premiumOverlayK: number; // size-factor sensitivity to λ̂
  premiumOverlayMinFactor: number;
  premiumOverlayMaxFactor: number;
  // v39 (Phase A2, 2026-08-31): calibrated sentiment evidence aggregation —
  // replaces the Phase-8 fixed ±boost when enabled. The sentiment layer becomes
  // a Bayesian edge: delta = posterior − market (probability points) from
  // correlation-aware log-odds aggregation of the category's 7d opinionated
  // RegulatorySignals (src/lib/forecasting). copyScore += delta·sentimentScale,
  // still clamped at regulatoryScoreCap (v34 safety bound). 0 = legacy fixed
  // boost (fully revertible via rule change).
  sentimentEvidenceEnabled: number; // 1 = calibrated delta path, 0 = legacy boost
  sentimentScale: number; // copyScore points per 1.0 of calibrated delta
  sentimentMinSignals: number; // min opinionated signals in window to engage
  // v40 (2026-08-31, Homerun audit): risk gates + per-token circuit breaker.
  // Daily loss limit halts new C-200 copies when today's realized PnL is below
  // the floor; gross exposure caps total open notional; the token breaker skips
  // markets with a flash move in the window (trip recorded, cooldown enforced).
  dailyLossLimitUsd: number;
  maxGrossExposureUsd: number;
  tokenCircuitBreakerPct: number; // flash-move threshold (fraction of price)
  tokenCircuitBreakerWindowMin: number; // lookback window for flash detection
  tokenCircuitBreakerCooldownMin: number; // halt new copies after a trip
  // v41 risk gates (tuning review #12, 2026-09-01, approved): Phase B prep
  // from octagon-audit §4 — complements the per-market v40 gates.
  // maxCategoryPositions: max open C-200 positions per research category
  //   (Crypto, Tech/AI, Defense/Geopolitics, Healthcare, Energy/Climate,
  //   Finance, Macro/Politics via researchCategoryFor). Unmapped markets
  //   ("Other") are heterogeneous and uncapped. 0 = disabled.
  // maxDrawdownPct: portfolio drawdown gate — (peak − net worth)/peak, peak
  //   tracked in data/c200-drawdown.json (seeded from principal). 0 = disabled.
  maxCategoryPositions: number;
  maxDrawdownPct: number;
}

export const DEFAULT_RULES: Rules = {
  maxSpread: 0.05,
  minLiquidity: 5000,
  maxPriceDrift: 0.08,
  minTimeToResolutionHours: 12,
  minCopyScore: 65,
  watchlistScore: 45,
  maxEntryPrice: 0.88,
  maxCopiesPerCycle: 50,
  maxCopiesPerWalletPerDay: 10,
  minWalletGlobalScore: 55,
  minResolvedTrades: 5,
  minOrderbookImbalance: -0.40,
  weightRoi: 0.35,
  weightConsistency: 0.35,
  weightCopyability: 0.3,
  baseSizeUsd: 8,
  confidenceSizeBonus: 20,
  // Lane disabled by default — activation is an explicit rule change (v28+).
  shortTtrMaxHours: 0,
  shortTtrMinHours: 2,
  shortTtrMinCopyScore: 999,
  shortTtrMaxDrift: 0.05,
  shortTtrSizeUsd: 10,
  shortTtrMaxCopiesPerCycle: 10,
  // v29 defaults (values land in the DB ruleset at activation; these keep any
  // ruleset lacking the fields on the same behavior).
  sweetSpotMinScore: 70,
  sweetSpotMaxScore: 79,
  sweetSpotSizeUsd: 18,
  highScoreCapMin: 80,
  // v35: fresh 30d data (2026-08-29 report) has the ≥80 band as the best
  // bucket (+$0.57/trade) — it pays the same top allocation as the sweet spot
  // instead of the old v29 penalty cap. The drift ceiling stays as the gate.
  highScoreCapUsd: 18,
  highScoreMaxDrift: 0.004,
  maxOpenPositions: 100,
  staleExitHours: 48,
  staleExitMinMove: 0.05,
  staleExitHardHours: 168,
  // v34: clamp boosted scores into the 70–79 sweet spot (= sweetSpotMaxScore).
  regulatoryScoreCap: 79,
  // v37 defaults (live values land in the DB ruleset at activation).
  minConfidence: 0.7,
  kalshiMinCopyScore: 80,
  kalshiMinConfidence: 0.75,
  kalshiCircuitBreakerPnl: -50,
  deadZoneMinPrice: 0.2,
  deadZoneMaxPrice: 0.6,
  // v41 (2026-08-31, approved): band sizing moved to paper.ts
  // mapBankroll200Size - factors neutralized to 1.0 (RuleSet v39) so the
  // calibration bands apply exactly once. Re-enabling double-counts.
  deadZoneSizeFactor: 1.0,
  longshotMaxPrice: 0.2,
  longshotSizeFactor: 1.0,
  // v38 Phase-A overlay defaults (live values land in the DB ruleset).
  premiumOverlayEnabled: 1,
  premiumOverlayK: 0.5,
  premiumOverlayMinFactor: 0.5,
  premiumOverlayMaxFactor: 2.0,
  // v39 Phase-A2 defaults (live values land in the DB ruleset). Enabled: the
  // calibrated delta path replaces the unvalidated fixed boost; a rule change
  // to 0 reverts to the legacy ±boost.
  sentimentEvidenceEnabled: 1,
  sentimentScale: 100,
  sentimentMinSignals: 1,
  // v40 risk-gate defaults (live values land in the DB ruleset).
  dailyLossLimitUsd: -150,
  maxGrossExposureUsd: 250,
  tokenCircuitBreakerPct: 0.15,
  tokenCircuitBreakerWindowMin: 5,
  tokenCircuitBreakerCooldownMin: 30,
  // v41 risk-gate defaults (live values land in the DB ruleset at activation).
  maxCategoryPositions: 40,
  maxDrawdownPct: 0.2,
};

export async function getActiveRules(): Promise<{ rules: Rules; version: number; id: string }> {
  let active = await prisma.ruleSet.findFirst({ where: { active: true }, orderBy: { version: "desc" } });
  if (!active) {
    active = await prisma.ruleSet.create({
      data: { version: 1, active: true, rulesJson: JSON.stringify(DEFAULT_RULES) },
    });
  }
  const parsed = { ...DEFAULT_RULES, ...(JSON.parse(active.rulesJson) as Partial<Rules>) };
  return { rules: parsed, version: active.version, id: active.id };
}

export interface RuleChangeProposal {
  field: keyof Rules;
  newValue: number;
  reason: string;
  evidence: string;
}

/**
 * Apply proposals as a new rule version. Old version is deactivated, the new
 * one activated, and a RuleChange row records everything.
 */
export async function applyRuleChanges(
  proposals: RuleChangeProposal[],
  changedBy = "hermes"
): Promise<{ newVersion: number } | null> {
  if (proposals.length === 0) return null;
  const { rules, version, id: oldId } = await getActiveRules();
  const before: Record<string, number> = {};
  const after: Record<string, number> = {};
  const newRules: Rules = { ...rules };
  for (const p of proposals) {
    before[p.field] = rules[p.field];
    (newRules as unknown as Record<string, number>)[p.field] = p.newValue;
    after[p.field] = p.newValue;
  }
  const newVersion = version + 1;
  const created = await prisma.$transaction(async (tx) => {
    await tx.ruleSet.update({ where: { id: oldId }, data: { active: false } });
    const ns = await tx.ruleSet.create({
      data: { version: newVersion, active: true, rulesJson: JSON.stringify(newRules) },
    });
    await tx.ruleChange.create({
      data: {
        oldRuleSetId: oldId,
        newRuleSetId: ns.id,
        changedBy,
        reason: proposals.map((p) => p.reason).join(" | "),
        evidenceSummary: proposals.map((p) => p.evidence).join(" | "),
        beforeJson: JSON.stringify(before),
        afterJson: JSON.stringify(after),
      },
    });
    return ns;
  });
  return { newVersion: created.version };
}
