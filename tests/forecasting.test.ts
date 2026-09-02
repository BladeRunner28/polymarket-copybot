import { describe, it, expect } from "vitest";
import {
  aggregateEvidenceItems,
  corroborationFactor,
  effectiveCount,
  evidenceLogLR,
  logit,
  recencyFactor,
  sigmoid,
  trimmedMean,
  type EvidenceItem,
} from "../src/lib/forecasting";
import { buildEvidenceItems } from "../src/lib/forecasting/sentiment";
import { scoreTrade } from "../src/lib/scoring/trade";
import { DEFAULT_RULES, type Rules } from "../src/lib/rules";

const HOUR = 3_600_000;
const DAY = 86_400_000;

describe("forecasting math", () => {
  it("logit/sigmoid round-trip", () => {
    expect(sigmoid(logit(0.3))).toBeCloseTo(0.3, 6);
    expect(sigmoid(logit(0.7))).toBeCloseTo(0.7, 6);
    expect(sigmoid(0)).toBe(0.5);
  });

  it("effectiveCount collapses correlated clusters (ρ=0.6)", () => {
    expect(effectiveCount(1)).toBe(1);
    expect(effectiveCount(2)).toBeCloseTo(2 / 1.6, 6); // 1.25
    // 50 same-source signals ≈ 1.64 independent signals — the double-count fix.
    expect(effectiveCount(50)).toBeCloseTo(50 / (1 + 49 * 0.6), 6);
  });

  it("trimmedMean drops extremes on large arrays, plain mean on small", () => {
    expect(trimmedMean([1, 2, 3])).toBe(2);
    const xs = [1, 2, 3, 4, 5];
    expect(trimmedMean(xs)).toBe(3); // trims 1 and 5
    expect(trimmedMean([10, 10, 10, 10, 100])).toBeCloseTo(10, 6);
  });

  it("corroboration saturation grows sublinearly with k", () => {
    expect(corroborationFactor(0)).toBe(0);
    expect(corroborationFactor(1)).toBeCloseTo(1 - Math.exp(-0.2), 6);
    expect(corroborationFactor(10)).toBeGreaterThan(corroborationFactor(2));
    expect(corroborationFactor(10)).toBeLessThan(1);
  });

  it("recency half-life: fresh = 1, 120 days = 0.5", () => {
    expect(recencyFactor(0)).toBe(1);
    expect(recencyFactor(120)).toBe(0.5);
  });

  it("evidenceLogLR applies tier cap and quality weights", () => {
    const e: EvidenceItem = {
      cluster: "x",
      polarity: 1.0,
      typeCap: 1.0,
      verifiability: 0.9,
      corroboration: 0.3,
      consistency: 1.0,
      recency: 0.9,
    };
    const expected = 0.45 * 0.9 + 0.25 * 0.3 + 0.15 * 1.0 + 0.15 * 0.9;
    expect(evidenceLogLR(e)).toBeCloseTo(expected, 6);
    // Tier cap halves the contribution for B-tier evidence.
    expect(evidenceLogLR({ ...e, typeCap: 0.6 })).toBeCloseTo(expected * 0.6, 6);
    // Neutral polarity contributes nothing.
    expect(evidenceLogLR({ ...e, polarity: 0 })).toBe(0);
  });
});

describe("aggregateEvidenceItems", () => {
  const fresh: EvidenceItem = {
    cluster: "quiver_congress_trade",
    polarity: 0.8,
    typeCap: 1.0,
    verifiability: 0.85,
    corroboration: 0,
    consistency: 1.0,
    recency: 1.0,
  };

  it("no evidence → zero delta (market is the estimate)", () => {
    const r = aggregateEvidenceItems([], 0.6);
    expect(r.delta).toBe(0);
    expect(r.pAware).toBe(0.6);
    expect(r.n).toBe(0);
  });

  it("single strong A-tier signal moves the posterior and yields a positive delta", () => {
    const r = aggregateEvidenceItems([fresh], 0.5);
    expect(r.pNeutral).toBeGreaterThan(0.6);
    expect(r.pAware).toBeGreaterThan(0.6);
    expect(r.delta).toBeGreaterThan(0.1);
    expect(r.delta).toBeLessThan(0.18);
  });

  it("neutral evidence produces ~zero delta (the 0.0 FR-notice firewall)", () => {
    const r = aggregateEvidenceItems([{ ...fresh, polarity: 0 }], 0.5);
    expect(r.delta).toBeCloseTo(0, 6);
  });

  it("correlation correction: 50 same-source signals ≪ 50 independent signals", () => {
    const sameSource = Array.from({ length: 50 }, () => fresh);
    const independent = Array.from({ length: 50 }, (_, i) => ({
      ...fresh,
      cluster: `src_${i}`,
    }));
    const clustered = aggregateEvidenceItems(sameSource, 0.5);
    const free = aggregateEvidenceItems(independent, 0.5);
    expect(clustered.clusterCount).toBe(1);
    expect(free.clusterCount).toBe(50);
    expect(clustered.delta).toBeLessThan(free.delta * 0.6);
  });

  it("prior matters: same evidence yields a smaller delta against an already-expensive market", () => {
    const cheap = aggregateEvidenceItems([fresh], 0.4);
    const expensive = aggregateEvidenceItems([fresh], 0.85);
    expect(cheap.delta).toBeGreaterThan(expensive.delta);
  });
});

