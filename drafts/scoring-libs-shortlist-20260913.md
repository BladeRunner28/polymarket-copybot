# Scoring Library Shortlist — Tabular Binary Classification with Calibration + Walk-Forward Validation

**Date:** 2026-09-13
**Scope:** production-ready libraries for (a) weekly refit of a tabular binary classifier with probability calibration, (b) time-series-safe (walk-forward) validation, (c) inference inside the Node/TS scoring loop at ~500 decisions/run.
**Method:** every license / release / maintenance claim below was read from the **PyPI JSON API, the npm registry API, and the GitHub API** on 2026-09-13 — not from blog benchmarks. Claims marked *measured* were reproduced against this repo's own data.
**Status:** the library shortlist is complete. **A data-integrity blocker was found while grounding it that must be fixed before any library comparison is meaningful (see §0).**

---

## §0. BLOCKER — read this before choosing a library

Grounding the shortlist required actually running a walk-forward evaluation on the existing labeled data. Two findings from that run invalidate the current ML-1 lane as it stands. Neither is a library problem; no library choice fixes either one.

### 0.1 There is only 688 labeled rows, from 2 decision days

Queried directly from `prisma/dev.db`:

| quantity | value |
|---|---|
| `OutcomeReview` rows total | **688** |
| rows with `wasDecisionGood NOT NULL` | **688** |
| rows with `finalOutcome NOT NULL` | **688** |
| `DecisionJournal` rows | 253,640 |

The working figure of "~2,000 labels" in the task brief is **not** what the database holds — the export and the DB both stop at 688. The existing `npm run export:training` produces exactly 688 data rows.

Worse, those 688 labels are **not spread over time**. Ordered by `DecisionJournal.createdAt`:

| property | measured |
|---|---|
| decision `createdAt` span | **2026-07-14 → 2026-07-15 (1.02 days)** |
| distinct decision days | **2** |
| distinct minute-of-decision buckets | 13 |
| distinct `marketId` | 178 |
| distinct `walletAddress` | **10** |

`reviewTime` spans 2026-09-01 → 2026-09-12, i.e. the labels were produced by a **single bulk backfill**, not by a live weekly review cadence.

**Consequence: strict walk-forward validation is currently impossible.** A first attempt with `TimeSeriesSplit`-style time folds and a 7-day embargo returned **zero usable folds** — that is not a bug in the harness, it is the correct answer. With a 1.02-day decision window you cannot construct a train window and a non-overlapping test window.

### 0.2 Effective sample size is far below 688

Cluster design-effect / ICC on the label, computed on the 688 rows:

| clustering | k clusters | mean size | ICC | design effect | **N_eff** |
|---|---|---|---|---|---|
| decision day | 2 | 344.0 | 0.595 | 205.0 | **3.4** |
| minute bucket | 13 | 52.9 | 0.481 | 26.0 | **26.5** |
| walletAddress | 10 | 68.8 | 0.413 | 29.0 | **23.7** |
| marketId | 178 | 3.87 | 0.899 | 3.58 | **192.4** |

Any "N_eff ≥ X" acceptance gate must be evaluated against **these** numbers, not against 688. The honest range is **~3 to ~190 depending on clustering choice**, and the defensible default (cluster by decision time) is **double digits at best**.

### 0.3 The target variable mixes two opposite definitions

This is the most serious finding. `wasDecisionGood` is not one estimable quantity — it is defined **differently, and with opposite sign on the PnL axis**, depending on the decision type. From `scripts/backfill-outcome-reviews.ts`:

```ts
if (d.decision === "paper_copy") {
  good = simulatedPnl > 0;          // good  ==  OUR paper trade made money
} else {
  good = !won;                       // good  ==  THE WALLET'S trade lost
}
```

Measured on the live DB:

```
rows=688  skip=200  paper_copy=488
label != (simulatedPnl > 0):  all=200   skip=200   paper_copy=0
skip rows with simPnl<0 but label=True ("avoided loser"): 108
```

The disagreement between the label and `simulatedPnl > 0` is **exactly and entirely** the 200 `skip` rows — zero mismatches among the 488 `paper_copy` rows. For a `skip` row, "good" means the wallet lost, so a *negative* `simulatedPnl` is a *positive* label. Concatenating `skip` and `paper_copy` rows into a single binary target asks a model to predict a variable that flips meaning by subgroup. Because `decision` is also a feature in `training_data.csv`, a model can trivially learn "skip → 1" and score well while learning nothing about decision quality — which is a material part of why the current score shows no predictive power.

