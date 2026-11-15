/**
 * Decision provenance — the inputs a decision was actually made on.
 *
 * WHY THIS EXISTS (card `data2-per-decision-provenance`, 2026-11-14)
 * ----------------------------------------------------------------
 * The journal stored the SCORE and the prose reasons, but none of the numbers
 * that produced them: the sentiment edge the sentiment layer computed, the price
 * the decision was taken at, and whether the market was already decided at that
 * price. The consequences, measured before this module existed:
 *
 *   - sentiment was unjoinable. 696 of 375,323 journal rows (0.19%) mention it at
 *     all, and only as prose inside reasonsJson ("Sentiment evidence edge +21.1pp,
 *     calibrated"). RegulatorySignal has no marketId, so the research bot's
 *     signals cannot be joined to a decision either. Every sentiment read was
 *     therefore a grep over English.
 *   - `priceAtDecision` did not exist, so "already decided at entry" (the class
 *     that dilutes a gate test) could not be flagged at all.
 *   - OutcomeReview.priceAfter1h/6h/24h existed and had NO writer and NO reader
 *     anywhere in the repo (verified 2026-11-14), i.e. the horizon was never
 *     recorded, so nothing could learn timing.
 *
 * This module is PURE: no I/O, no DB, no network. It is the shared rule for what
 * counts as a horizon price, so the writer and the probe cannot disagree.
 */

/** At or above this price the market is already decided — an entry here has no edge to measure. */
export const ALREADY_DECIDED_PRICE = 0.995;

/** The horizons the card asks for; the order is the order they are reported in. */
export const HORIZONS = [
  { key: "1h", hours: 1 },
  { key: "6h", hours: 6 },
  { key: "24h", hours: 24 },
] as const;

export type HorizonKey = (typeof HORIZONS)[number]["key"];

/**
 * How far before the horizon a print may sit and still be called "the price at
 * the horizon". 90 minutes: the venue tape thins out on slow markets, and an
 * hour-and-a-half-old quote is still the market's own view; a day-old one is not.
 */
export const HORIZON_MAX_STALENESS_MS = 90 * 60_000;

export type PricePoint = { t: number; p: number };

export type HorizonReason =
  | "ok"
  | "no_path" // the venue returned no usable points in the window
  | "no_print" // nothing at or before the horizon (market had not traded yet)
  | "stale" // last print at/before the horizon is older than the tolerance
  | "terminal_print"; // the last print is exactly 0 or 1 — settlement, not a market price

export type HorizonRead = {
  /** The price of the held token at the horizon; null when the tape cannot say. */
  price: number | null;
  /** When that print happened (epoch ms), or null. */
  atMs: number | null;
  reason: HorizonReason;
};

/**
 * The three DecisionJournal provenance fields, as one object, so the write site and
 * its test cannot drift apart.
 *
 * `sentimentDelta: undefined` means the sentiment layer was silent for this decision;
 * it is persisted as NULL, never as 0 — "no evidence" and "evidence that nets to zero"
 * are different rows and a 0 would let a model average them together.
 */
export function decisionProvenanceFields(
  priceAtDecision: number | null | undefined,
  sentimentDelta: number | null | undefined
): { priceAtDecision: number | null; sentimentDelta: number | null; alreadyDecidedAtEntry: boolean } {
  const price =
    typeof priceAtDecision === "number" && Number.isFinite(priceAtDecision) ? priceAtDecision : null;
  return {
    priceAtDecision: price,
    sentimentDelta:
      typeof sentimentDelta === "number" && Number.isFinite(sentimentDelta) ? sentimentDelta : null,
    alreadyDecidedAtEntry: isAlreadyDecided(price),
  };
}

/** Is this entry price already decided? null/undefined is never a decided market. */
export function isAlreadyDecided(price: number | null | undefined): boolean {
  if (typeof price !== "number" || !Number.isFinite(price)) return false;
  return price >= ALREADY_DECIDED_PRICE;
}

/**
 * Parse a CLOB /prices-history payload into sorted, validated points.
 *
 * The venue shape is `{history:[{t:epochSeconds,p:price}]}`. Anything that is not
 * a finite price inside [0,1] is dropped rather than clamped: a clamped price is
 * a fabricated one. Points are sorted by time so a reordered payload cannot move
 * which print "the last one at or before the horizon" is.
 */
export function parsePricesHistory(payload: unknown): PricePoint[] {
  if (!payload || typeof payload !== "object") return [];
  const history = (payload as { history?: unknown }).history;
  if (!Array.isArray(history)) return [];
  const out: PricePoint[] = [];
  for (const row of history) {
    if (!row || typeof row !== "object") continue;
    const t = (row as { t?: unknown }).t;
    const p = (row as { p?: unknown }).p;
    if (typeof t !== "number" || !Number.isFinite(t)) continue;
    if (typeof p !== "number" || !Number.isFinite(p)) continue;
    if (p < 0 || p > 1) continue;
    out.push({ t, p });
  }
  out.sort((a, b) => a.t - b.t);
  return out;
}

/**
 * The held token's price at `targetMs`: the LAST print at or before the horizon,
 * within `maxStalenessMs` of it.
 *
 * Deliberately not interpolated and not nearest-in-either-direction: a print that
 * lands after the horizon is information the decision could not have had at that
 * horizon (it is the same class of error as a look-ahead label), and interpolation
 * between two quotes invents a price the venue never showed.
 */
export function pickHorizonPrice(
  points: PricePoint[],
  targetMs: number,
  maxStalenessMs: number = HORIZON_MAX_STALENESS_MS
): HorizonRead {
  if (!Number.isFinite(targetMs)) return { price: null, atMs: null, reason: "no_path" };
  if (points.length === 0) return { price: null, atMs: null, reason: "no_path" };
  let last: PricePoint | null = null;
  for (const pt of points) {
    if (pt.t * 1000 > targetMs) break;
    last = pt;
  }
  if (!last) return { price: null, atMs: null, reason: "no_print" };
  const atMs = last.t * 1000;
  if (targetMs - atMs > maxStalenessMs) return { price: null, atMs, reason: "stale" };
  // Exactly 0 or 1 is the venue's settlement mark, not a market price. Recording
  // it as a horizon price would teach a model that the market always resolves.
  if (last.p === 0 || last.p === 1) return { price: null, atMs, reason: "terminal_print" };
  return { price: last.p, atMs, reason: "ok" };
}

/** All three horizons, one basis. `decisionMs` is the journal row's createdAt (epoch ms). */
export function horizonReads(
  points: PricePoint[],
  decisionMs: number,
  maxStalenessMs: number = HORIZON_MAX_STALENESS_MS
): Record<HorizonKey, HorizonRead> {
  const out = {} as Record<HorizonKey, HorizonRead>;
  for (const h of HORIZONS) {
    out[h.key] = pickHorizonPrice(points, decisionMs + h.hours * 3_600_000, maxStalenessMs);
  }
  return out;
}
