/**
 * Re-derivation rules for the venue-shadow det stamp (card det-our-side-flag-defect).
 * Each arm below is a way the ledger's one-shot, marketId-keyed stamp printed a wrong
 * side or a wrong contract — measured, not hypothetical.
 */

import { describe, it, expect } from "vitest";
import {
  DET_DERIVATION_VERSION, detKey, needsDetRederive, restampEntry, venueReadStale,
} from "../src/lib/kalshi-det-restamp";

describe("detKey", () => {
  it("separates two legs of ONE market — the collision that stamped the UFC pair twice", () => {
    const a = detKey("ufc-jar-ikr-2026-11-21", "JARED CANNONIER");
    const b = detKey("ufc-jar-ikr-2026-11-21", "IKRAM ALISKEROV");
    expect(a).not.toBe(b);
  });
  it("normalises surrounding whitespace the way pairKey() does", () => {
    expect(detKey(" m1 ", " YES ")).toBe(detKey("m1", "YES"));
    expect(detKey(null, null)).toBe("|");
  });
});

describe("needsDetRederive", () => {
  it("derives a row that was never stamped (the arm's forward backlog)", () => {
    expect(needsDetRederive({})).toBe(true);
  });
  it("re-derives an EQUIV stamp written by an older derivation", () => {
    expect(needsDetRederive({ detVerdict: "EQUIV" })).toBe(true);
    expect(needsDetRederive({ detVerdict: "EQUIV", detVersion: 1 })).toBe(true);
  });
  it("leaves a current stamp alone — no re-walk of the pool, no re-price", () => {
    expect(needsDetRederive({ detVerdict: "EQUIV", detVersion: DET_DERIVATION_VERSION })).toBe(false);
  });
  it("leaves a non-EQUIV verdict alone at ANY version: it carries no side or price to correct", () => {
    expect(needsDetRederive({ detVerdict: "NO_EVENT_MATCH" })).toBe(false);
    expect(needsDetRederive({ detVerdict: "OTHER_CLASS", detVersion: 1 })).toBe(false);
  });
});

describe("restampEntry", () => {
  const prev = { detTicker: "KXNCAAMBSPREAD-26NOV19HOUKU-KU2", detOurSideIsYes: true, detEntry: 0.42 };

  it("a first stamp takes the resolver's price, exactly as before this module", () => {
    expect(restampEntry({}, { ticker: "T", ourSideIsYes: true }, true, 0.42))
      .toEqual({ detEntry: 0.42, cleared: false, note: null });
  });
  it("a re-derivation NEVER takes a fresh price (a quote today is not the entry)", () => {
    expect(restampEntry(prev, { ticker: prev.detTicker, ourSideIsYes: true }, false, 0.99))
      .toEqual({ detEntry: 0.42, cleared: false, note: null });
  });
  it("clears an entry when the SIDE flips — it priced the position we did not hold", () => {
    const p = restampEntry(prev, { ticker: prev.detTicker, ourSideIsYes: false }, false, 0.11);
    expect(p.detEntry).toBeNull();
    expect(p.cleared).toBe(true);
    expect(p.note).toContain("side changed");
  });
  it("clears an entry when the CONTRACT changes even though the side did not", () => {
    const p = restampEntry(prev, { ticker: "KXNCAAMBSPREAD-26NOV19HOUKU-HOU2", ourSideIsYes: true }, false, null);
    expect(p.cleared).toBe(true);
    expect(p.note).toContain("contract changed");
  });
  it("reports cleared=false when the flipped stamp had no entry to lose", () => {
    const p = restampEntry({ ...prev, detEntry: null }, { ticker: prev.detTicker, ourSideIsYes: false }, false, null);
    expect(p).toMatchObject({ detEntry: null, cleared: false });
  });
  it("treats an unknown stored side as a change from a known one (never silently equal)", () => {
    const p = restampEntry({ ...prev, detOurSideIsYes: null }, { ticker: prev.detTicker, ourSideIsYes: true }, false, null);
    expect(p.cleared).toBe(true);
  });
});

describe("venueReadStale", () => {
  it("flags a settlement read cached under a contract the stamp no longer names", () => {
    // the UFC pair: both legs were stamped with the OTHER fighter's ticker, so the stored
    // result was a settlement of a market we never held
    expect(venueReadStale("KXUFCFIGHT-26NOV21CANALI-ALI", "KXUFCFIGHT-26NOV21CANALI-CAN")).toBe(true);
  });
  it("does not flag a read about the same contract", () => {
    expect(venueReadStale("T", "T")).toBe(false);
  });
  it("does not flag when either side is unknown — absence is not staleness", () => {
    expect(venueReadStale(null, "T")).toBe(false);
    expect(venueReadStale("T", undefined)).toBe(false);
  });
});
