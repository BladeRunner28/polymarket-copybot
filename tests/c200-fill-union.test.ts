/**
 * c200-fill-union — the UNION reader and the market-clustered delta
 * (Lane B repair, card `profit-c200-reachability-stamp`, 2026-11-22).
 *
 * These tests pin the four things that make the union read honest:
 *  1. the population is every snapshot's legs, not the last line (the defect
 *     that made item 1's instrument print n=4 / $0.00 on 2026-11-22);
 *  2. evidence beats absence — a tick that carries no evidence never erases a
 *     stamp that had it (the STANDARD booth's rule, kept identical);
 *  3. out-of-order rows resolve to the NEWER stamp, not the last line read;
 *  4. the delta's interval resamples MARKETS (the resolution unit), not legs,
 *     and is deterministic under a fixed seed.
 */
import { describe, expect, it } from "vitest";
import {
  StampUnionFolder,
  marketClusteredDelta,
  stampHasEvidence,
  unionStamps,
  type FillAwareLeg,
} from "../src/lib/c200-fill-resolution";

interface Leg {
  intentId: string;
  reached60?: boolean | null;
  tapeSilent?: boolean | null;
  book?: { minAsk?: number | null } | null;
}

const stamped = (intentId: string, minAsk: number | null): Leg => ({
  intentId,
  book: { minAsk },
  reached60: null,
  tapeSilent: false,
});

describe("stampHasEvidence", () => {
  it("a numeric book minAsk is evidence even with the tape silent", () => {
    expect(stampHasEvidence({ intentId: "a", book: { minAsk: 0.42 }, tapeSilent: true })).toBe(true);
  });
  it("a silent tape is NOT evidence, and neither is an empty book", () => {
    expect(stampHasEvidence({ intentId: "a", book: null, tapeSilent: true, reached60: false })).toBe(false);
    expect(stampHasEvidence({ intentId: "a", book: { minAsk: null }, reached60: null })).toBe(false);
  });
  it("a resolved tape boolean is evidence", () => {
    expect(stampHasEvidence({ intentId: "a", book: null, reached60: false })).toBe(true);
  });
});

describe("unionStamps", () => {
  it("keeps every snapshot's legs — the last line is not the population", () => {
    const u = unionStamps<Leg>([
      { ranAt: 1_000, legs: [stamped("a", 0.4), stamped("b", 0.5)] },
      { ranAt: 2_000, legs: [stamped("c", 0.6)] },
      { ranAt: 3_000, legs: [] },
    ]);
    expect(u.distinctLegs).toBe(3);
    expect(u.legs.map((l) => l.intentId)).toEqual(["a", "b", "c"]);
    expect(u.rows).toBe(3);
    expect(u.rowsWithLegs).toBe(2);
  });

  it("a newer stamp wins when both sides carry evidence", () => {
    const u = unionStamps<Leg>([
      { ranAt: 1_000, legs: [stamped("a", 0.40)] },
      { ranAt: 2_000, legs: [stamped("a", 0.55)] },
    ]);
    expect(u.legs).toHaveLength(1);
    expect(u.legs[0].book?.minAsk).toBe(0.55);
    expect(u.newerWins).toBe(1);
    expect(u.keptOldEvidence).toBe(0);
  });

  it("evidence beats absence: an evidence-less tick cannot erase a stamp", () => {
    const u = unionStamps<Leg>([
      { ranAt: 1_000, legs: [stamped("a", 0.40)] },
      { ranAt: 2_000, legs: [{ intentId: "a", book: null, tapeSilent: true, reached60: false }] },
    ]);
    expect(u.legs[0].book?.minAsk).toBe(0.40);
    expect(u.keptOldEvidence).toBe(1);
    expect(u.newerWins).toBe(0);
  });

  it("an upgrade is counted when the older stamp had nothing", () => {
    const u = unionStamps<Leg>([
      { ranAt: 1_000, legs: [{ intentId: "a", book: null, tapeSilent: true, reached60: false }] },
      { ranAt: 2_000, legs: [stamped("a", 0.31)] },
    ]);
    expect(u.legs[0].book?.minAsk).toBe(0.31);
    expect(u.upgraded).toBe(1);
  });

  it("out-of-order rows resolve to the newer ranAt, not the last line read", () => {
    const u = unionStamps<Leg>([
      { ranAt: 3_000, legs: [stamped("a", 0.70)] },
      { ranAt: 2_000, legs: [stamped("a", 0.20)] },
    ]);
    expect(u.legs[0].book?.minAsk).toBe(0.70);
    expect(u.firstRanAt).toBe(2_000);
    expect(u.lastRanAt).toBe(3_000);
  });

  it("a row without a timestamp cannot claim the range", () => {
    const u = unionStamps<Leg>([
      { ranAt: 0, legs: [stamped("a", 0.1)] },
      { ranAt: 5_000, legs: [stamped("b", 0.2)] },
    ]);
    expect(u.firstRanAt).toBe(5_000);
    expect(u.lastRanAt).toBe(5_000);
  });

  it("the streaming folder agrees with the in-memory wrapper", () => {
    const rows = [
      { ranAt: 1_000, legs: [stamped("a", 0.4), stamped("b", 0.5)] },
      { ranAt: 2_000, legs: [stamped("b", null as unknown as number), stamped("c", 0.6)] },
    ];
    const f = new StampUnionFolder<Leg>();
    for (const r of rows) f.add(r);
    expect(f.result()).toEqual(unionStamps<Leg>(rows));
  });
});

