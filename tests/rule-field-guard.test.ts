/**
 * Guard for staged Lane A apply scripts — see src/lib/rule-field-guard.ts.
 *
 * The defect this closes: `apply-v73-c200-cheap-band-clip.ts` typed its proposal
 * field as a literal that is not yet in `Rules`, so `npx tsc --noEmit` was red at
 * HEAD from 2026-11-12 until 2026-11-13 — the repo-wide finish condition every
 * other session is verified against. The interlock's INTENT is preserved at run
 * time and proven here, including the negative control (the guard must throw, not
 * warn) and the "declared but unread" arm.
 */
import { describe, it, expect } from "vitest";
import {
  assertRuleFieldHasReader,
  assertRuleFieldImplemented,
  countRuleFieldReaders,
  isRuleFieldImplemented,
} from "../src/lib/rule-field-guard";
import { DEFAULT_RULES } from "../src/lib/rules";

describe("assertRuleFieldImplemented", () => {
  it("passes for a field that is actually part of the Rules shape", () => {
    expect(() => assertRuleFieldImplemented("minLiquidity")).not.toThrow();
    expect(isRuleFieldImplemented("minLiquidity")).toBe(true);
  });

  it("throws for the staged v73 field, which has no consumer yet", () => {
    expect(isRuleFieldImplemented("c200BandClipCaps")).toBe(false);
    expect(() => assertRuleFieldImplemented("c200BandClipCaps")).toThrow(/NOT implemented/);
  });

  it("names the offending field in the message", () => {
    expect(() => assertRuleFieldImplemented("c200BandClipCaps")).toThrow(/c200BandClipCaps/);
  });

  it("does not accept an inherited member as a rule field", () => {
    expect(() => assertRuleFieldImplemented("toString")).toThrow(/NOT implemented/);
  });

  it("respects an explicitly supplied rules record (fixture arm)", () => {
    const rules = { ...(DEFAULT_RULES as unknown as Record<string, unknown>), stagedField: "" };
    expect(() => assertRuleFieldImplemented("stagedField", rules)).not.toThrow();
    expect(() => assertRuleFieldImplemented("minLiquidity", {})).toThrow();
  });
});

describe("countRuleFieldReaders", () => {
  const fixture = [
    { path: "src/lib/rules.ts", text: "minLiquidity: 5000, stagedField: \"\"" },
    { path: "src/lib/sizing.ts", text: "if (rules.stagedField) return 1;" },
    { path: "src/lib/other.ts", text: "const x = rules.minLiquidity;" },
  ];

  it("does not count the definition module as a reader", () => {
    expect(countRuleFieldReaders("stagedField", fixture)).toBe(1);
  });

  it("counts zero when only the definition mentions the field", () => {
    expect(countRuleFieldReaders("stagedOnly", [{ path: "src/lib/rules.ts", text: "stagedOnly: 1" }])).toBe(0);
  });

  it("refuses a declared-but-unread field (the silent-no-op arm)", () => {
    expect(() => assertRuleFieldHasReader("stagedOnly", 0)).toThrow(/READ BY NOTHING/);
  });

  it("allows a field with at least one reader", () => {
    expect(() => assertRuleFieldHasReader("stagedField", 1)).not.toThrow();
  });

  it("finds a live reader for a live rule field in this repo's src tree", async () => {
    const { readdirSync, readFileSync, statSync } = await import("node:fs");
    const { join } = await import("node:path");
    const sources: Array<{ path: string; text: string }> = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const p = join(dir, name);
        if (statSync(p).isDirectory()) walk(p);
        else if (/\.tsx?$/.test(name)) sources.push({ path: p, text: readFileSync(p, "utf8") });
      }
    };
    walk("src");
    expect(countRuleFieldReaders("minLiquidity", sources)).toBeGreaterThan(0);
    expect(countRuleFieldReaders("c200BandClipCaps", sources)).toBe(0);
  });
});
