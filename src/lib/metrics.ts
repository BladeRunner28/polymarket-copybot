/**
 * Pure metrics for gate reads: AUC, Brier, and a CLUSTERED bootstrap over rows.
 *
 * WHY THESE EXIST SEPARATELY FROM `shadow-read.ts`
 * -----------------------------------------------
 * `shadow-read.ts` already has a clustered bootstrap, but it is specialised: it
 * resamples market clusters and re-computes a STAKE-WEIGHTED ROI on would-have
 * decision rows, and its numbers are published lane summaries. Unifying the two
 * would change those published figures for no gain, so this module stays generic —
 * a resampler that takes a cluster key and ANY row statistic — and the gate read
 * uses it for AUC / AUC-difference / mean-PnL-per-leg.
 *
 * CLUSTERING IS NOT OPTIONAL. Several legs on one market share a single resolution:
 * resampling rows would treat those as independent draws and understate every
 * interval. Every function here takes a cluster accessor and there is no row-level
 * default.
 *
 * DETERMINISM: the PRNG is seeded, so re-running a read reproduces the same CI. A
 * CI that changes between two runs of the same data is not evidence.
 */

/** AUC with average ranks for ties: the probability a random positive outranks a random negative. */
export function auc(scores: readonly number[], labels: readonly number[]): number {
  const n = scores.length;
  if (n === 0) throw new Error("auc: no rows");
  const pos = labels.filter((y) => y === 1).length;
  const neg = n - pos;
  if (pos === 0 || neg === 0) return Number.NaN; // undefined, not 0.5 — never silently invent a number
  const order = scores.map((s, i) => ({ s, i })).sort((a, b) => a.s - b.s);
  const ranks = new Array<number>(n);
  let i = 0;
  while (i < order.length) {
    let j = i;
    while (j + 1 < order.length && order[j + 1].s === order[i].s) j++;
    const avgRank = (i + j) / 2 + 1; // 1-based average rank across the tie group
    for (let k = i; k <= j; k++) ranks[order[k].i] = avgRank;
    i = j + 1;
  }
  let rankSumPos = 0;
  for (let k = 0; k < n; k++) if (labels[k] === 1) rankSumPos += ranks[k];
  return (rankSumPos - (pos * (pos + 1)) / 2) / (pos * neg);
}

/** Brier score. Only meaningful for a CALIBRATED probability — never for a 0-100 score. */
export function brier(probs: readonly number[], labels: readonly number[]): number {
  if (probs.length === 0) throw new Error("brier: no rows");
  if (probs.length !== labels.length) throw new Error("brier: length mismatch");
  let s = 0;
  for (let i = 0; i < probs.length; i++) s += (probs[i] - labels[i]) ** 2;
  return s / probs.length;
}

