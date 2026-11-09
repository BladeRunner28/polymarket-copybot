import { describe, expect, it } from "vitest";
import {
  averageRanks,
  clusterBootstrapSpearman,
  MIN_ARM_ROWS,
  mulberry32,
  preRegisteredVerdict,
  priceBandOf,
  readEra,
  returnSummary,
  spearman,
  type HygieneRankLeg,
} from "../src/lib/hygiene-rank";

function leg(over: Partial<HygieneRankLeg> & { era: string; riskScore: number; returned: number }): HygieneRankLeg {
  return {
    legId: `${over.marketId ?? "m"}-${Math.random().toString(36).slice(2, 8)}`,
    marketId: over.marketId ?? "m1",
    era: over.era,
    ruleSetVersion: over.ruleSetVersion ?? 60,
    snapAtMs: over.snapAtMs ?? 1_700_000_000_000,
    riskScore: over.riskScore,
    riskGrade: over.riskGrade ?? "B",
    washScore: over.washScore ?? 0,
    washAssessed: over.washAssessed ?? false,
    entryPrice: over.entryPrice ?? 0.5,
    returned: over.returned,
    settlement: over.settlement ?? false,
  };
}

/** n legs per era with a chosen sign between score and outcome, spread over 4 markets. */
function eraLegs(era: string, n: number, sign: 1 | -1, prefix: string): HygieneRankLeg[] {
  return Array.from({ length: n }, (_, i) => {
    const score = 10 + (i % 30);
    return leg({
      era,
      riskScore: score,
      returned: sign * ((i % 30) / 100),
      marketId: `${prefix}-${i % 4}`,
    });
  });
}

describe("averageRanks", () => {
  it("averages ties instead of breaking them by position", () => {
    expect(averageRanks([10, 20, 20, 30])).toEqual([1, 2.5, 2.5, 4]);
  });
});

describe("spearman", () => {
  it("is -1 for a strictly decreasing relation and +1 increasing", () => {
    expect(spearman([1, 2, 3, 4], [4, 3, 2, 1])).toBeCloseTo(-1, 10);
    expect(spearman([1, 2, 3, 4], [10, 20, 30, 40])).toBeCloseTo(1, 10);
  });

  it("returns null (not 0) when either side has no variance or n < 3", () => {
    expect(spearman([1, 1, 1, 1], [1, 2, 3, 4])).toBeNull();
    expect(spearman([1, 2], [1, 2])).toBeNull();
  });
});

describe("returnSummary", () => {
  it("reports the concentration companions on the same population", () => {
    const s = returnSummary([10, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, -1]);
    expect(s.n).toBe(12);
    expect(s.sum).toBeCloseTo(19, 10);
    expect(s.mean).toBeCloseTo(19 / 12, 10);
    expect(s.winRate).toBeCloseTo(11 / 12, 10);
    expect(s.median).toBeCloseTo(1, 10);
    // exTop10 drops the two best legs (10 and 1): mean of the remaining two is 0
    expect(s.exTop10).toBeCloseTo(0, 10);
    expect(s.trimmedMean).toBeCloseTo(1, 10);
    expect(s.trimmedMean).toBeLessThan(s.mean);
  });

  it("is all zeros on an empty population", () => {
    expect(returnSummary([])).toEqual({ n: 0, mean: 0, median: 0, trimmedMean: 0, winRate: 0, sum: 0, exTop10: 0 });
  });
});

describe("mulberry32 / clusterBootstrapSpearman", () => {
  it("is reproducible for a fixed seed", () => {
    const a = mulberry32(7);
    const b = mulberry32(7);
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
  });

  it("clusters on market and returns a percentile interval", () => {
    const points = Array.from({ length: 120 }, (_, i) => ({ cluster: `m${i % 6}`, x: i % 30, y: -((i % 30) / 10) }));
    const first = clusterBootstrapSpearman(points, spearman, 400, 11);
    const second = clusterBootstrapSpearman(points, spearman, 400, 11);
    expect(first).not.toBeNull();
    expect(first!.lo).toBeLessThanOrEqual(first!.hi);
    expect(first!.lo).toBe(second!.lo);
    expect(first!.hi).toBe(second!.hi);
  });
});

describe("readEra", () => {
  it("splits by era and reports the band and price-band controls", () => {
    const legs = [...eraLegs("exposure-v58plus", 40, -1, "a"), ...eraLegs("pre-kelly-v1-48", 40, -1, "b")];
    const e = readEra("exposure-v58plus", legs);
    expect(e.nLegs).toBe(40);
    expect(e.nMarkets).toBe(4);
    expect(e.riskSpearman).toBeCloseTo(-1, 6);
    expect(e.byGrade.length).toBe(5);
    expect(e.byPriceBand.map((b) => b.band)).toContain("0.40-0.60");
  });
});

describe("priceBandOf", () => {
  it("assigns the half-open bands including the top edge", () => {
    expect(priceBandOf(0)).toBe("0.00-0.20");
    expect(priceBandOf(0.2)).toBe("0.20-0.40");
    expect(priceBandOf(0.99)).toBe("0.80-1.00");
    expect(priceBandOf(1)).toBe("0.80-1.00");
  });
});

describe("preRegisteredVerdict", () => {
  const eras = ["pre-kelly-v1-48", "kelly-window-v49-57", "exposure-v58plus"];

  it("PASSes only when every era is negative AND the pooled clustered CI excludes zero", () => {
    const legs = eras.flatMap((e, i) => eraLegs(e, 160, -1, `p${i}`));
    const perEra = eras.map((e) => readEra(e, legs));
    const v = preRegisteredVerdict(perEra, legs);
    expect(v.verdict).toBe("PASS");
    expect(v.pooledCi!.hi).toBeLessThan(0);
  });

  it("does NOT pass when one era flips sign — the actual live read", () => {
    const legs = [
      ...eraLegs(eras[0], 160, -1, "f0"),
      ...eraLegs(eras[1], 160, 1, "f1"),
      ...eraLegs(eras[2], 160, -1, "f2"),
    ];
    const perEra = eras.map((e) => readEra(e, legs));
    const v = preRegisteredVerdict(perEra, legs);
    expect(v.verdict).toBe("NO RANK INFORMATION");
    expect(v.reasons.join(" ")).toContain("sign is not negative in every era");
  });

  it("applies the audit kill rule below the 150-row floor instead of calling a thin arm a verdict", () => {
    const legs = [
      ...eraLegs(eras[0], MIN_ARM_ROWS - 1, -1, "t0"),
      ...eraLegs(eras[1], 200, -1, "t1"),
      ...eraLegs(eras[2], 200, -1, "t2"),
    ];
    const perEra = eras.map((e) => readEra(e, legs));
    const v = preRegisteredVerdict(perEra, legs);
    expect(v.verdict).toBe("TOO FEW DECISIONS");
    expect(v.reasons[0]).toContain(`${MIN_ARM_ROWS} floor`);
  });
});
