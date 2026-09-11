/**
 * C-200 day-PnL summariser tests (Overview cards, 2026-09-11).
 * Guards the invariants that matter: realized is a plain sum of realizedPnl (the
 * figure the daily-loss breaker uses), the window helpers bucket by the same
 * timestamp the ladder uses (closedAt ?? resolvedAt), and the combined figure
 * still matches the historical Goal-Trajectory formula.
 */

import { describe, it, expect } from "vitest";
import {
  summarizeDayPnl,
  combinedTodayPnl,
  dayWindow,
  finishedAt,
  reportDayOffset,
  rowsFinishedIn,
} from "../src/lib/day-pnl";

describe("C-200 day PnL summary", () => {
  it("returns zeros for an empty day", () => {
    const s = summarizeDayPnl([]);
    expect(s).toMatchObject({
      realized: 0,
      residualUnrealized: 0,
      closedCount: 0,
      wins: 0,
      losses: 0,
      scratch: 0,
      best: 0,
      worst: 0,
    });
    expect(s.byVenue).toEqual([]);
    expect(combinedTodayPnl(s, 0)).toBe(0);
  });

  it("splits wins/losses/scratch, finds best+worst and sums realized", () => {
    const s = summarizeDayPnl([
      { realizedPnl: 12.5, venue: "Polymarket" },
      { realizedPnl: -4.25, venue: "Polymarket" },
      { realizedPnl: -59.8, venue: "Kalshi" },
      { realizedPnl: 0, venue: "Polymarket" },
      { realizedPnl: 0.59, venue: "Polymarket" },
      { realizedPnl: null, venue: undefined },
    ]);
    expect(s.realized).toBeCloseTo(-50.96, 6);
    expect(s.closedCount).toBe(6);
    expect(s.wins).toBe(2);
    expect(s.losses).toBe(2);
    expect(s.scratch).toBe(2); // one explicit 0, one null
    expect(s.best).toBeCloseTo(12.5, 6);
    expect(s.worst).toBeCloseTo(-59.8, 6);
  });

  it("groups by venue, sorted by realized, and labels a missing venue", () => {
    const s = summarizeDayPnl([
      { realizedPnl: -10, venue: "Kalshi" },
      { realizedPnl: 4, venue: "Polymarket" },
      { realizedPnl: 6, venue: "Polymarket" },
      { realizedPnl: 1, venue: null },
    ]);
    expect(s.byVenue).toEqual([
      { venue: "Polymarket", realized: 10, count: 2 },
      { venue: "unknown", realized: 1, count: 1 },
      { venue: "Kalshi", realized: -10, count: 1 },
    ]);
  });

  it("keeps the historical combined formula: realized + residual + open MTM", () => {
    const s = summarizeDayPnl([
      { realizedPnl: -59.8, unrealizedPnl: 0, venue: "Polymarket" },
      { realizedPnl: 0.59, unrealizedPnl: 0.25, venue: "Polymarket" },
    ]);
    expect(s.realized).toBeCloseTo(-59.21, 6);
    expect(s.residualUnrealized).toBeCloseTo(0.25, 6);
    // matches page.tsx's previous expression (sum realized + sum unrealized on
    // today's closed rows + open book MTM)
    expect(combinedTodayPnl(s, 573.33)).toBeCloseTo(-59.21 + 0.25 + 573.33, 6);
  });
});

describe("local calendar-day windows", () => {
  const noon = new Date(2026, 8, 11, 12, 30, 0); // Fri 2026-09-11 12:30 local

  it("today's window is [00:00, next 00:00)", () => {
    const { start, end } = dayWindow(0, noon);
    expect([start.getHours(), start.getMinutes(), start.getSeconds()]).toEqual([0, 0, 0]);
    expect(start.getDate()).toBe(11);
    expect(end.getTime() - start.getTime()).toBe(86_400_000);
    expect(end.getDate()).toBe(12);
  });

  it("yesterday's window is exactly one local day earlier", () => {
    const today = dayWindow(0, noon);
    const yest = dayWindow(-1, noon);
    expect(yest.end.getTime()).toBe(today.start.getTime());
    expect(yest.start.getDate()).toBe(10);
  });

  it("walks across a month boundary", () => {
    const { start, end } = dayWindow(-1, new Date(2026, 2, 1, 9, 0, 0)); // Mar 1 local
    expect([start.getMonth(), start.getDate()]).toEqual([1, 28]); // Feb 28
    expect([end.getMonth(), end.getDate()]).toEqual([2, 1]);
  });

  it("picks the day a report should cover: today after noon, else the day just ended", () => {
    expect(reportDayOffset(new Date(2026, 8, 11, 22, 0, 0))).toBe(0);   // 22:00 cron
    expect(reportDayOffset(new Date(2026, 8, 11, 23, 58, 0))).toBe(0);  // 23:5x cron
    expect(reportDayOffset(new Date(2026, 8, 12, 0, 5, 0))).toBe(-1);   // 00:05 cron -> yesterday
    expect(reportDayOffset(new Date(2026, 8, 12, 11, 59, 0))).toBe(-1);
    expect(reportDayOffset(new Date(2026, 8, 12, 12, 0, 0))).toBe(0);
  });

  it("prefers closedAt (TR-15 early exit) over resolvedAt", () => {
    const closed = new Date(2026, 8, 10, 23, 53, 49);
    const resolved = new Date(2026, 8, 11, 0, 30, 0);
    expect(finishedAt({ realizedPnl: 1, closedAt: closed, resolvedAt: resolved })).toBe(closed);
    expect(finishedAt({ realizedPnl: 1, resolvedAt: resolved })).toBe(resolved);
    expect(finishedAt({ realizedPnl: 1, closedAt: undefined })).toBeNull();
  });

  it("buckets a 23:53 close into yesterday and a 00:30 close into today", () => {
    const rows = [
      { realizedPnl: -12, closedAt: new Date(2026, 8, 10, 23, 53, 49) },
      { realizedPnl: 5, resolvedAt: new Date(2026, 8, 11, 0, 30, 0) },
      { realizedPnl: 3, closedAt: new Date(2026, 8, 9, 23, 59, 0) },
    ];
    const yest = dayWindow(-1, noon);
    const today = dayWindow(0, noon);
    expect(rowsFinishedIn(rows, yest.start, yest.end).map((r) => r.realizedPnl)).toEqual([-12]);
    expect(rowsFinishedIn(rows, today.start, today.end).map((r) => r.realizedPnl)).toEqual([5]);
    // a row cannot land in both windows
    expect(rowsFinishedIn(rows, yest.start, yest.end).length + rowsFinishedIn(rows, today.start, today.end).length).toBe(2);
  });
});
