/**
 * Open MTM horizon tests (2026-10-04, /capital "when does the open mark close").
 *
 * Guards the three things the card's honesty depends on:
 *   - bucket boundaries are half-open and `remainHours <= 0` is overdue, so a
 *     market that has already closed is never counted as future exposure;
 *   - the unlock ladder is CUMULATIVE and signed, so the ladder's last step plus
 *     the untimed markets must reconcile to the open mark (no silent drop);
 *   - a missing snapshot / missing timeToResolution lands in `unknown` and is
 *     warned about, instead of being treated as "closes now".
 */

import { describe, it, expect } from "vitest";
import {
  HORIZON_BUCKETS,
  bucketOf,
  estimateCloseMs,
  formatHorizon,
  summarizeHorizon,
  toGroup,
  type HorizonGroup,
  type HorizonSummary,
} from "../src/lib/open-mtm-horizon";

const H = 3_600_000;
const NOW = 1_800_000_000_000;

function mk(
  marketId: string,
  opts: {
    legs?: number;
    cost?: number;
    unrealized?: number;
    remainHours?: number | null;
    snapshotMs?: number | null;
    ttrHours?: number | null;
    question?: string | null;
    isDemo?: boolean;
  } = {},
): HorizonGroup {
  const snapshotMs = opts.snapshotMs === undefined ? NOW - 6 * H : opts.snapshotMs;
  const remainHours = opts.remainHours === undefined ? 12 : opts.remainHours;
  // ttrHours is expressed relative to the snapshot, so derive it from the
  // snapshot age unless the test pins it (e.g. ttr = 0).
  const ttrHours =
    opts.ttrHours !== undefined
      ? opts.ttrHours
      : remainHours === null || snapshotMs === null
        ? null
        : remainHours + (NOW - snapshotMs) / H;
  return toGroup({
    marketId,
    legs: opts.legs ?? 1,
    cost: opts.cost ?? 10,
    unrealized: opts.unrealized ?? 1,
    openedAtMs: NOW - 48 * H,
    isDemo: opts.isDemo ?? false,
    question: opts.question ?? `Will ${marketId} happen?`,
    snapshotMs,
    ttrHours,
    nowMs: NOW,
  });
}

describe("bucketOf", () => {
  it("treats <= 0 hours as overdue, not as imminent", () => {
    expect(bucketOf(0)).toBe("overdue");
    expect(bucketOf(-0.01)).toBe("overdue");
    expect(bucketOf(-86.9)).toBe("overdue");
  });

  it("uses half-open boundaries", () => {
    expect(bucketOf(0.5)).toBe("lt24h");
    expect(bucketOf(23.999)).toBe("lt24h");
    expect(bucketOf(24)).toBe("d1_3");
    expect(bucketOf(72)).toBe("d3_7");
    expect(bucketOf(168)).toBe("d7_30");
    expect(bucketOf(720)).toBe("d30_90");
    expect(bucketOf(2160)).toBe("gt90d");
  });

  it("sends a missing estimate to unknown", () => {
    expect(bucketOf(null)).toBe("unknown");
    expect(bucketOf(undefined)).toBe("unknown");
    expect(bucketOf(Number.NaN)).toBe("unknown");
  });

  it("covers every bucket id in the render order", () => {
    expect(HORIZON_BUCKETS.map((b) => b.id)).toEqual([
      "overdue",
      "lt24h",
      "d1_3",
      "d3_7",
      "d7_30",
      "d30_90",
      "gt90d",
      "unknown",
    ]);
  });
});

describe("estimateCloseMs", () => {
  it("adds ttr hours to the snapshot stamp", () => {
    expect(estimateCloseMs(NOW, 4)).toBe(NOW + 4 * H);
  });

  it("returns null rather than guessing when evidence is missing", () => {
    expect(estimateCloseMs(null, 4)).toBeNull();
    expect(estimateCloseMs(NOW, null)).toBeNull();
    expect(estimateCloseMs(undefined, undefined)).toBeNull();
  });
});

describe("toGroup", () => {
  it("marks a past close for a still-open leg as overdue and keeps the evidence age", () => {
    const g = mk("ufc-x", { remainHours: -86.9, snapshotMs: NOW - 87 * H, cost: 2.48, unrealized: 0.79 });
    expect(g.bucket).toBe("overdue");
    expect(g.remainHours).toBeCloseTo(-86.9, 6);
    expect(g.staleDays).toBeCloseTo(3.625, 6);
  });

  it("treats a leg with no snapshot at all as unknown, with no fake staleness", () => {
    const g = toGroup({
      marketId: "quiet-market",
      legs: 2,
      cost: 4,
      unrealized: 0.5,
      openedAtMs: NOW - 10 * H,
      isDemo: false,
      question: null,
      snapshotMs: null,
      ttrHours: null,
      nowMs: NOW,
    });
    expect(g.bucket).toBe("unknown");
    expect(g.remainHours).toBeNull();
    expect(g.staleDays).toBeNull();
  });

  it("keeps a ttr of 0 as overdue (the venue clock already fired)", () => {
    const g = mk("resolved-not-booked", { snapshotMs: NOW - 5 * H, ttrHours: 0, remainHours: -5 });
    expect(g.bucket).toBe("overdue");
  });
});

