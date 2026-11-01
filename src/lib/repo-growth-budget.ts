/**
 * repo-growth-budget — how fast this repo grows, in the numbers git actually pays.
 *
 * WHY THIS EXISTS (2026-10-31, kalshi-tape-repo-size-policy):
 * That card was written 2026-10-12 from an ARITHMETIC estimate — ~22 MB/day of prints,
 * ~11 MB/day of bars, ~1 MB/day of coverage, i.e. 25-35 MB/day of TRACKED growth.
 * The estimate measures the wrong quantity twice over:
 *   - it is a TREE DELTA (how much the tracked tree grew), while .git pays for every
 *     blob ever committed. An append-only tape rewritten WHOLE on each of the 5-26
 *     commits a day adds its full size every time, not its delta;
 *   - it assumes one write per file per day. The live tree changes far more often.
 * MEASURED on the real object store 2026-10-31 (7 complete UTC days): 38-65 MB/day
 * added to .git against a tree delta of 30-35 MB/day, i.e. ~200 MB/day uncompressed at
 * ~0.21 disk/raw. Only ~1% of those bytes are a path re-committed inside the same day,
 * so the growth is real content and not a commit-cadence artefact: the tape is the
 * driver, and a 2 GiB .git is ~17 days away at the median day.
 *
 * Whether the tape STAYS tracked is the user call (kalshi-tape-capture-live user
 * override 2026-10-12) and is parked on git-backup-large-artifact-policy. A ceiling
 * that only ALARMS changes nothing the bot decides, so it is Lane B.
 *
 * BASIS, stated once: the daily figure is the sum over a UTC calendar day of the
 * on-disk (loose zlib / delta-packed) size of every blob NEWLY added by that day
 * commits, from `git diff-tree --raw` against the first parent. It is what the object
 * store gained that day; a later gc can only lower it.
 */
export type PathClass =
  | "db"
  | "orderbook"
  | "cache"
  | "dataset"
  | "tape-kalshi"
  | "tape-shadow"
  | "tape-other"
  | "code"
  | "other";

/** Policy defaults. A ceiling that only alarms, never deletes. */
export const DEFAULT_CEILING_BYTES = 2 * 1024 ** 3; // 2 GiB .git: GitHub recommends <1 GiB per repo and this repo is already past it; 2 GiB is the chosen operating wall, not a vendor limit.
export const DEFAULT_DAILY_BUDGET_BYTES = 40 * 1024 * 1024; // 40 MB/day: upper end of the cards 25-35 MB/day arithmetic plus headroom, so the budget cannot be met by re-labelling churn.
export const DEFAULT_ALARM_DAYS = 90; // alarm when the projected crossing of the ceiling is inside one quarter.

/**
 * Which class of tracked file a path belongs to. Order matters: the cheap, exact
 * checks run before the generic data/ one so a parquet under data/ is never counted
 * as tape, and the tape classes are split because they have different owners.
 */
