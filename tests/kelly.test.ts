import { describe, it, expect } from "vitest";
import {
  normCdf,
  normInv,
  fairProbability,
  kellyFraction,
  kellySizeForCopy,
  type KellySizeParams,
} from "../src/lib/kelly";

// Sep 1 2026 Wang calibration (data/premium-calibration.json) band λ̂ values.
const LAMBDA = {
  longshot: -0.9099, // <0.20
  midlow: -0.2136, // 0.20–0.40
  mid: 0.0299, // 0.40–0.60
  midhigh: 0.2078, // 0.60–0.80
  favorite: 0.3655, // ≥0.80
};

const BASE: KellySizeParams = {
  price: 0.12,
  outcome: "YES",
  lambda: LAMBDA.longshot,
  side: "BUY",
  availableBankroll: 1146,
  fraction: 0.5,
  maxBankrollPct: 0.1,
  maxSizeUsd: 60,
  minBetUsd: 2,
  minEdgePct: 0.02,
};

describe("normCdf / normInv", () => {
  it("hits known quantiles", () => {
    expect(normCdf(0)).toBeCloseTo(0.5, 6);
    expect(normCdf(1.96)).toBeCloseTo(0.975, 4);
    expect(normInv(0.5)).toBeCloseTo(0, 6);
    expect(normInv(0.975)).toBeCloseTo(1.96, 3);
  });
  it("round-trips Φ⁻¹(Φ(z)) ≈ z", () => {
    for (const z of [-2.2, -1.5, -0.4, 0.4, 1.2, 2.0]) {
      expect(normInv(normCdf(z))).toBeCloseTo(z, 4);
    }
  });
});

describe("fairProbability", () => {
  it("long-shot band: λ̂=−0.91 lifts fair prob far above price", () => {
    // q = Φ(Φ⁻¹(0.12) + 0.9099) ≈ 0.395
    expect(fairProbability(0.12, LAMBDA.longshot)).toBeCloseTo(0.3955, 3);
  });
  it("mid band: λ̂≈+0.03 ⇒ fair ≈ price (no edge)", () => {
    expect(fairProbability(0.5, LAMBDA.mid)).toBeCloseTo(0.4881, 3);
  });
  it("favorite band: λ̂=+0.37 ⇒ fair well below price", () => {
    // q = Φ(Φ⁻¹(0.88) − 0.3655) ≈ 0.79
    expect(fairProbability(0.88, LAMBDA.favorite)).toBeCloseTo(0.7909, 3);
  });
  it("rejects out-of-range prices", () => {
    expect(() => fairProbability(0, LAMBDA.mid)).toThrow();
    expect(() => fairProbability(1, LAMBDA.mid)).toThrow();
  });
});

describe("kellyFraction", () => {
  it("long-shot: f* ≈ 0.313", () => {
    const q = fairProbability(0.12, LAMBDA.longshot);
    expect(kellyFraction(0.12, q)).toBeCloseTo(0.3131, 3);
  });
  it("NO-side buy mirrors YES-side math on the bought token", () => {
    // Buy NO@0.70 when fair NO = 0.75 ⇒ f* = (0.05)/0.30 ≈ 0.1667
    expect(kellyFraction(0.7, 0.75)).toBeCloseTo(0.1667, 3);
    // Buy NO@0.70 when fair NO = 0.65 ⇒ negative (overpriced NO)
    expect(kellyFraction(0.7, 0.65)).toBeLessThan(0);
  });
});

describe("kellySizeForCopy", () => {
  it("long-shot copy sizes to the USD cap (60) at current bankroll", () => {
    const r = kellySizeForCopy(BASE);
    expect(r.skip).toBe(false);
    expect(r.sizeUsd).toBe(60);
    expect(r.fStarFull).toBeCloseTo(0.3131, 3);
    expect(r.fStarApplied).toBeCloseTo(0.1566, 3);
  });
  it("0.20–0.40 band (λ̂=−0.21) also caps at 60 on a $1,146 book", () => {
    const r = kellySizeForCopy({ ...BASE, price: 0.3, lambda: LAMBDA.midlow });
    expect(r.skip).toBe(false);
    expect(r.sizeUsd).toBe(60);
  });
  it("fraction scales on a smaller book (no cap binding)", () => {
    const r = kellySizeForCopy({ ...BASE, price: 0.3, lambda: LAMBDA.midlow, availableBankroll: 500 });
    // fApplied ≈ 0.0557 → 500 × 0.0557 ≈ 27.8 (pct cap 50, usd cap 60 don't bind)
    expect(r.skip).toBe(false);
    expect(r.sizeUsd).toBeCloseTo(27.85, 1);
  });
  it("mid band (λ̂≈+0.03) is skipped — no edge", () => {
    const r = kellySizeForCopy({ ...BASE, price: 0.5, lambda: LAMBDA.mid });
    expect(r.skip).toBe(true);
    expect(r.reason).toContain("no edge");
  });
  it("favorite band (λ̂=+0.37) is skipped — overpriced", () => {
    const r = kellySizeForCopy({ ...BASE, price: 0.88, lambda: LAMBDA.favorite });
    expect(r.skip).toBe(true);
    expect(r.reason).toContain("no edge");
  });
  it("0.60–0.80 band is skipped", () => {
    const r = kellySizeForCopy({ ...BASE, price: 0.7, lambda: LAMBDA.midhigh });
    expect(r.skip).toBe(true);
  });
  it("skips when the edge is below minEdgePct", () => {
    const r = kellySizeForCopy({ ...BASE, price: 0.3, lambda: -0.005 });
    expect(r.skip).toBe(true);
    expect(r.reason).toContain("minEdgePct");
  });
  it("skips dust below minBetUsd", () => {
    // bankroll 10 → fraction path $1.57, pct-cap $1.00 → min $1.00 < $2.00
    const r = kellySizeForCopy({ ...BASE, availableBankroll: 10, maxSizeUsd: 5 });
    expect(r.skip).toBe(true);
    expect(r.reason).toContain("minBetUsd");
  });
  it("skips SELL side explicitly", () => {
    const r = kellySizeForCopy({ ...BASE, side: "SELL" });
    expect(r.skip).toBe(true);
  });
  it("skips non-positive bankroll", () => {
    const r = kellySizeForCopy({ ...BASE, availableBankroll: 0 });
    expect(r.skip).toBe(true);
  });
});
