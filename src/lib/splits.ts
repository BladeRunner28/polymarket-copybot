/**
 * Shared split utility — time-ordered + era-aware splits, never random row folds
 * (card `ml-doctrine-time-and-era-splits`).
 *
 * WHY THIS EXISTS AS ONE MODULE
 * -----------------------------
 * Every fit/eval script in scripts/ rolled its own folds. The designs were right
 * (`fit-price-edge.py` = wallet-blocked + walk-forward), but each one was prose in
 * its own header, so nothing could CHECK them and nothing forced a report to name
 * its split. Two measured facts make that a real risk on this project rather than a
 * stylistic preference:
 *
 *   * the label set spans ruleSetVersion v1..v6x and the feature vector contains
 *     POLICY OUTPUTS (copyScore and friends are the ruleset's own decisions), so a
 *     random-row fold lets the model read its own era's answer back — it teaches the
 *     average of ~50 policies and reports the retirement as the improvement;
 *   * the era read INVERTS between the two labeled artifacts we hold (the old
 *     OutcomeReview export ranked the live era worst on a binary was_good; the
 *     re-pointed acted book ranks it best on net-entry PnL — 42.7% win rate at
 *     +$6.06/leg vs pre-kelly 58.8% at +$0.34), which is exactly the kind of
 *     disagreement a pooled random fold averages away.
 *
 * WHAT IT GUARANTEES
 * ------------------
 *   1. TIME ORDER. `timeOrderedHoldout` splits by a timestamp, never by index into a
 *      shuffled list, and returns the boundary it used plus the row counts.
 *   2. PURGE (no test-window leakage). A training row whose LABEL was not knowable
 *      before the test window opened is dropped and counted. Without this, a leg
 *      that settled inside the test window can be trained on — the classic walk-
 *      forward leak that makes a model look prescient.
 *   3. ERA PROVENANCE. Every split carries per-era train/test counts and the list of
 *      eras present on both sides, so a report can quote its era mix instead of
 *      implying the population is homogeneous.
 *   4. IDENTICAL FOLDS IN BOTH LANGUAGES. `crc32` is the zlib/IEEE polynomial, so
 *      `assignBlockedFold(wallet, k)` gives the SAME fold number as Python's
 *      `zlib.crc32(x.encode()) % k` in `scripts/fit-price-edge.py`. The Python mirror
 *      is `scripts/lib/splits.py`; `tests/splits.test.ts` pins the cross-language
 *      values.
 *
 * WHAT IT DELIBERATELY DOES NOT OFFER
 * -----------------------------------
 * There is no shuffled/random-row fold function here. That is the point: a caller
 * cannot reach for one, and `scripts/check-split-doctrine.py` fails the build if a
 * script imports a random-fold API (`KFold`, `train_test_split`, `cross_val_score`)
 * instead of this module. Bootstrap RESAMPLING (with replacement, clustered by
 * market/wallet) is still legitimate and lives with the metric code — the ban is on
 * random folds for model selection.
 */

/** CRC-32 (IEEE 802.3, zlib-compatible) — same numbers as Python's `zlib.crc32`. */
const CRC_TABLE: Uint32Array = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

