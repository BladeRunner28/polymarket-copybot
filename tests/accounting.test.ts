/**
 * Accounting invariants. See src/lib/accounting.ts for why each of these exists — every one of
 * them has been violated at least once in this repo, and each violation produced a number that
 * looked plausible and was wrong.
 */

import { describe, it, expect } from "vitest";
import {
  dedupeFirstLeg,
  summarise,
  clusterBootstrapCI,
  TERMINAL_STATUSES,
  type LaneLeg,
} from "../src/lib/accounting";

const leg = (o: Partial<LaneLeg> & { marketId: string }): LaneLeg => ({
  walletAddress: "w1",
  outcome: "YES",
  cost: 10,
  pnl: 0,
  entryPrice: 0.5,
  openedAt: new Date("2026-10-01T00:00:00Z"),
  doneAt: new Date("2026-10-02T00:00:00Z"),
  ...o,
});

describe("invariant 1 — cost basis is DOLLARS, not shares", () => {
  it("treats cost as USD directly, never multiplied by entryPrice", () => {
    // $10 at risk returning $5 is +50%. If cost were treated as a share count and multiplied by
    // entryPrice (0.5), notional would read $5 and this would wrongly read +100%.
    const s = summarise([leg({ marketId: "m1", cost: 10, pnl: 5, entryPrice: 0.5 })]);
    expect(s.notional).toBe(10);
    expect(s.roi).toBeCloseTo(50, 6);
  });

  it("returns NaN rather than a silent 0 when notional is zero", () => {
    expect(summarise([leg({ marketId: "m1", cost: 0, pnl: 0 })]).roi).toBeNaN();
    expect(summarise([]).roi).toBeNaN();
  });
});

describe("invariant 2 — both terminal statuses count", () => {
  it("includes early exits AND natural resolutions", () => {
    expect([...TERMINAL_STATUSES].sort()).toEqual(["closed", "resolved"]);
  });
});

describe("invariant 3 — dedupe to the first leg per (wallet, market, outcome)", () => {
  it("keeps only the first leg when a wallet re-trades one market/outcome", () => {
    const rows = [
      { walletAddress: "w1", marketId: "m1", outcome: "YES", tag: "first" },
      { walletAddress: "w1", marketId: "m1", outcome: "YES", tag: "second" },
      { walletAddress: "w1", marketId: "m1", outcome: "YES", tag: "third" },
    ];
    const out = dedupeFirstLeg(rows);
    expect(out).toHaveLength(1);
    expect(out[0].tag).toBe("first");
  });

  it("does NOT collapse distinct outcomes or distinct wallets", () => {
    const rows = [
      { walletAddress: "w1", marketId: "m1", outcome: "YES" },
      { walletAddress: "w1", marketId: "m1", outcome: "NO" },
      { walletAddress: "w2", marketId: "m1", outcome: "YES" },
      { walletAddress: "w2", marketId: "m2", outcome: "YES" },
    ];
    expect(dedupeFirstLeg(rows)).toHaveLength(4);
  });
});

describe("invariant 4 — CIs cluster by market, not by leg", () => {
  // Two markets, each with 100 perfectly correlated legs. Leg-clustered resampling would treat
  // 200 independent observations and produce a tight CI around 0. Market-clustered resampling
  // sees only TWO independent draws, so the interval must be very wide.
  const clustered: LaneLeg[] = [
    ...Array.from({ length: 100 }, () => leg({ marketId: "win", cost: 10, pnl: 10 })),
    ...Array.from({ length: 100 }, () => leg({ marketId: "lose", cost: 10, pnl: -10 })),
  ];

  it("produces a wide interval when legs are correlated within markets", () => {
    const ci = clusterBootstrapCI(clustered, { iterations: 2000, seed: 42 });
    expect(ci.markets).toBe(2);
    expect(ci.point).toBeCloseTo(0, 6);
    // the whole point: a leg-clustered CI here would be ~±2%; this must be far wider
    expect(ci.lo).toBeLessThan(-50);
    expect(ci.hi).toBeGreaterThan(50);
  });

  it("is deterministic for a given seed", () => {
    const a = clusterBootstrapCI(clustered, { iterations: 500, seed: 7 });
    const b = clusterBootstrapCI(clustered, { iterations: 500, seed: 7 });
    expect(a.lo).toBe(b.lo);
    expect(a.hi).toBe(b.hi);
  });

  it("narrows toward the point estimate as markets are added independently", () => {
    // 200 independent markets, half winning, each one leg — genuinely independent draws.
    const independent: LaneLeg[] = Array.from({ length: 200 }, (_, i) =>
      leg({ marketId: `m${i}`, cost: 10, pnl: i % 2 === 0 ? 10 : -10 })
    );
    const ci = clusterBootstrapCI(independent, { iterations: 2000, seed: 11 });
    expect(ci.markets).toBe(200);
    expect(ci.hi - ci.lo).toBeLessThan(40); // tight
  });
});
