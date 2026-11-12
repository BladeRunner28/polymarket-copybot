/**
 * The ML-1 per-era read and train-era mix (card `ml1-fit-population-gaps`, claim (2) — reporting
 * only, nothing fitted here). These pin the two properties that make the gate output honest:
 *
 *   1. the TRAIN mix is MEASURED from the window actually used, so a single-era fit says so in the
 *      gate output instead of only in a roadmap note; and
 *   2. a per-era AUC row always carries `seenInTrain`, so an arm scored on an era the fit never saw
 *      cannot be printed as if it were a same-regime read.
 *
 * None of these assertions encodes a market result — they are arithmetic and labelling.
 */
import { describe, expect, it } from "vitest";
import { BOUNDARY, eraAucRead, fitPopulations, parseFitSplitMode, readArms, trainEraMix, type Leg } from "../src/lib/ml1-read";

const day = 86_400_000;
const base = Date.parse("2026-06-01T00:00:00Z");

/** A leg whose price ranks its label perfectly inside its own era. */
function leg(era: string, i: number, y: 0 | 1, opts: { market?: string; price?: number } = {}): Leg {
  const price = opts.price ?? (y === 1 ? 0.8 : 0.2);
  return {
    at: base + i * day,
    readyAt: base + (i + 5) * day,
    market: opts.market ?? `m-${era}-${i}`,
    wallet: `w-${i}`,
    era,
    price,
    detected: price,
    pnlNetEntry: y === 1 ? 1 : -1,
    y,
    scores: {},
    f: {},
  };
}

describe("trainEraMix", () => {
  it("measures the window it was given, shares summing to 1", () => {
    const train = [...Array(90)].map((_, i) => leg("pre-kelly-v1-48", i, (i % 2) as 0 | 1))
      .concat([...Array(10)].map((_, i) => leg("kelly-window-v49-57", 100 + i, (i % 2) as 0 | 1)));
    const mix = trainEraMix(train);
    expect(mix).toHaveLength(2);
    expect(mix.find((e) => e.era === "pre-kelly-v1-48")).toMatchObject({ n: 90 });
    expect(mix.find((e) => e.era === "kelly-window-v49-57")!.share).toBeCloseTo(0.1, 10);
    expect(mix.reduce((s, e) => s + e.share, 0)).toBeCloseTo(1, 10);
  });

  it("reports a single-era window as exactly one era at 100%", () => {
    const mix = trainEraMix([...Array(40)].map((_, i) => leg("pre-kelly-v1-48", i, (i % 2) as 0 | 1)));
    expect(mix).toEqual([{ era: "pre-kelly-v1-48", n: 40, share: 1 }]);
  });

  it("returns nothing for an empty window rather than inventing an era", () => {
    expect(trainEraMix([])).toEqual([]);
  });
});

describe("eraAucRead", () => {
  const train = [...Array(60)].map((_, i) => leg("pre-kelly-v1-48", i, (i % 2) as 0 | 1));
  const trainEras = new Set(trainEraMix(train).map((e) => e.era));

  it("stratifies by era and flags the era the fit never saw", () => {
    const seen = [...Array(40)].map((_, i) => leg("pre-kelly-v1-48", i, (i % 2) as 0 | 1, { price: i % 2 === 1 ? 0.9 : 0.1 }));
    const unseen = [...Array(40)].map((_, i) => leg("exposure-v58plus", 200 + i, (i % 2) as 0 | 1, { price: i % 2 === 1 ? 0.4 : 0.6 }));
    const rows = eraAucRead([...seen, ...unseen], (l) => l.price, trainEras);
    expect(rows.map((r) => r.era)).toEqual(["exposure-v58plus", "pre-kelly-v1-48"]);
    const e = rows.find((r) => r.era === "exposure-v58plus")!;
    const p = rows.find((r) => r.era === "pre-kelly-v1-48")!;
    expect(e.seenInTrain).toBe(false);
    expect(p.seenInTrain).toBe(true);
    expect(e.n).toBe(40);
    // In the unseen era price is ANTI-ranked (winners at 0.4) -> AUC below 0.5; in the seen era it is perfect.
    expect(e.auc).toBeLessThan(0.5);
    expect(p.auc).toBe(1);
  });

  it("does not read an era below the row floor, and says so instead of printing a number", () => {
    const few = [...Array(5)].map((_, i) => leg("kelly-window-v49-57", 300 + i, (i % 2) as 0 | 1));
    const rows = eraAucRead(few, (l) => l.price, trainEras, 30);
    expect(rows[0].usable).toBe(false);
    expect(Number.isNaN(rows[0].auc)).toBe(true);
  });

  it("does not read a one-class era (AUC is undefined, not 0.5)", () => {
    const oneClass = [...Array(50)].map((_, i) => leg("exposure-v58plus", 400 + i, 1));
    const rows = eraAucRead(oneClass, (l) => l.price, trainEras);
    expect(rows[0].usable).toBe(false);
    expect(Number.isNaN(rows[0].auc)).toBe(true);
  });

  it("drops rows the ranker cannot score (no silent imputation)", () => {
    const rows = eraAucRead(
      [
        ...Array.from({ length: 40 }, (_, i) => leg("pre-kelly-v1-48", i, (i % 2) as 0 | 1)),
        leg("pre-kelly-v1-48", 999, 1, { price: Number.NaN }),
      ] as Leg[],
      (l) => l.price,
      trainEras
    );
    expect(rows[0].n).toBe(40);
  });
});

