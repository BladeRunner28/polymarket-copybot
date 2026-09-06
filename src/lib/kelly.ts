/**
 * Phase B — Kelly sizing for C-200 (2026-09-05). Pure math, no I/O.
 *
 * Formulas derived from the OctagonAI/kalshi-trading-bot-cli executable-quote
 * Kelly (MIT; audited 2026-08-31 → drafts/octagon-audit.md §2) and Thorp
 * (2006), adapted to the copybot's calibrated-premium edge:
 *
 *   fair q = Φ(Φ⁻¹(p) − λ̂)          (Wang-transform inversion; λ̂ from
 *                                     data/premium-calibration.json band,
 *                                     + venue offset applied by the caller)
 *   f*     = (q − p) / (1 − p)       (binary Kelly on the BOUGHT token —
 *                                     reduces the audit's YES/NO pair: both
 *                                     reduce to this once p,q are the bought
 *                                     token's price and fair probability)
 *
 * p is the price actually paid (shadow-FAK fill = executable by construction,
 * so the audit's ask-adjustment is satisfied by our fill model). λ̂ < 0 ⇒ info
 * edge (q > p ⇒ bet); λ̂ > 0 ⇒ overpriced (q < p ⇒ skip, never a floor bet).
 *
 * Sizing: size = min(fraction·f*·bankroll, maxBankrollPct·bankroll,
 * maxSizeUsd), with edge/dust floors. Skips carry a reason (journaled).
 *
 * BUY side only today (SELL is future-proofing → explicit skip).
 */

// ---- standard normal Φ and Φ⁻¹ (no dependencies) ---------------------------

/** Standard normal CDF. Abramowitz & Stegun 7.1.26, |err| ≤ 1.5e-7. */
export function normCdf(z: number): number {
  const sign = z < 0 ? -1 : 1;
  const x = Math.abs(z) / Math.SQRT2;
  const t = 1 / (1 + 0.3275911 * x);
  const poly =
    t *
    (0.254829592 +
      t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))));
  const erf = 1 - poly * Math.exp(-x * x);
  return 0.5 * (1 + sign * erf);
}

/** Standard normal quantile. Acklam's algorithm + one Halley refinement. */
export function normInv(p: number): number {
  if (!(p > 0 && p < 1)) throw new Error(`normInv: p must be in (0,1), got ${p}`);
  const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const plow = 0.02425;
  const phigh = 1 - plow;
  let q: number;
  let r: number;
  let x: number;
  if (p < plow) {
    q = Math.sqrt(-2 * Math.log(p));
    x =
      (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  } else if (p <= phigh) {
    q = p - 0.5;
    r = q * q;
    x =
      ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q) /
      (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  } else {
    q = Math.sqrt(-2 * Math.log(1 - p));
    x =
      -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  // One Halley refinement (Acklam).
  const e = normCdf(x) - p;
  const u = e * Math.SQRT2 * Math.sqrt(2 * Math.PI) * Math.exp((x * x) / 2);
  return x - u / (1 + (x * u) / 2);
}

// ---- Kelly core ------------------------------------------------------------

/**
 * Fair probability of the bought token under the Wang premium model:
 * p_mkt = Φ(Φ⁻¹(p*) + λ̂) ⇒ p* = Φ(Φ⁻¹(p) − λ̂).
 */
export function fairProbability(price: number, lambda: number): number {
  if (!(price > 0 && price < 1)) throw new Error(`fairProbability: price must be in (0,1), got ${price}`);
  return normCdf(normInv(price) - lambda);
}

/**
 * Full-Kelly fraction for buying a binary token at `price` whose fair
 * probability is `fairQ`. Same expression for YES and NO once p,q describe
 * the bought token: f* = (q − p)/(1 − p). Negative ⇒ no edge.
 */
export function kellyFraction(price: number, fairQ: number): number {
  if (!(price > 0 && price < 1)) throw new Error(`kellyFraction: price must be in (0,1), got ${price}`);
  return (fairQ - price) / (1 - price);
}

export interface KellySizeParams {
  /** Bought token price actually paid (executable). */
  price: number;
  /** Bought token: "YES" | "NO" (journaling only; math is side-symmetric). */
  outcome: "YES" | "NO";
  /** Band λ̂ (+ venue offset). λ̂<0 info edge, λ̂>0 overpriced, ~0 no edge. */
  lambda: number;
  /** BUY today; SELL → explicit skip. */
  side?: "BUY" | "SELL";
  /** cashBalance − open exposure at decision time. */
  availableBankroll: number;
  /** Fractional-Kelly multiplier (0.5 = half-Kelly). */
  fraction: number;
  /** Per-position cap as a fraction of available bankroll. */
  maxBankrollPct: number;
  /** Hard per-position USD cap. */
  maxSizeUsd: number;
  /** Skip dust below this. */
  minBetUsd: number;
  /** Skip when the edge fraction is below this (0.02 = 2%). */
  minEdgePct: number;
}

export interface KellySizeResult {
  /** USD to book; 0 when skipped. */
  sizeUsd: number;
  /** Full-Kelly fraction (pre multiplier). */
  fStarFull: number;
  /** Applied fraction (× fraction multiplier). */
  fStarApplied: number;
  /** Fair probability of the bought token. */
  q: number;
  skip: boolean;
  reason?: string;
}

export function kellySizeForCopy(params: KellySizeParams): KellySizeResult {
  const skip = (reason: string): KellySizeResult => ({
    sizeUsd: 0,
    fStarFull: 0,
    fStarApplied: 0,
    q: 0,
    skip: true,
    reason,
  });

  if (params.side === "SELL") return skip("SELL side not supported (BUY only today)");
  if (!(params.price > 0 && params.price < 1)) return skip(`price out of range: ${params.price}`);
  if (params.price <= 0.005 || params.price >= 0.995) return skip(`extreme price ${params.price.toFixed(3)} — no edge resolution`);
  if (!(params.availableBankroll > 0)) return skip(`availableBankroll ${params.availableBankroll} ≤ 0`);

  const q = fairProbability(params.price, params.lambda);
  const fStarFull = kellyFraction(params.price, q);

  if (fStarFull <= 0) {
    return skip(`no edge: q=${q.toFixed(3)} ≤ price=${params.price.toFixed(3)} (λ̂=${params.lambda.toFixed(3)})`);
  }
  if (fStarFull < params.minEdgePct) {
    return skip(`edge ${(fStarFull * 100).toFixed(2)}% < minEdgePct ${(params.minEdgePct * 100).toFixed(0)}%`);
  }

  const fStarApplied = fStarFull * params.fraction;
  const byFraction = fStarApplied * params.availableBankroll;
  const byPct = params.maxBankrollPct * params.availableBankroll;
  const sizeUsd = Math.min(byFraction, byPct, params.maxSizeUsd);
  const rounded = Math.round(sizeUsd * 100) / 100;

  if (rounded < params.minBetUsd) {
    return skip(`size $${rounded.toFixed(2)} < minBetUsd $${params.minBetUsd.toFixed(2)}`);
  }

  return {
    sizeUsd: rounded,
    fStarFull,
    fStarApplied,
    q,
    skip: false,
  };
}
