/**
 * repo-growth-budget — the measurement behind kalshi-tape-repo-size-policy.
 *
 * The numbers in these tests are synthetic on purpose; the LIVE figures (and their
 * population/clock/level) are printed by scripts/repo-growth-budget.ts on every run
 * and written to data/repo-growth-budget-read.json.
 */

import { describe, it, expect } from "vitest";
import {
  budgetVerdict,
  churnBytes,
  classTotals,
  classifyTrackedPath,
  daysToCeiling,
  summariseGrowth,
  topContributors,
} from "../src/lib/repo-growth-budget";

const MB = 1048576;

describe("classifyTrackedPath", () => {
  it("separates the classes the growth report acts on", () => {
    expect(classifyTrackedPath("data/kalshi-macro-quotes.jsonl")).toBe("tape-kalshi");
    expect(classifyTrackedPath("data/kalshi-1c-queue/snaps-2026-10-30.jsonl.gz")).toBe("tape-kalshi");
    expect(classifyTrackedPath("data/jev-shadow.jsonl")).toBe("tape-shadow");
    expect(classifyTrackedPath("data/lowconf-shadow.jsonl")).toBe("tape-shadow");
    expect(classifyTrackedPath("data/wallet-sells.jsonl")).toBe("tape-other");
    expect(classifyTrackedPath("data/archive-analysis/asset-labels-2026_04.parquet")).toBe("dataset");
    expect(classifyTrackedPath("data/ml/decisions.csv")).toBe("dataset");
    expect(classifyTrackedPath("training_data.csv")).toBe("dataset");
    expect(classifyTrackedPath("data/l2/54182850929628351640608730901839648941414372369142005155365066950018033015874.jsonl")).toBe("orderbook");
    expect(classifyTrackedPath("data/cache/data-feed-scout/9b09fbb4a373bf30.body")).toBe("cache");
    expect(classifyTrackedPath("prisma/dev.db")).toBe("db");
    expect(classifyTrackedPath("src/lib/repo-growth-budget.ts")).toBe("code");
    expect(classifyTrackedPath("package.json")).toBe("code");
});

  it("does not call a parquet under data/ tape just because it lives in data/", () => {
    expect(classifyTrackedPath("data/foo.parquet")).toBe("dataset");
    expect(classifyTrackedPath("data/foo.jsonl")).toBe("tape-other");
  });
});

describe("classTotals", () => {
  it("groups files and bytes, and omits classes that are absent", () => {
    const out = classTotals([
      { path: "data/kalshi-tape/bars.jsonl", bytes: 10 },
      { path: "data/kalshi-macro-quotes.jsonl", bytes: 5 },
      { path: "src/a.ts", bytes: 1 },
    ]);
    expect(out["tape-kalshi"]).toEqual({ files: 2, bytes: 15 });
    expect(out["code"]).toEqual({ files: 1, bytes: 1 });
    expect(out["db"]).toBeUndefined();
  });
});

describe("summariseGrowth", () => {
  it("reports median, mean and the concentration checks on the live shape", () => {
    const s = summariseGrowth([34, 38, 45, 38, 44, 50, 65].map((v) => v * MB));
    expect(s.n).toBe(7);
    expect(s.median).toBe(44 * MB);
    expect(s.max).toBe(65 * MB);
    expect(s.p90).toBe(65 * MB);
    expect(s.mean).toBeCloseTo(((34 + 38 + 45 + 38 + 44 + 50 + 65) / 7) * MB, 0);
    // ex-top-1 must not collapse to zero: the growth is a class, not one day
    expect(s.exTop1Mean).toBeCloseTo(((34 + 38 + 45 + 38 + 44 + 50) / 6) * MB, 0);
  });

  it("keeps zero days in the population and counts them", () => {
    const s = summariseGrowth([0, 0, 40 * MB, 0]);
    expect(s.idleDays).toBe(3);
    expect(s.median).toBe(0);
    expect(s.max).toBe(40 * MB);
  });

  it("returns an empty summary for no data", () => {
    const s = summariseGrowth([]);
    expect(s).toEqual({ n: 0, idleDays: 0, mean: 0, median: 0, trimmedMean: 0, p90: 0, max: 0, exTop1Mean: 0 });
  });

  it("drops out-of-range values instead of letting them set the headline", () => {
    const s = summariseGrowth([10, -5, Number.NaN, 20]);
    expect(s.n).toBe(2);
    expect(s.median).toBe(15);
  });
});

