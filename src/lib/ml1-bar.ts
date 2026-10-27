/**
 * The ML-1 promotion bar, stated RELATIVELY to the comparator it names.
 *
 * WHY THIS MODULE EXISTS (card `ml1-price-baseline-drift`). The in-force constants
 * (`BAR` = AUC 0.729 / Brier 0.212 in `ml1-read.ts`) were never a margin over price — they are
 * price's OWN numbers on `data/decision-dataset.csv` rounded to three decimals
 * (measured 2026-09-13: 0.7285 / 0.2115 -> printed as 0.729 / 0.212). Read as an absolute
 * threshold and carried onto a different population, they say something the author never
 * intended: "beat price by 0.0195 AUC" on the re-pointed book, where price itself scores
 * 0.7095 / 0.2196 — i.e. 0.0076 Brier on the WRONG side of its own ceiling.
 *
 * WHAT THIS MODULE IS: the arithmetic of the restatement (price + the rounding slack the
 * original constants allowed) and the verdict test under it. Nothing here is wired into
 * `ml1-read.ts`, and `BAR` keeps enforcing exactly what it enforced before. The restatement
 * is a Lane A change — a prereg floor's basis — so it goes live only on the operator's yes
 * (card tagged `awaiting-approval`).
 */

/** The slack the in-force constants allowed over price on the population they were measured on. */
export const BAR_SLACK = { auc: 0.0005, brier: 0.0005 } as const;

/** Price-only read on a holdout: the thing the bar is relative to. */
export type PriceRead = { auc: number; brier: number };
/** A bar in absolute AUC/Brier terms. */
export type BarRead = { auc: number; brier: number };
export type ArmRead = { auc: number; brier: number | null };

/**
 * The restated bar: price-only on the SAME holdout, plus the same slack the original constants
 * carried. Relative by construction, so it cannot become unreachable when the population moves —
 * which is the defect the card names.
 */
export function relativeBar(price: PriceRead): BarRead {
  return { auc: price.auc + BAR_SLACK.auc, brier: price.brier + BAR_SLACK.brier };
}

/**
 * How much a candidate must beat price by to clear `bar`. Positive AUC = headroom demanded;
 * negative Brier = price is already above the ceiling (no candidate-exists reachable by copying price).
 */
export function demandedMargin(price: PriceRead, bar: BarRead): { auc: number; brier: number } {
  return { auc: bar.auc - price.auc, brier: bar.brier - price.brier };
}

/**
 * Does an arm clear `bar`? `brier` is null for arms that are not probabilities (scores), which
 * leaves the Brier leg undecided rather than silently passing it.
 */
export function clearsBar(arm: ArmRead, bar: BarRead): { auc: boolean; brier: boolean | null; both: boolean | null } {
  const a = arm.auc >= bar.auc;
  const b = arm.brier === null ? null : arm.brier <= bar.brier;
  return { auc: a, brier: b, both: b === null ? null : a && b };
}

/**
 * The falsifiable check on the slack itself: applied to the price read on the bar's OWN
 * population, `relativeBar` must reproduce the in-force constants. If it does not, the
 * restatement's basis is wrong and no read from it counts.
 *
 * PASS THE RECORDED READ, NOT A FRESH ONE. The constants were cut from the 2026-09-13 snapshot
 * of `data/decision-dataset.csv` (0.7285 / 0.2115). Recomputed on today's file that population
 * reads 0.7292 / 0.2110 because the export has grown since — that is population drift, a
 * separate number to print and not a failure of this slack. Mixing the two would let a moving
 * file masquerade as a wrong derivation.
 */
export function reproducesInForceBar(
  priceOnBarPopulation: PriceRead,
  bar: BarRead,
  tol = 0.0005
): boolean {
  const r = relativeBar(priceOnBarPopulation);
  return Math.abs(r.auc - bar.auc) <= tol && Math.abs(r.brier - bar.brier) <= tol;
}
