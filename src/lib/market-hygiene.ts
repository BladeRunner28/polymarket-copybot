/**
 * Market-hygiene shadow scores — offline, advisory-only.
 *
 * Ported formulas (NOT code) from polyterm (MIT), see
 * drafts/polyterm-audit-2026-09-28.md §P3/§P5:
 *   - wash-trade indicators  <- core/wash_trade_detector.py:181-260, 67-69
 *   - 6-factor market risk   <- core/risk_score.py:45-52, 197-358
 *   - holder concentration   <- Data API /holders (api/data_api.py:137-144);
 *                               the concentration statistic itself is ours.
 *
 * WHY THIS IS PURE AND ADVISORY-ONLY: every threshold below is a hypothesis
 * from another repo, unvalidated on our data. The Kelly measurement window is
 * frozen (through 2026-10-08), and our doctrine is that a rule, a size, a gate
 * or a published number may not move on an unmeasured input. So these functions
 * compute a score, label it `heuristic`, and nothing imports them into the live
 * path. The pre-registered read (rank correlation vs realized copies, per
 * era) decides whether that ever changes — see the audit's Trial B.
 *
 * Tier tables are copied faithfully from the source (scores included) so a
 * later comparison against their published behaviour is possible; where the
 * source had no name for a band, the label is ours and is marked as such.
 */

/** Inputs the scores need. All optional: a missing input skips its indicator. */
export type HygieneMarketInput = {
  slug: string;
  question?: string;
  description?: string;
  /** Market category text used by the dispute-rate proxy (our coarse class). */
  categoryForRisk?: string;
  endDate?: Date | null;
  volume24hr?: number;
  liquidity?: number;
  spread?: number;
  closed?: boolean;
  /** Print-tape stats, when we have them (Data API short window). */
  tradeCount?: number;
  uniqueTraders?: number;
  avgTradeSize?: number;
  medianTradeSize?: number;
  yesVolume?: number;
  noVolume?: number;
};

export type WashIndicator = {
  type: "volume_liquidity" | "trader_concentration" | "size_uniformity" | "side_balance" | "volume_anomaly";
  score: number; // 0-100, higher = more suspicious
  detail: string;
};

export type WashProfile = {
  /** Weighted mean of the indicators (weight = 1 + score/100), 0 when none fired. */
  score: number;
  /** Band label — the thresholds are polyterm's; the wording is ours. */
  band: "clean" | "low" | "moderate" | "high";
  indicators: WashIndicator[];
  /** False when no indicator could be computed (missing inputs) — not the same as clean. */
  assessed: boolean;
};

/** polyterm `wash_trade_detector.py:67-69`. */
export const WASH_THRESHOLDS = {
  volumeLiquidity: 3.0,
  tradeSizeUniformity: 0.8,
  timeClustering: 0.7,
} as const;

/** polyterm `risk_score.py:45-52`. */
export const RISK_WEIGHTS = {
  resolutionClarity: 0.25,
  liquidity: 0.2,
  timeRisk: 0.15,
  volumeQuality: 0.15,
  spread: 0.15,
  categoryRisk: 0.1,
} as const;

/** polyterm `risk_score.py:55-69`. */
export const SUBJECTIVE_KEYWORDS = [
  "effectively",
  "essentially",
  "significant",
  "major",
  "meaningful",
  "substantial",
  "largely",
  "mainly",
  "generally",
  "typically",
  "consensus",
  "widely",
  "broadly",
  "most people",
  "mainstream",
] as const;

export const HIGH_DISPUTE_CATEGORIES = ["politics", "legal", "regulatory", "media", "social"] as const;
export const LOW_DISPUTE_CATEGORIES = ["sports", "crypto", "finance", "weather", "science"] as const;

export type RiskFactor = { key: string; score: number; weight: number; reason: string };

export type RiskGrade = {
  /** Weighted sum, 0-100 (higher = riskier). */
  score: number;
  grade: "A" | "B" | "C" | "D" | "F";
  factors: RiskFactor[];
  warnings: string[];
};

