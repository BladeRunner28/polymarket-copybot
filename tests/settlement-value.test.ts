import { describe, expect, it } from "vitest";
import { settlementValue } from "../src/lib/resolution";

/**
 * The venue reports a winning token label in its own casing ("No", "Under",
 * "Team Liquid"); the trade's outcome is uppercased at ingest ("NO", "UNDER").
 * A raw `winnerLabel === tradeOutcome` therefore never matched a label-cased
 * market and scored every settled one as a loss — the `outcome-casing-mismatch`
 * signature. These cases pin the normalised comparison.
 */
describe("settlementValue — venue winner label vs stored trade outcome", () => {
  it("matches a mixed-case venue label against the uppercased stored outcome (win = 1)", () => {
    expect(settlementValue("UNDER", { winningLabel: "Under" })).toBe(1);
    expect(settlementValue("YES", { winningLabel: "Yes" })).toBe(1);
    expect(settlementValue("NO", { winningLabel: "No" })).toBe(1);
    expect(settlementValue("TEAM LIQUID", { winningLabel: "Team Liquid" })).toBe(1);
    expect(settlementValue("MINNESOTA TWINS", { winningLabel: "Minnesota Twins" })).toBe(1);
  });

  it("reads a different mixed-case winner as a loss (0), not as undeterminable", () => {
    expect(settlementValue("YES", { winningLabel: "No" })).toBe(0);
    expect(settlementValue("TEAM LIQUID", { winningLabel: "Team Falcons" })).toBe(0);
    expect(settlementValue("UNDER", { winningLabel: "Over" })).toBe(0);
  });

  it("returns undefined — never a phantom 0 — when the labels cannot be compared", () => {
    // binary winner vs non-binary trade label: different markets, do not guess
    expect(settlementValue("VITALITY", { winningLabel: "No" })).toBeUndefined();
    // empty stored outcome
    expect(settlementValue("", { winningLabel: "No" })).toBeUndefined();
    // no label at all on a non-binary trade
    expect(settlementValue("UNDER", {})).toBeUndefined();
  });

  it("still uses the YES-price fallback for binary trades", () => {
    expect(settlementValue("YES", { yesPrice: 0.98 })).toBe(1);
    expect(settlementValue("NO", { yesPrice: 0.98 })).toBe(0);
    expect(settlementValue("UNDER", { yesPrice: 0.98 })).toBeUndefined();
  });
});
