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
 *
 * 2026-11-03 (winrate-payoff-companion-reporting): the companions used to be a SECOND line, so a caller
 * (or a reader) could print/repeat the rate without them — and the dashboard, the rule-change evidence
 * and the fact sheet all did exactly that. They now ride on the SAME line, from the SAME rows, via
 * src/lib/payoff.ts, which every surface shares. The tests below pin the one-line invariant.
 */

import { describe, it, expect } from "vitest";
import { payoffStats, winRateLine } from "../src/lib/report";
import { payoffSummary, payoffCompanionText } from "../src/lib/payoff";
import { proposeRuleChanges } from "../src/lib/rule-updater";
import { DEFAULT_RULES } from "../src/lib/rules";

type Row = {
  realizedPnl: number | null;
  simulatedPositionSize: number;
  closedAt: Date | null;
  resolvedAt: Date | null;
};

// Noon UTC, not midnight: the EOD report renders `since` on the LOCAL calendar (localDate), so a
// midnight-UTC fixture would print the previous day in any negative-offset zone and the assertion
// would be testing the test's timezone instead of the label.
const row = (pnl: number, ntl: number, d = new Date("2026-07-15T12:00:00Z")): Row => ({
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
    expect(winRateLine(p, 12)).toMatch(/undefined here, not 0%/);
  });

  it("is the same arithmetic every other surface uses (one source of truth)", () => {
    const rows = [row(10, 100), row(-30, 100), row(-30, 100)];
    const viaReport = payoffStats(rows);
    const viaPayoff = payoffSummary(rows.map((r) => ({ pnl: r.realizedPnl, stake: r.simulatedPositionSize, at: r.closedAt ?? r.resolvedAt })));
    expect(viaPayoff).toEqual(viaReport);
  });
});

describe("winRateLine: the rate cannot be printed without its companions", () => {
  const p = payoffStats([row(10, 100), row(-30, 100), row(-30, 100)]);

  it("names the clock, the population and the level on the rate's own line", () => {
    const line = winRateLine(p, 469);
    expect(line).toContain("LIFETIME settled");
    expect(line).toContain("level=leg");
    expect(line).toContain("n=3");
    expect(line).toContain("since 2026-07-15");
    // the old line said only "Win Rate: 33.3% | Open Positions: N" — no clock, no n
    expect(line).not.toMatch(/^• Win Rate: [\d.]+% \| Open Positions/);
  });

  it("prints average win, average loss and ROI on that same line — not the line below", () => {
    const line = winRateLine(p, 469);
    expect(line).toMatch(/avg win \+\$10\.00/);
    expect(line).toMatch(/avg loss -\$30\.00/);
    expect(line).toMatch(/ROI -16\.7%/);
    expect(line).not.toContain("\n");
  });

  it("does not claim a direction it has not measured", () => {
    expect(winRateLine(p, 469)).not.toMatch(/falling win rate|rising average win/);
  });
});

describe("payoffCompanionText: an unknown stake is n/a, never 0%", () => {
  it("says ROI n/a when no leg carried a stake", () => {
    const p = payoffSummary([{ pnl: 5, stake: null, at: null }, { pnl: -2, stake: null, at: null }]);
    expect(payoffCompanionText(p)).toContain("ROI n/a (no stake recorded)");
    expect(payoffCompanionText(p)).not.toContain("ROI +0.0%");
    expect(payoffCompanionText(p)).toContain("n=2");
  });
});

describe("rule-change evidence: the threshold move carries its payoff", () => {
  it("prints avg win / avg loss / ROI beside the win rate that justified the move", () => {
    const samples = Array.from({ length: 8 }, () => ({
      pnl: -5,
      stake: 20,
      at: new Date("2026-07-20T00:00:00Z"),
      spread: 0.01,
      liquidity: 50_000,
      drift: 0.01,
      walletScore: 70,
    }));
    const proposals = proposeRuleChanges(samples, DEFAULT_RULES);
    const copyBar = proposals.find((p) => p.field === "minCopyScore");
    expect(copyBar).toBeDefined();
    expect(copyBar!.evidence).toContain("win rate 0%");
    expect(copyBar!.evidence).toContain("avg win");
    expect(copyBar!.evidence).toContain("avg loss");
    expect(copyBar!.evidence).toMatch(/ROI -25\.0%/);
  });
});
