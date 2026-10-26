/**
 * The drift gate must tell a DISCOUNT from a CHASE.
 *
 * Measured 2026-10-26 on data/drift-shadow.jsonl (settled, ex-$0.10-dust, deduped per
 * wallet/market/outcome, market-clustered CIs): FAVOURABLE n=4,303 net +31.9%, ADVERSE
 * n=3,616/4,021 net -19.0%. The absolute-value gate blended them into +7.3% and skipped
 * both. By magnitude the halves are opposite, not symmetric:
 *
 *   adverse   >= 0.05   n=2,434   net -32.5%   <- must stay blocked
 *   favourable 0.004-0.05 n=2,583 trimmed 5% mean -0.9%   <- noise either way
 *   favourable >= 0.05  n=1,720   median +43.4%, trimmed +53.9%, top-10 = 7% of total
 *
 * These tests pin the DIRECTION semantics, which is the half that is not obvious: a
 * price that fell since the wallet's entry is the same position for less money, and a
 * BUY at a lower price is never "late".
 */
import { describe, it, expect } from "vitest";
import { scoreTrade } from "../src/lib/scoring/trade";
import { DEFAULT_RULES, type Rules } from "../src/lib/rules";

const BASE = {
  walletGlobalScore: 80,
  walletCategoryWinRate: 0.7,
  walletEntryPrice: 0.5,
  currentPrice: 0.502,
  spread: 0.01,
  liquidity: 60_000,
  timeToResolutionHours: 200,
};

const RULES: Rules = { ...DEFAULT_RULES, maxPriceDrift: 0.004 };

describe("drift direction — favourable (price fell) is never 'too late'", () => {
  it("does not skip a favourable move far beyond the tolerance", () => {
    // Wallet entered at 0.50, we can buy at 0.40: 10 cents CHEAPER, drift magnitude 0.10
    // — 25x the 0.004 tolerance, and entirely in our favour.
    const r = scoreTrade({ ...BASE, walletEntryPrice: 0.5, currentPrice: 0.4 }, RULES);
    expect(r.risks.join(" ")).not.toMatch(/drift/i);
    expect(r.decision).not.toBe("skip");
  });

  it("does not skip a deep favourable move", () => {
    const r = scoreTrade({ ...BASE, walletEntryPrice: 0.9, currentPrice: 0.55 }, RULES);
    expect(r.risks.join(" ")).not.toMatch(/drift/i);
    expect(r.decision).not.toBe("skip");
  });

  it("scores a favourable move as perfect timing, not a penalty", () => {
    const r = scoreTrade({ ...BASE, walletEntryPrice: 0.5, currentPrice: 0.4 }, RULES);
    expect(r.breakdown.entryTimingScore).toBe(100);
  });

  it("gives a favourable entry a higher timing score than an identical-magnitude chase", () => {
    const cheap = scoreTrade({ ...BASE, walletEntryPrice: 0.5, currentPrice: 0.45 }, RULES);
    const chase = scoreTrade({ ...BASE, walletEntryPrice: 0.5, currentPrice: 0.55 }, RULES);
    expect(cheap.breakdown.entryTimingScore).toBeGreaterThan(chase.breakdown.entryTimingScore);
  });
});

describe("drift direction — adverse (price rose) is still skipped", () => {
  it("skips a chase beyond the tolerance", () => {
    const r = scoreTrade({ ...BASE, walletEntryPrice: 0.5, currentPrice: 0.55 }, RULES);
    expect(r.decision).toBe("skip");
    expect(r.risks.join(" ")).toMatch(/drift/i);
    expect(r.risks.join(" ")).toMatch(/against us/i);
  });

  it("still admits a near-instant entry inside the tolerance", () => {
    // 0.001 adverse. (0.503 also clears the drift tolerance but is refused by
    // `confidence < minConfidence`, which is a different gate — do not conflate them.)
    const r = scoreTrade({ ...BASE, walletEntryPrice: 0.5, currentPrice: 0.501 }, RULES);
    expect(r.decision).toBe("paper_copy");
  });

  it("decays the timing score as the chase widens", () => {
    // maxPriceDrift is 0.004 and the formula spends 80 points across it, so the usable
    // range is sub-0.005: 0.0015 -> 70, 0.0030 -> 40, and anything >= 0.005 clamps to 0.
    const small = scoreTrade({ ...BASE, walletEntryPrice: 0.5, currentPrice: 0.5015 }, RULES);
    const large = scoreTrade({ ...BASE, walletEntryPrice: 0.5, currentPrice: 0.503 }, RULES);
    expect(small.breakdown.entryTimingScore).toBeGreaterThan(large.breakdown.entryTimingScore);
    const zeroed = scoreTrade({ ...BASE, walletEntryPrice: 0.5, currentPrice: 0.53 }, RULES);
    expect(zeroed.breakdown.entryTimingScore).toBe(0);
  });
});

describe("short-TTR lane uses adverse drift only", () => {
  const LANE: Rules = { ...DEFAULT_RULES, shortTtrMaxHours: 72, shortTtrMinHours: 2, shortTtrMaxDrift: 0.05 };

  it("keeps a favourable entry eligible for the lane", () => {
    // 0.90 -> 0.55 is a 0.35 favourable move, far past shortTtrMaxDrift 0.05.
    const r = scoreTrade(
      { ...BASE, walletEntryPrice: 0.9, currentPrice: 0.55, timeToResolutionHours: 40 },
      LANE
    );
    expect(r.risks.join(" ")).not.toMatch(/drift/i);
  });

  it("still disqualifies an adverse entry past the lane cap", () => {
    const r = scoreTrade(
      { ...BASE, walletEntryPrice: 0.5, currentPrice: 0.60, timeToResolutionHours: 40 },
      LANE
    );
    expect(r.risks.join(" ")).toMatch(/drift/i);
  });
});
