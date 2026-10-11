/**
 * Tests for the ML training-data export helpers (card `ml1-target-net-pnl-and-price-baseline`).
 *
 * The target math is the part the card's gate depends on, and it has to agree with
 * `scripts/build-decision-dataset.py` (the frozen Python artifact) digit for digit — the export
 * script asserts that reconciliation on every run, and these tests pin the pieces it is built from:
 * the fee decomposition, the net target + its sign, the dedupe key, the era boundaries, and the
 * second (market-outcome) label's null discipline.
 */

import { describe, it, expect } from "vitest";
import {
  dedupeFirstPerPosition,
  eraOf,
  feeDecomposition,
  netTargets,
  outcomeLabel,
  round4,
} from "../src/lib/training-export";

describe("feeDecomposition", () => {
  it("reproduces the Python fee model: entry fee = size * rate * (1 - entry)", () => {
    const f = feeDecomposition({
      entryPrice: 0.5,
      sizeUsd: 10,
      feeText: "Will BTC close above $100k?",
      status: "closed",
      currentPrice: 0.9,
    });
    expect(f.feeRate).toBe(0.07); // crypto keyword
    expect(f.shares).toBeCloseTo(20, 9);
    expect(f.feeEntryUsd).toBeCloseTo(10 * 0.07 * 0.5, 9); // = shares * takerFeePerShare(0.5, .07)
    expect(f.feeExitUsd).toBeCloseTo(20 * 0.07 * 0.9 * 0.1, 9);
    expect(f.exitPrice).toBe(0.9);
  });

  it("charges no exit fee on a settled leg (0/1 payoff, no trade)", () => {
    const f = feeDecomposition({
      entryPrice: 0.25,
      sizeUsd: 10,
      feeText: "Will the Fed cut rates in October?",
      status: "resolved",
      currentPrice: 1,
    });
    expect(f.feeRate).toBe(0.04); // politics/finance keyword
    expect(f.exitPrice).toBeNull();
    expect(f.feeExitUsd).toBe(0);
  });

  it("falls back to the default rate and ignores an unusable exit mark", () => {
    const f = feeDecomposition({
      entryPrice: 0.4,
      sizeUsd: 10,
      feeText: "Will Team Spirit win the series?",
      status: "closed",
      currentPrice: 1, // no usable early-exit mark
    });
    expect(f.feeRate).toBe(0.05);
    expect(f.exitPrice).toBeNull();
    expect(f.feeExitUsd).toBe(0);
  });
});

describe("netTargets", () => {
  it("subtracts the entry fee from realized PnL and labels the sign", () => {
    const fees = feeDecomposition({
      entryPrice: 0.5,
      sizeUsd: 10,
      feeText: "generic market",
      status: "closed",
      currentPrice: 0.8,
    });
    const t = netTargets({ realizedPnl: 1, fees });
    expect(t.pnlNetEntry).toBeCloseTo(1 - fees.feeEntryUsd, 9);
    expect(t.pnlNetFull).toBeCloseTo(1 - fees.feeEntryUsd - fees.feeExitUsd, 9);
    expect(t.yNetEntry).toBe(1);
  });

  it("treats a gross win that fees eat into a loss as y_net_entry = 0", () => {
    const fees = feeDecomposition({
      entryPrice: 0.05,
      sizeUsd: 50,
      feeText: "crypto market",
      status: "closed",
      currentPrice: 0.5,
    });
    const t = netTargets({ realizedPnl: 0.5, fees });
    expect(fees.feeEntryUsd).toBeGreaterThan(0.5); // 50 * 0.07 * 0.95
    expect(t.pnlNetEntry).toBeLessThan(0);
    expect(t.yNetEntry).toBe(0);
  });

  it("does not call an exactly-break-even leg a win", () => {
    const fees = feeDecomposition({
      entryPrice: 0.5,
      sizeUsd: 10,
      feeText: "generic market",
      status: "resolved",
      currentPrice: null,
    });
    const t = netTargets({ realizedPnl: fees.feeEntryUsd, fees });
    expect(t.pnlNetEntry).toBe(0);
    expect(t.yNetEntry).toBe(0);
  });
});

describe("dedupeFirstPerPosition", () => {
  const row = (botId: string, walletAddress: string, marketId: string, outcome: string, tag: string) => ({
    botId,
    walletAddress,
    marketId,
    outcome,
    tag,
  });

  it("keeps the first entry per bot|wallet|market|outcome and drops the rest", () => {
    const rows = [
      row("STANDARD", "0x1", "m1", "YES", "first"),
      row("STANDARD", "0x1", "m1", "YES", "duplicate-accumulation"),
      row("STANDARD", "0x1", "m1", "NO", "other-token"),
      row("BANKROLL_200", "0x1", "m1", "YES", "other-bot"),
      row("STANDARD", "0x2", "m1", "YES", "other-wallet"),
    ];
    expect(dedupeFirstPerPosition(rows).map((r) => r.tag)).toEqual([
      "first",
      "other-token",
      "other-bot",
      "other-wallet",
    ]);
  });

  it("is order-stable (caller supplies openedAt ASC)", () => {
    const rows = [row("STANDARD", "0x1", "m1", "YES", "a"), row("STANDARD", "0x1", "m1", "YES", "b")];
    expect(dedupeFirstPerPosition(rows)[0].tag).toBe("a");
  });
});

describe("eraOf", () => {
  it("splits at the documented milestones and never guesses an unversioned row", () => {
    expect(eraOf(48)).toBe("pre-kelly-v1-48");
    expect(eraOf(49)).toBe("kelly-window-v49-57");
    expect(eraOf(57)).toBe("kelly-window-v49-57");
    expect(eraOf(58)).toBe("exposure-v58plus");
    expect(eraOf(61)).toBe("exposure-v58plus");
    expect(eraOf(null)).toBe("unknown");
    expect(eraOf(undefined)).toBe("unknown");
  });
});

describe("outcomeLabel", () => {
  it("compares the traded token against the venue's winning label", () => {
    expect(outcomeLabel("YES", "Yes")).toBe(1);
    expect(outcomeLabel("NO", "Yes")).toBe(0);
    expect(outcomeLabel("Under", "Under")).toBe(1);
  });

  it("returns null rather than guessing when the labels describe different markets", () => {
    expect(outcomeLabel("Vitality", "Yes")).toBeNull(); // non-binary vs binary
    expect(outcomeLabel("YES", null)).toBeNull(); // no stored winner
    expect(outcomeLabel(null, "Yes")).toBeNull();
  });
});

describe("round4", () => {
  it("matches the Python dataset's 4-decimal rounding so sums reconcile", () => {
    expect(round4(0.123456)).toBe(0.1235);
    expect(round4(-0.00004)).toBe(-0);
    expect(round4(1)).toBe(1);
  });
});
