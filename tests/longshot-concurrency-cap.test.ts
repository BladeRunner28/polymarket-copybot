/**
 * v74 — concurrent LONG-SHOT concentration rail (kelly rec 4, approved 2026-11-13).
 *
 * The rail bounds a quantity no other rail holds: the SUM of open long-shot (< longshotMaxPrice)
 * legs as a share of the lane's REALISED net worth. Measured before arming: C-200 reached 60.85%
 * on 2026-09-14 and STANDARD 21.33%, against a 20% drawdown gate that only sees the damage after
 * it lands.
 *
 * This test locks the four properties that make the rail safe to ship:
 *   - it defaults to 0, so a ruleset lacking the field behaves exactly as pre-v74;
 *   - the cap boundary is INCLUSIVE (fires only above, like v55/v58);
 *   - a lane with no accounting identity (net worth <= 0) is NOT halted;
 *   - the reason string is not a PORTFOLIO gate, so it cannot freeze both books with no leg-block
 *     trail.
 */

import { describe, it, expect } from "vitest";
import { longshotConcurrencyDecision, isPortfolioGate } from "../src/lib/exposure-cap";
import { DEFAULT_RULES } from "../src/lib/rules";

describe("v74 DEFAULT_RULES field", () => {
  it("ships DISABLED so a ruleset lacking the field behaves as pre-v74", () => {
    expect(DEFAULT_RULES.maxConcurrentLongshotPctOfNetWorth).toBe(0);
  });

  it("is a separate field from the per-market ceiling, so arming one cannot move the other", () => {
    // Same default VALUE (both ship disabled), different keys: arming the long-shot rail must
    // leave the v55 per-market ceiling exactly where it was.
    const armed = { ...DEFAULT_RULES, maxConcurrentLongshotPctOfNetWorth: 20 };
    expect(armed.maxConcurrentLongshotPctOfNetWorth).toBe(20);
    expect(armed.maxMarketNotionalPctOfCap).toBe(DEFAULT_RULES.maxMarketNotionalPctOfCap);
    expect(DEFAULT_RULES.maxMarketNotionalPctOfCap).toBe(0); // untouched
  });
});

describe("longshotConcurrencyDecision", () => {
  // NW 7,570.95 (C-200 realised, 2026-11-13) at 20% => cap 1,514.19
  const base = {
    openLongshotNotionalUsd: 350,
    sizeUsd: 100,
    pctOfNetWorth: 20,
    netWorthUsd: 7570.95,
  };

  it("allows a long-shot leg that stays under the cap", () => {
    expect(longshotConcurrencyDecision(base).blocked).toBe(false);
  });

  it("projects the incoming leg into the comparison (not just the open book)", () => {
    // open 1,450 + 60 = 1,510 < 1,514.19 -> allowed; the OPEN book alone is far under the cap
    expect(
      longshotConcurrencyDecision({ ...base, openLongshotNotionalUsd: 1450, sizeUsd: 60 }).blocked
    ).toBe(false);
    // open 1,450 + 100 = 1,550 > cap -> blocked, though the open book alone is under it
    expect(
      longshotConcurrencyDecision({ ...base, openLongshotNotionalUsd: 1450, sizeUsd: 100 }).blocked
    ).toBe(true);
  });

  it("treats the cap boundary as INCLUSIVE (fires only above, like v55/v58)", () => {
    const cap = 0.2 * base.netWorthUsd; // 1,514.19
    expect(
      longshotConcurrencyDecision({ ...base, openLongshotNotionalUsd: cap - 100, sizeUsd: 100 })
        .blocked
    ).toBe(false);
    expect(
      longshotConcurrencyDecision({ ...base, openLongshotNotionalUsd: cap - 100 + 0.01, sizeUsd: 100 })
        .blocked
    ).toBe(true);
  });

  it("never blocks a NON-long-shot leg (sizeUsd 0), even on a book at its cap", () => {
    const d = longshotConcurrencyDecision({ ...base, openLongshotNotionalUsd: 999999, sizeUsd: 0 });
    expect(d.blocked).toBe(false);
    expect(d.pctAfter).toBeCloseTo(999999 / 7570.95, 6);
  });

  it("0 disables the rail entirely (legacy semantics)", () => {
    const d = longshotConcurrencyDecision({ ...base, openLongshotNotionalUsd: 999999, pctOfNetWorth: 0 });
    expect(d.blocked).toBe(false);
    expect(d.capUsd).toBe(0);
  });

  it("does NOT halt a lane with no accounting identity (net worth <= 0)", () => {
    // A ratio against an unknown/negative denominator is not a ceiling — refusing every leg
    // would be an un-budgeted lane halt, the exact failure the exposure cap avoids for
    // principal <= 0.
    const d = longshotConcurrencyDecision({ ...base, netWorthUsd: 0 });
    expect(d.blocked).toBe(false);
    expect(d.capUsd).toBe(0);
    const neg = longshotConcurrencyDecision({ ...base, netWorthUsd: -500 });
    expect(neg.blocked).toBe(false);
  });

  it("reports the before/after share so the shadow line and the block reason agree", () => {
    const d = longshotConcurrencyDecision({ ...base, openLongshotNotionalUsd: 1450, sizeUsd: 100 });
    expect(d.blocked).toBe(true);
    expect(d.pctBefore).toBeCloseTo(1450 / 7570.95, 6);
    expect(d.pctAfter).toBeCloseTo(1550 / 7570.95, 6);
    expect(d.why).toContain("> 20% of NW");
  });

  it("is PER LANE: the same book against a smaller lane's net worth blocks", () => {
    const leg = { openLongshotNotionalUsd: 700, sizeUsd: 100, pctOfNetWorth: 20 };
    // C-200 at NW 7,570.95 -> cap 1,514 -> allowed
    expect(longshotConcurrencyDecision({ ...leg, netWorthUsd: 7570.95 }).blocked).toBe(false);
    // the same dollars on a lane with NW 3,500 -> cap 700 -> blocked
    expect(longshotConcurrencyDecision({ ...leg, netWorthUsd: 3500 }).blocked).toBe(true);
  });
});

describe("v74 is a LANE-SCOPED gate, not a portfolio gate", () => {
  it("its block reason does not match isPortfolioGate()", () => {
    const d = longshotConcurrencyDecision({
      openLongshotNotionalUsd: 999999,
      sizeUsd: 100,
      pctOfNetWorth: 20,
      netWorthUsd: 7570.95,
    });
    const reason = `BANKROLL_200: v74 concurrent long-shot cap (${d.why})`;
    expect(isPortfolioGate(reason)).toBe(false);
  });
});
