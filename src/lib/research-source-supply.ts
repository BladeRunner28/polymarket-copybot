/**
 * Research source supply — how much DISTINCT evidence a RegulatorySignal set
 * actually carries, and whether its polarity can carry a sign at all.
 *
 * Card `insidercat-source-audit` (2026-11-15). The layer's headline number —
 * "N opinionated signals in the 7d window" — is a ROW count. A row is written
 * every time a poller re-reads a document it already saw, and for the bill
 * poller the polarity is a per-category constant assigned by a keyword table
 * (a default, not a judgement). So the row count can be large while the
 * distinct-event count is small and the polarity variance is zero. This module
 * supplies the three primitives that separate those readings, so no caller can
 * print n without also being able to print what n is made of:
 *
 *   eventKeyFor(rows)           — the identity of the underlying disclosure
 *   dedupeByEvent(rows)         — one row per identity (latest processedAt wins)
 *   polarityConcentration(rows) — modal polarity + its share, i.e. "can this
 *                                 source express more than one direction?"
 *
 * Pure functions only: no DB, no clock. The script
 * `scripts/research-source-supply-read.ts` reads the table and prints the arms;
 * this module is what makes those arms testable.
 */

/** The RegulatorySignal fields this module needs. */
export interface SupplyRow {
  source: string;
  sentimentScore: number;
  confidence: number;
  processedAt: Date;
  rawPayload?: string | null;
}

export interface PolarityConcentration {
  /** The most common polarity value in the set. */
  modal: number;
  /** Share of rows carrying `modal` polarity (0..1). */
  modalShare: number;
  /** How many distinct polarity values appear at all. */
  distinctValues: number;
  /** Rows whose |polarity| >= the opinionated threshold. */
  opinionatedRows: number;
}

export interface SupplyStats extends PolarityConcentration {
  source: string;
  rows: number;
  distinctEvents: number;
  /** rows / distinctEvents — how many times each event was re-emitted. */
  reEmission: number;
  opinionatedEvents: number;
  firstEmit: string | null;
  lastEmit: string | null;
}

export const DEFAULT_OPINIONATED_THRESHOLD = 0.3;

function parsePayload(raw: string | null | undefined): Record<string, unknown> | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw);
    return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function str(v: unknown): string {
  return typeof v === "string" || typeof v === "number" ? String(v) : "";
}

/**
 * The identity of the disclosure behind a row. Deliberately per-source, because
 * "the same evidence" means something different in each feed:
 *
 *   congress_gov_api      a BILL (type + number) — the poller re-reads the same
 *                         5 most-recently-updated bills every cycle
 *   quiver_congress_trade a disclosed transaction (member + traded date + ticker
 *                         + direction); the same filing reappears across polls
 *   govinfo_fr_notice     a Federal Register PACKAGE (packageId) — the payload is
 *                         a whole daily issue, so per-row identity is per-issue
 *   anything else         the exact payload text (conservative: if we cannot name
 *                         the identity we do not merge two rows)
 *
 * A row whose payload cannot be parsed is keyed by its own text, so an
 * unparseable feed is reported as un-de-duplicable rather than silently merged.
 */
export function eventKeyFor(source: string, rawPayload: string | null | undefined): string {
  const p = parsePayload(rawPayload);
  if (!p) return `raw:${rawPayload ?? ""}`;

  switch (source) {
    case "congress_gov_api": {
      const type = str(p.type);
      const number = str(p.number);
      if (type || number) return `bill:${type}${number}`;
      return `raw:${rawPayload}`;
    }
    case "quiver_congress_trade": {
      const key = [str(p.BioGuideID), str(p.TransactionDate), str(p.Ticker), str(p.Transaction)]
        .filter((s) => s.length > 0)
        .join("|");
      return key.length > 0 ? `trade:${key}` : `raw:${rawPayload}`;
    }
    case "govinfo_fr_notice": {
      const pkg = str(p.packageId);
      const docClass = str(p.docClass);
      if (pkg) return `fr:${pkg}:${docClass}`;
      return `raw:${rawPayload}`;
    }
    default:
      return `raw:${rawPayload}`;
  }
}

/** One row per distinct event: the LATEST processedAt wins (the date the evidence was last claimed). */
export function dedupeByEvent<T extends SupplyRow>(rows: T[]): T[] {
  const kept = new Map<string, T>();
  for (const r of rows) {
    const key = eventKeyFor(r.source, r.rawPayload);
    const prev = kept.get(key);
    if (!prev || r.processedAt.getTime() > prev.processedAt.getTime()) kept.set(key, r);
  }
  return [...kept.values()].sort((a, b) => a.processedAt.getTime() - b.processedAt.getTime());
}