export function classifyTrackedPath(rawPath: string): PathClass {
  const p = rawPath.replace(/^\.\//, "");
  if (/^prisma\/.*\.db$/.test(p) || /^dev\.db$/.test(p) || /\.db$/.test(p)) return "db";
  if (/^data\/l2\//.test(p) || /^data\/l2-[a-z-]+\.jsonl$/.test(p) || /^data\/orderbook/.test(p)) return "orderbook";
  if (/^data\/cache\//.test(p)) return "cache";
  if (
    /^data\/archive-analysis\//.test(p) ||
    /^data\/ml\//.test(p) ||
    /^data\/.*\.parquet$/.test(p) ||
    /^training_data\.csv$/.test(p)
  )
    return "dataset";
  if (/^data\/kalshi/.test(p)) return "tape-kalshi";
  if (/^data\/.*shadow.*\.(jsonl|jsonl\.gz)$/.test(p)) return "tape-shadow";
  if (/^data\/.*\.(jsonl|jsonl\.gz|csv|gz)$/.test(p)) return "tape-other";
  if (/^(src|scripts|tests|app|prisma|drafts|docs|public)\//.test(p) || !p.includes("/")) return "code";
  return "other";
}

export type ClassTotal = { files: number; bytes: number };

/** Bytes and file counts at HEAD, grouped by class. */
export function classTotals(entries: { path: string; bytes: number }[]): Record<PathClass, ClassTotal> {
  const out = {} as Record<PathClass, ClassTotal>;
  for (const e of entries) {
    const c = classifyTrackedPath(e.path);
    const cur = out[c] ?? { files: 0, bytes: 0 };
    out[c] = { files: cur.files + 1, bytes: cur.bytes + e.bytes };
  }
  return out;
}

export type GrowthSummary = {
  /** number of calendar days supplied */
  n: number;
  /** days that added exactly zero bytes (no commit, or a commit that touched nothing large) */
  idleDays: number;
  mean: number;
  median: number;
  /** mean after dropping the top and bottom floor(n/10) (at least 1 each when n >= 5) */
  trimmedMean: number;
  /** value at the 90th percentile (nearest-rank) */
  p90: number;
  max: number;
  /** mean with the single largest day removed — the concentration check */
  exTop1Mean: number;
};

function mean(xs: number[]): number {
  if (xs.length === 0) return 0;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

function median(xs: number[]): number {
  if (xs.length === 0) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 === 1 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/**
 * Robust read of a daily growth series. The headline projection must not be set by
 * one big day, so median, trimmed mean and ex-top-1 are all reported and the median
 * drives the verdict. Zeros are KEPT (a quiet day is real growth information) and
 * counted separately so a series that is mostly idle cannot masquerade as flat.
 */
export function summariseGrowth(daily: number[]): GrowthSummary {
  const xs = daily.filter((v) => Number.isFinite(v) && v >= 0);
  if (xs.length === 0) {
    return { n: 0, idleDays: 0, mean: 0, median: 0, trimmedMean: 0, p90: 0, max: 0, exTop1Mean: 0 };
  }
  const sorted = [...xs].sort((a, b) => a - b);
  const drop = xs.length >= 5 ? Math.max(1, Math.floor(xs.length / 10)) : 0;
  const trimmed = drop > 0 ? sorted.slice(drop, xs.length - drop) : sorted;
  const rank = Math.max(1, Math.ceil(0.9 * sorted.length));
  return {
    n: xs.length,
    idleDays: xs.filter((v) => v === 0).length,
    mean: mean(xs),
    median: median(xs),
    trimmedMean: mean(trimmed),
    p90: sorted[Math.min(rank, sorted.length) - 1],
    max: sorted[sorted.length - 1],
    exTop1Mean: xs.length >= 2 ? mean(xs.filter((_, i) => i !== xs.indexOf(sorted[sorted.length - 1]))) : xs[0],
  };
}

/**
 * Days until the object store reaches `ceilingBytes` at a constant `bytesPerDay`.
 * null when growth is zero or negative (no crossing to project), 0 when already past.
 */
export function daysToCeiling(currentBytes: number, bytesPerDay: number, ceilingBytes: number): number | null {
  if (currentBytes >= ceilingBytes) return 0;
  if (!Number.isFinite(bytesPerDay) || bytesPerDay <= 0) return null;
  return Math.ceil((ceilingBytes - currentBytes) / bytesPerDay);
}

/**
 * Bytes that a day added only because the SAME path was committed more than once.
 * `writes` must be in commit order; the first write of a path is treated as that
 * day legitimate new content and every later write of it as churn. This is the
 * number a lower commit cadence (or a squash before the nightly backup) would save,
 * and it is reported, never acted on.
 */
export function churnBytes(writes: { path: string; bytes: number }[]): number {
  const first = new Map<string, number>();
  const total = new Map<string, number>();
  for (const w of writes) {
    if (!first.has(w.path)) first.set(w.path, w.bytes);
    total.set(w.path, (total.get(w.path) ?? 0) + w.bytes);
  }
  let churn = 0;
  for (const [path, tot] of total) churn += tot - (first.get(path) ?? 0);
  return churn;
}

/** Largest contributors, with each one share of the population total. */
export function topContributors(
  rows: { path: string; bytes: number }[],
  k = 10,
): { path: string; bytes: number; share: number }[] {
  const byPath = new Map<string, number>();
  for (const r of rows) byPath.set(r.path, (byPath.get(r.path) ?? 0) + r.bytes);
  const total = [...byPath.values()].reduce((a, b) => a + b, 0);
  return [...byPath.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, k)
    .map(([path, bytes]) => ({ path, bytes, share: total > 0 ? bytes / total : 0 }));
}

export type VerdictLevel = "ok" | "warn" | "alarm";

export type Verdict = {
  level: VerdictLevel;
  reasons: string[];
  summary: GrowthSummary;
  daysAtMedian: number | null;
  daysAtMax: number | null;
  overBudget: boolean;
};

/**
 * Alarm-only verdict. ALARM when the robust (median) projection lands inside
 * `alarmDaysToCeiling` or the median day is over budget; WARN when the pessimistic
 * (max-day) projection is inside the alarm window or the median is above 75% of
 * budget. Nothing here deletes, untracks or rewrites: the whole point is that a
 * growth policy can be enforced by a signal instead of by pruning the one
 * irreversible asset.
 */
export function budgetVerdict(input: {
  currentGitBytes: number;
  daily: number[];
  ceilingBytes?: number;
  dailyBudgetBytes?: number;
  alarmDaysToCeiling?: number;
}): Verdict {
  const ceiling = input.ceilingBytes ?? DEFAULT_CEILING_BYTES;
  const budget = input.dailyBudgetBytes ?? DEFAULT_DAILY_BUDGET_BYTES;
  const alarmDays = input.alarmDaysToCeiling ?? DEFAULT_ALARM_DAYS;
  const summary = summariseGrowth(input.daily);
  const daysAtMedian = daysToCeiling(input.currentGitBytes, summary.median, ceiling);
  const daysAtMax = daysToCeiling(input.currentGitBytes, summary.max, ceiling);
  const overBudget = summary.median > budget;
  const reasons: string[] = [];
  let level: VerdictLevel = "ok";
  if (daysAtMedian !== null && daysAtMedian <= alarmDays) {
    level = "alarm";
    reasons.push(`median ${mbFmt(summary.median)}/day crosses the ${mbFmt(ceiling)} ceiling in ${daysAtMedian} days (alarm window ${alarmDays})`);
  }
  if (overBudget) {
    level = "alarm";
    reasons.push(`median ${mbFmt(summary.median)}/day is over the ${mbFmt(budget)}/day budget`);
  }
  if (level === "ok" && daysAtMax !== null && daysAtMax <= alarmDays) {
    level = "warn";
    reasons.push(`worst day ${mbFmt(summary.max)} crosses the ${mbFmt(ceiling)} ceiling in ${daysAtMax} days`);
  }
  if (level === "ok" && summary.median > budget * 0.75) {
    level = "warn";
    reasons.push(`median ${mbFmt(summary.median)}/day is above 75% of the ${mbFmt(budget)}/day budget`);
  }
  if (reasons.length === 0) reasons.push(`median ${mbFmt(summary.median)}/day is inside budget and the ${mbFmt(ceiling)} ceiling is not in sight`);
  return { level, reasons, summary, daysAtMedian, daysAtMax, overBudget };
}

/** Bytes as MB, for reason strings only. Declared last; function declarations hoist. */
function mbFmt(bytes: number): string {
  return `${(bytes / 1048576).toFixed(1)} MB`;
}
