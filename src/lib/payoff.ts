/**
 * The payoff companions — win rate, average win, average loss and ROI on ONE population.
 *
 * Card `winrate-payoff-companion-reporting` (2026-11-03). WHY: on 2026-10-27 a win-rate drop was
 * read as a profitability collapse. It was neither. Win rate fell 71.7% (Jul) -> 41.2% (Oct) while
 * ROI rose to the best month on record, because average win went $6.67 -> $23.30 against average
 * loss -$9.05 -> -$12.80. A win rate printed alone cannot separate that from a collapse, in either
 * direction — so every block that prints one prints these three beside it, from the SAME rows.
 *
 * Single source of truth: `src/lib/report.ts` (EOD), `src/lib/rule-updater.ts` (rule-change
 * evidence), `src/app/page.tsx` (dashboard home) and `scripts/research-collect.py` (fact sheet)
 * all call THIS function or its Python twin, so the four surfaces cannot drift apart.
 *
 * Pure: no DB, no clock of its own. The caller supplies the rows and (optionally) the date format,
 * because the EOD report prints local-calendar dates while the other surfaces print UTC.
 */
export type Payoff = {
  n: number;
  wins: number;
  winRate: number;
  avgWin: number;
  avgLoss: number;
  roi: number;
  cost: number;
  since: Date | null;
};

/** One settled leg: realized PnL, the stake it was staked at, and when it settled. */
export type PayoffRow = { pnl: number | null; stake: number | null; at: Date | null };

/**
 * Win rate and companions from the same rows, at the same level (the leg), on the same clock
 * (the caller's settlement clock). A zero-PnL leg counts as a NON-win, exactly as the win rate
 * does — if the two denominators disagreed, avg loss would silently drop the flat legs.
 */
export function payoffSummary(rows: PayoffRow[]): Payoff {
  const pnlOf = (r: PayoffRow) => r.pnl ?? 0;
  const wins = rows.filter((r) => pnlOf(r) > 0);
  const nonWins = rows.filter((r) => pnlOf(r) <= 0);
  const total = rows.reduce((a, r) => a + pnlOf(r), 0);
  // `stake` null/absent is NOT zero-cost: `cost` stays 0 and ROI is reported as n/a, never 0%.
  const cost = rows.reduce((a, r) => a + (r.stake ?? 0), 0);
  let since: Date | null = null;
  for (const r of rows) {
    if (r.at && (!since || r.at < since)) since = r.at;
  }
  return {
    n: rows.length,
    wins: wins.length,
    winRate: rows.length ? wins.length / rows.length : 0,
    avgWin: wins.length ? wins.reduce((a, r) => a + pnlOf(r), 0) / wins.length : 0,
    avgLoss: nonWins.length ? nonWins.reduce((a, r) => a + pnlOf(r), 0) / nonWins.length : 0,
    roi: cost ? (100 * total) / cost : 0,
    cost,
    since,
  };
}

const signed = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.abs(n).toFixed(2)}`;

/**
 * The companion fragment: clock + population + level, then average win, average loss and ROI.
 * Rendered on the SAME LINE as the win rate it accompanies, so no reader can lift the rate off
 * the line without the three numbers that make it readable.
 */
export function payoffCompanionText(p: Payoff, fmtDate: (d: Date) => string = isoDate): string {
  if (!p.n) return `no settled legs yet — win rate is undefined here, not 0%`;
  const since = p.since ? `, since ${fmtDate(p.since)}` : "";
  const roi = p.cost
    ? `ROI ${p.roi >= 0 ? "+" : ""}${p.roi.toFixed(1)}% on $${Math.round(p.cost).toLocaleString("en-US")} cost`
    : `ROI n/a (no stake recorded)`;
  return (
    `LIFETIME settled, level=leg, n=${p.n.toLocaleString("en-US")}${since} | ` +
    `avg win ${signed(p.avgWin)} / avg loss ${signed(p.avgLoss)} / ${roi}`
  );
}

export const isoDate = (d: Date) => d.toISOString().slice(0, 10);
