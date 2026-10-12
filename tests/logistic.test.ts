/**
 * Tests for the ridge-logistic fitter (card `phase-ml1`, the fitted candidate arm).
 *
 * The properties worth pinning are the ones a quiet mistake would hide: that the fitter
 * recovers a signal it should recover (not just "runs"), that the ridge actually shrinks,
 * that the INTERCEPT is unpenalized so the base rate is not biased, that standardization
 * is fitted on train rows only (a test-set moment leaking into training is invisible
 * otherwise), that a constant column cannot produce NaN/Infinity, and that the lambda
 * search stays inside the train window.
 */

import { describe, it, expect } from "vitest";
import { fitRidgeLogistic, pickL2ByInnerTimeSplit } from "../src/lib/logistic";
import { auc } from "../src/lib/metrics";

/** Deterministic standard-normal-ish generator (no dependency on the runtime's RNG). */
function makeRng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function synthetic(n: number, baseRateBias: number, seed = 7) {
  const rand = makeRng(seed);
  const X: number[][] = [];
  const y: number[] = [];
  for (let i = 0; i < n; i++) {
    // two informative columns and one pure noise column
    const x1 = (rand() * 2 - 1) * 3;
    const x2 = (rand() * 2 - 1) * 3;
    const noise = (rand() * 2 - 1) * 3;
    const z = 2 * x1 - 1.5 * x2 + baseRateBias;
    const p = 1 / (1 + Math.exp(-z));
    y.push(rand() < p ? 1 : 0);
    X.push([x1, x2, noise]);
  }
  return { X, y };
}

describe("fitRidgeLogistic", () => {
  it("recovers a real signal: AUC well above chance and the informative columns dominate", () => {
    const { X, y } = synthetic(6000, 0);
    const m = fitRidgeLogistic(X, y, { l2: 0.1 });
    const probs = X.map((r) => m.predictRow(r));
    const a = auc(probs, y);
    expect(Number.isFinite(a)).toBe(true);
    expect(a).toBeGreaterThan(0.85);
    // x1 positive, x2 negative, noise ~0 (features are already on a comparable scale)
    expect(m.beta[0]).toBeGreaterThan(1);
    expect(m.beta[1]).toBeLessThan(-0.7);
    expect(Math.abs(m.beta[2])).toBeLessThan(0.35);
    expect(m.iters).toBeGreaterThan(0);
    expect(Number.isFinite(m.logLoss)).toBe(true);
  });

  it("ridge shrinks the coefficients (and never grows them)", () => {
    const { X, y } = synthetic(2000, 0);
    const norm = (l2: number) => Math.sqrt(fitRidgeLogistic(X, y, { l2 }).beta.reduce((s, b, i) => s + (i < 2 ? b * b : 0), 0));
    const weak = norm(0.01);
    const strong = norm(50);
    expect(strong).toBeLessThan(weak);
    expect(strong).toBeGreaterThan(0);
  });

  it("does NOT penalize the intercept: with an uninformative feature the prediction is the base rate", () => {
    const n = 4000;
    const rand = makeRng(11);
    const X: number[][] = [];
    const y: number[] = [];
    for (let i = 0; i < n; i++) {
      const noise = (rand() * 2 - 1) * 5;
      y.push(rand() < 0.2 ? 1 : 0);
      X.push([noise]);
    }
    const m = fitRidgeLogistic(X, y, { l2: 1000 }); // huge ridge -> feature coefficient ~0
    // noise alone still buys a little slope, so the bar is "tiny", not "zero"
    expect(Math.abs(m.beta[0])).toBeLessThan(0.05);
    // intercept reproduces logit(0.2): predicting at the train mean of the feature
    expect(m.predictRow([m.mu[0]])).toBeCloseTo(0.2, 1);
  });

  it("standardizes on TRAIN rows only: the moments are returned, and a shifted row does not rescale the model", () => {
    const { X, y } = synthetic(1500, 0);
    const m = fitRidgeLogistic(X, y, { l2: 0.3 });
    const trainMean = X.reduce((s, r) => s + r[0], 0) / X.length;
    expect(m.mu[0]).toBeCloseTo(trainMean, 10);
    // the model's own standardization is exactly what predictRow applies
    const p0 = m.predictRow([m.mu[0], m.mu[1], m.mu[2]]);
    const interceptOnly = 1 / (1 + Math.exp(-m.beta[m.beta.length - 1]));
    expect(p0).toBeCloseTo(interceptOnly, 12);
    // a wild later row must be scored through the TRAIN moments, not its own
    expect(Number.isFinite(m.predictRow([1e6, -1e6, 0]))).toBe(true);
  });

  it("survives a constant column and a perfectly separable-ish column without NaN", () => {
    const n = 800;
    const rand = makeRng(3);
    const X: number[][] = [];
    const y: number[] = [];
    for (let i = 0; i < n; i++) {
      const x = (rand() * 2 - 1) * 2;
      y.push(x > 0 ? 1 : 0); // nearly separable
      X.push([x, 7.5]); // second column constant
    }
    const m = fitRidgeLogistic(X, y, { l2: 0.5 });
    expect(m.sd[1]).toBe(1); // constant column: sd guarded, not 0
    for (const r of X) {
      const p = m.predictRow(r);
      expect(Number.isFinite(p)).toBe(true);
      expect(p).toBeGreaterThan(0);
      expect(p).toBeLessThan(1);
    }
  });

  it("rejects malformed input instead of returning a plausible number", () => {
    expect(() => fitRidgeLogistic([], [])).toThrow();
    expect(() => fitRidgeLogistic([[1, 2]], [1, 0])).toThrow();
    const m = fitRidgeLogistic([[0, 1], [1, 0], [1, 1], [0, 0]], [0, 1, 1, 1], { l2: 1 });
    expect(() => m.predictRow([1])).toThrow();
  });

  it("is deterministic: same input, same coefficients", () => {
    const { X, y } = synthetic(1000, 0.3, 99);
    const a = fitRidgeLogistic(X, y, { l2: 1 });
    const b = fitRidgeLogistic(X, y, { l2: 1 });
    expect(b.beta).toEqual(a.beta);
    expect(b.logLoss).toBe(a.logLoss);
  });
});

describe("pickL2ByInnerTimeSplit", () => {
  it("searches only the grid, on the LATER half of the rows handed to it, and reports the inner read", () => {
    const { X, y } = synthetic(1200, 0);
    const rows = X.map((_, i) => ({ at: 1_000_000 + i * 1000 }));
    const grid = [0.03, 0.3, 3];
    const picked = pickL2ByInnerTimeSplit(rows, X, y, grid);
    expect(grid).toContain(picked.l2);
    expect(Object.keys(picked.innerAuc).sort()).toEqual(grid.map(String).sort());
    expect(picked.innerN).toBe(600);
  });

  it("falls back to the first grid value when the inner split cannot be scored", () => {
    const X = [[1], [2], [3], [4]];
    const y = [1, 1, 1, 1]; // one class only -> AUC undefined
    const rows = X.map((_, i) => ({ at: i }));
    const picked = pickL2ByInnerTimeSplit(rows, X, y, [0.5, 5]);
    expect(picked.l2).toBe(0.5);
  });
});
