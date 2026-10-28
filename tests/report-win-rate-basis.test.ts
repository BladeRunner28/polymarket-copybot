/**
 * 2026-10-28 (self-audit) — prereg Part C: a printed win rate must carry its population, clock and payoff.
 *
 * The EOD report printed "• Win Rate: 63.5% | Open Positions: 487" directly under a header that says the
 * report covers one calendar day. 63.5% was a LIFETIME figure, so the label misstated its clock; it
 * carried no n, no average win, no average loss and no ROI, so it could not be told apart from a
 * collapse. Precisely that confusion produced the "large drop in wins" that opened the 2026-10-27 prereg:
 * win rate falls 71.7% (Jul) -> 41.2% (Oct) while ROI rises to the best month in the series, because
 * average win goes $6.67 -> $23.30 against average loss -$9.05 -> -$12.80.
 *
 * Second defect fixed in the same line: neither the open nor the lifetime query scoped isDemo, so
 * "Open Positions: 487" counted 18 seeded demo rows (real book: 469). Every other read script in this
 * repo already scopes on isDemo=0.
 */

import { describe, it, expect } from "vitest";
import { payoffStats, winRateLine, payoffLine } from "../src/lib/report";

type Row = {
  realizedPnl: number | null;
  simulatedPositionSize: number;
  closedAt: Date | null;
  resolvedAt: Date | null;
};

const row = (pnl: number, ntl: number, d = new Date("2026-07-15T00:00:00Z")): Row => ({
  realizedPnl: pnl,
  simulatedPositionSize: ntl,
  closedAt: d,
  resolvedAt: null,
});

describe("payoffStats: the win rate and its companions come from one population", () => {
  it("computes win rate, average win, average loss and ROI on the same rows", () => {
    const p = payoffStats([row(10, 100), row(30, 100), row(-20, 100), row(-40, 100)]);
    expect(p.n).toBe(4);
    expect(p.wins).toBe(2);
    expect(p.winRate).toBeCloseTo(0.5);
    expect(p.avgWin).toBeCloseTo(20);
    expect(p.avgLoss).toBeCloseTo(-30);
    expect(p.cost).toBeCloseTo(400);
    expect(p.roi).toBeCloseTo(-5); // (10+30-20-40)/400
  });

  it("counts a zero-PnL leg as a non-win, the same way the win rate does", () => {
    // if the two denominators disagreed, avg loss would silently exclude flat legs
    const p = payoffStats([row(10, 100), row(0, 100)]);
    expect(p.winRate).toBeCloseTo(0.5);
    expect(p.avgLoss).toBeCloseTo(0);
    expect(p.avgWin + p.avgLoss).toBeCloseTo(10);
  });

  it("reports the earliest settlement, not the earliest opened", () => {
    const a = { ...row(5, 10), closedAt: new Date("2026-09-01T00:00:00Z") };
    const b = { ...row(5, 10), closedAt: null, resolvedAt: new Date("2026-07-15T00:00:00Z") };
    expect(payoffStats([a, b]).since?.toISOString().slice(0, 10)).toBe("2026-07-15");
  });

  it("does not divide by zero on an empty book", () => {
    const p = payoffStats([]);
    expect(p.n).toBe(0);
    expect(p.winRate).toBe(0);
    expect(p.roi).toBe(0);
    expect(payoffLine(p)).toMatch(/undefined here, not 0%/);
  });
});

describe("winRateLine / payoffLine: the label states what it counts", () => {
  const p = payoffStats([row(10, 100), row(-30, 100), row(-30, 100)]);

  it("names the clock and the denominator in the win-rate line", () => {
    const line = winRateLine(p, 469);
    expect(line).toContain("LIFETIME settled");
    expect(line).toContain("n=3");
    // the old line said only "Win Rate: 33.3% | Open Positions: N" — no clock, no n
    expect(line).not.toMatch(/^• Win Rate: [\d.]+% \| Open Positions/);
  });

  it("prints average win, average loss and ROI beside the rate", () => {
    const line = payoffLine(p);
    expect(line).toMatch(/avg win \+\$10\.00/);
    expect(line).toMatch(/avg loss -\$30\.00/);
    expect(line).toMatch(/ROI -16\.7%/);
  });

  it("does not claim a direction it has not measured", () => {
    // the payoff line must not assert that the rate is falling or the average win rising
    expect(payoffLine(p)).not.toMatch(/falling win rate|rising average win/);
  });
});
