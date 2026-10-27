/**
 * Maturity (time-to-resolution at ENTRY) size factor — STANDARD lane, v68.
 *
 * APPROVED 2026-10-27 ("approve standard-maturity-size-factor"). Lane A: this changes how much the
 * bot risks, so it is a ruleset value, defaulted OFF here (every factor 1.0 = byte-identical legacy
 * behaviour) and switched on only by a RuleSet row.
 *
 * THE FINDING IT ENCODES
 *   STANDARD sizes flat across a maturity axis whose realised ROI differs by more than 9x:
 *     <24h  1,845 legs, clip $11.20, -6.0%
 *     24-72h  704 legs, clip $10.00, +2.0%
 *     >=72h 3,338 legs, clip  $9.00, +21.4%
 *   The schedule 0.5 / 1.0 / 1.5 measured +$5,028 all-time and +$4,397 per 90d (90d CI
 *   [+1,018, +8,275], excluding zero, at 90d CI on the sized book), with the inverse control
 *   losing $6,939 — so the direction is not a coin flip dressed as a schedule.
 *
 * WHY TTL AT ENTRY AND NOT HOLDING TIME
 *   Only one of the two is a variable a rule can act on BEFORE the trade. Realised holding time is
 *   post-treatment: it is known only after the position closed, so a rule keyed on it cannot be
 *   executed and any backtest of it is lookahead. Time-to-resolution at entry is available at
 *   decision time (last MarketSnapshot at or before entry + 15 min), has no lookahead, and is the
 *   axis the measurement used.
 *
 * WHAT THIS DELIBERATELY DOES NOT DO
 *   It does not clamp. `clampPaperSize` (src/lib/safety.ts) applies BOT_LIMITS {min 0.25, max 20.00}
 *   to the FINAL size, i.e. AFTER this factor, so a 1.5x on an $18 clip books $20 and not $27. The
 *   shadow that justified the change applied exactly that clamp before quoting its effect, so the
 *   quoted +$4,397 already accounts for it. Adding a second clamp here would double-count and would
 *   also make the helper disagree with the code path that actually runs.
 *
 * BOUNDARY SEMANTICS (must match the measurement, which used ttl<24 -> 0, ttl<72 -> 1, else 2)
 *   ttr <  shortHours            -> factorShort
 *   ttr >= shortHours, < longHours -> factorMedium
 *   ttr >= longHours             -> factorLong
 *   So 24.000 is medium (not short) and 72.000 is long (not medium). Pinned by tests: an off-by-one
 *   on either boundary silently moves the biggest cohort by one bucket.
 */

export type MaturityFactors = {
  short: number;
  medium: number;
  long: number;
  shortHours: number;
  longHours: number;
};

/**
 * Apply the maturity factor to a STANDARD entry size.
 *
 * Returns `sizeUsd` UNCHANGED — never 0, never a floor — when:
 *   * the factors are disabled (all 1.0, the default) or any is non-finite/non-positive,
 *   * the TTL is unknown (null/undefined/NaN) or negative,
 *   * the hour boundaries are not a sane ascending pair.
 *
 * The "unchanged when unknown" rule is the important one: an unmeasured leg must fall back to the
 * live flat size, not to the down-weight. Treating "unknown" as "<24h" would silently down-size every
 * leg whose market had no snapshot, which is a real population (the shadow's TTL join drops those
 * legs entirely rather than guessing — see profit-velocity.py ttl_edges).
 */
export function applyMaturitySizeFactor(
  sizeUsd: number,
  ttrHours: number | null | undefined,
  f: MaturityFactors | null | undefined
): number {
  if (!f) return sizeUsd;
  if (!Number.isFinite(sizeUsd) || sizeUsd <= 0) return sizeUsd;
  if (!(f.shortHours > 0) || !(f.longHours > f.shortHours)) return sizeUsd;
  for (const v of [f.short, f.medium, f.long]) {
    if (!Number.isFinite(v) || !(v > 0)) return sizeUsd;
  }
  // Disabled: all three at 1.0 is the legacy path and must not even bucket the leg.
  if (f.short === 1 && f.medium === 1 && f.long === 1) return sizeUsd;
  if (ttrHours === null || ttrHours === undefined) return sizeUsd;
  const ttl = Number(ttrHours);
  if (!Number.isFinite(ttl) || ttl < 0) return sizeUsd;

  const w = ttl < f.shortHours ? f.short : ttl < f.longHours ? f.medium : f.long;
  return sizeUsd * w;
}

/** Bucket name for logging/tests only — never used to size anything. */
export function maturityBucket(
  ttrHours: number | null | undefined,
  f: MaturityFactors
): "short" | "medium" | "long" | "unknown" {
  if (ttrHours === null || ttrHours === undefined) return "unknown";
  const ttl = Number(ttrHours);
  if (!Number.isFinite(ttl) || ttl < 0) return "unknown";
  return ttl < f.shortHours ? "short" : ttl < f.longHours ? "medium" : "long";
}
