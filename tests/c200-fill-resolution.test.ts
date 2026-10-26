/**
 * c200-fill-resolution — the shared reachability/fill-aware resolver.
 *
 * These tests pin the four things that make the reported number honest:
 *  1. the credit mirrors the sidecar (flat 2c; live = 2c × measured share; a $0.01 floor);
 *  2. the tape's asymmetry — a NO at the deeper flat level is a valid no at any
 *     shallower credit, a YES there is NOT a yes at a shallower credit;
 *  3. unresolved legs are excluded from rates, never counted as "did not fill";
 *  4. an unreached leg is booked at $0 PnL AND $0 notional (not a haircut).
 */
import { describe, expect, it } from "vitest";
import {
  FILL_BANDS,
  bandOf,
  creditUsdFor,
  levelFor,
  resolveFill,
  summariseFillAware,
  type FillAwareLeg,
  type ResolutionLeg,
} from "../src/lib/c200-fill-resolution";

const leg = (o: Partial<ResolutionLeg> = {}): ResolutionLeg => ({
  intentPrice: 0.5,
  bookMinAsk: null,
  tapeReached5: null,
  tapeReached60: null,
  ...o,
});

describe("credit + level", () => {
  it("flat credit is exactly the sidecar's 2c", () => {
    expect(creditUsdFor(0.05, "flat")).toBeCloseTo(0.02, 10);
    expect(creditUsdFor(0.5, "flat")).toBeCloseTo(0.02, 10);
  });

  it("live credit is 2c x the measured share for the band (0.40-0.60 => 0.375c)", () => {
    // MEASURED_FILL_WEIGHTS 0.40-0.60: book1h 0.176, tape1h 0.199 -> mean 0.1875
    expect(creditUsdFor(0.5, "live")).toBeCloseTo(0.02 * 0.1875, 10);
    expect(creditUsdFor(0.15, "live")).toBeCloseTo(0.02 * ((0.067 + 0.1) / 2), 10);
  });

  it("live credit is never larger than the flat credit and never negative", () => {
    for (const p of [0.01, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 0.99]) {
      const live = creditUsdFor(p, "live");
      expect(live).toBeGreaterThanOrEqual(0);
      expect(live).toBeLessThanOrEqual(creditUsdFor(p, "flat") + 1e-12);
    }
  });

  it("the level mirrors the sidecar's $0.01 clamp", () => {
    expect(levelFor(0.5, "flat")).toBeCloseTo(0.48, 10);
    expect(levelFor(0.02, "flat")).toBe(0.01);
    expect(levelFor(0.0105, "flat")).toBe(0.01); // 0.0105 - 0.02 is below the floor
    expect(levelFor(0.02, "live")).toBeCloseTo(0.02 - 0.00056, 6); // above the floor: no clamp
  });
});

describe("resolveFill — evidence precedence", () => {
  it("our own book is the direct test: ask at/below the level is reachable", () => {
    const v = resolveFill(leg({ bookMinAsk: 0.48 }), "flat");
    expect(v.reachable).toBe(true);
    expect(v.basis).toBe("book-window");
    expect(v.level).toBeCloseTo(0.48, 10);
  });

  it("an ask above the level is not reachable", () => {
    const v = resolveFill(leg({ bookMinAsk: 0.49 }), "flat");
    expect(v.reachable).toBe(false);
    expect(v.basis).toBe("book-window");
  });

  it("book beats tape: a tape YES does not override an ask that never reached", () => {
    const v = resolveFill(leg({ bookMinAsk: 0.6, tapeReached60: true }), "flat");
    expect(v.reachable).toBe(false);
    expect(v.basis).toBe("book-window");
  });

  it("tape NO at the deeper flat level is a valid NO under the live (shallower) credit", () => {
    const v = resolveFill(leg({ tapeReached60: false }), "live");
    expect(v.reachable).toBe(false);
    expect(v.basis).toBe("tape-lower-bound");
  });

  it("tape YES at the flat level is a fill only under the flat model", () => {
    expect(resolveFill(leg({ tapeReached60: true }), "flat").reachable).toBe(true);
    const live = resolveFill(leg({ tapeReached60: true }), "live");
    expect(live.reachable).toBe(false);
    expect(live.basis).toBe("unresolved"); // must NOT be read as "did not fill"
  });

  it("no evidence at all is unresolved, not a miss", () => {
    const v = resolveFill(leg({ tapeReached60: null }), "live");
    expect(v.reachable).toBe(false);
    expect(v.basis).toBe("unresolved");
  });
});

