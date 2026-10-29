/**
 * standard-fill-stamp — the STANDARD fill booth's falsifiability contract.
 *
 * These tests pin the four things that make the reported distribution honest:
 *  1. no evidence is NOT a zero delta (a zero would mean "filled at the booked
 *     price" — the exact claim under test), so unresolved legs leave the rates;
 *  2. the buckets are half-open and ordered, so a leg cannot appear twice;
 *  3. sign: POSITIVE delta = the attainable entry was WORSE than the booked price;
 *  4. the card's decision rule is EVALUATED: the ±0.3c-of-mid refutation only fires
 *     at n >= 300, and the mean and median verdicts are reported separately.
 */
import { describe, expect, it } from "vitest";
import { creditUsdFor, levelFor, resolveFill } from "../src/lib/c200-fill-resolution";
import {
  GATE_LEGS,
  STANDARD_CREDIT_MODE,
  STAMP_LAG_BUCKETS,
  WIDEST_BUCKET,
  bucketForLag,
  deltaCents,
  evaluateRefutation,
  reachability,
  summariseStamps,
  type StampLeg,
  type StampObservation,
} from "../src/lib/standard-fill-stamp";

const obs = (price: number, mid: number | null = null): StampObservation => ({ price, mid });

const leg = (o: Partial<StampLeg> = {}): StampLeg => ({
  id: "t1",
  decisionPrice: 0.5,
  sizeUsd: 10,
  book: null,
  tape: null,
  ...o,
});

/** A book-stamped leg whose ask sits `d` cents above the decision in every bucket. */
const booked = (d: number, midOffsetC: number | null = d, sizeUsd = 10, id = "t"): StampLeg => {
  const byBucket: Record<string, StampObservation | null> = {};
  for (const b of STAMP_LAG_BUCKETS) {
    const ask = 0.5 + d / 100;
    const mid = midOffsetC === null ? null : 0.5 + midOffsetC / 100;
    byBucket[b.label] = obs(ask, mid);
  }
  return leg({ id, sizeUsd, book: { coverLagMs: 1_000, tokenAmbiguous: false, firstAsk: 0.5 + d / 100, firstBid: 0.5, byBucket } });
};

describe("mode none — the shared resolver, not a fork of it", () => {
  it("books no credit, so the level IS the booked price", () => {
    expect(creditUsdFor(0.5, "none")).toBe(0);
    expect(creditUsdFor(0.07, "none")).toBe(0);
    expect(levelFor(0.5, "none")).toBeCloseTo(0.5, 12);
    expect(STANDARD_CREDIT_MODE).toBe("none");
  });

  it("resolves the booked price reachable from the book window", () => {
    const v = resolveFill(
      { intentPrice: 0.5, bookMinAsk: 0.4999, tapeReached5: null, tapeReached60: null },
      "none"
    );
    expect(v.level).toBeCloseTo(0.5, 12);
    expect(v.reachable).toBe(true);
    expect(v.basis).toBe("book-window");
  });

  it("a tape-positive leg is NOT a fill at the shallower decision level", () => {
    const v = resolveFill(
      { intentPrice: 0.5, bookMinAsk: null, tapeReached5: true, tapeReached60: true },
      "none"
    );
    expect(v.basis).toBe("unresolved");
    expect(v.reachable).toBe(false);
  });

  it("a tape NEGATIVE is still a valid negative at the decision level", () => {
    const v = resolveFill(
      { intentPrice: 0.5, bookMinAsk: null, tapeReached5: false, tapeReached60: false },
      "none"
    );
    expect(v.basis).toBe("tape-lower-bound");
    expect(v.reachable).toBe(false);
  });
});

describe("deltas and buckets", () => {
  it("sign: attainable above the decision is a POSITIVE (worse) delta in cents", () => {
    expect(deltaCents(0.51, 0.5)).toBeCloseTo(1, 10);
    expect(deltaCents(0.49, 0.5)).toBeCloseTo(-1, 10);
    expect(deltaCents(0.5, 0.5)).toBe(0);
  });

  it("buckets are ordered and half-open at the top", () => {
    expect(bucketForLag(0)).toBe("0-10s");
    expect(bucketForLag(10_000)).toBe("0-10s");
    expect(bucketForLag(10_001)).toBe("10-30s");
    expect(bucketForLag(3_600_000)).toBe("30-60m");
    expect(bucketForLag(99_999_999)).toBe(WIDEST_BUCKET);
    const bounds = STAMP_LAG_BUCKETS.map((b) => b.maxMs);
    expect(bounds).toEqual([...bounds].sort((a, b) => a - b));
  });
});

