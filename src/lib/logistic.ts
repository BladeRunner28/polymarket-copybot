/**
 * Ridge logistic regression — a small, pure, dependency-free fitter for the ML-1 candidate
 * arm (card `phase-ml1`). No sklearn in this stack: the fits here are on thousands of rows
 * with a handful of features, so plain Newton/IRLS is both enough and auditable.
 *
 * WHY THE SHAPE IS THIS WAY
 *   * Standardization is fitted on TRAIN ONLY and returned with the model. Scaling on the
 *     full sample leaks test-set moments into training and makes a re-fit on a growing book
 *     silently non-reproducible.
 *   * The intercept is NOT penalized (a ridge on the intercept biases the base rate).
 *   * IRLS with a step-halving guard: a Newton step on a nearly-separable column can
 *     overshoot to a log-likelihood of -Infinity, which then reads as a great fit.
 *   * Missing features are dropped PER ROW by the caller (`usable`), never imputed here: a
 *     trade with a missing spread is not a trade with spread 0.
 *
 * Usage:
 *   const m = fitRidgeLogistic(X, y, { l2: 1.0 });
 *   m.predictRow(x)  // probability in (0,1)
 */

export type LogisticModel = {
  /** Feature means, fitted on the rows passed to the fitter. */
  mu: number[];
  /** Feature standard deviations (never 0 — a constant column gets 1). */
  sd: number[];
  /** Coefficients on STANDARDIZED features, intercept last. */
  beta: number[];
  /** Ridge strength used. */
  l2: number;
  /** Rows used. */
  n: number;
  /** In-sample mean log-loss (weighted by nothing — every row counts once). */
  logLoss: number;
  /** Newton iterations actually taken. */
  iters: number;
  /** Train-set AUC, so an overfit gap is visible without a second call. */
  aucInsample: number;
  predictRow: (x: readonly number[]) => number;
};

const sigmoid = (z: number) => (z >= 0 ? 1 / (1 + Math.exp(-z)) : Math.exp(z) / (1 + Math.exp(z)));

/** Rank-based AUC with ties counted as half — same convention as src/lib/metrics.ts. */
function aucOf(scores: readonly number[], labels: readonly number[]): number {
  const idx = scores.map((s, i) => [s, labels[i]] as [number, number]);
  idx.sort((a, b) => a[0] - b[0]);
  const ranks = new Array<number>(idx.length);
  let i = 0;
  while (i < idx.length) {
    let j = i;
    while (j + 1 < idx.length && idx[j + 1][0] === idx[i][0]) j++;
    const avg = (i + j + 2) / 2;
    for (let k = i; k <= j; k++) ranks[k] = avg;
    i = j + 1;
  }
  let pos = 0;
  let neg = 0;
  let rankSum = 0;
  for (let k = 0; k < idx.length; k++) {
    if (idx[k][1] > 0.5) {
      pos++;
      rankSum += ranks[k];
    } else neg++;
  }
  if (pos === 0 || neg === 0) return Number.NaN;
  return (rankSum - (pos * (pos + 1)) / 2) / (pos * neg);
}

