/**
 * Tests for the gate-read metrics (card `ml1-target-net-pnl-and-price-baseline` step 2).
 *
 * The properties that matter: AUC handles ties by average rank, an undefined AUC is
 * NaN rather than a flattering 0.5, the bootstrap is seeded (re-runs reproduce), the
 * difference bootstrap is PAIRED, and clustering actually widens an interval when the
 * data is clustered — which is the whole reason row-level resampling is banned.
 */

import { describe, it, expect } from "vitest";
import {
  auc,
  brier,
  clusteredBootstrap,
  clusteredBootstrapDelta,
  constantBrier,
  mean,
  rng,
} from "../src/lib/metrics";

describe("auc", () => {
  it("is 1 for perfect separation and 0 for a perfectly inverted ranker", () => {
    expect(auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1])).toBe(1);
    expect(auc([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1])).toBe(0);
  });

  it("averages ranks across a tie (a coin-flip score is 0.5, not 0 or 1)", () => {
    expect(auc([0.5, 0.5], [1, 0])).toBe(0.5);
    expect(auc([0.5, 0.5, 0.5, 0.5], [1, 1, 0, 0])).toBe(0.5);
    // Pairs: 0.6 beats both negatives (2), the 0.5 positive beats 0.4 and TIES the
    // other 0.5 negative (1.5) -> 3.5/4. Hand-checked against the tie rule.
    expect(auc([0.4, 0.5, 0.5, 0.6], [0, 0, 1, 1])).toBe(0.875);
  });

  it("returns NaN — never 0.5 — when a class is absent", () => {
    expect(auc([0.1, 0.2], [1, 1])).toBeNaN();
    expect(auc([0.1, 0.2], [0, 0])).toBeNaN();
  });

  it("matches a hand-computed rank sum", () => {
    // labels 1,0,1 with scores 3,2,1 -> positives rank 3 and 1: (4 - 3)/2 = 0.5
    expect(auc([3, 2, 1], [1, 0, 1])).toBe(0.5);
  });
});

describe("brier / constantBrier", () => {
  it("computes the mean squared error of a probability", () => {
    expect(brier([1, 0, 0.5], [1, 0, 0])).toBeCloseTo((0 + 0 + 0.25) / 3, 12);
  });

  it("gives the constant-predictor Brier b(1-b) at base rate b", () => {
    expect(constantBrier([1, 1, 0, 0])).toBeCloseTo(0.25, 12);
    expect(constantBrier([1, 1, 1, 0])).toBeCloseTo(0.1875, 12);
  });

  it("is 0 for a perfectly calibrated-and-correct forecast and 1 for a perfectly wrong one", () => {
    expect(brier([1, 0], [1, 0])).toBe(0);
    expect(brier([0, 1], [1, 0])).toBe(1);
  });

  it("refuses mismatched lengths instead of truncating", () => {
    expect(() => brier([0.5, 0.5], [1])).toThrow(/length mismatch/);
  });
});

describe("rng", () => {
  it("is deterministic for a seed and different across seeds", () => {
    const a = [rng(7)(), rng(7)(), rng(7)()];
    const b = [rng(7)(), rng(7)(), rng(7)()];
    expect(a).toEqual(b);
    expect(rng(8)()).not.toBe(rng(7)());
    expect(rng(7)()).toBeGreaterThanOrEqual(0);
    expect(rng(7)()).toBeLessThan(1);
  });
});

type Leg = { market: string; score: number; y: number; pnl: number };

