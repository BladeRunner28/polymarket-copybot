/**
 * Settlement basis for the Kalshi venue-shadow ledger. Each arm here is a way the exit-sign
 * basis was read as a settlement basis (card kalshi-venue-shadow-pnl-exit-sign-basis).
 */

import { describe, it, expect } from "vitest";
import {
  normaliseKalshiResult, venueSideWon, venueGross, compareBases, summariseBasis,
  venueWonFromPair, pairKey,
} from "../src/lib/kalshi-venue-settlement";

describe("normaliseKalshiResult", () => {
  it("accepts the venue's two final values regardless of case/whitespace", () => {
    expect(normaliseKalshiResult("yes")).toBe("yes");
    expect(normaliseKalshiResult(" NO ")).toBe("no");
  });
  it("returns null for unfinalized (''), void, numeric and non-string inputs — never a guess", () => {
    expect(normaliseKalshiResult("")).toBeNull();
    expect(normaliseKalshiResult(undefined)).toBeNull();
    expect(normaliseKalshiResult(null)).toBeNull();
    expect(normaliseKalshiResult(1)).toBeNull();
    expect(normaliseKalshiResult("void")).toBeNull();
    expect(normaliseKalshiResult("true")).toBeNull();
  });
});

describe("venueSideWon", () => {
  it("YES contract on a yes result wins; NO contract on the same result loses", () => {
    expect(venueSideWon("yes", true)).toBe(true);
    expect(venueSideWon("yes", false)).toBe(false);
    expect(venueSideWon("no", false)).toBe(true);
    expect(venueSideWon("no", true)).toBe(false);
  });
  it("is null when either input is unknown — the one case that must not be coerced", () => {
    expect(venueSideWon(null, true)).toBeNull();
    expect(venueSideWon("yes", null)).toBeNull();
    expect(venueSideWon("no", undefined)).toBeNull();
  });
});

describe("venueGross", () => {
  it("pays $1 per contract at settlement: size*(1/entry-1) on a win, -size on a loss", () => {
    expect(venueGross(10, 0.5, true)).toBeCloseTo(10, 10);
    expect(venueGross(10, 0.25, true)).toBeCloseTo(30, 10);
    expect(venueGross(10, 0.5, false)).toBeCloseTo(-10, 10);
  });
  it("refuses an unpriceable entry instead of returning a number", () => {
    expect(venueGross(10, 0, true)).toBeNull();
    expect(venueGross(10, Number.NaN, false)).toBeNull();
    expect(venueGross(Number.POSITIVE_INFINITY, 0.5, true)).toBeNull();
  });
});

describe("compareBases", () => {
  it("names the flip in the direction it happened", () => {
    expect(compareBases(true, true)).toBe("agree");
    expect(compareBases(false, false)).toBe("agree");
    expect(compareBases(false, true)).toBe("exit_loss_venue_win");
    expect(compareBases(true, false)).toBe("exit_win_venue_loss");
  });
  it("does not call an unknown a disagreement", () => {
    expect(compareBases(false, null)).toBe("venue_unknown");
    expect(compareBases(null, true)).toBe("exit_unknown");
  });
  it("an early exit that settled a win reads as a flip, not as agreement", () => {
    // the measured instance: realizedPnl <= 0 on a contract the venue settled in our favour
    expect(compareBases(false, true)).not.toBe("agree");
  });
});

describe("summariseBasis", () => {
  it("every leg lands in exactly one bucket", () => {
    const s = summariseBasis([
      { exitWon: true, venueWon: true },
      { exitWon: false, venueWon: true },
      { exitWon: false, venueWon: false },
      { exitWon: true, venueWon: false },
      { exitWon: false, venueWon: null },
      { exitWon: null, venueWon: true },
    ]);
    expect(s.population).toBe(6);
    expect(s.known).toBe(4);
    expect(s.agree + s.exitLossVenueWin + s.exitWinVenueLoss + s.venueUnknown + s.exitUnknown)
      .toBe(s.population);
    expect(s.known).toBe(s.agree + s.disagree);
  });
  it("counts wins per basis separately — the whole point of the second column", () => {
    const s = summariseBasis([
      { exitWon: false, venueWon: true },
      { exitWon: false, venueWon: true },
      { exitWon: false, venueWon: false },
    ]);
    expect(s.exitWins).toBe(0);
    expect(s.venueWins).toBe(2);
    expect(s.exitLossVenueWin).toBe(2);
    expect(s.disagree).toBe(2);
  });
  it("empty population is zero everywhere, not NaN", () => {
    const s = summariseBasis([]);
    expect(Object.values(s).every((v) => v === 0)).toBe(true);
  });
});

describe("venueWonFromPair", () => {
  it("reads the adjudicated Kalshi side when both result and side are known", () => {
    expect(venueWonFromPair({ sideYes: true, kalshiResult: "yes" })).toEqual({ won: true, source: "kalshi_side" });
    expect(venueWonFromPair({ sideYes: true, kalshiResult: "no" })).toEqual({ won: false, source: "kalshi_side" });
    expect(venueWonFromPair({ sideYes: false, kalshiResult: "no" })).toEqual({ won: true, source: "kalshi_side" });
  });
  it("falls back to PM's token winner only when the Kalshi side is not final", () => {
    expect(venueWonFromPair({ sideYes: null, kalshiResult: null, pmWinner: false }))
      .toEqual({ won: false, source: "pm_token" });
  });
  it("prefers the Kalshi read over the PM read when both exist — the lane is a venue comparison", () => {
    expect(venueWonFromPair({ sideYes: true, kalshiResult: "no", pmWinner: true }).source).toBe("kalshi_side");
  });
  it("never invents a verdict: no pair, no side, no result -> null", () => {
    expect(venueWonFromPair(null)).toEqual({ won: null, source: null });
    expect(venueWonFromPair({ sideYes: null, kalshiResult: "yes" })).toEqual({ won: null, source: null });
    expect(venueWonFromPair({ sideYes: true, kalshiResult: null })).toEqual({ won: null, source: null });
  });
  it("pairKey joins on the ledger's own identity fields", () => {
    expect(pairKey("m1", " Nets ", "KX-1")).toBe("m1|Nets|KX-1");
    expect(pairKey("m1", "NETS", "KX-1")).not.toBe(pairKey("m1", "Nets", "KX-1"));
  });
});
