/**
 * v41 C-200 calibration-band size mapping tests (2026-08-31 report, approved).
 * v51 (2026-09-07 report changes 1+2, user-approved): dead zone deepened
 * ×0.5 → ×0.25, long-shot reinforced ×1.5 → ×2.0, Kelly band rails added.
 */

import { describe, it, expect } from "vitest";
import { mapBankroll200Size, applyKellyBandRails } from "../src/lib/paper";

describe("mapBankroll200Size (v41 calibration-band sizing, v51 multipliers)", () => {
  it("maps the STANDARD-scale range into the $0.20–$20 band (multiplier applies at the floor too)", () => {
    // parent 0.25 → mapped 0.2, then ×0.25 at a 0.5 entry = $0.05 (v51)
    expect(mapBankroll200Size(0.25, 0.5)).toBeCloseTo(0.05, 5);
    expect(mapBankroll200Size(20, 0.5)).toBeCloseTo(5, 5);
  });

  it("applies ×2.0 to long-shot entries (< $0.20) — v51 reinforced from ×1.5", () => {
    // parent 8 → mapped ≈ 7.97 × 2.0 = 15.94
    expect(mapBankroll200Size(8, 0.15)).toBeCloseTo(15.94, 2);
  });

  it("applies ×1.0 to the 0.20–0.40 band (watch, don't chase)", () => {
    expect(mapBankroll200Size(8, 0.3)).toBeCloseTo(7.97, 2);
    expect(mapBankroll200Size(8, 0.2)).toBeCloseTo(7.97, 2); // boundary stays ×1.0
  });

  it("applies ×0.25 to the 0.40–0.60 dead zone (v51: deepened from ×0.5)", () => {
    expect(mapBankroll200Size(8, 0.5)).toBeCloseTo(1.99, 2);
    expect(mapBankroll200Size(8, 0.4)).toBeCloseTo(1.99, 2); // boundary ×0.25
  });

  it("applies ×0.5 to favorites (≥ $0.60) — unchanged (current-regime drag already fixed)", () => {
    expect(mapBankroll200Size(8, 0.7)).toBeCloseTo(3.98, 2);
    expect(mapBankroll200Size(20, 0.9)).toBeCloseTo(10, 2);
    expect(mapBankroll200Size(8, 0.6)).toBeCloseTo(3.98, 2); // boundary ×0.5
  });

  it("can exceed the $20 cap before the caller clamps (long-shot top allocation)", () => {
    // parent 20 @ 0.15 → mapped 20 × 2.0 = 40; openPaperTrade clamps to $20.
    expect(mapBankroll200Size(20, 0.15)).toBeCloseTo(40, 5);
  });

  it("is safe for non-finite entry prices (falls through to ×1.0)", () => {
    expect(mapBankroll200Size(8, NaN)).toBeCloseTo(7.97, 2);
    expect(mapBankroll200Size(8, -1)).toBeCloseTo(7.97, 2);
  });
});

describe("applyKellyBandRails (v51 — Kelly path can't contradict the band map)", () => {
  it("caps dead-zone [0.40, 0.60) Kelly admits at the legacy-equivalent size", () => {
    expect(applyKellyBandRails(80, 20, 0.5)).toBe(20); // cap binds
    expect(applyKellyBandRails(10, 20, 0.5)).toBe(10); // Kelly smaller → untouched
    expect(applyKellyBandRails(50, 12, 0.4)).toBe(12); // lower boundary
    expect(applyKellyBandRails(50, 12, 0.59)).toBe(12); // upper boundary (0.6 → favorite band)
  });

  it("floors long-shot (< 0.20) Kelly admits at the legacy-equivalent size", () => {
    expect(applyKellyBandRails(5, 20, 0.15)).toBe(20); // floor lifts
    expect(applyKellyBandRails(30, 20, 0.15)).toBe(30); // Kelly bigger → untouched
    expect(applyKellyBandRails(5, 16, 0.199)).toBe(16); // just under 0.20
  });

  it("passes other bands through unchanged (0.20–0.40 and ≥ 0.60)", () => {
    expect(applyKellyBandRails(25, 999, 0.3)).toBe(25);
    expect(applyKellyBandRails(25, 0.01, 0.3)).toBe(25);
    expect(applyKellyBandRails(25, 999, 0.6)).toBe(25); // favorite band: no rail
    expect(applyKellyBandRails(25, 0.01, 0.8)).toBe(25);
    expect(applyKellyBandRails(25, 0.01, 0.2)).toBe(25); // 0.20 boundary: not long-shot
  });
});
