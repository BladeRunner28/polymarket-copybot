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
  // v57 (2026-09-18 daily report change A, user-approved): a FLAT 0.4¢ tolerance
  // is 0.7% of price at 0.60 but 2–8% of price at 0.05–0.20, so the widest-edge
  // band (excess +22.5pp, z=+5.79) was the most drift-starved: 5 long-shot entries
  // in 24h vs 11 in the losing 0.20–0.40 band. When > 0, entries below
  // longshotMaxPrice use max(maxPriceDrift, pct × price) capped at
  // longshotDriftCap. 0 = legacy flat tolerance (default).
  longshotDriftPct: number; // e.g. 0.08 = 8% of the entry price
  longshotDriftCap: number; // absolute ceiling for the band (e.g. 0.02)
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
  /**
   * v65 (approved 2026-10-21): whether the wallet-quality component may move the
   * SIZE bucket. 1 = legacy (wallet score feeds the size score); 0 = wallet
   * quality is an ADMISSION-only signal and the size score renormalises the
   * remaining 0.70 weights. Default 1 so any ruleset lacking the field keeps
   * the historical behaviour — a revert is this single field.
   */
  walletQualityInSize: number;
  highScoreMaxDrift: number; // stricter drift ceiling for scores ≥ highScoreCapMin
  // v29: capital recycling — cap the open book and force-close stale positions
  // that haven't moved toward the winning outcome, so capital cycles through
  // fresh +EV signals instead of being stranded.
  maxOpenPositions: number;
  // v64: the SAME open-position cap for STANDARD, which has never had one. 0 = disabled.
  // Why this rail and not a per-slug cap: measured 2026-10-20, STANDARD books 4.90 legs/day and
  // holds 1,263 open positions -- 5.6x the C-200 cap of 225 that never applied to it -- on $13.6k
  // notional against $7.9k cash. A per-slug/per-class cap was the originally-approved instrument,
  // but measured it would have blocked ~55% of new flow at cap 15 or 30, and 39.5% of that flow is
  // the 'other' catch-all bucket, so it would have throttled unclassified markets rather than real
  // concentration. Open-position count is the quantity that is actually out of control.
  standardMaxOpenPositions: number;
  staleExitHours: number;
  staleExitMinMove: number;
  // v53 (2026-09-13 daily report Change 1, user-approved): adverse-only tier-1
  // stale exit. Pre-v53 the tier-1 cut closed any C-200 position older than
  // staleExitHours whose winMove < staleExitMinMove — a "flat is bad" rule, not
  // a loser-cut: it realized 24h noise as losses at scale (24–72h exits: 1,069
  // rows, −$1,215.72 on $7,152 staked, −17.0% ROI, 44% win; every other hold
  // window is positive, and excluding those rows Polymarket realized turns
  // +$817.81). With staleExitAdverseOnly = 1 the tier-1 cut fires only on
  // ADVERSE moves (winMove ≤ staleExitAdverseMove, negative), so flat positions
  // run to the staleExitHardHours max-age instead of being cut at 24h.
  // staleExitHours keeps its meaning as the tier-1 age gate. 0 (default) =
  // legacy behavior, byte-identical for any ruleset lacking these fields.
  staleExitAdverseOnly: number; // 1 = adverse-only tier-1 cut, 0 = legacy
  staleExitAdverseMove: number; // winMove threshold (negative fraction, e.g. -0.15)
  // v33: hard max-age — any BANKROLL_200 position open past this closes at
  // last price regardless of winMove. v29 tier-1 (72h + <5% move) can't fire
  // when every old position has drifted ≥5%; the real drag is winners that
  // never resolve. This is the "dead capital" recycle.
  staleExitHardHours: number;
  // v66 (tuning #2, user-approved 2026-10-23): give STANDARD the stale exit it has
  // never had, SCOPED to entry >= 0.60. The C-200 max-age above is unconditional and
  // applies only to BANKROLL_200; STANDARD has had no recycling rail at all, which is
  // why it parks capital in markets that never resolve (open STANDARD = ~1.07M
  // capital-days = 67.1% of all capital-time at +1.80 $/1k-capital-day, against
  // +27.43 finished -- 1/15th the rate).
  // Why >= 0.60 and nothing else: measured on settlement truth (277 legs, 85 markets
  // resolved >168h after entry) the >=0.60 stop is +$68..+$326, while the same stop at
  // 0.20-0.40 DESTROYS $1,064 on 135 legs -- a (1-p)/p payoff cannot be time-stopped.
  // 0.40-0.60 is not a scope decision: v63 skips that band on STANDARD, so no leg can
  // reach the exit there. Do NOT widen this downward without a new measurement.
  // 0 = disabled (the convention for every added rail: land the code, let the RuleSet
  // version switch it on).
  standardStaleExitHours: number;
  standardStaleExitBandMin: number;
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
  // v54 (2026-09-15 C-200 daily report Rec 1, user-approved): the C-200 band
  // multipliers that live in paper.ts mapBankroll200Size, exposed as rule fields
  // so a band reallocation is a VERSIONED, journal-taggable change instead of a
  // bare code edit. Defaults equal the shipped constants (longshot 2.0, dead
  // zone 0.25) — a ruleset lacking the fields behaves byte-identically.
  // NOTE: C-200-ONLY on purpose. The v37 rules-layer factors above
  // (deadZoneSizeFactor / longshotSizeFactor) are read by the SHARED scorer
  // (src/lib/scoring/trade.ts) for every bot — flipping those would also resize
  // STANDARD and would double-apply on the C-200 legacy path (the v41
  // neutralization exists to stop exactly that).
  c200LongshotBandFactor: number; // <0.20 entries (default 2.0)
  // v67 (profit-recs #1, user-approved 2026-10-24): LOWER bound for the long-shot
  // multiplier. The factor applied to every entry < 0.20 with nothing underneath, so the
  // ruleset's largest multiplier (3.5x) hit hardest at the smallest prices. Below 0.05:
  // 66 legs, 33 markets, $1,694, clip $25.66 (largest in the book), avgP 0.034,
  // settlement hit 0.0% vs a 3.39% break-even, -$1,041 realized (-61%). 0.05-0.20 earns
  // +98%..+102% on truth and is NOT touched. 0 = no floor (legacy).
  // NOTE: this factor is BANKROLL_200-only -- mapBankroll200Size is gated
  // `botId === "BANKROLL_200"` in openPaperTrade, so STANDARD's sub-0.05 legs never
  // received the 3.5x and are sized by the standard path instead.
  c200LongshotBandFloor: number;
  c200DeadZoneBandFactor: number; // 0.40–0.60 entries (default 0.25)
  // v68 (2026-10-27, user-approved "approve standard-maturity-size-factor"): STANDARD sizes
  // FLAT across an axis whose realised ROI spans 9x -- <24h -6.0%, 24-72h +2.0%, >=72h +21.4%
  // -- because the two band factors on its path were neutralised to 1.0 by v41 and Kelly is
  // C-200-only, so STANDARD books the same clip everywhere. These five fields are the maturity
  // schedule, keyed on time-to-resolution AT ENTRY (the only maturity variable a rule can act on
  // before the trade; realised holding time is post-treatment and cannot be gated).
  // ALL DEFAULTS ARE 1.0 == disabled, so a ruleset without these fields is byte-identical to v67.
  // STANDARD-only: the C-200 path never reads them (see paper.ts).
  standardMaturityFactorShort: number; // ttr <  standardMaturityShortHours
  standardMaturityShortHours: number; // default 24
  standardMaturityFactorMedium: number; // shortHours .. longHours
  standardMaturityLongHours: number; // default 72
  standardMaturityFactorLong: number; // ttr >= standardMaturityLongHours
  // v69 (2026-10-27, approved): optional 4th bucket for very long-dated legs. v68 put 3-7d, 7-30d and
  // >30d all at 1.5x, but they measure +46.8% / +19.9% / +12.8% and >30d earns +$2.88 per
  // $1k-capital-day against 3-7d's +$127.85 (median hold 36.7 days). Default hugeHours = 1e9 makes the
  // bucket INERT, so a ruleset without these fields is byte-identical to v68.
  standardMaturityHugeHours: number; // default 1e9 = inert
  standardMaturityFactorHuge: number; // factor for ttr >= hugeHours
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
  // v44 (tuning review #13, 2026-09-02, approved): STANDARD high-side entry
  // cap. Enforced per-leg in score-trades.ts (NOT via maxEntryPrice — that
  // gate is symmetric [1−max, max] and lowering it would kill the <0.15
  // long-shot edge). 0 = disabled.
  standardMaxEntryPrice: number;
  // v47 (2026-09-03 daily report, approved): C-200 high-side entry cap —
  // 0.80+ entries are the z=−2.48 premium drag. Same per-leg enforcement
  // pattern as standardMaxEntryPrice (never via the symmetric maxEntryPrice).
  // 0 = disabled.
  c200MaxEntryPrice: number;
  // v48 (2026-09-04 daily report, approved): band-aware admission floors for
  // <longshotMaxPrice entries. The long-shot band (z=+3.81, the only +PnL
  // band) is structurally anti-selected by win-rate-derived bars (low win
  // rate is why it's priced at ~12¢). When the entry price < longshotMaxPrice,
  // the copy/confidence floors relax to these values; 0 = keep global floors.
  longshotMinCopyScore: number;
  longshotMinConfidence: number;
  // v45 (execution-leak Step 2, 2026-09-03, approved): per-bot market-category
  // blacklists — the structural −EV slug set (lol/cs2/nfl/… lose for BOTH
  // bots regardless of venue; verified 2026-09-03: C-200 −$801, STANDARD
  // −$4.4k+ recoverable). Per-bot because dota2/elon are C-200-positive
  // (+$87/+$30) while STANDARD-negative. Question-fragment slugs (what/of/the/
  // where/which) are deliberately EXCLUDED — they wrap hundreds of real
  // markets each. Empty array = disabled.
  c200Blacklist: string[];
  standardBlacklist: string[];
  // v55 (2026-09-16 C-200 daily report Change 1, user-approved): PER-MARKET
  // concentration ceiling. maxMarketSlugPositions counts the research CATEGORY
  // (a slug wraps many markets), so nothing capped legs in one marketId — and
  // v54's 2.5x long-shot factor lifted the <0.20 band's average clip to ~$33, so
  // accumulation can now put $250+ into a single binary (the 7-day loss was 76%
  // two markets). Two independent limits, whichever binds first; 0 = disabled.
  maxMarketNotionalPctOfCap: number; // ceiling = pct × effective exposure cap
  maxMarketLegsPerMarketId: number; // max open legs in one marketId
  // v58 (2026-09-19 tuning review #30 rec 1, user-approved): PER-WALLET
  // concentration ceiling — the mirror of the v55 per-market rail, and the
  // half that did not exist. One wallet reached 84.6% of the C-200 book
  // (top-3 94.1%) on a book that tripled to $1,179.45 while the per-market
  // analogue was measured non-binding, so the two rails no longer confound
  // each other. Expressed as a fraction of the effective exposure cap, so the
  // ceiling scales with the equity-linked cap. 0 = disabled.
  maxWalletNotionalPctOfCap: number; // ceiling = pct × effective exposure cap
  // v59 (2026-09-19 daily report rec 2, user-approved): the BASIS the per-wallet
  // ceiling is measured on. "stock" (default/legacy) = the wallet's whole open
  // notional, which freezes a wallet already above the ceiling outright; "delta"
  // = pre-activation notional is GRANDFATHERED, so the ceiling becomes
  // baseline(wallet) + pct × cap and only new accumulation is gated. Baseline
  // lives in data/wallet-cap-baseline.json (see src/lib/wallet-cap-basis.ts).
  walletCapBasis: string; // "stock" | "delta"
  // v56 (2026-09-19 tuning review #29 rec 3, user-approved): the drawdown /
  // exposure BASIS as a first-class rule field, so "which basis is in force" is
  // a versioned fact in the RuleSet rather than only a line in a state file.
  // "mtm" | "realized" | "min". Empty string = not set → fall back to
  // data/c200-drawdown.json, then to "mtm" (legacy behavior).
  ddBasis: string;
  // v60 (2026-09-20 C-200 daily report change 1, user-approved): BAND-SCOPED SIZE
  // FACTOR. The 0.60-0.80 band is the one significant negative band (excess -0.0995,
  // z=-3.96 on N=382) and it produced essentially nothing (+$2.66 over 30d on $1,015
  // of flow) while taking a third of the day's opens, so its new copies are sized
  // down. Applied to the FINAL size of C-200 copies with an entry price inside
  // c200BandSizeFactorRange ("lo-hi", lo inclusive / hi exclusive; empty = disabled),
  // whatever lane booked them — the premium overlay could not deliver this because it
  // skips short-TTR lane copies and is band-driven (see src/lib/band-size.ts).
  c200BandSizeFactor: number; // 1 = no change
  c200BandSizeFactorRange: string; // e.g. "0.6-0.8"
  // v62 (2026-10-11 C-200 daily report change 2, user-approved): HARD-SKIP a price band
  // for C-200 copies. "lo-hi" (lo inclusive / hi exclusive, the same parser and the same
  // boundary semantics as c200BandSizeFactorRange), empty = disabled. A skip and not
  // another size factor because the 0.40–0.60 band is what it is (−7.4% all-time over
  // 1,048 legs) and it is spending the binding levers — maxCopiesPerCycle,
  // maxCopiesPerWalletPerDay, maxOpenPositions — while producing 0.1% of PnL; sizing there
  // is floored ($0.25–$1.25) so it cannot be shrunk to zero. Applies to every lane that
  // books a C-200 leg (main, short-TTR, Kelly rails) so the rail cannot be worked around.
  c200SkipBandRange: string; // e.g. "0.4-0.6"; empty = no skip
  // v63 (2026-10-20 profit review, user-approved in-thread): the SAME hard band skip for
  // STANDARD, closing a scoping gap — every band/skip rail since v41 had been written
  // `botId === "BANKROLL_200"`, so the lane carrying 99% of the open book never got one and
  // sized flat across bands where edge ranges from +47.75% to −7.67%. Empty = no skip.
  standardSkipBandRange: string; // e.g. "0.4-0.6"; empty = no skip
  // v45: per-market-slug open-position cap for C-200. The v41 research-category
  // gate maps esports to "Other" (uncapped), letting lol/cs2 pile up without a
  // gate; this caps open positions per raw marketCategory slug. 0 = disabled.
  maxMarketSlugPositions: number;
  // v45: whale-liquidity guard — wallets trading large size (> whaleSizeUsd)
  // in their home category are often the liquidity, not the edge (esports pros
  // score 78–82 via category-fit but their trades don't move markets). Caps
  // the category-fit score component at whaleCategoryFitCap for those trades.
  whaleSizeUsd: number;
  whaleCategoryFitCap: number;
  // v49 (Phase B, 2026-09-05 design drafts/phase-b-kelly-design.md): Kelly
  // sizing for C-200 main-lane copies. When kellyEnabled=1 the calibrated
  // edge (band λ̂ from data/premium-calibration.json) decides size AND skip:
  //   fair q = Φ(Φ⁻¹(p) − λ̂);  f* = (q − p)/(1 − p) on the bought token
  //   size  = min(fraction·f*·avail, maxBankrollPct·avail, maxSizeUsd)
  // Kelly REPLACES the ×3 confidence boost and the v38 premium-overlay resize
  // (premiumOverlayEnabled set 0 in the same ruleset change); the paper.ts
  // v41 band remap is bypassed for Kelly-sized copies (no double sizing).
  // Admission (copyScore/confidence bars) is unchanged. Short-TTR lane keeps
  // its fixed size (channel design). avail = bot cashBalance (free cash —
  // fills already decrement it, so open exposure is NOT subtracted again).
  // 0 = legacy sizing path, byte-identical to pre-v49 behavior.
  kellyEnabled: number; // 1 = Kelly sizing active, 0 = legacy
  kellyFraction: number; // fractional-Kelly multiplier (0.5 = half-Kelly)
  kellyMaxBankrollPct: number; // per-position cap as % of available bankroll
  kellyMaxSizeUsd: number; // hard per-position USD cap (executor clamp override)
  kellyMinBetUsd: number; // skip dust below this
  kellyMinEdgePct: number; // skip when f* < this (0.02 = 2%)
}

