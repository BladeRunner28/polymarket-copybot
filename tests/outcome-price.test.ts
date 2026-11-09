/**
 * 2026-11-09 — `price-side-inversion`: the ledger must price the token the leg
 * actually holds, by the venue's own label.
 *
 * Defect this pins: `MarketState.yesPrice`/`noPrice` are POSITIONAL —
 * `yesPrice = outcomePrices[0]`, `noPrice = outcomePrices[1]` — but every call
 * site read them with `outcome === "NO" ? noPrice : yesPrice`. On a market whose
 * tokens are named (`["Under","Over"]`, `["Vitality","9z"]`, moneyline team
 * names) the label `"NO"` never appears, so the leg was priced at the FIRST
 * token's price — the complement of the token it holds whenever it held the
 * second one.
 *
 * Measured cost (`scripts/profit-price-side.py`, 2026-11-08): 87 regime legs
 * (4.1%) booked the complement of the price the copied wallet paid for the SAME
 * labelled outcome, median mirror distance 0.007 around 0.50. A favourite booked
 * at its complement pays (1-p)/p on a win while still costing -stake on a loss,
 * so the error is one-sided and carried 56% of the book's booked PnL.
 *
 * These assertions FAIL on the pre-fix expression (they would all return the
 * first token's price) and PASS on `priceForOutcome`.
 */
import { describe, expect, it } from "vitest";
import { isYesSideOutcome, priceForOutcome } from "../src/lib/outcome-price";

const underOver = {
  outcomeLabels: ["Under", "Over"],
  outcomePrices: [0.3, 0.7],
  yesPrice: 0.3,
  noPrice: 0.7,
};

const teams = {
  outcomeLabels: ["Vitality", "9z"],
  outcomePrices: [0.12, 0.88],
  yesPrice: 0.12,
  noPrice: 0.88,
};

const binary = {
  outcomeLabels: ["Yes", "No"],
  outcomePrices: [0.25, 0.75],
  yesPrice: 0.25,
  noPrice: 0.75,
};

describe("priceForOutcome — named outcomes are priced by label", () => {
  it("prices the SECOND token at its own price, not the first token's", () => {
    // The defect: the old expression returned yesPrice (0.7) here.
    expect(priceForOutcome(underOver, "Over")).toBeCloseTo(0.7, 10);
    expect(priceForOutcome(underOver, "Under")).toBeCloseTo(0.3, 10);
  });

  it("is case- and punctuation-insensitive like the rest of the label path", () => {
    expect(priceForOutcome(teams, " 9Z ")).toBeCloseTo(0.88, 10);
    expect(priceForOutcome(teams, "vitality")).toBeCloseTo(0.12, 10);
  });

  it("keeps binary YES/NO byte-identical to the old behaviour", () => {
    expect(priceForOutcome(binary, "YES")).toBeCloseTo(0.25, 10);
    expect(priceForOutcome(binary, "NO")).toBeCloseTo(0.75, 10);
  });

  it("falls back to 1-minus when the payload omits the opposing price", () => {
    expect(priceForOutcome({ yesPrice: 0.2 }, "NO")).toBeCloseTo(0.8, 10);
    expect(priceForOutcome({ noPrice: 0.9 }, "YES")).toBeCloseTo(0.1, 10);
  });

  it("claims nothing for a named outcome on a payload with no token list", () => {
    // Callers keep their previous value rather than guess a side.
    expect(priceForOutcome({ yesPrice: 0.4, noPrice: 0.6 }, "Over")).toBeUndefined();
    expect(priceForOutcome(binary, "")).toBeUndefined();
    expect(priceForOutcome(binary, null)).toBeUndefined();
  });

  it("rejects a label that is not in the venue's token list", () => {
    expect(priceForOutcome(underOver, "Draw")).toBeUndefined();
  });

  it("ignores a non-finite or out-of-range venue price", () => {
    expect(
      priceForOutcome({ outcomeLabels: ["A", "B"], outcomePrices: [NaN, 0.6] }, "A")
    ).toBeUndefined();
    expect(
      priceForOutcome({ outcomeLabels: ["A", "B"], outcomePrices: [1.4, 0.6] }, "A")
    ).toBeUndefined();
  });
});

describe("isYesSideOutcome — the YES-frame flip keyed on the venue's ordering", () => {
  it("knows the second token is not the yes side", () => {
    expect(isYesSideOutcome(underOver, "Over")).toBe(false);
    expect(isYesSideOutcome(underOver, "Under")).toBe(true);
  });

  it("keeps literal YES/NO exact", () => {
    expect(isYesSideOutcome(binary, "YES")).toBe(true);
    expect(isYesSideOutcome(binary, "NO")).toBe(false);
  });

  it("returns true (the pre-fix assumption) when the payload cannot say", () => {
    expect(isYesSideOutcome({}, "Over")).toBe(true);
    expect(isYesSideOutcome({ outcomeLabels: ["A", "B"] }, "Draw")).toBe(true);
  });
});
