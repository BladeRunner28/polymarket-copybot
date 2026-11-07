/**
 * category-cap-blocks — the v41 per-category concentration rail, read back out of
 * the journal, and the price of the copies it refused.
 *
 * WHY THIS EXISTS (2026-11-06, category-seats-never-released):
 * `c200CategoryCounts` is seeded from the C-200 open rows at the top of a scoring
 * run (scripts/score-trades.ts ~L262), then incremented the moment a candidate
 * PASSES the category check (~L678). Nothing ever decrements it. Every refusal
 * that fires LATER in the same run (drawdown, kelly no-edge, entry caps, band
 * skips, v55, v58, maxOpen) therefore leaves its seat consumed for the rest of the
 * run, so the printed `would be 41/40` describes ATTEMPTS THAT PASSED, not open
 * positions. Same defect class as the v45 slug cap (77/105 = 73.3% phantom) and the
 * v55 per-market rail (5/58 = 8.6%).
 *
 * TWO BASIS LIES LIVE IN THAT ONE STRING, and both are visible in the live data:
 *   1. the count is attempts, not positions (this module's `classify`);
 *   2. the seed is C-200 rows only, while the gate blocks the DECISION, which is
 *      scored for both lanes — so the string also claims a lane scope it does not
 *      have. The `basis` on the parsed block records which form was written.
 *
 * The refused copy is in the journal: DecisionJournal.risksJson carries
 * `category concentration (Defense/Geopolitics would be 41/40)`. That is the
 * population this module reads.
 */

/** One refused copy's category state, parsed from a journal `risksJson` blob. */
export type CategoryCapBlock = {
  /** research category the gate was counting (e.g. "Defense/Geopolitics") */
  category: string;
  /** the count the decision would have made, ON THE COUNTER'S OWN BASIS */
  wouldBe: number;
  /** rules.maxCategoryPositions in force at decision time */
  cap: number;
  /**
   * "attempts" — written before the 2026-11-06 basis repair: `wouldBe` is seats
   * consumed by passing candidates, not open positions.
   * "attempts-labelled" — post-repair form, which says so in the string and
   * carries the true open count beside it.
   */
  basis: "attempts" | "attempts-labelled";
  /** true open C-200 legs in this category at decision time, when the row states it */
  trueOpen?: number;
};

// Anchored on the exact strings scripts/score-trades.ts writes. A looser pattern
// would also match prose about the rail inside a card note. Both forms are read:
// the historical `... would be 41/40)` and the post-repair
// `... would be 41/40 on an attempts basis; true open 0)`.
const BLOCK_RE = /category concentration \(([^ ]+) would be (\d+)\/(\d+)( on an attempts basis; true open (\d+))?\)/g;

/** Every category-cap block recorded on one decision row (usually 0 or 1). */
export function parseCategoryCapBlocks(risksJson: string | null | undefined): CategoryCapBlock[] {
  if (!risksJson) return [];
  const out: CategoryCapBlock[] = [];
  BLOCK_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = BLOCK_RE.exec(risksJson)) !== null) {
    const wouldBe = Number(m[2]);
    const cap = Number(m[3]);
    if (!Number.isFinite(wouldBe) || !Number.isFinite(cap)) continue;
    if (m[5] !== undefined) {
      const trueOpen = Number(m[5]);
      out.push({ category: m[1], wouldBe, cap, basis: "attempts-labelled", trueOpen });
    } else {
      out.push({ category: m[1], wouldBe, cap, basis: "attempts" });
    }
  }
  return out;
}

export function isCategoryCapBlock(risksJson: string | null | undefined): boolean {
  return parseCategoryCapBlocks(risksJson).length > 0;
}

/** The line scripts/score-trades.ts writes. One place, so the string and the
 *  parser can never drift. `trueOpen` is the reconstructed open-leg count; pass
 *  null when the caller cannot establish it and the clause is omitted rather
 *  than guessed. */
export function formatCategoryCapBlock(
  category: string,
  projected: number,
  cap: number,
  trueOpen: number | null
): string {
  const tail = trueOpen === null ? "" : ` on an attempts basis; true open ${trueOpen}`;
  return `category concentration (${category} would be ${projected}/${cap}${tail})`;
}

export type BlockClass = "genuine" | "phantom" | "unknown";

/**
 * Was this refusal a REAL seat, or a seat held by copies a later gate refused?
 * `openLegs` is the true number of open C-200 legs in the same research category
 * at decision time, reconstructed from the booked legs' own open/close intervals.
 * `unknown` is a real answer, never a fallback: it is returned when the caller
 * cannot reconstruct the ground truth, so an unclassifiable refusal can never be
 * counted as evidence for either arm.
 */
export function classifyCategoryBlock(block: CategoryCapBlock, openLegs: number | null): BlockClass {
  if (openLegs === null || !Number.isFinite(openLegs)) return "unknown";
  if (block.cap <= 0) return "unknown";
  return openLegs >= block.cap ? "genuine" : "phantom";
}

/** Human line for a refusal's cause, kept beside the parser so the label can
 *  never drift from the string it names. */
export function describeCategoryBlock(b: CategoryCapBlock): string {
  return `category ${b.category} seats ${b.wouldBe}/${b.cap} (attempt basis)`;
}

export type Interval = { open: number; end: number | null };

/** Open intervals live at time `at` (ms). An interval with `end === null` is still
 *  open; `open <= at < end` mirrors the rail's own `status: "open"` seed. */
export function openLegsAt(intervals: Interval[], at: number): number {
  let n = 0;
  for (const i of intervals) if (i.open <= at && (i.end === null || i.end > at)) n += 1;
  return n;
}

/** Peak concurrent open legs over the whole series — the ceiling this rail would
 *  have to reach to bind at all. Swept at interval starts, which is where a peak
 *  can occur. */
export function maxConcurrentLegs(intervals: Interval[]): number {
  let best = 0;
  for (const i of intervals) best = Math.max(best, openLegsAt(intervals, i.open));
  return best;
}

/**
 * Same sweep as `maxConcurrentLegs`, keeping WHEN the peak happened. A peak that
 * predates the rail's own activation says nothing about whether the rail binds, so
 * the caller must be able to see the clock.
 */
export function maxConcurrentLegsAt(intervals: Interval[]): { legs: number; at: number | null } {
  let best = 0;
  let at: number | null = null;
  for (const i of intervals) {
    const n = openLegsAt(intervals, i.open);
    if (n > best) {
      best = n;
      at = i.open;
    }
  }
  return { legs: best, at };
}
