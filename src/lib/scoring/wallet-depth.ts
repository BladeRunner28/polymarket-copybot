/**
 * wallet-depth — count how deep a wallet's position record actually runs.
 *
 * WHY THIS EXISTS (wallet-depth-field-clamp, 2026-09-23): the scanner's depth
 * fields were not clamped by any rule, they were clamped by the FETCH —
 * `fetchWalletActivity` takes two 50-row closed-position pages (best + worst
 * realized PnL) and one 100-row open-position page, so it can never see more
 * than 100 resolved / 200 total positions. Measured 2026-09-23: 65.3% of all
 * 3,201 wallets sat at exactly resolvedTradeCount30d = 100 and tradeCount30d
 * capped at 200, i.e. a 100-position record was indistinguishable from a
 * 900-position one, and the thin-record work had to build its own as-of-entry
 * depth measure to say anything about the deep end.
 *
 * THE SEPARATION THAT MATTERS: the fetched SAMPLE feeds `scoreWallet` and must
 * stay exactly as it is (a bigger sample would move consistency, copyability,
 * averageTradeSize and the one-hit-wonder penalty — published scores). The
 * COUNT is a separate question with its own bounded walk. Nothing here is
 * allowed to touch the sample.
 */

import type { WalletDepth } from "../types";

/** One bounded paged count. `fetchPage(offset)` returns that page's rows. */
export async function countPaged(
  fetchPage: (offset: number) => Promise<unknown[]>,
  pageSize: number,
  maxPages: number
): Promise<{ count: number; censored: boolean; requests: number }> {
  let count = 0;
  let requests = 0;
  for (let page = 0; page < maxPages; page++) {
    const rows = await fetchPage(page * pageSize);
    requests++;
    if (!Array.isArray(rows)) break;
    count += rows.length;
    // A short page means the record ended — the count is exact.
    if (rows.length < pageSize) return { count, censored: false, requests };
  }
  // Every page was full: the record continues past the walk budget. The count
  // is a LOWER BOUND and the caller must store it as such.
  return { count, censored: true, requests };
}

export interface WalletDepthOptions {
  /** Closed (resolved) rows the scoring SAMPLE already returned. */
  sampledClosed: number;
  /** Open rows the scoring SAMPLE already returned. */
  sampledOpen: number;
  /** Sampling ceilings the sample is known to truncate at. */
  sampleClosedCap: number;
  sampleOpenCap: number;
  /** Rows per page on each endpoint (server-enforced for closed-positions). */
  closedPageSize: number;
  openPageSize: number;
  /** Walk budgets — pages, not rows. */
  maxClosedPages: number;
  maxOpenPages: number;
}

export type { WalletDepth };

/**
 * Decide whether a deeper walk is needed at all, then run it.
 *
 * A sample below its ceiling already IS the whole record (the two closed pages
 * exhaust both directions, and a short open page exhausts the open set), so
 * those wallets cost ZERO extra requests — the common case. Only wallets that
 * come back exactly at a ceiling get walked, and the walk is bounded.
 */
export async function measureDepth(
  fetchClosedPage: (offset: number) => Promise<unknown[]>,
  fetchOpenPage: (offset: number) => Promise<unknown[]>,
  opts: WalletDepthOptions
): Promise<WalletDepth> {
  let closedCount = opts.sampledClosed;
  let closedCensored = false;
  let openCount = opts.sampledOpen;
  let openCensored = false;
  let requests = 0;

  if (opts.sampledClosed >= opts.sampleClosedCap) {
    const r = await countPaged(fetchClosedPage, opts.closedPageSize, opts.maxClosedPages);
    closedCount = r.count;
    closedCensored = r.censored;
    requests += r.requests;
  }
  if (opts.sampledOpen >= opts.sampleOpenCap) {
    const r = await countPaged(fetchOpenPage, opts.openPageSize, opts.maxOpenPages);
    openCount = r.count;
    openCensored = r.censored;
    requests += r.requests;
  }

  return {
    closedCount,
    openCount,
    totalCount: closedCount + openCount,
    closedCensored,
    openCensored,
    censored: closedCensored || openCensored,
    capNote: `closed<=${opts.maxClosedPages * opts.closedPageSize}/open<=${opts.maxOpenPages * opts.openPageSize}`,
    requests,
  };
}
