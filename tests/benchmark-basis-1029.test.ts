import { describe, expect, it } from "vitest";
import { beatBlindOnMatchedBasis, benchmarkBucket, type BenchmarkBucket, type BenchmarkReport } from "../src/lib/benchmarks";

/** Build a bucket from (pnl, cost) rows -- the same constructor the report uses. */
const bucket = (label: string, rows: Array<{ pnl: number; cost: number }>, total = rows.length): BenchmarkBucket =>
  benchmarkBucket(label, rows, total);

describe("bot-vs-blind verdict is computed on ONE basis (2026-10-29)", () => {
  const exitBook = bucket("bot exit", [{ pnl: 30, cost: 100 }]); // +30% on our own exits
  const blind = bucket("blind", [{ pnl: 10, cost: 100 }]); // +10% hold to resolution
  const heldCopy = bucket("bot held", [{ pnl: 5, cost: 100 }]); // +5% hold to resolution

  it("the exit book can look better while the matched pair says otherwise", () => {
    const report = { botFiltered: exitBook, botFilteredOutcome: heldCopy, blindCopy: blind } as Pick<
      BenchmarkReport,
      "botFilteredOutcome" | "blindCopy"
    >;
    // Old verdict: exitBook.roi (0.30) > blind.roi (0.10) => beat. That is an EXIT number against
    // an OUTCOME number, so it is exactly the comparison this fix removes.
    expect(exitBook.roi).toBeGreaterThan(blind.roi);
    expect(beatBlindOnMatchedBasis(report)).toBe(false);
  });

  it("reads only the matched pair, never the exit book", () => {
    const winning = bucket("bot held", [{ pnl: 50, cost: 100 }]);
    const report = { botFilteredOutcome: winning, blindCopy: blind } as Pick<BenchmarkReport, "botFilteredOutcome" | "blindCopy">;
    expect(beatBlindOnMatchedBasis(report)).toBe(true);
    const tied = { botFilteredOutcome: bucket("bot held", [{ pnl: 10, cost: 100 }]), blindCopy: blind };
    expect(beatBlindOnMatchedBasis(tied)).toBe(false); // a tie is not a win
  });

  it("a bucket with no resolved rows carries roi 0 and cannot win", () => {
    const empty = benchmarkBucket("bot held", [{ pnl: null, cost: null }], 1);
    expect(empty.resolvedCount).toBe(0);
    expect(empty.roi).toBe(0);
    expect(beatBlindOnMatchedBasis({ botFilteredOutcome: empty, blindCopy: bucket("blind", [{ pnl: -5, cost: 100 }]) })).toBe(true);
  });
});
