/**
 * Capital accounting for the C-200 book (2026-09-20, user request: "daily
 * deposits into Total Capital").
 *
 * DEFINITIONS — the point of this module is that the two figures below are NOT
 * the same and must never be conflated on a page:
 *
 *   Total Capital (Overview stat) = BotBankroll.principal + C-200 total PnL
 *                                   (realized + OPEN mark-to-market). Moves with
 *                                   marks, so it can fall without a trade closing.
 *   Booked capital (this module)  = seedPrincipal + Σ booked PnL + Σ ledger flows
 *                                   Only finished trades (closed/resolved) and
 *                                   recorded injections move it.
 *
 *   Daily deposit = the capital ADDED on a local calendar day
 *                 = that day's booked PnL + that day's ledger injection.
 *
 * Why the ledger: `BotBankroll.principal` has no history — `prisma/dev.db` is
 * gitignored and nothing logs a principal change, so pre-ledger injections are
 * not reconstructible. `data/capital-ledger.json` records them from now on; the
 * standing principal is seeded once as an `opening` entry (baseline, not a
 * daily bar), and `ledgerGapUsd` flags any principal movement the ledger does
 * not explain.
 *
 * Day bucketing is LOCAL (same boundary the Overview's startOfDay and the EOD
 * report use) and keys finished trades by `closedAt ?? resolvedAt` — early exits
 * carry only `closedAt` (see references/papertrade-timestamp-semantics.md).
 *
 * Pure functions only: plain row objects in, no prisma types, no clock reads
 * (the caller passes `todayMs`). Unit-tested in tests/capital.test.ts.
 */

export interface CapitalLedgerEntry {
  /** Local calendar day, 'YYYY-MM-DD'. */
  date: string;
  /** + = money put in, − = money taken out (sweep/withdrawal). */
  amountUsd: number;
  /**
   * `opening` = the baseline principal already in the book (drawn as the line's
   * start, never as a daily deposit bar). `deposit`/`withdrawal` = a real flow.
   */
  kind: "opening" | "deposit" | "withdrawal";
  note?: string;
}

export interface FinishedTradeRow {
  closedAt: number | null;
  resolvedAt: number | null;
  realizedPnl: number | null;
}

export interface DailyCapitalPoint {
  day: string;
  /** PnL booked by finished trades on this day. */
  booked: number;
  /** Ledger flows on this day (0 unless a deposit/withdrawal is recorded). */
  injected: number;
  /** booked + injected — the day's deposit into Total Capital. */
  deposit: number;
  /** Booked capital at the end of this day. */
  closing: number;
  /** Finished trades booked this day. */
  trades: number;
}

export interface CapitalSeries {
  points: DailyCapitalPoint[];
  seedUsd: number;
  seededOn: string | null;
  /** Capital at the START of the first emitted day. */
  openingUsd: number;
  /** Σ booked PnL inside the emitted window. */
  bookedTotal: number;
  /** Σ ledger flows inside the emitted window. */
  injectedTotal: number;
  /** Capital at the end of the last emitted day. */
  closingUsd: number;
  /** principal − (seed + Σ ALL ledger flows). 0 = principal fully explained. */
  ledgerGapUsd: number;
  warnings: string[];
}

const DAY_MS = 86_400_000;

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** Local calendar day key 'YYYY-MM-DD' for an epoch-ms instant. */
export function localDayKey(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Local midnight (epoch ms) of a 'YYYY-MM-DD' key. Throws on a malformed key. */
export function dayKeyToMs(day: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!m) throw new Error(`dayKeyToMs: bad day key "${day}"`);
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 0, 0, 0, 0);
  return d.getTime();
}

/**
 * The epoch-ms instant a finished trade books at: `closedAt` (early exit) or
 * `resolvedAt` (natural settlement). Returns null when the row carries neither
 * (impossible for a finished row, but callers should not book a phantom day).
 */