/** polyterm `wash_trade_detector.py:195-225` — vol/liq ratio tiers. */
function volumeLiquidityIndicator(volume24hr: number, liquidity: number): WashIndicator | null {
  if (liquidity <= 0) {
    return { type: "volume_liquidity", score: 50, detail: "cannot assess - no liquidity data" };
  }
  if (volume24hr <= 0) return null;
  const ratio = volume24hr / liquidity;
  if (ratio > 10.0) return { type: "volume_liquidity", score: 90, detail: `volume is ${ratio.toFixed(1)}x liquidity - strong signal` };
  if (ratio > 5.0) return { type: "volume_liquidity", score: 75, detail: `volume is ${ratio.toFixed(1)}x liquidity - suspicious pattern` };
  if (ratio > WASH_THRESHOLDS.volumeLiquidity) return { type: "volume_liquidity", score: 55, detail: `volume is ${ratio.toFixed(1)}x liquidity` };
  if (ratio > 1.0) return { type: "volume_liquidity", score: 30, detail: `ratio ${ratio.toFixed(1)}x` };
  return null;
}

/** polyterm `wash_trade_detector.py:227-257` — trades-per-wallet tiers. */
function traderConcentrationIndicator(tradeCount: number, uniqueTraders: number): WashIndicator | null {
  if (tradeCount <= 0 || uniqueTraders <= 0) return null;
  const perTrader = tradeCount / uniqueTraders;
  if (perTrader > 20) return { type: "trader_concentration", score: 85, detail: `avg ${perTrader.toFixed(1)} trades/wallet - few wallets driving volume` };
  if (perTrader > 10) return { type: "trader_concentration", score: 65, detail: `avg ${perTrader.toFixed(1)} trades/wallet` };
  if (perTrader > 5) return { type: "trader_concentration", score: 40, detail: `avg ${perTrader.toFixed(1)} trades/wallet` };
  return null;
}

/** polyterm `wash_trade_detector.py:259-284` — median/avg size uniformity. */
function sizeUniformityIndicator(avgSize: number, medianSize: number): WashIndicator | null {
  if (avgSize <= 0 || medianSize <= 0) return null;
  const ratio = medianSize / avgSize;
  if (ratio > 0.9) return { type: "size_uniformity", score: 75, detail: `median/avg ${ratio.toFixed(2)} - trades are too similar` };
  if (ratio > 0.8) return { type: "size_uniformity", score: 50, detail: `median/avg ${ratio.toFixed(2)}` };
  return null;
}

/** polyterm `wash_trade_detector.py:286-311` — YES/NO volume symmetry. */
function sideBalanceIndicator(yesVolume: number, noVolume: number): WashIndicator | null {
  if (yesVolume <= 0 || noVolume <= 0) return null;
  const balance = Math.min(yesVolume, noVolume) / Math.max(yesVolume, noVolume);
  if (balance > 0.95) return { type: "side_balance", score: 70, detail: `balance ratio ${balance.toFixed(2)} - unusual symmetry` };
  if (balance > 0.85) return { type: "side_balance", score: 45, detail: `balance ratio ${balance.toFixed(2)}` };
  return null;
}

/** polyterm `wash_trade_detector.py:313-333` — reported volume vs trade arithmetic. */
function volumeAnomalyIndicator(volume24hr: number, tradeCount: number, avgTradeSize: number): WashIndicator | null {
  if (tradeCount <= 0 || avgTradeSize <= 0 || volume24hr <= 0) return null;
  const expected = tradeCount * avgTradeSize;
  const discrepancy = Math.abs(volume24hr - expected) / volume24hr;
  if (discrepancy > 0.5) {
    return { type: "volume_anomaly", score: 60, detail: `reported volume differs from trade data by ${Math.round(discrepancy * 100)}%` };
  }
  return null;
}

/**
 * Wash-trade profile. Indicators that cannot be computed are omitted (and the
 * result reports `assessed: false` when none could be), so "no signal" is never
 * confused with "clean".
 */
