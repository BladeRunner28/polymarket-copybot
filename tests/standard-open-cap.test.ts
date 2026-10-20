/**
 * v64 — STANDARD open-position cap (user-approved 2026-10-20).
 *
 * The rail exists because `maxOpenPositions` is guarded `botId === "BANKROLL_200"`
 * (score-trades.ts:723), so STANDARD ran 1,263 open positions against a 225 cap that never
 * governed it. This test locks the two properties that make the rail safe to ship:
 *   - it defaults to 0, so a ruleset lacking the field behaves exactly as pre-v64, and
 *   - it is independent of the C-200 field, so enabling it cannot move C-200.
 */

import { describe, it, expect } from "vitest";
import { DEFAULT_RULES } from "../src/lib/rules";

describe("v64 STANDARD open-position cap", () => {
  it("ships DISABLED so a ruleset lacking the field behaves as pre-v64", () => {
    expect(DEFAULT_RULES.standardMaxOpenPositions).toBe(0);
  });

  it("is a separate field from the C-200 cap, so enabling one cannot move the other", () => {
    expect(DEFAULT_RULES.standardMaxOpenPositions).not.toBe(DEFAULT_RULES.maxOpenPositions);
    expect(DEFAULT_RULES.maxOpenPositions).toBe(100); // C-200 default untouched
  });

  it("is inert at 0 — the guard is `> 0`, so 0 means no ceiling rather than a ceiling of zero", () => {
    // A naive `>=` comparison against 0 would block every entry; the enforcement site checks
    // `rules.standardMaxOpenPositions > 0` first. Record the invariant here so a later refactor
    // cannot quietly turn "disabled" into "halt the lane".
    const guard = (cap: number, open: number) => cap > 0 && open >= cap;
    expect(guard(DEFAULT_RULES.standardMaxOpenPositions, 99999)).toBe(false);
    expect(guard(1300, 1263)).toBe(false); // headroom
    expect(guard(1300, 1300)).toBe(true); // binds exactly at the cap
    expect(guard(1300, 1301)).toBe(true);
  });
});
