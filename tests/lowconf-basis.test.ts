/**
 * 2026-10-26 (self-audit) — the lowconf counterfactual must be readable per COPY, not per poll.
 *
 * Defect this pins: `summarizeLowConf` counted one "bet" per candidate ROW and printed the
 * result as "$X @ $10/trade ... N settled". src/lib/shadow-lowconf.ts appends a row on every
 * scan while a refused market stays refused, so on the live file 24,958 candidate rows were
 * really 4,943 copy signals (marketId|outcome|wallet) on 4,240 markets — one triple logged
 * 363 times — and the headline $545,126 at one ticket per signal is $362,939 (1.50x). The
 * same defect was fixed for the DRIFT shadow on 2026-10-11 (card
 * drift-shadow-instrument-defects, 26,928 rows -> 9,075 signals).
 *
 * These tests pin the LEVEL basis: the signal key matches shadow-drift.dedupeSignals
 * (marketId|outcome|wallet), the EARLIEST row wins (the decision the gate actually made),
 * row-level fields are untouched, and an empty feed cannot look like a clean read.
 */

import { describe, it, expect } from "vitest";
import { summarizeLowConf } from "../src/lib/shadow-lowconf";

const RESOLVE = (marketId: string, outcome: string, value: number, ts: string) => ({
  ts,
  type: "resolve",
  marketId,
  outcome,
  value,
});

const CAND = (
  marketId: string,
  outcome: string,
  wallet: string,
  price: number,
  ts: string
) => ({
  ts,
  type: "candidate",
  marketId,
  outcome,
  wallet,
  currentPrice: price,
  band: "0-0.2",
  confidenceBucket: "<0.40",
  rawConfidence: 0.2,
  stakeUsd: 10,
  confidenceOnly: true,
});

describe("lowconf shadow — LEVEL basis", () => {
  // One market, one wallet, three polls: 0.02 -> 0.04 -> 0.05, resolving to 1.
  // Row-level sums all three tickets (+$490 + $240 + $190 = +$920);
  // per signal it is the EARLIEST (+$490); per market also the earliest (+$490).
  const rows = [
    RESOLVE("m1", "YES", 1, "2026-10-20T00:00:00.000Z"),
    CAND("m1", "YES", "w1", 0.02, "2026-10-19T00:00:00.000Z"),
    CAND("m1", "YES", "w1", 0.04, "2026-10-19T01:00:00.000Z"),
    CAND("m1", "YES", "w1", 0.05, "2026-10-19T02:00:00.000Z"),
  ];

  it("counts rows as bets and collapses them to signals/markets", () => {
    const s = summarizeLowConf(rows);
    expect(s.marked).toBe(3);
    expect(s.basis.bets).toBe(3);
    expect(s.basis.signals).toBe(1);
    expect(s.basis.markets).toBe(1);
  });

  it("per-signal basis takes the EARLIEST poll, not the sum of polls", () => {
    const s = summarizeLowConf(rows);
    expect(s.wouldHavePnl).toBeCloseTo(920, 6); // row level: all three tickets
    expect(s.basis.wouldHavePnlPerSignal).toBeCloseTo(490, 6); // (1 - 0.02) / 0.02 * 10
    expect(s.basis.wouldHavePnlOneBetPerMarket).toBeCloseTo(490, 6);
  });

  it("keeps two wallets on one market as two signals but one market", () => {
    const s = summarizeLowConf([
      ...rows,
      CAND("m1", "YES", "w2", 0.04, "2026-10-19T03:00:00.000Z"),
    ]);
    expect(s.basis.signals).toBe(2);
    expect(s.basis.markets).toBe(1);
    expect(s.basis.wouldHavePnlPerSignal).toBeCloseTo(490 + 240, 6);
  });

  it("an unresolved feed reports zero marked bets, never a clean win/loss", () => {
    const s = summarizeLowConf([CAND("m2", "NO", "w1", 0.3, "2026-10-19T00:00:00.000Z")]);
    expect(s.marked).toBe(0);
    expect(s.candidates).toBe(1);
    expect(s.basis.bets).toBe(0);
    expect(s.basis.signals).toBe(0);
    expect(s.winRate).toBeNull();
    expect(s.awaitingResolution).toBe(1);
  });
});
