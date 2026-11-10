import { describe, it, expect } from "vitest";
import {
  coverageVerdict,
  emptyProvenanceColumns,
  readProvenanceColumns,
  summarizeCoverage,
  toProvenanceColumns,
  type StampObservation,
} from "../src/lib/provenance-persistence";
import { laggedDataApiProvenance, gammaProvenance } from "../src/lib/provenance";

/**
 * Provenance persistence (card `polyterm-p1-provenance-persistence`).
 *
 * The defect this guards is not arithmetic — it is a claim: "the stamp travels with the
 * row". So every test here is about the label being READABLE, never about a lag duration
 * (there is none, by doctrine). The coverage verdict is pinned in BOTH directions: a frame
 * with a post-epoch unstamped row must go RED, otherwise the check can never catch the
 * regression it exists for.
 */

const at = (iso: string) => new Date(iso);

describe("column round-trip", () => {
  it("persists a lagged data-api stamp without inventing a duration", () => {
    const cols = toProvenanceColumns(laggedDataApiProvenance(["activity_endpoint", "short_window"]));
    expect(cols.provenanceSource).toBe("data-api");
    expect(cols.provenanceLagged).toBe(true);
    expect(JSON.parse(cols.provenanceFlags as string)).toEqual(["lagged_data_api", "activity_endpoint", "short_window"]);
    const back = readProvenanceColumns(cols);
    expect(back).toEqual({ source: "data-api", lagged: true, qualityFlags: ["lagged_data_api", "activity_endpoint", "short_window"] });
  });

  it("records a live (non-lagged) surface as lagged=false, not NULL", () => {
    const cols = toProvenanceColumns(gammaProvenance(["slug_endpoint"]));
    expect(cols.provenanceSource).toBe("gamma");
    expect(cols.provenanceLagged).toBe(false);
    expect(readProvenanceColumns(cols)).toEqual({ source: "gamma", lagged: false, qualityFlags: ["slug_endpoint"] });
  });

  it("writes all-NULL for an unstamped row instead of defaulting it to live", () => {
    expect(toProvenanceColumns(undefined)).toEqual(emptyProvenanceColumns());
    expect(toProvenanceColumns(null)).toEqual({ provenanceSource: null, provenanceLagged: null, provenanceFlags: null });
  });

  it("a row with no source reads back as unstamped", () => {
    expect(readProvenanceColumns({ provenanceSource: null, provenanceLagged: null, provenanceFlags: null })).toBeNull();
    expect(readProvenanceColumns({ provenanceSource: "   " })).toBeNull();
  });

  it("an unparsable or non-array flag blob reads as unstamped (corrupt is not clean)", () => {
    expect(readProvenanceColumns({ provenanceSource: "data-api", provenanceFlags: "{not json" })).toBeNull();
    expect(readProvenanceColumns({ provenanceSource: "data-api", provenanceFlags: '{"a":1}' })).toBeNull();
    // no flags at all is legitimate: the source alone is a usable label
    expect(readProvenanceColumns({ provenanceSource: "data-api", provenanceLagged: true })).toEqual({
      source: "data-api",
      lagged: true,
      qualityFlags: [],
    });
  });
});

describe("epoch coverage rule", () => {
  const frame = (rows: StampObservation[]) => summarizeCoverage(rows);

  it("legacy rows before the epoch are NULL by design, not a regression", () => {
    const f = frame([
      { at: at("2026-06-18T13:00:00Z"), stamped: false },
      { at: at("2026-11-09T23:00:00Z"), stamped: true },
      { at: at("2026-11-10T00:30:00Z"), stamped: true },
    ]);
    expect(f.total).toBe(3);
    expect(f.stamped).toBe(2);
    expect(f.epoch?.toISOString()).toBe("2026-11-09T23:00:00.000Z");
    expect(f.lastUnstampedAt?.toISOString()).toBe("2026-06-18T13:00:00.000Z");
    expect(f.unstampedAtOrAfterEpoch).toBe(0);
    expect(coverageVerdict(f).ok).toBe(true);
  });

  it("NEGATIVE CONTROL: one unstamped row at the epoch turns the verdict RED", () => {
    const clean = frame([
      { at: at("2026-11-10T00:00:00Z"), stamped: true },
      { at: at("2026-11-10T01:00:00Z"), stamped: true },
    ]);
    expect(coverageVerdict(clean).ok).toBe(true);
    const dirty = frame([
      { at: at("2026-11-10T00:00:00Z"), stamped: true },
      { at: at("2026-11-10T00:00:00Z"), stamped: false }, // same instant counts as AT the epoch
    ]);
    const v = coverageVerdict(dirty);
    expect(v.ok).toBe(false);
    expect(v.reason).toContain("RED");
    expect(dirty.unstampedAtOrAfterEpoch).toBe(1);
  });

  it("nothing stamped at all is RED — the wired-but-unwritten state the card shipped from", () => {
    const v = coverageVerdict(frame([{ at: at("2026-11-10T00:00:00Z"), stamped: false }]));
    expect(v.ok).toBe(false);
    expect(v.reason).toContain("0 of 1");
  });

  it("an empty scope is RED, not vacuously green", () => {
    expect(coverageVerdict(frame([])).ok).toBe(false);
  });

  it("counts are order-independent", () => {
    const rows: StampObservation[] = [
      { at: at("2026-11-10T02:00:00Z"), stamped: true },
      { at: at("2026-11-09T00:00:00Z"), stamped: false },
      { at: at("2026-11-10T03:00:00Z"), stamped: false },
    ];
    const fwd = summarizeCoverage(rows);
    const rev = summarizeCoverage([...rows].reverse());
    expect(fwd).toEqual(rev);
    expect(fwd.unstampedAtOrAfterEpoch).toBe(1);
    expect(fwd.lastUnstampedAt?.toISOString()).toBe("2026-11-10T03:00:00.000Z");
  });
});