A corroborating symptom: the label rate **swings from 8.0% (2026-07-14, n=100) to 87.2% (2026-07-15, n=588)** — a 79-point move between two consecutive days. Day 1 is 100% `skip` rows drawn from **3 markets and 2 wallets**; day 2 is 488 `paper_copy` + 100 `skip` across 175 markets. `simulatedPnl` moves the *opposite* way (+12.06 day 1 → −0.99 day 2). No mechanism makes copy decisions 92% bad one day and 87% good the next; the swing is the label definition and the sample composition.

### 0.4 The existing exporter drops the timestamp

`scripts/export-training-data.ts` writes:

```
review_id,decision,confidence,wallet_score,trade_size,spread,liquidity,ttr_hours,was_good
```

There is **no timestamp column**. `DecisionJournal.createdAt`, `OutcomeReview.reviewTime`, and `OutcomeReview.createdAt` all exist in the schema and are simply not exported. As shipped, `training_data.csv` **cannot be used for walk-forward validation at all** — the row order carries no time information, so every time-based split is silently unenforceable. Fix this first; it is a one-line change.

Also note `training_data.csv` column `ttr_hours` is populated from `d.entryTimingScore`, not from any time-to-resolution field — a label/name mismatch worth cleaning up while the exporter is open.

### 0.5 What this does to the shortlist

The ranking below stands on its own merits (licensing, maintenance, API fit, inference path). But **the correct sequence is: fix the exporter and the label, accumulate labels across ≥8–12 weekly refit cycles, and only then run the library comparison.** Running a model bake-off on the current 688 rows will produce a confident, meaningless answer. The acceptance criteria in §6 are written to be falsifiable *and* to fail loudly on data this thin.

---

## §1. Verified library table

All figures read from PyPI / npm / GitHub APIs on 2026-09-13. "last release" = latest upload/publish date.

### Python — refit side

| library | license | latest ver | last release | releases/12mo | repo activity | role |
|---|---|---|---|---|---|---|
| **scikit-learn** | **BSD-3-Clause** | 1.9.1 | 2026-09-10 | 5 | 67.2k★, push 2026-09-12 | model, scaler, walk-forward splitter, calibration |
| **netcal** | **Apache-2.0** | 1.4.0 | 2026-04-16 | 1 | 380★, push 2026-04-16 | binary calibration methods + ECE/MCE/ACE metrics |
| **river** | **BSD-3-Clause** | 0.26.1 | 2026-08-21 | 7 | 6.1k★, push 2026-09-03 | online/streaming model, ADWIN drift detection, rolling metrics |
| **MAPIE** | **BSD-3-Clause** | 1.5.0 | 2026-08-05 | 7 | 1.6k★, push 2026-09-08 | Venn-ABERS calibration, conformal sets, calibration hypothesis tests |
| **skfolio** | **BSD-3-Clause** | 1.2.0 | 2026-09-13 | 28 | 2.4k★, push 2026-09-13 | CombinatorialPurgedCV (purge + embargo) |
| LightGBM | MIT | 4.7.0 | 2026-07-18 | 1 | 18.8k★, push 2026-09-13 | GBDT — **not yet**, see §4 |
| XGBoost | Apache-2.0 | 3.4.1 | 2026-08-15 | 9 | 28.8k★, push 2026-09-11 | GBDT — **not yet** |
| CatBoost | Apache-2.0 | 1.2.10 | 2026-02-18 | 2 | 9.1k★, push 2026-09-12 | GBDT — **not yet** |
| statsmodels | BSD-3-Clause | 0.15.0 | 2026-08-30 | 3 | 11.6k★, push 2026-09-12 | HAC/Newey-West SEs for the significance test |

### TypeScript — inference side

| library | license | latest ver | last release | notes | role |
|---|---|---|---|---|---|
| **onnxruntime-node** | **MIT** | 1.29.0 | 2026-08-24 | 3 runtime deps; `microsoft/onnxruntime` 21.8k★, push 2026-09-13 | production Node inference engine |
| onnxruntime-web | MIT | 1.29.0 | 2026-08-24 | same monorepo | browser path (dashboard), if ever needed |
| simple-statistics | ISC | 7.12.0 | 2026-09-08 | 0 deps | descriptive stats / bootstrap helpers |

