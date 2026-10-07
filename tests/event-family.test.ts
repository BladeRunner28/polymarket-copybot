import { describe, it, expect } from "vitest";
import {
  NO_WALLET,
  describeSplit,
  eventFamily,
  shortWallet,
  walletSplit,
  type CostedLeg,
} from "../src/lib/event-family";

/**
 * Tuning #48 rec 1 (approved 2026-10-07) added the wallet dimension to the shipped EOD
 * event-family read. What these tests must protect:
 *   1. the PRE-REGISTERED family rule is unchanged (a reviewer's cross-check and the EOD line
 *      must agree — silently re-deriving it is the failure mode the header warns about);
 *   2. the wallet split is ORDER-DETERMINISTIC, because the line is verified by re-running it
 *      at a fixed instant: ties must not flip between runs;
 *   3. a leg with no stored wallet is visibly its own bucket, never folded into a real address.
 */

describe("eventFamily — the pre-registered rule", () => {
  it("cuts at the ISO date when the slug carries one, so same-event legs are ONE family", () => {
    expect(eventFamily("unl-nor-prt-2026-09-27-nor")).toBe("unl-nor-prt-2026-09-27");
    expect(eventFamily("unl-nor-prt-2026-09-27-prt")).toBe("unl-nor-prt-2026-09-27");
    expect(eventFamily("cfb-nmxst-flint-2026-10-07")).toBe("cfb-nmxst-flint-2026-10-07");
  });

  it("falls back to the first 3 dash tokens — the entity the event set hangs off", () => {
    expect(eventFamily("will-david-lisnard-win-the-california-governorship")).toBe("will-david-lisnard");
    expect(eventFamily("elon-musk-of-tweets-october-10-17")).toBe("elon-musk-of");
    // a real live case: a non-ISO date suffix must NOT be mistaken for a date cut
    expect(eventFamily("highest-temperature-in-denver-on-october-8-2026-86-87f")).toBe("highest-temperature-in");
  });

  it("returns a short slug unchanged rather than inventing tokens", () => {
    expect(eventFamily("bra-cre")).toBe("bra-cre");
    expect(eventFamily("single")).toBe("single");
  });
});

const leg = (walletAddress: string | null, cost: number | null): CostedLeg => ({ walletAddress, cost });

describe("walletSplit — deterministic, and honest about a missing wallet", () => {
  it("aggregates legs and cost per wallet", () => {
    const split = walletSplit([leg("0xaaa", 100), leg("0xaaa", 50), leg("0xbbb", 10)]);
    expect(split.map((s) => [s.wallet, s.legs, s.cost])).toEqual([
      ["0xaaa", 2, 150],
      ["0xbbb", 1, 10],
    ]);
  });

  it("orders by cost DESC and breaks ties by wallet, so shuffling the input cannot change the line", () => {
    const legs = [leg("0xzz", 25), leg("0xaa", 25), leg("0xmm", 90)];
    const a = walletSplit(legs).map((s) => s.wallet);
    const b = walletSplit([...legs].reverse()).map((s) => s.wallet);
    const c = walletSplit([legs[1], legs[2], legs[0]]).map((s) => s.wallet);
    expect(a).toEqual(["0xmm", "0xaa", "0xzz"]);
    expect(b).toEqual(a);
    expect(c).toEqual(a);
  });

  it("keeps a leg with no wallet as its own bucket, never inside a real address", () => {
    const split = walletSplit([leg(null, 40), leg("", 1), leg("0xaaa", 5)]);
    const noWallet = split.find((s) => s.wallet === NO_WALLET);
    expect(noWallet).toEqual({ wallet: NO_WALLET, legs: 2, cost: 41 });
    expect(split.find((s) => s.wallet === "0xaaa")?.cost).toBe(5);
  });

  it("treats a null cost as zero rather than NaN", () => {
    const split = walletSplit([leg("0xaaa", null), leg("0xaaa", 10)]);
    expect(split[0].cost).toBe(10);
    expect(Number.isNaN(split[0].cost)).toBe(false);
  });
});

describe("describeSplit / shortWallet — the rendered fragment", () => {
  it("renders legs, cost and share, capped at `limit`", () => {
    const split = walletSplit([leg("0x7c63520c2ca9b336af0c205b9ccf68217bb393d4", 279.9), leg("0xbbb", 100)]);
    const text = describeSplit(split, 379.9, 1);
    expect(text).toBe("0x7c63520c… 1 legs +$279.90 (73.7%)");
  });

  it("says n/a instead of dividing by zero, and keeps the sign", () => {
    expect(describeSplit(walletSplit([leg("0xaaa", -20)]), 0)).toBe("0xaaa 1 legs -$20.00 (n/a)");
  });

  it("shortens only real addresses", () => {
    expect(shortWallet("0x7c63520c2ca9b336af0c205b9ccf68217bb393d4")).toBe("0x7c63520c…");
    expect(shortWallet("0xabc")).toBe("0xabc");
    expect(shortWallet(NO_WALLET)).toBe(NO_WALLET);
  });
});
