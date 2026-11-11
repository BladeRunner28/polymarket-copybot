/**
 * Arm check for the per-wallet-ceiling shadow (card t_bfb9e54c).
 *
 * The lane sat in the reconcile table as a 10/10 match for 53 days while its
 * feed held ZERO rows. These tests pin the property that made that possible:
 * an empty feed is only a legitimate zero when the gated rail is provably NOT
 * firing — never when it fired, and never when a wallet is already past its
 * ceiling.
 */

import { describe, expect, it } from "vitest";
import { assessWalletCapArming, type WalletCapArmingInput } from "../src/lib/wallet-cap-arming";
import { walletCapFeedState } from "../src/lib/shadow-wallet-cap";
import type { WalletCapBaselineFile } from "../src/lib/wallet-cap-basis";

const baselines: WalletCapBaselineFile = {
  declaredAt: "2026-09-20T09:40:34.849Z",
  appliedWithRuleSet: 59,
  capUsd: 1723.87,
  ceilingUsd: 430.97,
  basis: "delta",
  baseline: { "0xgrandfathered": 987.43 },
};

const base = (over: Partial<WalletCapArmingInput> = {}): WalletCapArmingInput => ({
  walletPctOfCap: 0.25,
  capUsd: 3525.76,
  basis: "delta",
  baselines,
  holdings: [{ walletAddress: "0xfresh", notionalUsd: 505.13 }],
  blocksInWindow: 0,
  windowDays: 7,
  feedRows: 0,
  maxClipUsd: 100,
  ...over,
});

describe("assessWalletCapArming — the ceiling itself", () => {
  it("is 25% of the effective cap, with no baseline for a wallet new since activation", () => {
    const a = assessWalletCapArming(base());
    expect(a.enabled).toBe(true);
    expect(a.walletCapUsd).toBeCloseTo(881.44, 2);
    expect(a.wallets[0].baselineUsd).toBe(0);
    expect(a.wallets[0].ceilingUsd).toBeCloseTo(881.44, 2);
    expect(a.wallets[0].headroomUsd).toBeCloseTo(376.31, 2);
    expect(a.wallets[0].ratio).toBeCloseTo(0.5731, 4);
  });

  it("adds the grandfather baseline under `delta`, and not under `stock`", () => {
    const holdings = [{ walletAddress: "0xgrandfathered", notionalUsd: 993.66 }];
    const delta = assessWalletCapArming(base({ holdings }));
    const stock = assessWalletCapArming(base({ holdings, basis: "stock" }));
    expect(delta.wallets[0].ceilingUsd).toBeCloseTo(881.44 + 987.43, 2);
    expect(delta.wallets[0].headroomUsd).toBeGreaterThan(0);
    // The episode that motivated v59: under `stock` the same wallet is 2.3x over.
    expect(stock.wallets[0].ceilingUsd).toBeCloseTo(881.44, 2);
    expect(stock.wallets[0].headroomUsd).toBeLessThan(0);
    expect(stock.breached).toEqual(["0xgrandfathered"]);
  });

  it("is DISABLED when the pct is 0 (the branch is skipped entirely)", () => {
    const a = assessWalletCapArming(base({ walletPctOfCap: 0 }));
    expect(a.enabled).toBe(false);
    expect(a.state).toBe("DISABLED");
    expect(a.walletCapUsd).toBe(0);
    expect(a.breached).toEqual([]);
    expect(a.contradiction).toBe(false);
    expect(a.note).toMatch(/cannot run/);
  });

  it("is DISABLED when the pct is set but the effective cap is 0", () => {
    const a = assessWalletCapArming(base({ capUsd: 0 }));
    expect(a.enabled).toBe(false);
    expect(a.state).toBe("DISABLED");
    expect(a.note).toMatch(/effective cap/);
  });
});

