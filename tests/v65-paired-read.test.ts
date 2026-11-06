import { describe, expect, it } from "vitest";
import {
  V65_GATE,
  classPairs,
  diffConcentration,
  exactMates,
  gateVerdict,
  pairedStats,
  priceBand,
  type LegPair,
  type PairedLeg,
} from "../src/lib/v65-paired-read";

const leg = (over: Partial<PairedLeg> & { id: string }): PairedLeg => ({
  lane: "BANKROLL_200",
  marketId: "m1",
  outcome: "Yes",
  entryPrice: 0.5,
  sizeUsd: 10,
  pnlNet: 0,
  pnlGross: 0,
  openedAt: new Date("2026-10-01T00:00:00Z"),
  settledAt: new Date("2026-10-02T00:00:00Z"),
  ruleSetVersion: 65,
  ...over,
});

const pair = (post: PairedLeg, pre: PairedLeg, basis: "exact" | "class" = "class"): LegPair => ({
  basis,
  post,
  pre,
  gap: 0,
});

describe("priceBand", () => {
  it("assigns the half-open bands the band map uses", () => {
    expect(priceBand(0.1999)).toBe("<0.20");
    expect(priceBand(0.2)).toBe("0.20-0.40");
    expect(priceBand(0.4)).toBe("0.40-0.60");
    expect(priceBand(0.6)).toBe("0.60-0.80");
    expect(priceBand(0.8)).toBe(">=0.80");
    expect(priceBand(0.999)).toBe(">=0.80");
  });
});

describe("exactMates", () => {
  it("pairs only same lane + market + outcome, and never reuses a leg", () => {
    const post = [
      leg({ id: "p1", marketId: "A", outcome: "Yes" }),
      leg({ id: "p2", marketId: "A", outcome: "Yes" }),
      leg({ id: "p3", marketId: "B", outcome: "Yes" }),
    ];
    const pre = [
      leg({ id: "q1", marketId: "A", outcome: "Yes" }),
      leg({ id: "q2", marketId: "B", outcome: "No" }), // wrong outcome
      leg({ id: "q3", marketId: "C", outcome: "Yes" }), // wrong market
    ];
    const pairs = exactMates(post, pre);
    expect(pairs).toHaveLength(1);
    expect(pairs[0].post.marketId).toBe("A");
    expect(pairs[0].pre.id).toBe("q1");
    // The second A leg has no mate left: 1:1 without replacement.
    expect(pairs.some((p) => p.post.id === "p2")).toBe(false);
  });

  it("does not pair across lanes even when the market matches", () => {
    const post = [leg({ id: "p1", lane: "STANDARD", marketId: "A" })];
    const pre = [leg({ id: "q1", lane: "BANKROLL_200", marketId: "A" })];
    expect(exactMates(post, pre)).toHaveLength(0);
  });

  it("is deterministic: nearest opening time wins, ties break on id", () => {
    const post = [leg({ id: "p1", marketId: "A", openedAt: new Date("2026-10-05T00:00:00Z") })];
    const pre = [
      leg({ id: "qB", marketId: "A", openedAt: new Date("2026-10-01T00:00:00Z") }),
      leg({ id: "qA", marketId: "A", openedAt: new Date("2026-10-04T00:00:00Z") }),
    ];
    expect(exactMates(post, pre)[0].pre.id).toBe("qA");
  });
});

describe("classPairs", () => {
  it("matches within lane + band and respects the price gap ceiling", () => {
    const post = [leg({ id: "p1", entryPrice: 0.31, marketId: "X" })];
    const pre = [
      leg({ id: "q-far", entryPrice: 0.50, marketId: "Y" }), // same band, 0.19 away > 0.10
      leg({ id: "q-near", entryPrice: 0.36, marketId: "Z" }), // 0.05 away
      leg({ id: "q-other-band", entryPrice: 0.65, marketId: "W" }),
    ];
    const pairs = classPairs(post, pre);
    expect(pairs).toHaveLength(1);
    expect(pairs[0].pre.id).toBe("q-near");
    expect(pairs[0].basis).toBe("class");
  });

  it("never pairs a leg with itself twice and keeps the tighter gap first", () => {
    const post = [
      leg({ id: "p1", entryPrice: 0.50 }),
      leg({ id: "p2", entryPrice: 0.52 }),
    ];
    const pre = [leg({ id: "q1", entryPrice: 0.505 })];
    const pairs = classPairs(post, pre);
    expect(pairs).toHaveLength(1);
    expect(pairs[0].post.id).toBe("p1");
  });
});

