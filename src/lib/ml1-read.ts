/**
 * ML-1 promotion-gate READ, as a library — so the harness that judges a candidate and the
 * script that fits one cannot drift apart (card `phase-ml1`, gate half 2).
 *
 * THE BAR (restated 2026-10-11, do not weaken it):
 *   A candidate promotes only if it beats the PRICE-ONLY baseline on a frozen
 *   TIME-ORDERED holdout — train <= 2026-08-21, test after, label `pnl_net_entry > 0` —
 *   clearing AUC >= 0.729 AND Brier <= 0.212 with a market-CLUSTERED 95% CI on the
 *   difference that excludes 0. Beating `copyScore` proves nothing: it measures AUC
 *   0.474-0.481, i.e. WORSE than the base rate.
 *
 * WHAT `readArms` IS
 *   The comparator, the calibration check and the money arm — plus an optional hook for
 *   a FITTED candidate (`CandidateSpec`). The candidate is trained on THIS split's train
 *   rows only and scored on its test rows, so a fitted arm is judged by exactly the code
 *   that judges the static arms, on exactly the same holdout.
 *
 * SPLITS: every cut goes through `src/lib/splits.ts` — time-ordered, era-reported, purged
 * on the label-ready stamp. No random row folds anywhere; `scripts/check-split-doctrine.py`
 * enforces that repo-wide.
 *
 * Extracted verbatim from scripts/ml1-gate-read.ts on 2026-10-11 (that script's console
 * output and data/ml1-gate-read.json are unchanged, minus `pct`, which was unused).
 */

import * as fs from "fs";
import { timeOrderedHoldout, eraStratifiedHoldout, eraGroups } from "./splits";
import { auc, brier, clusteredBootstrapDelta, constantBrier, mean } from "./metrics";
import { eraOf } from "./training-export";

/** The frozen boundary the bar names. A gate that moves its holdout is not a gate. */
export const BOUNDARY = Date.parse("2026-08-21T00:00:00Z");
/**
 * THE BAR — RESTATED 2026-10-27 (Lane A, approved: "approve ml1-price-baseline-drift").
 *
 * The old form was `AUC >= 0.729 AND Brier <= 0.212` as ABSOLUTE constants. Those were measured
 * 2026-09-13 on data/decision-dataset.csv, where price read 0.7285 / 0.2115 — i.e. 0.729/0.212 IS
 * price rounded to 3dp. They were then applied to the population the fit actually uses
 * (training_data.csv), where price reads 0.7095 / 0.2196. The consequence was not a strict gate but
 * an IMPOSSIBLE one: it demanded +0.0195 AUC of headroom AND a Brier ceiling 0.0076 BELOW price's own
 * Brier. No candidate could ever clear it, so the gate stopped being falsifiable — it could not fail,
 * which is the same defect as a probe that cannot fail.
 *
 * The restated form keeps the ORIGINAL STRICTNESS (the same 0.0005 tolerance) and states it against
 * the comparator the bar names, computed on the SAME scored rows the arm is judged on:
 *     AUC >= price_auc + 0.0005   AND   Brier <= price_brier + 0.0005
 * with the market-clustered CI on ΔAUC still required to exclude 0 (unchanged).
 *
 * This promotes nothing. On 2026-10-27 every stored score sits BELOW price on the fit population
 * (copy_score 0.5130, wallet_quality 0.5099, entry_timing 0.5489, thesis 0.4613 vs price 0.7095), so
 * the restatement changes which numbers get PRINTED as a pass/fail verdict, not what the bot decides.
 *
 * `auc`/`brier` are retained as a REFERENCE LINE only — printed beside every read so the historical
 * 2026-09-13 measurement stays visible and comparable. They are not enforcement.
 */
export const BAR = {
  auc: 0.729,
  brier: 0.212,
  /** The tolerance the absolute form always carried, now applied to the comparator. */
  margin: 0.0005,
  comparator: "price-only (entry_price)",
  form: "relative" as const,
  /** The population the absolute constants were measured on, kept so the drift is auditable. */
  measuredOn: "data/decision-dataset.csv 2026-09-13 (price 0.7285 / 0.2115)",
};

export type Leg = {
  at: number;
  /** Terminal time (when the label became knowable) — the PURGE key. */
  readyAt: number | null;
  market: string;
  wallet: string;
  era: string;
  price: number;
  detected: number;
  pnlNetEntry: number;
  y: 0 | 1;
  scores: Record<string, number>;
  /** Every other numeric column the dataset carries, keyed by its CSV name. */
  f: Record<string, number>;
};

