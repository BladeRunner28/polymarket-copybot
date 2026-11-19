/**
 * Tests for the frozen-dataset drift localiser (card `export-reconciliation-localisable`).
 *
 * The thing under test is a CLAIM, not a formula: that a sum-level "DRIFT" can be attributed to
 * named positions using the frozen artifact's own per-position fee columns. So the arms are chosen
 * to break the claim, not to decorate it — a round-trip through the fee parabola, a row that must
 * NOT be called moved, a row moved only in its fee leg, and the scope rule that keeps venue-rate
 * rows out of a proxy-priced baseline.
 */

import { describe, it, expect } from "vitest";
import {
  DELTA_TOLERANCE,
  deltaOf,
  impliedExitMarks,
  localiseFrozenPositions,
  parseFrozenCsv,
  parseFrozenLine,
  summariseDeltas,
  type CurrentPosition,
  type FrozenPosition,
} from "../src/lib/decision-dataset-drift";

const HEADER =
  "trade_id,bot_id,venue,rule_set_version,decision,opened_at,closed_at,wallet,market_id,outcome,side," +
  "market_question,entry_price,size_usd,ttr_hours,raw_spread,raw_liquidity,raw_volume,snapshot_at," +
  "copy_score,confidence,wallet_quality_score,category_fit_score,entry_timing_score,spread_score," +
  "liquidity_score,thesis_score,detected_price,wallet_entry_price,observed_size_usd,y_win,pnl_gross," +
  "pnl_net_entry,pnl_net_full,fee_rate,fee_entry_usd,fee_exit_usd,time_to_resolution_flag";

/** One frozen CSV line: 10 shares at 0.50, rate 0.05, closed at 0.40. */
function frozenLine(over: { id?: string; gross?: number; feeExit?: number; rate?: number; entry?: number; size?: number } = {}): string {
  const entry = over.entry ?? 0.5;
  const size = over.size ?? 5;
  const rate = over.rate ?? 0.05;
  const gross = over.gross ?? 1.0;
  const feeEntry = (size / entry) * rate * entry * (1 - entry);
  const feeExit = over.feeExit ?? 0;
  return [
    over.id ?? "t1", "STANDARD", "Polymarket", "2", "paper_copy", "2026-07-15T00:00:00Z",
    "2026-07-16T00:00:00Z", "0xabc", "mkt-1", "YES", "BUY", "Will X happen?",
    String(entry), String(size), "", "", "", "", "2026-07-15T00:00:00Z",
    "70", "0.6", "70", "0", "90", "90", "100", "90", "0.5", "0.5", "6", "1",
    String(gross), String(gross - feeEntry), String(gross - feeEntry - feeExit), String(rate),
    feeEntry.toFixed(4), feeExit.toFixed(4), "",
  ].join(",");
}

const currentOf = (f: FrozenPosition, over: Partial<CurrentPosition> = {}): CurrentPosition => ({
  tradeId: f.tradeId,
  marketId: f.marketId,
  status: "resolved",
  entryPrice: f.entryPrice,
  sizeUsd: f.sizeUsd,
  realizedPnl: f.pnlGross,
  feeRate: f.feeRate,
  feeRateSource: "proxy",
  feeEntryUsd: f.feeEntryUsd,
  feeExitUsd: f.feeExitUsd,
  pnlNetEntry: f.pnlNetEntry,
  pnlNetFull: f.pnlNetFull,
  ...over,
});

describe("parseFrozenLine", () => {
  it("reads the columns the localisation depends on, by position", () => {
    const row = parseFrozenLine(frozenLine())!;
    expect(row.tradeId).toBe("t1");
    expect(row.marketId).toBe("mkt-1");
    expect(row.entryPrice).toBe(0.5);
    expect(row.sizeUsd).toBe(5);
    expect(row.pnlGross).toBe(1);
    expect(row.feeRate).toBe(0.05);
    expect(row.closedAt).toBe("2026-07-16T00:00:00Z");
  });

  it("refuses a short line instead of padding it (a misaligned row would invent drift)", () => {
    expect(parseFrozenLine("t1,STANDARD,Polymarket")).toBeNull();
  });

  it("skips the header and counts unparsable lines", () => {
    const { positions, unparsed } = parseFrozenCsv(`${HEADER}\n${frozenLine()}\nshort,line\n`);
    expect(positions).toHaveLength(1);
    expect(unparsed).toBe(1);
  });
});