The model class that actually fits n_eff ≈ tens — a **ridge logistic regression** — needs no TS library at all. See §3.

---

## §2. What each is best at (and its real limits)

### 2.1 scikit-learn — BSD-3-Clause — **primary**
The refit workhorse and the substrate every other entry plugs into. `LogisticRegression` (L2, `lbfgs`) is the right model class for double-digit N_eff; `StandardScaler` gives you the exact `mean_`/`scale_` vectors you ship to Node; `CalibratedClassifierCV` does Platt/isotonic.

Walk-forward: `sklearn.model_selection.TimeSeriesSplit` — signature verified from the 1.9.1 docs:
```
TimeSeriesSplit(n_splits=5, *, max_train_size=None, test_size=None, gap=0)
```
`gap` is documented as *"Number of samples to exclude from the end of each train set before the test set"* — so scikit-learn **does** give you an embargo. Two honest caveats:
- `gap` is counted in **samples, not time**. With irregular decision timing you must convert your embargo window into a count of intervening decisions. This is a real footgun on this data (13 minute-buckets, bursty arrivals).
- `TimeSeriesSplit` does **not purge**. It will not drop a training row whose *label* resolves after the test fold begins. In this system a `PaperTrade` opened in the training window can resolve weeks later — that is exactly a label-overlap leak, and `TimeSeriesSplit` alone will not close it. Purge by `resolvedAt` yourself (§3.4).

Also verified: **`CalibratedClassifierCV` fits its calibrator via cross-validation**, and its docs warn *"When a class is absent in the test subset, the calibrator for that class … is fit on data with no positive class. This results in ineffective calibration."* With 8% positive rate in one of the two available days, that failure mode is live here. Guard the fit.

### 2.2 netcal — Apache-2.0 — **primary (calibration depth)**
Verified from the project README: *"Most of the calibration methods are designed for binary classification tasks."* Provides `scaling.LogisticCalibration` (Platt), `scaling.TemperatureScaling`, `scaling.BetaCalibration`, plus binning methods (`HistogramBinning`, `IsotonicRegression`, `BBQ`, `ENIR`), and metrics `ECE`, `MCE`, `ACE`, `MMCE`.

Why it earns a top-3 slot: the acceptance criteria here are **Brier / log-loss / calibration-error**, and scikit-learn ships no ECE. netcal is the tool that makes the acceptance gate *measurable* rather than asserted. `BetaCalibration` is the well-founded generalization of Platt (Kull et al.) and its fitted parameters are a handful of floats — trivially portable into the same JSON artifact as the linear coefficients.

Limit: calibration cadence is slow (last release 2026-04-16, 1 release in 12 months, 2 open issues) — but it is feature-complete for binary classification and tiny, so slow cadence is tolerable here. It is not a security- or correctness-sensitive dependency.

### 2.3 onnxruntime-node — MIT — **primary (TS inference)**
The credible production inference engine for a Node process. MIT, actively built (v1.29.0, 2026-08-24, monorepo pushed 2026-09-13), only 3 runtime dependencies.

Its role is the **escalation path**: if the team later moves to LightGBM/XGBoost/CatBoost, ONNX is the sane way to score it from Node without a sidecar. For the linear model that fits today's N_eff, it is unnecessary — measured below, a dependency-free scorer is exact and faster.

### 2.4 river — BSD-3-Clause — **supporting, high value**
Two things river does that nothing else here does as cleanly:
- **`drift.ADWIN`** — drift detection with mathematical guarantees (adaptive windowing, δ significance). Non-stationarity is *the* defining property of this problem; an ADWIN on the realized-Brier series gives an objective trigger to refit, disable a lane, or distrust the model, instead of a cron schedule guessing.
- **Online metrics** — `metrics.LogLoss()`, rolling wrappers, `update(yt, yp)` / `get()`. Lets the shadow loop track Brier against the incumbent continuously, which is precisely the "measure-before-implement" posture.

