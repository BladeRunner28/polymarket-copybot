/**
 * FEE BOOKING — the one fee helper for the paper ledger (Lane A, PROPOSAL stage).
 *
 * STATUS: NOT WIRED. Nothing in the live path imports this module yet. It is the
 * shared law + rate resolution for the approved-in-principle card
 * `fee-booking-net-ledger` (drafts/fee-booking-net-ledger-20261112.md), and it
 * exists so the dry-run backfill (scripts/backfill-fee-usd.ts) and the eventual
 * booking change cannot disagree about what a fee is.
 *
 * THE LAW IS IMPORTED, NEVER RE-IMPLEMENTED
 *   taker fee for C shares at price p = C * rate * p * (1 - p)
 *   -> fee/notional = rate * (1 - p)      (shares = sizeUsd / p)
 * Source of record: src/lib/scoring/price-edge.ts `takerFeePerShare` +
 * `categoryFeeRate`, cross-checked against the venue's own per-market schedule in
 * data/fee-sign-flip-report.json ($4,996.97 venue vs $5,024.02 proxy on 12,710
 * legs, 99.68% coverage). Do NOT add a fourth copy of this formula: there are
 * already two others in the tree (scripts/profit-fee-net.py for the read-side
 * instruments, and src/lib/shadow-jev.ts's `takerFeePerShare(price)` which is the
 * RETIRED archive-era 0.10*min(p,1-p) law and must not be used for booking).
 *
 * RATE RESOLUTION ORDER
 *   1. the venue's own published rate for that market slug, when captured
 *      (data/fee-schedules.jsonl -> feeSchedule.rate; capture-only, 40 slugs as of
 *      2026-11-12, so coverage is ~1.5% of the book and will grow)
 *   2. the slug-keyword proxy in price-edge.ts (default 0.05 / politics+finance
 *      0.04 / crypto 0.07)
 * The chosen basis is stamped on every row (`feeBasis`) so a later venue-truth
 * capture can be adopted without re-deriving the fee, and so a reader can tell a
 * modelled rate from a published one.
 *
 * WHAT A FEE IS *NOT*
 *   - It is not a PnL mutation. `realizedPnl` stays the price-path number it has
 *     always been; the fee lands in its own nullable column and the net figure is
 *     derived at read time. That keeps every historical figure and every rollup
 *     byte-identical and makes the change reversible by unsetting a flag.
 *   - It is not charged on a settlement. Holding to resolution and redeeming is
 *     not a sale, so only an early exit (status "closed", where we actually sell)
 *     pays the second fee. `feeUsdAtExit` is therefore only meaningful on closed
 *     rows.
 *   - It is not charged twice on the same side of the same trade: the entry fee is
 *     stamped at booking (the row's own booked entry price), the exit fee at close
 *     (the row's own exit price).
 */

import { categoryFeeRate, takerFeePerShare } from "./scoring/price-edge";

/** Which notional the booked net figure charges. Stamped per row in `feeBasis`. */
export type FeeBasis = "entry" | "two";

/**
 * FEE_NET_LEDGER — the read-side switch. DEFAULT OFF: with it unset, every
 * published number reads exactly what it read before this change existed.
 * The ledger write (feeUsd columns) is independent of this flag: stamping is
 * additive and harmless even while the read stays gross, which is what lets the
 * operator measure the fee on the live book before publishing a net number.
 */
export function feeNetLedgerEnabled(): boolean {
  const v = (process.env.FEE_NET_LEDGER ?? "").trim().toLowerCase();
  return v === "1" || v === "true" || v === "on";
}

export interface FeeRateResolution {
  rate: number;
  /** "venue" = the venue's published schedule for this market; "proxy" = slug keywords */
  source: "venue" | "proxy";
  /** category implied by the keyword map (diagnostic only) */
  category: string;
}

/**
 * Resolve the taker rate for one market. `venueRates` is a slug -> rate map built
 * from data/fee-schedules.jsonl (see `venueRateMap` in the backfill script).
 * Never throws; a market with no slug and no rate falls back to the proxy default.
 */
export function resolveFeeRate(
  marketSlug: string | null | undefined,
  venueRates?: Map<string, number> | Record<string, number>
): FeeRateResolution {
  const slug = (marketSlug ?? "").trim();
  if (slug && venueRates) {
    const hit = venueRates instanceof Map ? venueRates.get(slug) : venueRates[slug];
    if (typeof hit === "number" && Number.isFinite(hit) && hit >= 0 && hit < 1) {
      return { rate: hit, source: "venue", category: "venue-schedule" };
    }
  }
  const rate = categoryFeeRate(slug);
  return { rate, source: "proxy", category: rate === 0.07 ? "crypto" : rate === 0.04 ? "politics-finance" : "other" };
}