export function fitRidgeLogistic(
  X: readonly (readonly number[])[],
  y: readonly (0 | 1 | number)[],
  opts: { l2?: number; maxIters?: number; tol?: number } = {}
): LogisticModel {
  const l2 = opts.l2 ?? 1.0;
  const maxIters = opts.maxIters ?? 50;
  const tol = opts.tol ?? 1e-8;
  const n = X.length;
  const p = n > 0 ? X[0].length : 0;
  if (n === 0 || p === 0) throw new Error("fitRidgeLogistic: no rows or no features");
  if (y.length !== n) throw new Error("fitRidgeLogistic: X and y disagree on row count");

  // --- standardization (train rows only) ---
  const mu = new Array<number>(p).fill(0);
  for (const row of X) for (let j = 0; j < p; j++) mu[j] += row[j] / n;
  const sd = new Array<number>(p).fill(0);
  for (const row of X) for (let j = 0; j < p; j++) sd[j] += (row[j] - mu[j]) ** 2 / n;
  for (let j = 0; j < p; j++) sd[j] = Math.sqrt(sd[j]) < 1e-12 ? 1 : Math.sqrt(sd[j]);

  // design matrix: [standardized features, 1]
  const Z: number[][] = X.map((row) => [...row.map((v, j) => (v - mu[j]) / sd[j]), 1]);
  const d = p + 1;

  // --- Newton / IRLS on the penalized log-likelihood (intercept unpenalized) ---
  let beta = new Array<number>(d).fill(0);
  let iters = 0;
  let converged = false;
  for (let it = 0; it < maxIters && !converged; it++) {
    const grad = new Array<number>(d).fill(0);
    const hess: number[][] = Array.from({ length: d }, () => new Array<number>(d).fill(0));
    let logLoss = 0;
    for (let i = 0; i < n; i++) {
      const zi = Z[i];
      let z = 0;
      for (let j = 0; j < d; j++) z += zi[j] * beta[j];
      const pr = Math.min(Math.max(sigmoid(z), 1e-12), 1 - 1e-12);
      const w = pr * (1 - pr);
      const r = y[i] - pr; // score residual
      logLoss -= (y[i] > 0.5 ? Math.log(pr) : Math.log(1 - pr)) / n;
      for (let j = 0; j < d; j++) {
        grad[j] += r * zi[j];
        for (let k = j; k < d; k++) hess[j][k] += w * zi[j] * zi[k];
      }
    }
    for (let j = 0; j < d; j++) grad[j] -= j < p ? l2 * beta[j] : 0;
    for (let j = 0; j < d; j++) {
      for (let k = 0; k < j; k++) hess[j][k] = hess[k][j];
      hess[j][j] += j < p ? l2 : 0;
      hess[j][j] += 1e-10; // keep the system solvable when a column is nearly constant
    }
    const step = solve(hess, grad);
    if (!step) break;

    // step-halving: accept only a step that does not increase the penalized loss
    let scale = 1;
    let accepted = false;
    for (let attempt = 0; attempt < 30; attempt++) {
      const cand = beta.map((b, j) => b + scale * step[j]);
      const lp = penalizedLoss(Z, y, cand, l2, p);
      if (Number.isFinite(lp) && lp <= penalizedLoss(Z, y, beta, l2, p) + 1e-12) {
        const delta = Math.max(...cand.map((b, j) => Math.abs(b - beta[j])));
        beta = cand;
        accepted = true;
        iters = it + 1;
        if (delta < tol) converged = true;
        break;
      }
      scale /= 2;
    }
    if (!accepted) break;
  }

  const probs = Z.map((zi) => {
    let z = 0;
    for (let j = 0; j < d; j++) z += zi[j] * beta[j];
    return Math.min(Math.max(sigmoid(z), 1e-12), 1 - 1e-12);
  });
  const logLoss = probs.reduce((acc, pr, i) => acc - (y[i] > 0.5 ? Math.log(pr) : Math.log(1 - pr)), 0) / n;

  return {
    mu,
    sd,
    beta,
    l2,
    n,
    logLoss,
    iters,
    aucInsample: aucOf(probs, y as number[]),
    predictRow: (x: readonly number[]) => {
      if (x.length !== p) throw new Error(`predictRow: expected ${p} features, got ${x.length}`);
      let z = beta[p];
      for (let j = 0; j < p; j++) z += ((x[j] - mu[j]) / sd[j]) * beta[j];
      return Math.min(Math.max(sigmoid(z), 1e-12), 1 - 1e-12);
    },
  };
}

function penalizedLoss(Z: number[][], y: readonly number[], beta: readonly number[], l2: number, p: number): number {
  let ll = 0;
  for (let i = 0; i < Z.length; i++) {
    let z = 0;
    for (let j = 0; j < beta.length; j++) z += Z[i][j] * beta[j];
    const pr = Math.min(Math.max(sigmoid(z), 1e-12), 1 - 1e-12);
    ll -= y[i] > 0.5 ? Math.log(pr) : Math.log(1 - pr);
  }
  let pen = 0;
  for (let j = 0; j < p; j++) pen += beta[j] * beta[j];
  return ll / Z.length + (l2 / (2 * Z.length)) * pen;
}

/** Gaussian elimination with partial pivoting; null when the system is singular. */
function solve(A: number[][], b: readonly number[]): number[] | null {
  const n = b.length;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let c = 0; c < n; c++) {
    let piv = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[piv][c])) piv = r;
    if (Math.abs(M[piv][c]) < 1e-14) return null;
    [M[c], M[piv]] = [M[piv], M[c]];
    for (let r = 0; r < n; r++) {
      if (r === c) continue;
      const factor = M[r][c] / M[c][c];
      if (factor === 0) continue;
      for (let k = c; k <= n; k++) M[r][k] -= factor * M[c][k];
    }
  }
  return M.map((row, i) => row[n] / M[i][i]);
}

/**
 * Pick the ridge strength on an INNER time-ordered holdout of the TRAIN window only.
 * Choosing lambda on the test window is tuning on the answer; choosing it on a random
 * split of train would violate the split doctrine (`src/lib/splits.ts`).
 */
export function pickL2ByInnerTimeSplit(
  rows: readonly { at: number }[],
  X: readonly (readonly number[])[],
  y: readonly (0 | 1 | number)[],
  grid: readonly number[] = [0.03, 0.1, 0.3, 1, 3]
): { l2: number; innerN: number; innerAuc: Record<string, number> } {
  const order = rows.map((r, i) => [r.at, i] as [number, number]).sort((a, b) => a[0] - b[0]);
  const cut = Math.floor(order.length / 2);
  const trainIdx = order.slice(0, cut).map(([, i]) => i);
  const innerIdx = order.slice(cut).map(([, i]) => i);
  const innerAuc: Record<string, number> = {};
  let best = grid[0];
  let bestAuc = -Infinity;
  for (const l2 of grid) {
    const m = fitRidgeLogistic(trainIdx.map((i) => X[i]), trainIdx.map((i) => y[i]), { l2 });
    const probs = innerIdx.map((i) => m.predictRow(X[i]));
    const a = aucOf(probs, innerIdx.map((i) => y[i]));
    innerAuc[String(l2)] = a;
    if (Number.isFinite(a) && a > bestAuc) {
      bestAuc = a;
      best = l2;
    }
  }
  return { l2: best, innerN: innerIdx.length, innerAuc };
}
