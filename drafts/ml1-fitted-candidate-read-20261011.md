# ML-1 fit arm — a pre-registered fitted family does not beat price-only

**Cards:** `phase-ml1` (the fit), `ml1-fitted-candidate-read` (Done), `ml1-fit-population-gaps` (Backlog)
**Date:** 2026-10-11 · **Approval:** "Do the migration and then I approve starting on the fit"
**Status:** measurement only — no RuleSet, threshold, size or live lane touched. Nothing promoted.

---

## 1. Key insight

**Price is not just the bar, it is the best ranker this book has.** Fitting the stored features
does not merely fail to beat price-only out of sample — it makes ranking *significantly worse*,
while looking *better* in sample. On the fit population the feature-bearing candidates reach
in-sample AUC 0.741–0.745 and land at 0.681–0.702 on the frozen holdout, with ΔAUC confidence
intervals that exclude 0 **on the wrong side**. That is the signature of a model memorising a
regime, not of a signal that needs a better fit.

The anchor is what makes the read trustworthy: C0 — a logistic on `logit(entry_price)` alone — must
reproduce the price-only AUC *exactly*, because it is a monotone transform of price. It does, to
4dp, on both populations (0.7093 and 0.7292; ΔAUC 0.0000, CI [0,0]). Its Brier improves a hair
(0.2184→0.2178, 0.2110→0.2107): a **calibration** gain, not ranking information. So the fitter and
the wiring are right, and the negative result is about the features.

## 2. What ran

- **Family, pre-registered in the script header before the run:** C0 price-only (anchor) ·
  C1 price + stored components · C2 price + execution features · C3 combined. Ridge logistic
  (`src/lib/logistic.ts`, IRLS, intercept unpenalised, standardisation on train rows only).
- **λ** chosen on an **inner time-ordered holdout of the train window only** (grid 0.03–3), never on
  the test window, never on a random split (the doctrine checker bans random folds repo-wide).
- **Judged by the same harness as the static arms:** the candidate is trained inside
  `src/lib/ml1-read.ts` on that split's train rows and scored on its test rows — same holdout, same
  market-clustered paired bootstrap (2,000 iters, seed 20261011), same money arm. Frozen boundary
  2026-08-21.
- `npx tsx scripts/ml1-fit-candidate.ts` → `data/ml1-fit-candidate.json`.

## 3. The read

**Fit population — `training_data.csv`** (test n=2,306, base rate 0.4926, 1,771 markets, price-only AUC 0.7093 / Brier 0.2184):

| candidate | test AUC | ΔAUC vs price (95% CI) | in-sample AUC | calibration slope |
|---|---|---|---|---|
| C0 price-only (anchor) | 0.7093 | 0.0000 [0, 0] | 0.7405 | 0.877 |
| C1 price+stored (8 feats) | 0.7022 | −0.0071 [−0.0169, +0.0032] | 0.7431 | 0.814 |
| C2 price+exec (7 feats) | 0.6808 | **−0.0239 [−0.0366, −0.0106]** | 0.7419 | 0.723 |
| C3 combined (14 feats) | 0.6808 | **−0.0238 [−0.0384, −0.0090]** | 0.7449 | 0.712 |

**Bar population — `decision-dataset.csv`** (test n=1,060, base rate 0.5349, price-only AUC 0.7292 / Brier 0.2110):

| candidate | test AUC | ΔAUC vs price (95% CI) |
|---|---|---|
| C0 price-only (anchor) | 0.7292 | 0.0000 [0, 0] |
| C1 price+stored (9 feats) | 0.5978 | −0.1315 [−0.1684, −0.0914] |
| C2 price+exec (7 feats) | 0.7030 | −0.0224 [−0.0409, −0.0063] |
| C3 combined (15 feats) | 0.6649 | −0.0605 [−0.0905, −0.0310] |

- **Bar:** AUC ≥ 0.729 **and** Brier ≤ 0.212 vs price-only. No fitted candidate clears it. On the
  bar's own population the *comparator itself* clears it (0.7292 / 0.2107) — a comparator that
  passes its own thresholds is not a candidate, and a tie with it is not a promotion. (That is
  finding card `ml1-price-baseline-drift`, restated as a measurement.)
- **Money arm (AUC is not money):** on `training_data.csv` the top tercile loses to copy-all
  whichever score picks it — price −2.37 $/leg CI [−5.13, −0.15], C1 −2.54 [−5.29, −0.28],
  C2 −2.67 [−5.49, −0.31], C3 −2.52 [−5.35, −0.15]; on `decision-dataset.csv` every arm's CI spans
  0. No fitted candidate improves the money arm over price. This is the U2 lesson again.
- **Calibration slopes** on test: every feature-bearing model is over-confident (0.71–0.81 on the
  fit book, C1 down to 0.368 on the bar population) where the price anchor sits at 0.88–0.99.

## 4. Reality checks

- **The export carries no terminal stamp.** `training_data.csv` has no closed/settled column, so the
  harness reports `purged 0` — the doctrine's purge cannot run on the file the model is fitted on,
  while it purges 148 rows on `decision-dataset.csv`. A leg that settled inside the test window may
  be trained on. Carded: `ml1-fit-population-gaps`.
- **The train window is a single era.** All 2,539 train rows are `pre-kelly-v1-48`; the 2,306 test
  rows span pre-kelly 850 / kelly-window 832 / exposure-v58plus 624. Every candidate is fitted on
  regime 1 and scored across regimes 1–3 — the most plausible reason in-sample 0.744 lands at
  0.68–0.70, and the same direction as price's own recorded era decay (0.758 → 0.673 → 0.654).
- **Rows with missing features drop, and that is per candidate.** C2/C3 lose 90 train / 80 test rows
  (raw volume / ttr gaps); `confidence` does not exist in this export, so C1 there is price + 8
  components. Both are reported in the artifact rather than silently imputed.
- **Sample size is the binding constraint on this conclusion.** 2,539 train rows cannot separate a
  modest edge from noise; what the CIs support is "no gain measured, two families measurably worse",
  not "no feature can ever help".
- **The stored features were already known to be weak** (skip-probe rankers: consistency 0.599,
  wallet quality 0.543, copyScore 0.408 vs price 0.932). This run prices what fitting them buys:
  nothing.

## 5. Verdict

The fit arm is a **documented negative**: price-only stands, and no fitted candidate is promotable.
The value delivered is that the promotion gate is now *exercisable* — a fitted candidate can be run
through the same harness, with an anchor that proves the wiring, so the next idea can be judged
rather than argued. Two population defects that limit any fit on this book are carded separately.

**Reproduce:** `npx tsx scripts/ml1-fit-candidate.ts` (full read) · `npx tsx scripts/ml1-gate-read.ts`
(comparators + calibration) · `npx vitest run` (480 tests) · `python3 scripts/check-split-doctrine.py`

## 6. Where to go next (pick one; nothing below is started)

1. **Close the fit arm and run the shadow A/B with the price-based scorer** — the read says the
   remaining ML-1 arm should carry price, not a refit of these features. Cheapest path that keeps
   `phase-ml1` moving.
2. **Fix the two population gaps first** (`ml1-fit-population-gaps`: terminal stamp → purge, era
   coverage printed at export), then re-run the same family. Turns "may be leaking" and
   "trained on one era" into measured facts before any bigger fit is attempted.
3. **Change the feature basis, not the fitter** — a candidate only worth fitting if its features
   carry a *mechanism* price cannot see (e.g. the U1 conditional-fill / markout tape features), and
   then pre-registered on forward data rather than on this back book.