export function washTradeProfile(input: HygieneMarketInput): WashProfile {
  const indicators: WashIndicator[] = [];
  const add = (i: WashIndicator | null) => {
    if (i) indicators.push(i);
  };
  if (input.volume24hr !== undefined && input.liquidity !== undefined) {
    add(volumeLiquidityIndicator(input.volume24hr, input.liquidity));
  }
  if (input.tradeCount !== undefined && input.uniqueTraders !== undefined) {
    add(traderConcentrationIndicator(input.tradeCount, input.uniqueTraders));
  }
  if (input.avgTradeSize !== undefined && input.medianTradeSize !== undefined) {
    add(sizeUniformityIndicator(input.avgTradeSize, input.medianTradeSize));
  }
  if (input.yesVolume !== undefined && input.noVolume !== undefined) {
    add(sideBalanceIndicator(input.yesVolume, input.noVolume));
  }
  if (input.volume24hr !== undefined && input.tradeCount !== undefined && input.avgTradeSize !== undefined) {
    add(volumeAnomalyIndicator(input.volume24hr, input.tradeCount, input.avgTradeSize));
  }

  // polyterm `:144-156`: weight = 1 + score/100, weighted mean, integer.
  const totalWeight = indicators.reduce((a, i) => a + (1 + i.score / 100), 0);
  const weighted = indicators.reduce((a, i) => a + i.score * (1 + i.score / 100), 0);
  const score = totalWeight > 0 ? Math.round(weighted / totalWeight) : 0;
  // Bands are polyterm `:152-156` (<=25 / <=45 / <=65); labels are ours.
  const band: WashProfile["band"] = score <= 25 ? "clean" : score <= 45 ? "low" : score <= 65 ? "moderate" : "high";
  return { score, band, indicators, assessed: indicators.length > 0 };
}

/** polyterm `risk_score.py:197-237` — resolution clarity. */
function resolutionClarityScore(input: HygieneMarketInput): RiskFactor {
  const text = `${input.question ?? ""} ${input.description ?? ""}`.toLowerCase();
  let score = 0;
  const reasons: string[] = [];
  const subjectiveCount = SUBJECTIVE_KEYWORDS.reduce((a, kw) => a + (text.includes(kw) ? 1 : 0), 0);
  if (subjectiveCount >= 3) {
    score += 40;
    reasons.push("multiple subjective terms");
  } else if (subjectiveCount >= 1) {
    score += 20;
    reasons.push("some subjective language");
  }
  const clearSources = ["official", "government", "data", "api", "verifiable"];
  if (!clearSources.some((s) => text.includes(s))) {
    score += 25;
    reasons.push("no clear resolution source specified");
  }
  if (!text.includes("will") && !text.includes("does")) {
    score += 15;
    reasons.push("question format may need interpretation");
  }
  if (/\d{4}|\d+%|\$\d+/.test(text)) {
    score -= 10;
    reasons.push("has specific numeric criteria");
  }
  score = Math.max(0, Math.min(100, score));
  return {
    key: "resolution_clarity",
    score,
    weight: RISK_WEIGHTS.resolutionClarity,
    reason: reasons.length ? reasons.join("; ") : "resolution appears clear",
  };
}

/** polyterm `risk_score.py:239-255` — liquidity tiers. */
function liquidityScore(liquidity: number | undefined): RiskFactor {
  const raw = liquidity ?? 0;
  let score: number;
  let reason: string;
  if (raw <= 0) {
    score = 80;
    reason = "no liquidity data available";
  } else if (raw >= 500000) {
    score = 0;
    reason = "excellent liquidity";
  } else if (raw >= 100000) {
    score = 15;
    reason = "good liquidity";
  } else if (raw >= 50000) {
    score = 30;
    reason = "moderate liquidity";
  } else if (raw >= 10000) {
    score = 50;
    reason = "low liquidity";
  } else if (raw >= 1000) {
    score = 70;
    reason = "very low liquidity";
  } else {
    score = 90;
    reason = "minimal liquidity";
  }
  return { key: "liquidity", score, weight: RISK_WEIGHTS.liquidity, reason: `${reason} ($${Math.round(raw).toLocaleString("en-US")})` };
}

