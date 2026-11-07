import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  canonicalJson,
  checkFrozen,
  checkTouchedPaths,
  digestManifest,
  freezeEndsAt,
  isEnforced,
  sha256Hex,
  verifyPin,
  type FreezeManifest,
  type FreezePin,
} from "../src/lib/frozen-artifacts";

const ROOT = path.resolve(__dirname, "..");
const manifest = JSON.parse(readFileSync(path.join(ROOT, "data/frozen-artifacts.json"), "utf8")) as FreezeManifest;
const pin = JSON.parse(readFileSync(path.join(ROOT, "data/frozen-artifacts.pin.json"), "utf8")) as FreezePin;
const readRel = (rel: string): Buffer | null => {
  try {
    return readFileSync(path.join(ROOT, rel));
  } catch {
    return null;
  }
};

const entry = (over: Partial<FreezeManifest["entries"][number]> = {}) => ({
  id: "e1",
  reason: "FREEZE REASON under test",
  frozenFrom: "2026-01-01",
  frozenUntil: "2999-12-31" as string | null,
  approval: { date: "2026-01-01", by: "test", quote: "test" },
  artifacts: [{ path: "a.json", sha256: sha256Hex("clean") }],
  ...over,
});
const withEntry = (...entries: FreezeManifest["entries"]): FreezeManifest => ({ version: 1, updatedAt: "2026-01-01T00:00:00Z", entries });
const NOW = new Date("2026-06-01T00:00:00Z");

describe("frozen artifacts — the live set", () => {
  it("every enforced freeze matches the bytes in the repo", () => {
    // This is the arm that runs on every `npx vitest run`: a session that edits a frozen artifact
    // breaks the suite, which is the finish condition every worker already respects.
    const r = checkFrozen({ manifest, readFile: readRel, now: new Date() });
    expect(r.violations).toEqual([]);
    expect(r.enforced.length).toBeGreaterThan(0);
  });

  it("the manifest digest matches the pin, and no window has closed unexpectedly", () => {
    const v = verifyPin(manifest, pin, new Date());
    expect(v.problems).toEqual([]);
    expect(v.ok).toBe(true);
  });

  it("every entry carries a dated approval and a reason (nothing is frozen by prose alone)", () => {
    for (const e of manifest.entries) {
      expect(e.reason.length).toBeGreaterThan(20);
      expect(e.approval.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(e.approval.quote.length).toBeGreaterThan(0);
      expect(e.artifacts.length).toBeGreaterThan(0);
      for (const a of e.artifacts) expect(a.sha256).toMatch(/^[0-9a-f]{64}$/);
    }
  });
});

describe("frozen artifacts — each arm trips", () => {
  it("passes an untouched file", () => {
    const r = checkFrozen({ manifest: withEntry(entry()), readFile: () => Buffer.from("clean"), now: NOW });
    expect(r.violations).toEqual([]);
  });

  it("trips CHANGED with the freeze's own reason and both digests", () => {
    const r = checkFrozen({ manifest: withEntry(entry()), readFile: () => Buffer.from("refit-wrote-over-it"), now: NOW });
    expect(r.violations).toHaveLength(1);
    expect(r.violations[0]).toMatchObject({ kind: "changed", freezeId: "e1", path: "a.json", reason: "FREEZE REASON under test" });
    expect(r.violations[0].actual).toBe(sha256Hex("refit-wrote-over-it"));
    expect(r.violations[0].expected).toBe(sha256Hex("clean"));
  });

  it("trips MISSING when the frozen file is gone", () => {
    const r = checkFrozen({ manifest: withEntry(entry()), readFile: () => null, now: NOW });
    expect(r.violations.map((v) => v.kind)).toEqual(["missing"]);
  });

  it("trips TOUCHED for a commit that names a frozen path, and only that path", () => {
    const m = withEntry(entry());
    const hit = checkTouchedPaths(["data/a.json"], m, NOW);
    expect(hit.map((v) => v.kind)).toEqual(["touched"]);
    expect(hit[0].reason).toBe("FREEZE REASON under test");
    expect(checkTouchedPaths(["src/lib/rules.ts"], m, NOW)).toEqual([]);
  });

  it("stops enforcing once the window closes, and reports it as expired not clean-in-silence", () => {
    const m = withEntry(entry({ frozenUntil: "2026-05-31" }));
    const r = checkFrozen({ manifest: m, readFile: () => Buffer.from("anything"), now: NOW });
    expect(r.violations).toEqual([]);
    expect(r.expired).toEqual([{ id: "e1", frozenUntil: "2026-05-31" }]);
    expect(checkTouchedPaths(["data/a.json"], m, NOW)).toEqual([]);
  });

  it("does not enforce before the window opens", () => {
    const m = withEntry(entry({ frozenFrom: "2026-07-01" }));
    expect(checkFrozen({ manifest: m, readFile: () => null, now: NOW }).violations).toEqual([]);
  });

  it("an open-ended freeze never expires", () => {
    expect(isEnforced(entry({ frozenUntil: null }), new Date("2099-01-01T00:00:00Z"))).toBe(true);
    expect(freezeEndsAt(entry({ frozenUntil: null }))).toBeNull();
  });
});

describe("frozen artifacts — bypass resistance", () => {
  it("an edited manifest trips the pin", () => {
    const edited = withEntry(entry(), entry({ id: "e2" }));
    expect(digestManifest(edited)).not.toBe(pin.manifestSha256);
    expect(verifyPin(edited, { ...pin, manifestSha256: digestManifest(manifest) }, NOW).ok).toBe(false);
  });

  it("removing an entry trips the pin even though nothing else changed", () => {
    const shrunk: FreezeManifest = { ...manifest, entries: manifest.entries.slice(1) };
    expect(verifyPin(shrunk, pin, NOW).ok).toBe(false);
  });

  it("a window that closes without being retired trips the pin's expiry list", () => {
    const late = new Date("2026-11-21T00:00:00Z");
    const v = verifyPin(manifest, pin, late);
    expect(v.ok).toBe(false);
    expect(v.problems.join(" ")).toContain("kelly-band-020-040-unresolved");
  });

  it("the digest is stable across key order", () => {
    const a = { version: 1, updatedAt: "x", entries: [] };
    const b = { entries: [], updatedAt: "x", version: 1 };
    expect(canonicalJson(a)).toBe(canonicalJson(b));
    expect(digestManifest(a as FreezeManifest)).toBe(digestManifest(b as FreezeManifest));
  });
});