// ------------------------------------------------------------------ clustered delta

const aware = (
  marketId: string,
  realizedPnl: number | null,
  sizeUsd: number,
  reachable: boolean
): FillAwareLeg => ({
  marketId,
  sizeUsd,
  realizedPnl,
  leg: {
    intentPrice: 0.5,
    // book evidence decides reachability deterministically at the flat level
    // (0.48 = intent − 2c): at or below the level = reachable.
    bookMinAsk: reachable ? 0.40 : 0.60,
    tapeReached5: null,
    tapeReached60: null,
  },
});

describe("marketClusteredDelta", () => {
  const legs: FillAwareLeg[] = [
    // three markets: all lose, only the first is reachable
    aware("m1", -10, 100, true),
    aware("m2", -20, 100, false),
    aware("m2", +5, 100, false),
    aware("m3", -5, 100, false),
  ];

  it("prices both arms per dollar of INTENDED copy on one denominator", () => {
    const d = marketClusteredDelta(legs, "flat");
    // booked = -30 on 400 = -7.5%; fill-aware = -10 on 400 = -2.5%
    expect(d.bookedRoiPct).toBeCloseTo(-7.5, 6);
    expect(d.fillAwareRoiPct).toBeCloseTo(-2.5, 6);
    expect(d.deltaPct).toBeCloseTo(5, 6);
    expect(d.markets).toBe(3);
    expect(d.settledMarkets).toBe(3);
    expect(d.legs).toBe(4);
  });

  it("is deterministic under a fixed seed and reports its seed", () => {
    const a = marketClusteredDelta(legs, "flat", { reps: 300, seed: 7 });
    const b = marketClusteredDelta(legs, "flat", { reps: 300, seed: 7 });
    expect(a).toEqual(b);
    expect(a.seed).toBe(7);
    expect(a.reps).toBe(300);
  });

  it("brackets the point estimate and widens with fewer markets", () => {
    const many: FillAwareLeg[] = [];
    for (let i = 0; i < 40; i++) many.push(aware(`m${i}`, i % 2 ? -4 : 3, 100, i % 3 === 0));
    const wide = marketClusteredDelta(many, "flat");
    expect(wide.ciLoPct).not.toBeNull();
    expect(wide.ciHiPct as number).toBeGreaterThanOrEqual(wide.ciLoPct as number);
    expect(wide.deltaPct as number).toBeGreaterThanOrEqual(wide.ciLoPct as number);
    expect(wide.deltaPct as number).toBeLessThanOrEqual(wide.ciHiPct as number);
  });

  it("returns nulls (never a number) below two settled markets", () => {
    const one = marketClusteredDelta([aware("m1", -10, 100, true), aware("m1", -5, 100, false)], "flat");
    expect(one.deltaPct).toBeNull();
    expect(one.ciLoPct).toBeNull();
    expect(one.settledMarkets).toBe(1);
  });

  it("ignores unsettled legs in BOTH arms", () => {
    const withOpen = [...legs, aware("m4", null, 100, true)];
    const d = marketClusteredDelta(withOpen, "flat");
    expect(d.bookedRoiPct).toBeCloseTo(-7.5, 6);
    expect(d.legs).toBe(5);
  });
});
