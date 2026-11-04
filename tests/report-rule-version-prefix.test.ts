/**
 * Rule-change bullet: the version is printed ONCE, and "Top lesson" does not reprint the rule text.
 *
 * 2026-11-04 (self-audit). Measured on the 11-03 EOD dry run (prisma/dev.db, live):
 *   BEFORE  "• Rule changes: 1 — v71: v71: the band map was lane-blind; ..."
 *           "• Top lesson: v71: v71: the band map was lane-blind; ... (same 245-char sentence)"
 *   AFTER   "• Rule changes: 1 — v71: the band map was lane-blind; ..."
 *           "• Top lesson: the rule change above (v71) is the day's lesson — ..."
 * 1 of 70 stored reasons opens with "v71:"; 13 more open with "v52 ..." .. "v64 ..." (each naming
 * their OWN version), so the same doubling was on the wire for every rule-change day since v52.
 * 2 of 70 (v69, v70) open with an EARLIER version's token and MUST NOT be stripped.
 */
import { describe, expect, it } from "vitest";
import { withoutOwnVersion } from "../src/lib/report";

describe("withoutOwnVersion", () => {
  it("strips the row's own version when it opens the reason", () => {
    expect(withoutOwnVersion("v71: the band map was lane-blind", 71)).toBe("the band map was lane-blind");
    expect(withoutOwnVersion("v64 (user-approved 2026-10-20): give STANDARD the open-position cap", 64)).toBe(
      "(user-approved 2026-10-20): give STANDARD the open-position cap"
    );
    expect(withoutOwnVersion("v53 Change 1 (user-approved): hard-skip", "53")).toBe(
      "Change 1 (user-approved): hard-skip"
    );
  });

  it("keeps a reference to an EARLIER version verbatim", () => {
    // v69's real reason opens on v68; v70's opens on v66. A version-blind strip would eat these.
    expect(withoutOwnVersion("v68 gave the same 1.5x up-weight to 3-7d", 69)).toBe(
      "v68 gave the same 1.5x up-weight to 3-7d"
    );
    expect(withoutOwnVersion("v66's standard stale exit recycles capital", 70)).toBe(
      "v66's standard stale exit recycles capital"
    );
  });

  it("does not strip a version number that is a prefix of another (v7 vs v71)", () => {
    expect(withoutOwnVersion("v71: x", 7)).toBe("v71: x");
    expect(withoutOwnVersion("v7: x", 7)).toBe("x");
  });

  it("never returns an empty reason", () => {
    expect(withoutOwnVersion("v71:", 71)).toBe("v71:");
    expect(withoutOwnVersion("", 71)).toBe("");
  });

  it("leaves a reason with no version token untouched", () => {
    const r = "STANDARD sizes flat across a maturity axis whose realised ROI disagrees";
    expect(withoutOwnVersion(r, 68)).toBe(r);
  });
});