export const DEFAULT_RULES: Rules = {
  maxSpread: 0.05,
  minLiquidity: 5000,
  maxPriceDrift: 0.08,
  longshotDriftPct: 0,
  longshotDriftCap: 0.02,
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
  // v65 default 1 = legacy (wallet quality feeds the size bucket). The active
  // ruleset sets 0 via scripts/apply-v65.ts; revert = set this field back to 1.
  walletQualityInSize: 1,
  highScoreMaxDrift: 0.004,
  maxOpenPositions: 100,
  // v64: disabled by default -- same convention as every other added rail.
  standardMaxOpenPositions: 0,
  // v66: 0 = disabled. 168h matches the C-200 hard max-age that v33 established, and
  // 0.60 is the measured scope. See the type comment; do not lower the band.
  standardStaleExitHours: 0,
  standardStaleExitBandMin: 0.6,
  staleExitHours: 48,
  staleExitMinMove: 0.05,
  // v53: adverse-only tier-1 (live values land in the DB ruleset at activation).
  // Default 0 keeps legacy behavior; the −15% threshold is the value the
  // 2026-09-13 report measured against (1,069 cut rows, −17.0% ROI in 24–72h).
  staleExitAdverseOnly: 0,
  staleExitAdverseMove: -0.15,
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
  // v54: the live C-200 band map (paper.ts mapBankroll200Size owns the tilt).
  c200LongshotBandFactor: 2.0,
  // v67: 0 = no floor, so a ruleset lacking the field is byte-identical to pre-v67.
  c200LongshotBandFloor: 0,
  // v68: maturity schedule, DISABLED by default (every factor 1.0). The live values
  // (0.5 / 1.0 / 1.5) land in the DB ruleset via scripts/apply-v68.ts, never in the code default,
  // so an un-migrated environment and a revert both behave exactly like v67.
  standardMaturityFactorShort: 1.0,
  standardMaturityShortHours: 24,
  standardMaturityFactorMedium: 1.0,
  standardMaturityLongHours: 72,
  standardMaturityFactorLong: 1.0,
  // v69: inert by default — 1e9 hours is longer than any market's life, so the 4th bucket never fires
  // until a ruleset sets a real bound.
  standardMaturityHugeHours: 1e9,
  standardMaturityFactorHuge: 1.0,
  c200DeadZoneBandFactor: 0.25,
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
  // v44: STANDARD entries ≥ 0.85 are the worst band (z=−2.50, p=0.013).
  standardMaxEntryPrice: 0.85,
  // v47: C-200 entries ≥ 0.80 (z=−2.48 premium drag; −8.5pp excess 0.80–1.01).
  c200MaxEntryPrice: 0.8,
  // v48: <0.20 long-shot band — median historical copyScore 72 / conf 0.57;
  // the global 80/0.7 bars admitted 3 of 64 signals.
  longshotMinCopyScore: 70,
  longshotMinConfidence: 0.55,
  // v55: per-market ceiling disabled by default (legacy semantics; activation
  // is an explicit ruleset change).
  maxMarketNotionalPctOfCap: 0,
  maxMarketLegsPerMarketId: 0,
  // v58: per-wallet ceiling disabled by default, same convention.
  maxWalletNotionalPctOfCap: 0,
  walletCapBasis: "stock",
  // v60: band-scoped size factor disabled by default, same convention.
  c200BandSizeFactor: 1,
  c200BandSizeFactorRange: "",
  // v62: band skip disabled by default, same convention.
  c200SkipBandRange: "",
  // v63: STANDARD band skip disabled by default, same convention.
  standardSkipBandRange: "",
  ddBasis: "mtm",
  // v45 defaults (live values land in the DB ruleset at activation).
  c200Blacklist: [],
  standardBlacklist: [],
  maxMarketSlugPositions: 0,
  whaleSizeUsd: 0,
  whaleCategoryFitCap: 60,
  // v49 Phase-B Kelly defaults (drafts/phase-b-kelly-design.md §5). Default
  // kellyEnabled=0 keeps every ruleset lacking the fields on the LEGACY
  // sizing path — activation is an explicit rule change (apply-v49.ts sets
  // kellyEnabled=1 + premiumOverlayEnabled=0 in one ruleset version).
  kellyEnabled: 0,
  kellyFraction: 0.5,
  kellyMaxBankrollPct: 0.1,
  kellyMaxSizeUsd: 60,
  kellyMinBetUsd: 2.0,
  kellyMinEdgePct: 0.02,
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
  newValue: number | string | string[];
  reason: string;
  evidence: string;
}

