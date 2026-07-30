/**
 * Safety tests: version 1 must be paper-only, read-only against markets.
 */

import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import {
  REAL_EXECUTION_ENABLED,
  assertPaperOnly,
  clampPaperSize,
  PAPER_MIN_SIZE_USD,
  PAPER_MAX_SIZE_USD,
} from "../src/lib/safety";
import { redactSecrets } from "../src/lib/redact";

describe("read-only safety / no real trade execution", () => {
  it("REAL_EXECUTION_ENABLED is hard-coded false", () => {
    expect(REAL_EXECUTION_ENABLED).toBe(false);
  });

  it("assertPaperOnly does not throw while execution is disabled", () => {
    expect(() => assertPaperOnly("test")).not.toThrow();
  });

  it("position sizes are always clamped to $.25-$20", () => {
    expect(clampPaperSize(0)).toBe(PAPER_MIN_SIZE_USD);
    expect(clampPaperSize(-100)).toBe(PAPER_MIN_SIZE_USD);
    expect(clampPaperSize(1_000_000)).toBe(PAPER_MAX_SIZE_USD);
    expect(clampPaperSize(NaN)).toBe(PAPER_MIN_SIZE_USD);
    expect(clampPaperSize(12)).toBe(12);
  });

  it("live adapter source contains no order/signing endpoints", () => {
    const src = fs.readFileSync(
      path.join(__dirname, "../src/lib/adapters/polymarket.ts"),
      "utf-8"
    );
    // Only GET requests, no order placement, no signing, no private keys.
    expect(src).not.toMatch(/method:\s*["'](POST|PUT|DELETE)/i);
    expect(src.toLowerCase()).not.toContain("privatekey");
    expect(src.toLowerCase()).not.toContain("signtransaction");
    expect(src).not.toContain("clob.polymarket.com/order");
  });

  it("codebase never asks for or stores private keys", () => {
    const roots = ["src", "scripts", "prisma"];
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const f of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, f.name);
        if (f.isDirectory()) walk(p);
        else if (/\.(ts|tsx|prisma)$/.test(f.name)) {
          const content = fs.readFileSync(p, "utf-8").toLowerCase();
          if (content.includes("private_key") || content.includes("privatekey") || content.includes("mnemonic")) {
            offenders.push(p);
          }
        }
      }
    };
    for (const r of roots) walk(path.join(__dirname, "..", r));
    expect(offenders).toEqual([]);
  });
});

describe("secret redaction", () => {
  it("redacts Discord webhook URLs", () => {
    const msg = "sent to https://discord.com/api/webhooks/12345/abcdef-secret";
    expect(redactSecrets(msg)).not.toContain("abcdef-secret");
    expect(redactSecrets(msg)).toContain("[REDACTED");
  });

  it("redacts 64-char hex strings that could be keys", () => {
    const fakeKey = "0x" + "a1b2c3d4".repeat(8);
    expect(redactSecrets(`oops ${fakeKey}`)).not.toContain(fakeKey);
  });

  it("redacts bearer tokens", () => {
    expect(redactSecrets("Authorization: Bearer abcdefghijklmnop12345")).not.toContain(
      "abcdefghijklmnop12345"
    );
  });
});