describe("summariseFillAware — accounting", () => {
  const row = (o: Partial<FillAwareLeg> & { leg: ResolutionLeg }): FillAwareLeg => ({
    realizedPnl: null,
    sizeUsd: 100,
    ...o,
  });

  it("an unreached leg is $0 PnL and $0 notional in the fill-aware book", () => {
    const legs = [
      row({ leg: leg({ bookMinAsk: 0.49 }), realizedPnl: 10, sizeUsd: 100 }), // live-reachable
      row({ leg: leg({ bookMinAsk: 0.6 }), realizedPnl: -30, sizeUsd: 100 }), // never reached
    ];
    const s = summariseFillAware(legs, "live");
    expect(s.total.bookedPnlUsd).toBeCloseTo(-20, 9);
    expect(s.total.fillAwarePnlUsd).toBeCloseTo(10, 9);
    expect(s.total.notionalUsd).toBeCloseTo(200, 9);
    expect(s.total.reachableNotionalUsd).toBeCloseTo(100, 9);
    expect(s.total.bookedRoiPct).toBeCloseTo(-10, 9);
    expect(s.total.roiGivenFillPct).toBeCloseTo(10, 9);
    // per intended copy: the same PnL over the notional of BOTH intents
    expect(s.total.perIntendedCopyPct).toBeCloseTo(5, 9);
    expect(s.total.settled).toBe(2);
  });

  it("unresolved legs are excluded from the rate's denominator", () => {
    const legs = [
      row({ leg: leg({ bookMinAsk: 0.47 }) }), // reachable
      row({ leg: leg({ bookMinAsk: 0.6 }) }), // not reachable
      row({ leg: leg({}) }), // unresolved
    ];
    const s = summariseFillAware(legs, "flat");
    expect(s.total.attempted).toBe(2);
    expect(s.total.unresolved).toBe(1);
    expect(s.total.reachable).toBe(1);
    expect(s.total.reachRate).toBeCloseTo(0.5, 12);
  });

  it("open legs carry reach but no PnL opinion", () => {
    const legs = [
      row({ leg: leg({ bookMinAsk: 0.47 }), realizedPnl: null }),
      row({ leg: leg({ bookMinAsk: 0.47 }), realizedPnl: 4 }),
    ];
    const s = summariseFillAware(legs, "flat");
    expect(s.total.attempted).toBe(2);
    expect(s.total.reachable).toBe(2);
    expect(s.total.settled).toBe(1);
    expect(s.total.fillAwarePnlUsd).toBeCloseTo(4, 9);
  });

  it("bands partition the population and keep intent-price order", () => {
    const legs = [
      row({ leg: leg({ intentPrice: 0.05, bookMinAsk: 0.02, tapeReached60: false }), realizedPnl: -5 }),
      row({ leg: leg({ intentPrice: 0.5, bookMinAsk: 0.48, tapeReached60: true }), realizedPnl: 7 }),
    ];
    const s = summariseFillAware(legs, "flat");
    expect(s.byBand.map((b) => b.label)).toEqual(["0.00-0.10", "0.40-0.60"]);
    expect(s.total.bookedPnlUsd).toBeCloseTo(2, 9);
    expect(bandOf(0.05)).toBe("0.00-0.10");
    expect(bandOf(0.999)).toBe("0.80-1.00");
    expect(FILL_BANDS.length).toBe(6);
  });

  it("ex-top-10 is null until there are more than ten legs, then drops the ten best", () => {
    const few = Array.from({ length: 10 }, () => row({ leg: leg({ bookMinAsk: 0.47 }), realizedPnl: 1 }));
    expect(summariseFillAware(few, "flat").total.exTop10BookedUsd).toBeNull();

    const many = Array.from({ length: 12 }, (_, i) =>
      row({ leg: leg({ bookMinAsk: 0.47 }), realizedPnl: i + 1 })
    );
    // 1..12 = 78; minus the ten best (3..12 = 75) leaves 1 + 2
    expect(summariseFillAware(many, "flat").total.exTop10BookedUsd).toBeCloseTo(3, 9);
  });

  it("median leg PnL is reported for both books", () => {
    const legs = [1, 2, 100].map((p) =>
      row({ leg: leg({ intentPrice: 0.6, bookMinAsk: 0.5 }), realizedPnl: p })
    );
    const s = summariseFillAware(legs, "flat");
    expect(s.total.medianBookedPnlUsd).toBeCloseTo(2, 9);
    expect(s.total.medianFillAwarePnlUsd).toBeCloseTo(2, 9);
  });
});