describe("assessWalletCapArming — silence vs a clean result", () => {
  it("an empty feed with a dormant rail is a real zero, not a defect", () => {
    const a = assessWalletCapArming(base());
    expect(a.state).toBe("DORMANT");
    expect(a.contradiction).toBe(false);
    expect(a.note).toMatch(/DORMANT \(a real zero, not a missing writer\)/);
    expect(a.note).toMatch(/3\.8x the largest clip/); // 376.31 / 100
  });

  it("an empty feed while the rail FIRED is the writer being broken", () => {
    const a = assessWalletCapArming(base({ blocksInWindow: 3 }));
    expect(a.state).toBe("FIRING");
    expect(a.contradiction).toBe(true);
    expect(a.note).toMatch(/WRITER BROKEN/);
    expect(a.note).toMatch(/fired 3x in the last 7d/);
  });

  it("an empty feed while a wallet is already at/over its ceiling is also broken", () => {
    const a = assessWalletCapArming(
      base({
        basis: "stock",
        holdings: [{ walletAddress: "0xover", notionalUsd: 993.66 }],
      })
    );
    expect(a.state).toBe("AT_CEILING");
    expect(a.breached).toEqual(["0xover"]);
    expect(a.contradiction).toBe(true);
    expect(a.note).toMatch(/already breached by 1 wallet/);
  });

  it("a POPULATED feed is never a contradiction, whatever the rail does", () => {
    const a = assessWalletCapArming(base({ blocksInWindow: 3, feedRows: 3 }));
    expect(a.state).toBe("FIRING");
    expect(a.contradiction).toBe(false);
  });

  it("a DISABLED rail with no blocks in the window is a legitimate empty feed", () => {
    const a = assessWalletCapArming(base({ walletPctOfCap: 0, blocksInWindow: 0, feedRows: 0 }));
    expect(a.state).toBe("DISABLED");
    expect(a.contradiction).toBe(false);
    expect(a.note).toMatch(/DISABLED, so there is nothing to record/);
  });

  it("a rail disabled TODAY does not excuse blocks recorded inside the window", () => {
    // The writer's duty is the same whichever way the pct points: a block was
    // journalled, so a row was owed. Silence is still a broken writer.
    const a = assessWalletCapArming(base({ walletPctOfCap: 0, blocksInWindow: 9, feedRows: 0 }));
    expect(a.state).toBe("DISABLED");
    expect(a.contradiction).toBe(true);
  });
});

describe("walletCapFeedState — an all-zero summary must explain itself", () => {
  const now = Date.parse("2026-11-11T19:00:00Z");
  const report = (generatedAt: string, armCheck: unknown) => ({
    generatedAt,
    lanes: [{ laneId: "walletCap", armCheck }],
  });
  const arm = { state: "DORMANT", contradiction: false, note: "DORMANT (a real zero, not a missing writer): …" };

  it("carries the gate's own note when the arm check is fresh", () => {
    const s = walletCapFeedState(report("2026-11-11T18:50:00Z", arm), now);
    expect(s.stale).toBe(false);
    expect(s.armCheckAsOf).toBe("2026-11-11T18:50:00Z");
    expect(s.note).toMatch(/DORMANT \(a real zero/);
    expect((s.armCheck as Record<string, unknown>).state).toBe("DORMANT");
  });

  it("flags an arm check older than a week instead of trusting it", () => {
    const s = walletCapFeedState(report("2026-10-20T00:00:00Z", arm), now);
    expect(s.stale).toBe(true);
    expect(s.note).toMatch(/STALE/);
    expect(s.note).toMatch(/shadow:reconcile/);
  });

  it("says the emptiness is UNEXPLAINED when no arm check is on disk", () => {
    for (const r of [null, {}, { generatedAt: "2026-11-11T18:50:00Z", lanes: [] }]) {
      const s = walletCapFeedState(r, now);
      expect(s.armCheck).toBeNull();
      expect(s.stale).toBe(false);
      expect(s.note).toMatch(/UNEXPLAINED/);
    }
  });
});

describe("assessWalletCapArming — ranking", () => {
  it("orders wallets by ratio and reports the tightest, not the largest", () => {
    const a = assessWalletCapArming(
      base({
        holdings: [
          { walletAddress: "0xbig", notionalUsd: 700 },
          { walletAddress: "0xtight", notionalUsd: 860 },
          { walletAddress: "0xgrandfathered", notionalUsd: 900 },
        ],
      })
    );
    expect(a.tightest?.walletAddress).toBe("0xtight");
    expect(a.wallets.map((w) => w.walletAddress)).toEqual(["0xtight", "0xbig", "0xgrandfathered"]);
    // The grandfathered wallet holds the most but is the FURTHEST from its ceiling.
    expect(a.wallets[2].ratio).toBeLessThan(a.wallets[0].ratio);
  });

  it("reports no tightest wallet on an empty book", () => {
    const a = assessWalletCapArming(base({ holdings: [] }));
    expect(a.tightest).toBeNull();
    expect(a.note).toMatch(/no open C-200 wallet/);
  });
});
