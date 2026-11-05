import { describe, expect, it } from "vitest";
import {
  NEARCERT_DUST_FLOOR,
  breakevenWinRate,
  decisionLiveness,
  dedupeToSignal,
  evPerIntent,
  geometricMeanPerLeg,
  isSoleBlocker,
  legReturn,
  parseNearCertaintyOperand,
  parseVenueClock,
  priceBucket,
  riskEntries,
  summarizeCohort,
  topKShare,
} from "../src/lib/nearcertainty-tail";

const nc = (p: string) => `price ${p} near certainty (band 0.05–0.95) — limited upside`;

describe("parseNearCertaintyOperand", () => {
  it("reads the price the clause actually compared", () => {
    expect(parseNearCertaintyOperand(JSON.stringify([nc("0.012")]))).toBe(0.012);
    expect(parseNearCertaintyOperand(JSON.stringify([nc("0.001")]))).toBe(0.001);
  });

  it("does not fire on other risk strings", () => {
    expect(parseNearCertaintyOperand(JSON.stringify(["price drifted 0.390 since entry > max 0.15 (too late)"]))).toBeNull();
    expect(parseNearCertaintyOperand(JSON.stringify(["Price already near certainty — limited upside"]))).toBeNull();
    expect(parseNearCertaintyOperand(null)).toBeNull();
  });
});

describe("riskEntries / isSoleBlocker", () => {
  it("parses the journal array and tolerates garbage", () => {
    expect(riskEntries(JSON.stringify([nc("0.01"), "x"]))).toHaveLength(2);
    expect(riskEntries("{not json")).toEqual([]);
    expect(riskEntries(null)).toEqual([]);
  });

  it("counts the clause as sole only when nothing else refused the leg", () => {
    expect(isSoleBlocker([nc("0.03")])).toBe(true);
    expect(isSoleBlocker([nc("0.03"), "confidence 0.41 < 0.7"])).toBe(false);
    expect(isSoleBlocker([])).toBe(false);
    expect(isSoleBlocker(["spread 0.09 > max 0.06"])).toBe(false);
  });
});

describe("priceBucket", () => {
  it("separates tick-floor dust from a buyable longshot", () => {
    expect(priceBucket(0)).toBe("floor");
    expect(priceBucket(0.0049)).toBe("floor");
    expect(priceBucket(NEARCERT_DUST_FLOOR)).toBe("0.005-0.02");
    expect(priceBucket(0.0199)).toBe("0.005-0.02");
    expect(priceBucket(0.02)).toBe("0.02-0.05");
    expect(priceBucket(0.05)).toBe("0.05+");
  });
});

describe("venue clock", () => {
  it("parses the venue's space-separated +00 offset", () => {
    expect(parseVenueClock("2026-10-15 21:00:00+00")).toBe(Date.parse("2026-10-15T21:00:00Z"));
    expect(parseVenueClock("2026-10-20 21:50:22.228128+00")).toBe(Date.parse("2026-10-20T21:50:22.228Z"));
  });

  it("reads an offset-less clock as UTC, not as host-local time", () => {
    expect(parseVenueClock("2026-10-15T21:00:00")).toBe(Date.parse("2026-10-15T21:00:00Z"));
  });

  it("returns null rather than NaN for unreadable input", () => {
    expect(parseVenueClock("not-a-date")).toBeNull();
    expect(parseVenueClock(null)).toBeNull();
  });
});

describe("decisionLiveness", () => {
  it("marks a decision before the close as live", () => {
    expect(decisionLiveness(Date.parse("2026-10-15T20:00:00Z"), true, "2026-10-15 21:00:00+00")).toBe("live");
  });

  it("marks a decision after the close as a post-close poll", () => {
    expect(decisionLiveness(Date.parse("2026-10-16T00:00:00Z"), true, "2026-10-15 21:00:00+00")).toBe("post-close");
  });

  it("treats an open market as live — it cannot have closed before the decision", () => {
    expect(decisionLiveness(Date.now(), false, null)).toBe("live");
  });

  it("never coerces an unknown clock to live", () => {
    expect(decisionLiveness(Date.now(), true, null)).toBe("unknown");
    expect(decisionLiveness(Date.now(), true, "bogus")).toBe("unknown");
  });
});