describe("readArms carries the era basis into the artifact", () => {
  it("records the train mix and a per-era AUC on every arm it reports", () => {
    const before = BOUNDARY - 200 * day;
    const after = BOUNDARY + 10 * day;
    const mk = (era: string, at: number, i: number, y: 0 | 1): Leg => ({
      at,
      readyAt: at + day,
      market: `mk-${i}`,
      wallet: `wal-${i}`,
      era,
      price: y === 1 ? 0.8 : 0.2,
      detected: y === 1 ? 0.75 : 0.25,
      pnlNetEntry: y === 1 ? 1 : -1,
      y,
      scores: {},
      f: {},
    });
    const legs: Leg[] = [
      ...Array.from({ length: 120 }, (_, i) => mk("pre-kelly-v1-48", before + i * 3_600_000, i, (i % 2) as 0 | 1)),
      ...Array.from({ length: 60 }, (_, i) => mk("kelly-window-v49-57", after + i * 3_600_000, 200 + i, (i % 2) as 0 | 1)),
      ...Array.from({ length: 60 }, (_, i) => mk("exposure-v58plus", after + (i + 60) * 3_600_000, 400 + i, (i % 2) as 0 | 1)),
    ];
    const artifact: Record<string, unknown> = {};
    readArms(legs, "era-read fixture", 50, artifact);
    const entry = artifact["era-read fixture"] as Record<string, unknown>;
    expect(entry.trainEraMix).toEqual([{ era: "pre-kelly-v1-48", n: 120, share: 1 }]);
    expect(entry.trainEraCount).toBe(1);
    expect(entry.testUnseenEraN).toBe(120);
    const arms = entry.arms as Record<string, unknown>[];
    const price = arms.find((a) => a.arm === "entry_price")!;
    const perEra = price.eraAuc as { era: string; seenInTrain: boolean }[];
    // This fixture's test window is entirely AFTER the boundary, so every test era is unseen.
    expect(perEra.map((e) => [e.era, e.seenInTrain])).toEqual([
      ["exposure-v58plus", false],
      ["kelly-window-v49-57", false],
    ]);
    expect(price.unseenEraN).toBe(120);
  });
});

describe("fit populations (claim (2): the fit can no longer be single-era only)", () => {
  it("defaults to BOTH populations — a bare run does not fit on one era", () => {
    expect(parseFitSplitMode([])).toBe("both");
    expect(fitPopulations("both").map((p) => p.mode)).toEqual(["time", "era"]);
    // The published time population keeps its ORIGINAL artifact label, so its numbers stay comparable.
    expect(fitPopulations("time")[0].label).toBe("training_data.csv — the population the model is fitted on");
    expect(fitPopulations("era").map((p) => p.mode)).toEqual(["era"]);
    // Distinct labels, or the two reads would overwrite each other in the artifact.
    const labels = fitPopulations("both").map((p) => p.label);
    expect(new Set(labels).size).toBe(2);
  });

  it("throws on an unknown --split instead of falling back to a single era", () => {
    expect(() => parseFitSplitMode(["--split", "eras"])).toThrow(/--split must be/);
    expect(() => fitPopulations("ear" as never)).toThrow(/unknown mode/);
  });

  it("the era population fits on MULTIPLE eras and holds out only the named regime", () => {
    // Two earlier eras in train, the named regime as test — the window claim (2) says the fit never had.
    const t0 = Date.parse("2026-05-01T00:00:00Z");
    const mk = (era: string, at: number, i: number, y: 0 | 1): Leg => ({
      at,
      readyAt: at + day,
      market: `fp-${i}`,
      wallet: `fpw-${i}`,
      era,
      price: y === 1 ? 0.8 : 0.2,
      detected: y === 1 ? 0.75 : 0.25,
      pnlNetEntry: y === 1 ? 1 : -1,
      y,
      scores: {},
      f: {},
    });
    const legs: Leg[] = [
      ...Array.from({ length: 80 }, (_, i) => mk("pre-kelly-v1-48", t0 + i * day, i, (i % 2) as 0 | 1)),
      ...Array.from({ length: 80 }, (_, i) => mk("kelly-window-v49-57", t0 + (i + 100) * day, 200 + i, (i % 2) as 0 | 1)),
      ...Array.from({ length: 60 }, (_, i) => mk("exposure-v58plus", t0 + (i + 300) * day, 400 + i, (i % 2) as 0 | 1)),
    ];
    const artifact: Record<string, unknown> = {};
    readArms(legs, "era-population fixture", 50, artifact, [], "era");
    const entry = artifact["era-population fixture"] as Record<string, unknown>;
    expect(entry.splitMode).toBe("era");
    expect(entry.trainEraCount).toBe(2);
    expect(entry.trainEraMix).toEqual([
      { era: "kelly-window-v49-57", n: 80, share: 0.5 },
      { era: "pre-kelly-v1-48", n: 80, share: 0.5 },
    ]);
    // The held-out regime is the TEST side and only the test side — a clean regime cut.
    expect(entry.testN).toBe(60);
    expect((entry.eraRead as { era: string; seenInTrain: boolean }[]).map((e) => [e.era, e.seenInTrain])).toEqual([
      ["exposure-v58plus", false],
    ]);
  });
});
