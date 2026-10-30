/**
 * Outcome identity keys — the measured twin-spelling regression.
 *
 * The 14 pairs below are FROZEN EVIDENCE taken from prisma/dev.db at 2026-10-29T23:10Z,
 * level = token text over ObservedTrade, population 4,740,734 rows: 7,245 distinct
 * outcome texts collapse to 7,231 alnum-only identities, so exactly 14 tokens are
 * spelled two ways by the venue. Each pair must key as ONE identity, or the fill
 * dedupe, the sweep dedupe and the leg accounting split one position in two.
 */

import { describe, it, expect } from "vitest";
import { outcomeIdentity, fillIdentityKey, positionIdentityKey } from "../src/lib/outcome-identity";
import { dedupeFirstLeg } from "../src/lib/accounting";

const MEASURED_TWINS: Array<[string, string]> = [
  ["CDP JUNIOR FC", "CDPJUNIORFC"],
  ["JIA-JING LU", "JIAJING LU"],
  ["MACCABI TEL AVIV", "MACCABI TEL-AVIV"],
  ["NONGSHIM RED FORCE", "NONGSHIM REDFORCE"],
  ["OLDBOYS", "OLDBOYS-"],
  ["ORIOL ROCA BATALLA", "ORIOL ROCA-BATALLA"],
  ["PORTLAND FIRE", "PORTLANDFIRE"],
  ["SO-HYUN PARK", "SOHYUN PARK"],
  ["TEAM SECRET", "TEAM SECRET "],
  ["TSUNG HAO HUANG", "TSUNG-HAO HUANG"],
  ["X-CITY", "XCITY"],
  ["YEON-WOO KU", "YEONWOO KU"],
  ["YU JUN LIN", "YUJUN LIN"],
  ["YUN-SEONG CHUNG", "YUNSEONG CHUNG"],
];

describe("outcomeIdentity", () => {
  it("collapses every measured twin spelling to one key", () => {
    for (const [a, b] of MEASURED_TWINS) {
      expect(outcomeIdentity(a)).toBe(outcomeIdentity(b));
      expect(outcomeIdentity(a).length).toBeGreaterThan(0);
    }
  });
  it("keeps genuinely different tokens apart", () => {
    expect(outcomeIdentity("YES")).not.toBe(outcomeIdentity("NO"));
    expect(outcomeIdentity("OVER")).not.toBe(outcomeIdentity("UNDER"));
    expect(outcomeIdentity("TEAM LIQUID")).not.toBe(outcomeIdentity("TEAM SECRET"));
  });
  it("is blank-safe: no label means the empty identity, never a throw", () => {
    expect(outcomeIdentity(null)).toBe("");
    expect(outcomeIdentity(undefined)).toBe("");
    expect(outcomeIdentity("---")).toBe("");
  });
});

describe("fillIdentityKey", () => {
  const base = { marketId: "kbo-non-2026-10-09", marketQuestion: "Nongshim vs", side: "BUY", ts: 1793318400000 };
  it("keys one fill as one fill across two spellings", () => {
    expect(fillIdentityKey({ ...base, outcome: "NONGSHIM RED FORCE" })).toBe(
      fillIdentityKey({ ...base, outcome: "NONGSHIM REDFORCE" })
    );
  });
  it("still separates distinct fills on side, timestamp and market", () => {
    const yes = fillIdentityKey({ ...base, outcome: "YES" });
    expect(fillIdentityKey({ ...base, outcome: "YES", side: "SELL" })).not.toBe(yes);
    expect(fillIdentityKey({ ...base, outcome: "YES", ts: base.ts + 1 })).not.toBe(yes);
    expect(fillIdentityKey({ ...base, outcome: "YES", marketId: "other" })).not.toBe(yes);
  });
  it("keys a blank marketId on the question so parlay legs do not collapse", () => {
    const leg = (question: string) => fillIdentityKey({ marketId: "", marketQuestion: question, outcome: "YES", side: "BUY", ts: 1 });
    expect(leg("Parlay A")).not.toBe(leg("Parlay B"));
    expect(fillIdentityKey({ marketId: null, marketQuestion: "Parlay A", outcome: "YES", side: "BUY", ts: 1 })).toBe(leg("Parlay A"));
  });
});

describe("positionIdentityKey", () => {
  it("is one open position per wallet, market and token identity", () => {
    expect(positionIdentityKey("0xabc", "m1", "PORTLAND FIRE")).toBe(positionIdentityKey("0xabc", "m1", "PORTLANDFIRE"));
    expect(positionIdentityKey("0xabc", "m1", "PORTLAND FIRE")).not.toBe(positionIdentityKey("0xdef", "m1", "PORTLAND FIRE"));
    expect(positionIdentityKey("0xabc", "m1", "PORTLAND FIRE")).not.toBe(positionIdentityKey("0xabc", "m2", "PORTLAND FIRE"));
  });
});

describe("dedupeFirstLeg", () => {
  it("dedupes two spellings of one position and keeps the earlier leg", () => {
    const first = { walletAddress: "0xabc", marketId: "m1", outcome: "PORTLAND FIRE", id: "a" };
    const second = { walletAddress: "0xabc", marketId: "m1", outcome: "PORTLANDFIRE", id: "b" };
    expect(dedupeFirstLeg([first, second])).toEqual([first]);
  });
  it("still keeps distinct tokens", () => {
    const yes = { walletAddress: "0xabc", marketId: "m1", outcome: "YES", id: "a" };
    const no = { walletAddress: "0xabc", marketId: "m1", outcome: "NO", id: "b" };
    expect(dedupeFirstLeg([yes, no])).toHaveLength(2);
  });
});
