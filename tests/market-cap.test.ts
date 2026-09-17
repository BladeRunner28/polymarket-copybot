/**
 * v55 per-market concentration ceiling (2026-09-16 C-200 daily report Change 1,
 * user-approved). The 7-day replay that justified it: 298 legs booked, the
 * ceiling blocks 13 of them (all leg-3+ in one market) worth -$144.01.
 */

import { describe, it, expect } from "vitest";
import { marketCapDecision } from "../src/lib/exposure-cap";

describe("marketCapDecision", () => {
  const base = { legsAlready: 0, notionalAlready: 0, sizeUsd: 20, maxLegs: 2, notionalCapUsd: 135 };

  it("allows the first two legs under both limits", () => {
    expect(marketCapDecision(base).blocked).toBe(false);
    expect(marketCapDecision({ ...base, legsAlready: 1 }).blocked).toBe(false);
  });

  it("blocks the third leg in one market (the rule that bound in the replay)", () => {
    const d = marketCapDecision({ ...base, legsAlready: 2 });
    expect(d.blocked).toBe(true);
    expect(d.why).toContain("legs 3 > max 2");
  });

  it("blocks on notional even inside the leg limit", () => {
    const d = marketCapDecision({ ...base, legsAlready: 0, notionalAlready: 120, sizeUsd: 20 });
    expect(d.blocked).toBe(true);
    expect(d.why).toContain("notional");
  });

  it("counts the new leg into the projection, and the cap boundary is inclusive", () => {
    // 115 + 20 = 135 == cap → allowed (the gate fires only ABOVE the cap)
    expect(marketCapDecision({ ...base, notionalAlready: 115, sizeUsd: 20 }).blocked).toBe(false);
    // one cent over → blocked
    expect(marketCapDecision({ ...base, notionalAlready: 115.01, sizeUsd: 20 }).blocked).toBe(true);
  });

  it("0 disables each limit independently (legacy semantics)", () => {
    expect(marketCapDecision({ ...base, legsAlready: 9, maxLegs: 0 }).blocked).toBe(false);
    expect(marketCapDecision({ ...base, notionalAlready: 9999, notionalCapUsd: 0 }).blocked).toBe(false);
    expect(marketCapDecision({ legsAlready: 9, notionalAlready: 9999, sizeUsd: 20, maxLegs: 0, notionalCapUsd: 0 }).blocked).toBe(false);
  });

  it("leg limit is checked first, so its reason wins when both bind", () => {
    const d = marketCapDecision({ legsAlready: 5, notionalAlready: 9999, sizeUsd: 20, maxLegs: 2, notionalCapUsd: 100 });
    expect(d.why).toContain("legs 6 > max 2");
  });
});
