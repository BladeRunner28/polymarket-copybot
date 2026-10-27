/**
 * ML-1 promotion bar — restatement read (card `ml1-price-baseline-drift`, queue item 3).
 *
 * THE DEFECT THIS MEASURES. The in-force bar is absolute: AUC >= 0.729 AND Brier <= 0.212
 * (`BAR` in src/lib/ml1-read.ts). Those two constants are the PRICE-ONLY read on
 * `data/decision-dataset.csv` rounded to three decimals — not a margin over price. Applied to
 * the re-pointed book the fit actually uses (`training_data.csv`), the absolute form silently
 * changes meaning: it asks the candidate to beat price by the whole distance between two
 * different populations' price reads. This script prints, for both populations and on the
 * same frozen holdout, (a) price's own read, (b) the headroom the in-force bar demands over
 * that price read, and (c) the restated bar (price + the 0.0005 loose change the original
 * constants allowed) with each stored arm's verdict under it.
 *
 * WHAT THIS IS NOT: nothing is trained, promoted or enforced. The gate still applies the
 * absolute BAR. Every number printed is read-only evidence for a Lane A proposal that goes
 * live only on the operator's yes; the proposal lives on the card, tagged `awaiting-approval`.
 *
 * BASIS, stated once here and repeated per number:
 *   population — one row per ACTED leg (a decision that became a paper trade), file named per block
 *   clock      — frozen time-ordered holdout at 2026-08-21T00:00:00Z, train <= boundary, test after
 *   level      — leg level, label `pnl_net_entry > 0`, purged on the terminal stamp
 *
 * Usage: npx tsx scripts/ml1-bar-restatement.ts
 */

import * as fs from "fs";
import { timeOrderedHoldout } from "../src/lib/splits";
import { auc, brier } from "../src/lib/metrics";
import { BAR, BOUNDARY, fmt, loadDecisionDataset, loadTrainingData, type Leg } from "../src/lib/ml1-read";
import { BAR_SLACK, clearsBar, demandedMargin, relativeBar, reproducesInForceBar } from "../src/lib/ml1-bar";

/**
 * The price-only read the 0.729/0.212 constants were CUT FROM: `data/decision-dataset.csv`,
 * 2026-09-13, net label, time-ordered holdout test n=1,055. Recorded in
 * drafts/ml1-target-and-price-baseline-20261011.md §"Restated promotion gate". This is the
 * frozen reference the slack is derived against; a fresh recompute on the grown file is
 * reported separately as population drift.
 */
const RECORDED_BAR_POP = { auc: 0.7285, brier: 0.2115, testN: 1055, asOf: "2026-09-13" };

const ARMS: { name: string; get: (l: Leg) => number; probability: boolean }[] = [
  { name: "entry_price", get: (l) => l.price, probability: true },
  { name: "detected_price", get: (l) => l.detected, probability: true },
  { name: "copy_score", get: (l) => l.scores.copy_score, probability: false },
  { name: "wallet_quality_score", get: (l) => l.scores.wallet_quality_score, probability: false },
  { name: "entry_timing_score", get: (l) => l.scores.entry_timing_score, probability: false },
  { name: "thesis_score", get: (l) => l.scores.thesis_score, probability: false },
];

function readPopulation(label: string, role: string, legs: Leg[]) {
  const usable = legs.filter((l) => Number.isFinite(l.pnlNetEntry) && Number.isFinite(l.price) && Number.isFinite(l.at));
  const split = timeOrderedHoldout(usable, {
    at: (l) => l.at,
    era: (l) => l.era,
    labelReadyAt: (l) => l.readyAt,
    boundary: BOUNDARY,
    design: label,
  });
  const test = split.test;
  const labels = test.map((l) => l.y);
  const price = { auc: auc(test.map((l) => l.price), labels), brier: brier(test.map((l) => l.price), labels) };
  const restated = relativeBar(price);
  const margin = demandedMargin(price, BAR);

  console.log(`\n### ${label}`);
  console.log(`  role: ${role}`);
  console.log(`  basis: population=acted legs in ${label}, clock=holdout at 2026-08-21T00:00:00Z, level=leg, label=pnl_net_entry>0`);
  console.log(`  ${split.provenance}`);
  console.log(`  price-only on the test side: AUC ${fmt(price.auc)} | Brier ${fmt(price.brier)} (test n=${test.length}, markets ${new Set(test.map((l) => l.market)).size})`);
  console.log(
    `  IN-FORCE bar (AUC>=${BAR.auc}, Brier<=${BAR.brier}) demands of a candidate: ` +
      `${margin.auc >= 0 ? "+" : ""}${fmt(margin.auc)} AUC and ${margin.brier >= 0 ? "+" : ""}${fmt(margin.brier)} Brier vs this price read` +
      (margin.brier < 0 ? "  <-- price is already ABOVE the Brier ceiling" : "")
  );
  console.log(
    `  RESTATED bar (price + ${BAR_SLACK.auc} AUC / + ${BAR_SLACK.brier} Brier, NOT IN FORCE): ` +
      `AUC >= ${fmt(restated.auc)} AND Brier <= ${fmt(restated.brier)}`
  );

  const arms = ARMS.map((a) => {
    const scored = test.filter((l) => Number.isFinite(a.get(l)));
    const y = scored.map((l) => l.y);
    const read = {
      auc: auc(scored.map(a.get), y),
      brier: a.probability ? brier(scored.map(a.get), y) : null,
    };
    const inForce = { auc: read.auc >= BAR.auc, brier: read.brier === null ? null : read.brier <= BAR.brier };
    const restatedVerdict = clearsBar(read, restated);
    console.log(
      `    ${a.name.padEnd(20)} AUC ${fmt(read.auc)}` +
        (read.brier === null ? ` Brier    n/a` : ` Brier ${fmt(read.brier)}`) +
        ` | in-force: ${inForce.auc ? "clears AUC" : "fails AUC"}, ${inForce.brier === null ? "Brier n/a" : inForce.brier ? "clears Brier" : "fails Brier"}` +
        ` | restated: ${restatedVerdict.both === null ? "AUC only " + (restatedVerdict.auc ? "pass" : "fail") : restatedVerdict.both ? "PASSES" : "fails"}`
    );
    return { arm: a.name, ...read, inForce, restated: restatedVerdict };
  });

  const eras = [...new Set(test.map((l) => l.era))].sort().map((era) => {
    const rows = test.filter((l) => l.era === era);
    return { era, n: rows.length, priceAuc: auc(rows.map((l) => l.price), rows.map((l) => l.y)) };
  });

  return { label, role, provenance: split.provenance, priceOnly: price, inForceBar: BAR, demandedMargin: margin, restatedBar: restated, arms, eras };
}

