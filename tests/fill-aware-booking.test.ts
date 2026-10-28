import { describe, it, expect, afterEach } from "vitest";
import { bookedPnl, fillAwareBookingEnabled, computePnl } from "../src/lib/paper";

/**
 * Fill-aware booking (approved 2026-10-27, re-affirmed 2026-10-28, coverage floor waived).
 *
 * The property that matters is CONSERVATISM: the flag must only ever remove PnL from legs the resolver
 * positively proved never filled. An unresolved leg (fillStatus NULL) must pass through untouched, or the
 * flip would be manufacturing losses out of ignorance rather than removing a fiction.
 */

const ORIGINAL = process.env.FILL_AWARE_BOOKING;
afterEach(() => {
  if (ORIGINAL === undefined) delete process.env.FILL_AWARE_BOOKING;
  else process.env.FILL_AWARE_BOOKING = ORIGINAL;
});

describe("fill-aware booking", () => {
  it("is OFF unless the env flag is exactly '1'", () => {
    delete process.env.FILL_AWARE_BOOKING;
    expect(fillAwareBookingEnabled()).toBe(false);
    for (const v of ["0", "true", "yes", "", "2"]) {
      process.env.FILL_AWARE_BOOKING = v;
      expect(fillAwareBookingEnabled(), `FILL_AWARE_BOOKING=${JSON.stringify(v)} must not enable it`).toBe(false);
    }
    process.env.FILL_AWARE_BOOKING = "1";
    expect(fillAwareBookingEnabled()).toBe(true);
  });

  it("with the flag OFF, every leg books exactly as before regardless of fillStatus", () => {
    delete process.env.FILL_AWARE_BOOKING;
    for (const s of ["filled", "unfilled", null, undefined]) {
      expect(bookedPnl({ fillStatus: s as string | null }, 12.34)).toBe(12.34);
      expect(bookedPnl({ fillStatus: s as string | null }, -18)).toBe(-18);
    }
  });

  it("with the flag ON, a proven-unfilled leg books $0 — it was never a position", () => {
    process.env.FILL_AWARE_BOOKING = "1";
    expect(bookedPnl({ fillStatus: "unfilled" }, 45.5)).toBe(0);
    expect(bookedPnl({ fillStatus: "unfilled" }, -18)).toBe(0);
  });

  it("with the flag ON, a filled leg keeps its PnL untouched", () => {
    process.env.FILL_AWARE_BOOKING = "1";
    expect(bookedPnl({ fillStatus: "filled" }, 45.5)).toBe(45.5);
    expect(bookedPnl({ fillStatus: "filled" }, -18)).toBe(-18);
  });

  it("with the flag ON, an UNRESOLVED leg (null) passes through — never written to zero", () => {
    // This is the case that makes waiving the 80% floor safe. 26.4% of intents hold no evidence either
    // way; zeroing them would convert "we don't know" into "it didn't happen".
    process.env.FILL_AWARE_BOOKING = "1";
    expect(bookedPnl({ fillStatus: null }, 45.5)).toBe(45.5);
    expect(bookedPnl({ fillStatus: undefined }, -18)).toBe(-18);
    expect(bookedPnl({}, 7)).toBe(7);
  });

  it("moves every affected leg TOWARD ZERO — it removes a position, not a win", () => {
    process.env.FILL_AWARE_BOOKING = "1";
    // The naive invariant "no leg gains" is WRONG and this test exists because the first version
    // asserted it and failed on an unfilled LOSER: -18 -> 0 is a gain. A leg that never filled has no
    // PnL in either direction, so the flip deletes fictional wins AND fictional losses. That means the
    // aggregate direction is EMPIRICAL, not guaranteed negative -- which is why the effect on the real
    // book has to be measured (scripts/c200-fill-aware-pnl.ts) rather than assumed from the 61%
    // "never filled" headline.
    const legs = [
      { fillStatus: "unfilled", pnl: 100 },
      { fillStatus: "unfilled", pnl: -18 },
      { fillStatus: "filled", pnl: 40 },
      { fillStatus: null, pnl: -25 },
    ];
    for (const l of legs) {
      const after = bookedPnl(l, l.pnl);
      expect(Math.abs(after), `leg ${JSON.stringify(l)} must not move away from zero`).toBeLessThanOrEqual(
        Math.abs(l.pnl)
      );
      // a filled or unresolved leg is untouched, bit for bit
      if (l.fillStatus !== "unfilled") expect(after).toBe(l.pnl);
    }
  });

  it("does not silently un-book a losing leg into a win in aggregate without saying so", () => {
    process.env.FILL_AWARE_BOOKING = "1";
    // Two unfilled losers, one unfilled winner: the flip is a NET IMPROVEMENT here, by design.
    const legs = [
      { fillStatus: "unfilled", pnl: 10 },
      { fillStatus: "unfilled", pnl: -30 },
      { fillStatus: "unfilled", pnl: -30 },
    ];
    const before = legs.reduce((a, l) => a + l.pnl, 0);
    const after = legs.reduce((a, l) => a + bookedPnl(l, l.pnl), 0);
    expect(before).toBe(-50);
    expect(after).toBe(0);
  });

  it("composes with computePnl without changing the arithmetic", () => {
    process.env.FILL_AWARE_BOOKING = "1";
    const raw = computePnl(0.4, 1, 10);
    expect(raw).toBeCloseTo(15, 10);
    expect(bookedPnl({ fillStatus: "filled" }, raw)).toBeCloseTo(15, 10);
    expect(bookedPnl({ fillStatus: "unfilled" }, raw)).toBe(0);
  });
});
