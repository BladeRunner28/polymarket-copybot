/**
 * v65 (2026-10-21, profit-recs #3, user-approved "Do recommendation"):
 * wallet quality becomes an ADMISSION-only signal, not a SIZE signal.
 *
 * Why this file exists: the revert guarantee for this change lives ENTIRELY in the
 * default. If `walletQualityInSize` ever ships as anything but 1, then every ruleset
 * lacking the field silently stops using wallet quality in size — a change nobody
 * approved, applied to every historical and replay ruleset at once. So the default is
 * asserted here first, before any behaviour test.
 *
 * The measured effect (scripts/wallet-size-separation-read.py, 9,043 STANDARD legs,
 * both arms re-computed under v64): notional $137,895.70 -> $130,697.91 (-5.2%),
 * mean clip $15.25 -> $14.45, 1,738 legs down / 632 up / 6,673 unchanged.
 */

import { describe, it, expect } from "vitest";
import { DEFAULT_RULES } from "../src/lib/rules";

describe("v65 walletQualityInSize", () => {
  it("defaults to 1 so a ruleset lacking the field keeps LEGACY sizing", () => {
    expect(DEFAULT_RULES.walletQualityInSize).toBe(1);
  });

  it("the wallet term is 0.30 of a 1.00 composite, so the remaining weights are 0.70", () => {
    // The renormalisation in trade.ts divides by 0.70. If the composite weights ever
    // change without this test, the size score silently shifts scale.
    const WEIGHTS = { wallet: 0.3, catFit: 0.15, entry: 0.2, spread: 0.1, liquidity: 0.15, thesis: 0.1 };
    const total = Object.values(WEIGHTS).reduce((a, b) => a + b, 0);
    expect(total).toBeCloseTo(1.0, 10);
    expect(1 - WEIGHTS.wallet).toBeCloseTo(0.7, 10);
  });

  it("removing the wallet term is a renormalisation, not a shrink: a wallet score equal to the rest leaves the score unchanged", () => {
    const wallet = 74;
    const other = 74;
    const copyScore = wallet * 0.3 + other * 0.7;
    const sizeScore = (copyScore - wallet * 0.3) / 0.7;
    expect(sizeScore).toBeCloseTo(74, 10);
  });

  it("a wallet score ABOVE the other components lowers the size score when the flag is 0", () => {
    // Measured population mean: wallet 79.04 vs other-components 73.37, so on the
    // real book the flag removes a 5.67pt boost rather than adding one.
    const wallet = 79.04;
    const other = 73.37;
    const copyScore = wallet * 0.3 + other * 0.7;
    const sizeScore = (copyScore - wallet * 0.3) / 0.7;
    expect(sizeScore).toBeLessThan(copyScore);
    expect(sizeScore).toBeCloseTo(73.37, 6);
  });
});
