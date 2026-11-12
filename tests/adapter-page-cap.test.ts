import { describe, it, expect, vi, afterEach } from "vitest";
import { PolymarketAdapter } from "../src/lib/adapters/polymarket";
import type { PrintFilterReport } from "../src/lib/print-types";

/**
 * The page cap's WIRING (card t_4c9847c9, Lane B).
 *
 * `fetchRecentTrades` reads at most 4 x 500 activity rows per wallet per sweep
 * (`for (let page = 0; page < 4; page++)`). Until this alarm existed, a wallet
 * busy enough to fill the budget looked exactly like a quiet wallet: the sweep
 * returned, stored what it got, and no number in the run moved.
 *
 * These tests pin both halves of the guarantee:
 *  - a read that stops at the budget with a cursor still pending REPORTS it
 *    (that is the whole repair — visibility, not a page-size change);
 *  - the measured steady state (a short page, or a last page with no cursor)
 *    stays silent, so the alarm cannot become routine log noise.
 */
const ADDR = "0x111f73e91f85b6fe4de1ddec3de2fe32122e355b";
const NOW_S = Math.floor(Date.now() / 1000);

function fillRow(i: number, over: Record<string, unknown> = {}) {
  return {
    type: "TRADE",
    timestamp: NOW_S - 60,
    price: 0.5,
    usdcSize: 100,
    size: 200,
    slug: `m-${i}`,
    conditionId: "0xabc",
    outcome: "Yes",
    side: "BUY",
    ...over,
  };
}

/** Serve `pages` full 500-row pages, each advertising another cursor. */
function stubPagedActivity(pages: number) {
  let served = 0;
  const fetchMock = vi.fn(async (url: string) => {
    if (!String(url).includes("/activity?")) throw new Error(`unexpected request: ${url}`);
    const body =
      served < pages
        ? { data: Array.from({ length: 500 }, (_, i) => fillRow(served * 500 + i)), pagination: { next_cursor: `c${served + 1}`, has_more: true } }
        : { data: [], pagination: { next_cursor: null } };
    served += 1;
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("activity read — page cap", () => {
  it("reports a capped read instead of passing it off as a quiet wallet", async () => {
    const fetchMock = stubPagedActivity(4);
    const reports: PrintFilterReport[] = [];

    const trades = await new PolymarketAdapter().fetchWalletActivity(ADDR, 1, (r) => reports.push(r));

    // The budget is 4 pages: 2,000 rows is the ceiling on what a sweep can see.
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(trades).toHaveLength(2000);
    expect(reports).toHaveLength(1);
    expect(reports[0].cappedAtPageLimit).toBe(true);
    expect(reports[0].rowsFetched).toBe(2000);
    expect(reports[0].address).toBe(ADDR);
    // A capped read is not a print-type finding.
    expect(reports[0].dropped).toBe(0);
    expect(reports[0].uncataloguedTypes).toEqual([]);
  });

  it("stays silent when the venue runs out of rows inside the budget", async () => {
    stubPagedActivity(2); // 2 full pages, then an empty page with a null cursor
    const reports: PrintFilterReport[] = [];

    const trades = await new PolymarketAdapter().fetchWalletActivity(ADDR, 1, (r) => reports.push(r));

    expect(trades).toHaveLength(1000);
    expect(reports).toEqual([]); // no cap, no drops => no report
  });

  it("stays silent on a single short page (the ordinary case)", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (!String(url).includes("/activity?")) throw new Error(`unexpected request: ${url}`);
      return new Response(JSON.stringify({ data: [fillRow(1)], pagination: { next_cursor: null } }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const reports: PrintFilterReport[] = [];

    await new PolymarketAdapter().fetchWalletActivity(ADDR, 1, (r) => reports.push(r));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(reports).toEqual([]);
  });
});
