import { describe, it, expect } from "vitest";
import {
  bookedFee,
  feeNetLedgerEnabled,
  feeUsdAtEntry,
  feeUsdAtExit,
  impliedExitPrice,
  netPnl,
  resolveFeeRate,
} from "../src/lib/fee";
import { takerFeePerShare } from "../src/lib/scoring/price-edge";

/**
 * The fee law is NOT re-implemented here — these reference values are the closed
 * form the book's read instruments use (scripts/profit-fee-net.py `fee_entry` /
 * `fee_exit`), so a booking that disagrees with them is a booking that disagrees
 * with every measurement the card quotes.
 *
 *   fee_entry = size * rate * (1 - p)
 *   fee_exit  = (size / p) * rate * c * (1 - c)
 */
const PY_FEE_ENTRY = (size: number, p: number, rate: number) => size * rate * (1 - p);
const PY_FEE_EXIT = (size: number, p: number, c: number, rate: number) => (size / p) * rate * c * (1 - c);

const close = (a: number, b: number) => Math.abs(a - b) < 0.0051; // booked values are rounded to cents

describe("fee law (entry)", () => {
  it("matches the Python instrument on the boundaries and the mid", () => {
    const cases = [
      { p: 0.02, size: 10, rate: 0.05 },
      { p: 0.05, size: 20, rate: 0.07 },
      { p: 0.5, size: 10, rate: 0.05 },
      { p: 0.937, size: 13, rate: 0.05 },
      { p: 0.99, size: 5, rate: 0.04 },
    ];
    for (const c of cases) {
      expect(close(feeUsdAtEntry(c.p, c.size, c.rate), PY_FEE_ENTRY(c.size, c.p, c.rate))).toBe(true);
    }
  });

  it("is rate x (1-p) of notional — the identity the preflight checks on the book", () => {
    // booked values are rounded to cents, so test the identity where a cent is small
    const size = 1000;
    const p = 0.25;
    const rate = 0.05;
    expect(feeUsdAtEntry(p, size, rate) / size).toBeCloseTo(rate * (1 - p), 5);
  });

  it("DOLLAR fee falls as the price rises, while the PER-SHARE fee peaks at 0.5", () => {
    // fee in dollars = (size/p) * rate * p * (1-p) = size * rate * (1-p) -> decreasing in p
    const cheap = feeUsdAtEntry(0.1, 10, 0.05);
    const mid = feeUsdAtEntry(0.5, 10, 0.05);
    const rich = feeUsdAtEntry(0.9, 10, 0.05);
    expect(cheap).toBeGreaterThan(mid);
    expect(mid).toBeGreaterThan(rich);
    expect(cheap).toBeCloseTo(PY_FEE_ENTRY(10, 0.1, 0.05), 2);
    expect(feeUsdAtEntry(0.999, 10, 0.05)).toBeCloseTo(0, 2);
    // per share it is the other way round: the venue's fee peaks in the middle
    expect(takerFeePerShare(0.5, 0.05)).toBeGreaterThan(takerFeePerShare(0.1, 0.05));
    expect(takerFeePerShare(0.5, 0.05)).toBeGreaterThan(takerFeePerShare(0.9, 0.05));
  });

  it("returns 0 (never NaN) on a price outside (0,1) or a bad size", () => {
    expect(feeUsdAtEntry(0, 10, 0.05)).toBe(0);
    expect(feeUsdAtEntry(1, 10, 0.05)).toBe(0);
    expect(feeUsdAtEntry(Number.NaN, 10, 0.05)).toBe(0);
    expect(feeUsdAtEntry(0.5, 0, 0.05)).toBe(0);
  });
});