describe("impliedExitMarks", () => {
  it("recovers the mark the artifact was priced against", () => {
    const shares = 100;
    const rate = 0.05;
    const p = 0.37;
    const fee = shares * rate * p * (1 - p);
    const marks = impliedExitMarks(fee, shares, rate)!;
    // Two roots of p(1-p); the pair must contain the true mark and its complement.
    expect(marks).toHaveLength(2);
    expect(marks!.some((m) => Math.abs(m - p) < 1e-4)).toBe(true);
    expect(marks!.some((m) => Math.abs(m - (1 - p)) < 1e-4)).toBe(true);
  });

  it("returns null for a settled row (no exit fee was ever charged)", () => {
    expect(impliedExitMarks(0, 100, 0.05)).toBeNull();
  });

  it("returns null rather than guessing when the fee is outside the parabola", () => {
    expect(impliedExitMarks(100, 1, 0.05)).toBeNull();
  });
});

describe("deltaOf / summariseDeltas", () => {
  it("calls an unchanged row 'none' (the tolerance is not a free pass for noise above it)", () => {
    const f = parseFrozenLine(frozenLine())!;
    const d = deltaOf(f, currentOf(f, { realizedPnl: f.pnlGross + DELTA_TOLERANCE / 2 }));
    expect(d.cause).toBe("none");
  });

  it("separates a gross restatement from a fee-only restatement", () => {
    const f = parseFrozenLine(frozenLine())!;
    expect(deltaOf(f, currentOf(f, { realizedPnl: f.pnlGross + 10 })).cause).toBe("gross");
    expect(deltaOf(f, currentOf(f, { feeExitUsd: f.feeExitUsd + 1, pnlNetFull: f.pnlNetFull - 1 })).cause).toBe("fee");
  });

  it("sums to the drift and states how concentrated it is", () => {
    const a = parseFrozenLine(frozenLine({ id: "a" }))!;
    const b = parseFrozenLine(frozenLine({ id: "b" }))!;
    const s = summariseDeltas([
      deltaOf(a, currentOf(a, { realizedPnl: a.pnlGross + 9, pnlNetFull: a.pnlNetFull + 9 })),
      deltaOf(b, currentOf(b, { realizedPnl: b.pnlGross + 1, pnlNetFull: b.pnlNetFull + 1 })),
    ]);
    expect(s.moved).toBe(2);
    expect(s.sum.dGross).toBeCloseTo(10, 6);
    expect(s.topSharePct).toBeCloseTo(90, 4);
  });
});

describe("localiseFrozenPositions", () => {
  it("keeps venue-rate rows out of a proxy-priced baseline and names what is missing", () => {
    const a = parseFrozenLine(frozenLine({ id: "a" }))!;
    const b = parseFrozenLine(frozenLine({ id: "b" }))!;
    const c = parseFrozenLine(frozenLine({ id: "c" }))!;
    const loc = localiseFrozenPositions([a, b, c], (id) => {
      if (id === "a") return currentOf(a, { realizedPnl: a.pnlGross + 5 });
      if (id === "b") return currentOf(b, { feeRateSource: "venue" });
      return null;
    });
    expect(loc.deltas.map((d) => d.tradeId)).toEqual(["a"]);
    expect(loc.truthExcluded).toBe(1);
    expect(loc.missing).toEqual(["c"]);
    expect(loc.summary.moved).toBe(1);
    expect(loc.summary.sum.dGross).toBeCloseTo(5, 6);
  });

  it("reports a rate-basis change instead of silently re-pricing it as drift", () => {
    const a = parseFrozenLine(frozenLine({ id: "a" }))!;
    const loc = localiseFrozenPositions([a], () => currentOf(a, { feeRate: 0.07 }));
    expect(loc.rateChanged).toBe(1);
    expect(loc.summary.moved).toBe(0);
  });
});
