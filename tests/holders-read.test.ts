import { describe, expect, it } from "vitest";
import { readOutcomeHolders } from "../src/lib/holders-read";

/**
 * The pagination walk is the part that decides whether a "top-N share" is a share of the outcome's
 * SUPPLY or of whatever page the endpoint happened to return first, so it is tested against a fake
 * transport rather than only by eye on a live run.
 */
const COND = "0xabc";

function page(entries: unknown[], pagination: Record<string, unknown>) {
  return { data: entries, pagination };
}

describe("/v2/holders pagination", () => {
  it("follows next_cursor and sums the supply across pages", async () => {
    const urls: string[] = [];
    const read = await readOutcomeHolders(COND, {
      limit: 2,
      fetchJson: async (url) => {
        urls.push(url);
        if (urls.length === 1)
          return page(
            [{ token_id: "T1", holders: [{ proxy_wallet: "0xa", amount: 10, outcome_index: 0 }, { proxy_wallet: "0xb", amount: 5, outcome_index: 0 }] }],
            { has_more: true, next_cursor: "cur-1" }
          );
        return page(
          [{ token_id: "T1", holders: [{ proxy_wallet: "0xc", amount: 5, outcome_index: 0 }] }],
          { has_more: false, next_cursor: null }
        );
      },
    });
    expect(read.ok).toBe(true);
    if (!read.ok) return;
    expect(urls.length).toBe(2);
    expect(urls[1]).toContain("cursor=cur-1");
    expect(urls[0]).toContain(`conditionId=${COND}`);
    expect(urls[0]).toContain("/v2/holders");
    expect(read.pages).toBe(2);
    expect(read.truncated).toBe(false);
    expect(read.outcomes).toHaveLength(1);
    expect(read.outcomes[0].supplyShares).toBe(20);
    expect(read.outcomes[0].complete).toBe(true);
    expect(read.outcomes[0].holders.map((h) => h.proxyWallet)).toEqual(["0xa", "0xb", "0xc"]);
  });

  it("stops at the page cap and says the supply is incomplete", async () => {
    let calls = 0;
    const read = await readOutcomeHolders(COND, {
      limit: 1,
      maxPages: 2,
      fetchJson: async () => {
        calls += 1;
        return page([{ token_id: "T1", holders: [{ proxy_wallet: `0x${calls}`, amount: 1, outcome_index: 0 }] }], {
          has_more: true,
          next_cursor: `cur-${calls}`,
        });
      },
    });
    expect(read.ok).toBe(true);
    if (!read.ok) return;
    expect(calls).toBe(2);
    expect(read.truncated).toBe(true);
    expect(read.outcomes[0].complete).toBe(false);
  });

  it("fails loudly on an unexpected envelope instead of returning a zeroed read", async () => {
    const read = await readOutcomeHolders(COND, { fetchJson: async () => ({ error: "nope" }) });
    expect(read.ok).toBe(false);
    if (read.ok) return;
    expect(read.error).toContain("unexpected /v2/holders shape");
  });

  it("reports an empty holder list as unavailable, not as zero concentration", async () => {
    const read = await readOutcomeHolders(COND, {
      fetchJson: async () => page([{ token_id: "T1", holders: [] }], { has_more: false, next_cursor: null }),
    });
    expect(read.ok).toBe(false);
  });

  it("keeps both outcomes apart (the sides of a complementary market are separate holder bases)", async () => {
    const read = await readOutcomeHolders(COND, {
      fetchJson: async () =>
        page(
          [
            { token_id: "T1", holders: [{ proxy_wallet: "0xa", amount: 90, outcome_index: 0 }] },
            { token_id: "T2", holders: [{ proxy_wallet: "0xb", amount: 90, outcome_index: 1 }] },
          ],
          { has_more: false, next_cursor: null }
        ),
    });
    expect(read.ok).toBe(true);
    if (!read.ok) return;
    expect(read.outcomes.map((o) => o.outcomeIndex).sort()).toEqual([0, 1]);
  });
});
