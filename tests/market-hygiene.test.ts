import { describe, it, expect } from "vitest";
import {
  RISK_WEIGHTS,
  WASH_THRESHOLDS,
  holderConcentration,
  hygieneRow,
  marketRiskGrade,
  scoreToGrade,
  washTradeProfile,
  type HygieneMarketInput,
} from "../src/lib/market-hygiene";

/**
 * Market-hygiene shadow scores (audit §P3/§P5). Ported tier tables are pinned at
 * their BOUNDARIES, not just in the middle: an off-by-one at `> 3.0` vs `>= 3.0`
 * silently changes which markets look suspicious, and the whole point of porting
 * rather than inventing is that the numbers stay comparable to the source.
 *
 * These scores are advisory-only; no assertion here implies a gate input.
 */

const base: HygieneMarketInput = { slug: "test-market" };

describe("wash-trade indicators (ported tiers)", () => {
  it("pins the volume/liquidity boundaries from the source", () => {
    // >10 -> 90, >5 -> 75, >threshold(3.0) -> 55, >1 -> 30, else no indicator
    expect(washTradeProfile({ ...base, volume24hr: 1100, liquidity: 100 }).indicators[0].score).toBe(90);
    expect(washTradeProfile({ ...base, volume24hr: 600, liquidity: 100 }).indicators[0].score).toBe(75);
    expect(washTradeProfile({ ...base, volume24hr: 310, liquidity: 100 }).indicators[0].score).toBe(55);
    expect(washTradeProfile({ ...base, volume24hr: 110, liquidity: 100 }).indicators[0].score).toBe(30);
    // exactly at the threshold is NOT above it
    const atThreshold = washTradeProfile({ ...base, volume24hr: 300, liquidity: 100 });
    expect(atThreshold.indicators[0].type).toBe("volume_liquidity");
    expect(atThreshold.indicators[0].score).toBe(30);
    // below 1x -> no indicator at all
    expect(washTradeProfile({ ...base, volume24hr: 90, liquidity: 100 }).indicators).toHaveLength(0);
  });

  it("flags missing liquidity as unassessable rather than clean", () => {
    const p = washTradeProfile({ ...base, volume24hr: 500, liquidity: 0 });
    expect(p.indicators[0].score).toBe(50);
    expect(p.indicators[0].detail).toMatch(/no liquidity data/);
  });

  it("pins trades-per-wallet tiers (>20 -> 85, >10 -> 65, >5 -> 40)", () => {
    const score = (tradeCount: number, uniqueTraders: number) =>
      washTradeProfile({ ...base, tradeCount, uniqueTraders }).indicators.find((i) => i.type === "trader_concentration")?.score;
    expect(score(210, 10)).toBe(85);
    expect(score(110, 10)).toBe(65);
    expect(score(60, 10)).toBe(40);
    expect(score(50, 10)).toBeUndefined(); // exactly 5/wallet is not > 5
  });

  it("pins size uniformity (>0.9 -> 75, >0.8 -> 50) and side balance (>0.95 -> 70, >0.85 -> 45)", () => {
    const size = (avg: number, median: number) =>
      washTradeProfile({ ...base, avgTradeSize: avg, medianTradeSize: median }).indicators[0]?.score;
    expect(size(100, 95)).toBe(75);
    expect(size(100, 85)).toBe(50);
    expect(size(100, 79)).toBeUndefined();

    const bal = (yes: number, no: number) =>
      washTradeProfile({ ...base, yesVolume: yes, noVolume: no }).indicators[0]?.score;
    expect(bal(100, 96)).toBe(70);
    expect(bal(100, 90)).toBe(45);
    expect(bal(100, 80)).toBeUndefined();
  });

  it("marks an unassessable market as not-assessed, never as clean", () => {
    const p = washTradeProfile(base);
    expect(p.assessed).toBe(false);
    expect(p.score).toBe(0);
    // The band is a numeric statement about FIRED indicators; `assessed` is what
    // separates "nothing suspicious" from "nothing measured".
    expect(p.band).toBe("clean");
  });

  it("weights fired indicators by 1 + score/100 and bands them at 25/45/65", () => {
    // single 90 indicator -> weight 1.9 -> weighted mean = 90 -> band high
    expect(washTradeProfile({ ...base, volume24hr: 2000, liquidity: 100 }).band).toBe("high");
    // single 30 indicator -> weighted mean 30 -> band low
    expect(washTradeProfile({ ...base, volume24hr: 150, liquidity: 100 }).band).toBe("low");
    expect(WASH_THRESHOLDS.volumeLiquidity).toBe(3.0);
    expect(WASH_THRESHOLDS.tradeSizeUniformity).toBe(0.8);
  });
});

