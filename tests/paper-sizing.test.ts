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

  it("caps 0.20–0.40 (v57 change B) and passes ≥0.60 through unchanged", () => {
    // v57 (2026-09-18 daily report change B, user-approved) EXTENDED this rail:
    // 0.20–0.40 used to pass through, and Kelly could ride it to the $100 ceiling;
    // the band's clip-size split (≤$15 +$149 / $15-30 −$116 / ≥$30 −$331) is why
    // it is now capped at the legacy-equivalent like the dead zone.
    expect(applyKellyBandRails(25, 999, 0.3)).toBe(25); // cap above Kelly → untouched
    expect(applyKellyBandRails(25, 0.01, 0.3)).toBe(0.01); // cap below Kelly → clipped
    expect(applyKellyBandRails(25, 0.01, 0.7)).toBe(25); // ≥0.60 still passes through
    expect(applyKellyBandRails(25, 999, 0.6)).toBe(25); // favorite band: no rail
    expect(applyKellyBandRails(25, 0.01, 0.8)).toBe(25);
    // 0.20 is now the cap band's LOWER boundary (v57) — it used to be "not long-shot,
    // pass through"; the long-shot floor still starts strictly below 0.20.
    expect(applyKellyBandRails(25, 0.01, 0.2)).toBe(0.01);
    expect(applyKellyBandRails(25, 999, 0.1999)).toBe(999); // <0.20 → floor, not cap
  });
});

describe("v54 C-200 band factors (2026-09-15 Rec 1: reallocate size to the long-shot band)", () => {
  const V54 = { longshot: 2.5, deadZone: 0.125 };

  it("defaults stay byte-identical to the shipped constants when omitted", () => {
    for (const [size, price] of [[8, 0.15], [8, 0.5], [8, 0.3], [8, 0.7]] as const) {
      expect(mapBankroll200Size(size, price, {})).toBeCloseTo(mapBankroll200Size(size, price), 10);
    }
  });

  it("+25% on the long-shot band, −50% in the dead zone", () => {
    const base = mapBankroll200Size(8, 0.15); // ×2.0
    expect(mapBankroll200Size(8, 0.15, V54)).toBeCloseTo(base * 1.25, 5);
    const dz = mapBankroll200Size(8, 0.5); // ×0.25
    expect(mapBankroll200Size(8, 0.5, V54)).toBeCloseTo(dz * 0.5, 5);
  });

  it("leaves the untouched bands alone (0.20–0.40 and ≥0.60)", () => {
    for (const price of [0.2, 0.3, 0.399, 0.6, 0.75, 0.9]) {
      expect(mapBankroll200Size(8, price, V54)).toBeCloseTo(mapBankroll200Size(8, price), 10);
    }
  });

  it("moves both Kelly-rail comparisons together (same factors feed legacyEquiv)", () => {
    // long-shot floor: a bigger legacy-equivalent raises the Kelly floor.
    const legacyV53 = mapBankroll200Size(8, 0.15);
    const legacyV54 = mapBankroll200Size(8, 0.15, V54);
    expect(applyKellyBandRails(10, legacyV53, 0.15)).toBeCloseTo(legacyV53, 10);
    expect(applyKellyBandRails(10, legacyV54, 0.15)).toBeCloseTo(legacyV54, 10);
    // dead-zone cap: a smaller legacy-equivalent binds harder.
    expect(applyKellyBandRails(10, mapBankroll200Size(8, 0.5, V54), 0.5)).toBeLessThan(
      applyKellyBandRails(10, mapBankroll200Size(8, 0.5), 0.5)
    );
  });
});

describe("v57 change B: Kelly rail extended to [0.20, 0.40)", () => {
  it("caps the 0.20-0.40 band at the legacy-equivalent size", () => {
    // The band's map is x1.0, so a Kelly admit used to ride to the $100 ceiling.
    const legacyEquiv = mapBankroll200Size(8, 0.3); // ~$7.97
    expect(applyKellyBandRails(100, legacyEquiv, 0.3)).toBeCloseTo(legacyEquiv, 10);
    expect(applyKellyBandRails(5, legacyEquiv, 0.3)).toBeCloseTo(5, 10); // smaller Kelly untouched
  });

  it("keeps the dead-zone cap and the long-shot floor unchanged", () => {
    const dz = mapBankroll200Size(8, 0.5);
    expect(applyKellyBandRails(100, dz, 0.5)).toBeCloseTo(dz, 10); // [0.40,0.60)
    const ls = mapBankroll200Size(8, 0.15);
    expect(applyKellyBandRails(1, ls, 0.15)).toBeCloseTo(ls, 10); // <0.20 floors
  });

  it("leaves >=0.60 alone", () => {
    expect(applyKellyBandRails(100, 3.98, 0.7)).toBe(100);
    expect(applyKellyBandRails(100, 3.98, 0.2)).toBeLessThan(100); // boundary belongs to the cap
  });
});