function main() {
  console.log("ML-1 bar restatement read — read-only; the in-force bar is unchanged and nothing is promoted");
  console.log(`  in-force bar: AUC >= ${BAR.auc} AND Brier <= ${BAR.brier} (src/lib/ml1-read.ts BAR)`);
  console.log(`  slack under test: AUC +${BAR_SLACK.auc}, Brier +${BAR_SLACK.brier} — the loose change the 2026-10-11 constants allowed over their own price read`);
  console.log("  NOTE entry_price IS the comparator: 'restated: fails' on that row is the expected answer (a candidate identical to price cannot clear price + slack).");

  const barPop = readPopulation(
    "data/decision-dataset.csv",
    "the population the 0.729/0.212 constants were MEASURED on — this block is the drift block",
    loadDecisionDataset() as unknown as Leg[]
  );
  const fitPop = readPopulation(
    "training_data.csv",
    "the file the ML-1 fit actually uses — this block is the population the absolute bar is now applied to",
    loadTrainingData() as unknown as Leg[]
  );

  // (a) The slack basis, checked against the FROZEN recorded read.
  const slackOk = reproducesInForceBar(RECORDED_BAR_POP, BAR);
  const restatedFromRecorded = relativeBar(RECORDED_BAR_POP);
  console.log(
    `\n  SLACK CHECK vs the frozen ${RECORDED_BAR_POP.asOf} read (AUC ${RECORDED_BAR_POP.auc} / Brier ${RECORDED_BAR_POP.brier}, test n=${RECORDED_BAR_POP.testN}):` +
      ` restated = ${fmt(restatedFromRecorded.auc)} / ${fmt(restatedFromRecorded.brier)} vs in-force ${BAR.auc} / ${BAR.brier}` +
      ` -> ${slackOk ? "REPRODUCES (0.729/0.212 IS price rounded to 3dp)" : "DOES NOT REPRODUCE — the slack basis is wrong, no read from this script counts"}`
  );
  // (b) Population drift, printed rather than folded into (a).
  const drift = { auc: barPop.priceOnly.auc - RECORDED_BAR_POP.auc, brier: barPop.priceOnly.brier - RECORDED_BAR_POP.brier };
  console.log(
    `  DRIFT on that same file today: AUC ${fmt(barPop.priceOnly.auc)} / Brier ${fmt(barPop.priceOnly.brier)} vs recorded` +
      ` -> ${fmt(drift.auc)} AUC / ${fmt(drift.brier)} Brier, test n=${barPop.arms[0] ? (barPop.provenance.match(/test n=(\d+)/) ?? [])[1] : "n/a"} vs ${RECORDED_BAR_POP.testN} recorded` +
      ` (the export has GROWN since 2026-09-13; this is population drift, not a wrong derivation)`
  );
  console.log(
    `  GAP the absolute bar carries onto the fit population: ${fmt(fitPop.demandedMargin.auc)} AUC of headroom demanded,` +
      ` and a Brier ceiling price itself misses by ${fmt(Math.abs(fitPop.demandedMargin.brier))}.`
  );

  const artifact = {
    generatedAt: new Date().toISOString(),
    inForceBar: BAR,
    slack: BAR_SLACK,
    boundary: new Date(BOUNDARY).toISOString(),
    recordedBarPopulationRead: RECORDED_BAR_POP,
    slackReproducesInForceBar: slackOk,
    driftOnBarPopulationSinceRecording: drift,
    barPopulation: barPop,
    fitPopulation: fitPop,
    note: "Read-only. The restated bar is NOT in force; BAR in src/lib/ml1-read.ts is unchanged. Proposal on card ml1-price-baseline-drift (awaiting-approval).",
  };
  fs.writeFileSync("data/ml1-bar-restatement.json", JSON.stringify(artifact, null, 2) + "\n");
  console.log(`\nwrote data/ml1-bar-restatement.json`);
  console.log("reproduce: npx tsx scripts/ml1-bar-restatement.ts");
  if (!slackOk) process.exit(1);
}

main();
