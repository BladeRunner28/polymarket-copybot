/**
 * Tests for the shared split utility (card `ml-doctrine-time-and-era-splits`).
 *
 * The properties worth pinning are the ones a mistake would hide: that the cut is
 * by TIME and not by index, that a train row whose label landed inside the test
 * window is purged (leakage), that era provenance is reported rather than implied,
 * that a re-run is bit-identical, and that the blocked-fold hash agrees with the
 * Python fold assignment the existing fit script uses.
 */

import { describe, it, expect } from "vitest";
import {
  assignBlockedFold,
  blockedFolds,
  crc32,
  eraGroups,
  timeOrderedHoldout,
  walkForward,
} from "../src/lib/splits";

const DAY = 86_400_000;
const T = (iso: string) => Date.parse(iso);

type Row = {
  id: string;
  at: number;
  era: string;
  market: string;
  wallet: string;
  labelReadyAt: number;
  price: number;
};

const row = (o: Partial<Row> & { id: string }): Row => ({
  at: T("2026-07-20"),
  era: "pre-kelly-v1-48",
  market: "m1",
  wallet: "0xaa",
  labelReadyAt: T("2026-07-25"),
  price: 0.5,
  ...o,
});

describe("crc32 / blocked folds", () => {
  it("matches Python's zlib.crc32 on the same input", () => {
    // Values generated with: python3 -c "import zlib;print(zlib.crc32(b'x'))"
    expect(crc32("")).toBe(0);
    expect(crc32("a")).toBe(3904355907);
    expect(crc32("hello")).toBe(907060870);
    expect(crc32("0x85f031d069de3000")).toBe(1744693684);
    expect(crc32("0xb0c85813a7a4428f")).toBe(3390051983);
  });

  it("assigns the SAME fold number the Python fit script would (crc32 % k)", () => {
    expect(assignBlockedFold("0x85f031d069de3000", 5)).toBe(4);
    expect(assignBlockedFold("0xe0e637b08c971c2f", 5)).toBe(3);
    expect(assignBlockedFold("0xb0c85813a7a4428f", 5)).toBe(3);
  });

  it("is deterministic and keeps a group whole", () => {
    const rows = [
      row({ id: "a", wallet: "0xw1" }),
      row({ id: "b", wallet: "0xw1" }),
      row({ id: "c", wallet: "0xw2" }),
      row({ id: "d", wallet: "0xw3" }),
    ];
    const { folds, sizes } = blockedFolds(rows, (r) => r.wallet, 4);
    expect(sizes.reduce((a, b) => a + b, 0)).toBe(4);
    // Both rows of 0xw1 must sit in one fold — a split wallet leaks.
    const foldOf = rows.map((r) => folds.findIndex((f) => f.some((x) => x.id === r.id)));
    expect(foldOf[0]).toBe(foldOf[1]);
    expect(blockedFolds(rows, (r) => r.wallet, 4).sizes).toEqual(sizes);
  });

  it("rejects a k below 2 rather than silently returning fold 0 for everything", () => {
    expect(() => assignBlockedFold("0xaa", 1)).toThrow(/k must be an integer >= 2/);
  });
});

