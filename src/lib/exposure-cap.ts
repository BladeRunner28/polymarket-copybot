/**
 * Equity-linked gross-exposure cap (v46, 2026-09-03, user-approved).
 *
 * The C-200 book's gross-exposure ceiling is no longer a fixed rule value:
 *   effective cap = base + 0.5 × max(0, net worth − principal)
 *
 * - Grows only on net worth ABOVE starting principal (real recovery — the
 *   current −$269 realized hole must be repaid first).
 * - SYMMETRIC: shrinks back automatically when net worth falls below the
 *   level that justified the higher cap.
 * - Recomputed every scoring cycle and on the dashboard, so the enforced
 *   number and the displayed number are always the same formula.
 *
 * The stored rule `maxGrossExposureUsd` remains the BASE — ruleset values
 * are unchanged (no ruleset bump needed; behavior derives from this helper).
 */

/**
 * Effective exposure cap for a bot book.
 *
 * @param baseUsd     stored rule value (maxGrossExposureUsd) — the floor
 * @param netWorth    principal + realized PnL + Σ open unrealized
 * @param principal   starting principal; when 0/unknown, no scaling applies
 *                    (can't verify recovery against an unknown baseline)
 */
export function effectiveExposureCap(baseUsd: number, netWorth: number, principal: number): number {
  if (principal <= 0 || baseUsd <= 0) return baseUsd;
  return baseUsd + 0.5 * Math.max(0, netWorth - principal);
}

/** Human note for the dashboard — shows the derivation in one line. */
export function exposureCapNote(baseUsd: number, netWorth: number, principal: number): string {
  const eff = effectiveExposureCap(baseUsd, netWorth, principal);
  if (eff <= baseUsd) return `$${eff.toFixed(0)} (base $${baseUsd} — net worth below principal)`;
  return `$${eff.toFixed(0)} = $${baseUsd} + 50% × $${Math.max(0, netWorth - principal).toFixed(0)} above principal`;
}
