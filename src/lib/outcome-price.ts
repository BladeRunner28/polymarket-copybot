/**
 * Price of the token a leg actually holds.
 *
 * WHY THIS EXISTS
 * ---------------
 * `MarketState.yesPrice` / `noPrice` are POSITIONAL: the adapter sets
 * `yesPrice = outcomePrices[0]`, `noPrice = outcomePrices[1]`. On a binary
 * `["Yes","No"]` market that is correct. On a market whose tokens are named —
 * `["Under","Over"]`, `["Vitality","9z"]`, moneyline team names — the label
 * `"NO"` never appears, so every
 * `outcome === "NO" ? noPrice : yesPrice` call site fell through to the FIRST
 * token and priced the leg at the other side's price.
 *
 * Measured cost (`scripts/profit-price-side.py`, 2026-11-08): 87 regime legs
 * (4.1% of the book) booked the complement of the price the copied wallet paid
 * for the same labelled outcome — median mirror distance 0.007 around 0.50,
 * i.e. arithmetic, not price movement. A favourite booked at its complement is
 * a fake longshot: it pays `(1-p)/p` on a win while costing the same `-stake`
 * on a loss, so the error is ONE-SIDED — it invents wins and leaves losses
 * alone — and it carried 56% of the book's booked PnL.
 *
 * The venue already ships token labels next to token prices
 * (`MarketState.outcomeLabels` / `outcomePrices`). This module reads the price
 * BY LABEL, and keeps behaviour byte-identical for `YES`/`NO` labels and for
 * payloads that carry no token list at all.
 *
 * Read-only: pure functions over a market payload. No I/O, no rule, no size.
 */
import { normalizeOutcomeLabel } from "./resolution";
import type { MarketState } from "./types";

type PricableMarket = Pick<
  MarketState,
  "yesPrice" | "noPrice" | "outcomeLabels" | "outcomePrices"
>;

/** A finite price inside [0, 1]; anything else is not a usable venue price. */
function usable(price: unknown): number | undefined {
  if (typeof price !== "number" || !Number.isFinite(price)) return undefined;
  if (price < 0 || price > 1) return undefined;
  return price;
}

/**
 * The price of the token labelled `outcomeLabel`, or `undefined` when the
 * payload cannot say.
 *
 * Order of evidence:
 *   1. the venue's own token list (the only path that can price a named
 *      outcome — this is the fix),
 *   2. binary yes/no semantics for payloads without a token list,
 *   3. no claim (callers keep their previous behaviour rather than guess).
 */
export function priceForOutcome(
  market: PricableMarket,
  outcomeLabel: string | null | undefined
): number | undefined {
  const want = normalizeOutcomeLabel(outcomeLabel);
  if (!want) return undefined;

  const labels = market.outcomeLabels;
  const prices = market.outcomePrices;
  if (labels && prices && labels.length === prices.length && labels.length > 0) {
    const idx = labels.findIndex((l) => normalizeOutcomeLabel(l) === want);
    if (idx >= 0) {
      const hit = usable(prices[idx]);
      if (hit !== undefined) return hit;
    }
  }

  if (want === "YES") {
    return usable(market.yesPrice) ?? (usable(market.noPrice) !== undefined ? 1 - (market.noPrice as number) : undefined);
  }
  if (want === "NO") {
    return usable(market.noPrice) ?? (usable(market.yesPrice) !== undefined ? 1 - (market.yesPrice as number) : undefined);
  }

  return undefined;
}

/**
 * Is `outcomeLabel` the market's FIRST (yes-side) token?
 *
 * Needed wherever a YES-frame number is derived from an outcome-side price
 * (sentiment aggregation signs its edge in the YES frame).
 *
 * Unknown labels return `true` — the pre-fix assumption — so a payload without
 * a token list behaves exactly as it did before this module existed.
 */
export function isYesSideOutcome(
  market: Pick<MarketState, "outcomeLabels">,
  outcomeLabel: string | null | undefined
): boolean {
  const want = normalizeOutcomeLabel(outcomeLabel);
  if (!want) return true;
  if (want === "YES") return true;
  if (want === "NO") return false;

  const labels = market.outcomeLabels;
  if (labels && labels.length > 0) {
    const idx = labels.findIndex((l) => normalizeOutcomeLabel(l) === want);
    if (idx >= 0) return idx === 0;
  }
  return true;
}