export function mean(xs: readonly number[]): number {
  if (xs.length === 0) return Number.NaN;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

/** Brier of the best constant predictor: b(1-b) at the base rate b. */
export function constantBrier(labels: readonly number[]): number {
  const b = mean(labels);
  return b * (1 - b);
}

/** Deterministic PRNG (mulberry32) so a CI is reproducible across runs. */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export type BootstrapResult = {
  point: number;
  low: number;
  high: number;
  /** Draws whose statistic was undefined (e.g. a resample with one class) — reported, never hidden. */
  skipped: number;
  iters: number;
  seed: number;
};

/**
 * Cluster bootstrap of a single statistic. Resamples CLUSTERS with replacement.
 * `stat` returning NaN marks a degenerate draw, which is counted in `skipped`.
 */
export function clusteredBootstrap<T>(
  rows: readonly T[],
  cluster: (r: T) => string,
  stat: (sample: readonly T[]) => number,
  opts: { iters?: number; seed?: number; alpha?: number } = {}
): BootstrapResult {
  const iters = opts.iters ?? 2000;
  const alpha = opts.alpha ?? 0.05;
  const seed = opts.seed ?? 20261011;
  const groups = new Map<string, T[]>();
  for (const r of rows) {
    const k = cluster(r);
    const list = groups.get(k) ?? [];
    list.push(r);
    groups.set(k, list);
  }
  const keys = [...groups.keys()];
  const point = stat(rows);
  if (keys.length < 2) {
    return { point, low: point, high: point, skipped: 0, iters: 0, seed };
  }
  const rand = rng(seed);
  const draws: number[] = [];
  let skipped = 0;
  for (let it = 0; it < iters; it++) {
    const sample: T[] = [];
    for (let g = 0; g < keys.length; g++) {
      sample.push(...groups.get(keys[Math.floor(rand() * keys.length)])!);
    }
    const v = stat(sample);
    if (Number.isNaN(v)) skipped += 1;
    else draws.push(v);
  }
  if (draws.length === 0) return { point, low: Number.NaN, high: Number.NaN, skipped, iters, seed };
  draws.sort((a, b) => a - b);
  const at = (q: number) => draws[Math.min(draws.length - 1, Math.max(0, Math.floor(q * draws.length)))];
  return { point, low: at(alpha / 2), high: at(1 - alpha / 2), skipped, iters, seed };
}

export type DeltaBootstrapResult = BootstrapResult & {
  pointB: number;
  /** Share of draws where A beat B — the one-sided read. */
  pGreater: number;
  /** Draws used for both statistics (a draw counts only when both are defined). */
  pairedDraws: number;
};

/**
 * Paired cluster bootstrap of the DIFFERENCE statA - statB on the SAME resampled
 * clusters. Pairing matters: comparing two independently-drawn intervals is the
 * standard way a difference looks significant when it is not.
 */
export function clusteredBootstrapDelta<T>(
  rows: readonly T[],
  cluster: (r: T) => string,
  statA: (sample: readonly T[]) => number,
  statB: (sample: readonly T[]) => number,
  opts: { iters?: number; seed?: number; alpha?: number } = {}
): DeltaBootstrapResult {
  const iters = opts.iters ?? 2000;
  const alpha = opts.alpha ?? 0.05;
  const seed = opts.seed ?? 20261011;
  const groups = new Map<string, T[]>();
  for (const r of rows) {
    const k = cluster(r);
    const list = groups.get(k) ?? [];
    list.push(r);
    groups.set(k, list);
  }
  const keys = [...groups.keys()];
  const pointA = statA(rows);
  const pointB = statB(rows);
  const point = pointA - pointB;
  if (keys.length < 2) {
    return { point, pointB, low: point, high: point, pGreater: point > 0 ? 1 : 0, skipped: 0, pairedDraws: 0, iters: 0, seed };
  }
  const rand = rng(seed);
  const draws: number[] = [];
  let skipped = 0;
  let greater = 0;
  for (let it = 0; it < iters; it++) {
    const sample: T[] = [];
    for (let g = 0; g < keys.length; g++) {
      sample.push(...groups.get(keys[Math.floor(rand() * keys.length)])!);
    }
    const a = statA(sample);
    const b = statB(sample);
    if (Number.isNaN(a) || Number.isNaN(b)) {
      skipped += 1;
      continue;
    }
    const d = a - b;
    if (d > 0) greater += 1;
    draws.push(d);
  }
  if (draws.length === 0) {
    return { point, pointB, low: Number.NaN, high: Number.NaN, pGreater: Number.NaN, skipped, pairedDraws: 0, iters, seed };
  }
  draws.sort((x, y) => x - y);
  const at = (q: number) => draws[Math.min(draws.length - 1, Math.max(0, Math.floor(q * draws.length)))];
  return {
    point,
    pointB,
    low: at(alpha / 2),
    high: at(1 - alpha / 2),
    pGreater: greater / draws.length,
    skipped,
    pairedDraws: draws.length,
    iters,
    seed,
  };
}
