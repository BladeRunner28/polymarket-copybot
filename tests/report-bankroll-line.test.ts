import { describe, expect, it } from "vitest";
import { bankrollLine } from "../src/lib/report";

/**
 * 2026-11-19 self-audit.
 *
 * The C-200 cash line used to be a bare template:
 *   `$${cmpBankroll ? Math.max(0, cmpBankroll.cashBalance).toFixed(2) : "0.00"} | …`
 * with the net-worth term defaulted to 0 when the row was absent. Both failure paths
 * printed a NUMBER where the honest answer was "not measured":
 *   - no BotBankroll row  -> "Available Cash: $0.00 | Current Net Worth: $0.00"
 *   - overdrawn cash (<0) -> "Available Cash: $0.00" (Math.max clamped the sign away)
 * The second is unrecoverable downstream: the ledger note compares cashBalance against
 * principal + realized − open notional, which goes negative with it, so no gap appears.
 *
 * The healthy path must stay byte-identical to what the 2026-11-19 12:50Z report printed.
 */
describe("the C-200 cash line cannot print a missing or negative balance as $0.00", () => {
  it("healthy path is byte-identical to the live 2026-11-19 line", () => {
    expect(bankrollLine({ cashBalance: 6993.96493648101, principal: 1900 }, 5123.94)).toBe(
      "• Available Cash: $6993.96 | Current Net Worth: $7023.94"
    );
  });

  it("no BotBankroll row says UNMEASURED, never $0.00", () => {
    const line = bankrollLine(undefined, 5123.94);
    expect(line).toContain("UNMEASURED");
    expect(line).toContain("NOT a $0.00 balance");
    expect(line).toContain("Current Net Worth: UNAVAILABLE");
    expect(line).not.toContain("Available Cash: $0.00");
  });

  it("an overdrawn ledger keeps its sign instead of clamping to zero", () => {
    const line = bankrollLine({ cashBalance: -412.5, principal: 1900 }, 100);
    expect(line).toContain("−$412.50");
    expect(line).toContain("NEGATIVE");
    expect(line).toContain("Current Net Worth: $2000.00");
    expect(line).not.toContain("Available Cash: $0.00");
  });

  it("a genuinely flat-but-present zero balance still reads $0.00 (not flagged)", () => {
    const line = bankrollLine({ cashBalance: 0, principal: 0 }, 0);
    expect(line).toBe("• Available Cash: $0.00 | Current Net Worth: $0.00");
    expect(line).not.toContain("⚠️");
  });
});
