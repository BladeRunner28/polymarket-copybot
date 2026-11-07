import { describe, expect, it } from "vitest";
import {
  classifyCategoryBlock,
  describeCategoryBlock,
  formatCategoryCapBlock,
  isCategoryCapBlock,
  maxConcurrentLegs,
  maxConcurrentLegsAt,
  openLegsAt,
  parseCategoryCapBlocks,
} from "../src/lib/category-cap-blocks";

describe("parseCategoryCapBlocks", () => {
  it("reads the historical form exactly as score-trades wrote it before 2026-11-06", () => {
    const b = parseCategoryCapBlocks(
      '["drawdown gate [mtm] (net worth $2548 vs peak $3409 = 25.3% > 20%)","category concentration (Defense/Geopolitics would be 41/40)"]'
    );
    expect(b).toEqual([
      { category: "Defense/Geopolitics", wouldBe: 41, cap: 40, basis: "attempts" },
    ]);
  });

  it("reads the post-repair form and keeps the stated true open count", () => {
    const b = parseCategoryCapBlocks(
      '["category concentration (Crypto would be 41/40 on an attempts basis; true open 0)"]'
    );
    expect(b).toEqual([
      { category: "Crypto", wouldBe: 41, cap: 40, basis: "attempts-labelled", trueOpen: 0 },
    ]);
  });

  it("round-trips every form it can write, including multi-word-slash categories", () => {
    for (const cat of ["Macro/Politics", "Tech/AI", "Energy/Climate", "Defense/Geopolitics"]) {
      for (const open of [null, 0, 17]) {
        const line = formatCategoryCapBlock(cat, 41, 40, open);
        const [parsed] = parseCategoryCapBlocks(`["${line}"]`);
        expect(parsed.category).toBe(cat);
        expect(parsed.wouldBe).toBe(41);
        expect(parsed.cap).toBe(40);
        expect(parsed.trueOpen).toBe(open === null ? undefined : open);
      }
    }
  });

  it("is anchored to the written string, not prose about the rail", () => {
    expect(parseCategoryCapBlocks("category concentration counted 41 legs across 10 markets")).toEqual(
      []
    );
    expect(
      parseCategoryCapBlocks('["BANKROLL_200: v45 market-slug cap (highest would be 16/15)"]')
    ).toEqual([]);
    expect(isCategoryCapBlock('["category concentration (Crypto would be 41/40)"]')).toBe(true);
    expect(isCategoryCapBlock(null)).toBe(false);
    expect(isCategoryCapBlock(undefined)).toBe(false);
  });

  it("survives a repeated parse (no lastIndex leak between rows)", () => {
    const s = '["category concentration (Crypto would be 41/40)"]';
    expect(parseCategoryCapBlocks(s)).toHaveLength(1);
    expect(parseCategoryCapBlocks(s)).toHaveLength(1);
  });
});

describe("classifyCategoryBlock", () => {
  const block = { category: "Crypto", wouldBe: 41, cap: 40, basis: "attempts" as const };

  it("calls a refusal genuine only when the category really held the cap", () => {
    expect(classifyCategoryBlock(block, 40)).toBe("genuine");
    expect(classifyCategoryBlock(block, 41)).toBe("genuine");
  });

  it("calls a refusal phantom when the true open book was below the cap", () => {
    expect(classifyCategoryBlock(block, 39)).toBe("phantom");
    expect(classifyCategoryBlock(block, 0)).toBe("phantom");
  });

  it("refuses to classify when the ground truth is missing or the cap is disabled", () => {
    expect(classifyCategoryBlock(block, null)).toBe("unknown");
    expect(classifyCategoryBlock({ ...block, cap: 0 }, 0)).toBe("unknown");
  });

  it("describes the cause as an attempt basis, never as open positions", () => {
    expect(describeCategoryBlock(block)).toBe("category Crypto seats 41/40 (attempt basis)");
  });
});

describe("openLegsAt / maxConcurrentLegs", () => {
  const ivs = [
    { open: 100, end: 200 },
    { open: 150, end: null },
    { open: 300, end: 400 },
  ];

  it("counts an interval from its open instant and drops it at its close instant", () => {
    expect(openLegsAt(ivs, 99)).toBe(0);
    expect(openLegsAt(ivs, 100)).toBe(1);
    expect(openLegsAt(ivs, 150)).toBe(2);
    expect(openLegsAt(ivs, 200)).toBe(1);
    expect(openLegsAt(ivs, 10_000)).toBe(1);
  });

  it("finds the peak and the clock it happened at", () => {
    expect(maxConcurrentLegs(ivs)).toBe(2);
    const peak = maxConcurrentLegsAt(ivs);
    expect(peak.legs).toBe(2);
    expect(peak.at).toBe(150);
  });

  it("returns zero and no clock for an empty book", () => {
    expect(maxConcurrentLegs([])).toBe(0);
    expect(maxConcurrentLegsAt([])).toEqual({ legs: 0, at: null });
  });
});
