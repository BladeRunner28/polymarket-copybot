/**
 * Wiring test for loadOpenMtmHorizon's latest-snapshot read (card: dashboard-latest-snapshot-cost).
 *
 * The helpers are pure and already covered; the cost fix lives in HOW the loader talks to the DB.
 * These tests stub the transport so they exercise the real loader and assert on what the caller
 * receives — the shape of the read (index-only aggregate, then one row fetch per market), the
 * chunk boundary, and the two failure modes that a two-step read introduces: an empty aggregate
 * must not emit a malformed second query, and a market whose snapshot row is missing must land in
 * `unknown` rather than being dropped.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

const groupBy = vi.fn();
const queryRaw = vi.fn();

vi.mock("../src/lib/db", () => ({
  prisma: {
    paperTrade: { get groupBy() { return groupBy; } },
    get $queryRaw() { return queryRaw; },
  },
}));

import { loadOpenMtmHorizon } from "../src/lib/open-mtm-horizon";

const NOW = 1_800_000_000_000;
const H = 3_600_000;

/** marketId -> latest snapshot stamp (ms). */
function fixtures(n: number) {
  const grouped: {
    marketId: string;
    _count: { _all: number };
    _sum: { simulatedPositionSize: number; unrealizedPnl: number };
    _min: { openedAt: Date };
  }[] = [];
  const maxes: { marketId: string; collectedAt: number }[] = [];
  const rows: {
    marketId: string;
    collectedAt: number;
    timeToResolution: number | null;
    question: string | null;
    isDemo: boolean;
  }[] = [];
  for (let i = 0; i < n; i += 1) {
    const id = `m-${String(i).padStart(3, "0")}`;
    grouped.push({
      marketId: id,
      _count: { _all: 1 },
      _sum: { simulatedPositionSize: 10, unrealizedPnl: 1 },
      _min: { openedAt: new Date(NOW - 48 * H) },
    });
    maxes.push({ marketId: id, collectedAt: NOW - i * 1000 });
    rows.push({
      marketId: id,
      collectedAt: NOW - i * 1000,
      timeToResolution: 100 + i,
      question: `Q ${id}`,
      isDemo: false,
    });
  }
  return { grouped, maxes, rows };
}

/** $queryRaw dispatch: call 1 is the aggregate, later calls are pair fetches. */
function wire(f: ReturnType<typeof fixtures>, pairLimit?: number) {
  let call = 0;
  queryRaw.mockImplementation(() => {
    call += 1;
    if (call === 1) return Promise.resolve(f.maxes);
    const start = 200 * (call - 2);
    const end = pairLimit === undefined ? start + 200 : Math.min(start + pairLimit, f.rows.length);
    return Promise.resolve(f.rows.slice(start, end));
  });
  return () => call;
}

beforeEach(() => {
  groupBy.mockReset();
  queryRaw.mockReset();
});

describe("loadOpenMtmHorizon latest-snapshot read", () => {
  it("reads the aggregate first, then fetches rows in chunks of <=200 pairs", async () => {
    const f = fixtures(449);
    groupBy.mockResolvedValue(f.grouped);
    const calls = wire(f);

    const s = await loadOpenMtmHorizon({ botId: "STANDARD", nowMs: NOW });

    expect(s.totals.groups).toBe(449);
    // 1 aggregate + ceil(449/200) = 3 pair fetches
    expect(calls()).toBe(4);
    for (const c of s.groups) {
      expect(c.snapshotMs).not.toBeNull();
      expect(c.remainHours).not.toBeNull();
    }
  });

  it("keeps every market and its own snapshot stamp when the book is under one chunk", async () => {
    const f = fixtures(5);
    groupBy.mockResolvedValue(f.grouped);
    const calls = wire(f);

    const s = await loadOpenMtmHorizon({ botId: "STANDARD", nowMs: NOW });

    expect(calls()).toBe(2);
    const byId = new Map(s.groups.map((g) => [g.marketId, g]));
    for (let i = 0; i < 5; i += 1) {
      const id = `m-${String(i).padStart(3, "0")}`;
      const g = byId.get(id);
      expect(g, `missing group ${id}`).toBeTruthy();
      expect(g?.snapshotMs).toBe(NOW - i * 1000);
      expect(g?.ttrHours).toBe(100 + i);
      expect(g?.question).toBe(`Q ${id}`);
    }
  });

  it("does not issue a second query for an empty aggregate (no malformed WHERE)", async () => {
    const f = fixtures(1);
    groupBy.mockResolvedValue(f.grouped);
    const calls = wire({ grouped: [], maxes: [], rows: [] });

    const s = await loadOpenMtmHorizon({ botId: "STANDARD", nowMs: NOW });

    expect(calls()).toBe(1);
    expect(s.totals.groups).toBe(1);
    expect(s.groups[0].bucket).toBe("unknown");
    // its mark is still carried, as untimed exposure (fixture unrealized = 1)
    expect(s.totals.untimedUnrealized).toBe(1);
  });

  it("lands a market whose snapshot row is missing in unknown instead of dropping it", async () => {
    const f = fixtures(3);
    groupBy.mockResolvedValue(f.grouped);
    // aggregate announces all three, but the row fetch returns only two
    let call = 0;
    queryRaw.mockImplementation(() => {
      call += 1;
      if (call === 1) return Promise.resolve(f.maxes);
      return Promise.resolve(f.rows.slice(0, 2));
    });

    const s = await loadOpenMtmHorizon({ botId: "STANDARD", nowMs: NOW });

    expect(s.totals.groups).toBe(3);
    const last = s.groups.find((g) => g.marketId === "m-002");
    expect(last?.bucket).toBe("unknown");
    expect(last?.snapshotMs).toBeNull();
  });

  it("returns a zeroed summary without touching the DB when the book is empty", async () => {
    groupBy.mockResolvedValue([]);
    const s = await loadOpenMtmHorizon({ botId: "STANDARD", nowMs: NOW });
    expect(queryRaw).not.toHaveBeenCalled();
    expect(s.totals.groups).toBe(0);
  });
});
