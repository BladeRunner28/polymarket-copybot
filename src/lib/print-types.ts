/**
 * Print-type classification for the public trade tape.
 *
 * Ported from polyterm `core/print_scanner.py:16-33, 149, 174` (MIT), see
 * drafts/polyterm-audit-2026-09-28.md §P6.
 *
 * WHY: `data-api.polymarket.com/activity` and `/trades` mix real fills with
 * position-management rows (`split`, `merge`, `redeem`, `reward`, `conversion`,
 * liquidity ops, deposits/withdrawals). A row that is not a fill is not a
 * print: booking one as a copy-able trade inflates volume, invents trades at
 * prices nobody crossed, and — worst case — books a redemption as a buy.
 *
 * The set below is the source repo's whitelist/blacklist, re-typed. It is a
 * classification helper only: nothing here filters the live ingest by default.
 * Turning it on changes what the adapter counts, which is a measurement change,
 * so it must be measured before/after first (see the audit's P6 and the
 * `audit:print-types` script).
 */

/**
 * Row types that are never fills.
 *
 * The first eight are the ported source list. The last three were OBSERVED on
 * our own tape by `audit:print-types --unfiltered` (2026-09-28, 30 wallets /
 * 14,500 rows) and named here so the rejection is deliberate instead of a side
 * effect of the unknown-type default: `isTradeRow` already returned false for
 * them, so adding them changes no behaviour — it makes the reason legible.
 */
export const NON_TRADE_TYPES: ReadonlySet<string> = new Set([
  "split",
  "merge",
  "redeem",
  "reward",
  "conversion",
  "liquidity",
  "deposit",
  "withdrawal",
  // Observed on the public tape, not in the source repo's list:
  "maker_rebate",
  "taker_rebate",
  "yield",
]);

/** Row types that are fills, plus the empty/absent case (the tape omits `type`). */
export const TRADE_TYPES: ReadonlySet<string> = new Set(["", "trade", "trade_matched", "buy", "sell"]);

function typeOf(row: unknown): string {
  if (row === null || typeof row !== "object") return "";
  const v = (row as Record<string, unknown>).type;
  return v === undefined || v === null ? "" : String(v).toLowerCase();
}

/**
 * True when a row is a fill. Unknown non-empty types are NOT fills: an
 * unrecognised row is a row we cannot classify, and treating it as a print is
 * how invented trades get into the book.
 */
export function isTradeRow(row: unknown): boolean {
  const t = typeOf(row);
  if (NON_TRADE_TYPES.has(t)) return false;
  return TRADE_TYPES.has(t);
}

/**
 * True when a row type is one we have a position on — either a fill or a known
 * non-fill. False means the tape produced a type we have never catalogued, which
 * is the signal a measurement wants: the conservative default silently drops it,
 * so an unaudited new type would shrink ingest with no visible cause.
 *
 * Compares lowercased, because the API returns types in mixed case (`REDEEM`,
 * `CONVERSION`) while our sets are lowercase.
 */
export function isKnownRowType(type: unknown): boolean {
  const t = type === undefined || type === null ? "" : String(type).toLowerCase();
  return NON_TRADE_TYPES.has(t) || TRADE_TYPES.has(t);
}

export type PrintFilterResult<T> = {
  kept: T[];
  skipped: number;
  /** Count per dropped type, for the before/after measurement. */
  skippedByType: Record<string, number>;
  qualityFlags: string[];
};

/**
 * Split rows into fills and non-fills. Never throws and never invents rows: an
 * empty input yields an empty output plus the `empty_page` flag, so a caller
 * cannot read "nothing skipped" as "tape was fine".
 */
export function filterTradeRows<T>(rows: readonly T[]): PrintFilterResult<T> {
  const kept: T[] = [];
  const skippedByType: Record<string, number> = {};
  let skipped = 0;
  for (const row of rows) {
    if (isTradeRow(row)) {
      kept.push(row);
      continue;
    }
    skipped += 1;
    const t = typeOf(row) || "(unclassified)";
    skippedByType[t] = (skippedByType[t] ?? 0) + 1;
  }
  const qualityFlags = ["public_trade_rows_only"];
  if (skipped > 0) qualityFlags.push("skipped_non_trade_rows");
  if (rows.length === 0) qualityFlags.push("empty_data_api_page");
  return { kept, skipped, skippedByType, qualityFlags };
}

/**
 * What the client-side print-type guard dropped on one activity read. Emitted
 * only when it dropped something, so a quiet run stays quiet — and a non-empty
 * report is by construction a change in the venue's tape, not routine noise
 * (measured baseline 2026-09-28: zero drops over 14,500 rows on the live path).
 */
export type PrintFilterReport = {
  address: string;
  dropped: number;
  droppedByType: Record<string, number>;
  /** Types we have never catalogued (or "(empty)"): the alarm that matters. */
  uncataloguedTypes: string[];
};