export function bookedAtMs(row: FinishedTradeRow): number | null {
  if (row.closedAt !== null && row.closedAt !== undefined) return Number(row.closedAt);
  if (row.resolvedAt !== null && row.resolvedAt !== undefined) return Number(row.resolvedAt);
  return null;
}

/** The `days` local day keys ending on (and including) the day of `todayMs`. */
export function dayWindowKeys(todayMs: number, days: number): string[] {
  if (!Number.isFinite(days) || days < 1) throw new Error(`dayWindowKeys: days must be >= 1, got ${days}`);
  const out: string[] = [];
  for (let i = days - 1; i >= 0; i--) out.push(localDayKey(todayMs - i * DAY_MS));
  return out;
}

export function buildCapitalSeries(opts: {
  /** Standing principal from BotBankroll (C-200). */
  principal: number;
  /** Finished trades (closed/resolved) — pre-filtered by the caller. */
  rows: FinishedTradeRow[];
  ledger: CapitalLedgerEntry[];
  /** How many local days to emit, ending today. */
  days: number;
  todayMs: number;
}): CapitalSeries {
  const { principal, rows, ledger, days, todayMs } = opts;
  const warnings: string[] = [];

  const openings = ledger.filter((e) => e.kind === "opening");
  const flows = ledger.filter((e) => e.kind !== "opening");
  let seedUsd: number;
  let seededOn: string | null;
  if (openings.length > 0) {
    seedUsd = openings.reduce((a, e) => a + e.amountUsd, 0);
    seededOn = openings.map((e) => e.date).sort()[0];
  } else {
    seedUsd = Number.isFinite(principal) ? principal : 0;
    seededOn = null;
    warnings.push(
      "no `opening` entry in data/capital-ledger.json — seeded from the standing principal, so the first day's capital has no dated provenance"
    );
  }

  const keys = dayWindowKeys(todayMs, days);
  const windowStart = dayKeyToMs(keys[0]);
  const windowEnd = dayKeyToMs(keys[keys.length - 1]) + DAY_MS;

  // Bring the book forward to the window start.
  let running = seedUsd;
  for (const r of rows) {
    const ms = bookedAtMs(r);
    if (ms !== null && ms < windowStart) running += r.realizedPnl ?? 0;
  }
  for (const e of flows) {
    if (dayKeyToMs(e.date) < windowStart) running += e.amountUsd;
  }
  const openingUsd = running;

  const byDay = new Map<string, { booked: number; trades: number }>();
  for (const r of rows) {
    const ms = bookedAtMs(r);
    if (ms === null || ms < windowStart || ms >= windowEnd) continue;
    const k = localDayKey(ms);
    const acc = byDay.get(k) ?? { booked: 0, trades: 0 };
    acc.booked += r.realizedPnl ?? 0;
    acc.trades += 1;
    byDay.set(k, acc);
  }
  const injByDay = new Map<string, number>();
  for (const e of flows) {
    const ms = dayKeyToMs(e.date);
    if (ms < windowStart || ms >= windowEnd) continue;
    injByDay.set(e.date, (injByDay.get(e.date) ?? 0) + e.amountUsd);
  }

  const points: DailyCapitalPoint[] = keys.map((day) => {
    const acc = byDay.get(day) ?? { booked: 0, trades: 0 };
    const injected = injByDay.get(day) ?? 0;
    const deposit = acc.booked + injected;
    running += deposit;
    return {
      day,
      booked: round2(acc.booked),
      injected: round2(injected),
      deposit: round2(deposit),
      closing: round2(running),
      trades: acc.trades,
    };
  });

  const ledgerGapUsd = round2(principal - (seedUsd + flows.reduce((a, e) => a + e.amountUsd, 0)));
  if (Math.abs(ledgerGapUsd) > 0.01) {
    warnings.push(
      `principal $${principal.toFixed(2)} is not explained by the ledger (seed $${seedUsd.toFixed(2)} + net flows ` +
        `$${flows.reduce((a, e) => a + e.amountUsd, 0).toFixed(2)}): unexplained $${ledgerGapUsd.toFixed(2)} — ` +
        `record the injection/withdrawal in data/capital-ledger.json`
    );
  }

  return {
    points,
    seedUsd: round2(seedUsd),
    seededOn,
    openingUsd: round2(openingUsd),
    bookedTotal: round2(points.reduce((a, p) => a + p.booked, 0)),
    injectedTotal: round2(points.reduce((a, p) => a + p.injected, 0)),
    closingUsd: points.length ? points[points.length - 1].closing : round2(openingUsd),
    ledgerGapUsd,
    warnings,
  };
}