describe("dedupeToSignal", () => {
  it("keeps the earliest refusal per market+outcome and reports the inflation", () => {
    const rows = [
      { marketId: "m1", outcome: "YES", decidedAtMs: 300 },
      { marketId: "m1", outcome: "YES", decidedAtMs: 100 },
      { marketId: "m1", outcome: "YES", decidedAtMs: 200 },
      { marketId: "m1", outcome: "NO", decidedAtMs: 50 },
      { marketId: "m2", outcome: "YES", decidedAtMs: 10 },
    ];
    const d = dedupeToSignal(rows);
    expect(d.legs).toHaveLength(3);
    expect(d.rows).toBe(5);
    expect(d.inflation).toBeCloseTo(5 / 3, 10);
    expect(d.legs[0].decidedAtMs).toBe(10);
    expect(d.legs.find((l) => l.marketId === "m1" && l.outcome === "YES")?.decidedAtMs).toBe(100);
  });
});

describe("return arithmetic", () => {
  it("prices a longshot hold-to-settlement", () => {
    expect(legReturn(0.03, true)).toBeCloseTo(32.3333, 3);
    expect(legReturn(0.03, false)).toBe(-1);
    expect(legReturn(0.5, true)).toBeCloseTo(1, 10);
  });

  it("refuses to price a dust entry (0 is not infinite leverage)", () => {
    expect(legReturn(0, true)).toBeNull();
    expect(legReturn(null, true)).toBeNull();
    expect(legReturn(1.2, true)).toBeNull();
  });

  it("breakeven win rate is the mean price", () => {
    expect(breakevenWinRate([0.02, 0.04])).toBeCloseTo(0.03, 10);
    expect(breakevenWinRate([])).toBe(0);
  });
});

describe("geometricMeanPerLeg", () => {
  it("reports ruin when any leg is a total loss, instead of dropping it", () => {
    expect(geometricMeanPerLeg([30, -1])).toBe(-1);
  });

  it("compounds the surviving legs otherwise", () => {
    expect(geometricMeanPerLeg([1, 1])).toBeCloseTo(1, 10);
    expect(geometricMeanPerLeg([0.21, 0.21])).toBeCloseTo(0.21, 10);
  });

  it("returns null on an empty population", () => {
    expect(geometricMeanPerLeg([])).toBeNull();
  });
});

describe("fill arithmetic", () => {
  it("scales EV per intent by reach — an unfilled order returns nothing", () => {
    expect(evPerIntent(0.026, 10)).toBeCloseTo(0.26, 10);
    expect(evPerIntent(0, 10)).toBe(0);
  });
});

describe("concentration", () => {
  it("names the share of positive return carried by the top winners", () => {
    expect(topKShare([90, 5, 5, -1, -1], 1)).toBeCloseTo(0.9, 10);
    expect(topKShare([-1, -1], 5)).toBe(0);
  });

  it("ex-top-10 flips the sign of a book carried by ten legs", () => {
    // 20 legs: ten winners of +3, ten losers of -1 -> sum +20, ex-top-10 -10.
    const legs = [
      ...Array.from({ length: 10 }, () => ({ entry: 0.25, ret: 3 })),
      ...Array.from({ length: 10 }, () => ({ entry: 0.25, ret: -1 })),
    ];
    const s = summarizeCohort(legs);
    expect(s.sum).toBeCloseTo(20, 10);
    expect(s.exTop10Sum).toBeCloseTo(-10, 10);
    expect(s.breakevenWinRate).toBeCloseTo(0.25, 10);
    expect(s.winRate).toBeCloseTo(0.5, 10);
    expect(s.top5ShareOfWins).toBeCloseTo(0.5, 10);
  });

  it("an all-loser tail reads -1 per leg with no positive concentration", () => {
    const s = summarizeCohort(Array.from({ length: 12 }, () => ({ entry: 0.03, ret: -1 })));
    expect(s.mean).toBe(-1);
    expect(s.median).toBe(-1);
    expect(s.exTop10Sum).toBe(-2);
    expect(s.geometricMean).toBe(-1);
    expect(s.top5ShareOfWins).toBe(0);
    expect(s.breakevenWinRate).toBeCloseTo(0.03, 10);
  });
});
