/**
 * v66 — STANDARD's scoped stale exit (entry >= 0.60, 168h).
 *
 * The rail exists because the v33 hard max-age is gated `botId === "BANKROLL_200"` in
 * scripts/update-pnl.ts, so STANDARD has never recycled capital at all. This test locks
 * the properties that make the rail safe to ship:
 *   - it defaults to DISABLED (0), so a ruleset lacking the field behaves as pre-v66;
 *   - the band is an ENTRY-price test with an inclusive floor;
 *   - it cannot fire below the floor, which is where the measurement says the stop
 *     destroys value (-$1,064 on 0.20-0.40);
 *   - it is independent of the C-200 helper, so enabling it cannot move C-200.
 */

import { describe, it, expect } from "vitest";
import { DEFAULT_RULES } from "../src/lib/rules";
import { standardStaleExitFires, staleExitDecision } from "../src/lib/paper";

const ON = { standardStaleExitHours: 168, standardStaleExitBandMin: 0.6 };

describe("v66 standard stale exit — defaults", () => {
  it("is disabled in DEFAULT_RULES, so an unpatched ruleset cannot start closing legs", () => {
    expect(DEFAULT_RULES.standardStaleExitHours).toBe(0);
    expect(standardStaleExitFires(10_000, 0.95, DEFAULT_RULES)).toBe(false);
  });

  it("carries the measured band floor", () => {
    expect(DEFAULT_RULES.standardStaleExitBandMin).toBe(0.6);
  });

  it("treats 0 and negative hours as disabled rather than 'close immediately'", () => {
    expect(standardStaleExitFires(1e6, 0.95, { ...ON, standardStaleExitHours: 0 })).toBe(false);
    expect(standardStaleExitFires(1e6, 0.95, { ...ON, standardStaleExitHours: -5 })).toBe(false);
  });
});

describe("v66 standard stale exit — age", () => {
  it("does not fire before 168h", () => {
    expect(standardStaleExitFires(167.9, 0.7, ON)).toBe(false);
  });

  it("fires at exactly 168h (inclusive)", () => {
    expect(standardStaleExitFires(168, 0.7, ON)).toBe(true);
  });

  it("fires well past 168h", () => {
    expect(standardStaleExitFires(1_000, 0.7, ON)).toBe(true);
  });
});

describe("v66 standard stale exit — band scope", () => {
  it("fires for an entry above the floor", () => {
    expect(standardStaleExitFires(200, 0.95, ON)).toBe(true);
  });

  it("fires at exactly the 0.60 floor (inclusive)", () => {
    expect(standardStaleExitFires(200, 0.6, ON)).toBe(true);
  });

  it("does NOT fire just below the floor", () => {
    expect(standardStaleExitFires(200, 0.5999, ON)).toBe(false);
  });

  it("does NOT fire in the cheap band where the stop destroys value", () => {
    for (const p of [0.05, 0.15, 0.2, 0.3, 0.4, 0.5, 0.59]) {
      expect(standardStaleExitFires(1_000, p, ON), `entry ${p} must be out of scope`).toBe(false);
    }
  });

  it("treats a non-finite entry price as out of scope rather than firing", () => {
    expect(standardStaleExitFires(1_000, Number.NaN, ON)).toBe(false);
  });
});

describe("v66 does not disturb the C-200 rail", () => {
  const c200 = {
    staleExitHours: 48,
    staleExitMinMove: 0.05,
    staleExitHardHours: 168,
    staleExitAdverseOnly: 1,
    staleExitAdverseMove: -0.15,
  };

  it("C-200 behaviour is unchanged by the new fields", () => {
    expect(staleExitDecision(200, 0.5, c200)).toBe("hard_max_age");
    expect(staleExitDecision(10, 0.5, c200)).toBe("none");
    // v66 fields are absent from StaleExitRules by construction — nothing to enable.
    expect(Object.keys(c200)).not.toContain("standardStaleExitHours");
  });

  it("the STANDARD helper is not unconditional the way the C-200 one is", () => {
    // Same age, same rules: C-200 fires at any price, STANDARD only at/above the floor.
    expect(staleExitDecision(200, 0.3, c200)).toBe("hard_max_age");
    expect(standardStaleExitFires(200, 0.3, ON)).toBe(false);
  });
});
