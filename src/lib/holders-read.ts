/**
 * Data API `/v2/holders` reader — the outcome-supply side of the hygiene concentration metric.
 *
 * WHY THIS IS A LIB and not inline in the script (2026-11-11, card `polyterm-p5-holders-concentration`):
 * two callers need the same paginated walk — the hygiene scorer (`scripts/shadow-market-hygiene.ts`)
 * and the coverage read over OUR OWN traded markets (`scripts/holders-coverage-our-markets.ts`). A
 * second hand-rolled copy is how the two numbers drift apart.
 *
 * THE MOVE FROM v1 THAT MADE THIS NECESSARY: `${dataApi}/holders?market=<conditionId>` is RETIRED —
 * it answers `410 {"error":"Data API v1 has been retired"}` — so every read written against it fails
 * silently behind a try/catch and writes a zeroed concentration block. v2 is
 * `/v2/holders?conditionId=<conditionId>`, envelope `{data, pagination{limit, offset, has_more,
 * next_cursor}}`, cursor-only paging, and snake_case fields (`proxy_wallet`, `outcome_index`,
 * `token_id`).
 *
 * SUPPLY, NOT PAGES: "top-N share of outcome supply" needs the WHOLE holder list as the
 * denominator. This walks `next_cursor` until `has_more: false` and returns each outcome's
 * enumerated sum as `supplyShares`; a walk stopped by the page cap returns `truncated: true` so the
 * caller records an upper bound instead of a share. Read-only: GET, no auth, no side effects.
 */

import { VENUE, asNumber, venueGetJson } from "./venue-read";
import { laggedDataApiProvenance } from "./provenance";
import type { HolderRow } from "./market-hygiene";

/** One outcome's holder list, with the supply it accounts for when the walk reached the end. */
export type OutcomeHolders = {
  /** The CLOB token id for this outcome (v2's `token_id`). */
  tokenId?: string;
  outcomeIndex?: number;
  holders: HolderRow[];
  /** Sum of every listed holder amount — the outcome's supply only when `complete`. */
  supplyShares: number;
  /** True when the walk reached `has_more: false`: the list is the whole holder base. */
  complete: boolean;
};

export type HoldersRead =
  | { ok: true; outcomes: OutcomeHolders[]; pages: number; truncated: boolean; provenance: unknown }
  | { ok: false; error: string };

export type HoldersReadOptions = {
  /** Holders per page (v2 accepts up to 1000). Default 500. */
  limit?: number;
  /**
   * Page cap. Default 20: the endpoint's `limit` bounds holders ACROSS the market's outcomes, so a
   * two-outcome market yields roughly limit/2 holders per side per page — a 500 limit with a 5-page
   * cap truncated a 1,158-holder outcome in the 2026-11-11 coverage read. 20 pages at 500 is a
   * ~5,000-holder ceiling, and a walk that hits it is flagged `truncated` rather than averaged in.
   */
  maxPages?: number;
  /** Injection point for tests; defaults to the strict one-attempt venue GET. */
  fetchJson?: (url: string) => Promise<unknown>;
};

export async function readOutcomeHolders(
  conditionId: string,
  opts: HoldersReadOptions = {},
): Promise<HoldersRead> {
  const limit = opts.limit ?? 500;
  const maxPages = opts.maxPages ?? 20;
  const getJson = opts.fetchJson ?? ((url: string) => venueGetJson(url));
  const base = `${VENUE.dataApi}/v2/holders?conditionId=${encodeURIComponent(conditionId)}&limit=${limit}`;
  const byToken = new Map<string, OutcomeHolders>();
  let url: string | null = base;
  let pages = 0;
  let truncated = false;
  try {
    while (url && pages < maxPages) {
      const raw = await getJson(url);
      pages += 1;
      const env = raw as { data?: unknown; pagination?: { has_more?: boolean; next_cursor?: string | null } };
      const entries = Array.isArray(raw)
        ? (raw as Record<string, unknown>[])
        : Array.isArray(env.data)
          ? (env.data as Record<string, unknown>[])
          : null;
      if (!entries) throw new Error(`unexpected /v2/holders shape: ${Object.keys(env).slice(0, 6).join(",")}`);
      for (const entry of entries) {
        const token =
          entry.token_id !== undefined ? String(entry.token_id) : entry.token !== undefined ? String(entry.token) : "";
        const cur: OutcomeHolders =
          byToken.get(token) ?? { tokenId: token || undefined, outcomeIndex: undefined, holders: [], supplyShares: 0, complete: false };
        const rows = Array.isArray(entry.holders) ? (entry.holders as Record<string, unknown>[]) : [];
        for (const h of rows) {
          const outcomeIndex = asNumber(h.outcome_index) ?? asNumber(h.outcomeIndex);
          const wallet = h.proxy_wallet ?? h.proxyWallet;
          cur.holders.push({
            proxyWallet: wallet === undefined || wallet === null ? undefined : String(wallet),
            amount: asNumber(h.amount),
            outcomeIndex,
          });
          if (cur.outcomeIndex === undefined) cur.outcomeIndex = outcomeIndex;
        }
        byToken.set(token, cur);
      }
      const pag = env.pagination;
      const hasMore = !Array.isArray(raw) && Boolean(pag?.has_more);
      const next = pag?.next_cursor;
      if (hasMore && typeof next === "string" && next) {
        url = `${base}&cursor=${encodeURIComponent(next)}`;
      } else {
        if (hasMore) truncated = true; // has_more with no cursor: cannot continue
        url = null;
      }
    }
    if (url) truncated = true; // page cap reached with a cursor still open
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
  const outcomes: OutcomeHolders[] = [...byToken.values()].map((o) => ({
    tokenId: o.tokenId,
    outcomeIndex: o.outcomeIndex,
    holders: o.holders,
    supplyShares: o.holders.reduce((a, h) => a + (h.amount ?? 0), 0),
    complete: !truncated,
  }));
  if (outcomes.length === 0 || outcomes.every((o) => o.holders.length === 0)) {
    return { ok: false, error: "empty holder list" };
  }
  return { ok: true, outcomes, pages, truncated, provenance: laggedDataApiProvenance(["holders_endpoint_v2"]) };
}
