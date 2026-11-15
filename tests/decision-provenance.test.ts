/**
 * Tests for decision provenance (card `data2-per-decision-provenance`).
 *
 * The properties worth pinning are the ones a mistake would hide: that a horizon
 * price can never be read from a print AFTER the horizon (look-ahead), that a
 * settlement mark at 0 or 1 is refused rather than recorded as a certainty, that a
 * thin tape yields NULL with a reason instead of a stale number, and that an
 * out-of-range venue price is dropped rather than clamped into a plausible one.
 */

import { describe, it, expect } from "vitest";
import {
  ALREADY_DECIDED_PRICE,
  decisionProvenanceFields,
  HORIZON_MAX_STALENESS_MS,
  horizonReads,
  isAlreadyDecided,
  parsePricesHistory,
  pickHorizonPrice,
} from "../src/lib/decision-provenance";

const T0 = Date.parse("2026-11-01T00:00:00Z");
const S = (offsetSec: number) => T0 / 1000 + offsetSec;

describe("parsePricesHistory", () => {
  it("keeps valid points and sorts them by time", () => {
    const pts = parsePricesHistory({ history: [{ t: S(60), p: 0.9 }, { t: S(0), p: 0.1 }] });
    expect(pts.map((p) => p.p)).toEqual([0.1, 0.9]);
  });

  it("drops out-of-range and non-finite prices instead of clamping them", () => {
    const pts = parsePricesHistory({
      history: [
        { t: S(0), p: 1.4 },
        { t: S(1), p: -0.2 },
        { t: S(2), p: Number.NaN },
        { t: S(3), p: 0.5 },
      ],
    });
    expect(pts).toEqual([{ t: S(3), p: 0.5 }]);
  });

  it("returns [] for a payload it cannot read", () => {
    expect(parsePricesHistory(null)).toEqual([]);
    expect(parsePricesHistory({})).toEqual([]);
    expect(parsePricesHistory({ history: "nope" })).toEqual([]);
  });
});

describe("pickHorizonPrice", () => {
  const tape = [
    { t: S(0), p: 0.4 },
    { t: S(3600), p: 0.55 },
    { t: S(4 * 3600), p: 0.6 },
  ];

  it("takes the last print at or BEFORE the horizon", () => {
    const r = pickHorizonPrice(tape, T0 + 3600_000);
    expect(r).toEqual({ price: 0.55, atMs: T0 + 3600_000, reason: "ok" });
  });

  it("never reads a print after the horizon (no look-ahead)", () => {
    const r = pickHorizonPrice(tape, T0 + 2 * 3_600_000);
    expect(r.price).toBe(0.55); // 0.6 lands at +4h and is not available at +2h
    expect(r.atMs).toBe(T0 + 3600_000);
  });

  it("refuses a print older than the staleness tolerance", () => {
    const r = pickHorizonPrice([{ t: S(0), p: 0.5 }], T0 + HORIZON_MAX_STALENESS_MS + 1000);
    expect(r).toEqual({ price: null, atMs: T0, reason: "stale" });
  });

  it("refuses a settlement print at exactly 0 or 1", () => {
    expect(pickHorizonPrice([{ t: S(3600), p: 1 }], T0 + 3600_000).reason).toBe("terminal_print");
    expect(pickHorizonPrice([{ t: S(3600), p: 0 }], T0 + 3600_000).reason).toBe("terminal_print");
    // ...but a near-certain market print is a real price and is kept.
    expect(pickHorizonPrice([{ t: S(3600), p: 0.9995 }], T0 + 3600_000).price).toBe(0.9995);
  });

  it("reports no_print when nothing exists at or before the horizon", () => {
    const r = pickHorizonPrice([{ t: S(60), p: 0.5 }], T0);
    expect(r).toEqual({ price: null, atMs: null, reason: "no_print" });
  });

  it("reports no_path on an empty tape", () => {
    expect(pickHorizonPrice([], T0).reason).toBe("no_path");
  });
});

describe("horizonReads", () => {
  it("prices all three horizons off one tape with one basis", () => {
    const pts = parsePricesHistory({
      history: [
        { t: S(3600), p: 0.5 },
        { t: S(6 * 3600), p: 0.7 },
        { t: S(24 * 3600), p: 0.9 },
      ],
    });
    const r = horizonReads(pts, T0);
    expect([r["1h"].price, r["6h"].price, r["24h"].price]).toEqual([0.5, 0.7, 0.9]);
  });

  it("does not let a settlement at the last horizon poison the earlier ones", () => {
    const pts = parsePricesHistory({
      history: [
        { t: S(3600), p: 0.5 },
        { t: S(24 * 3600), p: 1 },
      ],
    });
    const r = horizonReads(pts, T0);
    expect(r["1h"].price).toBe(0.5);
    expect(r["6h"].reason).toBe("stale"); // last print is 18h stale at +6h
    expect(r["24h"].reason).toBe("terminal_print");
  });
});

describe("isAlreadyDecided", () => {
  it("flags at the threshold and above", () => {
    expect(ALREADY_DECIDED_PRICE).toBe(0.995);
    expect(isAlreadyDecided(0.995)).toBe(true);
    expect(isAlreadyDecided(1)).toBe(true);
    expect(isAlreadyDecided(0.994)).toBe(false);
  });

  it("never flags a missing price", () => {
    expect(isAlreadyDecided(null)).toBe(false);
    expect(isAlreadyDecided(undefined)).toBe(false);
    expect(isAlreadyDecided(Number.NaN)).toBe(false);
  });
});

describe("decisionProvenanceFields (the write-site mapping)", () => {
  it("persists the scored price and the decided flag together", () => {
    expect(decisionProvenanceFields(0.42, undefined)).toEqual({
      priceAtDecision: 0.42,
      sentimentDelta: null,
      alreadyDecidedAtEntry: false,
    });
    expect(decisionProvenanceFields(0.998, 0.031)).toEqual({
      priceAtDecision: 0.998,
      sentimentDelta: 0.031,
      alreadyDecidedAtEntry: true,
    });
  });

  it("keeps 'no evidence' distinct from 'zero evidence'", () => {
    expect(decisionProvenanceFields(0.5, undefined).sentimentDelta).toBeNull();
    expect(decisionProvenanceFields(0.5, 0).sentimentDelta).toBe(0);
  });

  it("never writes a non-finite price", () => {
    expect(decisionProvenanceFields(Number.NaN, 0.1).priceAtDecision).toBeNull();
    expect(decisionProvenanceFields(null, 0.1).alreadyDecidedAtEntry).toBe(false);
  });
});
