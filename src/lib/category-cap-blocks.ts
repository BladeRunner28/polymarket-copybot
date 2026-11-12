/**
 * category-cap-blocks — the v41 per-category concentration rail, read back out of
 * the journal, and the price of the copies it refused.
 *
 * WHY THIS EXISTS (2026-11-06, category-seats-never-released):
 * `c200CategoryCounts` was seeded from the C-200 open rows at the top of a scoring
 * run (scripts/score-trades.ts ~L262), then incremented the moment a candidate
 * PASSED the category check. Nothing ever decremented it, so every refusal that
 * fired LATER in the same run (drawdown, kelly no-edge, entry caps, band skips,
 * v55, v58, maxOpen) left its seat consumed for the rest of the run, and the
 * printed `would be 41/40` described ATTEMPTS THAT PASSED, not open positions.
 * Same defect class as the v45 slug cap (77/105 = 73.3% phantom) and the v55
 * per-market rail (5/58 = 8.6%).
 *
 * APPLIED 2026-11-12 (operator-approved): the seat is now consumed at the booking
 * point, so the counter is seed + dispatched legs — a position count. The refusal
 * line therefore changed form; three forms exist in the journal and all three are
 * parsed here:
 *
 *   1. `category concentration (Crypto would be 41/40)`
 *        pre-2026-11-06. `wouldBe` = attempts that passed the gate. basis "attempts".
 *   2. `category concentration (Crypto would be 41/40 on an attempts basis; true open 0)`
 *        2026-11-06..2026-11-12. Same attempts count, with the reconstructed true
 *        open stated beside it. basis "attempts-labelled".
 *   3. `category concentration (Crypto open 40/40 on an open-position basis)`
 *        post-2026-11-12. `open` IS the open C-200 leg count in the category and
 *        `cap` the cap; the candidate would have made it open+1. basis "positions".
 *
 * The refused copy is in the journal: DecisionJournal.risksJson carries one of the
 * strings above. That is the population this module reads.
 */

/** One refused copy's category state, parsed from a journal `risksJson` blob. */
export type CategoryCapBlock = {
  /** research category the gate was counting (e.g. "Defense/Geopolitics") */
  category: string;
  /**
   * The count the refused decision would have produced, ON THE COUNTER'S OWN BASIS.
   * For basis "positions" this is DERIVED (`open + 1`) so that every form of the
   * block answers `wouldBe > cap` the same way; read `trueOpen` for the stated value.
   */
  wouldBe: number;
  /** rules.maxCategoryPositions in force at decision time */
  cap: number;
  /**
   * "attempts" — pre-2026-11-06: `wouldBe` is seats consumed by passing candidates.
   * "attempts-labelled" — 2026-11-06..11-12: says so in the string and carries the
   *   true open count beside it.
   * "positions" — post-2026-11-12: the string states the open leg count itself.
   */
  basis: "attempts" | "attempts-labelled" | "positions";
  /** open C-200 legs in this category at decision time, as the row states it */
  trueOpen?: number;
};

// Anchored on the exact strings scripts/score-trades.ts writes. A looser pattern
// would also match prose about the rail inside a card note. The historical forms
// (1 and 2) and the post-fix position form (3) are separate patterns so neither
// can silently absorb the other.
const BLOCK_RE =
  /category concentration \(([^ ]+) would be (\d+)\/(\d+)( on an attempts basis; true open (\d+))?\)/g;
const POSITIONS_RE =
  /category concentration \(([^ ]+) open (\d+)\/(\d+) on an open-position basis\)/g;

/** Every category-cap block recorded on one decision row (usually 0 or 1). */
export function parseCategoryCapBlocks(risksJson: string | null | undefined): CategoryCapBlock[] {
  if (!risksJson) return [];
  const out: CategoryCapBlock[] = [];
  BLOCK_RE.lastIndex = 0;
  POSITIONS_RE.lastIndex = 0;
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
  while ((m = POSITIONS_RE.exec(risksJson)) !== null) {
    const trueOpen = Number(m[2]);
    const cap = Number(m[3]);
    if (!Number.isFinite(trueOpen) || !Number.isFinite(cap)) continue;
    out.push({ category: m[1], wouldBe: trueOpen + 1, cap, basis: "positions", trueOpen });
  }
  return out;
}

export function isCategoryCapBlock(risksJson: string | null | undefined): boolean {
  return parseCategoryCapBlocks(risksJson).length > 0;
}

/** The line scripts/score-trades.ts writes. One place, so the string and the
 *  parser can never drift. `openPositions` is the category's open C-200 leg count
 *  at decision time — the counter's own basis since 2026-11-12 (seed + legs
 *  dispatched this run). Passing an attempt count here would be a basis lie. */
export function formatCategoryCapBlock(
  category: string,
  openPositions: number,
  cap: number
): string {
  return `category concentration (${category} open ${openPositions}/${cap} on an open-position basis)`;
}

export type BlockClass = "genuine" | "phantom" | "unknown";

/**
 * The seat decision for one candidate. `openPositions` is the counter's value for
 * the candidate's research category — seed (open C-200 legs at run start) plus the
 * legs this run actually dispatched, and NOTHING else. Blocked iff admitting this
 * candidate would put the category above `cap`; a cap of 0 disables the rail.
 *
 * This is the arithmetic the 2026-11-12 fix turned on: the counter must never be
 * incremented by a candidate that merely PASSED this check, because every refusal
 * that fires later in the same run (drawdown, kelly no-edge, entry caps, band
 * skips, v55, v58) would otherwise leave a seat consumed for a leg that never
 * booked. Callers consume the seat at the booking point only.
 */
export function categorySeatDecision(
  openPositions: number,
  cap: number
): { blocked: boolean; wouldBe: number; openPositions: number } {
  const wouldBe = openPositions + 1;
  return { blocked: cap > 0 && wouldBe > cap, wouldBe, openPositions };
}

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
  const basis =
    b.basis === "positions"
      ? "open-position basis"
      : b.basis === "attempts-labelled"
        ? "attempt basis, true open stated"
        : "attempt basis";
  return `category ${b.category} seats ${b.wouldBe}/${b.cap} (${basis})`;
}

/**
 * The card's own refutation, machine-checkable. A refusal written on the
 * open-position basis must state an open count AT the cap (that is the only way
 * `open + 1 > cap`); one that states fewer means the counter went back to counting
 * candidates that a LATER gate refused — the exact defect the 2026-11-12 change
 * removed. Rows on the older bases are not judged by this (they are honest history).
 */
export function positionBasisViolation(b: CategoryCapBlock): boolean {
  if (b.basis !== "positions") return false;
  return b.trueOpen === undefined || b.trueOpen < b.cap;
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
