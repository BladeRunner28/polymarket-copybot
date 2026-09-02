/**
 * Forecasting core — correlation-aware Bayesian evidence aggregation.
 *
 * Methodology (attributed, reimplemented from public forecasting literature;
 * cf. the Polyseer audit at drafts/polyseer-audit.md — Polyseer itself is
 * all-rights-reserved, so these are standard formulas written from first
 * principles):
 *
 *   Evidence → log-likelihood ratio (Karger-style effective counts, Metaculus-
 *   style weighting):
 *     logLR = polarity × typeCap × (0.45·verifiability + 0.25·corroboration
 *                                   + 0.15·consistency + 0.15·recency)
 *     corroboration: r = 1 − e^(−k₀·k)     (independent corroborations → 0..1)
 *     recency:        1/(1 + days/120)     (120-day half-life)
 *
 *   Aggregation (logit-space Bayesian updating with correlation correction):
 *     l = logit(p₀)                        # prior (here: the market price)
 *     per cluster (correlated sources share a cluster):
 *       ρ = 0.6 if m>1 else 0              # default intra-cluster correlation
 *       mEff = m / (1 + (m−1)·ρ)           # effective independent count
 *       l += mEff × trimmedMean₂₀%(logLRs)
 *     pNeutral = sigmoid(l)                # evidence-only posterior
 *     pAware   = sigmoid(logit(pNeutral) + 0.1·logit(pMarket))  # firewall
 *     delta    = pAware − pMarket          # calibrated edge in probability points
 *
 * All functions here are pure and unit-tested — the DB-facing adapter lives
 * in ./sentiment.ts.
 */

export interface EvidenceItem {
  /** Cluster key — correlated evidence shares one (e.g. same source). */
  cluster: string;
  /** Signed strength of the evidence, -1..1 (e.g. sentimentScore). */
  polarity: number;
  /** Evidence-tier cap (A=1.0, B=0.6, C=0.3, D=0.2). */
  typeCap: number;
  /** Verifiability / authority of the source, 0..1. */
  verifiability: number;
  /** Corroboration saturation 0..1 (1 − e^(−k₀·k)). */
  corroboration: number;
  /** Consistency with the rest of the batch, 0..1 (fraction agreeing). */
  consistency: number;
  /** Recency factor 0..1 (1/(1 + days/120)). */
  recency: number;
}

export interface AggregateResult {
  pNeutral: number;
  pAware: number;
  /** pAware − prior, in probability points (0..1 scale). */
  delta: number;
  prior: number;
  n: number;
  clusterCount: number;
}

const EPS = 1e-6;

/** logit(p) with numerical guards at the 0/1 boundaries. */
export function logit(p: number): number {
  const x = Math.min(1 - EPS, Math.max(EPS, p));
  return Math.log(x / (1 - x));
}

export function sigmoid(x: number): number {
  if (x >= 0) {
    const z = Math.exp(-x);
    return 1 / (1 + z);
  }
  const z = Math.exp(x);
  return z / (1 + z);
}

/**
 * Effective independent count under intra-cluster correlation ρ:
 * mEff = m / (1 + (m−1)·ρ). ρ=0 → m (independent), ρ=1 → 1 (fully redundant).
 */
export function effectiveCount(m: number, rho = 0.6): number {
  if (m <= 1) return m;
  return m / (1 + (m - 1) * rho);
}

/** 20% trimmed mean; arrays too small to trim (n<4) fall back to plain mean. */
export function trimmedMean(xs: number[], trim = 0.2): number {
  if (xs.length === 0) return 0;
  if (xs.length < 4) return xs.reduce((a, b) => a + b, 0) / xs.length;
  const sorted = [...xs].sort((a, b) => a - b);
  const k = Math.max(0, Math.floor(sorted.length * trim));
  const cut = sorted.slice(k, sorted.length - k);
  return cut.reduce((a, b) => a + b, 0) / cut.length;
}

/** Corroboration saturation: r = 1 − e^(−k₀·k). */
export function corroborationFactor(k: number, k0 = 0.2): number {
  return 1 - Math.exp(-k0 * k);
}

/** Recency half-life: 1/(1 + days/120). */
export function recencyFactor(days: number, halfLifeDays = 120): number {
  return 1 / (1 + days / halfLifeDays);
}

/** Evidence → log-likelihood ratio (the Polyseer-quality rubric). */
export function evidenceLogLR(e: EvidenceItem): number {
  const quality =
    0.45 * e.verifiability +
    0.25 * e.corroboration +
    0.15 * e.consistency +
    0.15 * e.recency;
  return e.polarity * e.typeCap * quality;
}

/**
 * Aggregate evidence items into a calibrated probability edge.
 * prior = the market price (firewall: the market is blended LAST at 10%).
 */
export function aggregateEvidenceItems(
  items: EvidenceItem[],
  prior: number,
  marketBlend = 0.1
): AggregateResult {
  const n = items.length;
  if (n === 0) {
    return { pNeutral: prior, pAware: prior, delta: 0, prior, n: 0, clusterCount: 0 };
  }

  const byCluster = new Map<string, EvidenceItem[]>();
  for (const it of items) {
    const arr = byCluster.get(it.cluster) ?? [];
    arr.push(it);
    byCluster.set(it.cluster, arr);
  }

  let l = logit(prior);
  for (const clusterItems of byCluster.values()) {
    const m = clusterItems.length;
    const rho = m > 1 ? 0.6 : 0;
    const mEff = effectiveCount(m, rho);
    const logLRs = clusterItems.map(evidenceLogLR);
    l += mEff * trimmedMean(logLRs);
  }

  const pNeutral = sigmoid(l);
  const pAware = sigmoid(logit(pNeutral) + marketBlend * logit(prior));
  const delta = pAware - prior;
  return { pNeutral, pAware, delta, prior, n, clusterCount: byCluster.size };
}
