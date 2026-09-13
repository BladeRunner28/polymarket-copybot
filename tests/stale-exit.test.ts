/**
 * v53 C-200 Change 1 tests (2026-09-13 daily report, user-approved): the tier-1
 * stale exit is ADVERSE-ONLY. Pre-v53 it was "flat is bad" (cut anything not
 * already up ≥ staleExitMinMove at staleExitHours), which realized 24h noise as
 * losses: 24–72h exits, 1,069 rows, −$1,215.72 on $7,152 staked (−17.0% ROI).
 *
 * The rules object is the RuleSet v53 shape; the legacy branch must stay
 * byte-identical so a revert (staleExitAdverseOnly = 0) restores old behavior.
 */

import { describe, it, expect } from "vitest";
import { staleExitDecision, winMovePct, type StaleExitRules } from "../src/lib/paper";

const V53: StaleExitRules = {
  staleExitHours: 24,
  staleExitMinMove: 0.05,
  staleExitHardHours: 168,
  staleExitAdverseOnly: 1,
  staleExitAdverseMove: -0.15,
};

const LEGACY: StaleExitRules = { ...V53, staleExitAdverseOnly: 0 };

describe("winMovePct", () => {
  it("BUY: a rising price is winning", () => {
    expect(winMovePct("BUY", 0.4, 0.5)).toBeCloseTo(0.25, 6);
    expect(winMovePct("BUY", 0.4, 0.34)).toBeCloseTo(-0.15, 6);
  });

  it("SELL: a falling price is winning (sign flips)", () => {
    expect(winMovePct("SELL", 0.4, 0.5)).toBeCloseTo(-0.25, 6);
    expect(winMovePct("SELL", 0.4, 0.34)).toBeCloseTo(0.15, 6);
  });

  it("never divides by a zero entry", () => {
    expect(winMovePct("BUY", 0, 0.5)).toBe(0);
  });
});

describe("staleExitDecision — v53 adverse-only", () => {
  it("spares the flat position the old rule cut (the whole point of Change 1)", () => {
    // 30h old, +1% — pre-v53 this was closed (winMove < +5%), realizing noise.
    expect(staleExitDecision(30, 0.01, V53)).toBe("none");
    expect(staleExitDecision(30, 0.01, LEGACY)).toBe("tier1");
  });

  it("spares everything between the adverse threshold and +5%", () => {
    for (const mv of [-0.1499, -0.05, 0, 0.01, 0.0499]) {
      expect(staleExitDecision(48, mv, V53)).toBe("none");
    }
  });

  it("cuts an adverse move at ≥24h", () => {
    expect(staleExitDecision(24, -0.15, V53)).toBe("tier1"); // boundary is inclusive
    expect(staleExitDecision(25, -0.1501, V53)).toBe("tier1");
    expect(staleExitDecision(120, -0.6, V53)).toBe("tier1");
  });

  it("does not touch anything younger than the tier-1 age gate", () => {
    expect(staleExitDecision(23.99, -0.9, V53)).toBe("none");
    expect(staleExitDecision(0, -0.9, V53)).toBe("none");
  });

  it("the 168h hard max-age still fires regardless of move (winners included)", () => {
    expect(staleExitDecision(168, 0.8, V53)).toBe("hard_max_age");
    expect(staleExitDecision(200, -0.9, V53)).toBe("hard_max_age");
    expect(staleExitDecision(168, 0.8, LEGACY)).toBe("hard_max_age");
  });
});

describe("staleExitDecision — legacy branch stays revert-identical", () => {
  it("legacy cuts flat-or-worse at ≥24h and nothing below the age gate", () => {
    expect(staleExitDecision(24, 0.0499, LEGACY)).toBe("tier1");
    expect(staleExitDecision(24, 0.05, LEGACY)).toBe("none"); // +5% exactly is not cut
    expect(staleExitDecision(24, -0.5, LEGACY)).toBe("tier1");
    expect(staleExitDecision(23, -0.5, LEGACY)).toBe("none");
  });

  it("legacy ignores the adverse threshold entirely", () => {
    expect(staleExitDecision(48, -0.14, LEGACY)).toBe("tier1");
    expect(staleExitDecision(48, -0.14, V53)).toBe("none");
  });
});