/** A model trained inside the harness on the harness's own train rows. */
export type CandidateSpec = {
  name: string;
  /** Receives ONLY train rows; returns a scorer applied to the test rows. */
  fit: (train: readonly Leg[]) => (l: Leg) => number;
  /** True when the scorer returns a probability (so Brier is meaningful and the bar applies). */
  probability: boolean;
  note?: string;
};

export const SCORE_ARMS = ["copy_score", "wallet_quality_score", "entry_timing_score", "thesis_score"] as const;

function parseCsv(path: string): { header: string[]; rows: string[][] } {
  const text = fs.readFileSync(path, "utf8").trimEnd();
  const lines = text.split("\n");
  return { header: lines[0].split(","), rows: lines.slice(1).map((l) => l.split(",")) };
}

export function loadDecisionDataset(): (Leg & { yWin: number })[] {
  const { header, rows } = parseCsv("data/decision-dataset.csv");
  const col = (n: string) => {
    const i = header.indexOf(n);
    if (i < 0) throw new Error(`decision-dataset.csv is missing column ${n}`);
    return i;
  };
  const num = (v: string) => (v === "" || v === undefined ? null : Number(v));
  const fKeys = ["size_usd", "ttr_hours", "raw_spread", "raw_liquidity", "raw_volume", "confidence", "category_fit_score", "spread_score", "liquidity_score"];
  /** Tolerant: a dataset that lacks a column yields NaN for it rather than throwing. */
  const opt = (r: string[], n: string) => {
    const i = header.indexOf(n);
    return i < 0 ? Number.NaN : num(r[i]) ?? Number.NaN;
  };
  return rows.map((r) => {
    const pnl = num(r[col("pnl_net_entry")]);
    const rsv = num(r[col("rule_set_version")]);
    const f: Record<string, number> = {};
    for (const k of fKeys) f[k] = opt(r, k);
    return {
      at: Date.parse(r[col("opened_at")]),
      // The dataset's own terminal stamp: closed_at, else opened_at (settled legs).
      readyAt: Date.parse(r[col("closed_at")] || r[col("opened_at")]),
      market: r[col("market_id")],
      wallet: r[col("wallet")],
      era: eraOf(rsv === null ? null : rsv),
      price: Number(r[col("entry_price")]),
      detected: num(r[col("detected_price")]) ?? Number.NaN,
      pnlNetEntry: pnl ?? Number.NaN,
      y: (pnl !== null && pnl > 0 ? 1 : 0) as 0 | 1,
      scores: Object.fromEntries(SCORE_ARMS.map((s) => [s, num(r[col(s)]) ?? Number.NaN])),
      f,
      yWin: num(r[col("y_win")]) ?? Number.NaN,
    };
  });
}

export function loadTrainingData(): (Leg & { yOutcome: number | null })[] {
  const { header, rows } = parseCsv("training_data.csv");
  const col = (n: string) => {
    const i = header.indexOf(n);
    if (i < 0) throw new Error(`training_data.csv is missing column ${n}`);
    return i;
  };
  const num = (v: string) => (v === "" || v === undefined ? null : Number(v));
  const fKeys = [
    "size_usd", "observed_size_usd", "horizon_to_resolution_hours", "raw_spread", "raw_liquidity", "raw_volume",
    "confidence", "category_fit_score", "spread_score", "liquidity_score", "fee_rate",
  ];
  /** Tolerant: this export has no `confidence` column, and that must not throw. */
  const opt = (r: string[], n: string) => {
    const i = header.indexOf(n);
    return i < 0 ? Number.NaN : num(r[i]) ?? Number.NaN;
  };
  return rows.map((r) => {
    const out = r[col("y_outcome")];
    const f: Record<string, number> = {};
    for (const k of fKeys) f[k] = opt(r, k);
    return {
      at: Date.parse(r[col("decision_at")]),
      // The export DOES carry the terminal stamp (`terminal_at`, 100% populated since 9468900) and
      // it is the purge key. Hard-coding null made `purged` a structural zero: a train row whose
      // label only became knowable after the boundary kept feeding the future into the fit. Read it.
      readyAt: (() => {
        const i = header.indexOf("terminal_at");
        const p = i < 0 || !r[i] ? Number.NaN : Date.parse(r[i]);
        return Number.isFinite(p) ? p : null;
      })(),
      market: r[col("market_id")],
      wallet: r[col("wallet")],
      era: r[col("era")],
      price: Number(r[col("entry_price")]),
      detected: num(r[col("detected_price")]) ?? Number.NaN,
      pnlNetEntry: num(r[col("pnl_net_entry")]) ?? Number.NaN,
      y: (r[col("y_net_entry")] === "1" ? 1 : 0) as 0 | 1,
      scores: Object.fromEntries(SCORE_ARMS.map((s) => [s, num(r[col(s)]) ?? Number.NaN])),
      f,
      yOutcome: out === "" ? null : Number(out),
    };
  });
}

