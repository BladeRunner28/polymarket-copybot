/**
 * v41 C-200 calibration-band size mapping tests (2026-08-31 report, approved).
 */

import { describe, it, expect } from "vitest";
import { mapBankroll200Size } from "../src/lib/paper";

describe("mapBankroll200Size (v41 calibration-band sizing)", () => {
  it("maps the STANDARD-scale range into the $0.20–$20 band (multiplier applies at the floor too)", () => {
    // parent 0.25 → mapped 0.2, then ×0.5 at a 0.5 entry = $0.10 (v42)
    expect(mapBankroll200Size(0.25, 0.5)).toBeCloseTo(0.1, 5);
    expect(mapBankroll200Size(20, 0.5)).toBeCloseTo(10, 5);
  });

  it("applies ×1.5 to long-shot entries (< $0.20)", () => {
    // parent 8 → mapped ≈ 7.97 × 1.5 = 11.95
    expect(mapBankroll200Size(8, 0.15)).toBeCloseTo(11.95, 2);
  });

  it("applies ×1.0 to the 0.20–0.40 band (watch, don't chase)", () => {
    expect(mapBankroll200Size(8, 0.3)).toBeCloseTo(7.97, 2);
    expect(mapBankroll200Size(8, 0.2)).toBeCloseTo(7.97, 2); // boundary stays ×1.0
  });

  it("applies ×0.5 to the 0.40–0.60 dead zone (v42: deepened from ×0.75)", () => {
    expect(mapBankroll200Size(8, 0.5)).toBeCloseTo(3.98, 2);
    expect(mapBankroll200Size(8, 0.4)).toBeCloseTo(3.98, 2); // boundary ×0.5
  });

  it("applies ×0.5 to favorites (≥ $0.60)", () => {
    expect(mapBankroll200Size(8, 0.7)).toBeCloseTo(3.98, 2);
    expect(mapBankroll200Size(20, 0.9)).toBeCloseTo(10, 2);
    expect(mapBankroll200Size(8, 0.6)).toBeCloseTo(3.98, 2); // boundary ×0.5
  });

  it("can exceed the $20 cap before the caller clamps (long-shot top allocation)", () => {
    // parent 20 @ 0.15 → mapped 20 × 1.5 = 30; openPaperTrade clamps to $20.
    expect(mapBankroll200Size(20, 0.15)).toBeCloseTo(30, 5);
  });

  it("is safe for non-finite entry prices (falls through to ×1.0)", () => {
    expect(mapBankroll200Size(8, NaN)).toBeCloseTo(7.97, 2);
    expect(mapBankroll200Size(8, -1)).toBeCloseTo(7.97, 2);
  });
});
