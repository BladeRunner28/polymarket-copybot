/**
 * Tests for research source supply (card `insidercat-source-audit`, 2026-11-15).
 *
 * The properties worth pinning are the ones whose failure would look like a
 * healthy feed: that the SAME bill re-read on four poll cycles counts as one
 * disclosure and not four; that two different members trading the same ticker on
 * the same day stay two; that an unparseable payload is never merged with
 * another unparseable payload; and that a set whose polarity never varies is
 * reported as a constant (share 1, one distinct value) rather than as evidence
 * with a direction.
 */

import { describe, it, expect } from "vitest";
import {
  dedupeByEvent,
  eventKeyFor,
  polarityConcentration,
  signedEvidence,
  supplyStats,
  type SupplyRow,
} from "../src/lib/research-source-supply";

const T = (iso: string) => new Date(iso);

const bill = (n: number, at: string, s = 0.5): SupplyRow => ({
  source: "congress_gov_api",
  sentimentScore: s,
  confidence: 0.7,
  processedAt: T(at),
  rawPayload: JSON.stringify({ type: "HR", number: String(n), title: "A bill" }),
});

const trade = (member: string, ticker: string, date: string, at: string): SupplyRow => ({
  source: "quiver_congress_trade",
  sentimentScore: -0.8,
  confidence: 0.85,
  processedAt: T(at),
  rawPayload: JSON.stringify({
    BioGuideID: member,
    TransactionDate: date,
    Ticker: ticker,
    Transaction: "Sale (Partial)",
  }),
});

describe("eventKeyFor — the identity of the disclosure", () => {
  it("keys a bill by type+number, not by poll cycle", () => {
    const a = JSON.stringify({ type: "S", number: "4557" });
    const b = JSON.stringify({ type: "S", number: "4557", updateDate: "2026-11-02" });
    expect(eventKeyFor("congress_gov_api", a)).toBe("bill:S4557");
    expect(eventKeyFor("congress_gov_api", b)).toBe("bill:S4557");
  });

  it("keys a congress trade by member+date+ticker+direction", () => {
    const k = eventKeyFor(
      "quiver_congress_trade",
      JSON.stringify({ BioGuideID: "W000802", TransactionDate: "2026-09-02", Ticker: "NVDA", Transaction: "Sale (Partial)" })
    );
    expect(k).toBe("trade:W000802|2026-09-02|NVDA|Sale (Partial)");
  });

  it("keys a Federal Register row by package, because one payload is a whole issue", () => {
    const k = eventKeyFor(
      "govinfo_fr_notice",
      JSON.stringify({ packageId: "FR-2026-11-10", docClass: "FR" })
    );
    expect(k).toBe("fr:FR-2026-11-10:FR");
  });

  it("falls back to the payload text for an unknown source, and never throws", () => {
    expect(eventKeyFor("mystery_feed", "not json")).toBe("raw:not json");
    expect(eventKeyFor("mystery_feed", JSON.stringify({ x: 1 }))).toBe('raw:{"x":1}');
    expect(eventKeyFor("mystery_feed", null)).toBe("raw:");
  });
});

describe("dedupeByEvent", () => {
  it("merges re-emissions of one bill and keeps the LATEST processedAt", () => {
    const rows = [bill(1, "2026-11-01T00:00:00Z"), bill(1, "2026-11-02T00:00:00Z"), bill(2, "2026-11-03T00:00:00Z")];
    const out = dedupeByEvent(rows);
    expect(out).toHaveLength(2);
    expect(out[0].processedAt.toISOString()).toBe("2026-11-02T00:00:00.000Z");
  });

  it("keeps two members trading the same ticker on the same day as two events", () => {
    const rows = [
      trade("A1", "NVDA", "2026-11-01", "2026-11-02T00:00:00Z"),
      trade("B2", "NVDA", "2026-11-01", "2026-11-02T00:00:00Z"),
    ];
    expect(dedupeByEvent(rows)).toHaveLength(2);
  });

  it("does not merge two unparseable payloads into one", () => {
    const rows: SupplyRow[] = [
      { source: "congress_gov_api", sentimentScore: 0.5, confidence: 0.7, processedAt: T("2026-11-01T00:00:00Z"), rawPayload: "not json" },
      { source: "congress_gov_api", sentimentScore: 0.5, confidence: 0.7, processedAt: T("2026-11-02T00:00:00Z"), rawPayload: "also not json" },
    ];
    expect(dedupeByEvent(rows)).toHaveLength(2);
  });

  it("returns events in ascending processedAt order", () => {
    const out = dedupeByEvent([bill(2, "2026-11-03T00:00:00Z"), bill(1, "2026-11-01T00:00:00Z")]);
    expect(out.map((r) => r.processedAt.toISOString())).toEqual([
      "2026-11-01T00:00:00.000Z",
      "2026-11-03T00:00:00.000Z",
    ]);
  });
});

