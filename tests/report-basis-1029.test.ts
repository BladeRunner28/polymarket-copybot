/**
 * 2026-10-29 (self-audit) — three EOD-report reads that carried no basis, and the label lie each one
 * allowed. None of these change a rule, a threshold or a size: they change what the report can be
 * READ as.
 *
 * 1. "Signals today: 1071 (copy 16 / watch 0 / skip 1055)" on the 10-28 report, run at 06:50 on
 *    10-29, against 1,011 decisions that actually fall inside 10-28 (copy 11 / skip 1000). The
 *    decision and rule-change reads had `gte: dayStart` and NO upper bound, so "today" meant
 *    "midnight onward" — a late/catch-up run (copybot-eod-catchup.sh re-runs report:daily by
 *    design) attributed the next day's rows to the reported day, and those rows were then counted
 *    again in their own report.
 *
 * 2. "Bot vs blind copy: bot avg +$0.97/trade vs blind +$0.60/trade": two buckets, two stake bases
 *    (bot legs sized at whatever each leg was worth, blind at a flat $10), no n on either side, and
 *    a blind population that is the reviewed 3.2% of signals rather than all of them.
 *
 * 3. "Rule changes" / "Top lesson": the same stored reason printed verbatim in both bullets. The
 *    writer was fixed on 2026-10-28 (05836b2), but rows written before it still hold one copy of the
 *    reason per field the change touched (v69 x2 = 583 chars), and the renderer trusts the string.
 */

import { describe, it, expect } from "vitest";
import { oneReason } from "../src/lib/report";
import { benchmarkBucket } from "../src/lib/benchmarks";

const A = "v68 gave the same 1.5x up-weight to 3-7d, 7-30d and >30d.";
const B = "Splitting the bucket at 168h sends the up-weight only to the window that recycles capital.";

describe("oneReason: a rule-change reason is printed once, however it was stored", () => {
  it("collapses the pre-05836b2 duplicate segments", () => {
    // v69, live: 583 chars of the same sentence twice
    expect(oneReason(`${A} | ${A}`)).toBe(A);
    // v68, live: five copies, 1,477 chars
    expect(oneReason([A, A, A, A, A].join(" | "))).toBe(A);
  });

  it("keeps distinct reasons, in the order they were recorded", () => {
    expect(oneReason(`${A} | ${B}`)).toBe(`${A} | ${B}`);
    expect(oneReason(`${B} | ${A} | ${B}`)).toBe(`${B} | ${A}`);
  });

  it("trims duplicates that differ only in whitespace, and drops empty segments", () => {
    expect(oneReason(`${A} |  ${A}  | `)).toBe(A);
  });

  it("is a no-op on a single reason, and never returns a stray separator", () => {
    expect(oneReason(A)).toBe(A);
    expect(oneReason("")).toBe("");
    expect(oneReason(" |  | ")).toBe("");
  });
});

describe("benchmarkBucket: $/trade is not comparable across stake bases, ROI is", () => {
  // The exact shape of the live book: the bot stakes ~$10.85/leg, the blind hypothetical is flat $10.
  const bot = benchmarkBucket("bot", [{ pnl: 2, cost: 20 }], 1);
  const blind = benchmarkBucket("blind", [{ pnl: 1.5, cost: 10 }], 1);

  it("reports the stake it divided by, so the average can be read as a rate", () => {
    expect(bot.avgPnl).toBe(2);
    expect(bot.totalCost).toBe(20);
    expect(bot.roi).toBeCloseTo(0.1);
    expect(blind.roi).toBeCloseTo(0.15);
  });

  it("shows the case the old line got backwards: more $/trade, less per dollar", () => {
    // the old verdict compared avgPnl and would call this a bot win at a 2x smaller stake
    expect(bot.avgPnl).toBeGreaterThan(blind.avgPnl);
    expect(bot.roi).toBeLessThan(blind.roi);
  });

  it("does not divide by zero when a bucket has no resolved rows", () => {
    const empty = benchmarkBucket("empty", [{ pnl: null, cost: 10 }], 7);
    expect(empty.resolvedCount).toBe(0);
    expect(empty.roi).toBe(0);
    expect(empty.totalCost).toBe(0);
  });

  it("excludes unresolved rows from the stake as well as from the PnL", () => {
    const mixed = benchmarkBucket("mixed", [{ pnl: 1, cost: 10 }, { pnl: null, cost: 999 }], 2);
    expect(mixed.totalCost).toBe(10);
    expect(mixed.resolvedCount).toBe(1);
  });
});
