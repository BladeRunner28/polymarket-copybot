/**
 * ML-1 promotion-gate read — makes the card's RESTATED bar executable instead of prose
 * (card `ml1-target-net-pnl-and-price-baseline`, gate half 2).
 *
 * THE BAR (restated 2026-10-11, do not weaken it):
 *   A candidate promotes only if it beats the PRICE-ONLY baseline on a frozen
 *   TIME-ORDERED holdout of the decision dataset — train <= 2026-08-21, test after,
 *   label `pnl_net_entry > 0` — clearing AUC >= 0.729 AND Brier <= 0.212 with a
 *   market-CLUSTERED 95% CI on the difference that excludes 0. Beating `copyScore`
 *   proves nothing: it measures AUC 0.474-0.481, i.e. WORSE than the base rate.
 *
 * WHAT THIS SCRIPT IS
 *   The comparator and the calibration check, not a candidate:
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
 * WHAT IT IS NOT: no model is trained, nothing is promoted, no rule, threshold, size
 * or published lane number is touched. It writes `data/ml1-gate-read.json` (evidence)
 * and prints the read.
 *
 * SPLITS: every cut goes through `src/lib/splits.ts` — time-ordered, era-reported, and
 * purged on `terminal_at` (a leg that settled inside the test window may not be
 * trained on). No random row folds anywhere; `scripts/check-split-doctrine.py`
 * enforces that repo-wide.
 *
 * Usage:  npx tsx scripts/ml1-gate-read.ts [--iters 2000]
 */

import * as fs from "fs";
import { timeOrderedHoldout, eraGroups } from "../src/lib/splits";
import { auc, brier, clusteredBootstrap, clusteredBootstrapDelta, constantBrier, mean } from "../src/lib/metrics";
import { eraOf } from "../src/lib/training-export";

/** The frozen boundary the bar names. A gate that moves its holdout is not a gate. */
const BOUNDARY = Date.parse("2026-08-21T00:00:00Z");
/** The bar, verbatim from the card. */
const BAR = { auc: 0.729, brier: 0.212, comparator: "price-only (entry_price)" };

type Leg = {
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
};

const SCORE_ARMS = ["copy_score", "wallet_quality_score", "entry_timing_score", "thesis_score"] as const;
const PROBABILITY_ARMS = ["entry_price", "detected_price"] as const;

function parseCsv(path: string): { header: string[]; rows: string[][] } {
  const text = fs.readFileSync(path, "utf8").trimEnd();
  const lines = text.split("\n");
  return { header: lines[0].split(","), rows: lines.slice(1).map((l) => l.split(",")) };
}

function loadDecisionDataset(): Leg[] {
  const { header, rows } = parseCsv("data/decision-dataset.csv");
  const col = (n: string) => {
    const i = header.indexOf(n);
    if (i < 0) throw new Error(`decision-dataset.csv is missing column ${n}`);
    return i;
  };
  const num = (v: string) => (v === "" || v === undefined ? null : Number(v));
  return rows
    .map((r) => {
      const pnl = num(r[col("pnl_net_entry")]);
      const winner = num(r[col("y_win")]);
      const rsv = num(r[col("rule_set_version")]);
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
        // keep the raw sign label for the calibration cross-check
      } as Leg & { yWin?: number };
    })
    .map((l, i) => ({ ...l, yWin: num(rows[i][header.indexOf("y_win")]) ?? Number.NaN }));
}

function loadTrainingData(): (Leg & { yOutcome: number | null })[] {
  const { header, rows } = parseCsv("training_data.csv");
  const col = (n: string) => {
    const i = header.indexOf(n);
    if (i < 0) throw new Error(`training_data.csv is missing column ${n}`);
    return i;
  };
  const num = (v: string) => (v === "" || v === undefined ? null : Number(v));
  return rows.map((r) => {
    const out = r[col("y_outcome")];
    return {
      at: Date.parse(r[col("decision_at")]),
      readyAt: null, // the export does not carry a terminal stamp; purge is n/a (reported)
      market: r[col("market_id")],
      wallet: r[col("wallet")],
      era: r[col("era")],
      price: Number(r[col("entry_price")]),
      detected: num(r[col("detected_price")]) ?? Number.NaN,
      pnlNetEntry: num(r[col("pnl_net_entry")]) ?? Number.NaN,
      y: (r[col("y_net_entry")] === "1" ? 1 : 0) as 0 | 1,
      scores: Object.fromEntries(SCORE_ARMS.map((s) => [s, num(r[col(s)]) ?? Number.NaN])),
      yOutcome: out === "" ? null : Number(out),
    };
  });
}