describe("buildEvidenceItems (RegulatorySignal → Evidence)", () => {
  const now = new Date();
  const rows = [
    { source: "quiver_congress_trade", sentimentScore: 0.8, confidence: 0.9, processedAt: new Date(now.getTime() - DAY) },
    { source: "congress_gov_api", sentimentScore: 0.7, confidence: 0.8, processedAt: new Date(now.getTime() - DAY) },
    { source: "quiver_congress_trade", sentimentScore: 0.6, confidence: 0.7, processedAt: new Date(now.getTime() - DAY) },
    { source: "govinfo_fr_notice", sentimentScore: -0.5, confidence: 0.5, processedAt: new Date(now.getTime() - 2 * DAY) },
  ];

  it("maps source → tier cap, confidence → verifiability, age → recency", () => {
    const [quiver, congress, quiver2, govinfo] = buildEvidenceItems(rows, now);
    expect(quiver.typeCap).toBe(1.0);
    expect(congress.typeCap).toBe(1.0);
    expect(govinfo.typeCap).toBe(0.6);
    expect(quiver.verifiability).toBe(0.9);
    expect(quiver.recency).toBeCloseTo(1 / (1 + 1 / 120), 6);
    expect(govinfo.recency).toBeCloseTo(1 / (1 + 2 / 120), 6);
  });

  it("corroboration counts DISTINCT agreeing sources (same-source duplicates excluded)", () => {
    const [quiver, congress] = buildEvidenceItems(rows, now);
    // quiver item: the only other agreeing source is congress_gov_api → k=1.
    expect(quiver.corroboration).toBeCloseTo(1 - Math.exp(-0.2), 6);
    expect(congress.corroboration).toBeCloseTo(1 - Math.exp(-0.2), 6);
  });

  it("consistency = share of the batch sharing the sign; contrarian item gets low consistency", () => {
    const [, , , govinfo] = buildEvidenceItems(rows, now);
    const [quiver] = buildEvidenceItems(rows, now);
    expect(quiver.consistency).toBe(0.75); // 3 of 4 bullish
    expect(govinfo.consistency).toBe(0.25); // 1 of 4 bearish
  });
});

describe("scoreTrade sentiment wiring (Phase A2)", () => {
  // Base score ≈ 90.1: passes minConfidence (0.82) and the ≥80 drift ceiling
  // (drift 0.002 ≤ 0.004) → clean paper_copy at the top band.
  const INPUT = {
    walletGlobalScore: 85,
    walletCategoryWinRate: 0.7,
    walletEntryPrice: 0.5,
    currentPrice: 0.502,
    spread: 0.01,
    liquidity: 60_000,
    timeToResolutionHours: 200,
  };
  const rules: Rules = { ...DEFAULT_RULES, sentimentEvidenceEnabled: 1 };

  it("applies the calibrated delta when enabled (scale 100 → +6 pts), clamped at the v34 cap", () => {
    const boosted = scoreTrade({ ...INPUT, sentimentDelta: 0.06 }, rules);
    expect(boosted.decision).toBe("paper_copy");
    expect(boosted.copyScore).toBe(DEFAULT_RULES.regulatoryScoreCap); // 79 clamp
    expect(boosted.reasons.join(" ")).toContain("Sentiment evidence edge +6.0pp");
  });

  it("penalizes a negative edge", () => {
    const base = scoreTrade(INPUT, rules);
    const penalized = scoreTrade({ ...INPUT, sentimentDelta: -0.06 }, rules);
    expect(penalized.copyScore).toBeLessThan(base.copyScore);
    expect(penalized.copyScore).toBeCloseTo(84.1, 1);
  });

  it("ignores sub-noise deltas (|delta| < 0.005)", () => {
    const base = scoreTrade(INPUT, rules);
    const quiet = scoreTrade({ ...INPUT, sentimentDelta: 0.001 }, rules);
    expect(quiet.copyScore).toBe(base.copyScore);
    expect(quiet.reasons.join(" ")).not.toContain("Sentiment evidence edge");
  });

  it("falls back to the legacy ±boost when the flag is off (revertible)", () => {
    const legacyRules: Rules = { ...DEFAULT_RULES, sentimentEvidenceEnabled: 0 };
    const deltaPath = scoreTrade({ ...INPUT, sentimentDelta: 0.06, regulatoryAgreement: 0.8 }, legacyRules);
    // Delta ignored; legacy +25 boost → clamped at 79.
    expect(deltaPath.copyScore).toBe(DEFAULT_RULES.regulatoryScoreCap);
    expect(deltaPath.reasons.join(" ")).toContain("Regulatory sentiment aligns strongly");
    const noBoost = scoreTrade({ ...INPUT, sentimentDelta: 0.06 }, legacyRules);
    expect(noBoost.copyScore).toBeCloseTo(90.1, 1);
  });
});
