/**
 * ML-1 candidate FIT — the missing piece on card `phase-ml1`: the harness could judge a
 * candidate, but there was nothing fitted to judge ("what remains on this card is the fit
 * + the shadow A/B itself").
 *
 * PRE-REGISTERED CANDIDATE FAMILY (stated before the run, so the result cannot choose it):
 *
 *   C0 fit_price_only      logit(entry_price)                                  — ANCHOR
 *   C1 fit_price_stored    C0 + the stored components (copy_score, confidence,
 *                          wallet_quality, category_fit, entry_timing, spread,
 *                          liquidity, thesis)
 *   C2 fit_price_exec      C0 + execution features (log size, spread, log liquidity,
 *                          log volume, log ttr, detected−entry gap)
 *   C3 fit_price_combined  C1 ∪ C2
 *
 * WHY C0 EXISTS: it is a monotone transform of price, so its test AUC MUST equal the
 * price-only AUC of the same holdout. If it does not, the fitter or the wiring is wrong
 * and no fitted read counts. Its Brier may beat price's, because a fitted monotone map
 * calibrates where raw price is over-confident — that difference is a calibration gain,
 * not ranking information, and the report says so.
 *
 * FEATURE AVAILABILITY IS PER POPULATION, and that is reported, not hidden: the re-pointed
 * export carries no `confidence` column, so C1 there is price + the stored components that
 * exist. A feature present on <90% of a population's train rows is dropped from that
 * candidate on that population and named in the output.
 *
 * RIDGE STRENGTH: chosen by an INNER time-ordered holdout of the TRAIN window only (never
 * on the test window, never by a random split — `scripts/check-split-doctrine.py` bans
 * random folds repo-wide).
 *
 * WHAT THIS DOES NOT DO: no promotion, no rule/threshold/size change, no lane touched. It
 * writes `data/ml1-fit-candidate.json` and prints the read. Promotion is a separate,
 * operator-approved step.
 *
 * Usage:  npx tsx scripts/ml1-fit-candidate.ts [--iters 2000]
 */

import * as fs from "fs";
import { fitRidgeLogistic, pickL2ByInnerTimeSplit, type LogisticModel } from "../src/lib/logistic";
import {
  BAR,
  BOUNDARY,
  fmt,
  loadDecisionDataset,
  loadTrainingData,
  readArms,
  type CandidateSpec,
  type Leg,
} from "../src/lib/ml1-read";

const clampP = (p: number) => Math.min(Math.max(p, 1e-6), 1 - 1e-6);
const logit = (p: number) => Math.log(clampP(p) / (1 - clampP(p)));
const log1pOrNaN = (v: number) => (Number.isFinite(v) && v > 0 ? Math.log1p(v) : Number.NaN);
/** First finite value among the named columns (the two exports name ttr differently). */
const firstFinite = (l: Leg, keys: string[]) => {
  for (const k of keys) {
    const v = l.f[k];
    if (Number.isFinite(v)) return v;
  }
  return Number.NaN;
};

/** Named feature builders. A missing input yields NaN, and the row drops out of THAT candidate. */
const FEATURES: Record<string, (l: Leg) => number> = {
  logit_price: (l) => logit(l.price),
  copy_score: (l) => l.scores["copy_score"],
  confidence: (l) => l.f["confidence"],
  wallet_quality_score: (l) => l.scores["wallet_quality_score"],
  category_fit_score: (l) => l.f["category_fit_score"],
  entry_timing_score: (l) => l.scores["entry_timing_score"],
  spread_score: (l) => l.f["spread_score"],
  liquidity_score: (l) => l.f["liquidity_score"],
  thesis_score: (l) => l.scores["thesis_score"],
  log_size: (l) => log1pOrNaN(l.f["size_usd"]),
  raw_spread: (l) => l.f["raw_spread"],
  log_liquidity: (l) => log1pOrNaN(l.f["raw_liquidity"]),
  log_volume: (l) => log1pOrNaN(l.f["raw_volume"]),
  log_ttr: (l) => log1pOrNaN(firstFinite(l, ["ttr_hours", "horizon_to_resolution_hours"])),
  price_gap: (l) => (Number.isFinite(l.detected) ? l.detected - l.price : Number.NaN),
};

