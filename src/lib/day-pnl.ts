/**
 * C-200 day-PnL summariser — "Today's PnL" and "Yesterday's PnL" cards
 * (2026-09-11).
 *
 * Two different numbers get called "today's PnL" on the Overview page, and they
 * must not be confused:
 *
 *   realized   — PnL booked in the day window on trades that finished in it
 *                (status closed|resolved, bucketed by closedAt ?? resolvedAt).
 *                TR-15 (2026-09-03) early exits only carry closedAt. This is
 *                the number the daily-loss breaker, the phase ladder ("7
 *                consecutive days at goal") and the EOD report all key off.
 *   openMtm    — live mark on positions still open (PaperTrade.unrealizedPnl).
 *                Cumulative, not a daily move: it is the whole open book.
 *
 * `combinedTodayPnl` reproduces the historical Goal-Trajectory figure
 * (realized + residual unrealized on today's finished rows + open MTM) so that
 * refactoring onto this module cannot silently move the number the user has
 * been reading.
 *
 * Day windows are LOCAL calendar days (the ladder buckets the same way, via
 * c200DayKey) and they are immutable once they end: src/lib/paper.ts stamps
 * `closedAt`/`resolvedAt` with `new Date()` at run time, so no code writes into
 * a past day.
 */

export type FinishedRow = {
  realizedPnl: number | null;
  unrealizedPnl?: number | null;
  venue?: string | null;
  closedAt?: Date | null;
  resolvedAt?: Date | null;
};

export type TodayVenueSplit = { venue: string; realized: number; count: number };

export type DayPnlSummary = {
  /** realizedPnl booked in the window (includes TR-15 early exits) */
  realized: number;
  /** unrealizedPnl lingering on rows that finished in the window (normally 0) */
  residualUnrealized: number;
  closedCount: number;
  wins: number;
  losses: number;
  scratch: number;
  best: number;
  worst: number;
  byVenue: TodayVenueSplit[];
};

/**
 * Which day an end-of-day report should cover: today once we are past noon,
 * otherwise the day that just ended. Lets one rule serve both a 22:00 schedule
 * and a post-midnight 00:0x schedule without a midnight race (a 00:05 run must
 * still report yesterday, not the two minutes of the new day).
 */
export function reportDayOffset(now: Date = new Date()): number {
  return now.getHours() < 12 ? -1 : 0;
}

/** Local calendar-day window. offsetDays: 0 = today, -1 = yesterday. */
export function dayWindow(offsetDays: number, now: Date = new Date()): { start: Date; end: Date } {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() + offsetDays);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  return { start, end };
}

/** A trade's booking timestamp: realized books at closedAt for early exits. */
export function finishedAt(row: FinishedRow): Date | null {
  return row.closedAt ?? row.resolvedAt ?? null;
}

/** Rows whose booking timestamp falls in [start, end). */
export function rowsFinishedIn<T extends FinishedRow>(rows: T[], start: Date, end: Date): T[] {
  return rows.filter((row) => {
    const ts = finishedAt(row);
    return ts != null && ts >= start && ts < end;
  });
}

export function summarizeDayPnl(rows: FinishedRow[]): DayPnlSummary {
  let realized = 0;
  let residualUnrealized = 0;
  let wins = 0;
  let losses = 0;
  let scratch = 0;
  let best = 0;
  let worst = 0;
  const venues = new Map<string, TodayVenueSplit>();

  for (const row of rows) {
    const pnl = row.realizedPnl ?? 0;
    realized += pnl;
    residualUnrealized += row.unrealizedPnl ?? 0;

    if (pnl > 0) wins++;
    else if (pnl < 0) losses++;
    else scratch++;

    if (pnl > best) best = pnl;
    if (pnl < worst) worst = pnl;

    const venue = row.venue && row.venue.length > 0 ? row.venue : "unknown";
    const existing = venues.get(venue) ?? { venue, realized: 0, count: 0 };
    existing.realized += pnl;
    existing.count += 1;
    venues.set(venue, existing);
  }

  return {
    realized,
    residualUnrealized,
    closedCount: rows.length,
    wins,
    losses,
    scratch,
    best,
    worst,
    byVenue: [...venues.values()].sort((a, b) => b.realized - a.realized),
  };
}

/** Goal-Trajectory figure: realized + today's residual unrealized + open MTM. */
export function combinedTodayPnl(summary: DayPnlSummary, openMtm: number): number {
  return summary.realized + summary.residualUnrealized + openMtm;
}