export const fmt = (v: number, d = 4) => (Number.isNaN(v) || v === null ? "n/a" : v.toFixed(d));

/** The era composition of a TRAIN window, as measured — never assumed. */
export type TrainEraMix = { era: string; n: number; share: number };

/**
 * TRAIN era mix (card `ml1-fit-population-gaps`, claim (2)). A fitted arm inherits whatever
 * window it was given, so the window's era composition belongs in the gate output: a fit whose
 * train is 100% one era is a regime-1 model wearing the clothes of a general one, and the only
 * way to see that in the printed verdict is to print the mix.
 */
export function trainEraMix(train: readonly Leg[]): TrainEraMix[] {
  const counts = new Map<string, number>();
  for (const l of train) {
    const e = l.era ?? "unknown";
    counts.set(e, (counts.get(e) ?? 0) + 1);
  }
  const total = train.length || 1;
  return [...counts.entries()]
    .map(([era, n]) => ({ era, n, share: n / total }))
    .sort((a, b) => a.era.localeCompare(b.era));
}

export type EraAucRow = { era: string; n: number; auc: number; usable: boolean; seenInTrain: boolean };

/**
 * Test AUC WITHIN each era for one ranker. Same rows, same level (leg), same clock as the pooled
 * read — just stratified, so an arm whose pooled AUC is one era's edge cannot hide behind it.
 * `seenInTrain` is the honest flag: on a single-era train window every held-out era is unseen,
 * and an arm scored there is extrapolating, not generalising.
 */
export function eraAucRead(
  test: readonly Leg[],
  get: (l: Leg) => number,
  trainEras: ReadonlySet<string>,
  minN = 30
): EraAucRow[] {
  const byEra = new Map<string, Leg[]>();
  for (const l of test) {
    if (!Number.isFinite(get(l))) continue;
    const e = l.era ?? "unknown";
    const arr = byEra.get(e) ?? [];
    arr.push(l);
    byEra.set(e, arr);
  }
  return [...byEra.entries()]
    .map(([era, list]) => {
      const usable = list.length >= minN && new Set(list.map((l) => l.y)).size > 1;
      return {
        era,
        n: list.length,
        auc: usable ? auc(list.map(get), list.map((l) => l.y)) : Number.NaN,
        usable,
        seenInTrain: trainEras.has(era),
      };
    })
    .sort((a, b) => a.era.localeCompare(b.era));
}

/** The era held out by the era-stratified split. Named once so the gate and the read cannot disagree. */
export const ERA_HOLDOUT = ["exposure-v58plus"] as const;

export type SplitMode = "time" | "era";