const STORED = ["copy_score", "confidence", "wallet_quality_score", "category_fit_score", "entry_timing_score", "spread_score", "liquidity_score", "thesis_score"];
const EXEC = ["log_size", "raw_spread", "log_liquidity", "log_volume", "log_ttr", "price_gap"];
const MIN_FEATURE_COVERAGE = 0.9;

type Cand = {
  spec: CandidateSpec;
  keys: string[];
  usedKeys: string[];
  droppedKeys: string[];
  fitted?: LogisticModel;
  l2?: number;
  innerAuc?: Record<string, number>;
  droppedRows?: number;
};

const candidates: Cand[] = [
  { spec: { name: "C0_fit_price_only", probability: true, fit: () => () => Number.NaN, note: "ANCHOR — monotone in price, so its AUC must equal price-only" }, keys: ["logit_price"], usedKeys: [], droppedKeys: [] },
  { spec: { name: "C1_fit_price_stored", probability: true, fit: () => () => Number.NaN, note: "price + the stored component scores" }, keys: ["logit_price", ...STORED], usedKeys: [], droppedKeys: [] },
  { spec: { name: "C2_fit_price_exec", probability: true, fit: () => () => Number.NaN, note: "price + execution features" }, keys: ["logit_price", ...EXEC], usedKeys: [], droppedKeys: [] },
  { spec: { name: "C3_fit_price_combined", probability: true, fit: () => () => Number.NaN, note: "price + stored + execution" }, keys: ["logit_price", ...STORED, ...EXEC], usedKeys: [], droppedKeys: [] },
];

/** Design matrix for one candidate over the rows handed in (rows missing a used feature drop). */
function design(rows: readonly Leg[], keys: string[]) {
  const X: number[][] = [];
  const y: (0 | 1)[] = [];
  const kept: Leg[] = [];
  for (const l of rows) {
    const x = keys.map((k) => FEATURES[k](l));
    if (x.some((v) => !Number.isFinite(v))) continue;
    X.push(x);
    y.push(l.y);
    kept.push(l);
  }
  return { X, y, kept };
}

for (const cand of candidates) {
  cand.spec.fit = (trainAll: readonly Leg[]) => {
    // The harness hands over TRAIN rows only.
    const coverage = (k: string) => trainAll.filter((l) => Number.isFinite(FEATURES[k](l))).length / trainAll.length;
    cand.usedKeys = cand.keys.filter((k) => coverage(k) >= MIN_FEATURE_COVERAGE);
    cand.droppedKeys = cand.keys.filter((k) => !cand.usedKeys.includes(k));

    const { X, y, kept } = design(trainAll, cand.usedKeys);
    cand.droppedRows = trainAll.length - kept.length;
    if (kept.length < 50) throw new Error(`${cand.spec.name}: only ${kept.length} train rows usable`);

    const picked = pickL2ByInnerTimeSplit(kept, X, y);
    cand.l2 = picked.l2;
    cand.innerAuc = picked.innerAuc;
    const model = fitRidgeLogistic(X, y, { l2: picked.l2 });
    cand.fitted = model;

    console.log(
      `  [fit] ${cand.spec.name.padEnd(22)} train n=${kept.length} (dropped ${cand.droppedRows} rows missing a used feature)` +
        ` | features ${cand.usedKeys.length}${cand.droppedKeys.length ? ` (unavailable here: ${cand.droppedKeys.join(", ")})` : ""}` +
        ` | l2=${picked.l2} on an inner time-ordered holdout (n=${picked.innerN}; ` +
        `${Object.entries(picked.innerAuc).map(([k, v]) => `${k}:${fmt(v, 3)}`).join(" ")})` +
        ` | in-sample AUC ${fmt(model.aucInsample)} logloss ${fmt(model.logLoss)} iters ${model.iters}`
    );

    return (l: Leg) => {
      const x = cand.usedKeys.map((k) => FEATURES[k](l));
      return x.some((v) => !Number.isFinite(v)) ? Number.NaN : model.predictRow(x);
    };
  };
}