/** polyterm `risk_score.py:257-285` — time-to-resolution tiers. */
function timeRiskScore(endDate: Date | null | undefined, now: Date): RiskFactor {
  if (!endDate || isNaN(endDate.getTime())) {
    return { key: "time_risk", score: 50, weight: RISK_WEIGHTS.timeRisk, reason: "no end date specified" };
  }
  if (endDate.getTime() < now.getTime()) {
    return { key: "time_risk", score: 0, weight: RISK_WEIGHTS.timeRisk, reason: "market has ended" };
  }
  const days = Math.floor((endDate.getTime() - now.getTime()) / 86_400_000);
  const tier = days <= 1 ? 10 : days <= 7 ? 15 : days <= 30 ? 25 : days <= 90 ? 40 : days <= 365 ? 60 : 80;
  return { key: "time_risk", score: tier, weight: RISK_WEIGHTS.timeRisk, reason: `${days} days remaining` };
}

/** polyterm `risk_score.py:287-311` — volume quality (wash-trading proxy). */
function volumeQualityScore(volume24hr: number | undefined, liquidity: number | undefined): RiskFactor {
  const vol = volume24hr ?? 0;
  const liq = liquidity ?? 0;
  let score: number;
  let reason: string;
  if (vol <= 0) {
    score = 40;
    reason = "no recent volume";
  } else if (liq <= 0) {
    score = 50;
    reason = "cannot assess volume quality without liquidity data";
  } else {
    const ratio = vol / liq;
    if (ratio > 5.0) {
      score = 85;
      reason = `volume/liquidity very high (${ratio.toFixed(1)}x) - possible wash trading`;
    } else if (ratio > 2.0) {
      score = 60;
      reason = `volume/liquidity elevated (${ratio.toFixed(1)}x)`;
    } else if (ratio > 0.5) {
      score = 20;
      reason = `healthy volume/liquidity (${ratio.toFixed(1)}x)`;
    } else if (ratio > 0.1) {
      score = 30;
      reason = `low volume relative to liquidity (${ratio.toFixed(1)}x)`;
    } else {
      score = 45;
      reason = `very low trading activity (${ratio.toFixed(1)}x)`;
    }
  }
  return { key: "volume_quality", score, weight: RISK_WEIGHTS.volumeQuality, reason };
}

/** polyterm `risk_score.py:313-329` — spread tiers, in percentage points. */
function spreadScore(spread: number | undefined): RiskFactor {
  const raw = spread ?? 0;
  let score: number;
  let reason: string;
  if (raw <= 0) {
    score = 50;
    reason = "no spread data available";
  } else {
    const pct = raw * 100;
    if (pct <= 1) {
      score = 0;
      reason = `very tight spread (${pct.toFixed(1)}%)`;
    } else if (pct <= 2) {
      score = 15;
      reason = `good spread (${pct.toFixed(1)}%)`;
    } else if (pct <= 5) {
      score = 35;
      reason = `moderate spread (${pct.toFixed(1)}%)`;
    } else if (pct <= 10) {
      score = 55;
      reason = `wide spread (${pct.toFixed(1)}%)`;
    } else {
      score = 80;
      reason = `very wide spread (${pct.toFixed(1)}%)`;
    }
  }
  return { key: "spread", score, weight: RISK_WEIGHTS.spread, reason };
}

/** polyterm `risk_score.py:331-345` — dispute-rate proxy from category keywords. */
function categoryRiskScore(category: string | undefined, question: string | undefined): RiskFactor {
  const cat = (category ?? "").toLowerCase();
  const title = (question ?? "").toLowerCase();
  const hit = (list: readonly string[]) => list.find((k) => cat.includes(k) || title.includes(k));
  const high = hit(HIGH_DISPUTE_CATEGORIES);
  if (high) {
    return { key: "category_risk", score: 60, weight: RISK_WEIGHTS.categoryRisk, reason: `higher dispute rate proxy: ${high}` };
  }
  const low = hit(LOW_DISPUTE_CATEGORIES);
  if (low) {
    return { key: "category_risk", score: 15, weight: RISK_WEIGHTS.categoryRisk, reason: `lower dispute rate proxy: ${low}` };
  }
  return { key: "category_risk", score: 35, weight: RISK_WEIGHTS.categoryRisk, reason: "average category risk" };
}

