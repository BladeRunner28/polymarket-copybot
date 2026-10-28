/**
 * v68 — STANDARD maturity size factor (0.5 / 1.0 / 1.5 on time-to-resolution at entry).
 *
 * Approved 2026-10-27 ("approve standard-maturity-size-factor"). Lane A: it changes how much the bot
 * risks, so it ships as a RULESET VALUE with the code default left at 1.0/1.0/1.0 (disabled).
 *
 * These tests exist to pin the three things that would silently corrupt the measurement:
 *   1. the bucket boundaries (24.000 is MEDIUM and 72.000 is LONG — an off-by-one moves the whole
 *      >=72h cohort, the one that carries +21.4%, into a different multiplier),
 *   2. "unknown TTL" meaning UNCHANGED, never down-sized (the shadow drops TTL-less legs entirely
 *      rather than guessing; treating unknown as <24h would down-size a whole real population),
 *   3. the disable path being byte-identical, because the default ruleset has no schedule in it.
 */
import { describe, it, expect } from "vitest";
import { applyMaturitySizeFactor, maturityBucket, type MaturityFactors } from "../src/lib/maturity-size";

const LIVE: MaturityFactors = { short: 0.5, medium: 1.0, long: 1.5, shortHours: 24, longHours: 72 };
const OFF: MaturityFactors = { short: 1, medium: 1, long: 1, shortHours: 24, longHours: 72 };