describe("clusteredBootstrap", () => {
  const legs: Leg[] = [];
  for (let m = 0; m < 12; m++) {
    // Strong WITHIN-market correlation: every leg on a market shares the market's
    // outcome, which is exactly what makes row-level resampling lie.
    const good = m % 2 === 0;
    for (let i = 0; i < 10; i++) {
      legs.push({
        market: `mkt-${m}`,
        score: good ? 0.8 - i * 0.01 : 0.2 + i * 0.01,
        y: good ? 1 : 0,
        pnl: good ? 5 : -5,
      });
    }
  }

  it("is reproducible for a seed", () => {
    const stat = (s: readonly Leg[]) => mean(s.map((l) => l.pnl));
    const a = clusteredBootstrap(legs, (l) => l.market, stat, { iters: 400, seed: 11 });
    const b = clusteredBootstrap(legs, (l) => l.market, stat, { iters: 400, seed: 11 });
    expect(a.low).toBe(b.low);
    expect(a.high).toBe(b.high);
    expect(a.point).toBe(b.point);
  });

  it("is WIDER than resampling rows when the data is market-clustered", () => {
    const stat = (s: readonly Leg[]) => mean(s.map((l) => l.pnl));
    const clustered = clusteredBootstrap(legs, (l) => l.market, stat, { iters: 2000, seed: 3 });
    const rowLevel = clusteredBootstrap(legs, (l) => `${l.market}:${l.score}`, stat, { iters: 2000, seed: 3 });
    expect(rowLevel.high - rowLevel.low).toBeGreaterThan(0);
    expect(clustered.high - clustered.low).toBeGreaterThan(rowLevel.high - rowLevel.low);
  });

  it("counts degenerate draws instead of dropping them silently", () => {
    const oneClassPerCluster: Leg[] = [
      { market: "a", score: 3, y: 1, pnl: 1 },
      { market: "b", score: 1, y: 0, pnl: 2 },
      { market: "c", score: 2, y: 1, pnl: 3 },
    ];
    const r = clusteredBootstrap(oneClassPerCluster, (l) => l.market, (s) => auc(s.map((x) => x.score), s.map((x) => x.y)), {
      iters: 200,
      seed: 5,
    });
    expect(r.skipped).toBeGreaterThan(0); // single-class resamples exist and are reported
    expect(r.point).toBe(1);
  });

  it("collapses to a degenerate interval with one cluster instead of pretending to an interval", () => {
    const one = legs.map((l) => ({ ...l, market: "only" }));
    const r = clusteredBootstrap(one, (l) => l.market, (s) => mean(s.map((x) => x.pnl)), { iters: 100 });
    expect(r.iters).toBe(0);
    expect(r.low).toBe(r.high);
  });
});

describe("clusteredBootstrapDelta", () => {
  const legs: Leg[] = [];
  for (let m = 0; m < 30; m++) {
    const good = m % 3 === 0;
    for (let i = 0; i < 8; i++) {
      legs.push({
        market: `m${m}`,
        // `score` ranks well; `bad` is anti-correlated with the label.
        score: good ? 0.9 - i * 0.01 : 0.1 + i * 0.01,
        y: good ? 1 : 0,
        pnl: good ? 4 : -2,
      });
    }
  }
  const aucOf = (f: (l: Leg) => number) => (s: readonly Leg[]) => auc(s.map(f), s.map((l) => l.y));

  it("is paired and one-sided in the right direction", () => {
    const d = clusteredBootstrapDelta(
      legs,
      (l) => l.market,
      aucOf((l) => l.score),
      aucOf((l) => 1 - l.score),
      { iters: 300, seed: 9 }
    );
    expect(d.point).toBeCloseTo(1, 10); // perfect vs perfectly inverted
    expect(d.pGreater).toBe(1);
    expect(d.low).toBeGreaterThan(0);
    expect(d.pairedDraws).toBeGreaterThan(0);
  });

  it("reports a null difference as spanning zero", () => {
    const d = clusteredBootstrapDelta(
      legs,
      (l) => l.market,
      aucOf((l) => l.score),
      aucOf((l) => l.score),
      { iters: 300, seed: 9 }
    );
    expect(d.point).toBe(0);
    expect(d.low).toBeLessThanOrEqual(0);
    expect(d.high).toBeGreaterThanOrEqual(0);
  });
});
