/**
 * v58 per-wallet concentration ceiling (2026-09-19 tuning review #30 rec 1,
 * user-approved). Baseline that justified it: top wallet 0xb0c8…fe7f carried
 * 50 open rows / $997.38 = 84.6% of the C-200 book (top-3 94.1%) against an
 * effective cap of $1,734.50 — i.e. 57.5% of the whole cap in one wallet, with
 * no per-wallet rail at all. The analogous per-market rail (v55) had just been
 * measured non-binding (10 blocks, all pre-cap-growth, 0 since), so the two no
 * longer confound each other.
 */

import { describe, it, expect } from "vitest";
import { walletCapDecision } from "../src/lib/exposure-cap";

describe("walletCapDecision", () => {
  // 25% of the live $1,734.50 cap = $433.63
  const base = { notionalAlready: 0, sizeUsd: 100, notionalCapUsd: 433.63 };

  it("allows a Kelly-sized admit on a clean wallet", () => {
    expect(walletCapDecision(base).blocked).toBe(false);
  });

  it("allows accumulating up to the ceiling and blocks above it", () => {
    // 333.63 + 100 = 433.63 == cap → allowed (the gate fires only ABOVE the cap)
    expect(walletCapDecision({ ...base, notionalAlready: 333.63 }).blocked).toBe(false);
    // one cent over → blocked
    const d = walletCapDecision({ ...base, notionalAlready: 333.64 });
    expect(d.blocked).toBe(true);
    expect(d.why).toContain("notional $433.64 > cap $433.63");
  });

  it("blocks the live 84.6% wallet immediately (the measured baseline)", () => {
    // 997.38 already on the book; even a $2.25 dust leg projects over the cap
    const d = walletCapDecision({ notionalAlready: 997.38, sizeUsd: 2.25, notionalCapUsd: 433.63 });
    expect(d.blocked).toBe(true);
    expect(d.why).toContain("notional");
  });

  it("does not block a dust-sized leg on a wallet sitting just under the cap", () => {
    expect(walletCapDecision({ notionalAlready: 430, sizeUsd: 2.25, notionalCapUsd: 433.63 }).blocked).toBe(false);
  });

  it("0 disables the ceiling (legacy semantics — DEFAULT_RULES)", () => {
    expect(walletCapDecision({ notionalAlready: 9999, sizeUsd: 100, notionalCapUsd: 0 }).blocked).toBe(false);
  });

  it("scales with the cap: the same wallet passes at 25% of a doubled cap", () => {
    const doubled = 867.25; // 25% of $3,469
    expect(walletCapDecision({ notionalAlready: 500, sizeUsd: 100, notionalCapUsd: 433.63 }).blocked).toBe(true);
    expect(walletCapDecision({ notionalAlready: 500, sizeUsd: 100, notionalCapUsd: doubled }).blocked).toBe(false);
  });
});
