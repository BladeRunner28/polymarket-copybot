/**
 * Day-scoped payoff (2026-11-17 self-audit, /reports).
 *
 * Guards the two things that made the Reports card lie: the day rate must be
 * computed from the day's OWN settled legs (not a lifetime denominator), and the
 * bucket key must be the same local calendar day the EOD report stamps.
 */

import { describe, it, expect } from "vitest";
import { bucketByDayAndBot, dayPayoff, localDayKey } from "../src/lib/day-pnl";

const at = (iso: string) => new Date(iso);

describe("day-scoped payoff", () => {
  it("buckets by local day AND lane, on closedAt ?? resolvedAt", () => {
    const rows = [
      // early exit: closedAt only (TR-15)
      { botId: "STANDARD", realizedPnl: 5, simulatedPositionSize: 10, closedAt: at("2026-11-16T20:00:00"), resolvedAt: null },
      // natural resolution: resolvedAt only
      { botId: "STANDARD", realizedPnl: -5, simulatedPositionSize: 10, closedAt: null, resolvedAt: at("2026-11-16T22:00:00") },
      { botId: "BANKROLL_200", realizedPnl: 1, simulatedPositionSize: 10, closedAt: at("2026-11-16T23:00:00"), resolvedAt: null },
      { botId: "STANDARD", realizedPnl: 9, simulatedPositionSize: 10, closedAt: at("2026-11-15T12:00:00"), resolvedAt: null },
      // no timestamp at all: cannot be placed in a day, must not enter one
      { botId: "STANDARD", realizedPnl: 100, simulatedPositionSize: 10, closedAt: null, resolvedAt: null },
    ];
    const b = bucketByDayAndBot(rows);
    expect(b.get("2026-11-16|STANDARD")?.length).toBe(2);
    expect(b.get("2026-11-16|BANKROLL_200")?.length).toBe(1);
    expect(b.get("2026-11-15|STANDARD")?.length).toBe(1);
    // the undated row is in NO bucket
    expect([...b.values()].reduce((n, l) => n + l.length, 0)).toBe(4);
  });

  it("day rate uses the day's denominator, not a lifetime one", () => {
    const win = { botId: "STANDARD", realizedPnl: 5, simulatedPositionSize: 10, closedAt: at("2026-11-16T10:00:00"), resolvedAt: null };
    const loss = { botId: "STANDARD", realizedPnl: -5, simulatedPositionSize: 10, closedAt: at("2026-11-16T11:00:00"), resolvedAt: null };
    const day = dayPayoff([win, loss]);
    expect(day.n).toBe(2);
    expect(day.winRate).toBe(0.5);
    expect(day.roi).toBeCloseTo(0, 10);
    // a zero-PnL leg is a NON-win, exactly as payoffSummary defines it
    const flat = { botId: "STANDARD", realizedPnl: 0, simulatedPositionSize: 10, closedAt: at("2026-11-16T12:00:00"), resolvedAt: null };
    expect(dayPayoff([win, flat]).winRate).toBe(0.5);
  });

  it("an empty day has n=0 and winRate 0 — the page must print 'no settled leg', never 0%", () => {
    const empty = dayPayoff([]);
    expect(empty.n).toBe(0);
    expect(empty.winRate).toBe(0);
  });

  it("localDayKey is the local calendar date, not the UTC one", () => {
    // 2026-11-16 20:00 local: the UTC date can differ either side of midnight,
    // which is exactly how a day bucket drifts from the report's own date label.
    expect(localDayKey(at("2026-11-16T20:00:00"))).toBe("2026-11-16");
    expect(localDayKey(at("2026-01-02T00:30:00"))).toBe("2026-01-02");
  });
});
