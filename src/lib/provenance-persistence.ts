/**
 * provenance-persistence — the DataProvenance stamp, made durable.
 *
 * 2026-11-09 (Lane B, instrument repair; card `polyterm-p1-provenance-persistence`).
 *
 * WHY. `src/lib/provenance.ts` labels every read of the LAGGED `data-api` surfaces
 * ("lagged — not the live CLOB fill tape") and every consumer is supposed to carry it.
 * But the label lived only in memory: `prisma/schema.prisma` had no provenance column, so
 * the moment the monitor wrote an ObservedTrade the row became indistinguishable from a
 * print off the live CLOB tape. The card's complaint is exact — the C-200 print-through
 * work was described as "auditable", and it was not.
 *
 * WHAT THIS DOES. Two pure halves, no IO:
 *   toProvenanceColumns()   — the shape written at ingest (NULL when a row arrives unstamped,
 *                             which is a real observation and must not be papered over);
 *   readProvenanceColumns() — the shape read back, returning null for a row that carries no
 *                             stamp OR whose flag blob does not parse. A corrupt stamp is
 *                             NOT silently downgraded to "unlabelled but fine": the coverage
 *                             verdict counts it RED, because a stamp nobody can read is the
 *                             same defect this module exists to end.
 *   summarizeCoverage() / coverageVerdict() — the epoch rule: rows written BEFORE the first
 *                             stamped row are legacy (NULL is honest); rows written AT OR
 *                             AFTER it must carry a stamp, because every writer since then
 *                             runs this code. That is what makes the label a guarantee
 *                             going forward instead of a hope.
 *
 * HARD RULE inherited from provenance.ts: never invent a lag DURATION. Nothing here stores
 * or implies one. The columns record WHICH surface and WHICH flags; "how late" stays unknown.
 */

import type { DataProvenance } from "./provenance";

/** The three nullable columns on ObservedTrade that carry the stamp. */
export interface ProvenanceColumns {
  provenanceSource: string | null;
  provenanceLagged: boolean | null;
  provenanceFlags: string | null;
}

/** Column values for a row with no stamp (legacy row, or a reader that had none). */
export function emptyProvenanceColumns(): ProvenanceColumns {
  return { provenanceSource: null, provenanceLagged: null, provenanceFlags: null };
}

/**
 * Convert an in-memory stamp into column values. `undefined`/`null` in = all-NULL out:
 * an unstamped write is recorded as unstamped, never defaulted to "live".
 */
export function toProvenanceColumns(provenance?: DataProvenance | null): ProvenanceColumns {
  if (!provenance || !provenance.source) return emptyProvenanceColumns();
  const flags = provenance.qualityFlags ?? [];
  return {
    provenanceSource: provenance.source,
    provenanceLagged: provenance.lagged === true,
    provenanceFlags: flags.length > 0 ? JSON.stringify(flags) : null,
  };
}

export interface ProvenanceColumnRow {
  provenanceSource?: string | null;
  provenanceLagged?: boolean | null;
  provenanceFlags?: string | null;
}

/**
 * Read the stamp back. Returns null when the row is unstamped, when the source is blank,
 * or when the flags blob does not parse as an array — "cannot read the label" is reported
 * as no label rather than as a clean one.
 */
export function readProvenanceColumns(row: ProvenanceColumnRow): DataProvenance | null {
  const source = (row.provenanceSource ?? "").trim();
  if (!source) return null;
  let flags: string[] = [];
  if (row.provenanceFlags != null && row.provenanceFlags !== "") {
    try {
      const parsed: unknown = JSON.parse(row.provenanceFlags);
      if (!Array.isArray(parsed)) return null;
      flags = parsed.map((f) => String(f));
    } catch {
      return null;
    }
  }
  return { source, lagged: row.provenanceLagged === true, qualityFlags: flags };
}

/** One row as the coverage check sees it. */
export interface StampObservation {
  /** Row clock used for the epoch rule — ObservedTrade.createdAt (ingest time). */
  at: Date;
  /** True when the row parses to a readable stamp. */
  stamped: boolean;
}

export interface CoverageFrame {
  total: number;
  stamped: number;
  unstamped: number;
  /** Earliest stamped row — the epoch. Null when nothing is stamped yet. */
  epoch: Date | null;
  /** Latest unstamped row, for showing how far the gap runs. */
  lastUnstampedAt: Date | null;
  /** Rows AT OR AFTER the epoch with no readable stamp: the regression signal. */
  unstampedAtOrAfterEpoch: number;
}

/** Aggregate the epoch rule over a set of observations. Pure; order-independent. */
export function summarizeCoverage(rows: readonly StampObservation[]): CoverageFrame {
  let stamped = 0;
  let epoch: Date | null = null;
  let lastUnstampedAt: Date | null = null;
  for (const r of rows) {
    if (r.stamped) {
      stamped += 1;
      if (epoch === null || r.at.getTime() < epoch.getTime()) epoch = r.at;
    } else if (lastUnstampedAt === null || r.at.getTime() > lastUnstampedAt.getTime()) {
      lastUnstampedAt = r.at;
    }
  }
  let unstampedAtOrAfterEpoch = 0;
  if (epoch !== null) {
    const e = epoch.getTime();
    for (const r of rows) {
      if (!r.stamped && r.at.getTime() >= e) unstampedAtOrAfterEpoch += 1;
    }
  }
  return {
    total: rows.length,
    stamped,
    unstamped: rows.length - stamped,
    epoch,
    lastUnstampedAt,
    unstampedAtOrAfterEpoch,
  };
}

/**
 * The verdict. RED when nothing is stamped (the columns are wired but nothing writes them,
 * which is exactly the state this card shipped to end), or when ANY row at/after the epoch
 * is unstamped (a writer bypassing the ingest path, or stale code in a cron slot).
 */
export function coverageVerdict(f: CoverageFrame): { ok: boolean; reason: string } {
  if (f.total === 0) return { ok: false, reason: "no rows in scope — cannot verify persistence" };
  if (f.epoch === null) return { ok: false, reason: "RED: 0 of " + f.total + " rows carry a readable stamp — the columns are not being written" };
  if (f.unstampedAtOrAfterEpoch > 0) {
    return {
      ok: false,
      reason:
        "RED: " +
        f.unstampedAtOrAfterEpoch +
        " row(s) at/after the epoch (" +
        f.epoch.toISOString() +
        ") carry no readable stamp — an ingest path bypasses the stamp",
    };
  }
  return { ok: true, reason: "OK: every row at/after the epoch carries a readable stamp; " + f.unstamped + " pre-epoch row(s) in scope are legacy NULL by design" };
}