describe("summariseStamps", () => {
  it("excludes a leg with no evidence instead of scoring it 0", () => {
    const s = summariseStamps([booked(1, 0.5, 10, "a"), leg({ id: "b" })], "book");
    expect(s.coverage.offered).toBe(2);
    expect(s.coverage.covered).toBe(1);
    expect(s.total.n).toBe(1);
    expect(s.total.meanC).toBeCloseTo(1, 6);
    expect(s.coverage.rate).toBeCloseTo(0.5, 10);
  });

  it("counts the shares the card is read on, per bucket", () => {
    const legs = [booked(2, 0.1, 10, "a"), booked(0, 0, 10, "b"), booked(-1, -0.2, 10, "c")];
    const s = summariseStamps(legs, "book");
    const c = s.cells.find((x) => x.bucket === STAMP_LAG_BUCKETS[0].label);
    expect(c?.n).toBe(3);
    expect(c?.atOrBetter).toBe(2); // 0c and -1c
    expect(c?.worseBy1c).toBe(1); // +2c
    expect(c?.withinBand).toBe(1); // only the 0c leg is within ±0.3c of the decision
    expect(c?.notionalUsd).toBe(30);
    expect(c?.meanC).toBeCloseTo(1 / 3, 4);
    expect(c?.medianC).toBeCloseTo(0, 6);
  });

  it("keeps an empty bucket at n=0 rather than dropping it", () => {
    const byBucket: Record<string, StampObservation | null> = {};
    for (const b of STAMP_LAG_BUCKETS) byBucket[b.label] = null;
    byBucket[WIDEST_BUCKET] = obs(0.51, 0.505);
    const s = summariseStamps(
      [leg({ book: { coverLagMs: 3_600_000, tokenAmbiguous: false, firstAsk: 0.51, firstBid: 0.5, byBucket } })],
      "book"
    );
    expect(s.cells[0].n).toBe(0);
    expect(s.cells[0].meanC).toBeNull();
    expect(s.total.n).toBe(1);
    expect(s.coverage.coveredWidest).toBe(1);
  });

  it("records the tape arm separately — same legs, no mid", () => {
    const tapeLeg = leg({
      tape: { prints: 4, byBucket: Object.fromEntries(STAMP_LAG_BUCKETS.map((b) => [b.label, obs(0.49)])) },
    });
    const s = summariseStamps([tapeLeg, booked(1)], "tape");
    expect(s.coverage.covered).toBe(1);
    expect(s.total.n).toBe(1);
    expect(s.total.meanMidC).toBeNull(); // prints carry no mid: the refutation cannot use this arm
    expect(s.total.midN).toBe(0);
  });
});

describe("evaluateRefutation — the card's pre-registered rule", () => {
  const legsAt = (n: number, deltaC: number, midOffsetC: number): StampLeg[] =>
    Array.from({ length: n }, (_, i) => booked(deltaC, midOffsetC, 10, `l${i}`));

  it("does NOT fire below the 300-leg gate, however tempting the number", () => {
    const s = summariseStamps(legsAt(GATE_LEGS - 1, 0, 0), "book");
    const v = evaluateRefutation(s);
    expect(v.gateMet).toBe(false);
    expect(v.fired).toBe(false);
    expect(v.n).toBe(GATE_LEGS - 1);
    expect(v.reason).toContain("NOT EVALUABLE");
  });

  it("fires at n>=300 when the stamp lands inside ±0.3c of the mid", () => {
    const v = evaluateRefutation(summariseStamps(legsAt(GATE_LEGS, 0.2, 0.2), "book"));
    expect(v.gateMet).toBe(true);
    expect(v.fired).toBe(true);
    expect(v.reason).toContain("REFUTED");
  });

  it("does not fire at n>=300 when the gap is real (outside ±0.3c)", () => {
    const v = evaluateRefutation(summariseStamps(legsAt(GATE_LEGS, 1.5, 1.5), "book"));
    expect(v.gateMet).toBe(true);
    expect(v.fired).toBe(false);
    expect(v.reason).toContain("NOT REFUTED");
  });

  it("surfaces a mean/median disagreement instead of picking the friendlier one", () => {
    // 299 legs at 0.0c and one leg at +300c: median inside the band, mean far outside.
    const legs = [...legsAt(GATE_LEGS - 1, 0, 0), booked(300, 300, 10, "outlier")];
    const v = evaluateRefutation(summariseStamps(legs, "book"));
    expect(v.n).toBe(GATE_LEGS);
    expect(v.fired).toBe(false); // mean basis: the money-weighted test
    expect(v.firedOnMedian).toBe(true); // and the disagreement is returned, not hidden
  });

  it("never lets the tape arm carry the ±0.3c-of-mid verdict", () => {
    const tapeLegs = Array.from({ length: GATE_LEGS }, (_, i) =>
      leg({
        id: `t${i}`,
        tape: { prints: 2, byBucket: Object.fromEntries(STAMP_LAG_BUCKETS.map((b) => [b.label, obs(0.5)])) },
      })
    );
    const v = evaluateRefutation(summariseStamps(tapeLegs, "tape"));
    expect(v.n).toBe(0);
    expect(v.gateMet).toBe(false);
    expect(v.fired).toBe(false);
  });
});

describe("reachability in the resolver's terms", () => {
  it("counts only resolved legs and never reports a tape-positive as a fill", () => {
    const r = reachability([
      booked(0), // book: ask == decision → reachable
      booked(2), // book: ask above → not reachable
      leg({ id: "tapeyes", tape: { prints: 1, byBucket: { [WIDEST_BUCKET]: obs(0.49) } } }),
      leg({ id: "nothing" }),
    ]);
    expect(r.attempted).toBe(2);
    expect(r.reachable).toBe(1);
    expect(r.unresolved).toBe(2);
    expect(r.rate).toBeCloseTo(0.5, 10);
  });
});