/** Extra reads on exactly the harness's test rows: calibration slope and top-tercile composition. */
function calibrate(
  testRows: readonly Leg[],
  population: string,
  artifact: Record<string, unknown>,
  armRows: Record<string, unknown>[]
) {
  const store: Record<string, unknown> = {};
  for (const c of candidates) {
    const arm = armRows.find((a) => a.arm === c.spec.name);
    const entry: Record<string, unknown> = {
      usedFeatures: c.usedKeys,
      unavailableFeatures: c.droppedKeys,
      trainRowsDroppedForMissingFeatures: c.droppedRows,
      l2: c.l2,
      innerHoldoutAuc: c.innerAuc,
      testRead: arm ? { n: arm.n, auc: arm.auc, brier: arm.brier, deltaAuc: arm.deltaAuc, ci: [arm.beatsPriceCiLow, arm.beatsPriceCiHigh], pGreater: arm.pGreater, clearsAucBar: arm.clearsAucBar, clearsBrierBar: arm.clearsBrierBar } : null,
    };
    if (c.fitted) {
      const scored = testRows.filter((l) => c.usedKeys.every((k) => Number.isFinite(FEATURES[k](l))));
      if (scored.length >= 50) {
        const probs = scored.map((l) => c.fitted!.predictRow(c.usedKeys.map((k) => FEATURES[k](l))));
        const slope = fitRidgeLogistic(probs.map((p) => [logit(p)]), scored.map((l) => l.y), { l2: 0 });
        entry["testCalibrationSlope"] = slope.beta[0];
        console.log(
          `  ${c.spec.name.padEnd(22)} test calibration slope ${fmt(slope.beta[0], 3)} on n=${scored.length} (1.0 = the probabilities are the probabilities)`
        );
      }
    }
    store[c.spec.name] = entry;
  }
  (artifact["fittedCandidates"] as Record<string, unknown>)[population] = store;
}

function main() {
  const iters = (() => {
    const i = process.argv.indexOf("--iters");
    return i >= 0 ? Number(process.argv[i + 1]) : 2000;
  })();
  console.log("ML-1 candidate fit — a pre-registered family judged by the same harness as the static arms");
  console.log(`  bar (restated 2026-10-11): AUC >= ${BAR.auc} AND Brier <= ${BAR.brier} vs price-only, frozen time-ordered holdout`);
  console.log(`  frozen boundary: ${new Date(BOUNDARY).toISOString()} | bootstrap ${iters} iters, seed 20261011, clustered by market_id`);
  console.log("  candidates: C0 price-only (anchor) | C1 price+stored | C2 price+exec | C3 combined");

  const artifact: Record<string, unknown> = {
    bar: BAR,
    iters,
    boundary: new Date(BOUNDARY).toISOString(),
    preregisteredFamily: candidates.map((c) => ({ name: c.spec.name, features: c.keys, note: c.spec.note })),
    fittedCandidates: {},
  };

  const td = loadTrainingData() as unknown as Leg[];
  const tdLabel = "training_data.csv — the population the model is fitted on";
  const tdSplit = readArms(td, tdLabel, iters, artifact, candidates.map((c) => c.spec));
  calibrate(tdSplit.test, tdLabel, artifact, (artifact[tdLabel] as { arms: Record<string, unknown>[] }).arms);

  const dd = loadDecisionDataset() as unknown as Leg[];
  const ddLabel = "decision-dataset.csv — the bar's population, same candidates";
  const ddSplit = readArms(dd, ddLabel, iters, artifact, candidates.map((c) => c.spec));
  calibrate(ddSplit.test, ddLabel, artifact, (artifact[ddLabel] as { arms: Record<string, unknown>[] }).arms);

  fs.writeFileSync("data/ml1-fit-candidate.json", JSON.stringify(artifact, null, 2) + "\n");
  console.log(`\nwrote data/ml1-fit-candidate.json (${JSON.stringify(artifact).length} bytes)`);
  console.log("reproduce: npx tsx scripts/ml1-fit-candidate.ts");
}

main();
