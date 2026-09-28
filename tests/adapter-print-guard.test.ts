import { describe, it, expect, vi, afterEach } from "vitest";
import { PolymarketAdapter } from "../src/lib/adapters/polymarket";
import type { PrintFilterReport } from "../src/lib/print-types";

/**
 * The print-type guard's WIRING (audit §P6, user-approved 2026-09-28).
 *
 * `print-types.test.ts` already proves the classifier is correct. This file
 * proves the opposite half, which a helper test cannot: that the guard is
 * actually called inside the activity read, that it drops non-fill rows from
 * what the caller receives, and that it reports the drop instead of absorbing
 * it silently.
 *
 * The load-bearing number: the guard must drop NOTHING in the live steady state
 * (measured 2026-09-28: 14,500 rows kept, 0 dropped, because the adapter also
 * asks the server for `type=TRADE`). A guard that starts firing on ordinary
 * traffic has changed ingest counts, which is a finding — hence the report.
 */

const ADDR = "0x111f73e91f85b6fe4de1ddec3de2fe32122e355b";
const NOW_S = Math.floor(Date.now() / 1000);

function fillRow(over: Record<string, unknown> = {}) {
  return {
    type: "TRADE",
    timestamp: NOW_S - 60,
    price: 0.5,
    usdcSize: 100,
    size: 200,
    slug: "some-market",
    conditionId: "0xabc",
    outcome: "Yes",
    side: "BUY",
    ...over,
  };
}

/** Serve one activity page, then throw if the adapter asks for more. */
function stubActivityPage(rows: Record<string, unknown>[]) {
  const fetchMock = vi.fn(async (url: string) => {
    if (!String(url).includes("/activity?")) throw new Error(`unexpected request: ${url}`);
    return new Response(JSON.stringify(rows), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("activity read — print-type guard", () => {
  it("drops non-fill rows the server filter let through, and reports them", async () => {
    const reports: PrintFilterReport[] = [];
    stubActivityPage([
      fillRow({ slug: "keep-1" }),
      fillRow({ type: "REDEEM", slug: "drop-redeem" }),
      fillRow({ type: "CONVERSION", slug: "drop-conversion" }),
      fillRow({ type: "merge", slug: "drop-merge" }),
      fillRow({ slug: "keep-2" }),
    ]);

    const trades = await new PolymarketAdapter().fetchWalletActivity(ADDR, 1, (r) => reports.push(r));

    // What the caller receives is what it would book: fills only.
    expect(trades.map((t) => t.marketId)).toEqual(["keep-1", "keep-2"]);
    expect(reports).toHaveLength(1);
    expect(reports[0].dropped).toBe(3);
    expect(reports[0].droppedByType).toEqual({ redeem: 1, conversion: 1, merge: 1 });
    expect(reports[0].uncataloguedTypes).toEqual([]); // all three are catalogued
    expect(reports[0].address).toBe(ADDR);
  });

  it("raises an uncatalogued type — the alarm that a new tape type appeared", async () => {
    const reports: PrintFilterReport[] = [];
    stubActivityPage([fillRow(), fillRow({ type: "SOMETHING_NEW", slug: "mystery" })]);

    const trades = await new PolymarketAdapter().fetchWalletActivity(ADDR, 1, (r) => reports.push(r));

    expect(trades.map((t) => t.marketId)).toEqual(["some-market"]);
    // An unrecognised type is dropped (conservative default) AND named, because
    // silently dropping it would shrink ingest with no visible cause.
    expect(reports[0].uncataloguedTypes).toEqual(["something_new"]);
    expect(reports[0].droppedByType).toEqual({ something_new: 1 });
  });

  it("stays silent on the measured live steady state: server-filtered pages of fills", async () => {
    const reports: PrintFilterReport[] = [];
    // The live path always asks for type=TRADE; these are what it returns.
    stubActivityPage([fillRow(), fillRow({ type: "TRADE" }), fillRow({ type: "BUY" }), fillRow({ type: "" })]);

    const trades = await new PolymarketAdapter().fetchWalletActivity(ADDR, 1, (r) => reports.push(r));

    expect(trades).toHaveLength(4);
    expect(reports).toEqual([]); // zero drops => no report, no log noise
  });

  it("works when no observer is passed (existing callers are unaffected)", async () => {
    stubActivityPage([fillRow(), fillRow({ type: "REDEEM", slug: "drop" })]);

    const trades = await new PolymarketAdapter().fetchWalletActivity(ADDR, 1);

    expect(trades.map((t) => t.marketId)).toEqual(["some-market"]);
  });
});