/**
 * THE EVIDENCE A CONSTANT POLARITY CANNOT SUPPLY (card
 * `sentiment-edge-single-polarity`, 2026-11-16).
 *
 * One row per distinct disclosure, minus every source whose polarity is a SINGLE
 * value within this set. A source that can only ever print one number has no
 * direction to contribute: whatever it adds to a posterior is a template default,
 * and because it is the same for every market in the category it can only tilt
 * the whole category, never distinguish one leg from another.
 *
 * Measured on the live feed (2026-11-16): Macro/Politics is 119 rows / 35
 * disclosures, 100% +0.50; Tech/AI is 6 rows / 1 disclosure, 100% +0.80. Both are
 * dropped here, so `signedEvidence` returns empty and the caller must emit no
 * edge at all.
 *
 * Two properties worth keeping straight:
 *   - The variance gate is IMPLIED, not added: every surviving source holds >= 2
 *     distinct values, so a non-empty result always holds >= 2 distinct values.
 *     There is no extra condition to write, and none to get wrong.
 *   - Dedupe is NOT the fix. The aggregation already cluster-corrects re-emission
 *     (rho=0.6 collapses 119 rows of one source to 1.66 effective items), so
 *     dedupe alone moves the delta by 0.16pp. The EXCLUSION is what removes it.
 */
export function signedEvidence<T extends SupplyRow>(rows: T[]): T[] {
  const deduped = dedupeByEvent(rows);
  const polarities = new Map<string, Set<number>>();
  for (const r of deduped) {
    const set = polarities.get(r.source) ?? new Set<number>();
    set.add(r.sentimentScore);
    polarities.set(r.source, set);
  }
  return deduped.filter((r) => (polarities.get(r.source)?.size ?? 0) > 1);
}

/**
 * Can this set express more than one direction? `modalShare` near 1 with
 * `distinctValues` 1 means the set is a constant — its "signal" is a template
 * default, and any edge computed from it is a category prior, not evidence.
 */
export function polarityConcentration(
  rows: SupplyRow[],
  opinionatedThreshold = DEFAULT_OPINIONATED_THRESHOLD
): PolarityConcentration {
  if (rows.length === 0) {
    return { modal: 0, modalShare: 0, distinctValues: 0, opinionatedRows: 0 };
  }
  const counts = new Map<number, number>();
  let opinionatedRows = 0;
  for (const r of rows) {
    const s = r.sentimentScore;
    counts.set(s, (counts.get(s) ?? 0) + 1);
    if (Math.abs(s) >= opinionatedThreshold) opinionatedRows++;
  }
  let modal = 0;
  let modalCount = -1;
  for (const [s, c] of counts) {
    // Ties break toward the larger |polarity|, then the larger value — deterministic.
    if (c > modalCount || (c === modalCount && Math.abs(s) > Math.abs(modal))) {
      modal = s;
      modalCount = c;
    }
  }
  return {
    modal,
    modalShare: modalCount / rows.length,
    distinctValues: counts.size,
    opinionatedRows,
  };
}

/** Per-source supply stats. `rows` may hold several sources; they are grouped. */
export function supplyStats(
  rows: SupplyRow[],
  opinionatedThreshold = DEFAULT_OPINIONATED_THRESHOLD
): SupplyStats[] {
  const bySource = new Map<string, SupplyRow[]>();
  for (const r of rows) {
    const arr = bySource.get(r.source) ?? [];
    arr.push(r);
    bySource.set(r.source, arr);
  }

  const out: SupplyStats[] = [];
  for (const [source, srcRows] of bySource) {
    const events = dedupeByEvent(srcRows);
    const conc = polarityConcentration(srcRows, opinionatedThreshold);
    const times = srcRows.map((r) => r.processedAt.getTime());
    out.push({
      source,
      rows: srcRows.length,
      distinctEvents: events.length,
      reEmission: events.length === 0 ? 0 : srcRows.length / events.length,
      opinionatedRows: conc.opinionatedRows,
      opinionatedEvents: events.filter((r) => Math.abs(r.sentimentScore) >= opinionatedThreshold)
        .length,
      modal: conc.modal,
      modalShare: conc.modalShare,
      distinctValues: conc.distinctValues,
      firstEmit: times.length ? new Date(Math.min(...times)).toISOString() : null,
      lastEmit: times.length ? new Date(Math.max(...times)).toISOString() : null,
    });
  }
  return out.sort((a, b) => b.rows - a.rows);
}