Models are streaming (`learn_one` / `predict_proba_one`) and `partial_fit`-style, which is a genuine alternative to weekly batch refit — but with N_eff this low, online learning will chase noise. **Use river for drift + monitoring; do not make it the model.**

### 2.5 MAPIE — BSD-3-Clause — **supporting, with a caveat**
Verified from the source tree: contains `mapie/calibration.py`, `mapie/_venn_abers.py`, `mapie/conformity_scores/sets/{aps,lac,raps,topk}.py`, `mapie/exchangeability_testing/`, `mapie/metrics/calibration.py`, and `examples/calibration/1-quickstart/plot_calibration_hypothesis_testing.py`.

- **`VennAbersCalibrator`** is the standout: Venn-ABERS gives a *calibrated* probability with validity guarantees, which is a stronger formal footing than Platt. Its fitted state is piecewise-constant (P0/P1 vectors) and therefore serializable for TS inference.
- **`exchangeability_testing`** (martingales, risk monitoring) directly addresses "has my calibration stopped being valid?" — a real question for a non-stationary feed.
- **Caveat, verified:** MAPIE's time-series support is **regression-only** (`mapie/regression/time_series_regression.py`; there is no time-series classification module). And `_venn_abers.py` imports `StratifiedKFold` — i.e. its default calibrator split **shuffles**, which leaks on time-ordered data. If you use it, pass an explicit time-ordered `cv`. Do not take its defaults.

### 2.6 skfolio — BSD-3-Clause — **supporting**
`CombinatorialPurgedCV` implements genuine purging and embargoing; verified from source: *"Purging consists of removing from the training set all observations whose labels overlapped in time with those labels included in the testing set"* and *"Embargoing consists of removing from the training set all observations that immediately follow an observation in the testing set."* That is the correct, textbook construction and it fixes scikit-learn's missing purge.

Two caveats:
- It is **combinatorial**, by design: `n_folds=10, n_test_folds=8`, producing multiple backtest paths where some training folds sit *after* the test fold. That is right for strategy *selection*; it is **not** a deployment-order simulation. For "could this have run in production?" you want sequential expanding-window walk-forward.
- It pulls in `plotly` and `pandas`. A CV splitter with a plotting dependency is a heavy way to get ~150 lines of logic. Consider lifting the algorithm.

---

## §3. Minimal usage sketches + integration path

### 3.1 Recommended architecture (verified end-to-end)

```
weekly cron (Python)                      Node/TS scoring loop
─────────────────────                     ────────────────────
export labels  ──►  refit  ──►  freeze  ──►  read artifact  ──►  score
 (with times)      (sklearn)   (JSON)        (fs.readFile)      (sigmoid)
                                 + hash      + age guard
```

**The interface between the two halves is a versioned JSON artifact, not a binary model file.** That choice is what makes the Node side zero-dependency and deterministic.

```python
# refit.py  (venv-calib, sklearn 1.6.1 verified working)
import json, numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

sc = StandardScaler().fit(X)                       # X: (n, 12) float64, time-ordered
lr = LogisticRegression(C=0.3, max_iter=5000).fit(sc.transform(X), y)

json.dump({
  "schema": "copybot-score-artifact/v1",
  "features": FEATURES,                            # order is part of the contract
  "scaler_mean": sc.mean_.tolist(),
  "scaler_scale": sc.scale_.tolist(),
  "coef": lr.coef_[0].tolist(),
  "intercept": float(lr.intercept_[0]),
  "calibration": {"method": "platt_logit", "a": ..., "b": ...},
}, open("data/score-artifact.json", "w"), indent=2)
```

```ts
// src/lib/scoring/linear-model.ts  — production scorer, zero runtime deps
import fs from "node:fs";
const art = JSON.parse(fs.readFileSync("data/score-artifact.json", "utf8"));
const sigmoid = (z: number) => 1 / (1 + Math.exp(-z));

export function scoreLinear(x: number[]): number {
  let z = art.intercept;
  for (let i = 0; i < art.features.length; i++) {
    z += art.coef[i] * ((x[i] - art.scaler_mean[i]) / art.scaler_scale[i]);
  }
  return sigmoid(z);
}
```

### 3.2 This was built and measured, not asserted

I fit the model on the repo's own 688 rows and diffed the TS scorer against scikit-learn's `predict_proba` row by row:

