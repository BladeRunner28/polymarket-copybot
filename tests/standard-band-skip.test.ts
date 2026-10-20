/**
 * v63 (2026-10-20 profit review, user-approved in-thread): the STANDARD dead-zone band skip.
 *
 * Why this file exists when tests/band-size.test.ts already covers isInBandRange's boundary
 * semantics: the helper being correct does not mean the FIELD is correctly defaulted, and the
 * revert guarantee lives entirely in the default. If `standardSkipBandRange` ever ships as
 * anything but "" then every ruleset lacking the field silently starts skipping a band — the
 * single worst failure mode this change has.
 *
 * The scoping gap it closes is worth one line of context: every band/exit/concentration rail
 * since v41 was guarded `botId === "BANKROLL_200"`, so STANDARD (99% of the open book) sized
 * flat across bands. Measured on deduped STANDARD legs 2026-10-20: 0.40-0.60 was 43.5% of legs
 * and 44.1% of notional at -7.67% ROI, CI [-14.48,-0.89], rising to 75.5% of flow at -17.91%
 * over the last 7 days.
 */

import { describe, it, expect } from "vitest";
import { DEFAULT_RULES } from "../src/lib/rules";
import { isInBandRange } from "../src/lib/band-size";

describe("v63 STANDARD band skip", () => {
  it("ships DISABLED by default so a ruleset lacking the field behaves as pre-v63", () => {
    expect(DEFAULT_RULES.standardSkipBandRange).toBe("");
  });

  it("leaves the C-200 convention identical (both default to no skip)", () => {
    expect(DEFAULT_RULES.c200SkipBandRange).toBe("");
  });

  it("the activated v63 value skips only the dead zone", () => {
    const V63 = "0.4-0.6";
    expect(isInBandRange(0.5, V63)).toBe(true);
    expect(isInBandRange(0.4, V63)).toBe(true); // lo inclusive
    expect(isInBandRange(0.6, V63)).toBe(false); // hi exclusive
  });

  it("never touches the bands the same review wanted to KEEP", () => {
    const V63 = "0.4-0.6";
    expect(isInBandRange(0.15, V63)).toBe(false); // cheap tail — the paying band
    expect(isInBandRange(0.9, V63)).toBe(false); // near-certainty
    expect(isInBandRange(0.25, V63)).toBe(false);
  });

  it("is disabled for the empty default, so revert is one field", () => {
    for (const p of [0.3, 0.4, 0.5, 0.6, 0.7]) {
      expect(isInBandRange(p, DEFAULT_RULES.standardSkipBandRange)).toBe(false);
    }
  });
});
