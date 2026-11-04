/**
 * Lag persistence — pins the arithmetic the wallet-lag-persistence read depends on.
 *
 * The defects this class has produced before are all the same shape: a printed number
 * whose basis is not what the caption claims. So the tests are written as a NEGATIVE
 * CONTROL first — the fixtures are constructed so that a lazy implementation (take the
 * last print, whatever its age; clamp an unusable price; count an unpriced leg as zero)
 * produces a visibly better number than the honest one. If any of those pass, this file
 * fails.
 */
import { describe, expect, it } from "vitest";
import {
  copyReturnPerDollar,
  DEFAULT_GRACE_MS,
  DEFAULT_STALENESS_MS,
  isValidPrice,
  LAGS_MS,
  meanRetAtLag,
  persistenceDelta,
  priceAtLag,
  sortPrints,
  summariseCells,
  TapePrint,
} from "../src/lib/lag-persistence";

const T0 = 1_791_000_000_000; // fixed epoch so nothing in this file reads a clock
const m = (n: number) => n * 60_000;

describe("priceAtLag — the print a delayed copy would have paid", () => {
  const tape: TapePrint[] = [
    { ts: T0, price: 0.4 },
    { ts: T0 + m(9), price: 0.45 },
    { ts: T0 + m(31), price: 0.62 },
  ];

  it("uses the last print at or before the target", () => {
    const got = priceAtLag(tape, T0, m(10));
    expect(got).not.toBeNull();
    expect(got!.price).toBe(0.45);
    expect(got!.basis).toBe("print_at_or_before");
    expect(got!.stalenessMs).toBe(m(1));
  });

  it("falls forward inside the grace window and SAYS so", () => {
    const got = priceAtLag(tape, T0, m(30));
    expect(got!.price).toBe(0.62);
    expect(got!.basis).toBe("print_after");
    expect(got!.stalenessMs).toBe(m(1));
  });

  it("refuses a print older than the staleness floor instead of quoting it", () => {
    // The only print on this tape is a 0.40 winner. A copy one hour later priced at it
    // would read +1.50 of pure fiction; the honest answer is null.
    expect(priceAtLag([{ ts: T0, price: 0.4 }], T0, m(60))).toBeNull();
    expect(DEFAULT_STALENESS_MS).toBe(m(20));
  });

  it("refuses a print beyond the grace window", () => {
    expect(priceAtLag([{ ts: T0 + m(40), price: 0.5 }], T0, m(30))).toBeNull();
    expect(DEFAULT_GRACE_MS).toBe(m(5));
  });

  it("never prices from an untradable print", () => {
    const bad: TapePrint[] = [
      { ts: T0, price: 0 },
      { ts: T0 + m(1), price: Number.NaN },
      { ts: T0 + m(2), price: 1.4 },
    ];
    expect(priceAtLag(bad, T0, m(10))).toBeNull();
  });

  it("returns null on an empty tape", () => {
    expect(priceAtLag([], T0, 0)).toBeNull();
  });

  it("sortPrints puts an unsorted tape in order without mutating the input", () => {
    const unsorted: TapePrint[] = [{ ts: T0 + 2, price: 0.3 }, { ts: T0, price: 0.2 }];
    const sorted = sortPrints(unsorted);
    expect(sorted.map((p) => p.ts)).toEqual([T0, T0 + 2]);
    expect(unsorted[0].ts).toBe(T0 + 2);
  });

  it("the card lags are 0 / 10m / 30m / 1h", () => {
    expect(LAGS_MS).toEqual([0, m(10), m(30), m(60)]);
  });
});

