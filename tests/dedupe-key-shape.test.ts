/**
 * 2026-11-03 (tuning #75 Rec 1) — the same-run copy dedupe must anchor on the
 * SAME key shape it checks.
 *
 * Defect this pins: `score-trades.ts` seeded `openCopyKeys` from
 * `positionIdentityKey(...)` and tested membership against
 * `positionIdentityKey(...)`, but ADDED the just-opened anchor as
 * `${walletAddress}|${marketId}|${outcome}` — the raw label, with no
 * `outcomeIdentity` normalisation. Any outcome whose label normalises
 * (spaces/case/punctuation stripped) therefore never matched its own anchor,
 * so the guard silently passed and the same copy could open twice in one run.
 *
 * Measured on live bookings: 5 same-run duplicate pairs since 2026-10-30, two
 * of them on 2026-11-03 ($55.94 of doubled exposure, one pair duplicating a
 * -$35.98 loss). The per-market legs rail was the only thing bounding it.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { positionIdentityKey } from "../src/lib/outcome-identity";

const SOURCE = readFileSync(join(process.cwd(), "scripts", "score-trades.ts"), "utf8");

describe("same-run copy dedupe key shape", () => {
  it("normalisation collapses the label pair that produced the duplicate pairs", () => {
    const spaced = positionIdentityKey("0xwallet", "mkt1", "NEMIGA GAMING");
    const tight = positionIdentityKey("0xwallet", "mkt1", "NEMIGAGAMING");
    expect(spaced).toBe(tight);
  });

  it("the raw template that used to be added does NOT match the normalised key", () => {
    const raw = `${"0xwallet"}|${"mkt1"}|${"NEMIGA GAMING"}`;
    expect(raw).not.toBe(positionIdentityKey("0xwallet", "mkt1", "NEMIGA GAMING"));
  });

  it("every openCopyKeys.add goes through positionIdentityKey", () => {
    const adds = SOURCE.match(/openCopyKeys\.add\([^)]*\)/g) ?? [];
    expect(adds.length).toBeGreaterThan(0);
    for (const add of adds) {
      expect(add).toContain("positionIdentityKey(");
    }
  });

  it("no raw template literal is used as a dedupe key", () => {
    // Guards against reintroducing `${...}|${...}|${...}` around openCopyKeys.
    expect(SOURCE).not.toMatch(/openCopyKeys\.add\(`/);
  });

  it("the seed and the membership check both still use positionIdentityKey", () => {
    expect(SOURCE).toMatch(/positionIdentityKey\(p\.walletAddress/);
    const dupKeyUses = SOURCE.match(/positionIdentityKey\(t\.walletAddress, t\.marketId, t\.outcome\)/g) ?? [];
    // one for the membership check, one for the anchor add
    expect(dupKeyUses.length).toBeGreaterThanOrEqual(2);
  });
});
