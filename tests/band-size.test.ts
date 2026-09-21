/**
 * Band-scoped size factor (v60, 2026-09-20 daily report change 1, user-approved).
 *
 * Target: the 0.60–0.80 band — significant negative excess (−0.0995, z=−3.96, N=382)
 * and ~zero cash (+$2.66 over 30d on $1,015 of flow) while taking a third of the day's
 * new positions. The approved intent is to halve new size there. The rec named the
 * v38 premium-overlay flag, which cannot do it (it skips short-TTR lane copies, and
 * every 0.60–0.80 copy in the book is a lane copy at $4.99) — hence this factor.
 */

import { describe, it, expect } from "vitest";
import { applyBandSizeFactor, parseBandRange } from "../src/lib/band-size";

describe("parseBandRange", () => {
  it("parses the configured form", () => {
    expect(parseBandRange("0.6-0.8")).toEqual({ lo: 0.6, hi: 0.8 });
    expect(parseBandRange("0.20 - 0.40")).toEqual({ lo: 0.2, hi: 0.4 });
  });

  it("treats empty, malformed or inverted ranges as disabled", () => {
    expect(parseBandRange("")).toBeNull();
    expect(parseBandRange("0.8-0.6")).toBeNull();
    expect(parseBandRange("0.6..0.8")).toBeNull();
    expect(parseBandRange("all")).toBeNull();
  });
});

describe("applyBandSizeFactor", () => {
  const laneSize = 4.99; // the live 0.60–0.80 clip (fixed lane size × 0.5 band map)

  it("halves an entry inside the range (the approved change)", () => {
    expect(applyBandSizeFactor(laneSize, 0.7, 0.5, "0.6-0.8")).toBeCloseTo(2.495, 6);
  });

  it("leaves entries outside the range untouched", () => {
    expect(applyBandSizeFactor(laneSize, 0.59, 0.5, "0.6-0.8")).toBe(laneSize); // below lo
    expect(applyBandSizeFactor(laneSize, 0.8, 0.5, "0.6-0.8")).toBe(laneSize); // hi exclusive
    expect(applyBandSizeFactor(58.75, 0.15, 0.5, "0.6-0.8")).toBe(58.75); // long-shot band
  });

  it("is inert for factor 1 / 0 / disabled range (so a revert is one field)", () => {
    expect(applyBandSizeFactor(laneSize, 0.7, 1, "0.6-0.8")).toBe(laneSize);
    expect(applyBandSizeFactor(laneSize, 0.7, 0, "0.6-0.8")).toBe(laneSize);
    expect(applyBandSizeFactor(laneSize, 0.7, 0.5, "")).toBe(laneSize);
  });

  it("does not multiply twice — the caller passes the already-final size", () => {
    const once = applyBandSizeFactor(10, 0.7, 0.5, "0.6-0.8");
    const twice = applyBandSizeFactor(once, 0.7, 0.5, "0.6-0.8");
    expect(once).toBe(5);
    expect(twice).toBe(2.5); // documented behavior: it is a plain multiplier
  });
});
