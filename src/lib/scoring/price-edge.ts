/**
 * Price-edge score v1 — SHADOW ONLY.
 *
 * A calibrated P(copied token wins) as a function of the entry price, plus the
 * Polymarket taker-fee-aware expected-value gate that consumes it.
 *
 * STATUS: NOT WIRED INTO ANY LIVE PATH. `scoreTrade()` does not call this, and
 * nothing in scripts/ admits, sizes, or routes on it. The v1 spec FAILED its own
 * pre-registered acceptance test (see data/score-spec-v1.json
 * `acceptance_criteria.result`): the wallet-blocked improvement (+$1.23/trade,
 * n=564 of 3,481) has a wallet-cluster 95% CI of [-0.54, +2.62] that includes
 * zero, only 39% of wallets are non-negative, and under walk-forward the
 * improvement is NEGATIVE (-$0.18/trade). Do not gate on it until the
 * pre-registered test in drafts/scoring-fix-v1-impl-20260913.md passes.
 *
 * Spec source of record: data/score-spec-v1.json (fitted by
 * scripts/fit-price-edge.py on data/decision-dataset.csv). The constants below
 * are asserted to match that file by tests/price-edge.test.ts.
 *
 * Deliberately dependency-free and pure: no DB, no I/O, no rules object, so it can
 * be shadow-evaluated inside score-trades.ts later without side effects.
 */

export interface PriceEdgeSpec {
  specVersion: number;
  /** model = sigma(a + b * (logit(price) - mean) / sd) */
  mean: number;
  sd: number;
  a: number;
  b: number;
  /** admit iff P(win) - price - feePerShare(price) > margin */
  margin: number;
  /** default taker fee rate when the market category is unknown */
  defaultFeeRate: number;
  status: "shadow" | "admitted";
}

/** Fitted 2026-09-13 on 3,481 resolved copy decisions (188 wallets, 2026-07-15..09-12). */
export const PRICE_EDGE_SPEC_V1: PriceEdgeSpec = {
  specVersion: 1,
  mean: 0.6672113499908179,
  sd: 1.8361025406657638,
  a: 0.4991328447815187,
  b: 1.234131940373049,
  margin: 0.05,
  defaultFeeRate: 0.05,
  status: "shadow",
};

/**
 * Polymarket taker fee, expressed per share: fee = rate * p * (1 - p).
 * (Fee for C shares is C * rate * p * (1-p); shares = size / p, so the per-share
 * form is what a probability-space gate needs.) Source:
 * drafts/c200-taker-fee-measurement-2026-09-09.md, cross-checked against a live fill.
 */
export function takerFeePerShare(price: number, feeRate: number): number {
  return feeRate * price * (1 - price);
}

/**
 * Category taker-fee coefficients (docs.polymarket.com/trading/fees), inferred from
 * text because MarketSnapshot.category is NULL on every row. Mirrors the keyword map
 * in scripts/build-decision-dataset.py so the offline fit and the live score agree.
 */
export function categoryFeeRate(text: string | null | undefined): number {
  const t = (text ?? "").toLowerCase();
  const crypto = ["btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "token", "airdrop", "fdv", "market cap"];
  const politicsFin = ["election", "president", "senate", "congress", "nominee", "parliament", "prime minister",
    "fed", "rate cut", "inflation", "cpi", "gdp", "recession", "tariff", "stock", "nasdaq", "s&p", "earnings",
    "shutdown", "impeach", "poll", "vote", "governor", "mayor"];
  if (crypto.some((w) => t.includes(w))) return 0.07;
  if (politicsFin.some((w) => t.includes(w))) return 0.04;
  return PRICE_EDGE_SPEC_V1.defaultFeeRate;
}

/**
 * Calibrated P(win) for a copy entered at `price`.
 * Returns null for prices outside (0, 1) — callers must treat null as "no score",
 * never as 0 or 0.5.
 */
export function priceEdgeProbability(price: number, spec: PriceEdgeSpec = PRICE_EDGE_SPEC_V1): number | null {
  if (!Number.isFinite(price) || price <= 0 || price >= 1) return null;
  const logit = Math.log(price / (1 - price));
  const z = spec.a + spec.b * ((logit - spec.mean) / spec.sd);
  return 1 / (1 + Math.exp(-z));
}

export interface PriceEdgeResult {
  specVersion: number;
  /** shadow = computed for measurement only; must not influence admission/sizing */
  shadow: boolean;
  price: number;
  pWin: number;
  feeRate: number;
  feePerShare: number;
  /** expected value per share before the margin: pWin - price - feePerShare */
  edge: number;
  /** edge > margin */
  admit: boolean;
  reason: string;
}

/**
 * Compute the v1 price-edge view of a candidate copy. Pure; never throws on
 * plausible inputs. `admit` is a MEASUREMENT OUTPUT in v1 (status: "shadow") —
 * do not use it to open positions.
 */
export function priceEdge(
  price: number,
  opts: { feeRate?: number; spec?: PriceEdgeSpec } = {}
): PriceEdgeResult | null {
  const spec = opts.spec ?? PRICE_EDGE_SPEC_V1;
  const pWin = priceEdgeProbability(price, spec);
  if (pWin === null) return null;
  const feeRate = opts.feeRate ?? spec.defaultFeeRate;
  const feePerShare = takerFeePerShare(price, feeRate);
  const edge = pWin - price - feePerShare;
  const admit = edge > spec.margin;
  return {
    specVersion: spec.specVersion,
    shadow: spec.status === "shadow",
    price,
    pWin,
    feeRate,
    feePerShare,
    edge,
    admit,
    reason: admit
      ? `price-edge v${spec.specVersion}: p̂=${pWin.toFixed(3)} price=${price.toFixed(3)} fee=${feePerShare.toFixed(4)} edge=${edge.toFixed(4)} > ${spec.margin}`
      : `price-edge v${spec.specVersion}: no edge (p̂=${pWin.toFixed(3)} edge=${edge >= 0 ? "+" : ""}${edge.toFixed(4)} ≤ ${spec.margin})`,
  };
}
