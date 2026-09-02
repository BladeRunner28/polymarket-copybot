import { describe, it, expect } from "vitest";
import {
  getBandLambda,
  computePremiumFactor,
  premiumRiskTag,
  loadPremiumCalibration,
  type PremiumCalibration,
} from "../src/lib/premium";

// Calibration as of 2026-08-31 (WangMLE on C-200 paper data).
const CAL: PremiumCalibration = {
  calibratedAt: "2026-08-31T00:00:00.000Z",
  source: "wang-mle",
  venueOffsetKalshi: 0.36,
  bands: [
    { lo: 0.0, hi: 0.2, lambda: -1.2036, n: 43 },
    { lo: 0.2, hi: 0.4, lambda: -0.2411, n: 193 },
    { lo: 0.4, hi: 0.6, lambda: -0.0183, n: 441 },
    { lo: 0.6, hi: 0.8, lambda: 0.2479, n: 152 },
    { lo: 0.8, hi: 1.01, lambda: 0.3545, n: 94 },
  ],
};

describe("getBandLambda", () => {
  it("returns the band containing the entry price", () => {
    expect(getBandLambda(0.1, CAL.bands)).toBeCloseTo(-1.2036);
    expect(getBandLambda(0.5, CAL.bands)).toBeCloseTo(-0.0183);
    expect(getBandLambda(0.95, CAL.bands)).toBeCloseTo(0.3545);
  });
  it("treats the low edge as inclusive and the high edge as exclusive", () => {
    expect(getBandLambda(0.2, CAL.bands)).toBeCloseTo(-0.2411); // 0.2 belongs to 0.2–0.4
    expect(getBandLambda(0.6, CAL.bands)).toBeCloseTo(0.2479); // 0.6 belongs to 0.6–0.8
  });
  it("falls back to the top band above the last boundary", () => {
    expect(getBandLambda(1.0, CAL.bands)).toBeCloseTo(0.3545);
  });
});

describe("computePremiumFactor", () => {
  const k = 0.5;
  it("boosts negative λ̂ (info edge) and shrinks positive λ̂ (premium drag)", () => {
    expect(computePremiumFactor(-1.2036, k, 0.5, 2.0)).toBeCloseTo(1.6018); // long-shot edge
    expect(computePremiumFactor(0.3545, k, 0.5, 2.0)).toBeCloseTo(0.82275); // overpriced
    expect(computePremiumFactor(0.0, k, 0.5, 2.0)).toBe(1.0); // dead zone unchanged
  });
  it("clamps to [minFactor, maxFactor]", () => {
    expect(computePremiumFactor(-3.0, k, 0.5, 2.0)).toBe(2.0);
    expect(computePremiumFactor(3.0, k, 0.5, 2.0)).toBe(0.5);
  });
  it("adds the venue offset before computing (Kalshi entries are premium-laden)", () => {
    // Polymarket λ̂ at 0.5 is −0.0183; Kalshi adds +0.36 → +0.34 → shrink.
    const poly = computePremiumFactor(getBandLambda(0.5, CAL.bands), k, 0.5, 2.0);
    const kalshi = computePremiumFactor(getBandLambda(0.5, CAL.bands) + CAL.venueOffsetKalshi, k, 0.5, 2.0);
    expect(poly).toBeGreaterThan(kalshi);
    expect(kalshi).toBeLessThan(1.0);
  });
});

describe("premiumRiskTag", () => {
  it("labels edge, fair, and drag regimes", () => {
    expect(premiumRiskTag(-0.5, "Polymarket")).toContain("info edge");
    expect(premiumRiskTag(0.0, "Polymarket")).toContain("fair");
    expect(premiumRiskTag(0.31, "Kalshi")).toContain("overpriced entry");
  });
});

describe("loadPremiumCalibration", () => {
  it("returns null for a missing file (overlay safely off)", () => {
    expect(loadPremiumCalibration("/nonexistent/premium-calibration.json")).toBeNull();
  });
});