const fmt = (v: number, d = 4) => (Number.isNaN(v) || v === null ? "n/a" : v.toFixed(d));
const pct = (v: number) => (Number.isNaN(v) ? "n/a" : `${(v * 100).toFixed(1)}%`);

function readArms(legs: Leg[], label: string, iters: number, artifact: Record<string, unknown>) {
  const usable = legs.filter((l) => Number.isFinite(l.pnlNetEntry) && Number.isFinite(l.price) && Number.isFinite(l.at));
  const split = timeOrderedHoldout(usable, {
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

  const priceAuc = auc(test.map((l) => l.price), labels);
  const priceBrier = brier(test.map((l) => l.price), labels);
  const rows: Record<string, unknown>[] = [];
  const armList: { name: string; get: (l: Leg) => number; probability: boolean }[] = [
    { name: "entry_price", get: (l) => l.price, probability: true },
    { name: "detected_price", get: (l) => l.detected, probability: true },
    ...SCORE_ARMS.map((s) => ({ name: s, get: (l: Leg) => l.scores[s], probability: false })),
  ];

  for (const arm of armList) {
    const scored = test.filter((l) => Number.isFinite(arm.get(l)));
    if (scored.length < 30) {
      rows.push({ arm: arm.name, n: scored.length, note: "too few finite scores to read" });
      continue;
    }
    const a = auc(scored.map(arm.get), scored.map((l) => l.y));
    const b = arm.probability
      ? brier(scored.map(arm.get), scored.map((l) => l.y))
      : Number.NaN;
    const delta = clusteredBootstrapDelta(
      scored,
      (l) => l.market,
      (s) => auc(s.map(arm.get), s.map((l) => l.y)),
      (s) => auc(s.map((l) => l.price), s.map((l) => l.y)),
      { iters, seed: 20261011 }
    );
    // Money arm: re-select the top tercile INSIDE each bootstrap draw.
    const selectBy = (s: readonly Leg[], get: (l: Leg) => number) => {
      const ordered = [...s].filter((l) => Number.isFinite(get(l))).sort((x, y2) => get(y2) - get(x));
      return ordered.slice(0, Math.max(1, Math.floor(ordered.length / 3)));
    };
    const money = clusteredBootstrapDelta(
      scored,
      (l) => l.market,
      (s) => mean(selectBy(s, arm.get).map((l) => l.pnlNetEntry)),
      (s) => mean(s.map((l) => l.pnlNetEntry)),
      { iters, seed: 20261011 }
    );

    const clearsAuc = a >= BAR.auc;
    const clearsBrier = arm.probability ? b <= BAR.brier : null;
    rows.push({
      arm: arm.name,
      n: scored.length,
      auc: a,
      brier: arm.probability ? b : null,
      beatsPriceCiLow: delta.low,
      beatsPriceCiHigh: delta.high,
      deltaAuc: delta.point,
      pGreater: delta.pGreater,
      clearsAucBar: clearsAuc,
      clearsBrierBar: clearsBrier,
      topTercileMeanPnl: money.point,
      topTercileVsCopyAllCi: [money.low, money.high],
      topTercileN: selectBy(scored, arm.get).length,
    });
    console.log(
      `  ${arm.name.padEnd(22)} n=${String(scored.length).padStart(4)} AUC ${fmt(a)}` +
        (arm.probability ? ` Brier ${fmt(b)}` : ` Brier n/a (not a probability)`) +
        ` | ΔAUC vs price ${fmt(delta.point, 4)} CI [${fmt(delta.low)}, ${fmt(delta.high)}] P(>) ${fmt(delta.pGreater, 3)}` +
        ` | topTercile $/leg ${fmt(money.point, 2)} vs copy-all, CI [${fmt(money.low, 2)}, ${fmt(money.high, 2)}]`
    );
  }

  console.log(`  PRICE-ONLY (the bar's comparator): AUC ${fmt(priceAuc)} Brier ${fmt(priceBrier)}`);
  // Per-era read — criterion (d) of the pre-registered shadow read, applied to AUC:
  // a sign that only holds in one era is not a signal, it is a policy artifact.
  const eras = eraGroups(test, (l) => l.era);
  const eraRows: Record<string, unknown>[] = [];
  for (const [era, list] of [...eras.entries()].sort()) {
    const eLabels = list.map((l) => l.y);
    const eAuc = list.length >= 30 ? auc(list.map((l) => l.price), eLabels) : Number.NaN;
    eraRows.push({ era, n: list.length, priceAuc: eAuc, priceAucUsable: !Number.isNaN(eAuc) });
    console.log(
      `    era ${era.padEnd(20)} n=${String(list.length).padStart(4)} price-only AUC ${fmt(eAuc)}` +
        (Number.isNaN(eAuc) ? " (too few rows or one class — not read)" : "")
    );
  }

  artifact[label] = {
    provenance: split.provenance,
    boundary: new Date(BOUNDARY).toISOString(),
    trainN: split.trainN,
    testN: split.testN,
    purged: split.purged,
    tiedAtBoundary: split.tiedAtBoundary,
    testBaseRate: mean(labels),
    constantBrier: constantBrier(labels),
    priceOnly: { auc: priceAuc, brier: priceBrier },
    arms: rows,
    eraRead: eraRows,
  };
}

function main() {
  const iters = (() => {
    const i = process.argv.indexOf("--iters");
    return i >= 0 ? Number(process.argv[i + 1]) : 2000;
  })();
  console.log("ML-1 promotion-gate read (comparators + calibration; nothing is trained or promoted)");
  console.log(`  bar (restated 2026-10-11): AUC >= ${BAR.auc} AND Brier <= ${BAR.brier} vs price-only on a frozen time-ordered holdout`);
  console.log(`  frozen boundary: ${new Date(BOUNDARY).toISOString()} | bootstrap ${iters} iters, seed 20261011, clustered by market_id`);

  const artifact: Record<string, unknown> = { bar: BAR, iters, boundary: new Date(BOUNDARY).toISOString() };

  // 1. Calibration on the artifact the bar was measured on.
  const dd = loadDecisionDataset();
  readArms(dd, "decision-dataset (bar population: must reproduce 0.7285 / 0.2115)", iters, artifact);
  // cross-check the other label basis the draft recorded (realizedPnl>0 = y_win)
  const yWinSplit = timeOrderedHoldout(
    dd.filter((l) => Number.isFinite(l.at) && Number.isFinite(l.price)),
    { at: (l) => l.at, era: (l) => l.era, labelReadyAt: (l) => l.readyAt, boundary: BOUNDARY, design: "decision-dataset, y_win label" }
  );
  const winLabels = yWinSplit.test.map((l) => (l as Leg & { yWin: number }).yWin === 1 ? 1 : 0);
  console.log(
    `\n  cross-check label y_win (realizedPnl>0): price-only AUC ${fmt(auc(yWinSplit.test.map((l) => l.price), winLabels))}` +
      ` Brier ${fmt(brier(yWinSplit.test.map((l) => l.price), winLabels))} (recorded: 0.7331 / 0.2079)`
  );
  (artifact as any)["decision-dataset y_win cross-check"] = {
    auc: auc(yWinSplit.test.map((l) => l.price), winLabels),
    brier: brier(yWinSplit.test.map((l) => l.price), winLabels),
    testN: yWinSplit.test.length,
  };

  // 2. The same read on the NEW export — new evidence, NOT the bar (different population).
  const td = loadTrainingData();
  readArms(td as unknown as Leg[], "training_data.csv (re-pointed acted book — new evidence, not the bar)", iters, artifact);

  fs.writeFileSync("data/ml1-gate-read.json", JSON.stringify(artifact, null, 2) + "\n");
  console.log(`\nwrote data/ml1-gate-read.json (${JSON.stringify(artifact).length} bytes)`);
  console.log("reproduce: npx tsx scripts/ml1-gate-read.ts");
}

main();