describe("fee law (exit)", () => {
  it("matches the Python instrument at the implied exit price", () => {
    // bought 10 @ 0.40, sold at 0.50 -> shares 25, exit fee 25 * 0.05 * 0.5 * 0.5
    expect(close(feeUsdAtExit(0.4, 10, 0.5, 0.05), PY_FEE_EXIT(10, 0.4, 0.5, 0.05))).toBe(true);
    expect(feeUsdAtExit(0.4, 10, 0.5, 0.05)).toBeCloseTo(0.31, 1);
  });

  it("derives the exit price from the booked PnL identity", () => {
    // pnl = shares * exit - size  =>  exit = p * (1 + pnl/size)
    expect(impliedExitPrice(0.4, 10, 2.5)).toBeCloseTo(0.5, 6);
    expect(impliedExitPrice(0.4, 10, -10)).toBeCloseTo(0, 6);
    expect(impliedExitPrice(0.9, 10, 100)).toBe(1); // clamped
    expect(impliedExitPrice(0, 10, 1)).toBe(0);
  });
});

describe("bookedFee — the basis that runs", () => {
  const leg = { entryPrice: 0.4, simulatedPositionSize: 10, realizedPnl: 2.5, marketId: "nfl-phi-chi-2026-09-29" };

  it("charges the exit fee ONLY on an early exit (a settlement is not a sale)", () => {
    const closed = bookedFee({ ...leg, status: "closed" }, { basis: "two" });
    const resolved = bookedFee({ ...leg, status: "resolved" }, { basis: "two" });
    const open = bookedFee({ ...leg, status: "open" }, { basis: "two" });
    expect(closed.exit).toBeGreaterThan(0);
    expect(resolved.exit).toBe(0);
    expect(open.exit).toBe(0);
    expect(closed.total).toBeCloseTo(closed.entry + closed.exit, 2);
  });

  it("entry basis never charges an exit fee, whatever the status", () => {
    for (const status of ["open", "closed", "resolved"]) {
      expect(bookedFee({ ...leg, status }, { basis: "entry" }).exit).toBe(0);
    }
  });

  it("prefers the venue's published rate when the slug was captured", () => {
    const v = new Map([["nfl-phi-chi-2026-09-29", 0.03]]);
    const f = bookedFee({ ...leg, status: "resolved" }, { basis: "entry", venueRates: v });
    expect(f.rate).toBe(0.03);
    expect(f.rateSource).toBe("venue");
    expect(f.entry).toBeCloseTo(PY_FEE_ENTRY(10, 0.4, 0.03), 2);
  });

  it("falls back to the keyword proxy and stamps which basis it used", () => {
    expect(resolveFeeRate("will-bitcoin-hit-200k").rate).toBe(0.07);
    expect(resolveFeeRate("us-senate-election-winner").rate).toBe(0.04);
    expect(resolveFeeRate("nba-lal-bos").rate).toBe(0.05);
    expect(resolveFeeRate(null).source).toBe("proxy");
  });
});

describe("netPnl and the read flag", () => {
  it("subtracts both fee columns and treats NULL as zero", () => {
    expect(netPnl({ entryPrice: 0.5, simulatedPositionSize: 10, realizedPnl: 3, feeUsd: 0.5, feeExitUsd: 0.25 })).toBe(2.25);
    expect(netPnl({ entryPrice: 0.5, simulatedPositionSize: 10, realizedPnl: 3 })).toBe(3);
    expect(netPnl({ entryPrice: 0.5, simulatedPositionSize: 10, realizedPnl: null })).toBe(0);
  });

  it("FEE_NET_LEDGER defaults OFF — the published numbers must not move on deploy", () => {
    const prev = process.env.FEE_NET_LEDGER;
    delete process.env.FEE_NET_LEDGER;
    expect(feeNetLedgerEnabled()).toBe(false);
    process.env.FEE_NET_LEDGER = "0";
    expect(feeNetLedgerEnabled()).toBe(false);
    process.env.FEE_NET_LEDGER = "1";
    expect(feeNetLedgerEnabled()).toBe(true);
    if (prev === undefined) delete process.env.FEE_NET_LEDGER;
    else process.env.FEE_NET_LEDGER = prev;
  });
});
