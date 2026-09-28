/**
 * Data-provenance labels for venue reads.
 *
 * Ported doctrine (NOT code): polyterm's `api/data_api_lag.py` — see
 * drafts/polyterm-audit-2026-09-28.md §P1. MIT-licensed source, reimplemented
 * here in our own types and naming.
 *
 * WHY: `data-api.polymarket.com` wallet/positions/activity/trades surfaces are
 * LAGGED relative to the CLOB fill tape. Code that reads them and calls the
 * result "live" is wrong in a way that is invisible in the numbers: every
 * consumer downstream (win rate, PnL, print-through) inherits the error without
 * the payload ever saying so.
 *
 * HARD RULE (inherited): never invent a lag DURATION. We do not know how long
 * the lag is, so no label claims one. A fabricated number here would be worse
 * than no number — it would make an unknown look measured.
 *
 * This module is pure and has no IO, so it can be applied at any boundary
 * (adapter rows, script output, JSONL appends) without pulling in a client.
 */

/** Source tag for the lagged public wallet/positions/activity surfaces. */
export const SOURCE_DATA_API = "data-api" as const;
/** Source tag for the CLOB WebSocket book/quote stream (the live tape we record). */
export const SOURCE_CLOB_WS = "clob-ws" as const;
/** Source tag for Gamma market metadata (reference data, not a fill tape). */
export const SOURCE_GAMMA = "gamma" as const;

/** Quality flag attached to every payload read from the lagged Data API. */
export const QUALITY_FLAG_LAGGED = "lagged_data_api" as const;
/**
 * A misnomer we never want to emit: the Data API is not the live CLOB tape.
 * Dropped wherever flags are merged, per the source doctrine.
 */
export const QUALITY_FLAG_LIVE_MISNOMER = "live_data_api_trades" as const;

export type DataProvenance = {
  /** Which surface this row came from. */
  source: string;
  /** True when the source is known to lag the live tape. */
  lagged: boolean;
  /** Deduped, ordered labels describing the read (no duration claims). */
  qualityFlags: string[];
};

/**
 * Merge quality flags: strip the live-CLOB misnomer, dedupe, and put the lagged
 * marker first when the payload is lagged. Order is stable so JSONL diffs stay
 * readable.
 */
export function mergeQualityFlags(existing: readonly string[] = [], extra: readonly string[] = [], lagged = true): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  const push = (f: string) => {
    if (!f || f === QUALITY_FLAG_LIVE_MISNOMER || seen.has(f)) return;
    seen.add(f);
    out.push(f);
  };
  if (lagged) push(QUALITY_FLAG_LAGGED);
  for (const f of existing) push(f);
  for (const f of extra) push(f);
  return out;
}

/** Provenance for a row read from the lagged Data API. */
export function laggedDataApiProvenance(extra: readonly string[] = []): DataProvenance {
  return {
    source: SOURCE_DATA_API,
    lagged: true,
    qualityFlags: mergeQualityFlags([], extra, true),
  };
}

/** Provenance for reference market metadata read from Gamma. */
export function gammaProvenance(extra: readonly string[] = []): DataProvenance {
  return {
    source: SOURCE_GAMMA,
    lagged: false,
    qualityFlags: mergeQualityFlags([], extra, false),
  };
}

/** Provenance for data ingested from the CLOB WebSocket stream. */
export function clobWsProvenance(extra: readonly string[] = []): DataProvenance {
  return {
    source: SOURCE_CLOB_WS,
    lagged: false,
    qualityFlags: mergeQualityFlags([], extra, false),
  };
}

/**
 * Attach provenance to a row without touching its existing fields — the label
 * is additive, so no existing consumer changes behaviour.
 */
export function withProvenance<T extends object>(row: T, provenance: DataProvenance): T & { provenance: DataProvenance } {
  return { ...row, provenance };
}

/** Human-readable one-liner for logs/reports. Never states a duration. */
export function provenanceNote(provenance: DataProvenance): string {
  return `${provenance.source}${provenance.lagged ? " (lagged — not the live CLOB fill tape)" : " (live)"}`;
}
