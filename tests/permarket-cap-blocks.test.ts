import { describe, expect, it } from "vitest";
import {
  classifyBlock,
  describeBlock,
  isPerMarketCapBlock,
  parsePerMarketCapBlocks,
} from "../src/lib/permarket-cap-blocks";

describe("parsePerMarketCapBlocks", () => {
  it("reads the legs clause exactly as score-trades writes it", () => {
    const b = parsePerMarketCapBlocks('["BANKROLL_200: v55 per-market cap (legs 3 > max 2)"]');
    expect(b).toEqual([{ clause: "legs", wouldBeLegs: 3, maxLegs: 2 }]);
  });

  it("reads the notional clause including decimals", () => {
    const b = parsePerMarketCapBlocks(
      '["BANKROLL_200: v55 per-market cap (notional $185.53 > cap $125.12)"]'
    );
    expect(b).toEqual([{ clause: "notional", projectedNotional: 185.53, notionalCap: 125.12 }]);
  });

  it("reads both clauses when one row carries two refusals", () => {
    const b = parsePerMarketCapBlocks(
      '["BANKROLL_200: v55 per-market cap (legs 3 > max 2)","BANKROLL_200: v55 per-market cap (notional $200.00 > cap $125.12)"]'
    );
    expect(b.map((x) => x.clause)).toEqual(["legs", "notional"]);
  });

  it("is anchored to the written string, not prose about the rail", () => {
    expect(parsePerMarketCapBlocks("v55 per-market cap counted 16 legs across 10 markets")).toEqual([]);
    expect(isPerMarketCapBlock('["BANKROLL_200: v45 market-slug cap (highest would be 16/15)"]')).toBe(false);
    expect(isPerMarketCapBlock(null)).toBe(false);
    expect(isPerMarketCapBlock(undefined)).toBe(false);
  });

  it("survives a repeated parse (no lastIndex leak between rows)", () => {
    const s = '["BANKROLL_200: v55 per-market cap (legs 3 > max 2)"]';
    expect(parsePerMarketCapBlocks(s)).toHaveLength(1);
    expect(parsePerMarketCapBlocks(s)).toHaveLength(1);
  });
});

describe("classifyBlock — genuine seat vs phantom seat", () => {
  const legs = { wouldBeLegs: 3, maxLegs: 2, clause: "legs" as const };

  it("calls a refusal genuine when the market really held max legs", () => {
    expect(classifyBlock(legs, { legs: 2, notional: 200 }, 20)).toBe("genuine");
    expect(classifyBlock(legs, { legs: 3, notional: 300 }, 20)).toBe("genuine");
  });

  it("calls a refusal phantom when the market held fewer legs than claimed", () => {
    expect(classifyBlock(legs, { legs: 1, notional: 100 }, 20)).toBe("phantom");
    expect(classifyBlock(legs, { legs: 0, notional: 0 }, 20)).toBe("phantom");
  });

  it("never guesses: unknown when the state is unreconstructable", () => {
    expect(classifyBlock(legs, null, 20)).toBe("unknown");
    expect(classifyBlock({ ...legs, maxLegs: 0 }, { legs: 5, notional: 0 }, 20)).toBe("unknown");
  });

  const notional = {
    clause: "notional" as const,
    projectedNotional: 200,
    notionalCap: 125.12,
  };

  it("classifies the notional clause on the true open notional when size is known", () => {
    expect(classifyBlock(notional, { legs: 1, notional: 100 }, 100)).toBe("genuine");
    expect(classifyBlock(notional, { legs: 1, notional: 10 }, 20)).toBe("phantom");
  });

  it("still answers genuine when the market alone exceeded the ceiling", () => {
    expect(classifyBlock(notional, { legs: 2, notional: 200 }, null)).toBe("genuine");
  });

  it("leaves the ambiguous middle unknown rather than folding it into an arm", () => {
    expect(classifyBlock(notional, { legs: 1, notional: 100 }, null)).toBe("unknown");
    expect(classifyBlock(notional, null, 100)).toBe("unknown");
  });
});

describe("describeBlock", () => {
  it("round-trips both clauses without drifting from the written form", () => {
    expect(describeBlock({ clause: "legs", wouldBeLegs: 3, maxLegs: 2 })).toBe("legs 3 > max 2");
    expect(
      describeBlock({ clause: "notional", projectedNotional: 200, notionalCap: 125.12 })
    ).toBe("notional $200.00 > cap $125.12");
  });
});
