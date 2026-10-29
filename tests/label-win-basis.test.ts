/**
 * label-integrity-wallet-win-filter — the `won` flag on a closed-position row.
 *
 * Two things are pinned here:
 *  1. the label itself: only a TERMINAL mark may state a settled win; a mark
 *     inside the band (or a missing price) must return null, never a guess;
 *  2. the blast radius: `scoreWallet` does not read `won` at all, so correcting
 *     the label cannot move a score or a status. That is what makes the fix
 *     Lane B. If a future change makes the scorer read `won`, this test goes
 *     red and the change has to be priced as Lane A instead.
 */
import { describe, it, expect } from "vitest";
import { settledWinFromMark } from "../src/lib/resolution";
import { scoreWallet, walletStatus } from "../src/lib/scoring/wallet";
import { DEFAULT_RULES } from "../src/lib/rules";
import { WalletActivityTrade } from "../src/lib/types";

function trade(o: Partial<WalletActivityTrade> = {}): WalletActivityTrade {
  return {
    marketId: "m1",
    marketQuestion: "Test market?",
    marketCategory: "sports",
    outcome: "YES",
    side: "BUY",
    price: 0.5,
    size: 100,
    timestamp: new Date(),
    resolved: true,
    won: true,
    pnl: 50,
    liquidity: 50_000,
    spread: 0.01,
    ...o,
  };
}

describe("settledWinFromMark — a closed position states a win only when the mark is terminal", () => {
  it("reads a terminal winning mark as a win", () => {
    expect(settledWinFromMark(1)).toBe(true);
    expect(settledWinFromMark(0.999)).toBe(true);
    expect(settledWinFromMark(0.99)).toBe(true);
  });

  it("reads a terminal losing mark as a loss", () => {
    expect(settledWinFromMark(0)).toBe(false);
    expect(settledWinFromMark(0.001)).toBe(false);
    expect(settledWinFromMark(0.01)).toBe(false);
  });

  it("refuses to call a MARK inside the band a settled win", () => {
    // The old expression called every one of these a win (or used our exit).
    for (const mark of [0.5, 0.51, 0.75, 0.95, 0.98, 0.02, 0.2]) {
      expect(settledWinFromMark(mark)).toBeNull();
    }
  });

  it("refuses to guess when the row carries no price", () => {
    expect(settledWinFromMark(undefined)).toBeNull();
    expect(settledWinFromMark(null)).toBeNull();
    expect(settledWinFromMark(NaN)).toBeNull();
    expect(settledWinFromMark(Infinity)).toBeNull();
  });
});

describe("blast radius — the scorer derives wins from pnl, never from `won`", () => {
  const legs = [
    trade({ pnl: 40, won: true }),
    trade({ pnl: -30, won: false }),
    trade({ pnl: 12, won: true }),
    trade({ pnl: -8, won: false }),
    trade({ pnl: 25, won: true }),
  ];

  it("gives an identical score with `won` flipped on every leg", () => {
    const flipped = legs.map((t) => ({ ...t, won: !t.won }));
    const a = scoreWallet(legs, DEFAULT_RULES);
    const b = scoreWallet(flipped, DEFAULT_RULES);
    expect(b.globalScore).toBe(a.globalScore);
    expect(b.winRate30d).toBe(a.winRate30d);
    expect(b.consistencyScore).toBe(a.consistencyScore);
    expect(b.oneHitWonderPenalty).toBe(a.oneHitWonderPenalty);
    expect(walletStatus(b, DEFAULT_RULES)).toEqual(walletStatus(a, DEFAULT_RULES));
  });

  it("gives an identical score when `won` is absent (the early-exit label)", () => {
    const absent = legs.map((t) => ({ ...t, won: undefined }));
    const a = scoreWallet(legs, DEFAULT_RULES);
    const b = scoreWallet(absent, DEFAULT_RULES);
    expect(b.globalScore).toBe(a.globalScore);
    expect(b.winRate30d).toBe(a.winRate30d);
    expect(b.categoryStrengths.sports.winRate).toBe(a.categoryStrengths.sports.winRate);
  });
});
