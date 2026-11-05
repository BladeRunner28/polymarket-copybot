/**
 * wallet-depth-ceiling — what `resolvedTradeCount30d` can and cannot say about depth.
 *
 * Card `wallet-depth-ceiling-300-finding` (queue item 18, 2026-11-04). WHY THIS EXISTS: the
 * depth walk is bounded (`DEPTH_MAX_CLOSED_PAGES` default 6 x 50 rows = 300 closed), so every
 * wallet whose record runs past 300 stores EXACTLY 300 and `depthCensored = true`. On the live
 * book 1,870 of 3,831 wallets (48.8%) sit ON the ceiling, so the field is a THRESHOLD indicator,
 * not a depth measure: a 300-position record and a 3,000-position one are the same number.
 *
 * THE DISTINCTION THIS MODULE KEEPS (and the reason it exists rather than one more printed
 * caveat): a CENSORED count is a LOWER BOUND, and a lower bound answers a floor question
 * TRUTHFULLY right up to the ceiling. `count >= 300` really does pass a floor of 5, 10, 50 or
 * 100. It only turns indeterminate ABOVE the ceiling, where a censored wallet can "fail" a floor
 * its true depth would clear. So the ceiling is not a defect in the floor — it is a defect in
 * any comparison that needs to ORDER wallets inside the deep end, and in any floor placed at or
 * above the ceiling.
 *
 * Pure: no DB, no clock, no I/O. The caller supplies the rows.
 */

export type DepthObservation = { value: number; censored: boolean };

export type CeilingRead = {
  /** wallets observed */
  n: number;
  /** the ceiling, DERIVED from the rows (never hard-coded — it moved 100 -> 300 once already) */
  ceiling: number;
  /** rows sitting exactly on the ceiling */
  atCeiling: number;
  atCeilingShare: number;
  /** rows flagged censored (walk budget bound) */
  censored: number;
  /** censored rows whose count stopped on the closed-side ceiling */
  censoredAtCeiling: number;
  /** censored rows whose count is under the ceiling — the OPEN-side budget bound instead */
  censoredBelowCeiling: number;
  /** rows exactly at the ceiling with no censoring — a genuinely exact 300 */
  exactAtCeiling: number;
};

function safeShare(part: number, whole: number): number {
  return whole > 0 ? part / whole : 0;
}

/** Derive the ceiling and its tie mass from the rows themselves. */
export function readCeiling(rows: DepthObservation[]): CeilingRead {
  const n = rows.length;
  const ceiling = n === 0 ? 0 : Math.max(...rows.map((r) => r.value));
  const atCeiling = rows.filter((r) => r.value === ceiling).length;
  const censored = rows.filter((r) => r.censored).length;
  const censoredAtCeiling = rows.filter((r) => r.censored && r.value === ceiling).length;
  return {
    n,
    ceiling,
    atCeiling,
    atCeilingShare: safeShare(atCeiling, n),
    censored,
    censoredAtCeiling,
    censoredBelowCeiling: censored - censoredAtCeiling,
    exactAtCeiling: atCeiling - censoredAtCeiling,
  };
}

export type FloorVerdict = {
  floor: number;
  /** rows whose stored count clears the floor (verdict is TRUE for a lower bound) */
  pass: number;
  /** of those, rows that only clear it as a lower bound */
  passCensored: number;
  /** rows whose stored count is under the floor */
  fail: number;
  /** of those, rows that MAY actually clear it: censored, under the floor, and floor above the ceiling */
  failIndeterminate: number;
};

/**
 * Simulate one minimum-depth floor over the field. A censored row PASSES truthfully when its
 * lower bound clears the floor. It FAILS INDETERMINATELY only when the floor is ABOVE the
 * ceiling, because then the walk stopped before it could see enough rows to decide.
 */
export function floorVerdict(rows: DepthObservation[], floor: number, ceiling: number): FloorVerdict {
  const pass = rows.filter((r) => r.value >= floor).length;
  const passCensored = rows.filter((r) => r.value >= floor && r.censored).length;
  const failRows = rows.filter((r) => r.value < floor);
  const indeterminate = floor > ceiling ? failRows.filter((r) => r.censored).length : 0;
  return {
    floor,
    pass,
    passCensored,
    fail: failRows.length,
    failIndeterminate: indeterminate,
  };
}

/** One verdict per candidate floor, ceiling derived from the same rows. */
export function floorVerdicts(rows: DepthObservation[], floors: number[]): FloorVerdict[] {
  const { ceiling } = readCeiling(rows);
  return floors.map((f) => floorVerdict(rows, f, ceiling));
}

/**
 * The smallest floor at which ANY verdict can be indeterminate: one above the ceiling. Below it
 * the ceiling cannot move a floor decision, because a censored count still answers "at least k".
 */
export function saturationFloor(ceiling: number): number {
  return ceiling + 1;
}

/**
 * Bucket label for any printed depth statistic. Never calls a bucket "the deep end": once a
 * bucket contains the ceiling it contains both exact and lower-bound rows and cannot order them.
 */
export function depthBucketLabel(value: number, censored: boolean, ceiling: number): string {
  if (value >= ceiling) return `${ceiling}+ ${censored ? "(lower bound)" : "(exact)"}`;
  if (value < 10) return "<10";
  if (value < 25) return "10-24";
  if (value < 50) return "25-49";
  if (value < 100) return "50-99";
  return `100-${ceiling - 1}`;
}
