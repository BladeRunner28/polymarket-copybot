import { describe, expect, it } from "vitest";
import { sizingRangeLine } from "../src/lib/report";

/**
 * 2026-11-13 self-audit.
 *
 * The sizing-range line used to be unable to tell three states apart: a real
 * range, a genuinely empty week, and a FAILED read. `observedSizingRanges` returned
 * an empty Map from its catch, and the renderer maps "no entry for this bot" to
 * "no <BOT> trade opened in the last 7d" — so a dead aggregate printed as a clean
 * quiet week. These three cases are the whole point: the failure case must not
 * share a string with the empty case.
 */
const range = (min: number, max: number, n: number) => ({ ranges: new Map([["STANDARD", { min, max, n }]]), failed: false });

describe("sizing-range line tells a failed read from an empty window", () => {
  it("renders a real range with its window and n (live 2026-11-13: $4.00–$20.00, n=56)", () => {
    expect(sizingRangeLine("STANDARD", range(4, 20, 56))).toBe("• Sizing Range: $4.00–$20.00 (opened last 7d, n=56)");
    expect(sizingRangeLine("STANDARD", range(18, 18, 3))).toBe("• Sizing Range: $18.00 (opened last 7d, n=3)");
  });

  it("an EMPTY result still says no trade opened — that state is real and must stay readable", () => {
    const empty = { ranges: new Map(), failed: false };
    expect(sizingRangeLine("STANDARD", empty)).toBe("• Sizing Range: no STANDARD trade opened in the last 7d");
  });

  it("a FAILED read is not reported as 'no trades' (the old defect)", () => {
    const failed = { ranges: new Map(), failed: true, error: "SQLITE_BUSY: database is locked" };
    const line = sizingRangeLine("STANDARD", failed);
    expect(line).toContain("UNAVAILABLE");
    expect(line).toContain("database is locked");
    expect(line).not.toContain("no STANDARD trade opened");
    // The old code path produced exactly this string on failure:
    expect(line).not.toBe("• Sizing Range: no STANDARD trade opened in the last 7d");
  });

  it("a failed read still names a failure when the driver gives no message", () => {
    const line = sizingRangeLine("BANKROLL_200", { ranges: new Map(), failed: true });
    expect(line).toContain("UNAVAILABLE");
    expect(line).toContain("unknown");
  });
});
