import { describe, it, expect } from "vitest";
import {
  clobWsProvenance,
  gammaProvenance,
  laggedDataApiProvenance,
  mergeQualityFlags,
  provenanceNote,
  QUALITY_FLAG_LAGGED,
  QUALITY_FLAG_LIVE_MISNOMER,
  withProvenance,
} from "../src/lib/provenance";

/**
 * Provenance labels (audit §P1 — doctrine ported from polyterm's
 * api/data_api_lag.py). The invariants that matter:
 *  1. a Data-API row is ALWAYS marked lagged, and the lagged flag comes first;
 *  2. the `live_data_api_trades` misnomer can never survive a merge;
 *  3. no label invents a lag DURATION (we do not know it, so we do not claim it);
 *  4. stamping is additive — it must not mutate or drop the row's own fields.
 */
describe("provenance labels", () => {
  it("marks Data-API reads lagged with the lagged flag first", () => {
    const p = laggedDataApiProvenance(["positions"]);
    expect(p.source).toBe("data-api");
    expect(p.lagged).toBe(true);
    expect(p.qualityFlags[0]).toBe(QUALITY_FLAG_LAGGED);
    expect(p.qualityFlags).toContain("positions");
  });

  it("does not mark Gamma or CLOB-WS reads as lagged", () => {
    expect(gammaProvenance().lagged).toBe(false);
    expect(clobWsProvenance().lagged).toBe(false);
    expect(gammaProvenance().qualityFlags).not.toContain(QUALITY_FLAG_LAGGED);
  });

  it("drops the live-CLOB misnomer and dedupes while keeping order", () => {
    const merged = mergeQualityFlags(["alpha", QUALITY_FLAG_LIVE_MISNOMER, "beta", "alpha"], ["gamma", "beta"]);
    expect(merged).not.toContain(QUALITY_FLAG_LIVE_MISNOMER);
    expect(merged[0]).toBe(QUALITY_FLAG_LAGGED);
    expect(merged.slice(1)).toEqual(["alpha", "beta", "gamma"]);
  });

  it("omits the lagged flag first when not lagged", () => {
    const merged = mergeQualityFlags(["x"], [], false);
    expect(merged).toEqual(["x"]);
  });

  it("never states a lag duration anywhere in the label", () => {
    // The source doctrine's whole point: an unknown lag must stay unknown. A
    // digit in the note would be a fabricated measurement.
    const note = provenanceNote(laggedDataApiProvenance(["activity_endpoint"]));
    expect(note).toContain("data-api");
    expect(note).toMatch(/lagged/);
    expect(note).not.toMatch(/\d/);
    expect(provenanceNote(gammaProvenance())).toContain("live");
  });

  it("stamps additively without mutating the row", () => {
    const row = { marketId: "m1", size: 12, nested: { a: 1 } };
    const stamped = withProvenance(row, laggedDataApiProvenance());
    expect(stamped.marketId).toBe("m1");
    expect(stamped.size).toBe(12);
    expect(stamped.nested).toEqual({ a: 1 });
    expect(stamped.provenance.lagged).toBe(true);
    // original untouched
    expect(Object.keys(row)).toEqual(["marketId", "size", "nested"]);
  });
});