```
rows scored        : 688
max |TS - Python|  : 2.220e-16
parity             : EXACT (<1e-12)
total              : 0.461 ms for 688 rows
per-decision       : 0.67 us
projected 500/run  : 0.335 ms
```

**2.22e-16 is float64 epsilon** — the two implementations agree to the last representable bit. 500 decisions costs **0.34 ms**, four orders of magnitude inside any plausible latency budget, and the scorer is pure, synchronous and deterministic (no threads, no BLAS, no RNG, no native module).

Conclusion: for the linear model that suits this sample size, **ONNX Runtime is not needed.** Keep the JSON path. Adopt `onnxruntime-node` at the moment a GBDT earns its place.

### 3.3 Walk-forward with purge + embargo (the part scikit-learn does not do for you)

```python
# Label-overlap purge: drop training rows whose LABEL resolves after test start.
tr = tr[resolved_at[tr] < test_start - embargo]      # purge by resolvedAt, in TIME
# scikit-learn's gap= is in SAMPLES, so additionally:
tscv = TimeSeriesSplit(n_splits=k, gap=embargo_in_decisions)
```

Rules that follow from the verified facts:
1. Split on **time**, never at random. `KFold`/`StratifiedKFold`/`train_test_split` are all invalid here.
2. Purge on `resolvedAt`, embargo on `createdAt`. They are different fields and both matter.
3. Report **per-fold** Brier/log-loss. A pooled number hides a fold that failed.
4. Always include the **test-fold constant base-rate** as a baseline. It is the only honest floor: in the one split I could run, constant-at-train-rate scored Brier 0.739 while the test fold's own base rate would score 0.111 — a model that beats the former and not the latter has learned nothing.

### 3.4 Acceptance gate (falsifiable, N_eff-aware)

Ship a challenger only if, on held-out time folds:
- Brier **and** log-loss beat the test-fold base-rate constant, **and** beat the incumbent 6-component score;
- the paired loss differential's block-bootstrap 95% CI excludes zero;
- the CI is computed with **N_eff from §0.2** (cluster by decision time), not nominal n;
- netcal `ECE` does not regress;
- the gain survives on ≥3 consecutive folds, not one.

Given N_eff ≈ tens, expect this gate to **fail** on current data. That is the gate working.

---

## §4. NOT recommended

| library | license | why not |
|---|---|---|
| **mlfinlab** (Hudson & Thames) | **proprietary / subscription** — *verified* | GitHub license `NOASSERTION`; the LICENSE is a *"Copyright Protection Notice and Licensing Agreement"* requiring "I AGREE" / subscription sign-up, updated Nov 2021. Last push 2023-10-02. **No PyPI package (404) and no GitHub releases.** Cannot be a dependency of this repo. Its PurgedKFold/CPCV ideas are good — reimplement them (or use skfolio). |
| **timeseriescv** | MIT | v0.2, last PyPI upload **2018-09-07 — 8 years stale**; GitHub repo 404s. Unmaintained. Its whole content is PurgedKFold + embargo (~60 lines) — vendor the algorithm, not the package. |
| **betacal** | MIT | Last release **2021-04-01**, 0 releases in 12 months. Superseded by netcal's `BetaCalibration`. |
| **hummingbird-ml** | MIT | Last release 2024-10-25 (~2 years). Its value prop is compiling sklearn to tensor ops — moot when a 15-line sigmoid achieves exact parity at 0.67 µs/row (§3.2). |
| **ml-logistic-regression** (npm) | MIT | v2.0.0, last published **2020-05-03**. No calibration, no CV, single maintainer. Do not add a 6-year-old dependency to compute a dot product. |
| **npm `lightgbm`** | MIT | v1.0.27, last published 2023-11-08. Thin wrapper, not the real project. |
| **npm `xgboost`** | Apache-2.0 | Last published **2017-10-30**. Effectively abandoned. |
| **@tensorflow/tfjs-node** | Apache-2.0 | Last release 2024-10-21 (~2 years). Heavy native build for a problem whose model has 12 coefficients. |
| **skl2onnx / onnxmltools** | Apache-2.0 / MIT | Not *wrong* — just pointless for a linear model, and they add a converter version-coupling you then have to keep in sync. Worth revisiting only alongside a GBDT. |
| **LightGBM / XGBoost / CatBoost** | MIT / Apache-2.0 | **Not "bad" — "not yet."** All three are excellently maintained. But gradient boosting on N_eff in the tens with 12 features will overfit, and its calibration is an extra problem you must then solve. Revisit once labels span ≥8–12 weekly cycles. CatBoost's ordered boosting is the most defensible first GBDT at small n, if one is tried. |
| **Random k-fold / `StratifiedKFold` on this data** | — | Not a library, but the invalid default that will leak. Called out because **MAPIE's `VennAbersCalibrator` uses `StratifiedKFold` by default** — verified in `_venn_abers.py`. Never accept a time-series task's default split without checking it. |
| **isotonic calibration (`method="isotonic"`)** | — | scikit-learn's own docs: *"more prone to overfitting, especially on small datasets"*, and it *"will perform as well as or better than `sigmoid` when there is enough data (greater than ~1000 samples)."* At 688 rows / N_eff in the tens, use **sigmoid (Platt)**. Also note isotonic introduces ties, altering ranking metrics. |

