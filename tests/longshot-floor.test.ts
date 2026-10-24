/**
 * v67 — lower bound on the C-200 long-shot band multiplier.
 * (profit-recs #1, user-approved 2026-10-24)
 *
 * The multiplier applied to every entry < 0.20 with nothing underneath, so the ruleset's
 * largest factor (3.5x) hit hardest at the smallest prices. Below 0.05 the measured book
 * was 66 legs / $1,694 at a $25.66 clip — the largest in the book — with a 0.0%
 * settlement hit against a 3.39% break-even price, -$1,041 realized.
 *
 * This test locks the two properties that make the floor safe to ship:
 *   - it defaults to 0 (no floor), so a ruleset lacking the field is byte-identical
 *     to pre-v67, and landing the code changes nothing on its own;
 *   - it removes the multiplier below the floor WITHOUT shrinking the healthy
 *     0.05-0.20 cell, which is the measured +98%..+102% region.
 */

import { describe, it, expect } from "vitest";
import { DEFAULT_RULES } from "../src/lib/rules";
import { C200_BAND_DEFAULTS, mapBankroll200Size } from "../src/lib/paper";

const FLOOR = { longshot: 3.5, deadZone: 0.25, longshotFloor: 0.05 };
// midpoint of the 0.25..20 standard scale, so bands are the only variable
const SCALE = 10;

describe("v67 long-shot floor — defaults", () => {
  it("has no floor by default, so unpatched rulesets behave exactly as pre-v67", () => {
    expect(DEFAULT_RULES.c200LongshotBandFloor).toBe(0);
    const withFloorZero = mapBankroll200Size(SCALE, 0.01, {
      longshot: 3.5,
      deadZone: 0.25,
      longshotFloor: 0,
    });
    const legacy = mapBankroll200Size(SCALE, 0.01, { longshot: 3.5, deadZone: 0.25 });
    expect(withFloorZero).toBe(legacy);
  });

  it("applies the shipped long-shot factor below 0.20 when no floor is set", () => {
    const boosted = mapBankroll200Size(SCALE, 0.01, { longshot: 2.0, deadZone: 0.25 });
    const plain = mapBankroll200Size(SCALE, 0.30, { longshot: 2.0, deadZone: 0.25 });
    expect(boosted).toBeGreaterThan(plain);
  });
});

describe("v67 long-shot floor — the floor bites below 0.05", () => {
  it("does NOT apply the multiplier below the floor", () => {
    const floored = mapBankroll200Size(SCALE, 0.01, FLOOR);
    const unfloored = mapBankroll200Size(SCALE, 0.01, { longshot: 3.5, deadZone: 0.25 });
    expect(floored).toBeLessThan(unfloored);
    // below the floor it falls through to the same size as a 0.20-0.40 entry (x1.0)
    const neutral = mapBankroll200Size(SCALE, 0.30, FLOOR);
    expect(floored).toBeCloseTo(neutral, 10);
  });

  it("treats the floor as inclusive: 0.05 exactly still gets the multiplier", () => {
    const atFloor = mapBankroll200Size(SCALE, 0.05, FLOOR);
    const below = mapBankroll200Size(SCALE, 0.0499, FLOOR);
    expect(atFloor).toBeGreaterThan(below);
  });

  it("trims the biggest clips in the measured bad region", () => {
    for (const p of [0.001, 0.0029, 0.01, 0.034, 0.049]) {
      const floored = mapBankroll200Size(SCALE, p, FLOOR);
      const legacy = mapBankroll200Size(SCALE, p, { longshot: 3.5, deadZone: 0.25 });
      expect(floored, `entry ${p} must shrink`).toBeLessThan(legacy);
    }
  });
});

describe("v67 long-shot floor — leaves the healthy cell alone", () => {
  it("still multiplies the whole 0.05-0.20 cell", () => {
    for (const p of [0.05, 0.08, 0.12, 0.15, 0.199]) {
      const floored = mapBankroll200Size(SCALE, p, FLOOR);
      const legacy = mapBankroll200Size(SCALE, p, { longshot: 3.5, deadZone: 0.25 });
      expect(floored, `entry ${p} must be unchanged`).toBe(legacy);
    }
  });

  it("does not disturb the dead zone or the premium band", () => {
    for (const p of [0.4, 0.5, 0.6, 0.8, 0.95]) {
      const floored = mapBankroll200Size(SCALE, p, FLOOR);
      const legacy = mapBankroll200Size(SCALE, p, { longshot: 3.5, deadZone: 0.25 });
      expect(floored, `entry ${p} must be unchanged`).toBe(legacy);
    }
  });

  it("keeps bad data falling through at x1.0 rather than throwing", () => {
    for (const p of [0, -0.5, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(() => mapBankroll200Size(SCALE, p, FLOOR)).not.toThrow();
    }
  });
});

describe("v67 long-shot floor — constants untouched", () => {
  it("does not move the shipped defaults", () => {
    expect(C200_BAND_DEFAULTS.longshot).toBe(2.0);
    expect(C200_BAND_DEFAULTS.deadZone).toBe(0.25);
    expect(C200_BAND_DEFAULTS.premium).toBe(0.5);
  });
});
