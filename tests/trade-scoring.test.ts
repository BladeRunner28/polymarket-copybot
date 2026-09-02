import { describe, it, expect } from "vitest";
import { scoreTrade } from "../src/lib/scoring/trade";
import { researchCategoryFor } from "../src/lib/research-categories";
import { DEFAULT_RULES, type Rules } from "../src/lib/rules";
import { PAPER_MIN_SIZE_USD, PAPER_MAX_SIZE_USD } from "../src/lib/safety";

const GOOD_INPUT = {
  walletGlobalScore: 80,
  walletCategoryWinRate: 0.7,
  walletEntryPrice: 0.5,
  currentPrice: 0.51,
  spread: 0.01,
  liquidity: 60_000,
  timeToResolutionHours: 200,
};

describe("scoreTrade", () => {
  it("paper-copies a clean high-quality signal", () => {
    // Near-instant entry (drift 0.002) — a ≥80 score must clear the v29
    // high-score drift ceiling (0.004) to copy.
    const r = scoreTrade({ ...GOOD_INPUT, currentPrice: 0.502 }, DEFAULT_RULES);
    expect(r.decision).toBe("paper_copy");
    expect(r.simulatedPositionSize).not.toBeNull();
    expect(r.reasons.length).toBeGreaterThan(0);
  });

  it("keeps simulated size within $.25-$20 even at extreme confidence", () => {
    const r = scoreTrade(
      { ...GOOD_INPUT, walletGlobalScore: 100, walletCategoryWinRate: 1, currentPrice: 0.502 },
      DEFAULT_RULES
    );
    expect(r.decision).toBe("paper_copy");
    expect(r.simulatedPositionSize!).toBeGreaterThanOrEqual(PAPER_MIN_SIZE_USD);
    expect(r.simulatedPositionSize!).toBeLessThanOrEqual(PAPER_MAX_SIZE_USD);
  });

  it("sizes ≥80 at the top allocation (v37 dead-zone factor neutralized in v41 — bands sized in paper.ts)", () => {
    // currentPrice 0.502 sits in the old 0.2–0.6 dead zone — the rules-layer
    // factor is now 1.0 (v41); the ×0.75/×0.5 bands live in paper.ts.
    const r = scoreTrade(
      { ...GOOD_INPUT, walletGlobalScore: 95, walletCategoryWinRate: 0.9, currentPrice: 0.502 },
      DEFAULT_RULES
    );
    expect(r.decision).toBe("paper_copy");
    expect(r.copyScore).toBeGreaterThanOrEqual(DEFAULT_RULES.highScoreCapMin); // ≥80
    expect(r.simulatedPositionSize!).toBe(DEFAULT_RULES.highScoreCapUsd); // 18
  });

  it("sizes long-shot entries (< $0.20) at the top allocation (v37 1.5× moved to paper.ts in v41)", () => {
    // Entry at 0.15 → $18 (the 1.5× long-shot boost now lives in paper.ts).
    const r = scoreTrade(
      { ...GOOD_INPUT, walletGlobalScore: 95, walletCategoryWinRate: 0.9, walletEntryPrice: 0.15, currentPrice: 0.15 },
      DEFAULT_RULES
    );
    expect(r.decision).toBe("paper_copy");
    expect(r.copyScore).toBeGreaterThanOrEqual(DEFAULT_RULES.highScoreCapMin);
    expect(r.simulatedPositionSize!).toBe(DEFAULT_RULES.highScoreCapUsd); // 18
  });

  it("skips below-minimum-confidence signals (v37) even with a copyable score", () => {
    // ~77 score but confidence (77−45)/55 ≈ 0.59 < minConfidence 0.70 → hard skip.
    const r = scoreTrade(
      { ...GOOD_INPUT, walletGlobalScore: 55, walletCategoryWinRate: 0.5, currentPrice: 0.502 },
      DEFAULT_RULES
    );
    expect(r.decision).toBe("skip");
    expect(r.risks.join(" ")).toContain("confidence");
  });

  it("rejects ≥80 late entries (drift beyond the high-score ceiling)", () => {
    const r = scoreTrade({ ...GOOD_INPUT, walletGlobalScore: 95, currentPrice: 0.505 }, DEFAULT_RULES);
    expect(r.decision).toBe("skip");
    expect(r.risks.join(" ")).toContain("late entry");
  });

  it("lets ≥80 signals with drift beyond the ceiling through the short-TTR lane", () => {
    const laneRules: Rules = {
      ...DEFAULT_RULES,
      shortTtrMaxHours: 72,
      shortTtrMinCopyScore: 35,
      shortTtrMaxDrift: 0.05,
      shortTtrSizeUsd: 10,
    };
    const r = scoreTrade(
      { ...GOOD_INPUT, walletGlobalScore: 95, currentPrice: 0.505, timeToResolutionHours: 48 },
      laneRules
    );
    expect(r.decision).toBe("paper_copy"); // NOT skipped by the high-score drift filter
    expect(r.simulatedPositionSize!).toBe(DEFAULT_RULES.highScoreCapUsd); // 18 (factor neutralized, v41)
  });

  it("routes sub-threshold signals through the short-TTR lane at lane size", () => {
    const laneRules: Rules = {
      ...DEFAULT_RULES,
      minWalletGlobalScore: 40, // v28 DB value — lane fixture wallet (42) clears it
      shortTtrMaxHours: 72,
      shortTtrMinCopyScore: 35,
      shortTtrMaxDrift: 0.05,
      shortTtrSizeUsd: 10,
    };
    const r = scoreTrade(
      { ...GOOD_INPUT, walletGlobalScore: 42, walletCategoryWinRate: 0.3, currentPrice: 0.53, timeToResolutionHours: 48 },
      laneRules
    );
    expect(r.decision).toBe("paper_copy");
    expect(r.lane).toBe("short_ttr");
    expect(r.simulatedPositionSize!).toBe(laneRules.shortTtrSizeUsd);
  });

  it("skips when spread exceeds rule threshold", () => {
    const r = scoreTrade({ ...GOOD_INPUT, spread: 0.2 }, DEFAULT_RULES);
    expect(r.decision).toBe("skip");
    expect(r.risks.join(" ")).toContain("spread");
  });

  it("skips illiquid markets", () => {
    const r = scoreTrade({ ...GOOD_INPUT, liquidity: 100 }, DEFAULT_RULES);
    expect(r.decision).toBe("skip");
    expect(r.risks.join(" ")).toContain("liquidity");
  });

  it("skips late entries (price drifted too far)", () => {
    const r = scoreTrade({ ...GOOD_INPUT, currentPrice: 0.75 }, DEFAULT_RULES);
    expect(r.decision).toBe("skip");
    expect(r.risks.join(" ")).toContain("drift");
  });

  it("skips weak wallets regardless of market quality", () => {
    const r = scoreTrade({ ...GOOD_INPUT, walletGlobalScore: 20 }, DEFAULT_RULES);
    expect(r.decision).toBe("skip");
    expect(r.risks.join(" ")).toContain("wallet score");
  });

  it("skips markets resolving too soon", () => {
    const r = scoreTrade({ ...GOOD_INPUT, timeToResolutionHours: 2 }, DEFAULT_RULES);
    expect(r.decision).toBe("skip");
  });

  it("watchlists middling setups instead of copying", () => {
    const r = scoreTrade(
      { ...GOOD_INPUT, walletGlobalScore: 58, walletCategoryWinRate: 0.45, currentPrice: 0.55, liquidity: 9000 },
      DEFAULT_RULES
    );
    expect(["watchlist", "skip"]).toContain(r.decision);
    expect(r.simulatedPositionSize).toBeNull();
  });

  it("provides a full score breakdown", () => {
    const r = scoreTrade(GOOD_INPUT, DEFAULT_RULES);
    for (const key of ["walletQualityScore", "categoryFitScore", "entryTimingScore", "spreadScore", "liquidityScore", "thesisScore"] as const) {
      expect(r.breakdown[key]).toBeGreaterThanOrEqual(0);
      expect(r.breakdown[key]).toBeLessThanOrEqual(100);
    }
  });

  // --- Phase 8: Regulatory/Political Sentiment Agreement ---

  it("clamps a strongly-aligned regulatory boost into the sweet spot (v34)", () => {
    // walletGlobalScore 75 → base ~87 (conf 0.76, clears minConfidence); +25
    // would reach ~112 — the v34 clamp pins boosted scores at
    // regulatoryScoreCap (79) so an unvalidated signal can't manufacture a
    // copy in the ≥80 band. Clamped 79 → sweet-spot sizing → ×0.5 dead zone.
    const boosted = scoreTrade(
      { ...GOOD_INPUT, walletGlobalScore: 75, walletCategoryWinRate: 0.7, regulatoryAgreement: 0.9, currentPrice: 0.502 },
      DEFAULT_RULES
    );
    expect(boosted.decision).toBe("paper_copy");
    expect(boosted.copyScore).toBe(DEFAULT_RULES.regulatoryScoreCap); // 79 — clamped
    expect(boosted.reasons.join(" ")).toContain("Regulatory sentiment aligns strongly");
    expect(boosted.simulatedPositionSize).toBe(DEFAULT_RULES.sweetSpotSizeUsd); // 18 (factor neutralized, v41)
  });

  it("rejects a boosted late entry BEFORE the clamp (pre-clamp drift filter)", () => {
    // Pre-clamp score ~110 (conf ≥ 0.70 clears the v37 gate); drift 0.01 >
    // highScoreMaxDrift 0.004 and not lane-eligible → the v29 late-entry
    // filter fires on the unclamped score.
    const r = scoreTrade(
      { ...GOOD_INPUT, walletGlobalScore: 75, walletCategoryWinRate: 0.7, regulatoryAgreement: 0.9, currentPrice: 0.51 },
      DEFAULT_RULES
    );
    expect(r.decision).toBe("skip");
    expect(r.risks.join(" ")).toContain("late entry");
  });

  it("does NOT clamp unboosted high scores (v34)", () => {
    const r = scoreTrade(
      { ...GOOD_INPUT, walletGlobalScore: 95, walletCategoryWinRate: 0.9, currentPrice: 0.502 },
      DEFAULT_RULES
    );
    expect(r.decision).toBe("paper_copy");
    expect(r.copyScore).toBeGreaterThan(DEFAULT_RULES.regulatoryScoreCap); // ~93 stays ≥80
    expect(r.simulatedPositionSize).toBe(DEFAULT_RULES.highScoreCapUsd); // 18 (factor neutralized, v41)
  });

  it("penalizes copyScore when regulatory sentiment opposes direction", () => {
    const base = scoreTrade(GOOD_INPUT, DEFAULT_RULES);
    const opposed = scoreTrade({ ...GOOD_INPUT, regulatoryAgreement: -0.8 }, DEFAULT_RULES);
    expect(opposed.copyScore).toBeLessThan(base.copyScore);
    expect(opposed.risks.join(" ")).toContain("Regulatory sentiment opposes");
  });

  it("leaves score unchanged when no regulatory signal applies", () => {
    const a = scoreTrade(GOOD_INPUT, DEFAULT_RULES);
    const b = scoreTrade({ ...GOOD_INPUT, regulatoryAgreement: undefined }, DEFAULT_RULES);
    expect(b.copyScore).toBe(a.copyScore);
  });

  it("keeps size within clamps even with max regulatory boost", () => {
    const r = scoreTrade({ ...GOOD_INPUT, regulatoryAgreement: 1.0, currentPrice: 0.502 }, DEFAULT_RULES);
    expect(r.decision).toBe("paper_copy");
    expect(r.simulatedPositionSize!).toBeGreaterThanOrEqual(PAPER_MIN_SIZE_USD);
    expect(r.simulatedPositionSize!).toBeLessThanOrEqual(PAPER_MAX_SIZE_USD);
  });

  describe("researchCategoryFor", () => {
    it("classifies political markets", () => {
      expect(researchCategoryFor("Will Mary Peltola win the Alaska Senate race in 2026?", "alaska")).toBe("Macro/Politics");
      expect(researchCategoryFor("Which party will control the House in 2026?", "which")).toBe("Macro/Politics");
    });

    it("classifies finance and crypto markets", () => {
      expect(researchCategoryFor("Will the Fed cut rates in 2026?", "")).toBe("Finance");
      expect(researchCategoryFor("Will Bitcoin hit $100,000 in 2026?", "crypto")).toBe("Crypto");
    });

    it("returns undefined for sports/esports markets", () => {
      expect(researchCategoryFor("Will Team A win the CS2 major?", "cs2")).toBeUndefined();
      expect(researchCategoryFor("Will the Lakers win the NBA finals?", "nba")).toBeUndefined();
    });
  });
});
