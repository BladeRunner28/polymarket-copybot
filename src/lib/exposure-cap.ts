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
 * v74 (kelly rec 4, approved via the approvals inbox 2026-11-13; measured 2026-11-13 on card
 * `kelly-single-loss-concentration-test`): CONCURRENT LONG-SHOT concentration rail.
 *
 * Why a container rather than a better per-leg cap: the $100 Kelly clip is already the per-leg
 * bound, and measuring the legs that sit at it says tightening it is not supported (60 C-200 legs
 * at the $100 clip book +$3,141.77 lifetime, but the top 10 carry +$5,749.83 and the other 50 are
 * −$2,608.06 — an apparent edge that is a top-10 artefact). What was unbounded is the SUM: the
 * open C-200 long-shot book reached 60.85% of realised net worth on 2026-09-14 ($1,121 at risk on
 * NW $1,842) and STANDARD reached 21.33%, so a single bad weekend across the cluster is a
 * drawdown the whole-equity 20% gate only sees after the fact.
 *
 * BOUNDARY: fires only ABOVE the ceiling, like v55/v58 — a projected level that lands exactly on
 * the cap is allowed. Disabled by `pctOfNetWorth <= 0` OR `netWorthUsd <= 0` (a lane with no
 * accounting identity cannot be ratio-managed; refusing every leg there would be an
 * un-budgeted halt, so the rail reports `capUsd: 0` and lets the caller log it).
 *
 * Pure — the caller owns the running total and applies the increment at the BOOKING point.
 */
export interface LongshotConcurrencyInput {
  openLongshotNotionalUsd: number;
  sizeUsd: number; // 0 when the incoming leg is not a long-shot
  pctOfNetWorth: number; // rule value; 20 means "20% of realised net worth"
  netWorthUsd: number; // REALISED net worth: principal + realised PnL
}

export interface LongshotConcurrencyDecision {
  blocked: boolean;
  why?: string;
  capUsd: number;
  projectedUsd: number;
  pctBefore: number;
  pctAfter: number;
}

export function longshotConcurrencyDecision(i: LongshotConcurrencyInput): LongshotConcurrencyDecision {
  const projected = i.openLongshotNotionalUsd + i.sizeUsd;
  const pctBefore = i.netWorthUsd > 0 ? i.openLongshotNotionalUsd / i.netWorthUsd : 0;
  const pctAfter = i.netWorthUsd > 0 ? projected / i.netWorthUsd : 0;
  const capUsd = i.pctOfNetWorth > 0 && i.netWorthUsd > 0 ? (i.pctOfNetWorth / 100) * i.netWorthUsd : 0;
  if (capUsd <= 0) {
    return { blocked: false, capUsd: 0, projectedUsd: projected, pctBefore, pctAfter };
  }
  // An INCOMING leg that is not a long-shot adds nothing to the cluster, so the rail must be
  // inert for it even when the LONG-SHOT book is already over its cap (a lane can be over the
  // cap while the book is being wound down, and refusing every high-price leg as well would be a
  // different rule than the one approved — a lane brake, not this rail).
  if (i.sizeUsd <= 0) {
    return { blocked: false, capUsd, projectedUsd: i.openLongshotNotionalUsd, pctBefore, pctAfter: pctBefore };
  }
  if (projected > capUsd) {
    return {
      blocked: true,
      why: `long-shot $${projected.toFixed(2)} > cap $${capUsd.toFixed(2)} (${(pctAfter * 100).toFixed(2)}% > ${i.pctOfNetWorth}% of NW $${i.netWorthUsd.toFixed(2)})`,
      capUsd,
      projectedUsd: projected,
      pctBefore,
      pctAfter,
    };
  }
  return { blocked: false, capUsd, projectedUsd: projected, pctBefore, pctAfter };
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
