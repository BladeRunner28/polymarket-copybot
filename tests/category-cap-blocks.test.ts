import { describe, expect, it } from "vitest";
import {
  categorySeatDecision,
  classifyCategoryBlock,
  describeCategoryBlock,
  formatCategoryCapBlock,
  isCategoryCapBlock,
  maxConcurrentLegs,
  maxConcurrentLegsAt,
  openLegsAt,
  parseCategoryCapBlocks,
  positionBasisViolation,
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

  it("reads the post-repair attempts form and keeps the stated true open count", () => {
    const b = parseCategoryCapBlocks(
      '["category concentration (Crypto would be 41/40 on an attempts basis; true open 0)"]'
    );
    expect(b).toEqual([
      { category: "Crypto", wouldBe: 41, cap: 40, basis: "attempts-labelled", trueOpen: 0 },
    ]);
  });

  it("reads the open-position form written after the 2026-11-12 seat fix", () => {
    const b = parseCategoryCapBlocks(
      '["category concentration (Macro/Politics open 40/40 on an open-position basis)"]'
    );
    expect(b).toEqual([
      { category: "Macro/Politics", wouldBe: 41, cap: 40, basis: "positions", trueOpen: 40 },
    ]);
  });

  it("does not let one form absorb the other on a row carrying both", () => {
    const b = parseCategoryCapBlocks(
      '["category concentration (Crypto would be 41/40)","category concentration (Crypto open 40/40 on an open-position basis)"]'
    );
    expect(b.map((x) => x.basis)).toEqual(["attempts", "positions"]);
  });

  it("round-trips the form it writes today, including multi-word-slash categories", () => {
    for (const cat of ["Macro/Politics", "Tech/AI", "Energy/Climate", "Defense/Geopolitics"]) {
      for (const open of [0, 17, 40]) {
        const line = formatCategoryCapBlock(cat, open, 40);
        const [parsed] = parseCategoryCapBlocks(`["${line}"]`);
        expect(parsed.category).toBe(cat);
        expect(parsed.basis).toBe("positions");
        expect(parsed.trueOpen).toBe(open);
        expect(parsed.cap).toBe(40);
        // wouldBe is derived so every form answers `wouldBe > cap` the same way
        expect(parsed.wouldBe).toBe(open + 1);
      }
    }
  });

  it("still parses the two historical forms written before it (no back-compat loss)", () => {
    const legacy = parseCategoryCapBlocks(
      '["category concentration (Defense/Geopolitics would be 41/40)"]'
    );
    expect(legacy[0].basis).toBe("attempts");
    const labelled = parseCategoryCapBlocks(
      '["category concentration (Crypto would be 41/40 on an attempts basis; true open 0)"]'
    );
    expect(labelled[0].basis).toBe("attempts-labelled");
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

  it("describes a post-fix refusal as the open-position basis it now is", () => {
    expect(
      describeCategoryBlock({
        category: "Crypto",
        wouldBe: 41,
        cap: 40,
        basis: "positions",
        trueOpen: 40,
      })
    ).toBe("category Crypto seats 41/40 (open-position basis)");
  });
});

describe("positionBasisViolation (the card's own refutation condition)", () => {
  const post = { category: "Crypto", wouldBe: 41, cap: 40, basis: "positions" as const };

  it("accepts a post-fix refusal that states the cap in open legs", () => {
    expect(positionBasisViolation({ ...post, trueOpen: 40 })).toBe(false);
    // above the cap is a genuine over-count, also not this refutation
    expect(positionBasisViolation({ ...post, trueOpen: 44 })).toBe(false);
  });

  it("fires when a post-fix refusal still states fewer open legs than the cap", () => {
    // i.e. the counter went back to consuming seats on candidates a later gate refused
    expect(positionBasisViolation({ ...post, trueOpen: 39 })).toBe(true);
    expect(positionBasisViolation({ ...post, trueOpen: 0 })).toBe(true);
    expect(positionBasisViolation({ ...post, trueOpen: undefined })).toBe(true);
  });

  it("never judges rows written on the older bases — those are honest history", () => {
    expect(
      positionBasisViolation({ category: "Crypto", wouldBe: 41, cap: 40, basis: "attempts" })
    ).toBe(false);
    expect(
      positionBasisViolation({
        category: "Crypto",
        wouldBe: 41,
        cap: 40,
        basis: "attempts-labelled",
        trueOpen: 0,
      })
    ).toBe(false);
  });
});

describe("categorySeatDecision (the seat is only consumed by a BOOKED leg)", () => {
  it("never blocks a candidate that merely PASSED the gate and died downstream", () => {
    // The 2026-09-17 burst: 41 candidates in one run each passed v41 and were then
    // refused by a later gate. On the old counter the 41st read "would be 41/40"
    // with ZERO legs open in the category; that is the defect this pins shut.
    const counter = new Map<string, number>();
    for (let i = 0; i < 41; i++) {
      const seat = categorySeatDecision(counter.get("Defense/Geopolitics") ?? 0, 40);
      expect(seat.blocked).toBe(false);
      // refused downstream -> nothing booked -> no seat consumed
    }
    expect(counter.size).toBe(0);

    // NEGATIVE CONTROL: the same loop under the OLD mutation (seat consumed when the
    // candidate PASSES the gate) produces exactly one phantom refusal — so this test
    // can go red, it is not asserting a tautology.
    let legacySeats = 0;
    let legacyBlocked = 0;
    for (let i = 0; i < 41; i++) {
      const seat = categorySeatDecision(legacySeats, 40);
      if (seat.blocked) legacyBlocked += 1;
      else legacySeats += 1; // old behaviour: consume the seat on pass
    }
    expect(legacyBlocked).toBe(1);
  });

  it("still binds once 40 legs have actually booked in the same run", () => {
    const counter = new Map<string, number>();
    for (let i = 0; i < 40; i++) {
      const seat = categorySeatDecision(counter.get("Crypto") ?? 0, 40);
      expect(seat.blocked).toBe(false);
      counter.set("Crypto", (counter.get("Crypto") ?? 0) + 1); // the leg booked
    }
    expect(categorySeatDecision(counter.get("Crypto") ?? 0, 40)).toEqual({
      blocked: true,
      wouldBe: 41,
      openPositions: 40,
    });
  });

  it("counts the run-start seed, so a category already at the cap refuses immediately", () => {
    expect(categorySeatDecision(40, 40).blocked).toBe(true);
    expect(categorySeatDecision(39, 40).blocked).toBe(false);
  });

  it("treats a cap of 0 as disabled", () => {
    expect(categorySeatDecision(1_000, 0).blocked).toBe(false);
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
