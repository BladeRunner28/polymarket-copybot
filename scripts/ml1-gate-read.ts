/**
 * ML-1 promotion-gate read — the CLI half. The comparators, the calibration check and the
 * money arm live in `src/lib/ml1-read.ts`, so a FITTED candidate
 * (`scripts/ml1-fit-candidate.ts`) is judged by the same code on the same holdout instead
 * of by a forked copy of it. This file only wires the populations and writes the artifact.
 *
 * THE BAR (restated 2026-10-11, do not weaken it):
 *   A candidate promotes only if it beats the PRICE-ONLY baseline on a frozen
 *   TIME-ORDERED holdout of the decision dataset — train <= 2026-08-21, test after,
 *   label `pnl_net_entry > 0` — clearing AUC >= 0.729 AND Brier <= 0.212 with a
 *   market-CLUSTERED 95% CI on the difference that excludes 0. Beating `copyScore`
 *   proves nothing: it measures AUC 0.474-0.481, i.e. WORSE than the base rate.
 *
 * WHAT THIS SCRIPT IS: the comparator and the calibration check, not a candidate.
 *
 *   1. CALIBRATION. Run on `data/decision-dataset.csv` (the frozen Python artifact the
 *      bar was measured on) it must reproduce the recorded price-only numbers
 *      (AUC 0.7285 / Brier 0.2115 / test n=1,055 on the net label). If it does not,
 *      the harness is wrong and no read from it counts. That check is printed, not
 *      assumed.
 *   2. COMPARATORS on the same holdout: entry_price (the bar), detected_price, the
 *      stored component scores, and the stored `copy_score`. All are rankers of the
 *      same rows, so they are directly comparable — none of them is fitted here.
 *   3. MONEY ARM. Top-tercile selection by each score vs copy-all on `pnl_net_entry`
 *      per leg, with a paired market-clustered CI. AUC is not money; the wallet-side
 *      promotion gate (U2) failed at exactly this step while its AUCs looked fine.
 *
 * WHAT IT IS NOT: no model is trained, nothing is promoted, no rule, threshold, size or
 * published lane number is touched. It writes `data/ml1-gate-read.json` (evidence) and
 * prints the read.
 *
 * Usage:  npx tsx scripts/ml1-gate-read.ts [--iters 2000]
 */

import * as fs from "fs";
import { timeOrderedHoldout } from "../src/lib/splits";
import { auc, brier } from "../src/lib/metrics";
import {
  BAR,
  BOUNDARY,
  fmt,
  loadDecisionDataset,
  loadTrainingData,
  readArms,
  type Leg,
} from "../src/lib/ml1-read";

function main() {
  const iters = (() => {
    const i = process.argv.indexOf("--iters");
    return i >= 0 ? Number(process.argv[i + 1]) : 2000;
  })();
  // --split=era runs the same gate over the era-stratified holdout (card ml1-fit-population-gaps
  // claim (2), option (a), approved 2026-10-28). Default stays "time" so the frozen-bar population
  // and every number published against it are untouched unless this is asked for explicitly.
  const splitMode = ((): "time" | "era" => {
    const i = process.argv.indexOf("--split");
    const v = i >= 0 ? String(process.argv[i + 1]) : "time";
    if (v !== "time" && v !== "era") throw new Error(`--split must be "time" or "era" (got ${v})`);
    return v;
  })();
  console.log("ML-1 promotion-gate read (comparators + calibration; nothing is trained or promoted)");
  console.log(
    `  bar (RESTATED 2026-10-27, relative): AUC >= price + ${BAR.margin} AND Brier <= price + ${BAR.margin}, ` +
      `computed on the same scored rows, market-clustered CI on dAUC excluding 0; ` +
      `[reference only: the old absolute ${BAR.auc}/${BAR.brier} was measured on ${BAR.measuredOn}]`
  );
  console.log(`  frozen boundary: ${new Date(BOUNDARY).toISOString()} | bootstrap ${iters} iters, seed 20261011, clustered by market_id`);

  const artifact: Record<string, unknown> = { bar: BAR, iters, boundary: new Date(BOUNDARY).toISOString() };

  // 1. Calibration on the artifact the bar was measured on.
  const dd = loadDecisionDataset();
  // The bar population is ALWAYS read on the frozen time split: it was built 2026-09-13 and holds no
  // exposure-v58plus rows, so an era-stratified cut there has an empty test set by construction. The
  // era split exists to ask a question about the book the model is fitted on TODAY, not to re-cut a
  // historical population. eraStratifiedHoldout throws rather than returning an empty test, so passing
  // the era mode here would be a crash, not a measurement.
  if (splitMode === "era") {
    console.log(
      "  NOTE: --split=era applies to training_data.csv only. The decision-dataset bar population " +
        "(built 2026-09-13) has no exposure-v58plus rows, so it is read on the frozen time split."
    );
  }
  readArms(dd, "decision-dataset (bar population: must reproduce 0.7285 / 0.2115)", iters, artifact, [], "time");
  // cross-check the other label basis the draft recorded (realizedPnl>0 = y_win)
  const yWinSplit = timeOrderedHoldout(
    dd.filter((l) => Number.isFinite(l.at) && Number.isFinite(l.price)),
    { at: (l) => l.at, era: (l) => l.era, labelReadyAt: (l) => l.readyAt, boundary: BOUNDARY, design: "decision-dataset, y_win label" }
  );
  const winLabels = yWinSplit.test.map((l) => ((l as Leg & { yWin: number }).yWin === 1 ? 1 : 0));
  console.log(
    `\n  cross-check label y_win (realizedPnl>0): price-only AUC ${fmt(auc(yWinSplit.test.map((l) => l.price), winLabels))}` +
      ` Brier ${fmt(brier(yWinSplit.test.map((l) => l.price), winLabels))} (recorded: 0.7331 / 0.2079)`
  );
  (artifact as Record<string, unknown>)["decision-dataset y_win cross-check"] = {
    auc: auc(yWinSplit.test.map((l) => l.price), winLabels),
    brier: brier(yWinSplit.test.map((l) => l.price), winLabels),
    testN: yWinSplit.test.length,
  };

  // 2. The same read on the NEW export — new evidence, NOT the bar (different population).
  const td = loadTrainingData();
  readArms(td as unknown as Leg[], "training_data.csv (re-pointed acted book — new evidence, not the bar)", iters, artifact, [], splitMode);

  fs.writeFileSync("data/ml1-gate-read.json", JSON.stringify(artifact, null, 2) + "\n");
  console.log(`\nwrote data/ml1-gate-read.json (${JSON.stringify(artifact).length} bytes)`);
  console.log("reproduce: npx tsx scripts/ml1-gate-read.ts");
}

main();
