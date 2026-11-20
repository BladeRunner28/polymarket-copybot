/**
 * Fee-schedule capture at export scale (card paper-ledger-fee-fidelity, 2026-11-20).
 *
 * The arms that matter are the ones that would have produced a WRONG population:
 * a position-based column read, a closed market's settlement mark read as a
 * trade price, and the `?slug=` query form that returns `[]` for every closed
 * market (the trap the first version of the capture fell into).
 */

import { describe, it, expect } from "vitest";
import {
  capturedSlugs,
  feePerShare,
  parseExportSlugs,
  pickMarketRow,
  resolveVenueFee,
  slugMarketUrl,
} from "../src/lib/fee-capture";

describe("parseExportSlugs", () => {
  it("locates market_id by NAME and preserves first-seen order", () => {
    const csv = "review_id,market_id,bot_id\nr1,b-market,a\nr2,a-market,b\nr3,b-market,c\n";
    expect(parseExportSlugs(csv)).toEqual(["b-market", "a-market"]);
  });

  it("is not fooled by an inserted column before market_id", () => {
    const csv = "extra,market_id\nx,s1\n";
    expect(parseExportSlugs(csv)).toEqual(["s1"]);
  });

  it("throws rather than guessing a position when the column is absent", () => {
    expect(() => parseExportSlugs("review_id,market\nr1,slug")).toThrow(/market_id/);
  });

  it("drops blank ids and the header", () => {
    expect(parseExportSlugs("market_id\n,\nm1\n   \n")).toEqual(["m1"]);
  });
});

describe("resolveVenueFee", () => {
  it("prefers feeSchedule.rate over the static takerBaseFee", () => {
    const f = resolveVenueFee({
      feeType: "sports_fees_v2",
      feeSchedule: { rate: 0.03, exponent: 1, rebateRate: 0.15 },
      takerBaseFee: 1000,
    });
    expect(f).toMatchObject({ rate: 0.03, exponent: 1, rebate: 0.15, source: "market" });
  });

  it("reads a JSON-string feeSchedule (the venue returns both shapes)", () => {
    expect(resolveVenueFee({ feeSchedule: '{"rate":0.07,"rebateRate":0.2}' })).toMatchObject({ rate: 0.07, rebate: 0.2 });
  });

  it("treats feesEnabled=false as a real zero, not a missing value", () => {
    expect(resolveVenueFee({ feesEnabled: false, feeSchedule: { rate: 0.05 } })).toMatchObject({ rate: 0, source: "market" });
  });

  it("falls back to takerBaseFee only when no schedule exists, and keeps it identifiable", () => {
    expect(resolveVenueFee({ takerBaseFee: 400 })).toMatchObject({ rate: 0.04, source: "market" });
  });

  it("reports source 'none' instead of inventing a rate", () => {
    expect(resolveVenueFee({ feeType: "politics_fees" })).toEqual({ feeType: "politics_fees", feesEnabled: undefined, source: "none" });
  });
});

describe("slugMarketUrl", () => {
  it("uses the slug PATH, not the ?slug= query (which hides closed markets)", () => {
    const url = slugMarketUrl("https://gamma-api.polymarket.com", "nba-gsw-mem-2026-11-19");
    expect(url).toBe("https://gamma-api.polymarket.com/markets/slug/nba-gsw-mem-2026-11-19");
    expect(url).not.toContain("?slug=");
  });

  it("percent-encodes so a stray character cannot match another market", () => {
    expect(slugMarketUrl("http://x", "a b/c")).toBe("http://x/markets/slug/a%20b%2Fc");
  });
});

describe("capturedSlugs", () => {
  it("counts a slug as captured only when a finite resolvedRate is stored", () => {
    const jsonl = [
      '{"slug":"a","resolvedRate":0.03}',
      '{"slug":"b"}',
      '{"slug":"c","resolvedRate":null}',
      'not json',
      '{"slug":"d","resolvedRate":0}',
    ].join("\n");
    expect([...capturedSlugs(jsonl)].sort()).toEqual(["a", "d"]);
  });
});

describe("pickMarketRow", () => {
  it("accepts both the single-object and list response shapes", () => {
    expect(pickMarketRow({ slug: "a" })).toEqual({ slug: "a" });
    expect(pickMarketRow([{ slug: "b" }])).toEqual({ slug: "b" });
    expect(pickMarketRow([])).toBeUndefined();
    expect(pickMarketRow(null)).toBeUndefined();
  });
});

describe("feePerShare", () => {
  it("matches the venue curve rate*p*(1-p)", () => {
    expect(feePerShare(0.5, 0.05)).toBeCloseTo(0.0125, 10);
    expect(feePerShare(0.9, 0.03)).toBeCloseTo(0.0027, 10);
    expect(feePerShare(0.5, 0)).toBe(0);
  });
});
