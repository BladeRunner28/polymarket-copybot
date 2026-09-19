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

/**
 * v55 (2026-09-16 C-200 daily report Change 1, user-approved): per-market
 * concentration ceiling. `maxMarketSlugPositions` counts the research CATEGORY
 * (a slug wraps many markets), so nothing capped legs in a single marketId; with
 * v54's 2.5x long-shot factor the band's average clip is ~$33, so one binary can
 * absorb $250+. Two limits, whichever binds first; 0 disables either.
 *
 * Pure — the caller owns the maps and applies the increments.
 */
export interface MarketCapInput {
  legsAlready: number;
  notionalAlready: number;
  sizeUsd: number;
  maxLegs: number;
  notionalCapUsd: number;
}

export interface MarketCapDecision {
  blocked: boolean;
  why?: string;
}

export function marketCapDecision(i: MarketCapInput): MarketCapDecision {
  const legs = i.legsAlready + 1;
  const projected = i.notionalAlready + i.sizeUsd;
  if (i.maxLegs > 0 && legs > i.maxLegs) {
    return { blocked: true, why: `legs ${legs} > max ${i.maxLegs}` };
  }
  if (i.notionalCapUsd > 0 && projected > i.notionalCapUsd) {
    return {
      blocked: true,
      why: `notional $${projected.toFixed(2)} > cap $${i.notionalCapUsd.toFixed(2)}`,
    };
  }
  return { blocked: false };
}

/**
 * v58 (2026-09-19 tuning review #30 rec 1, user-approved): per-WALLET
 * concentration ceiling — the mirror of `marketCapDecision`, applied to the
 * copying WALLET instead of the marketId.
 *
 * Why the wallet axis: at the v55 activation the two rails confounded each
 * other (a per-wallet limit could also have cut per-market accumulation), so
 * #29 deliberately held the wallet rail back until the market rail was
 * MEASURED. It now is — 10 blocks, all 2026-09-18 08:36-08:52 at the pre-growth
 * $125.12 ceiling, 0 since the cap rose to $1,734.50, max 2 legs/market — i.e.
 * non-binding, while one wallet carries 84.6% of the book. No leg limit here:
 * `maxMarketLegsPerMarketId` already bounds legs per market, and a wallet
 * ceiling on legs would be a different rule than the one approved.
 *
 * Pure — the caller owns the map and applies the increment.
 */
export interface WalletCapInput {
  notionalAlready: number;
  sizeUsd: number;
  notionalCapUsd: number;
}

export interface WalletCapDecision {
  blocked: boolean;
  why?: string;
}

export function walletCapDecision(i: WalletCapInput): WalletCapDecision {
  const projected = i.notionalAlready + i.sizeUsd;
  if (i.notionalCapUsd > 0 && projected > i.notionalCapUsd) {
    return {
      blocked: true,
      why: `notional $${projected.toFixed(2)} > cap $${i.notionalCapUsd.toFixed(2)}`,
    };
  }
  return { blocked: false };
}

/**
 * #29 rec 2 (2026-09-19, user-approved): is this veto reason a PORTFOLIO gate?
 *
 * Portfolio gates fire BEFORE the per-bot leg loop, so when they block everything
 * the cycle produces no copies, no leg-block reasons and no other signal — the
 * Sep 16-18 freeze ran 39.7h undetected. These two reasons are the ones that can
 * halt the whole book; per-market/per-token gates are scoped and cannot.
 */
export function isPortfolioGate(reason: string): boolean {
  return /drawdown gate|gross exposure cap/.test(reason);
}