describe("copyReturnPerDollar — return on the money a copy would stake", () => {
  it("a winning 0.40 entry returns +1.50, the same entry losing returns -1.00", () => {
    expect(copyReturnPerDollar(1, 0.4)).toBeCloseTo(1.5, 10);
    expect(copyReturnPerDollar(0, 0.4)).toBeCloseTo(-1, 10);
  });

  it("returns 0 for a winning entry at 1.00 (no room left) rather than null", () => {
    expect(copyReturnPerDollar(1, 1)).toBe(0);
  });

  it("refuses unusable prices and payout values", () => {
    expect(copyReturnPerDollar(1, 0)).toBeNull();
    expect(copyReturnPerDollar(1, 1.2)).toBeNull();
    expect(copyReturnPerDollar(1, Number.NaN)).toBeNull();
    expect(copyReturnPerDollar(0.5, 0.5)).toBeNull();
  });

  it("isValidPrice draws the line at 0 < p <= 1", () => {
    expect(isValidPrice(0.01)).toBe(true);
    expect(isValidPrice(1)).toBe(true);
    expect(isValidPrice(0)).toBe(false);
    expect(isValidPrice(1.01)).toBe(false);
    expect(isValidPrice(null)).toBe(false);
  });
});

describe("summariseCells — one cell per wallet per lag, unpriced legs excluded", () => {
  it("counts only priced legs and averages the rest", () => {
    const cells = summariseCells([
      { wallet: "A", lagMs: 0, ret: 1.0 },
      { wallet: "A", lagMs: 0, ret: -1.0 },
      { wallet: "A", lagMs: 0, ret: null },
      { wallet: "A", lagMs: m(60), ret: 0.5 },
      { wallet: "B", lagMs: 0, ret: -1.0 },
    ]);
    const a0 = cells.get("A")!.get(0)!;
    expect(a0.n).toBe(2);
    expect(a0.meanRet).toBeCloseTo(0, 10);
    expect(a0.winRate).toBeCloseTo(0.5, 10);
    expect(cells.get("A")!.get(m(60))!.n).toBe(1);
    expect(cells.get("B")!.get(m(60))).toBeUndefined();
  });

  it("a null return is never silently treated as a zero (the flattering answer)", () => {
    const cells = summariseCells([
      { wallet: "A", lagMs: m(60), ret: 2.0 },
      { wallet: "A", lagMs: m(60), ret: null },
      { wallet: "A", lagMs: m(60), ret: null },
    ]);
    const c = cells.get("A")!.get(m(60))!;
    expect(c.n).toBe(1);
    expect(c.meanRet).toBe(2.0);
  });

  it("median is the middle draw on odd n and the mean of the middle pair on even n", () => {
    const odd = summariseCells([1, 3, 10].map((r) => ({ wallet: "W", lagMs: 0, ret: r })));
    expect(odd.get("W")!.get(0)!.medianRet).toBe(3);
    const even = summariseCells([-1, 0, 1, 4].map((r) => ({ wallet: "W", lagMs: 0, ret: r })));
    expect(even.get("W")!.get(0)!.medianRet).toBe(0.5);
  });

  it("drops non-finite returns instead of propagating NaN into a mean", () => {
    const cells = summariseCells([
      { wallet: "W", lagMs: 0, ret: 1 },
      { wallet: "W", lagMs: 0, ret: Number.POSITIVE_INFINITY },
    ]);
    expect(cells.get("W")!.get(0)!.meanRet).toBe(1);
  });
});

describe("persistenceDelta and meanRetAtLag", () => {
  const legs = [
    { wallet: "A", lagMs: 0, ret: 0.5 },
    { wallet: "A", lagMs: m(60), ret: -0.2 },
    { wallet: "B", lagMs: 0, ret: -1.0 },
  ];

  it("reports the drop from the wallet own fill to the delayed one", () => {
    const cells = summariseCells(legs);
    expect(persistenceDelta(cells, "A", 0, m(60))).toBeCloseTo(-0.7, 10);
  });

  it("is null when either lag is missing for that wallet", () => {
    const cells = summariseCells(legs);
    expect(persistenceDelta(cells, "B", 0, m(60))).toBeNull();
    expect(persistenceDelta(cells, "nobody", 0, m(60))).toBeNull();
  });

  it("meanRetAtLag pools only that lag and returns null on an empty lag", () => {
    expect(meanRetAtLag(legs, 0)).toBeCloseTo(-0.25, 10);
    expect(meanRetAtLag(legs, m(30))).toBeNull();
  });
});
