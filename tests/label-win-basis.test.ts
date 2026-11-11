/**
 * label-integrity-wallet-win-filter — the `won` flag on a closed-position row, and the
 * basis the wallet SCORE reads.
 *
 * Three things are pinned here:
 *  1. the label itself: only a TERMINAL mark may state a settled win; a mark
 *     inside the band (or a missing price) must return null, never a guess;
 *  2. the score basis (Lane A, operator-approved 2026-11-11): every win-rate arm
 *     reads `won`, so a leg we exited at a profit on a token that settled to zero
 *     is a LOSS, and a leg with no knowable outcome is excluded from the
 *     denominator rather than defaulted;
 *  3. what must NOT move with it: ROI, the one-hit-wonder penalty and the
 *     resolved population. Those price what the wallet EARNED; only the
 *     win-rate arms claim to price what it PREDICTED.
 *
 * History worth knowing before editing: until 2026-10-29 the scorer read
 * `(pnl ?? 0) > 0` and this file pinned "the scorer does not read `won`" — that
 * pin is what forced the basis swap to be priced as Lane A instead of slipping
 * in as a label fix. It now pins the opposite, on purpose.
 */
import { describe, it, expect } from "vitest";
import { settledWinFromMark } from "../src/lib/resolution";
import { consistencyScore, scoreWallet, settledWinRate, walletStatus } from "../src/lib/scoring/wallet";
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

describe("settledWinRate — the settlement basis every win-rate arm reads", () => {
  it("counts what SETTLED, not what we sold for", () => {
    // Two profitable exits on tokens that settled LOST, one losing exit on a token that
    // settled WON. `pnl > 0` reads 2/3; settlement reads 1/3.
    const trades = [
      trade({ won: false, pnl: 40 }),
      trade({ won: false, pnl: 25 }),
      trade({ won: true, pnl: -60 }),
    ];
    expect(settledWinRate(trades)).toBeCloseTo(1 / 3, 12);
  });

  it("excludes a leg with no knowable outcome from the denominator (never defaults it)", () => {
    const trades = [
      trade({ won: true, pnl: 10 }),
      trade({ won: false, pnl: -10 }),
      trade({ won: undefined, pnl: 30 }), // mid mark: not a win, and not counted at all
    ];
    expect(settledWinRate(trades)).toBe(0.5);
  });

  it("returns null when nothing in the sample settled (no evidence != 0% wins)", () => {
    expect(settledWinRate([trade({ won: undefined })])).toBeNull();
    expect(settledWinRate([])).toBeNull();
  });

  it("requires the row to be resolved as well as flagged", () => {
    // An open position must never be treated as evidence either way, even if it
    // carries a stray flag.
    expect(settledWinRate([trade({ resolved: false, won: true, pnl: undefined })])).toBeNull();
  });
});

describe("scoreWallet — the win-rate arms read the settlement flag", () => {
  const legs = [
    trade({ pnl: 40, won: true }),
    trade({ pnl: -30, won: false }),
    trade({ pnl: 12, won: true }),
    trade({ pnl: -8, won: false }),
    trade({ pnl: 25, won: true }),
  ];

  it("moves winRate30d and consistencyScore when `won` moves, holding PnL fixed", () => {
    const flipped = legs.map((t) => ({ ...t, won: !t.won }));
    const a = scoreWallet(legs, DEFAULT_RULES);
    const b = scoreWallet(flipped, DEFAULT_RULES);
    expect(a.winRate30d).toBeCloseTo(0.6, 12); // 3 of 5 settled wins
    expect(b.winRate30d).toBeCloseTo(0.4, 12);
    expect(b.consistencyScore).not.toBe(a.consistencyScore);
    expect(b.globalScore).not.toBe(a.globalScore);
  });

  it("prices a profitable exit on a lost token as a LOSS (the defect this replaced)", () => {
    const profitableButLost = [
      trade({ won: false, pnl: 40 }),
      trade({ won: false, pnl: 30 }),
      trade({ won: false, pnl: 20 }),
    ];
    expect(settledWinRate(profitableButLost)).toBe(0);
    expect(scoreWallet(profitableButLost, DEFAULT_RULES).winRate30d).toBe(0);
    // ...while ROI still reads the money that was actually made.
    expect(scoreWallet(profitableButLost, DEFAULT_RULES).roi30d).toBeGreaterThan(0);
  });

  it("drops unknown-outcome legs from winRate30d but keeps them in the resolved population", () => {
    const withUnknown = [...legs, trade({ won: undefined, pnl: 15 })];
    const s = scoreWallet(withUnknown, DEFAULT_RULES);
    expect(s.winRate30d).toBeCloseTo(0.6, 12); // 3/5, the 6th leg is not evidence
    expect(s.resolvedTradeCount30d).toBe(6); // population unchanged
  });

  it("leaves ROI and the one-hit-wonder penalty on their old (PnL) basis", () => {
    const flipped = legs.map((t) => ({ ...t, won: !t.won }));
    const a = scoreWallet(legs, DEFAULT_RULES);
    const b = scoreWallet(flipped, DEFAULT_RULES);
    expect(b.roi30d).toBe(a.roi30d);
    expect(b.oneHitWonderPenalty).toBe(a.oneHitWonderPenalty);
    expect(b.copyabilityScore).toBe(a.copyabilityScore);
  });

  it("moves category bucket win rates with the same predicate", () => {
    const bucket = [
      trade({ won: false, pnl: 40 }), // profitable exit, token lost -> not a bucket win
      trade({ won: true, pnl: -20 }),
    ];
    const s = scoreWallet(bucket, DEFAULT_RULES);
    expect(s.categoryStrengths.sports.trades).toBe(2);
    expect(s.categoryStrengths.sports.winRate).toBe(0.5);
    expect(s.categoryStrengths.sports.pnl).toBe(20);
  });

  it("keeps the admission-relevant status monotone in the settlement rate", () => {
    const winners = Array.from({ length: 12 }, () => trade({ won: true, pnl: 40 }));
    const losers = Array.from({ length: 12 }, () => trade({ won: false, pnl: -30 }));
    expect(walletStatus(scoreWallet(winners, DEFAULT_RULES), DEFAULT_RULES).status).toBe("track");
    expect(walletStatus(scoreWallet(losers, DEFAULT_RULES), DEFAULT_RULES).status).toBe("ignore");
  });
});

describe("consistencyScore — a sample with no knowable outcome contributes no wins", () => {
  it("scores an all-unknown sample below the same sample with settled wins", () => {
    const unknown = Array.from({ length: 6 }, () => trade({ won: undefined, pnl: 20 }));
    const known = Array.from({ length: 6 }, () => trade({ won: true, pnl: 20 }));
    expect(consistencyScore(known)).toBeGreaterThan(consistencyScore(unknown));
  });
});