describe("summarizeHorizon", () => {
  const groups = [
    mk("soon", { remainHours: 4, unrealized: 0.5, cost: 2 }),
    mk("week", { remainHours: 100, unrealized: 3, cost: 20 }),
    mk("month", { remainHours: 650, unrealized: 630, cost: 100, legs: 4 }),
    mk("long", { remainHours: 4719.4, unrealized: 91.6, cost: 100 }),
    mk("late", { remainHours: 9000, unrealized: -50, cost: 40 }),
    mk("overdue-a", { remainHours: -86.9, unrealized: 0.9, cost: 8.69, legs: 3 }),
    mk("untimed", { remainHours: null, unrealized: 2.5, cost: 7 }),
  ];
  const s: HorizonSummary = summarizeHorizon("BANKROLL_200", groups, NOW);

  it("reconciles the ladder, the untimed markets and the overdue bucket to the open mark", () => {
    const allDated = s.steps[s.steps.length - 1];
    expect(allDated.label).toBe("all dated");
    expect(allDated.cumUnrealized + s.totals.untimedUnrealized).toBeCloseTo(s.totals.unrealized, 6);
    expect(s.steps[0].label).toBe("now (overdue)");
    expect(s.steps[0].cumUnrealized).toBeCloseTo(s.totals.overdueUnrealized, 6);
    expect(
      s.totals.within30d + s.totals.beyond30d + s.totals.untimedUnrealized + s.totals.overdueUnrealized,
    ).toBeCloseTo(s.totals.unrealized, 6);
  });

  it("makes the ladder cumulative and monotone in gross terms", () => {
    const gross = s.steps.map((st) => st.cumGross);
    for (let i = 1; i < gross.length; i += 1) {
      expect(gross[i]).toBeGreaterThanOrEqual(gross[i - 1]);
    }
    expect(s.steps[1].cumGross).toBeCloseTo(0.5 + 0.9, 6); // ≤ 24 h, overdue included
    expect(s.steps[3].cumGross).toBeCloseTo(0.5 + 3 + 630 + 0.9, 6); // ≤ 30 d
  });

  it("splits within-24h / 7d / 30d and beyond without double counting", () => {
    expect(s.totals.within24h).toBeCloseTo(0.5, 6);
    expect(s.totals.within7d).toBeCloseTo(3.5, 6);
    expect(s.totals.within30d).toBeCloseTo(633.5, 6);
    expect(s.totals.beyond30d).toBeCloseTo(91.6 - 50, 6);
  });

  it("counts overdue exposure separately from future exposure", () => {
    expect(s.totals.overdueGroups).toBe(1);
    expect(s.totals.overdueLegs).toBe(3);
    expect(s.totals.overdueCost).toBeCloseTo(8.69, 6);
    expect(s.totals.overdueUnrealized).toBeCloseTo(0.9, 6);
    expect(s.warnings.some((w) => w.includes("are past their scheduled close and still open"))).toBe(true);
  });

  it("reports the longest-dated market and the mark concentration", () => {
    expect(s.totals.longestHours).toBeCloseTo(9000, 6);
    expect(s.totals.longestMarketId).toBe("late");
    expect(s.totals.topShare).toBeCloseTo(630 / s.totals.unrealized, 6);
  });

  it("warns about untimed markets and about stale evidence", () => {
    expect(s.totals.untimedUnrealized).toBeCloseTo(2.5, 6);
    expect(s.warnings.some((w) => w.includes("no usable time-to-resolution"))).toBe(true);
    // fixtures are 6 h old, so nothing is stale yet
    expect(s.totals.staleGroups).toBe(0);
    const stale = summarizeHorizon("STANDARD", [mk("quiet", { snapshotMs: NOW - 30 * 24 * H, remainHours: 100 })], NOW);
    expect(stale.totals.staleGroups).toBe(1);
    expect(stale.totals.oldestEvidenceDays).toBeCloseTo(30, 6);
    expect(stale.warnings.some((w) => w.includes("older than 3 d"))).toBe(true);
  });

  it("orders groups nearest-close-first and pushes unknowns to the end", () => {
    expect(s.groups.map((g) => g.marketId)).toEqual([
      "overdue-a",
      "soon",
      "week",
      "month",
      "long",
      "late",
      "untimed",
    ]);
  });

  it("returns a zeroed summary for an empty book", () => {
    const empty = summarizeHorizon("STANDARD", [], NOW);
    expect(empty.totals.groups).toBe(0);
    expect(empty.totals.unrealized).toBe(0);
    expect(empty.warnings).toEqual([]);
    expect(empty.steps.map((st) => st.cumUnrealized)).toEqual([0, 0, 0, 0, 0, 0, 0]);
  });
});

describe("formatHorizon", () => {
  it("renders hours, days, months and overdue distinctly", () => {
    expect(formatHorizon(6.2)).toBe("6.2 h");
    expect(formatHorizon(100)).toBe("4.2 d");
    expect(formatHorizon(650)).toBe("27.1 d");
    expect(formatHorizon(9000)).toBe("12.3 mo");
    expect(formatHorizon(-86.9)).toBe("3.6 d overdue");
    expect(formatHorizon(null)).toBe("unknown");
  });
});
