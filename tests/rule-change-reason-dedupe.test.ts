/**
 * 2026-10-28 (self-audit) — a rule change must be recorded once, not once per field it touches.
 *
 * The EOD report's "Rule changes" bullet was 2,096 characters — about a third of the whole message — and
 * it was the same sentence six times. Cause was upstream of the report: `applyRuleChanges` joined one
 * reason per PROPOSAL, and a single decision touching N fields is N proposals that all carry the same
 * reason. Measured on the RuleChange table: v68 stored its reason x5 (1,477 chars), v69 x2, v66 x2 —
 * 4 of 68 rows affected. The renderer was innocent; it printed what it was given.
 *
 * This is an instrument fix, not a rules change: no threshold, sizing value or gate moves, and distinct
 * reasons are all preserved — only exact duplicates collapse.
 */

import { describe, it, expect } from "vitest";
import { dedupeProposalText } from "../src/lib/rules";

describe("dedupeProposalText: one decision, one reason", () => {
  it("collapses the same reason repeated once per changed field (v68: 5 fields)", () => {
    const r = "STANDARD sizes flat across a maturity axis whose realised ROI spans 9x";
    const out = dedupeProposalText([r, r, r, r, r]);
    expect(out).toBe(r);
    expect(out.split(" | ")).toHaveLength(1);
  });

  it("keeps two genuinely different reasons, in order", () => {
    const out = dedupeProposalText(["first reason", "second reason"]);
    expect(out).toBe("first reason | second reason");
  });

  it("collapses only the repeats, keeping distinct neighbours", () => {
    const out = dedupeProposalText(["a", "b", "a", "b", "c"]);
    expect(out).toBe("a | b | c");
  });

  it("ignores whitespace-only differences that would otherwise look like two reasons", () => {
    expect(dedupeProposalText(["same", "  same  "])).toBe("same");
  });

  it("drops empty entries rather than emitting a leading separator", () => {
    expect(dedupeProposalText(["", "real reason", null, undefined])).toBe("real reason");
  });

  it("returns an empty string for no proposals rather than 'undefined | undefined'", () => {
    expect(dedupeProposalText([])).toBe("");
  });
});
