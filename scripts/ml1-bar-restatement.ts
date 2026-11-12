/**
 * ML-1 promotion bar — restatement read (card `ml1-price-baseline-drift`, queue item 3).
 *
 * WHAT THIS IS (corrected 2026-11-12). The gate's ENFORCING bar has been RELATIVE since 815ecda
 * (2026-10-28): `AUC >= price_only + 0.0005 AND Brier <= price_only + 0.0005`, comparator
 * recomputed on each arm's own scored rows (`src/lib/ml1-read.ts`, `BAR.form === "relative"`).
 * This script is that change's AUDIT TRAIL: it re-derives, on both populations, (a) price's own
 * read on the frozen holdout, (b) each stored arm's verdict under the bar in force, and (c) the
 * RETIRED absolute form's arithmetic (`AUC >= 0.729 / Brier <= 0.212`), kept as the reference
 * line the card is about.
 *
 * THE DEFECT IT RECORDS. Those two retired constants are the PRICE-ONLY read on
 * `data/decision-dataset.csv` rounded to three decimals — not a margin over price. Carried onto
 * the re-pointed book the fit actually uses (`training_data.csv`) they stop meaning "beat price"
 * and start demanding the whole distance between two populations' price reads: +0.0147 AUC of
 * headroom AND a Brier ceiling price itself misses by 0.0062. Unreachable by construction, which
 * is the same defect as a probe that cannot fail — which is why the relative form is in force.
 *
 * WHAT THIS IS NOT: nothing is trained, promoted or enforced here. The script writes
 * `data/ml1-bar-restatement.json` and exits 1 only when its slack derivation no longer reproduces
 * the recorded constants (i.e. the evidence itself went bad).
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
import { BAR_SLACK, clearsBar, demandedMargin, relativeBar, reproducesInForceBar, type BarRead } from "../src/lib/ml1-bar";

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
  // What the gate ENFORCES (815ecda): price on the same scored rows + the 0.0005 tolerance.
  const enforced = relativeBar(price);
  // The RETIRED absolute form — a printed reference line, never enforcement.
  const retiredAbsolute: BarRead = { auc: BAR.auc, brier: BAR.brier };
  const retiredDemand = demandedMargin(price, retiredAbsolute);
  const eras = [...new Set(test.map((l) => l.era))].sort().map((era) => {
    const rows = test.filter((l) => l.era === era);
    return { era, n: rows.length, priceAuc: auc(rows.map((l) => l.price), rows.map((l) => l.y)) };
  });

  console.log(`\n### ${label}`);
  console.log(`  role: ${role}`);
  console.log(`  basis: population=acted legs in ${label}, clock=holdout at 2026-08-21T00:00:00Z, level=leg, label=pnl_net_entry>0`);
  console.log(`  ${split.provenance}`);
  console.log(`  price-only on the test side [label=EXIT: pnl_net_entry>0]: AUC ${fmt(price.auc)} | Brier ${fmt(price.brier)} (test n=${test.length}, markets ${new Set(test.map((l) => l.market)).size})`);
  console.log(
    `  IN-FORCE bar (RELATIVE, since 815ecda): AUC >= price + ${BAR.margin} AND Brier <= price + ${BAR.margin}` +
      ` -> on this population AUC >= ${fmt(enforced.auc)} AND Brier <= ${fmt(enforced.brier)} (comparator recomputed per arm below)`
  );
  console.log(
    `  RETIRED absolute bar (REFERENCE ONLY, ${BAR.measuredOn}): AUC >= ${BAR.auc} AND Brier <= ${BAR.brier}` +
      ` -> on this population it would demand ${retiredDemand.auc >= 0 ? "+" : ""}${fmt(retiredDemand.auc)} AUC and a Brier ceiling` +
      ` price itself misses by ${fmt(Math.abs(retiredDemand.brier))}` +
      (retiredDemand.brier < 0 ? "  <-- price is already ABOVE the retired ceiling" : "")
  );
  console.log(
    `  per-era price-only AUC on the test side (pooled ${fmt(price.auc)}): ` +
      eras.map((e) => `${e.era} ${fmt(e.priceAuc)} (n=${e.n})`).join(" | ")
  );

  const arms = ARMS.map((a) => {
    const scored = test.filter((l) => Number.isFinite(a.get(l)));
    const y = scored.map((l) => l.y);
    const read = {
      auc: auc(scored.map(a.get), y),
      brier: a.probability ? brier(scored.map(a.get), y) : null,
    };
    // The comparator on THIS arm's own scored rows — the same basis `readArms` uses, so an arm
    // that scores a different subset is never measured against another population's baseline.
    const comp = { auc: auc(scored.map((l) => l.price), y), brier: brier(scored.map((l) => l.price), y) };
    const inForce = clearsBar(read, relativeBar(comp));
    const retiredVerdict = clearsBar(read, retiredAbsolute);
    console.log(
      `    ${a.name.padEnd(20)} AUC ${fmt(read.auc)}` +
        (read.brier === null ? ` Brier    n/a` : ` Brier ${fmt(read.brier)}`) +
        ` | price here ${fmt(comp.auc)}/${fmt(comp.brier)}` +
        ` | IN FORCE: ${inForce.both === null ? "AUC only " + (inForce.auc ? "pass" : "fail") : inForce.both ? "PASSES" : "fails"}` +
        ` | retired abs: ${retiredVerdict.both === null ? "AUC only " + (retiredVerdict.auc ? "pass" : "fail") : retiredVerdict.both ? "clears" : "fails"}`
    );
    return { arm: a.name, ...read, comparatorHere: comp, inForce, retiredAbsolute: retiredVerdict };
  });

  return {
    label,
    role,
    provenance: split.provenance,
    priceOnly: price,
    inForceBar: { form: BAR.form, comparator: BAR.comparator, margin: BAR.margin, onThisPopulation: enforced },
    retiredAbsoluteBar: { auc: BAR.auc, brier: BAR.brier, measuredOn: BAR.measuredOn, demandedMargin: retiredDemand },
    eras,
    arms,
  };
}

function main() {
  console.log("ML-1 bar restatement read — audit trail; the ENFORCING bar is relative (815ecda) and nothing here changes it");
  console.log(`  in-force bar: AUC >= price-only + ${BAR.margin} AND Brier <= price-only + ${BAR.margin}, comparator recomputed on each arm's scored rows (src/lib/ml1-read.ts BAR, form=${BAR.form})`);
  console.log(`  retired absolute bar: AUC >= ${BAR.auc} AND Brier <= ${BAR.brier} — REFERENCE ONLY (price on ${BAR.measuredOn}, rounded to 3dp)`);
  console.log(`  slack check: the retired constants must reproduce from price + ${BAR_SLACK.auc}/${BAR_SLACK.brier} on their own population, else no read here counts`);
  console.log("  NOTE entry_price IS the comparator: it fails its own bar on every population by construction (a candidate identical to price cannot clear price + slack).");

  const barPop = readPopulation(
    "data/decision-dataset.csv",
    "the population the 0.729/0.212 constants were MEASURED on — this block is the drift block",
    loadDecisionDataset() as unknown as Leg[]
  );
  const fitPop = readPopulation(
    "training_data.csv",
    "the file the ML-1 fit actually uses — this is where the retired absolute form turns unreachable",
    loadTrainingData() as unknown as Leg[]
  );

  // (a) The slack basis, checked against the FROZEN recorded read.
  const slackOk = reproducesInForceBar(RECORDED_BAR_POP, BAR);
  const restatedFromRecorded = relativeBar(RECORDED_BAR_POP);
  const slackMatchesMargin = BAR_SLACK.auc === BAR.margin && BAR_SLACK.brier === BAR.margin;
  console.log(
    `\n  SLACK CHECK vs the frozen ${RECORDED_BAR_POP.asOf} read (AUC ${RECORDED_BAR_POP.auc} / Brier ${RECORDED_BAR_POP.brier}, test n=${RECORDED_BAR_POP.testN}):` +
      ` price + slack = ${fmt(restatedFromRecorded.auc)} / ${fmt(restatedFromRecorded.brier)} vs retired constants ${BAR.auc} / ${BAR.brier}` +
      ` -> ${slackOk ? "REPRODUCES (0.729/0.212 IS price rounded to 3dp)" : "DOES NOT REPRODUCE — the slack basis is wrong, no read from this script counts"}` +
      ` | slack ${slackMatchesMargin ? "==" : "!="} enforce margin ${BAR.margin}`
  );
  // (b) Population drift, printed rather than folded into (a).
  const drift = { auc: barPop.priceOnly.auc - RECORDED_BAR_POP.auc, brier: barPop.priceOnly.brier - RECORDED_BAR_POP.brier };
  console.log(
    `  DRIFT on that same file today: AUC ${fmt(barPop.priceOnly.auc)} / Brier ${fmt(barPop.priceOnly.brier)} vs recorded` +
      ` -> ${fmt(drift.auc)} AUC / ${fmt(drift.brier)} Brier, test n=${(barPop.provenance.match(/test n=(\d+)/) ?? [])[1] ?? "n/a"} vs ${RECORDED_BAR_POP.testN} recorded` +
      ` (the export has GROWN since 2026-09-13; this is population drift, not a wrong derivation)`
  );
  const fitDemand = fitPop.retiredAbsoluteBar.demandedMargin;
  console.log(
    `  GAP the RETIRED absolute bar would carry onto the fit population: ${fmt(fitDemand.auc)} AUC of headroom demanded,` +
      ` and a Brier ceiling price itself misses by ${fmt(Math.abs(fitDemand.brier))} — i.e. unreachable by construction, not a standard.`
  );

  const artifact = {
    generatedAt: new Date().toISOString(),
    enforcement: {
      form: BAR.form,
      comparator: BAR.comparator,
      margin: BAR.margin,
      since: "815ecda (2026-10-28, operator-approved restatement)",
      code: "src/lib/ml1-read.ts readArms() compares each arm against price recomputed on that arm's own scored rows",
    },
    retiredAbsoluteReference: { auc: BAR.auc, brier: BAR.brier, measuredOn: BAR.measuredOn },
    slack: BAR_SLACK,
    boundary: new Date(BOUNDARY).toISOString(),
    recordedBarPopulationRead: RECORDED_BAR_POP,
    slackReproducesInForceBar: slackOk,
    driftOnBarPopulationSinceRecording: drift,
    barPopulation: barPop,
    fitPopulation: fitPop,
    note:
      "Audit trail for the SHIPPED restatement (815ecda): the enforcing bar is RELATIVE (price + " +
      BAR.margin +
      "), and the absolute 0.729/0.212 is a REFERENCE line only. Read-only — this script changes no threshold and promotes nothing.",
  };
  fs.writeFileSync("data/ml1-bar-restatement.json", JSON.stringify(artifact, null, 2) + "\n");
  console.log(`\nwrote data/ml1-bar-restatement.json`);
  console.log("reproduce: npx tsx scripts/ml1-bar-restatement.ts");
  if (!slackOk || !slackMatchesMargin) process.exit(1);
}

main();
