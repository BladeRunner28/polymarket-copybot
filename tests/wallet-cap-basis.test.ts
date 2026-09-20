/**
 * Per-wallet ceiling BASIS (v59, 2026-09-19 daily report rec 2, user-approved) and
 * the shadow feed's band edges (rec 1a).
 *
 * The behaviour that matters: with the basis on "delta", a wallet's ceiling is
 * `grandfathered(wallet) + pct × effectiveCap`, so a wallet already above the plain
 * ceiling keeps its book and may add at most one ceiling of NEW notional — instead
 * of being frozen outright until ~$560 of its book closes on its own.
 */

import { describe, it, expect } from "vitest";
import { baselineFor, type WalletCapBaselineFile } from "../src/lib/wallet-cap-basis";
import { bandOf } from "../src/lib/shadow-wallet-cap";

const FILE: WalletCapBaselineFile = {
  declaredAt: "2026-09-20T09:30:00.000Z",
  appliedWithRuleSet: 59,
  capUsd: 1725,
  ceilingUsd: 431.25,
  basis: "delta",
  baseline: { "0xb0c8": 993.66, "0xcd91": 121.47 },
};

describe("baselineFor", () => {
  it("returns the grandfathered notional for a wallet that existed at activation", () => {
    expect(baselineFor(FILE, "0xb0c8")).toBe(993.66);
    expect(baselineFor(FILE, "0xcd91")).toBe(121.47);
  });

  it("returns 0 for a wallet first seen after activation (plain ceiling, not a fallback)", () => {
    expect(baselineFor(FILE, "0xNEWWALLET")).toBe(0);
  });

  it("returns 0 when the basis file is absent (stock semantics)", () => {
    expect(baselineFor(null, "0xb0c8")).toBe(0);
  });

  it("ignores non-finite, negative and zero entries", () => {
    const messy = {
      ...FILE,
      baseline: { a: Number.NaN, b: -5, c: 0, d: 42 } as Record<string, number>,
    };
    expect(baselineFor(messy, "a")).toBe(0);
    expect(baselineFor(messy, "b")).toBe(0);
    expect(baselineFor(messy, "c")).toBe(0);
    expect(baselineFor(messy, "d")).toBe(42);
  });

  it("turns a frozen wallet into a gated one: the frozen case vs the grandfathered ceiling", () => {
    const stockCeiling = 431.25; // 25% of cap, no grandfathering
    const walletOpen = 993.66;
    // stock basis: already 2.3x the ceiling -> every new leg vetoed
    expect(walletOpen + 50 > stockCeiling).toBe(true);
    // delta basis: current + new must exceed baseline + ceiling to be blocked
    const deltaCeiling = stockCeiling + baselineFor(FILE, "0xb0c8");
    expect(walletOpen + 50 > deltaCeiling).toBe(false); // allowed -> flow restored
    expect(walletOpen + 500 > deltaCeiling).toBe(true); // but the allowance is finite
  });
});

describe("bandOf", () => {
  it("buckets prices onto the calibration table's edges", () => {
    expect(bandOf(0.03)).toBe("0-0.2");
    expect(bandOf(0.199)).toBe("0-0.2");
    expect(bandOf(0.2)).toBe("0.2-0.4");
    expect(bandOf(0.39)).toBe("0.2-0.4");
    expect(bandOf(0.55)).toBe("0.4-0.6");
    expect(bandOf(0.7)).toBe("0.6-0.8");
    expect(bandOf(0.95)).toBe("0.8-1.01");
  });
});
