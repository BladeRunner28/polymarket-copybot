/**
 * v57 change A (2026-09-18 daily report, user-approved): price-relative drift
 * tolerance for the <0.20 band.
 *
 * Why: 245 of 405 C-200 vetoes in 24h were "price drifted ... > 0.004". A flat
 * 0.4c is 0.7% of price at 0.60 but 2-8% at 0.05-0.20, so the band with the widest
 * measured edge was the most starved of flow.
 */

import { describe, it, expect } from "vitest";
import { effectiveDriftTolerance } from "../src/lib/rules";

const V57 = { maxPriceDrift: 0.004, longshotMaxPrice: 0.2, longshotDriftPct: 0.08, longshotDriftCap: 0.02 };
const LEGACY = { ...V57, longshotDriftPct: 0 };

describe("effectiveDriftTolerance", () => {
  it("legacy (pct 0) is flat for every band", () => {
    for (const p of [0.03, 0.1, 0.2, 0.5, 0.9]) expect(effectiveDriftTolerance(LEGACY, p)).toBe(0.004);
  });

  it("scales with price inside the long-shot band", () => {
    expect(effectiveDriftTolerance(V57, 0.05)).toBeCloseTo(0.004, 10); // 0.08*0.05 < base → base
    expect(effectiveDriftTolerance(V57, 0.10)).toBeCloseTo(0.008, 10);
    expect(effectiveDriftTolerance(V57, 0.15)).toBeCloseTo(0.012, 10);
    expect(effectiveDriftTolerance(V57, 0.19)).toBeCloseTo(0.0152, 10);
  });

  it("caps the band tolerance", () => {
    expect(effectiveDriftTolerance(V57, 0.199)).toBeCloseTo(0.01592, 10);
    const wide = { ...V57, longshotDriftPct: 0.5 };
    expect(effectiveDriftTolerance(wide, 0.19)).toBeCloseTo(0.02, 10); // capped, not 0.095
  });

  it("never loosens at or above longshotMaxPrice (boundary is exclusive)", () => {
    expect(effectiveDriftTolerance(V57, 0.2)).toBe(0.004);
    expect(effectiveDriftTolerance(V57, 0.4)).toBe(0.004);
    expect(effectiveDriftTolerance(V57, 0.9)).toBe(0.004);
  });

  it("a 0.02 cap with a 0 pct still falls back to the base", () => {
    expect(effectiveDriftTolerance({ ...V57, longshotDriftPct: 0 }, 0.1)).toBe(0.004);
  });
});