/** polyterm `risk_score.py:347-358` — numeric score to letter grade. */
export function scoreToGrade(score: number): RiskGrade["grade"] {
  if (score <= 20) return "A";
  if (score <= 35) return "B";
  if (score <= 50) return "C";
  if (score <= 70) return "D";
  return "F";
}

/**
 * 6-factor risk grade. Weighted sum of the sub-scores; higher = riskier.
 * The `heuristic` label is the point: this is a market-screening prior, not a
 * measured edge, and the source itself returns no calibration evidence for it.
 */
export function marketRiskGrade(input: HygieneMarketInput, now: Date = new Date()): RiskGrade {
  const factors: RiskFactor[] = [
    resolutionClarityScore(input),
    liquidityScore(input.liquidity),
    timeRiskScore(input.endDate, now),
    volumeQualityScore(input.volume24hr, input.liquidity),
    spreadScore(input.spread),
    categoryRiskScore(input.categoryForRisk, input.question),
  ];
  const score = Math.round(factors.reduce((a, f) => a + f.score * f.weight, 0));
  const warnings: string[] = [];
  const get = (k: string) => factors.find((f) => f.key === k);
  if ((get("resolution_clarity")?.score ?? 0) >= 60) warnings.push("resolution criteria may be subjective or unclear");
  if ((get("liquidity")?.score ?? 0) >= 60) warnings.push("low liquidity - large orders may cause slippage");
  if ((get("time_risk")?.score ?? 0) >= 60) warnings.push("long time to resolution - capital locked up");
  if ((get("volume_quality")?.score ?? 0) >= 70) warnings.push("volume pattern may indicate wash trading");
  return { score, grade: scoreToGrade(score), factors, warnings };
}

export type HolderRow = { proxyWallet?: string; amount?: number; outcomeIndex?: number };

export type ConcentrationProfile = {
  holderCount: number;
  /** Share of amount held by the largest holder (0-1). */
  top1Share: number;
  top5Share: number;
  top10Share: number;
  /** Herfindahl-Hirschman index over holder amounts (0-1). */
  hhi: number;
  /** 1/hhi — the effective number of holders. */
  effectiveHolders: number;
  assessed: boolean;
};

/**
 * Holder concentration over one outcome's holder list. Statistic is ours (HHI
 * plus top-N shares) — the source repo fetches `/holders` but never calls it,
 * so there was no formula to port.
 */
export function holderConcentration(holders: readonly HolderRow[]): ConcentrationProfile {
  const amounts = holders.map((h) => (Number.isFinite(h.amount) ? Number(h.amount) : 0)).filter((a) => a > 0);
  const total = amounts.reduce((a, b) => a + b, 0);
  if (amounts.length === 0 || total <= 0) {
    return { holderCount: 0, top1Share: 0, top5Share: 0, top10Share: 0, hhi: 0, effectiveHolders: 0, assessed: false };
  }
  const sorted = [...amounts].sort((a, b) => b - a);
  const share = (n: number) => sorted.slice(0, n).reduce((a, b) => a + b, 0) / total;
  const hhi = sorted.reduce((a, b) => a + (b / total) ** 2, 0);
  return {
    holderCount: amounts.length,
    top1Share: share(1),
    top5Share: share(5),
    top10Share: share(10),
    hhi,
    effectiveHolders: hhi > 0 ? 1 / hhi : 0,
    assessed: true,
  };
}

/**
 * A single advisory row for JSONL output. Carries the `heuristic` flag so a
 * downstream reader cannot mistake it for a measured signal, and never claims a
 * live source.
 */
export function hygieneRow(input: HygieneMarketInput, holders: readonly HolderRow[] = [], now: Date = new Date()) {
  return {
    scoredAt: now.toISOString(),
    slug: input.slug,
    wash: washTradeProfile(input),
    risk: marketRiskGrade(input, now),
    concentration: holderConcentration(holders),
    /** Nothing may read this as an edge or a gate input until the pre-registered read. */
    qualityFlags: ["heuristic_market_hygiene", "advisory_only", "not_a_gate_input"],
  };
}