describe("timeOrderedHoldout", () => {
  const rows: Row[] = [];
  for (let i = 0; i < 10; i++) {
    rows.push(
      row({
        id: `early${i}`,
        at: T("2026-07-10") + i * DAY,
        labelReadyAt: T("2026-07-11") + i * DAY,
        era: "pre-kelly-v1-48",
      })
    );
  }
  for (let i = 0; i < 5; i++) {
    rows.push(
      row({
        id: `late${i}`,
        at: T("2026-08-20") + i * DAY,
        labelReadyAt: T("2026-08-21") + i * DAY,
        era: "kelly-window-v49-57",
      })
    );
  }

  it("cuts by timestamp, not by index into an unsorted list", () => {
    const shuffled = [...rows].reverse();
    const s = timeOrderedHoldout(shuffled, {
      at: (r) => r.at,
      era: (r) => r.era,
      boundary: T("2026-08-15"),
    });
    expect(s.train.every((r) => r.at < T("2026-08-15"))).toBe(true);
    expect(s.test.every((r) => r.at >= T("2026-08-15"))).toBe(true);
    expect(s.trainN).toBe(10);
    expect(s.testN).toBe(5);
  });

  it("purges train rows whose label was only knowable inside the test window", () => {
    const leaky = [
      ...rows,
      // Opens early, but its outcome settles AFTER the boundary — training on it
      // means training on the future.
      row({ id: "leaky", at: T("2026-08-01"), labelReadyAt: T("2026-09-01") }),
    ];
    const s = timeOrderedHoldout(leaky, {
      at: (r) => r.at,
      era: (r) => r.era,
      labelReadyAt: (r) => r.labelReadyAt,
      boundary: T("2026-08-15"),
    });
    expect(s.train.some((r) => r.id === "leaky")).toBe(false);
    expect(s.purged).toBe(1);
    expect(s.provenance).toContain("purged 1 train rows labelled after the boundary");
  });

  it("can keep the leaky row when the purge is explicitly disabled (so the flag is real)", () => {
    const leaky = [row({ id: "leaky", at: T("2026-08-01"), labelReadyAt: T("2026-09-01") }), ...rows];
    const s = timeOrderedHoldout(leaky, {
      at: (r) => r.at,
      labelReadyAt: (r) => r.labelReadyAt,
      boundary: T("2026-08-15"),
      purge: false,
    });
    expect(s.train.some((r) => r.id === "leaky")).toBe(true);
    expect(s.purged).toBe(0);
  });

  it("reports era provenance and flags eras present on both sides", () => {
    const s = timeOrderedHoldout(rows, { at: (r) => r.at, era: (r) => r.era, boundary: T("2026-08-15") });
    expect(s.eraTrain).toEqual({ "pre-kelly-v1-48": 10 });
    expect(s.eraTest).toEqual({ "kelly-window-v49-57": 5 });
    expect(s.overlapEras).toEqual([]);
    expect(s.provenance).toContain("eras train [pre-kelly-v1-48:10]");
    expect(s.provenance).toContain("eras on both sides: none");

    const crossing = timeOrderedHoldout(rows, { at: (r) => r.at, era: () => "one-era", boundary: T("2026-08-15") });
    expect(crossing.overlapEras).toEqual(["one-era"]);
    expect(crossing.provenance).toContain("eras on both sides: one-era");
  });

  it("never lets a tie group straddle the cut, and reports how wide it is", () => {
    const tied = [
      row({ id: "t1", at: T("2026-08-15") }),
      row({ id: "t2", at: T("2026-08-15") }),
      row({ id: "older", at: T("2026-08-01") }),
      row({ id: "newer", at: T("2026-08-16") }),
    ];
    const s = timeOrderedHoldout(tied, { at: (r) => r.at, boundary: T("2026-08-15") });
    // Both rows sharing the boundary go to TEST: a tie may not be split across sides.
    expect(s.test.map((r) => r.id).sort()).toEqual(["newer", "t1", "t2"]);
    expect(s.train.map((r) => r.id)).toEqual(["older"]);
    expect(s.tiedAtBoundary).toBe(2);
  });

  it("is reproducible: the same rows give the same split", () => {
    const a = timeOrderedHoldout(rows, { at: (r) => r.at, era: (r) => r.era, boundary: T("2026-08-15") });
    const b = timeOrderedHoldout([...rows], { at: (r) => r.at, era: (r) => r.era, boundary: T("2026-08-15") });
    expect(a.train.map((r) => r.id)).toEqual(b.train.map((r) => r.id));
    expect(a.provenance).toBe(b.provenance);
  });

  it("refuses a boundary that starves one side", () => {
    expect(() => timeOrderedHoldout(rows, { at: (r) => r.at, boundary: T("2026-01-01") })).toThrow(/every row in test/);
    expect(() => timeOrderedHoldout(rows, { at: (r) => r.at, boundary: T("2027-01-01") })).toThrow(/every row in train/);
  });
});

describe("walkForward", () => {
  const rows: Row[] = [];
  for (const [month, n] of [
    ["2026-06", 120],
    ["2026-07", 120],
    ["2026-08", 60],
  ] as const) {
    for (let i = 0; i < n; i++) {
      rows.push(
        row({
          id: `${month}-${i}`,
          at: Date.parse(`${month}-10T00:00:00Z`) + i * 60_000,
          labelReadyAt: Date.parse(`${month}-10T00:00:00Z`) + i * 60_000 + 5 * DAY,
        })
      );
    }
  }

  it("trains only on strictly earlier slices and respects the min-size bar", () => {
    const w = walkForward(rows, { at: (r) => r.at, labelReadyAt: (r) => r.labelReadyAt, slice: (r) => r.id.slice(0, 7) });
    expect(w.map((x) => x.label)).toEqual(["2026-07", "2026-08"]);
    expect(w[0].train.every((r) => r.id.startsWith("2026-06"))).toBe(true);
    expect(w[1].train).toHaveLength(240);
    expect(w[1].test).toHaveLength(60);
    expect(w[1].provenance).toContain("expanding-window walk-forward");
  });

  it("purges train rows whose label settled after the window opened", () => {
    const late = row({
      id: "2026-06-late",
      at: Date.parse("2026-06-10T00:00:00Z"),
      labelReadyAt: Date.parse("2026-07-09T00:00:00Z"), // before the July window: kept
    });
    const tooLate = row({
      id: "2026-06-tooLate",
      at: Date.parse("2026-06-11T00:00:00Z"),
      labelReadyAt: Date.parse("2026-07-11T00:00:00Z"), // after the July window: purged
    });
    const w = walkForward([...rows, late, tooLate], {
      at: (r) => r.at,
      labelReadyAt: (r) => r.labelReadyAt,
      slice: (r) => r.id.slice(0, 7),
    });
    const july = w.find((x) => x.label === "2026-07")!;
    expect(july.train.some((r) => r.id === "2026-06-late")).toBe(true);
    expect(july.train.some((r) => r.id === "2026-06-tooLate")).toBe(false);
    expect(july.provenance).toContain("purged");
  });
});

describe("eraGroups", () => {
  it("returns one subset per era — the per-era sign read the ML-1 gate needs", () => {
    const rows = [
      row({ id: "a", era: "pre-kelly-v1-48" }),
      row({ id: "b", era: "kelly-window-v49-57" }),
      row({ id: "c", era: "kelly-window-v49-57" }),
    ];
    const g = eraGroups(rows, (r) => r.era);
    expect([...g.keys()].sort()).toEqual(["kelly-window-v49-57", "pre-kelly-v1-48"]);
    expect(g.get("kelly-window-v49-57")).toHaveLength(2);
  });

  it("labels a null era as 'unknown' rather than filing it with a neighbour", () => {
    const g = eraGroups([row({ id: "a", era: null as unknown as string })], (r) => r.era);
    expect([...g.keys()]).toEqual(["unknown"]);
  });
});