/** Big movers first — used by the report's "notable days" section. */
export function topDays(points: DailyCapitalPoint[], n = 5): DailyCapitalPoint[] {
  return [...points].sort((a, b) => Math.abs(b.deposit) - Math.abs(a.deposit)).slice(0, n);
}

export interface DepositScale {
  /** Symmetric y half-range used by the bar panel. */
  axisMax: number;
  /** Days whose |deposit| exceeds axisMax — drawn clipped, values in the table. */
  clipped: { day: string; deposit: number }[];
  /** True when the axis had to be clipped (a data day exceeds what fits). */
  isClipped: boolean;
}

/**
 * Robust y-scale for the daily-deposit bars.
 *
 * WHY: one or two outlier days ($993 and $743 in the Sep window) otherwise set
 * the scale for the whole panel, leaving every ordinary day 1–2px tall — a chart
 * that reads as empty (the first version's bug).
 *
 * HOW: a Tukey fence on the magnitudes — fence = Q3 + 1.5·IQR — and the axis is
 * set to that fence ONLY when the largest day exceeds it by `materialRatio`
 * (default 1.5×), so a barely-over value is not clipped for cosmetics. A clean
 * series uses its real maximum and nothing is clipped. Clipped days are returned
 * so the caller can mark them and print the true numbers — this axis is never
 * silently truncated.
 */
export function depositScale(
  points: DailyCapitalPoint[],
  opts: { iqrFactor?: number; materialRatio?: number } = {}
): DepositScale {
  const iqrFactor = opts.iqrFactor ?? 1.5;
  const materialRatio = opts.materialRatio ?? 1.5;
  const mags = points
    .map((p) => Math.abs(p.deposit))
    .filter((v) => v > 0)
    .sort((a, b) => a - b);
  if (mags.length === 0) return { axisMax: 1, clipped: [], isClipped: false };

  const max = mags[mags.length - 1];
  const fence = quantile(mags, 0.75) + iqrFactor * (quantile(mags, 0.75) - quantile(mags, 0.25));
  const needsClip = fence > 0 && max > fence * materialRatio;
  const axisMax = needsClip ? fence : max;
  const clipped = needsClip
    ? points.filter((p) => Math.abs(p.deposit) > axisMax).map((p) => ({ day: p.day, deposit: p.deposit }))
    : [];
  return { axisMax, clipped, isClipped: needsClip };
}

/** Linear-interpolation quantile (numpy 'linear' / type 7) of a sorted array. */
export function quantile(sorted: number[], q: number): number {
  if (sorted.length === 0) return 0;
  if (sorted.length === 1) return sorted[0];
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

/** Consecutive-day streaks of positive deposits (the ladder's own view). */
export function positiveStreak(points: DailyCapitalPoint[]): { current: number; best: number } {
  let best = 0;
  let run = 0;
  for (const p of points) {
    if (p.deposit > 0) {
      run += 1;
      best = Math.max(best, run);
    } else {
      run = 0;
    }
  }
  let current = 0;
  for (let i = points.length - 1; i >= 0 && points[i].deposit > 0; i--) current += 1;
  return { current, best };
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