---

## §5. Verdict ranking

| rank | library | license | role |
|---|---|---|---|
| **1** | **scikit-learn** | **BSD-3-Clause** | Python refit: `LogisticRegression`, `StandardScaler`, `TimeSeriesSplit(gap=)`, `CalibratedClassifierCV`. The substrate. |
| **2** | **netcal** | **Apache-2.0** | Binary calibration (Platt / temperature / beta) + `ECE`/`MCE`/`ACE` — makes the acceptance gate measurable. |
| **3** | **onnxruntime-node** | **MIT** | Production Node inference engine; the escalation path for GBDT. Not needed for the linear model. |
| 4 | river | BSD-3-Clause | `ADWIN` drift detection + rolling log-loss for monitoring non-stationarity. |
| 5 | MAPIE | BSD-3-Clause | Venn-ABERS calibration + calibration hypothesis tests. Override its shuffling defaults. |
| 6 | skfolio | BSD-3-Clause | `CombinatorialPurgedCV` when purge+embargo is needed without hand-rolling it. |

**Ranking caveat that outranks the ranking:** every entry above is secondary to §0. The binding constraint is label integrity and label volume, not library capability. A perfect library applied to the current 688-row, two-day, mixed-definition target will produce a well-calibrated estimate of an incoherent quantity.

---

## §6. Recommended next actions, in order

1. **Fix the exporter** — add `decisionAt` (`DecisionJournal.createdAt`), `resolvedAt`, `marketId`, `walletAddress`, `ruleSetVersion`, `realizedPnl` to `training_data.csv`. One-line change; unblocks everything.
2. **Split the target.** Emit separate, coherent labels per lane: (a) `paper_copy` lane → `y = realizedPnl > 0` with the exact PnL; (b) a `skip`-outcome-study table, evaluated on its own terms (avoided-loss dollars), never concatenated with (a). Drop `decision` as a feature from lane (a) once the label no longer depends on it.
3. **Accumulate labels over time.** Weekly refit needs ≥8–12 refit cycles before walk-forward is meaningful. Until then, record predictions + outcomes and evaluate offline; do not ship a model.
4. **Then** run the §3.4 gate with netcal + scikit-learn, reporting N_eff from §0.2 honestly.
5. **Then** decide whether river's ADWIN earns a permanent monitoring slot.

---

## §7. Reproduction

Artifacts from this investigation (on the analysis box):
- `/tmp/wf_experiment.py` — first walk-forward attempt; returned **zero folds** (the §0.1 finding)
- `/tmp/neff_eval.py` — ICC / design-effect / N_eff table (§0.2) + the one runnable time-ordered split
- `/tmp/dbg_label.py` — per-day label composition (§0.3)
- `/tmp/emit_artifact.py` + `/tmp/score_parity.mjs` — the Python↔Node parity proof (§3.2)
- `/tmp/artifact.json`, `/tmp/parity_in.json` — frozen artifact + inputs

Environment: `venv-calib` (Python 3.9.6, numpy 2.0.2, scipy 1.13.1, **scikit-learn 1.6.1 installed during this work**), Node v26.0.0.
Database read-only via `sqlite3` against `prisma/dev.db`. No writes to the repo database were made.