describe("market risk grade (ported weights + tiers)", () => {
  it("keeps the source weights summing to 1", () => {
    const sum = Object.values(RISK_WEIGHTS).reduce((a, b) => a + b, 0);
    expect(sum).toBeCloseTo(1.0, 10);
    expect(RISK_WEIGHTS.resolutionClarity).toBe(0.25);
  });

  it("pins the grade bands", () => {
    expect(scoreToGrade(0)).toBe("A");
    expect(scoreToGrade(20)).toBe("A");
    expect(scoreToGrade(21)).toBe("B");
    expect(scoreToGrade(35)).toBe("B");
    expect(scoreToGrade(36)).toBe("C");
    expect(scoreToGrade(50)).toBe("C");
    expect(scoreToGrade(51)).toBe("D");
    expect(scoreToGrade(70)).toBe("D");
    expect(scoreToGrade(71)).toBe("F");
  });

  it("pins liquidity and spread tiers", () => {
    const liq = (liquidity: number) => marketRiskGrade({ ...base, liquidity }).factors.find((f) => f.key === "liquidity")!.score;
    expect(liq(600000)).toBe(0);
    expect(liq(100000)).toBe(15);
    expect(liq(50000)).toBe(30);
    expect(liq(10000)).toBe(50);
    expect(liq(1000)).toBe(70);
    expect(liq(999)).toBe(90);
    expect(liq(0)).toBe(80);

    const spr = (spread: number) => marketRiskGrade({ ...base, spread }).factors.find((f) => f.key === "spread")!.score;
    expect(spr(0.005)).toBe(0);
    expect(spr(0.02)).toBe(15);
    expect(spr(0.05)).toBe(35);
    expect(spr(0.1)).toBe(55);
    expect(spr(0.2)).toBe(80);
    expect(spr(0)).toBe(50);
  });

  it("raises resolution-clarity risk on subjective language and lowers it on specific criteria", () => {
    const clarity = (question: string) => marketRiskGrade({ ...base, question }).factors.find((f) => f.key === "resolution_clarity")!;
    const vague = clarity("Will there be a significant and substantial shift, effectively mainstream?");
    expect(vague.score).toBeGreaterThanOrEqual(40);
    const specific = clarity("Will CPI exceed 4% in 2027 per official data?");
    expect(specific.score).toBeLessThan(vague.score);
  });

  it("uses the dispute-rate keyword proxy for category risk", () => {
    const cat = (categoryForRisk: string) => marketRiskGrade({ ...base, categoryForRisk }).factors.find((f) => f.key === "category_risk")!;
    expect(cat("politics").score).toBe(60);
    expect(cat("sports").score).toBe(15);
    expect(cat("other").score).toBe(35);
  });

  it("carries warnings when the sub-scores cross the source thresholds", () => {
    const g = marketRiskGrade(
      { ...base, question: "Will something vague happen?", liquidity: 500, volume24hr: 100000, spread: 0.3 },
      new Date("2026-09-28T00:00:00Z")
    );
    expect(g.warnings.join(" | ")).toMatch(/low liquidity/);
    expect(g.grade).toMatch(/^[ABCDF]$/);
  });
});

describe("holder concentration (statistic is ours; the source never called /holders)", () => {
  it("computes top-N shares, HHI and effective holders", () => {
    const c = holderConcentration([{ amount: 50 }, { amount: 25 }, { amount: 25 }]);
    expect(c.holderCount).toBe(3);
    expect(c.top1Share).toBeCloseTo(0.5, 10);
    expect(c.top5Share).toBeCloseTo(1.0, 10);
    expect(c.hhi).toBeCloseTo(0.375, 10);
    expect(c.effectiveHolders).toBeCloseTo(1 / 0.375, 10);
    expect(c.assessed).toBe(true);
  });

  it("ignores non-positive and non-numeric amounts and reports unassessed when nothing remains", () => {
    expect(holderConcentration([]).assessed).toBe(false);
    expect(holderConcentration([{ amount: 0 }]).assessed).toBe(false);
    expect(holderConcentration([{ amount: Number.NaN }]).assessed).toBe(false);
    expect(holderConcentration([{ amount: 0 }, { amount: 10 }]).top1Share).toBe(1);
  });
});

describe("advisory row", () => {
  it("always declares itself advisory so it can never be read as a gate input", () => {
    const row = hygieneRow({ ...base, volume24hr: 150, liquidity: 100 });
    expect(row.qualityFlags).toContain("advisory_only");
    expect(row.qualityFlags).toContain("not_a_gate_input");
    expect(row.qualityFlags).toContain("heuristic_market_hygiene");
    expect(row.slug).toBe("test-market");
  });
});