describe("v68 maturity size factor", () => {
  it("is byte-identical when every factor is 1.0 — the shipped default", () => {
    for (const ttl of [0, 1, 23.9, 24, 71.9, 72, 500, 1e6]) {
      expect(applyMaturitySizeFactor(18, ttl, OFF)).toBe(18);
    }
    expect(applyMaturitySizeFactor(18, null, OFF)).toBe(18);
  });

  it("applies 0.5 / 1.0 / 1.5 by cohort", () => {
    expect(applyMaturitySizeFactor(18, 5, LIVE)).toBeCloseTo(9, 10); // <24h
    expect(applyMaturitySizeFactor(18, 48, LIVE)).toBeCloseTo(18, 10); // 24-72h
    expect(applyMaturitySizeFactor(18, 200, LIVE)).toBeCloseTo(27, 10); // >=72h
  });

  it("pins the boundaries: 24.000 is MEDIUM, 72.000 is LONG", () => {
    expect(applyMaturitySizeFactor(18, 23.999, LIVE)).toBeCloseTo(9, 10);
    expect(applyMaturitySizeFactor(18, 24, LIVE)).toBeCloseTo(18, 10);
    expect(applyMaturitySizeFactor(18, 71.999, LIVE)).toBeCloseTo(18, 10);
    expect(applyMaturitySizeFactor(18, 72, LIVE)).toBeCloseTo(27, 10);
    expect(maturityBucket(23.999, LIVE)).toBe("short");
    expect(maturityBucket(24, LIVE)).toBe("medium");
    expect(maturityBucket(71.999, LIVE)).toBe("medium");
    expect(maturityBucket(72, LIVE)).toBe("long");
  });

  it("leaves an unknown or nonsense TTL UNCHANGED — never down-sized", () => {
    for (const ttl of [null, undefined, Number.NaN, -1, -0.5]) {
      expect(applyMaturitySizeFactor(18, ttl as number | null | undefined, LIVE)).toBe(18);
    }
    expect(maturityBucket(null, LIVE)).toBe("unknown");
  });

  it("honours custom hour boundaries rather than assuming 24/72", () => {
    const f: MaturityFactors = { short: 0.5, medium: 1.0, long: 1.5, shortHours: 6, longHours: 12 };
    expect(applyMaturitySizeFactor(10, 5, f)).toBeCloseTo(5, 10);
    expect(applyMaturitySizeFactor(10, 6, f)).toBeCloseTo(10, 10);
    expect(applyMaturitySizeFactor(10, 12, f)).toBeCloseTo(15, 10);
  });

  it("refuses malformed schedules by doing nothing at all", () => {
    // inverted / non-positive hour bounds
    expect(applyMaturitySizeFactor(18, 5, { ...LIVE, shortHours: 72, longHours: 24 })).toBe(18);
    expect(applyMaturitySizeFactor(18, 5, { ...LIVE, shortHours: 0 })).toBe(18);
    // a zero or negative or NaN factor must not silently zero the clip
    expect(applyMaturitySizeFactor(18, 5, { ...LIVE, short: 0 })).toBe(18);
    expect(applyMaturitySizeFactor(18, 5, { ...LIVE, short: -1 })).toBe(18);
    expect(applyMaturitySizeFactor(18, 5, { ...LIVE, long: Number.NaN })).toBe(18);
    expect(applyMaturitySizeFactor(18, 5, null)).toBe(18);
  });

  it("scales a sub-dollar clip without rounding it away", () => {
    // clampPaperSize floors at $0.25 and runs AFTER this factor; the factor itself must not floor.
    expect(applyMaturitySizeFactor(0.5, 5, LIVE)).toBeCloseTo(0.25, 10);
    expect(applyMaturitySizeFactor(0.4, 5, LIVE)).toBeCloseTo(0.2, 10); // below the floor, clamp handles it
    expect(applyMaturitySizeFactor(0, 5, LIVE)).toBe(0);
  });

  it("v69: the 4th bucket is INERT while hugeHours keeps its 1e9 default", () => {
    const live69: MaturityFactors = { ...LIVE, hugeHours: 1e9, huge: 1.0 };
    for (const ttl of [200, 5_000, 100_000]) {
      expect(applyMaturitySizeFactor(10, ttl, live69)).toBeCloseTo(applyMaturitySizeFactor(10, ttl, LIVE), 10);
    }
    expect(maturityBucket(5_000, live69)).toBe("long");
  });

  it("v69: splits >=168h off the long bucket once a real bound is set", () => {
    const split: MaturityFactors = { ...LIVE, hugeHours: 168, huge: 1.0 };
    expect(applyMaturitySizeFactor(10, 100, split)).toBeCloseTo(15, 10); // 72-168h keeps 1.5x
    expect(applyMaturitySizeFactor(10, 167.9, split)).toBeCloseTo(15, 10);
    expect(applyMaturitySizeFactor(10, 168, split)).toBeCloseTo(10, 10); // >=168h back to 1.0x
    expect(applyMaturitySizeFactor(10, 900, split)).toBeCloseTo(10, 10);
    expect(maturityBucket(167.9, split)).toBe("long");
    expect(maturityBucket(168, split)).toBe("huge");
  });

  it("v69: a nonsense huge bound is ignored rather than silently zeroing the clip", () => {
    // hugeHours must be STRICTLY beyond longHours; otherwise it is not a distinct bucket.
    const bad: MaturityFactors = { ...LIVE, hugeHours: 72, huge: 0.1 };
    expect(applyMaturitySizeFactor(10, 200, bad)).toBeCloseTo(15, 10); // falls through to long
    const reversed: MaturityFactors = { ...LIVE, hugeHours: 24, huge: 0.1 };
    expect(applyMaturitySizeFactor(10, 200, reversed)).toBeCloseTo(15, 10);
    const zero: MaturityFactors = { ...LIVE, hugeHours: 168, huge: 0 };
    expect(applyMaturitySizeFactor(10, 200, zero)).toBeCloseTo(15, 10);
    expect(maturityBucket(200, bad)).toBe("long");
  });

  it("does not double-apply the $20 cap — that is clampPaperSize's job, one layer down", () => {
    // 18 x 1.5 = 27 here; the live path then clamps to 20. If this helper clamped too, the shadow
    // (which clamped once) and the code would disagree and the quoted effect would be overstated.
    expect(applyMaturitySizeFactor(18, 200, LIVE)).toBeCloseTo(27, 10);
  });
});
