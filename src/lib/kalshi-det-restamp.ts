/**
 * Re-derivation rules for the venue-shadow ledger's deterministic (det) stamp
 * (card det-our-side-flag-defect, adjudicated 2026-11-24).
 *
 * WHY THIS EXISTS: scripts/kalshi-venue-shadow.ts stamps each leg ONCE — its det batch
 * only picks up rows whose `detVerdict` is still undefined — and it keys the resolver's
 * output by `marketId` alone. Two consequences, both measured on the live ledger:
 *
 *   1. A stamp written by a SUPERSEDED derivation is never re-derived. The spread side
 *      rule was replaced on 2026-11-24T02:12Z (commit 2e43718f); the 41 EQUIV legs were
 *      stamped 2026-11-23T13:37–13:57Z, so 13 of them still carry the old rule's answer
 *      (`detOurSideIsYes=true` while the pair audit adjudicates `false`) and the ledger
 *      prints that flag as OUR side.
 *   2. One Polymarket market can carry TWO of our legs (one per outcome — e.g. the UFC
 *      fight where we held both fighters at different times). Keyed by marketId, both
 *      legs receive whichever outcome the resolver returned LAST, so the second leg is
 *      stamped with the wrong contract AND the wrong side.
 *
 * The rules here are deliberately narrow: a re-derivation refreshes derivation OUTPUTS and
 * never re-prices a leg. A price taken today for a leg opened last week is look-ahead, and
 * an entry priced on the other side of the contract is a different position — so an entry
 * survives only when the contract and the side it was priced on are both unchanged.
 */

/** Bumped whenever the resolver's DERIVATION changes in a way that invalidates stored output.
 *  v2 (2026-11-24): the spread side rule was replaced; stamps written before it are stale. */
export const DET_DERIVATION_VERSION = 2;

/**
 * Identity of one resolver request/answer: our market AND the outcome we held.
 * Bump this only together with DET_DERIVATION_VERSION — a stale stamp is identified by
 * (marketId, outcome) and an unstamped/older-version row is the thing being re-derived.
 * Same normalisation as pairKey() so the two keys can never disagree about an outcome.
 */
export function detKey(marketId: string | null | undefined, outcome: string | null | undefined): string {
  return `${(marketId ?? "").trim()}|${(outcome ?? "").trim()}`;
}

export type DetStampLike = {
  detVerdict?: string;
  detVersion?: number;
  detTicker?: string;
  detOurSideIsYes?: boolean | null;
  detEntry?: number | null;
};

/**
 * Does this row need (re-)derivation?
 *
 * - never stamped (`detVerdict` undefined)            -> yes, the arm's forward backlog;
 * - EQUIV and stamped by an older derivation          -> yes, its side/ticker/entry were printed;
 * - anything else (NO_EVENT_MATCH, OTHER_CLASS, …)    -> no. Those verdicts carry none of the
 *   side/price fields a version bump can correct, so re-walking the event pool for them would
 *   spend the per-run batch on rows that cannot change (and, for a settled row, on a walk that
 *   ends in the same answer).
 */
export function needsDetRederive(s: DetStampLike): boolean {
  if (s.detVerdict === undefined) return true;
  if (s.detVerdict !== "EQUIV") return false;
  return (s.detVersion ?? 1) < DET_DERIVATION_VERSION;
}

/**
 * Is the stored venue settlement read about a DIFFERENT contract than the stamp now names?
 * A corrected stamp (the marketId-collision repair) changes `detTicker`; the settlement pass
 * only re-reads rows whose `venueResult` is empty, so without this the row would keep the old
 * contract's `result` — a settlement attributed to a market we never held.
 */
export function venueReadStale(
  storedTicker: string | null | undefined, detTicker: string | null | undefined,
): boolean {
  if (!storedTicker || !detTicker) return false;
  return storedTicker !== detTicker;
}

export type RestampPlan = {
  /** entry to store: the previous entry when it is still the same position, else null */
  detEntry: number | null;
  /** true when a previously-priced entry was dropped because the position changed */
  cleared: boolean;
  /** note to append to the resolver's own note, naming why (null = nothing to say) */
  note: string | null;
};

/**
 * Decide what happens to a det stamp's ENTRY on (re-)derivation.
 *
 * - first stamp: take the resolver's price, exactly as before this module existed.
 * - re-derivation: NEVER take a fresh price (look-ahead). Keep the stored entry only if the
 *   contract and the side are unchanged; otherwise clear it, because that entry priced a
 *   position we did not hold.
 */
export function restampEntry(
  prev: { detTicker?: string; detOurSideIsYes?: boolean | null; detEntry?: number | null },
  next: { ticker?: string | null; ourSideIsYes?: boolean | null },
  firstStamp: boolean,
  price: number | null | undefined,
): RestampPlan {
  if (firstStamp) return { detEntry: price ?? null, cleared: false, note: null };
  const sameTicker = (prev.detTicker ?? null) === (next.ticker ?? null);
  const sameSide = (prev.detOurSideIsYes ?? null) === (next.ourSideIsYes ?? null);
  if (sameTicker && sameSide) {
    const kept = prev.detEntry ?? null;
    return { detEntry: kept, cleared: false, note: null };
  }
  const had = prev.detEntry != null;
  return {
    detEntry: null,
    cleared: had,
    note: `stale_stamp_v${DET_DERIVATION_VERSION}: ${sameTicker ? "side" : "contract"} changed `
      + `(${prev.detTicker ?? "none"}/${String(prev.detOurSideIsYes)} -> `
      + `${next.ticker ?? "none"}/${String(next.ourSideIsYes ?? null)})`,
  };
}
