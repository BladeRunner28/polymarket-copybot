import { describe, it, expect } from "vitest";
import { NON_TRADE_TYPES, TRADE_TYPES, filterTradeRows, isKnownRowType, isTradeRow } from "../src/lib/print-types";

/**
 * Print-type classification (audit §P6, ported from polyterm
 * core/print_scanner.py:16-33).
 *
 * The load-bearing decision: an UNRECOGNISED non-empty type is NOT a fill. A row
 * we cannot classify must not become a trade — that is how a redemption gets
 * booked as a buy. The empty type IS a fill, because the tape omits `type` on
 * ordinary trade rows.
 */
describe("isTradeRow", () => {
  it("accepts ordinary fill types and the absent-type case", () => {
    for (const t of ["", "trade", "trade_matched", "buy", "sell", "BUY", "Trade"]) {
      expect(isTradeRow({ type: t })).toBe(true);
    }
    expect(isTradeRow({})).toBe(true);
  });

  it("rejects every position-management type", () => {
    for (const t of [...NON_TRADE_TYPES]) {
      expect(isTradeRow({ type: t })).toBe(false);
      expect(isTradeRow({ type: t.toUpperCase() })).toBe(false);
    }
    expect([...NON_TRADE_TYPES]).toEqual([
      "split",
      "merge",
      "redeem",
      "reward",
      "conversion",
      "liquidity",
      "deposit",
      "withdrawal",
      // observed on our own tape by audit:print-types --unfiltered, 2026-09-28
      "maker_rebate",
      "taker_rebate",
      "yield",
    ]);
  });

  it("rejects unknown non-empty types rather than guessing they are fills", () => {
    expect(isTradeRow({ type: "something_new" })).toBe(false);
    expect(isTradeRow({ type: "transfer" })).toBe(false);
  });

  it("never throws on malformed rows", () => {
    expect(isTradeRow(null)).toBe(true); // type absent -> treated as a fill row
    expect(isTradeRow(undefined)).toBe(true);
    expect(isTradeRow("nonsense")).toBe(true);
    expect(isTradeRow({ type: null })).toBe(true);
    expect(isTradeRow({ type: 7 })).toBe(false); // "7" is an unknown type
  });

  it("exposes the whitelist it uses", () => {
    expect(TRADE_TYPES.has("buy")).toBe(true);
    expect(TRADE_TYPES.has("split")).toBe(false);
  });
});

/**
 * `isKnownRowType` exists for the measurement, not the ingest: the classifier's
 * default drops anything it does not recognise, so a brand-new tape type would
 * shrink ingest silently. This is what surfaces it.
 */
describe("isKnownRowType", () => {
  it("accepts every catalogued type, in either case", () => {
    for (const t of [...NON_TRADE_TYPES, ...TRADE_TYPES]) {
      expect(isKnownRowType(t)).toBe(true);
      expect(isKnownRowType(t.toUpperCase())).toBe(true);
    }
    expect(isKnownRowType(undefined)).toBe(true); // absent type == fill row
  });

  it("flags a type we have never catalogued", () => {
    expect(isKnownRowType("REDEEM")).toBe(true); // lowercased before lookup
    expect(isKnownRowType("something_new")).toBe(false);
    expect(isKnownRowType("transfer")).toBe(false);
  });
});

describe("filterTradeRows", () => {
  it("splits fills from non-fills and counts per dropped type", () => {
    const rows = [
      { type: "trade", id: 1 },
      { type: "redeem", id: 2 },
      { type: "redeem", id: 3 },
      { type: "split", id: 4 },
      { id: 5 },
    ];
    const r = filterTradeRows(rows);
    expect(r.kept.map((x) => x.id)).toEqual([1, 5]);
    expect(r.skipped).toBe(3);
    expect(r.skippedByType).toEqual({ redeem: 2, split: 1 });
    expect(r.qualityFlags).toContain("skipped_non_trade_rows");
    expect(r.qualityFlags).toContain("public_trade_rows_only");
  });

  it("counts unclassified drops under a distinguishable key", () => {
    const r = filterTradeRows([{ type: "mystery" }]);
    expect(r.skippedByType).toEqual({ mystery: 1 });
  });

  it("flags an empty page so 'nothing skipped' cannot read as 'tape was fine'", () => {
    const r = filterTradeRows([]);
    expect(r.kept).toHaveLength(0);
    expect(r.skipped).toBe(0);
    expect(r.qualityFlags).toContain("empty_data_api_page");
    expect(r.qualityFlags).not.toContain("skipped_non_trade_rows");
  });

  it("does not invent or reorder rows", () => {
    const rows = [{ type: "buy", n: "a" }, { type: "sell", n: "b" }];
    expect(filterTradeRows(rows).kept).toEqual(rows);
  });
});