/**
 * Entry taker fee in dollars on a booked leg.
 * shares = sizeUsd / price, so fee = sizeUsd * rate * (1 - price).
 * Returns 0 for a non-finite/out-of-range price rather than NaN: a NaN fee would
 * poison every SUM it touches.
 */
export function feeUsdAtEntry(price: number, sizeUsd: number, rate: number): number {
  if (!Number.isFinite(price) || price <= 0 || price >= 1) return 0;
  if (!Number.isFinite(sizeUsd) || sizeUsd <= 0) return 0;
  if (!Number.isFinite(rate) || rate < 0) return 0;
  return round2((sizeUsd / price) * takerFeePerShare(price, rate));
}

/**
 * Exit taker fee in dollars — charged only where we actually SELL (early exit).
 * `exitPrice` is the price the leg was closed at; pass the implied exit price when
 * only realizedPnl is known (see `impliedExitPrice`).
 */
export function feeUsdAtExit(price: number, sizeUsd: number, exitPrice: number, rate: number): number {
  if (!Number.isFinite(price) || price <= 0 || price >= 1) return 0;
  if (!Number.isFinite(sizeUsd) || sizeUsd <= 0) return 0;
  if (!Number.isFinite(exitPrice) || exitPrice <= 0 || exitPrice > 1) return 0;
  if (!Number.isFinite(rate) || rate < 0) return 0;
  const shares = sizeUsd / price;
  return round2(shares * takerFeePerShare(exitPrice, rate));
}

/**
 * The exit price implied by the booked PnL identity, clamped to (0,1):
 *   pnl = shares * exit - sizeUsd  =>  exit = price * (1 + pnl/sizeUsd)
 * Used only where the row does not carry an exit price (PaperTrade does not: an
 * early exit books realizedPnl at closedAt and leaves currentPrice at its mark).
 */
export function impliedExitPrice(price: number, sizeUsd: number, realizedPnl: number): number {
  if (!Number.isFinite(price) || price <= 0) return 0;
  if (!Number.isFinite(sizeUsd) || sizeUsd <= 0) return 0;
  const c = price * (1 + (realizedPnl || 0) / sizeUsd);
  return Math.min(Math.max(c, 0), 1);
}

export interface FeeableLeg {
  entryPrice: number;
  simulatedPositionSize: number;
  realizedPnl?: number | null;
  status?: string | null;
  marketId?: string | null;
}

export interface BookedFee {
  rate: number;
  rateSource: "venue" | "proxy";
  /** entry fee, always booked */
  entry: number;
  /** exit fee, booked only for an early exit (status "closed") */
  exit: number;
  total: number;
}

/**
 * The whole booked fee for one leg, on the basis that runs (`entry` or `two`).
 * `two` charges the exit fee only where a real sell happened — a resolved leg was
 * held to settlement and pays nothing on the way out.
 */
export function bookedFee(
  leg: FeeableLeg,
  opts: { basis?: FeeBasis; venueRates?: Map<string, number> | Record<string, number>; defaultRate?: number } = {}
): BookedFee {
  const basis = opts.basis ?? "two";
  const res = resolveFeeRate(leg.marketId, opts.venueRates);
  const rate = res.source === "venue" ? res.rate : opts.defaultRate ?? res.rate;
  const entry = feeUsdAtEntry(leg.entryPrice, leg.simulatedPositionSize, rate);
  let exit = 0;
  if (basis === "two" && leg.status === "closed") {
    const px = impliedExitPrice(leg.entryPrice, leg.simulatedPositionSize, leg.realizedPnl ?? 0);
    exit = feeUsdAtExit(leg.entryPrice, leg.simulatedPositionSize, px, rate);
  }
  return { rate, rateSource: res.source, entry, exit, total: round2(entry + exit) };
}

/** Net PnL for one leg: booked realizedPnl minus the booked fee. */
export function netPnl(leg: FeeableLeg & { feeUsd?: number | null; feeExitUsd?: number | null }): number {
  return round2((leg.realizedPnl ?? 0) - (leg.feeUsd ?? 0) - (leg.feeExitUsd ?? 0));
}

function round2(x: number): number {
  return Math.round(x * 100) / 100;
}