/**
 * Apply proposals as a new rule version. Old version is deactivated, the new
 * one activated, and a RuleChange row records everything. String[] values
 * (e.g. category blacklists) are supported and stored as JSON.
 */
export async function applyRuleChanges(
  proposals: RuleChangeProposal[],
  changedBy = "hermes"
): Promise<{ newVersion: number } | null> {
  if (proposals.length === 0) return null;
  const { rules, version, id: oldId } = await getActiveRules();
  const before: Record<string, number | string | string[]> = {};
  const after: Record<string, number | string | string[]> = {};
  const newRules: Rules = { ...rules };
  for (const p of proposals) {
    before[p.field] = rules[p.field] as number | string | string[];
    (newRules as unknown as Record<string, number | string | string[]>)[p.field] = p.newValue;
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

/**
 * v57 change A (2026-09-18 daily report, user-approved): effective price-drift
 * tolerance for one entry.
 *
 * A flat 0.4c tolerance is 0.7% of price at 0.60 but 2-8% of price at 0.05-0.20,
 * so the band carrying the widest measured edge (excess +22.5pp, z=+5.79) was the
 * one most often blocked as "too late". With longshotDriftPct > 0, entries below
 * longshotMaxPrice get max(maxPriceDrift, pct x price), capped at longshotDriftCap.
 * longshotDriftPct = 0 keeps the legacy flat tolerance for every band.
 */
export function effectiveDriftTolerance(
  rules: Pick<Rules, "maxPriceDrift" | "longshotMaxPrice" | "longshotDriftPct" | "longshotDriftCap">,
  entryPrice: number
): number {
  if (!(rules.longshotDriftPct > 0) || !(entryPrice < rules.longshotMaxPrice)) return rules.maxPriceDrift;
  const cap = rules.longshotDriftCap > 0 ? rules.longshotDriftCap : rules.maxPriceDrift;
  return Math.min(cap, Math.max(rules.maxPriceDrift, rules.longshotDriftPct * entryPrice));
}
