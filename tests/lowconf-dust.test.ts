/**
 * 2026-10-31 — the minConfidence counterfactual must not be read through its dust.
 *
 * Defect this pins: `summarizeLowConf` published a dust-inclusive headline. On the live
 * file (27,036 candidate rows, 2026-09-21..2026-10-31, level=market) the dust-inclusive
 * per-market total was +$277,439.50 while the same rows with entries below $0.10 removed
 * total +$6,225.25 — a $0.001 entry that settles at 1.0 returns 9,990x on a $10 ticket and
 * is not executable at any size on this venue. Tuning #29 rec 1 applied exactly this floor
 * to the late-drift feed on 2026-09-19; the minConfidence lane never got it.
 *
 * These tests pin four things: the floor removes the dust (and says how much), it removes
 * it at ALL THREE levels, the banned sub-$0.05 tail stays separately reconcilable, and an
 * all-dust feed reports that fact instead of a clean-looking zero.
 */

import { describe, it, expect } from "vitest";
import {
  summarizeLowConf,
  LOWCONF_DUST_MIN_ENTRY,
  LOWCONF_BANNED_TAIL_MAX,
} from "../src/lib/shadow-lowconf";

const RESOLVE = (marketId: string, outcome: string, value: number) => ({
  ts: "2026-10-20T00:00:00.000Z",
  type: "resolve",
  marketId,
  outcome,
  value,
});

const CAND = (marketId: string, outcome: string, wallet: string, price: number, ts = "2026-10-19T00:00:00.000Z") => ({
  ts,
  type: "candidate",
  marketId,
  outcome,
  wallet,
  currentPrice: price,
  stakeUsd: 10,
  confidenceOnly: true,
});

describe("lowconf shadow — dust floor", () => {
  it("keeps the dust row in the raw total but out of the floored total, and says what it removed", () => {
    // 0.001 -> 1.0 on $10 is +$9,990; 0.50 -> 1.0 is +$10.
    const s = summarizeLowConf([
      RESOLVE("dust", "YES", 1),
      RESOLVE("solid", "YES", 1),
      CAND("dust", "YES", "w1", 0.001),
      CAND("solid", "YES", "w1", 0.5),
    ]);
    expect(s.wouldHavePnl).toBeCloseTo(10000, 6);
    expect(s.dust.rowsExcluded).toBe(1);
    expect(s.dust.rowPnlExcluded).toBeCloseTo(9990, 6);
    expect(s.dust.wouldHavePnl).toBeCloseTo(10, 6);
    expect(s.dust.avgPnlPerTrade).toBeCloseTo(10, 6);
    expect(s.dust.minEntryPrice).toBe(LOWCONF_DUST_MIN_ENTRY);
    expect(s.dust.bannedTailMax).toBe(LOWCONF_BANNED_TAIL_MAX);
  });

  it("applies the floor at the copy and bet levels too, not only to rows", () => {
    const rows = [
      RESOLVE("dust", "YES", 1),
      RESOLVE("solid", "YES", 1),
      CAND("dust", "YES", "w1", 0.001),
      CAND("dust", "YES", "w2", 0.002),
      CAND("solid", "YES", "w1", 0.5),
    ];
    const s = summarizeLowConf(rows);
    expect(s.basis.wouldHavePnlPerSignal).toBeCloseTo(9990 + 4990 + 10, 6);
    expect(s.dust.signalsExcluded).toBe(2);
    expect(s.dust.wouldHavePnlPerSignal).toBeCloseTo(10, 6);
    expect(s.basis.wouldHavePnlOneBetPerMarket).toBeCloseTo(10000, 6);
    expect(s.dust.marketsExcluded).toBe(1);
    expect(s.dust.wouldHavePnlOneBetPerMarket).toBeCloseTo(10, 6);
  });

  it("prices the banned sub-0.05 tail separately so the 2026-10-26 correction stays reconcilable", () => {
    // 0.02 -> 1.0 on $10 is +$490 (the banned tail); 0.08 -> 1.0 is +$115 (dust, but tradable band).
    const s = summarizeLowConf([
      RESOLVE("banned", "YES", 1),
      RESOLVE("thin", "YES", 1),
      CAND("banned", "YES", "w1", 0.02),
      CAND("thin", "YES", "w1", 0.08),
    ]);
    expect(s.dust.bannedTailMarkets).toBe(1);
    expect(s.dust.bannedTailOneBetPerMarket).toBeCloseTo(490, 6);
    // both are below the floor, so the floored bet basis is empty and honest about it
    expect(s.dust.wouldHavePnlOneBetPerMarket).toBeCloseTo(0, 6);
    expect(s.dust.topMarketId).toBeNull();
    expect(s.dust.topMarketShare).toBeNull();
  });

  it("reports the floored total with the ten largest contributors removed", () => {
    // twelve tradable markets, each +$50 (entry 1/6 -> $50 on a $10 ticket): total $600,
    // ex-top-10 $100. Entry 1/6 is above the $0.10 floor, so this is a floored population.
    const rows = [];
    for (let i = 0; i < 12; i++) {
      rows.push(RESOLVE(`m${i}`, "YES", 1), CAND(`m${i}`, "YES", "w1", 1 / 6));
    }
    const s = summarizeLowConf(rows);
    expect(s.dust.wouldHavePnlOneBetPerMarket).toBeCloseTo(600, 6);
    expect(s.dust.wouldHavePnlOneBetPerMarketExTop10).toBeCloseTo(100, 6);
    expect(s.dust.topMarketShare).toBeCloseTo(1 / 12, 6);
    expect(s.dust.topMarketId).not.toBeNull();
  });

  it("an all-dust feed reports zero floored bets, never a clean-looking win", () => {
    const s = summarizeLowConf([
      RESOLVE("d1", "YES", 1),
      RESOLVE("d2", "YES", 0),
      CAND("d1", "YES", "w1", 0.001),
      CAND("d2", "YES", "w1", 0.002),
    ]);
    expect(s.marked).toBe(2);
    expect(s.dust.rowsExcluded).toBe(2);
    expect(s.dust.wouldHavePnl).toBeCloseTo(0, 6);
    expect(s.dust.avgPnlPerTrade).toBeNull();
    expect(s.dust.marketsExcluded).toBe(2);
    expect(s.dust.wouldHavePnlOneBetPerMarket).toBeCloseTo(0, 6);
    expect(s.dust.wouldHavePnlOneBetPerMarketExTop10).toBeCloseTo(0, 6);
    expect(s.dust.topMarketShare).toBeNull();
  });
});
