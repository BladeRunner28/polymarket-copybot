import { describe, it, expect } from "vitest";
import {
  scoreWallet,
  oneHitWonderPenalty,
  consistencyScore,
  copyabilityScore,
  walletStatus,
  categoryBucketKey,
  encodeCategoryStrengths,
  decodeCategoryStrengths,
  categoryWinRateFor,
} from "../src/lib/scoring/wallet";
import { DEFAULT_RULES } from "../src/lib/rules";
import { WalletActivityTrade } from "../src/lib/types";

function trade(overrides: Partial<WalletActivityTrade> = {}): WalletActivityTrade {
  return {
    marketId: "m1",
    marketQuestion: "Test market?",
    marketCategory: "politics",
    outcome: "YES",
    side: "BUY",
    price: 0.5,
    size: 100,
    timestamp: new Date(),
    resolved: true,
    won: true,
    pnl: 50,
    liquidity: 50_000,
    spread: 0.01,
    ...overrides,
  };
}

describe("oneHitWonderPenalty", () => {
  it("penalizes heavily when all profit came from one trade", () => {
    const trades = [
      trade({ pnl: 5000 }), // the one big win
      trade({ pnl: 10 }),
      trade({ pnl: 12 }),
      trade({ pnl: -40, won: false }),
    ];
    expect(oneHitWonderPenalty(trades)).toBeGreaterThan(70);
  });

  it("gives low penalty for evenly distributed wins", () => {
    const trades = Array.from({ length: 10 }, () => trade({ pnl: 50 }));
    expect(oneHitWonderPenalty(trades)).toBeLessThan(20);
  });

  it("maximally penalizes wallets with no wins", () => {
    const trades = [trade({ pnl: -50, won: false }), trade({ pnl: -30, won: false })];
    expect(oneHitWonderPenalty(trades)).toBe(100);
  });

  it("heavily penalizes a single-win wallet", () => {
    expect(oneHitWonderPenalty([trade({ pnl: 100 })])).toBeGreaterThanOrEqual(90);
  });
});

describe("consistencyScore", () => {
  it("scores steady winners above volatile ones", () => {
    const steady = Array.from({ length: 12 }, () => trade({ pnl: 40 }));
    const volatile = [
      trade({ pnl: 900 }),
      trade({ pnl: -400, won: false }),
      trade({ pnl: 500 }),
      trade({ pnl: -600, won: false }),
      trade({ pnl: 700 }),
      trade({ pnl: -450, won: false }),
    ];
    expect(consistencyScore(steady)).toBeGreaterThan(consistencyScore(volatile));
  });

  it("returns low score with too few resolved trades", () => {
    expect(consistencyScore([trade()])).toBeLessThanOrEqual(10);
  });
});

describe("copyabilityScore", () => {
  it("penalizes illiquid, wide-spread wallets", () => {
    const liquid = Array.from({ length: 8 }, () => trade({ liquidity: 80_000, spread: 0.008 }));
    const illiquid = Array.from({ length: 8 }, () => trade({ liquidity: 300, spread: 0.15 }));
    expect(copyabilityScore(liquid, DEFAULT_RULES)).toBeGreaterThan(
      copyabilityScore(illiquid, DEFAULT_RULES) + 20
    );
  });

  it("penalizes extreme-price entries", () => {
    const normal = Array.from({ length: 8 }, () => trade({ price: 0.5 }));
    const extreme = Array.from({ length: 8 }, () => trade({ price: 0.98 }));
    expect(copyabilityScore(normal, DEFAULT_RULES)).toBeGreaterThan(
      copyabilityScore(extreme, DEFAULT_RULES)
    );
  });
});

describe("scoreWallet", () => {
  it("caps unproven wallets (few resolved trades)", () => {
    const trades = [trade(), trade(), trade({ resolved: false, pnl: undefined })];
    const score = scoreWallet(trades, DEFAULT_RULES);
    expect(score.globalScore).toBeLessThanOrEqual(40);
  });

  it("identifies best category", () => {
    const trades = [
      trade({ marketCategory: "sports", pnl: 200 }),
      trade({ marketCategory: "sports", pnl: 150 }),
      trade({ marketCategory: "politics", pnl: 5 }),
      trade({ marketCategory: "politics", pnl: 8 }),
      trade({ marketCategory: "politics", pnl: -20, won: false }),
      trade({ marketCategory: "sports", pnl: 90 }),
    ];
    expect(scoreWallet(trades, DEFAULT_RULES).bestCategory).toBe("sports");
  });

  it("scores a strong wallet above a weak one and statuses reflect it", () => {
    const strong = Array.from({ length: 15 }, (_, i) =>
      trade({ pnl: 40 + (i % 4) * 10, liquidity: 60_000, spread: 0.01 })
    );
    const weak = [
      trade({ pnl: 3000, liquidity: 400, spread: 0.12 }),
      trade({ pnl: -200, won: false, liquidity: 350, spread: 0.11 }),
      trade({ pnl: -150, won: false, liquidity: 500, spread: 0.13 }),
    ];
    const s1 = scoreWallet(strong, DEFAULT_RULES);
    const s2 = scoreWallet(weak, DEFAULT_RULES);
    expect(s1.globalScore).toBeGreaterThan(s2.globalScore);
    expect(walletStatus(s1, DEFAULT_RULES).status).toBe("track");
    expect(walletStatus(s2, DEFAULT_RULES).status).not.toBe("track");
    expect(walletStatus(s2, DEFAULT_RULES).reason).toBeTruthy();
  });
});

