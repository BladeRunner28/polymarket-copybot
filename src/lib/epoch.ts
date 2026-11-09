/**
 * Timestamp normalisation for cross-store reads.
 *
 * WHY THIS EXISTS: the timestamp formats in this fleet are not uniform, and assuming one is how a
 * dashboard lies. Verified with `typeof` over live rows on 2026-11-09:
 *   kanban  tasks.worker_started_at   TEXT, epoch MILLISECONDS as a numeric string ("179423581209")
 *   kanban  tasks.started_at          INTEGER, epoch SECONDS
 *   kanban  tasks.completed_at        INTEGER, epoch SECONDS
 *   kanban  task_runs.started_at      INTEGER, epoch SECONDS
 *   cron    executions.started_at     ISO 8601 STRING, e.g. "2026-10-29T12:25:35.80-05:00"
 *
 * DEFECT THIS PINS: /workers rendered "NaNd NaNh" for a running worker's elapsed time. Its header
 * documented worker_started_at as epoch SECONDS (it is milliseconds, as TEXT), and the panel passed
 * the raw value into `nowS() - started`. Worse, the first fix attempt still failed: Date.parse on a
 * numeric STRING returns NaN, so a "normalise everything" helper that only understood numbers and
 * ISO strings returned null for exactly the value that was broken.
 *
 * Returns epoch SECONDS, or null for anything unusable — callers must render "—" rather than
 * compute with a null, because a wrong duration and a missing one look identical once printed.
 */
export function toEpoch(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") {
    // NaN is typeof "number". Returning it would hand the caller exactly the value that prints
    // "NaNd NaNh", so a non-finite number is junk like any other.
    if (!Number.isFinite(v)) return null;
    return fromMagnitude(v);
  }
  const s = String(v).trim();
  if (!s) return null;
  // Numeric strings first: Date.parse("179423581209") is NaN, and these columns store epoch
  // values as text.
  if (/^-?\d+(\.\d+)?$/.test(s)) {
    const n = Number(s);
    if (!Number.isFinite(n)) return null;
    return fromMagnitude(n);
  }
  const t = Date.parse(s);
  return Number.isFinite(t) ? Math.floor(t / 1000) : null;
}

/**
 * Epoch magnitudes actually observed in this fleet (2026-11-09, ~1.794e9 s):
 *   1,794,245,627      (10 digits) epoch SECONDS        -> as-is
 *   179,424,557,890    (12 digits) epoch CENTISECONDS   -> /100
 *   1,794,245,627,890  (13 digits) epoch MILLISECONDS   -> /1000
 * A two-tier "ms if > 1e11" test sends the 12-digit form through /1000 and lands 100x early —
 * which is a duration that looks plausible and is wrong by a factor of a hundred.
 */
function fromMagnitude(n: number): number | null {
  if (n > 1e12) return Math.floor(n / 1000); // milliseconds
  if (n > 1e10) return Math.floor(n / 100); // centiseconds
  return n; // seconds
}