export function readArms(
  legs: Leg[],
  label: string,
  iters: number,
  artifact: Record<string, unknown>,
  candidates: CandidateSpec[] = [],
  splitMode: SplitMode = "time"
) {
  const usable = legs.filter((l) => Number.isFinite(l.pnlNetEntry) && Number.isFinite(l.price) && Number.isFinite(l.at));
  const split =
    splitMode === "era"
      ? eraStratifiedHoldout(usable, {
          at: (l) => l.at,
          era: (l) => l.era,
          labelReadyAt: (l) => l.readyAt,
          holdoutEras: ERA_HOLDOUT,
          design: `${label} — era-stratified holdout`,
        })
      : timeOrderedHoldout(usable, {
          at: (l) => l.at,
          era: (l) => l.era,
          labelReadyAt: (l) => l.readyAt,
          boundary: BOUNDARY,
          design: `${label} — frozen time-ordered holdout`,
        });
  const test = split.test;
  const labels = test.map((l) => l.y);

  console.log(`\n### ${label}`);
  console.log(`  ${split.provenance}`);
  console.log(`  test base rate ${fmt(mean(labels))} | constant-predictor Brier ${fmt(constantBrier(labels))} | markets ${new Set(test.map((l) => l.market)).size}`);

  // TRAIN ERA MIX — claim (2) of card `ml1-fit-population-gaps`. Reporting only: the boundary,
  // the split and every bar stay exactly where they were. What changes is that the gate now SAYS
  // which era(s) the fit was allowed to see, instead of leaving it to a roadmap note.
  const trainMix = trainEraMix(split.train);
  const trainEras = new Set(trainMix.map((e) => e.era));
  const testUnseen = test.filter((l) => !trainEras.has(l.era ?? "unknown"));
  console.log(
    `  TRAIN eras (n=${split.train.length}): ` +
      (trainMix.length
        ? trainMix.map((e) => `${e.era} ${e.n} (${(e.share * 100).toFixed(1)}%)`).join(" | ")
        : "none — empty train window")
  );
  if (trainMix.length === 1 && testUnseen.length > 0) {
    console.log(
      `  ^ TRAIN IS SINGLE-ERA (${trainMix[0].era} only). Fitted arms below saw NO row from ` +
        `${testUnseen.length} of ${test.length} test legs: their pooled AUC is extrapolation across eras,` +
        ` and the 'forward-era' number on each arm is that read isolated.`
    );
  }

  const priceAuc = auc(test.map((l) => l.price), labels);
  const priceBrier = brier(test.map((l) => l.price), labels);
  const rows: Record<string, unknown>[] = [];

  /** The read every arm gets, static or fitted — same holdout, same CI, same money arm. */
  const readOne = (name: string, get: (l: Leg) => number, probability: boolean, extra: Record<string, unknown> = {}) => {
    const scored = test.filter((l) => Number.isFinite(get(l)));
    if (scored.length < 30) {
      rows.push({ arm: name, n: scored.length, note: "too few finite scores to read", ...extra });
      console.log(`  ${name.padEnd(22)} n=${scored.length} — too few finite scores to read`);
      return;
    }
    const a = auc(scored.map(get), scored.map((l) => l.y));
    const b = probability ? brier(scored.map(get), scored.map((l) => l.y)) : Number.NaN;
    const delta = clusteredBootstrapDelta(
      scored,
      (l) => l.market,
      (s) => auc(s.map(get), s.map((l) => l.y)),
      (s) => auc(s.map((l) => l.price), s.map((l) => l.y)),
      { iters, seed: 20261011 }
    );
    // Money arm: re-select the top tercile INSIDE each bootstrap draw.
    const selectBy = (s: readonly Leg[], g: (l: Leg) => number) => {
      const ordered = [...s].filter((l) => Number.isFinite(g(l))).sort((x, y2) => g(y2) - g(x));
      return ordered.slice(0, Math.max(1, Math.floor(ordered.length / 3)));
    };
    const money = clusteredBootstrapDelta(
      scored,
      (l) => l.market,
      (s) => mean(selectBy(s, get).map((l) => l.pnlNetEntry)),
      (s) => mean(s.map((l) => l.pnlNetEntry)),
      { iters, seed: 20261011 }
    );

    // Relative bar (2026-10-27): the comparator is recomputed on THIS arm's scored rows, so an arm
    // that scores a different subset is not measured against a baseline from a different population.
    const compAuc = auc(scored.map((l) => l.price), scored.map((l) => l.y));
    const compBrier = brier(scored.map((l) => l.price), scored.map((l) => l.y));
    const aucBar = compAuc + BAR.margin;
    const brierBar = compBrier + BAR.margin;
    const clearsAuc = a >= aucBar;
    const clearsBrier = probability ? b <= brierBar : null;
    // Per-era AUC on THIS arm's own scored rows (reporting only). The pooled number is kept as-is.
    const perEra = eraAucRead(scored, get, trainEras);
    const unseenScored = scored.filter((l) => !trainEras.has(l.era ?? "unknown"));
    const unseenUsable = unseenScored.length >= 30 && new Set(unseenScored.map((l) => l.y)).size > 1;
    const unseenAuc = unseenUsable ? auc(unseenScored.map(get), unseenScored.map((l) => l.y)) : Number.NaN;
    const unseenPriceAuc = unseenUsable ? auc(unseenScored.map((l) => l.price), unseenScored.map((l) => l.y)) : Number.NaN;

    rows.push({
      arm: name,
      n: scored.length,
      auc: a,
      brier: probability ? b : null,
      beatsPriceCiLow: delta.low,
      beatsPriceCiHigh: delta.high,
      deltaAuc: delta.point,
      pGreater: delta.pGreater,
      clearsAucBar: clearsAuc,
      clearsBrierBar: clearsBrier,
      // audit trail for the restated bar: what the comparator read HERE, and the resulting bar
      comparatorAuc: compAuc,
      comparatorBrier: compBrier,
      aucBar,
      brierBar,
      barForm: BAR.form,
      barMargin: BAR.margin,
      topTercileMeanPnl: money.point,
      topTercileVsCopyAllCi: [money.low, money.high],
      topTercileN: selectBy(scored, get).length,
      eraAuc: perEra,
      unseenEraN: unseenScored.length,
      unseenEraAuc: Number.isNaN(unseenAuc) ? null : unseenAuc,
      unseenEraPriceAuc: Number.isNaN(unseenPriceAuc) ? null : unseenPriceAuc,
      ...extra,
    });
    console.log(
      `  ${name.padEnd(22)} n=${String(scored.length).padStart(4)} AUC ${fmt(a)}` +
        (probability ? ` Brier ${fmt(b)}` : ` Brier n/a (not a probability)`) +
        ` | ΔAUC vs price ${fmt(delta.point, 4)} CI [${fmt(delta.low)}, ${fmt(delta.high)}] P(>) ${fmt(delta.pGreater, 3)}` +
        ` | topTercile $/leg ${fmt(money.point, 2)} vs copy-all, CI [${fmt(money.low, 2)}, ${fmt(money.high, 2)}]`
    );
    if (perEra.length > 1) {
      console.log(
        `  ${"".padEnd(22)} AUC by era: ` +
          perEra
            .map((e) => `${e.seenInTrain ? "" : "*"}${e.era} ${fmt(e.auc)} (n=${e.n})`)
            .join(" | ") +
          `   [* = era absent from train]`
      );
    }
    if (unseenUsable) {
      console.log(
        `  ${"".padEnd(22)} forward-era (unseen in train) n=${unseenScored.length} AUC ${fmt(unseenAuc)}` +
          ` vs price ${fmt(unseenPriceAuc)} (Δ ${fmt(unseenAuc - unseenPriceAuc, 4)})`
      );
    }
  };

  const armList: { name: string; get: (l: Leg) => number; probability: boolean }[] = [
    { name: "entry_price", get: (l) => l.price, probability: true },
    { name: "detected_price", get: (l) => l.detected, probability: true },
    ...SCORE_ARMS.map((s) => ({ name: s, get: (l: Leg) => l.scores[s], probability: false })),
  ];
  for (const arm of armList) readOne(arm.name, arm.get, arm.probability);

  for (const cand of candidates) {
    const score = cand.fit(split.train);
    readOne(cand.name, score, cand.probability, { fitted: true, note: cand.note ?? "fitted on this split's train rows" });
    // In-sample read, so the overfit gap is visible instead of implied.
    const trainScored = split.train.filter((l) => Number.isFinite(score(l)));
    if (trainScored.length >= 30) {
      const trainAuc = auc(trainScored.map(score), trainScored.map((l) => l.y));
      (rows[rows.length - 1] as Record<string, unknown>)["trainAucInsample"] = trainAuc;
      console.log(`  ${"".padEnd(22)} in-sample (train) AUC ${fmt(trainAuc)} — gap to the test AUC is the overfit read`);
    }
  }

  console.log(`  PRICE-ONLY (the bar's comparator): AUC ${fmt(priceAuc)} Brier ${fmt(priceBrier)}`);
  // Per-era read — criterion (d) of the pre-registered shadow read, applied to AUC:
  // a sign that only holds in one era is not a signal, it is a policy artifact.
  const eras = eraGroups(test, (l) => l.era);
  const eraRows: { era: string; n: number; priceAuc: number; priceAucUsable: boolean; seenInTrain: boolean }[] = [];
  for (const [era, list] of [...eras.entries()].sort()) {
    const eLabels = list.map((l) => l.y);
    const eAuc = list.length >= 30 ? auc(list.map((l) => l.price), eLabels) : Number.NaN;
    eraRows.push({ era, n: list.length, priceAuc: eAuc, priceAucUsable: !Number.isNaN(eAuc), seenInTrain: trainEras.has(era) });
    console.log(
      `    era ${(trainEras.has(era) ? "" : "*")}${era.padEnd(19)} n=${String(list.length).padStart(4)} price-only AUC ${fmt(eAuc)}` +
        (Number.isNaN(eAuc) ? " (too few rows or one class — not read)" : "")
    );
  }

  artifact[label] = {
    provenance: split.provenance,
    boundary: new Date(split.boundary).toISOString(),
    splitMode,
    trainN: split.trainN,
    testN: split.testN,
    purged: split.purged,
    tiedAtBoundary: split.tiedAtBoundary,
    testBaseRate: mean(labels),
    constantBrier: constantBrier(labels),
    priceOnly: { auc: priceAuc, brier: priceBrier },
    arms: rows,
    eraRead: eraRows,
    trainEraMix: trainMix,
    trainEraCount: trainMix.length,
    testUnseenEraN: testUnseen.length,
  };

  // Returned so a caller can put an EXTRA read on exactly these rows instead of
  // re-deriving the split (a second split is a second experiment).
  return { train: split.train, test };
}
