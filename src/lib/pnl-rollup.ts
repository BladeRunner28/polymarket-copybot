/**
 * Rollup-backed PnL read helpers.
 *
 * These replace the inline `SELECT strftime(...) FROM PnlSnapshot JOIN PaperTrade
 * GROUP BY ...` that /, /performance and /analytics each ran on every request —
 * a full scan of PnlSnapshot (1.99M rows, 159 MB table + 147 MB indexes, ~10s
 * per page load through the dashboard). The aggregate now lives in
 * `PnlHourlyRollup`, maintained by scripts/rollup-pnl-hourly.ts on the hourly
 * update-pnl cron (and every 10 min from the monitor-score cron so the
 * in-progress hour stays fresh).
 *
 * Both helpers return the EXACT shapes the old raw queries returned, so callers
 * did not change beyond the call itself.
 */

import { prisma } from "./db";

export type HourlyPnlRow = { hour: string; botId: string; total_pnl: number };
export type DailyPnlRow = { day: string; botId: string; total_pnl: number };

/**
 * Hourly PnL per bot, `hour` in the same UTC 'YYYY-MM-DD HH:00:00' format the
 * inline strftime produced, ordered by hour ascending (as before).
 */
export async function hourlyPnlSeries(): Promise<HourlyPnlRow[]> {
  const rows = await prisma.pnlHourlyRollup.findMany({ orderBy: { hour: "asc" } });
  return rows.map((r) => ({ hour: r.hour, botId: r.botId, total_pnl: r.totalPnl }));
}

/**
 * Daily PnL per bot — the hourly rollup folded up by UTC date, matching the old
 * `GROUP BY strftime('%Y-%m-%d', ...) ORDER BY day ASC`.
 *
 * NOTE: summing hourly subtotals instead of the raw snapshot rows can differ
 * from the single-pass SUM by float associativity (last bits only; callers
 * round to cents).
 */
export async function dailyPnlSeries(): Promise<DailyPnlRow[]> {
  const rows = await prisma.pnlHourlyRollup.findMany({ orderBy: { hour: "asc" } });
  const acc = new Map<string, number>();
  for (const r of rows) {
    const day = r.hour.slice(0, 10);
    const k = `${day}\u0000${r.botId}`;
    acc.set(k, (acc.get(k) ?? 0) + r.totalPnl);
  }
  return [...acc.entries()]
    .map(([k, total_pnl]) => {
      const [day, botId] = k.split("\u0000");
      return { day, botId, total_pnl };
    })
    .sort((a, b) => (a.day === b.day ? (a.botId < b.botId ? -1 : a.botId > b.botId ? 1 : 0) : a.day < b.day ? -1 : 1));
}
