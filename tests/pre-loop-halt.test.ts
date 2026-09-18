/**
 * #29 rec 2 (2026-09-19, user-approved): the pre-loop halt detector.
 *
 * Why it matters: portfolio gates (drawdown, gross exposure) fire BEFORE the
 * per-bot leg loop, so a total halt produced no copies, no leg blocks and no log
 * signal — the Sep 16-18 freeze ran 39.7h before a human noticed. The count of
 * "portfolio gate blocked this candidate" is what turns that silence into a
 * `[PRE-LOOP HALT]` line on every halted cycle.
 *
 * These tests pin the CLASSIFIER against the exact strings the gates emit, so a
 * rewording cannot silently disable the detector.
 */

import { describe, it, expect } from "vitest";
import { isPortfolioGate } from "../src/lib/exposure-cap";

describe("isPortfolioGate", () => {
  it("matches the drawdown gate, in both basis forms", () => {
    expect(isPortfolioGate("drawdown gate [realized] (net worth $2402 vs peak $2442 = 1.6% > 20%)")).toBe(true);
    expect(isPortfolioGate("drawdown gate (net worth $2496 vs peak $3409 = 26.8% > 20%)")).toBe(true);
  });

  it("matches the gross-exposure cap", () => {
    expect(
      isPortfolioGate("gross exposure cap (1275.00 > 1251 = $1000 base + 50% above principal)")
    ).toBe(true);
  });

  it("does NOT match scoped gates — they cannot halt the whole book", () => {
    for (const reason of [
      "category concentration (Crypto would be 41/40)",
      "token circuit breaker (flash move 18% in 5m)",
      "BANKROLL_200: v55 per-market cap (legs 3 > max 2)",
      "BANKROLL_200: v45 market-slug cap (highest would be 16/15)",
      "BANKROLL_200: hour blackout 8:00 ET",
      "wallet daily copy cap (25) reached",
      "price drifted 0.012 since entry > max 0.004 (too late)",
    ]) {
      expect(isPortfolioGate(reason)).toBe(false);
    }
  });
});
