/**
 * Band-scoped size factor (2026-09-20 C-200 daily report change 1, user-approved).
 *
 * APPROVED INTENT: halve the size of new C-200 copies entering the 0.60–0.80 band —
 * the one significant NEGATIVE band (excess −0.0995, z=−3.96 on N=382) that produced
 * essentially nothing (+$2.66 over 30d on $1,015 of flow) while absorbing a third of
 * the day's new positions.
 *
 * WHY THIS IS NOT THE PREMIUM OVERLAY FLAG. The rec named `premiumOverlayEnabled
 * 0 → 1`, but that overlay resizes only copies with `!kellySized && lane !==
 * "short_ttr"` — and every 0.60–0.80 copy in the book is a short-TTR LANE copy
 * (84 of the last 87 opens booked at exactly $4.99 = the fixed lane size × the 0.5
 * band map; zero Kelly admits, because Kelly refuses λ̂>0 bands). Flipping the flag
 * is therefore a provable NO-OP for the band the change targets, and it would
 * instead resize non-lane/non-Kelly copies in OTHER bands. It is also inexpressible
 * as "scoped to 0.60–0.80": the overlay is band-driven by construction and would
 * BOOST the <0.20 band by 1.39× (λ̂=−0.789), the exact tail-variance increase the
 * same report argues against ("prefer count over size there").
 *
 * So the delta is implemented where it can actually bind: one band-scoped factor on
 * the FINAL size, whatever lane booked it. Pure and unit-tested; the caller owns the
 * ruleset values.
 */

/** Parse a "lo-hi" range (e.g. "0.6-0.8"). Empty/invalid → null (disabled). */
export function parseBandRange(range: string): { lo: number; hi: number } | null {
  if (!range) return null;
  const m = range.trim().match(/^(\d*\.?\d+)\s*-\s*(\d*\.?\d+)$/);
  if (!m) return null;
  const lo = Number(m[1]);
  const hi = Number(m[2]);
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return null;
  return { lo, hi };
}

/**
 * Apply the factor when the entry price is inside the range. 0/empty factor or an
 * unparseable range = no change (legacy semantics), so a rule revert is one field.
 */
export function applyBandSizeFactor(sizeUsd: number, price: number, factor: number, range: string): number {
  if (!(factor > 0) || factor === 1) return sizeUsd;
  const parsed = parseBandRange(range);
  if (!parsed) return sizeUsd;
  if (price < parsed.lo || price >= parsed.hi) return sizeUsd;
  return sizeUsd * factor;
}