describe("wallet category basis (v72 class swap)", () => {
  const sample = [
    trade({ marketCategory: "nfl", marketCategoryClass: "sports", marketCategoryFine: "football-nfl", pnl: 40 }),
    trade({ marketCategory: "nba", marketCategoryClass: "sports", marketCategoryFine: "basketball-nba", pnl: 30 }),
    trade({ marketCategory: "will", marketCategoryClass: "politics", marketCategoryFine: "politics-us", pnl: -10, won: false }),
  ];

  it("defaults to the TOKEN basis, so any ruleset lacking the field scores as before", () => {
    expect(DEFAULT_RULES.walletCategoryBasis).toBe("token");
    const s = scoreWallet(sample, DEFAULT_RULES);
    expect(s.categoryBasis).toBe("token");
    expect(Object.keys(s.categoryStrengths).sort()).toEqual(["nba", "nfl", "will"]);
  });

  it("aggregates the same sample per COARSE class when the rule says class", () => {
    const s = scoreWallet(sample, { ...DEFAULT_RULES, walletCategoryBasis: "class" });
    expect(s.categoryBasis).toBe("class");
    expect(Object.keys(s.categoryStrengths).sort()).toEqual(["politics", "sports"]);
    expect(s.categoryStrengths.sports).toEqual({ trades: 2, winRate: 1, pnl: 70 });
    expect(s.bestCategory).toBe("sports");
    expect(s.copyabilityNotes).toContain("Strongest class: sports");
    // The fine grain is computed beside it as a diagnostic and never becomes the score's basis.
    expect(Object.keys(s.categoryStrengthsFine).sort()).toEqual([
      "basketball-nba",
      "football-nfl",
      "politics-us",
    ]);
  });

  it("never advertises the absence of a category as the strongest one", () => {
    const s = scoreWallet(
      [
        trade({ marketCategory: "highest", marketCategoryClass: undefined, pnl: 500 }),
        trade({ marketCategory: "highest", marketCategoryClass: undefined, pnl: 400 }),
      ],
      { ...DEFAULT_RULES, walletCategoryBasis: "class" }
    );
    expect(s.categoryStrengths.uncategorized.trades).toBe(2);
    expect(s.bestCategory).toBeNull();
  });

  it("buckets an empty class as uncategorized instead of falling back to the token", () => {
    expect(categoryBucketKey(trade({ marketCategory: "nfl", marketCategoryClass: "" }), "class")).toBe("uncategorized");
    expect(categoryBucketKey(trade({ marketCategory: "nfl", marketCategoryClass: "sports" }), "class")).toBe("sports");
    expect(categoryBucketKey(trade({ marketCategory: "nfl", marketCategoryClass: "sports" }), "token")).toBe("nfl");
  });

  it("round-trips the stored payload and decodes legacy flat maps as token-keyed", () => {
    const classScore = scoreWallet(sample, { ...DEFAULT_RULES, walletCategoryBasis: "class" });
    const payload = decodeCategoryStrengths(encodeCategoryStrengths(classScore));
    expect(payload.basis).toBe("class");
    expect(payload.strengths.sports.trades).toBe(2);
    expect(payload.fine?.["football-nfl"].trades).toBe(1);

    const legacy = decodeCategoryStrengths(JSON.stringify({ nfl: { trades: 2, winRate: 0.5, pnl: 10 } }));
    expect(legacy.basis).toBe("token");
    expect(legacy.strengths.nfl.winRate).toBe(0.5);
    expect(decodeCategoryStrengths(null).strengths).toEqual({});
    expect(decodeCategoryStrengths("not json").basis).toBe("token");
  });

  it("reads the win rate off the field that matches the map's own basis", () => {
    const classScore = scoreWallet(sample, { ...DEFAULT_RULES, walletCategoryBasis: "class" });
    const payload = decodeCategoryStrengths(encodeCategoryStrengths(classScore));
    expect(categoryWinRateFor(payload, { marketCategory: "nfl", marketCategoryClass: "sports" })).toBe(1);
    // A pre-2026-09-23 row carries no class: no category information (scoreTrade -> neutral 50),
    // never the token bucket's number.
    expect(
      categoryWinRateFor(payload, { marketCategory: "nfl", marketCategoryClass: null })
    ).toBeUndefined();

    const tokenPayload = decodeCategoryStrengths(JSON.stringify({ nfl: { trades: 2, winRate: 0.25, pnl: 1 } }));
    expect(categoryWinRateFor(tokenPayload, { marketCategory: "nfl", marketCategoryClass: "sports" })).toBe(0.25);
  });
});
