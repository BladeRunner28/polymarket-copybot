/**
 * Lag persistence — the pure arithmetic behind the wallet-lag-persistence read.
 *
 * WHY THIS EXISTS (roadmap card wallet-lag-persistence-ranker, Lane B measurement).
 * Every score we rank wallets with (ROI / consistency / copyability / win rate) is
 * measured on the wallet OWN fill price. None of them says whether the edge survives
 * a delayed copy, which is the only property that matters when our own fill is late,
 * gated or re-priced. This module holds the two pieces that must be exact:
 *
 *   1. PRICE AT LAG: given the print tape we recorded for one (market, token) leg and
 *      a lag target t + L, which recorded print is the one a copy would have paid, and
 *      how stale is it? A print is only admissible when it sits within a stated window
 *      of the target, so a thin leg yields null instead of a fabricated price.
 *   2. COUNTERFACTUAL RETURN per dollar staked: payout / price - 1, with payout in
 *      {0, 1} from venue truth. Null when the price is unusable (<= 0 or > 1), never
 *      silently clamped.
 *
 * Aggregation lives here too so the read cannot re-derive it two ways: summariseCells
 * produces one cell per (wallet, lag) on the SAME grain the aggregate table prints.
 *
 * Pure functions only: no DB, no clock, no network. Every caller supplies the tape.
 */

/** One recorded print on the tape: epoch ms and the price it traded at. */
export type TapePrint = { ts: number; price: number };

export type LagPrice = {
  price: number;
  /**
   * "print_at_or_before" = the last print at or before the target (the honest case).
   * "print_after" = nothing printed by the target, but one printed inside the grace
   * window after it, which still bounds what a slightly late copy would pay.
   */
  basis: "print_at_or_before" | "print_after";
  /** Absolute distance from the lag target to the print used, in ms. */
  stalenessMs: number;
};

/** 0 / +10m / +30m / +1h — the lags the card asks for. */
export const LAGS_MS: readonly number[] = [0, 600_000, 1_800_000, 3_600_000];

/** A print older than 20 minutes before the target is too stale to price a copy. */
export const DEFAULT_STALENESS_MS = 1_200_000;

/** A print up to 5 minutes AFTER the target bounds a slightly late copy. */
export const DEFAULT_GRACE_MS = 300_000;

export type PriceAtLagOpts = { maxStalenessMs?: number; graceMs?: number };

/** A tradable price is strictly above zero and at most one dollar. */
export function isValidPrice(p: number | null | undefined): p is number {
  return typeof p === "number" && Number.isFinite(p) && p > 0 && p <= 1;
}

/** Sort a tape into ascending time order (stable on equal timestamps). */
export function sortPrints(prints: readonly TapePrint[]): TapePrint[] {
  return prints.slice().sort((a, b) => a.ts - b.ts);
}

/**
 * The print a copy at `t + lagMs` would have paid, or null when the tape cannot say.
 *
 * `prints` MUST be sorted ascending by ts (use sortPrints). The scan walks back from
 * the grace boundary, which keeps this O(k) on the tiny windows the read uses.
 */
export function priceAtLag(
  prints: readonly TapePrint[],
  t: number,
  lagMs: number,
  opts: PriceAtLagOpts = {}
): LagPrice | null {
  const maxStaleness = opts.maxStalenessMs ?? DEFAULT_STALENESS_MS;
  const grace = opts.graceMs ?? DEFAULT_GRACE_MS;
  const target = t + lagMs;
  const limit = target + grace;
  for (let i = prints.length - 1; i >= 0; i--) {
    const p = prints[i];
    if (p.ts > limit) continue;
    if (!isValidPrice(p.price)) continue;
    const after = p.ts > target;
    const staleness = Math.abs(target - p.ts);
    if (!after && staleness > maxStaleness) return null;
    return { price: p.price, basis: after ? "print_after" : "print_at_or_before", stalenessMs: staleness };
  }
  return null;
}

/**
 * Counterfactual return per dollar staked: a copy that paid `price` and settled at
 * `payout` (1 = the token won, 0 = it lost). Null when the price is not tradable.
 *
 * This is RETURN ON COST, not edge per share: a 0.40 entry that wins returns +1.50,
 * and the same entry losing returns -1.00. Quoting edge per share instead would make
 * a cheap longshot look small next to an expensive favourite, which is exactly the
 * bias a lag measurement must not carry.
 */
export function copyReturnPerDollar(payout: number, price: number): number | null {
  if (!isValidPrice(price)) return null;
  if (payout !== 0 && payout !== 1) return null;
  return payout / price - 1;
}

export type LagCell = {
  n: number;
  meanRet: number;
  medianRet: number;
  /** Share of priced legs whose counterfactual return is strictly positive. */
  winRate: number;
};

export type LagLeg = { wallet: string; lagMs: number; ret: number | null };

function cell(rets: readonly number[]): LagCell {
  const n = rets.length;
  const meanRet = rets.reduce((a, b) => a + b, 0) / n;
  const sorted = rets.slice().sort((a, b) => a - b);
  const mid = Math.floor(n / 2);
  const medianRet = n % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  const wins = rets.filter((r) => r > 0).length;
  return { n, meanRet, medianRet, winRate: wins / n };
}

/**
 * One cell per (wallet, lag). Legs with a null return are COUNTED OUT of the cell and
 * never treated as a zero, so an unpriced leg cannot flatter a wallet.
 */
export function summariseCells(legs: readonly LagLeg[]): Map<string, Map<number, LagCell>> {
  const by = new Map<string, Map<number, number[]>>();
  for (const leg of legs) {
    if (leg.ret === null) continue;
    if (!Number.isFinite(leg.ret)) continue;
    let lags = by.get(leg.wallet);
    if (!lags) {
      lags = new Map<number, number[]>();
      by.set(leg.wallet, lags);
    }
    const list = lags.get(leg.lagMs) ?? [];
    list.push(leg.ret);
    lags.set(leg.lagMs, list);
  }
  const out = new Map<string, Map<number, LagCell>>();
  for (const [wallet, lags] of by) {
    const cells = new Map<number, LagCell>();
    for (const [lagMs, rets] of lags) cells.set(lagMs, cell(rets));
    out.set(wallet, cells);
  }
  return out;
}

/**
 * The drop from one lag to another for one wallet, in return-per-dollar units.
 * Negative means the edge decays with delay; positive means it improves. Null when
 * either lag has no priced legs for that wallet.
 */
export function persistenceDelta(
  cells: Map<string, Map<number, LagCell>>,
  wallet: string,
  fromLagMs: number,
  toLagMs: number
): number | null {
  const w = cells.get(wallet);
  if (!w) return null;
  const a = w.get(fromLagMs);
  const b = w.get(toLagMs);
  if (!a || !b) return null;
  return b.meanRet - a.meanRet;
}

/** Population mean of priced legs at one lag — the aggregate table row. */
export function meanRetAtLag(legs: readonly LagLeg[], lagMs: number): number | null {
  const rets = legs.filter((l) => l.lagMs === lagMs && l.ret !== null).map((l) => l.ret as number);
  if (rets.length === 0) return null;
  return rets.reduce((a, b) => a + b, 0) / rets.length;
}
