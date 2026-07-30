import { describe, it, expect } from "vitest";
import { scoreTrade } from "../src/lib/scoring/trade";
import { DEFAULT_RULES } from "../src/lib/rules";
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
    const r = scoreTrade(GOOD_INPUT, DEFAULT_RULES);
    expect(r.decision).toBe("paper_copy");
    expect(r.simulatedPositionSize).not.toBeNull();
    expect(r.reasons.length).toBeGreaterThan(0);
  });

  it("keeps simulated size within $.25-$20 even at extreme confidence", () => {
    const r = scoreTrade({ ...GOOD_INPUT, walletGlobalScore: 100, walletCategoryWinRate: 1 }, DEFAULT_RULES);
    expect(r.simulatedPositionSize!).toBeGreaterThanOrEqual(PAPER_MIN_SIZE_USD);
    expect(r.simulatedPositionSize!).toBeLessThanOrEqual(PAPER_MAX_SIZE_USD);
  });

  it("sizes up with higher confidence", () => {
    const low = scoreTrade({ ...GOOD_INPUT, walletGlobalScore: 62, walletCategoryWinRate: 0.5 }, DEFAULT_RULES);
    const high = scoreTrade({ ...GOOD_INPUT, walletGlobalScore: 95, walletCategoryWinRate: 0.9 }, DEFAULT_RULES);
    if (low.decision === "paper_copy" && high.decision === "paper_copy") {
      expect(high.simulatedPositionSize!).toBeGreaterThanOrEqual(low.simulatedPositionSize!);
    }
    expect(high.decision).toBe("paper_copy");
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
});
