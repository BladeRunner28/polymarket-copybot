/**
 * 2026-10-11 (card drift-shadow-instrument-defects) — the drift feed must be
 * readable per OPPORTUNITY, not per poll.
 *
 * Defect this pins: `summarizeDrift` counted one "trade" per candidate ROW, and
 * src/lib/shadow-drift.ts appends a row on every 10-minute scan while a market
 * stays drifted. Measured on the live file: 26,928 candidate rows collapse to
 * 9,075 distinct copy signals (marketId|outcome|wallet) and 3,550 settled, with
 * one market (`lal-bet-get-2026-09-17-bet`) contributing 428 rows on its own —
 * so the published `avgPnlPerTradeExDust` answered "what did the average POLL of
 * a blocked market return" (+$0.29) rather than "what would the average blocked
 * COPY have returned" (+$1.20 on the same rows). Both conditions of the
 * pre-registered 2026-09-20 decay bar read that number.
 *
 * These tests pin: the dedupe key and which poll wins (the EARLIEST — the
 * decision the gate actually made, and the price a relaxed tolerance would have
 * paid), that the two bases differ exactly as the defect predicts, that the dust
 * floor and the trailing-7d cohort apply on the per-signal basis too, and the
 * shared streak rule the two bar readings now both use.
 */

import { describe, it, expect } from "vitest";
import {
  dedupeSignals,
  consecutiveDaysAtOrBelow,
  summarizeDrift,
} from "../src/lib/shadow-drift";

const NOW = new Date().toISOString();
const RECENT = (minutesAgo: number) =>
  new Date(Date.now() - minutesAgo * 60_000).toISOString();

function candidate(over: Record<string, unknown>): Record<string, unknown> {
  return {
    type: "candidate",
    ts: NOW,
    marketId: "m",
    outcome: "YES",
    wallet: "w",
    currentPrice: 0.5,
    stakeUsd: 10,
    copyScore: 60,
    confidence: 0,
    rawConfidence: 0.8,
    ...over,
  };
}

function resolveRow(marketId: string, outcome: string, value: number): Record<string, unknown> {
  return { type: "resolve", ts: NOW, marketId, outcome, value };
}

describe("dedupeSignals", () => {
  it("keys on marketId|outcome|wallet and keeps the EARLIEST poll", () => {
    const rows = [
      candidate({ ts: "2026-10-01T00:30:00.000Z", currentPrice: 0.7 }),
      candidate({ ts: "2026-10-01T00:10:00.000Z", currentPrice: 0.5 }),
      candidate({ ts: "2026-10-01T00:20:00.000Z", currentPrice: 0.6 }),
    ];
    const out = dedupeSignals(rows);
    expect(out.size).toBe(1);
    const picked = [...out.values()][0];
    expect(picked.ts).toBe("2026-10-01T00:10:00.000Z");
    expect(picked.currentPrice).toBe(0.5);
  });

  it("treats a different wallet or outcome as a different signal", () => {
    const rows = [
      candidate({ ts: "2026-10-01T00:10:00.000Z", wallet: "w1" }),
      candidate({ ts: "2026-10-01T00:11:00.000Z", wallet: "w2" }),
      candidate({ ts: "2026-10-01T00:12:00.000Z", outcome: "NO" }),
    ];
    expect(dedupeSignals(rows).size).toBe(3);
  });

  it("ignores resolve rows", () => {
    expect(dedupeSignals([resolveRow("m", "YES", 1)]).size).toBe(0);
  });
});

describe("summarizeDrift — poll-row basis vs per-signal basis", () => {
  // M1 polled three times (a market that stays drifted), M2 once, M3 is dust.
  const rows = [
    candidate({ ts: RECENT(50), marketId: "m1", outcome: "YES", wallet: "w1", currentPrice: 0.5 }),
    candidate({ ts: RECENT(40), marketId: "m1", outcome: "YES", wallet: "w1", currentPrice: 0.6 }),
    candidate({ ts: RECENT(30), marketId: "m1", outcome: "YES", wallet: "w1", currentPrice: 0.7 }),
    candidate({ ts: RECENT(20), marketId: "m2", outcome: "NO", wallet: "w2", currentPrice: 0.4 }),
    candidate({
      ts: RECENT(10),
      marketId: "m3",
      outcome: "YES",
      wallet: "w3",
      currentPrice: 0.05,
      rawConfidence: null,
    }),
    resolveRow("m1", "YES", 1),
    resolveRow("m2", "NO", 0),
    resolveRow("m3", "YES", 1),
  ];
  const s = summarizeDrift(rows);

  it("counts every poll row on the original basis", () => {
    expect(s.candidates).toBe(5);
    expect(s.marked).toBe(5);
    expect(s.dustExcluded).toBe(1);
    // poll mean: (10 + 6.6667 + 4.2857 + (-10)) / 4 = +2.738
    expect(s.avgPnlPerTradeExDust).toBe(2.74);
  });

  it("counts one row per signal on the instrument-v2 basis", () => {
    expect(s.signals).toBe(3);
    expect(s.signalsSettled).toBe(3);
    expect(s.dustExcludedPerSignal).toBe(1);
    // earliest polls only: M1 @0.5 -> +10, M2 @0.4 -> -10 => mean 0
    expect(s.avgPnlPerTradeExDustPerSignal).toBe(0);
  });

  it("the two bases differ — the defect this card fixes", () => {
    expect(s.avgPnlPerTradeExDustPerSignal).not.toBe(s.avgPnlPerTradeExDust);
  });

  it("applies the same dust floor and trailing-7d cohort per signal", () => {
    expect(s.cohort7dMarkedPerSignal).toBe(2);
    expect(s.avgPnlPerTradeExDustLast7dCohortPerSignal).toBe(0);
    expect(s.cohort7dMarked).toBe(4);
  });

  it("counts rows carrying rawConfidence (instrument v2 rows only)", () => {
    expect(s.rawConfidenceRows).toBe(4);
  });
});

describe("consecutiveDaysAtOrBelow", () => {
  const day = (d: string, v: number | null) => ({ day: d, avgPnlPerTradeExDust: v });

  it("counts the run at the END of the deduped series", () => {
    const series = [
      day("2026-10-05", 0.52),
      day("2026-10-06", 0.39),
      day("2026-10-07", 0.39),
      day("2026-10-08", 0.38),
      day("2026-10-09", 0.38),
      day("2026-10-10", -0.26),
      day("2026-10-11", 0.17),
    ];
    expect(consecutiveDaysAtOrBelow(series, 0.5)).toBe(6);
  });

  it("breaks on the first day above the bar and on a null reading", () => {
    expect(
      consecutiveDaysAtOrBelow([day("2026-10-09", 0.1), day("2026-10-10", 0.9), day("2026-10-11", 0.1)], 0.5)
    ).toBe(1);
    expect(
      consecutiveDaysAtOrBelow([day("2026-10-09", 0.1), day("2026-10-10", null), day("2026-10-11", 0.1)], 0.5)
    ).toBe(1);
  });

  it("returns 0 for an empty series", () => {
    expect(consecutiveDaysAtOrBelow([], 0.5)).toBe(0);
  });
});
