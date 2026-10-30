/**
 * slug-cap-blocks — the v45 per-slug cap, read out of the journal.
 *
 * The strings below are the ones scripts/score-trades.ts actually writes
 * (`BANKROLL_200: v45 market-slug cap (mex would be 16/15)`), captured from
 * prisma/dev.db at 2026-10-30; the parser is anchored on that exact shape so a
 * card note that merely TALKS about the cap cannot be miscounted as a refusal.
 */

import { describe, it, expect } from "vitest";
import { parseSlugCapBlocks, isSlugCapBlock, perDollarReturn, summarizeReturns } from "../src/lib/slug-cap-blocks";

describe("parseSlugCapBlocks", () => {
  it("parses the live journal string", () => {
    expect(parseSlugCapBlocks('["BANKROLL_200: v45 market-slug cap (mex would be 16/15)"]')).toEqual([
      { token: "mex", wouldBe: 16, cap: 15 },
    ]);
  });

  it("returns nothing for a row with no cap block", () => {
    expect(parseSlugCapBlocks('["BANKROLL_200: kelly no-edge (no edge: q=0.846 ≤ price=0.905)"]')).toEqual([]);
    expect(parseSlugCapBlocks(null)).toEqual([]);
    expect(parseSlugCapBlocks("")).toEqual([]);
  });

  it("does not fire on prose about the cap (card notes, report headers)", () => {
    const prose = "the v45 15-per-slug cap counts TOKENS and token 'highest' spans 14,879 marketIds";
    expect(parseSlugCapBlocks(prose)).toEqual([]);
    expect(isSlugCapBlock(prose)).toBe(false);
  });

  it("parses every block on one row", () => {
    const rj =
      '["BANKROLL_200: v45 market-slug cap (dota2 would be 16/15)","BANKROLL_200: v45 market-slug cap (cfb would be 17/15)"]';
    expect(parseSlugCapBlocks(rj)).toEqual([
      { token: "dota2", wouldBe: 16, cap: 15 },
      { token: "cfb", wouldBe: 17, cap: 15 },
    ]);
  });

  it("is stable when called twice (no lastIndex leak on the shared regex)", () => {
    const rj = '["BANKROLL_200: v45 market-slug cap (fl1 would be 16/15)"]';
    expect(parseSlugCapBlocks(rj)).toEqual(parseSlugCapBlocks(rj));
  });
});

describe("perDollarReturn", () => {
  it("pays (1-p)/p on a win and -1 on a loss", () => {
    expect(perDollarReturn(0.5, true)).toBeCloseTo(1.0, 10);
    expect(perDollarReturn(0.5, false)).toBe(-1);
    expect(perDollarReturn(0.95, true)).toBeCloseTo(0.0526, 4);
    expect(perDollarReturn(1.0, false)).toBe(-1);
  });

  it("refuses an entry price that cannot describe a stake", () => {
    expect(perDollarReturn(0, true)).toBeNull();
    expect(perDollarReturn(-0.1, true)).toBeNull();
    expect(perDollarReturn(1.2, true)).toBeNull();
    expect(perDollarReturn(Number.NaN, true)).toBeNull();
    expect(perDollarReturn(null, true)).toBeNull();
  });
});

describe("summarizeReturns", () => {
  it("reports median and a trimmed mean that one leg cannot move", () => {
    // 18 legs at +0.10 and one leg at +40: the mean is dragged, the median is not,
    // and the trim removes the outlier from both tails.
    const rs = [...Array(18).fill(0.1), 40];
    const s = summarizeReturns(rs, 0.05);
    expect(s.n).toBe(19);
    expect(s.median).toBeCloseTo(0.1, 10);
    expect(s.mean).toBeGreaterThan(2);
    // 5% of 19 floors to zero, so the 5% trim removes NOTHING here — a property
    // worth pinning, because it means the trimmed mean only diverges from the mean
    // at n >= 20 and a small sample must be read off the median instead.
    expect(s.trimmedMean).toBeCloseTo(s.mean, 10);
    expect(summarizeReturns(rs, 0.1).trimmedMean).toBeCloseTo(0.1, 10);
  });

  it("ex-top-10 removes the ten largest winners, leaving the rest honest", () => {
    const rs = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, -0.2, -0.2];
    const s = summarizeReturns(rs);
    expect(s.sum).toBeCloseTo(9.6, 10);
    expect(s.exTop10Sum).toBeCloseTo(-0.4, 10);
  });

  it("is empty-safe", () => {
    const s = summarizeReturns([]);
    expect(s).toEqual({ n: 0, sum: 0, mean: 0, median: 0, trimmedMean: 0, winRate: 0, worstLeg: 0, exTop10Sum: 0 });
  });

  it("prices the measured 30d refusal population the way the artifact reports it", () => {
    // FROZEN EVIDENCE: the 105 refused C-200 decisions of 2026-09-30..2026-10-30,
    // per-token per-$1 sums as written to data/slug-cap-blocked-legs.json
    // (0 undetermined — all 105 priced to the market's own winning label).
    // Reconstructing the per-leg returns is not possible from the sums, so this
    // test pins the direction of each bucket: epl/nhl refused only losers,
    // fl1/mex refused only winners.
    const losers = summarizeReturns([-1, -1, -1, -1, -1, -1]);
    expect(losers.winRate).toBe(0);
    expect(losers.sum).toBe(-6);
    const winners = summarizeReturns([1.02, 1.02, 1.02, 1.02, 1.02, 1.02, 1.02, 1.02, 1.02]);
    expect(winners.winRate).toBe(1);
    expect(winners.sum).toBeCloseTo(9.18, 10);
  });
});