describe("polarityConcentration", () => {
  it("reports a constant set as one distinct value at share 1", () => {
    const c = polarityConcentration([bill(1, "2026-11-01T00:00:00Z"), bill(2, "2026-11-02T00:00:00Z")]);
    expect(c.modal).toBe(0.5);
    expect(c.modalShare).toBe(1);
    expect(c.distinctValues).toBe(1);
    expect(c.opinionatedRows).toBe(2);
  });

  it("reports a mixed set honestly (share < 1, both values counted)", () => {
    const c = polarityConcentration([
      bill(1, "2026-11-01T00:00:00Z", 0.5),
      bill(2, "2026-11-01T00:00:00Z", -0.5),
      bill(3, "2026-11-01T00:00:00Z", -0.5),
    ]);
    expect(c.distinctValues).toBe(2);
    expect(c.modal).toBe(-0.5);
    expect(c.modalShare).toBeCloseTo(2 / 3, 10);
  });

  it("counts neutrals as rows but not as opinionated", () => {
    const c = polarityConcentration([
      bill(1, "2026-11-01T00:00:00Z", 0),
      bill(2, "2026-11-01T00:00:00Z", 0),
      bill(3, "2026-11-01T00:00:00Z", 0.1),
    ]);
    expect(c.opinionatedRows).toBe(0);
    expect(c.modal).toBe(0);
  });

  it("is deterministic on an exact tie (breaks toward the larger |polarity|)", () => {
    const c = polarityConcentration([
      bill(1, "2026-11-01T00:00:00Z", 0.3),
      bill(2, "2026-11-01T00:00:00Z", -0.5),
    ]);
    expect(c.modal).toBe(-0.5);
    expect(c.modalShare).toBe(0.5);
  });

  it("returns an empty reading for an empty set instead of dividing by zero", () => {
    expect(polarityConcentration([])).toEqual({ modal: 0, modalShare: 0, distinctValues: 0, opinionatedRows: 0 });
  });
});

describe("supplyStats", () => {
  it("carries the re-emission factor and counts opinionated on BOTH bases", () => {
    const rows = [bill(1, "2026-11-01T00:00:00Z"), bill(1, "2026-11-02T00:00:00Z"), bill(2, "2026-11-03T00:00:00Z")];
    const [s] = supplyStats(rows);
    expect(s.rows).toBe(3);
    expect(s.distinctEvents).toBe(2);
    expect(s.reEmission).toBeCloseTo(1.5, 10);
    expect(s.opinionatedRows).toBe(3);
    expect(s.opinionatedEvents).toBe(2);
    expect(s.firstEmit).toBe("2026-11-01T00:00:00.000Z");
    expect(s.lastEmit).toBe("2026-11-03T00:00:00.000Z");
  });

  it("groups by source and orders by row count", () => {
    const rows = [
      ...Array.from({ length: 4 }, (_, i) => bill(i + 1, `2026-11-0${i + 1}T00:00:00Z`)),
      trade("A1", "NVDA", "2026-11-01", "2026-11-02T00:00:00Z"),
    ];
    const stats = supplyStats(rows);
    expect(stats.map((s) => s.source)).toEqual(["congress_gov_api", "quiver_congress_trade"]);
    expect(stats[0].rows).toBe(4);
    expect(stats[1].distinctEvents).toBe(1);
  });

  it("marks a single-polarity source per source, which is the level the aggregation runs at", () => {
    const [s] = supplyStats([bill(1, "2026-11-01T00:00:00Z"), bill(2, "2026-11-02T00:00:00Z")]);
    expect(s.distinctValues).toBe(1);
  });
});

/**
 * `signedEvidence` — the filter the LIVE aggregation would read its evidence
 * through (card `sentiment-edge-single-polarity`). The failure this pins is not
 * "no rows": it is a large, healthy-looking set whose polarity was assigned per
 * CATEGORY, so every row agrees and the resulting edge can only tilt the category.
 */
describe("signedEvidence (single-polarity exclusion)", () => {
  it("drops a source whose polarity is one value across DIFFERENT disclosures", () => {
    // Two distinct bills, same polarity — dedupe does not merge them, so the only
    // reason this set is empty is the constancy test.
    expect(signedEvidence([bill(1, "2026-11-01T00:00:00Z"), bill(2, "2026-11-02T00:00:00Z")])).toEqual(
      []
    );
  });

  it("keeps a source that varies across disclosures and drops the constant one beside it", () => {
    const rows = [
      bill(1, "2026-11-01T00:00:00Z"),
      bill(2, "2026-11-02T00:00:00Z"),
      trade("A1", "NVDA", "2026-11-01", "2026-11-02T00:00:00Z"),
      { ...trade("B2", "NVDA", "2026-11-01", "2026-11-03T00:00:00Z"), sentimentScore: 0.6 },
    ];
    const kept = signedEvidence(rows);
    expect(kept.map((r) => r.source)).toEqual(["quiver_congress_trade", "quiver_congress_trade"]);
  });

  it("collapses re-emissions of one bill before the constancy test", () => {
    const rows = Array.from({ length: 5 }, (_, i) => bill(7, `2026-11-0${i + 1}T00:00:00Z`));
    expect(dedupeByEvent(rows)).toHaveLength(1);
    expect(signedEvidence(rows)).toEqual([]);
  });

  it("implies the variance gate: a non-empty result always holds >= 2 distinct polarities", () => {
    const rows = [
      bill(1, "2026-11-01T00:00:00Z"),
      bill(2, "2026-11-02T00:00:00Z"),
      trade("A1", "NVDA", "2026-11-01", "2026-11-02T00:00:00Z"),
      { ...trade("B2", "NVDA", "2026-11-01", "2026-11-03T00:00:00Z"), sentimentScore: 0.6 },
    ];
    const kept = signedEvidence(rows);
    expect(kept.length).toBeGreaterThan(0);
    expect(polarityConcentration(kept).distinctValues).toBeGreaterThanOrEqual(2);
  });

  it("never merges two unparseable payloads to manufacture a constant", () => {
    const rows: SupplyRow[] = [
      { ...bill(1, "2026-11-01T00:00:00Z"), rawPayload: "not json" },
      { ...bill(2, "2026-11-01T00:00:00Z"), rawPayload: "also not json", sentimentScore: -0.5 },
    ];
    expect(signedEvidence(rows)).toHaveLength(2);
  });
});
