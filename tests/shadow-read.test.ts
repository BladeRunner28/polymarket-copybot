import { describe, it, expect } from "vitest";
import {
  evaluateShadowRead,
  clusteredBootstrapCi,
  stakeWeightedRead,
  type ShadowReadRow,
} from "../src/lib/shadow-read";

/**
 * The pre-registered shadow-read harness (phil audit Trial A).
 *
 * Each test pins one of the FOUR criteria, the KILL RULE, or the sampling bar,
 * because the harness's whole value is that its bar was fixed before outcomes
 * were read. A criterion that silently degrades to "pass" — an unreadable era,
 * a one-bet sample, a single-market "interval" — is worse than no harness, so
 * each of those has a test asserting it does NOT read as a pass.
 */

/** Deterministic row builder: `ret` is return per $1 staked. */
function row(over: Partial<ShadowReadRow> & { key: string }): ShadowReadRow {
  return {
    cluster: over.cluster ?? `m-${over.key}`,
    ret: over.ret ?? 0.2,
    stake: over.stake ?? 10,
    won: over.won ?? (over.ret ?? 0.2) > 0,
    decidedAt: over.decidedAt ?? Date.parse("2026-09-20T00:00:00Z"),
    era: over.era === undefined ? "v55" : over.era,
    ...over,
  } as ShadowReadRow;
}

/** n independent winners at a fixed return — the clean, well-powered case. */
function winners(n: number, ret = 0.2, era = "v55"): ShadowReadRow[] {
  return Array.from({ length: n }, (_, i) => row({ key: `w${i}`, ret, era }));
}

describe("stakeWeightedRead", () => {
  it("weights by stake, not by bet count", () => {
    // A $10 bet at +100% and a $1000 bet at +1% must average near 1%, not near 50%.
    const rows = [
      row({ key: "small", ret: 1.0, stake: 10 }),
      row({ key: "big", ret: 0.01, stake: 1000 }),
    ];
    const r = stakeWeightedRead(rows);
    expect(r.roi).toBeGreaterThan(0.015);
    expect(r.roi).toBeLessThan(0.025);
  });

  it("refuses a standard error from a single bet (that is how one bet becomes a 'win')", () => {
    const r = stakeWeightedRead([row({ key: "only", ret: 0.5 })]);
    expect(r.se).toBeCloseTo(0.5, 6);
  });

  it("is safe on empty input", () => {
    expect(stakeWeightedRead([])).toEqual({ roi: 0, se: 0, stakeUsd: 0 });
  });
});

describe("clusteredBootstrapCi", () => {
  it("is deterministic for a fixed seed (a CI that moves per run is not pre-registered)", () => {
    const rows = winners(200);
    const a = clusteredBootstrapCi(rows);
    const b = clusteredBootstrapCi(rows);
    expect(a).toEqual(b);
  });

  it("resamples markets, so same-market rows do not inflate the sample", () => {
    // 40 bets, all on ONE market, all winners: a row-level bootstrap would call
    // this significant; a market-clustered one cannot.
    const rows = Array.from({ length: 40 }, (_, i) => row({ key: `c${i}`, cluster: "same-market", ret: 0.3 }));
    const ci = clusteredBootstrapCi(rows);
    expect(ci.low).toBe(ci.high);
  });
});

describe("evaluateShadowRead — kill rule and sampling bar", () => {
  it("returns too_few_bets below MIN_BETS, never a verdict", () => {
    const r = evaluateShadowRead(winners(14));
    expect(r.decision).toBe("too_few_bets");
    expect(r.reasons[0]).toMatch(/KILL RULE/);
    expect(r.reasons[0]).toMatch(/NOT a verdict/);
  });

  it("returns underpowered below the pre-registered bar even when every criterion holds", () => {
    const r = evaluateShadowRead(winners(149));
    expect(r.criterionA).toBe(true);
    expect(r.criterionB).toBe(true);
    expect(r.criterionC).toBe(true);
    expect(r.criterionD).toBe(true);
    expect(r.decision).toBe("underpowered");
    expect(r.decision).not.toBe("pass");
  });

  it("passes only when powered AND all four criteria hold", () => {
    const r = evaluateShadowRead(winners(150));
    expect(r.decision).toBe("pass");
    expect(r.reasons).toEqual([]);
  });
});

describe("evaluateShadowRead — the four criteria", () => {
  it("(a) fails when the edge does not clear its own standard error", () => {
    // Alternating +100% / -98%: a POSITIVE mean (+1%/bet) that is dwarfed by its
    // own dispersion, so a naive "mean PnL > 0" would pass and cw_return does not.
    const rows = Array.from({ length: 200 }, (_, i) =>
      row({ key: `n${i}`, ret: i % 2 === 0 ? 1.0 : -0.98, era: "v55" })
    );
    const r = evaluateShadowRead(rows);
    expect(r.roi).toBeGreaterThan(0);
    expect(r.weightedSe).toBeGreaterThan(r.roi);
    expect(r.cwReturn).toBeLessThanOrEqual(0);
    expect(r.criterionA).toBe(false);
    expect(r.decision).toBe("fail");
  });

  it("(b) fails when one bet dominates positive P&L — phil's actual failure mode", () => {
    const big = row({ key: "the-one-bet", ret: 60, stake: 10 }); // +$600
    const rest = Array.from({ length: 199 }, (_, i) => row({ key: `r${i}`, ret: 0.1 })); // +$1 each
    const r = evaluateShadowRead([big, ...rest]);
    expect(r.largestWinnerShare).toBeGreaterThan(0.5);
    expect(r.criterionB).toBe(false);
    expect(r.decision).toBe("fail");
  });

  it("(b) measures dominance over POSITIVE P&L only (a big loser must not dilute it)", () => {
    const rows = [
      row({ key: "winner", ret: 5, stake: 10 }), // +$50
      ...Array.from({ length: 199 }, (_, i) => row({ key: `d${i}`, ret: -0.2 })), // losers
    ];
    const r = evaluateShadowRead(rows);
    expect(r.largestWinnerShare).toBeCloseTo(1, 6);
    expect(r.criterionB).toBe(false);
  });

  it("(c) fails on a single market cluster instead of reading a degenerate interval as significance", () => {
    const rows = Array.from({ length: 200 }, (_, i) => row({ key: `s${i}`, cluster: "one-market", ret: 0.4 }));
    const r = evaluateShadowRead(rows);
    expect(r.clusters).toBe(1);
    expect(r.criterionC).toBe(false);
    expect(r.decision).toBe("fail");
  });

  it("(d) reports an unreadable era as null, and null never passes", () => {
    const rows = winners(200).map((r) => ({ ...r, era: null }));
    const r = evaluateShadowRead(rows);
    expect(r.eras).toBeNull();
    expect(r.criterionD).toBeNull();
    expect(r.decision).toBe("fail");
    expect(r.reasons.join(" ")).toMatch(/UNVERIFIABLE/);
  });

  it("(d) fails when the sign flips between eras, even if the pooled read is positive", () => {
    const rows = [...winners(120, 0.2, "v55"), ...winners(80, -0.1, "v60")];
    const r = evaluateShadowRead(rows);
    expect(r.eras?.map((e) => e.era)).toEqual(["v55", "v60"]);
    expect(r.criterionD).toBe(false);
    expect(r.decision).toBe("fail");
    expect(r.reasons.join(" ")).toMatch(/sign not consistent across eras/);
  });
});