export function crc32(s: string): number {
  const bytes = new TextEncoder().encode(s);
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/** Deterministic blocked fold for a group key (wallet / market / question). */
export function assignBlockedFold(key: string, k: number): number {
  if (!Number.isInteger(k) || k < 2) throw new Error(`assignBlockedFold: k must be an integer >= 2 (got ${k})`);
  return crc32(key) % k;
}

/** k group-blocked folds. Every row of one group lands in exactly one fold. */
export function blockedFolds<T>(rows: readonly T[], key: (r: T) => string, k = 5): { folds: T[][]; sizes: number[] } {
  const folds: T[][] = Array.from({ length: k }, () => []);
  for (const r of rows) folds[assignBlockedFold(key(r), k)].push(r);
  return { folds, sizes: folds.map((f) => f.length) };
}

/** The line a report MUST quote: names the design, the boundary, the n's and the eras. */
export function formatProvenance(p: {
  design: string;
  boundary: string;
  trainN: number;
  testN: number;
  purgeNote?: string;
  eraTrain: Record<string, number>;
  eraTest: Record<string, number>;
  overlapEras: string[];
}): string {
  const eras = (m: Record<string, number>) =>
    Object.entries(m)
      .sort((a, b) => b[1] - a[1])
      .map(([e, n]) => `${e}:${n}`)
      .join(",") || "none";
  const overlap = p.overlapEras.length ? p.overlapEras.join(",") : "none";
  return (
    `${p.design} | boundary ${p.boundary} | train n=${p.trainN} | test n=${p.testN}` +
    ` | eras train [${eras(p.eraTrain)}] test [${eras(p.eraTest)}] | eras on both sides: ${overlap}` +
    (p.purgeNote ? ` | ${p.purgeNote}` : "")
  );
}

export type TimeSplit<T> = {
  train: T[];
  test: T[];
  /** First test timestamp (ms epoch). Rows before it are train. */
  boundary: number;
  trainN: number;
  testN: number;
  /** Test rows sharing the boundary timestamp — a tie group never straddles the cut. */
  tiedAtBoundary: number;
  /** Train rows dropped because their label was not knowable before the boundary. */
  purged: number;
  eraTrain: Record<string, number>;
  eraTest: Record<string, number>;
  overlapEras: string[];
  provenance: string;
};

/**
 * ERA-STRATIFIED HOLDOUT — approved 2026-10-28 ("All 5 are approved"), card `ml1-fit-population-gaps`
 * claim (2), option (a) of its own recommendation.
 *
 * THE PROBLEM IT SOLVES: the ML-1 gate cuts at a frozen calendar date (2026-08-21). Measured 2026-10-26,
 * that date puts 100% of the train window in ONE regime (pre-kelly-v1-48) while the test window spans
 * three (pre-kelly 960 / kelly-window 841 / exposure-v58plus 826) — so a fit that has only ever seen
 * regime 1 is scored across regimes 1-3, and "weak model" is indistinguishable from "never saw this
 * regime". That is the leading explanation for in-sample AUC 0.744 landing at 0.68-0.70 OOS.
 *
 * THIS SPLIT cuts on REGIME instead of on an arbitrary date: hold out the named era(s) as the test set.
 * It is still strictly forward in time — `eraOf` keys on ruleSetVersion, which only ever increases, so
 * the held-out era is chronologically after the train eras by construction. The difference is that the
 * test set is a REGIME rather than a slice, which is the thing a promotion bar should be forward about.
 *
 * THE PURGE MATTERS MORE HERE, NOT LESS: eras partition when a leg was OPENED, not when it SETTLED. A
 * long-dated regime-2 leg can resolve well inside regime 3, so any train row whose label only became
 * knowable at/after the first test row is dropped exactly as in the time-ordered split.
 *
 * TRADE-OFF, stated rather than hidden: this trains on everything before the held-out era, which is MORE
 * data than a date cut gives (good), but the comparison to the old bar is no longer apples-to-apples
 * because the test population changes. Both are therefore reported side by side, never merged.
 */
export function eraStratifiedHoldout<T>(
  rows: readonly T[],
  opts: {
    at: (r: T) => number;
    era: (r: T) => string | null;
    labelReadyAt?: (r: T) => number | null;
    /** The era name(s) composing the TEST set. Everything else is train. */
    holdoutEras: readonly string[];
    design?: string;
    purge?: boolean;
  }
): TimeSplit<T> {
  const purge = opts.purge ?? true;
  const design = opts.design ?? "era-stratified holdout";
  if (rows.length === 0) throw new Error("eraStratifiedHoldout: no rows");
  if (opts.holdoutEras.length === 0) throw new Error("eraStratifiedHoldout: holdoutEras is empty");

  const held = new Set(opts.holdoutEras);
  const isTest = (r: T) => held.has(opts.era(r) ?? "unknown");

  const test = rows.filter(isTest);
  const trainAll = rows.filter((r) => !isTest(r));
  if (test.length === 0) {
    throw new Error(
      `eraStratifiedHoldout: no row falls in the held-out era(s) ${opts.holdoutEras.join(", ")} — ` +
        `refusing to report an empty test set as a result`
    );
  }
  if (trainAll.length === 0) {
    throw new Error(`eraStratifiedHoldout: holding out ${opts.holdoutEras.join(", ")} leaves no train rows`);
  }

  // The boundary is the FIRST test timestamp: labels knowable at or after it cannot inform the fit.
  const boundary = Math.min(...test.map(opts.at));

  let dropped = 0;
  const train: T[] = [];
  for (const r of trainAll) {
    const ready = opts.labelReadyAt?.(r);
    if (purge && opts.labelReadyAt && ready !== null && ready !== undefined && ready >= boundary) {
      dropped += 1;
      continue;
    }
    train.push(r);
  }
  if (train.length === 0) {
    throw new Error("eraStratifiedHoldout: the purge removed every train row — the eras are not separable");
  }

  const count = (xs: readonly T[]) => {
    const m: Record<string, number> = {};
    for (const r of xs) {
      const e = opts.era(r) ?? "unknown";
      m[e] = (m[e] ?? 0) + 1;
    }
    return m;
  };
  const eraTrain = count(train);
  const eraTest = count(test);
  const overlapEras = Object.keys(eraTrain).filter((e) => e in eraTest).sort();
  const tiedAtBoundary = test.filter((r) => opts.at(r) === boundary).length;

  return {
    train,
    test,
    boundary,
    trainN: train.length,
    testN: test.length,
    tiedAtBoundary,
    purged: dropped,
    eraTrain,
    eraTest,
    overlapEras,
    provenance:
      `${design}: test = era(s) [${opts.holdoutEras.join(", ")}] (n=${test.length}), ` +
      `train = all other eras BEFORE ${new Date(boundary).toISOString()} minus ${dropped} purged label-tails ` +
      `(n=${train.length}); held-out regime is later by ruleSetVersion by construction; ` +
      `overlapping eras ${overlapEras.length ? `[${overlapEras.join(", ")}]` : "none (clean regime cut)"}`,
  };
}

/**
 * Time-ordered holdout. Sort by `at`, cut once, optionally purge train rows whose
 * label only became knowable inside the test window.
 *
 * `frac` is the TRAIN share (default 0.70). `boundary` (ms epoch) pins the cut to a
 * frozen date instead — required whenever a gate names its own boundary, because a
 * fraction-derived cut silently moves as the book grows and a bar measured on a
 * moving holdout is not a bar.
 */
export function timeOrderedHoldout<T>(
  rows: readonly T[],
  opts: {
    at: (r: T) => number;
    era?: (r: T) => string | null;
    /** When the row's LABEL was knowable (e.g. terminalAt). Enables the purge. */
    labelReadyAt?: (r: T) => number | null;
    frac?: number;
    boundary?: number;
    design?: string;
    purge?: boolean;
  }
): TimeSplit<T> {
  const at = opts.at;
  const era = opts.era;
  const purge = opts.purge ?? true;
  const design = opts.design ?? "time-ordered holdout";
  if (rows.length === 0) {
    throw new Error("timeOrderedHoldout: no rows");
  }
  // Stable sort by (timestamp, original index) so a re-run produces the same split.
  const indexed = rows.map((r, i) => ({ r, i, t: at(r) }));
  indexed.sort((a, b) => (a.t === b.t ? a.i - b.i : a.t - b.t));

  const boundary = opts.boundary ?? (() => {
    const frac = opts.frac ?? 0.7;
    if (!(frac > 0 && frac < 1)) throw new Error(`timeOrderedHoldout: frac must be in (0,1) (got ${frac})`);
    return indexed[Math.min(indexed.length - 1, Math.floor(indexed.length * frac))].t;
  })();

  const isTest = (t: number) => t >= boundary;
  const test = indexed.filter((x) => isTest(x.t)).map((x) => x.r);
  const trainAll = indexed.filter((x) => !isTest(x.t));
  if (test.length === 0) throw new Error(`timeOrderedHoldout: boundary ${boundary} puts every row in train`);
  if (trainAll.length === 0) throw new Error(`timeOrderedHoldout: boundary ${boundary} puts every row in test`);

  // PURGE: drop train rows whose label was not knowable before the test window opened.
  let dropped = 0;
  const train: T[] = [];
  for (const x of trainAll) {
    const ready = opts.labelReadyAt?.(x.r);
    if (purge && opts.labelReadyAt && ready !== null && ready !== undefined && ready > boundary) {
      dropped += 1;
      continue;
    }
    train.push(x.r);
  }

  const count = (list: readonly T[]): Record<string, number> => {
    const m: Record<string, number> = {};
    if (!era) return m;
    for (const r of list) {
      const e = era(r) ?? "unknown";
      m[e] = (m[e] ?? 0) + 1;
    }
    return m;
  };
  const eraTrain = count(train);
  const eraTest = count(test);
  const overlapEras = Object.keys(eraTrain).filter((e) => e in eraTest);
  // How many TEST rows share the boundary timestamp — i.e. how wide the tie group the
  // cut sits inside is. Ties never straddle the cut (the `>=` rule sends them all to
  // test), so this is a "how sharp is this boundary" flag, not a leakage warning.
  const tiedAtBoundary = test.filter((r) => at(r) === boundary).length;

  return {
    train,
    test,
    boundary,
    trainN: train.length,
    testN: test.length,
    tiedAtBoundary,
    purged: dropped,
    eraTrain,
    eraTest,
    overlapEras,
    provenance: formatProvenance({
      design,
      boundary: new Date(boundary).toISOString(),
      trainN: train.length,
      testN: test.length,
      purgeNote: opts.labelReadyAt ? `purged ${dropped} train rows labelled after the boundary` : "purge: n/a (no label timestamp given)",
      eraTrain,
      eraTest,
      overlapEras,
    }),
  };
}

export type WalkForwardWindow<T> = {
  /** e.g. "2026-08" — the evaluation slice's label. */
  label: string;
  train: T[];
  test: T[];
  provenance: string;
};

/**
 * Expanding-window walk-forward: fit on strictly earlier slices, evaluate on the
 * next. Mirrors `folds_time` in scripts/fit-price-edge.py (min 100 train / 50 eval)
 * but adds the purge, which that version did not have.
 */
export function walkForward<T>(
  rows: readonly T[],
  opts: {
    at: (r: T) => number;
    /** Slice label for a row (defaults to its UTC year-month). */
    slice?: (r: T) => string;
    era?: (r: T) => string | null;
    labelReadyAt?: (r: T) => number | null;
    minTrain?: number;
    minEval?: number;
  }
): WalkForwardWindow<T>[] {
  const slice = opts.slice ?? ((r: T) => new Date(opts.at(r)).toISOString().slice(0, 7));
  const minTrain = opts.minTrain ?? 100;
  const minEval = opts.minEval ?? 50;
  const sorted = [...rows].sort((a, b) => opts.at(a) - opts.at(b));
  const labels = [...new Set(sorted.map(slice))].sort();
  const out: WalkForwardWindow<T>[] = [];
  for (const label of labels) {
    const testAll = sorted.filter((r) => slice(r) === label);
    if (testAll.length < minEval) continue;
    const windowStart = Math.min(...testAll.map(opts.at));
    let train = sorted.filter((r) => slice(r) < label);
    let dropped = 0;
    if (opts.labelReadyAt) {
      const kept: T[] = [];
      for (const r of train) {
        const ready = opts.labelReadyAt(r);
        if (ready !== null && ready !== undefined && ready > windowStart) {
          dropped += 1;
          continue;
        }
        kept.push(r);
      }
      train = kept;
    }
    if (train.length < minTrain) continue;
    out.push({
      label,
      train,
      test: testAll,
      provenance: formatProvenance({
        design: "expanding-window walk-forward",
        boundary: new Date(windowStart).toISOString(),
        trainN: train.length,
        testN: testAll.length,
        purgeNote: opts.labelReadyAt ? `purged ${dropped} train rows labelled after the window opened` : "purge: n/a",
        eraTrain: countEras(train, opts.era),
        eraTest: countEras(testAll, opts.era),
        overlapEras: Object.keys(countEras(train, opts.era)).filter((e) => e in countEras(testAll, opts.era)),
      }),
    });
  }
  return out;
}

function countEras<T>(rows: readonly T[], era?: (r: T) => string | null): Record<string, number> {
  const m: Record<string, number> = {};
  if (!era) return m;
  for (const r of rows) {
    const e = era(r) ?? "unknown";
    m[e] = (m[e] ?? 0) + 1;
  }
  return m;
}

/** Per-era subsets — the read criterion (d) of the ML-1 gate needs ("same sign in each era"). */
export function eraGroups<T>(rows: readonly T[], era: (r: T) => string | null): Map<string, T[]> {
  const m = new Map<string, T[]>();
  for (const r of rows) {
    const e = era(r) ?? "unknown";
    const list = m.get(e) ?? [];
    list.push(r);
    m.set(e, list);
  }
  return m;
}