describe("daysToCeiling", () => {
  it("projects forward, returns 0 when already past, null on no growth", () => {
    expect(daysToCeiling(1000, 100, 1500)).toBe(5);
    expect(daysToCeiling(1000, 100, 1000)).toBe(0);
    expect(daysToCeiling(2000, 100, 1000)).toBe(0);
    expect(daysToCeiling(1000, 0, 1500)).toBeNull();
    expect(daysToCeiling(1000, -5, 1500)).toBeNull();
  });
});

describe("churnBytes", () => {
  it("counts only the writes after a path first appearance in the day", () => {
    expect(
      churnBytes([
        { path: "data/a.jsonl", bytes: 100 },
        { path: "data/b.jsonl", bytes: 50 },
        { path: "data/a.jsonl", bytes: 100 },
      ]),
    ).toBe(100);
  });

  it("is zero when every path is written once, whatever the sizes", () => {
    expect(churnBytes([{ path: "a", bytes: 9 }, { path: "b", bytes: 900 }])).toBe(0);
    expect(churnBytes([])).toBe(0);
  });
});

describe("topContributors", () => {
  it("ranks by bytes and states each share of the population total", () => {
    const top = topContributors([
      { path: "data/a.jsonl", bytes: 60 },
      { path: "data/b.jsonl", bytes: 30 },
      { path: "data/a.jsonl", bytes: 10 },
      { path: "data/c.jsonl", bytes: 10 },
    ], 2);
    expect(top).toHaveLength(2);
    expect(top[0]).toEqual({ path: "data/a.jsonl", bytes: 70, share: 70 / 110 });
    expect(top[1].path).toBe("data/b.jsonl");
  });

  it("returns nothing for an empty window", () => {
    expect(topContributors([], 5)).toEqual([]);
  });
});

describe("budgetVerdict", () => {
  const GB2 = 2048 * MB;

  it("alarms when the median day crosses the ceiling inside the alarm window", () => {
    const v = budgetVerdict({
      currentGitBytes: 1344 * MB,
      daily: [34, 38, 45, 38, 44, 50, 65].map((x) => x * MB),
      ceilingBytes: GB2,
      dailyBudgetBytes: 40 * MB,
      alarmDaysToCeiling: 90,
    });
    expect(v.level).toBe("alarm");
    expect(v.daysAtMedian).toBe(16);
    expect(v.overBudget).toBe(true);
    expect(v.reasons.join(" ")).toContain("44.0 MB/day");
  });

  it("stays ok when growth is small and the ceiling is far", () => {
    const v = budgetVerdict({
      currentGitBytes: 500 * MB,
      daily: [10, 12, 11, 13, 12, 10, 11].map((x) => x * MB),
      ceilingBytes: GB2,
      dailyBudgetBytes: 40 * MB,
      alarmDaysToCeiling: 90,
    });
    expect(v.level).toBe("ok");
    expect(v.overBudget).toBe(false);
  });

  it("warns when only the worst day is fast enough to matter", () => {
    const v = budgetVerdict({
      currentGitBytes: 200 * MB,
      daily: [20, 20, 20, 20, 20, 20, 120].map((x) => x * MB),
      ceilingBytes: GB2,
      dailyBudgetBytes: 40 * MB,
      alarmDaysToCeiling: 90,
    });
    expect(v.level).toBe("warn");
    expect(v.daysAtMax).toBe(16);
  });

  it("alarms at a ceiling already passed, without dividing by zero", () => {
    const v = budgetVerdict({ currentGitBytes: 3 * GB2, daily: [MB], ceilingBytes: GB2 });
    expect(v.level).toBe("alarm");
    expect(v.daysAtMedian).toBe(0);
  });
});
