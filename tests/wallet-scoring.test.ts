import { describe, it, expect } from "vitest";
import { scoreWallet, oneHitWonderPenalty, consistencyScore, copyabilityScore, walletStatus } from "../src/lib/scoring/wallet";
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