describe("pairedStats", () => {
  it("computes the paired mean, sd and 2SE on a hand-checkable set", () => {
    const pairs = [
      pair(leg({ id: "p1", pnlNet: 10 }), leg({ id: "q1", pnlNet: 0, marketId: "x1" })),
      pair(leg({ id: "p2", pnlNet: 20 }), leg({ id: "q2", pnlNet: 0, marketId: "x2" })),
    ];
    const s = pairedStats(pairs);
    expect(s.n).toBe(2);
    expect(s.meanDiff).toBeCloseTo(15, 10);
    expect(s.sd).toBeCloseTo(Math.sqrt(50), 10);
    // 2 * sd / sqrt(n)
    expect(s.twoSe).toBeCloseTo((2 * Math.sqrt(50)) / Math.sqrt(2), 10);
    expect(s.sumDiff).toBe(30);
  });

  it("clusters on the unordered market pair, so a repeated market is one observation", () => {
    const shared = [
      pair(leg({ id: "p1", pnlNet: 5, marketId: "A" }), leg({ id: "q1", pnlNet: 0, marketId: "B" })),
      pair(leg({ id: "p2", pnlNet: 7, marketId: "B" }), leg({ id: "q2", pnlNet: 0, marketId: "A" })),
      pair(leg({ id: "p3", pnlNet: 9, marketId: "C" }), leg({ id: "q3", pnlNet: 0, marketId: "D" })),
    ];
    const distinct = [
      pair(leg({ id: "p1", pnlNet: 5, marketId: "A" }), leg({ id: "q1", pnlNet: 0, marketId: "B" })),
      pair(leg({ id: "p2", pnlNet: 7, marketId: "E" }), leg({ id: "q2", pnlNet: 0, marketId: "F" })),
      pair(leg({ id: "p3", pnlNet: 9, marketId: "C" }), leg({ id: "q3", pnlNet: 0, marketId: "D" })),
    ];
    const a = pairedStats(shared);
    const b = pairedStats(distinct);
    expect(a.n).toBe(b.n);
    expect(a.clusters).toBe(2); // A|B and C|D
    expect(b.clusters).toBe(3);
    const widthA = a.clusterCi.hi - a.clusterCi.lo;
    const widthB = b.clusterCi.hi - b.clusterCi.lo;
    expect(widthA).toBeGreaterThan(widthB);
  });

  it("returns NaN cluster bounds rather than a fake interval when there is one cluster", () => {
    const one = [pair(leg({ id: "p1", pnlNet: 1, marketId: "A" }), leg({ id: "q1", pnlNet: 0, marketId: "B" }))];
    const s = pairedStats(one);
    expect(Number.isNaN(s.clusterCi.lo)).toBe(true);
  });
});

describe("gateVerdict", () => {
  it("uses the pre-registered bar: $10 at 70 pairs", () => {
    expect(V65_GATE).toEqual({ maxTwoSe: 10, minPairs: 70 });
    expect(gateVerdict(pairedStats([])).requiredSd).toBeCloseTo((10 * Math.sqrt(70)) / 2, 10); // $41.83
  });

  it("reads VANISHED-BY-N when n is short, even at zero variance", () => {
    const pairs = Array.from({ length: 17 }, (_, i) =>
      pair(leg({ id: `p${i}`, pnlNet: 1, marketId: `m${i}` }), leg({ id: `q${i}`, pnlNet: 1, marketId: `n${i}` }))
    );
    const g = gateVerdict(pairedStats(pairs));
    expect(g.nPass).toBe(false);
    expect(g.verdict).toBe("VANISHED-BY-N");
  });

  it("reads UNRESOLVABLE-BY-PRECISION at n >= 70 with a wide spread, and names the n it would need", () => {
    const pairs = Array.from({ length: 80 }, (_, i) =>
      pair(
        leg({ id: `p${i}`, pnlNet: i % 2 ? 79.6 : -79.6, marketId: `m${i}` }),
        leg({ id: `q${i}`, pnlNet: 0, marketId: `n${i}` })
      )
    );
    const st = pairedStats(pairs);
    const g = gateVerdict(st);
    expect(g.nPass).toBe(true);
    expect(g.precisionPass).toBe(false);
    expect(g.verdict).toBe("UNRESOLVABLE-BY-PRECISION");
    // 2SE <= 10 needs n >= (2*sd/10)^2
    expect(g.requiredPairs).toBe(Math.ceil((2 * st.sd / 10) ** 2));
  });

  it("reads RESOLVABLE only when both clauses hold", () => {
    const pairs = Array.from({ length: 80 }, (_, i) =>
      pair(leg({ id: `p${i}`, pnlNet: 1, marketId: `m${i}` }), leg({ id: `q${i}`, pnlNet: 0, marketId: `n${i}` }))
    );
    const g = gateVerdict(pairedStats(pairs));
    expect(g.verdict).toBe("RESOLVABLE");
    expect(g.precisionPass).toBe(true);
  });

  it("does not call zero pairs 'precise': 2SE is 0 by construction there", () => {
    const g = gateVerdict(pairedStats([]));
    expect(g.twoSe).toBe(0);
    expect(g.precisionPass).toBe(false);
  });
});

describe("diffConcentration", () => {
  it("shows a mean carried by the top pairs: median 0, ex-top negative, share > 100%", () => {
    const pairs = Array.from({ length: 20 }, (_, i) =>
      pair(
        leg({ id: `p${i}`, pnlNet: i === 0 ? 100 : 0, marketId: `m${i}` }),
        leg({ id: `q${i}`, pnlNet: 0, marketId: `n${i}` })
      )
    );
    const c = diffConcentration(pairs);
    expect(c.sum).toBe(100);
    expect(c.median).toBe(0);
    expect(c.exTop[0]).toEqual({ k: 3, sum: 0, mean: 0 });
    expect(c.topShare).toBeCloseTo(1, 10);
  });

  it("reports a negative share when the top pairs are losses, so sign flips are visible", () => {
    const pairs = Array.from({ length: 12 }, (_, i) =>
      pair(
        leg({ id: `p${i}`, pnlNet: i < 10 ? -10 : 100, marketId: `m${i}` }),
        leg({ id: `q${i}`, pnlNet: 0, marketId: `n${i}` })
      )
    );
    const c = diffConcentration(pairs);
    expect(c.sum).toBe(100); // 2 * 100 - 10 * 10
    expect(c.median).toBe(-10);
    expect(c.exTop[0].mean).toBe(-10);
    expect(c.topShare).toBeCloseTo(1.2, 10); // the 8 loser pairs push the top-10 share ABOVE the whole sum
  });
});
