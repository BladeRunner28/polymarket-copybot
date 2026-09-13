# Scoring fix — predictive, calibrated scores for a binary copy decision (methods shortlist)

**Status:** research + measured baseline · 2026-09-13 · paper-trading only, no execution advice
**Follow-on (executed same day):** `drafts/scoring-fix-v1-impl-20260913.md` — the v1 price-edge spec was
built, fitted and put through this doc's pre-registered test. **It FAILED** (no-effect cluster CI,
only 39% of wallets non-negative, negative under walk-forward), so it is shipped shadow-only and
nothing was wired. Read that doc for the executed numbers; this one remains the methods survey.
**Scope:** how to REPLACE/FIX the hand-weighted composite (`src/lib/scoring/trade.ts`, `copyScore`)
so it has demonstrated predictive power before it is used for admission, sizing, or venue routing.
**Everything in §1–§2 was measured on this repo's own `prisma/dev.db` today with the two scripts in
§7 (read-only, no DB writes).** Nothing in this doc is a benchmark I did not run; external method
claims are cited in §8.

---

## 0. Ranked shortlist (what to do, in order)

| # | Method | Effort | Why it ranks here |
|---|---|---|---|
| 0 | **Fix the target/label pipeline** (label the 9,642 resolved copies that already carry `realizedPnl`; re-define the target as price-adjusted PnL sign, not `wasDecisionGood`) | **Low** (~0.5–1 day) | Prerequisite, not a competitor. It moves the detectable-effect floor from **$6.16/trade to $1.29/trade** and the sample from **10 wallets to 188**. Every method below is unfalsifiable without it. |
| 1 | **Price-anchored calibrated probability + EV gate**: P(win) from entry price alone (smoothed band table or logistic in log-odds price), optionally +1–2 penalized covariates; admit iff `P(win) − price − fee > margin`; size ∝ edge later | **Low** (1–2 days) | The only measured signal in the data. Price-only AUC **0.747** vs composite **0.417**; Brier **0.199** vs base-rate 0.236. Portable to TS as a lookup table or 2–3 coefficients. |
| 2 | **Penalized/penalized-likelihood refit** (ridge logistic, Firth bias-reduction for separation) on ≤6 pre-specified predictors, **fit on the price-relative target**, with **uniform shrinkage** (van Houwelingen) and a **2-parameter calibration layer** (Platt/beta — not isotonic) | **Medium** (3–5 days) | The correct way to "refit the weights". Naive refit of the stored scores hits AUC 0.62–0.65 but calibration slope **0.37** (predictions ~2.7× too extreme) on the 688-row set — that is the trap, and shrinkage/Firth is the standard small-N remedy. |
| 3 | **Hierarchical / partial-pooling wallet model** (random effects in the logistic; beta-binomial for wallet win-rate) replacing `winRate*130−15` | **Medium-high** (3–7 days) | Wallet clustering is the dominant structure: ICC(wallet) **0.225** on 188 wallets, **0.464** on the 10-wallet label set. Raw win-rates with no pooling and no CI are what produced the "87.4 vs 86.9" wallet-quality non-result. |
| 4 | **Empirical-Bayes shrunk wallet/category estimates exported as a lookup** (closed-form; the pragmatic subset of #3) | **Low** (1 day) | Gets ~80% of #3's benefit with zero inference runtime: shrink each wallet's win-rate toward the panel mean with weight ∝ sample size, emit posterior mean + lower bound as TS-consumable JSON. |
| 5 | **Meta-labeling framing** (primary = the wallet's trade, which already exists; secondary = "will this copy pay", target = price-adjusted sign) | **Low-medium** (1–2 days) | Makes the objective explicit (filter/size an existing signal), keeps the feature set small, and is the standard way to add a second layer without pretending the first does not exist. |
| 6 | **Nested-CV + walk-forward + frozen-holdout evaluation harness** as a first-class deliverable (score versioning, cluster bootstrap, sequential monitoring) | **Medium** (2–3 days) | Without it every other row is unfalsifiable at this N. It is what turns "measure-before-implement" into a gate rather than a habit. |
| 7 | **Challenger models in a bake-off only** (TabPFN small-data tabular foundation model; gradient boosting) | **Medium-high** | Legitimate to *test* (TabPFN is designed for ~1k rows), but with effective dimensionality ≈1 in this feature set, expected lift over #1/#2 is small while the overfitting surface is large. Not for deployment. |

**Do not expect a model to rescue the composite.** The measured failure is structural: of every stored
feature, only the market's own price separates outcomes; the six component scores do not, and the
composite is *anti*-predictive at scale (§2).

---

## 1. Data inventory — the most important finding

The stated "~2,000 labeled decisions" is not what the DB contains, and the labeled subset is far
narrower than the available book:

| | `OutcomeReview` label set | Resolved paper-trade book |
|---|---|---|
| rows | **688** | **9,642** resolved/closed Polymarket copies joined to a `DecisionJournal` |
| decision split | 488 `paper_copy` + 200 `skip` | 100% copies (BANKROLL_200 1,473 / STANDARD 8,169) |
| distinct wallets | **10** | **188** |
| distinct markets | 178 | 2,568 |
| time span | **1 day** (created 2026-07-14T20:13Z → 2026-07-15T20:45Z; observed trades 07-14→07-15) | **60 days** (2026-07-15 → 2026-09-12) |
| features present | full component breakdown | full component breakdown (`walletQualityScore>0` for all 9,642), `ruleSetVersion` non-null |
| target available | `wasDecisionGood`, `simulatedPnl` (mixed semantics) | `entryPrice` + **booked `realizedPnl`** (a real, size-weighted, fee-inclusive label) |

Two consequences:

1. **The label table is a one-day cohort.** `scripts/review-outcomes.ts` pulls 200 unreviewed
   decisions per run ordered `paper_copy` first, so the 688 rows are one day's decisions that have
   since resolved — not a sample of the book. No drift robustness, no regime coverage.
2. **The labels are already derivable for 9,642 decisions** from `PaperTrade.realizedPnl` +
   `entryPrice` + `observedTrade.outcome`. The binding constraint is not model class, it is
   *labelled effective sample*, and ~93% of the available labels are sitting unused.

Also confirmed (relevant to any feature work): the stored `marketCategory` values in the reviewed set
are unreliable (`fifwc` for "France vs. Spain: O/U 2.5"; 16 distinct values), so `categoryFitScore`
rests on a field that does not mean "category".

---

## 2. Measured baseline (run today, both scripts in §7)

Cross-validation is **grouped by `marketId`** (respects repeated entries in one market); ridge penalty
picked by inner 3-fold CV on the training part only; target = "did the copied position make money".
`AUC` is pooled out-of-fold; per-fold means are given because pooled AUC across clusters with
different base rates is not a fair summary on its own.

### On the 688-row label set (target: copied token won)

| ranker | AUC [row-bootstrap 95% CI] | per-fold AUC | Brier | calib slope |
|---|---|---|---|---|
| stored `copyScore` | 0.518 [0.465, 0.570] | 0.485 (0.34–0.69) | n/a (not a probability) | — |
| **entry price alone** | **0.739** [0.703, 0.775] | 0.753 | — | — |
| smoothed price-band lookup (OOF) | 0.870 [0.839, 0.898] | 0.811 | **0.119** | 1.08 |
| ridge refit of the 8 stored scores | 0.653 [0.604, 0.704] | 0.670 | 0.189 | **0.37** |
| ridge refit price + execution scores | 0.506 [0.458, 0.552] | 0.705 | 0.252 | −0.01 |

Note on CIs: these are row bootstraps. Under the wallet clusters, the band-lookup AUC CI widens from
[0.839, 0.898] to **[0.785, 0.938]** (`supplementary.band_model_auc_cluster_ci`) — use cluster
bootstrap throughout (§5.7). The pooled-vs-per-fold split for the last row is itself a warning:
pooled 0.506 with per-fold 0.705 means the folds have different base rates and the pooled number is
not a fair summary.

### On the 9,642-row resolved book (target: `realizedPnl > 0`, base rate 0.618, mean +$0.72/trade, sd $12.89)

| ranker | AUC | per-fold mean (min–max) | Brier | calib slope | calib intercept |
|---|---|---|---|---|---|
| stored `copyScore` | **0.417** | 0.406 (0.32–0.49) | **0.277** | — | — |
| **entry price alone** | **0.747** | 0.744 (0.71–0.79) | **0.199** | — | — |
| smoothed price-band lookup (OOF) | 0.700 | 0.725 (0.69–0.77) | 0.206 | 0.84 | +0.60 |
| ridge refit price + execution scores | 0.736 | 0.748 (0.71–0.83) | 0.200 | 0.90 | +0.67 |
| ridge refit of the 8 stored scores | 0.623 | 0.644 (0.60–0.68) | 0.227 | 0.71 | +0.51 |

Read-outs that matter:

- **The composite is anti-predictive at scale** — AUC 0.417 (below 0.5), and its Brier **0.277 is worse
  than predicting the base rate for every trade (0.236)**. (Caveat: the composite is not a probability,
  so Brier flatters-or-penalises it as a ranking; both views agree it carries no usable signal.)
- **The market price already beats the base rate**: Brier 0.199 vs 0.236, AUC 0.747, stable across all
  five folds. Any model that does not beat price-only is adding nothing.
- **The execution features add nothing**: `price + size + spread + liquidity + entry-timing` scores
  AUC 0.736 vs price-only 0.747. They are not evidence of an edge; they are evidence of a market.
- **Refitting the stored scores is not a fix**: AUC 0.62–0.65 with calibration slope 0.37 (688-set) —
  probabilities roughly 2.7× too extreme, i.e. classic small-N overfitting.

### Effective sample size (why the numbers above have wide error bars)

| scope | groups | mean cluster | ICC | design effect | effective N |
|---|---|---|---|---|---|
| 688-label set, by wallet | 10 | 68.8 | **0.464** | 32.4 | **≈21** |
| 688-label set, by market | 178 | 3.87 | 0.903 | 3.59 | ≈192 |
| 9,642 rows, by wallet | 188 | 51.3 | **0.225** | 12.3 | **≈784** |
| 9,642 rows, by market | 2,568 | 3.75 | 0.904 | 3.49 | ≈2,763 |
| **3,481 decisions (deduped), by wallet** | 188 | 18.5 | **0.093** | 2.64 | **≈1,321** |
| **3,481 decisions (deduped), by market** | 2,569 | 1.4 | 0.810 | 1.29 | ≈2,704 |

The last two rows matter: collapsing duplicate accumulation rows (64% of the book) removes a large
part of the apparent clustering — ICC(wallet) falls from 0.225 to 0.093 and the effective N rises to
≈1,321, i.e. **MDE ≈ $1.08/trade** (per-trade net sd $14.01) rather than the row-level ≈$1.29. Both
sets give the same instruction, but the decision-level figures are the ones to quote. See
`drafts/scoring-fix-v1-impl-20260913.md` §1 for the dedupe accounting and
`data/decision-dataset.manifest.json` for the counts.

Minimum detectable per-trade edge (80% power, α=0.05, per-trade sd from the data):

| sample | effective N | MDE ($/trade) |
|---|---|---|
| 688 labels (10 wallets) | 21 | **$6.16** |
| 9,642 resolved copies (188 wallets) | 784 | **$1.29** |
| 25,000 decisions | 2,033 | $0.80 |

The measured wallet-cluster CI for the whole book's mean PnL illustrates the correction: on the
688-row set, mean +$0.98/trade with a **row** bootstrap CI [+0.23, +1.77] but a **wallet-cluster**
bootstrap CI **[−3.35, +4.14]**. Row-level resampling of clustered decisions produces false
confidence by a factor of ~2.5.

### The EV gate, measured (9,642 book, out-of-fold band model)

Copy iff `P̂(win) − entry > fee`:

| fee | selected | share | win rate | mean entry | excess | realized $ | $/trade |
|---|---|---|---|---|---|---|---|
| 0.00 | 4,212 | 43.7% | 0.479 | 0.448 | +0.031 | +$2,014 | +$0.48 |
| 0.02 | 3,601 | 37.3% | 0.465 | 0.431 | +0.034 | +$1,727 | +$0.48 |
| 0.03 | 3,312 | 34.3% | 0.459 | 0.422 | +0.036 | +$1,711 | +$0.52 |
| (no gate) | 9,642 | 100% | 0.618 | — | — | +$6,942 | **+$0.72** |

This is the honest, awkward result: a price-based EV gate **raises excess return** (+3.1→+3.6pp) but
**lowers $/trade** ($0.48 vs $0.72) because it concentrates on cheap longshots whose payoff asymmetry
and costs eat the edge. And the wallet-blocked version (band table fit on the other wallets, evaluated
on the held-out wallet, n≥5) is **65 wallets positive / 61 negative** — a coin flip across wallets.
So: a promising direction, **not** a demonstrated edge, and the choice of objective (excess vs
$/trade) changes the answer. Pre-register the objective; report both.

---

## 3. Method detail and pitfalls

### #0 Label/target pipeline (prerequisite)
Build one row per resolved decision: `entryPrice`, raw spread/liquidity/ttr at decision time,
component scores + `copyScore` (kept only as a legacy comparator), wallet, market, category,
`ruleSetVersion`, and the target. Use **two** targets and never conflate them:
`y_win = 1[token won]` (probabilistic target) and `y_pnl = realizedPnl` (decision target). Rebuild
`wasDecisionGood` as "sign of price-adjusted copy PnL" if it is to stay, because today it agrees with
the trade's own PnL sign only **484/688 = 70.3%** of the time (skip rows use `good = !won`).
*Pitfall:* `training_data.csv`'s columns are already misleading — `spread` and `liquidity` are the
stored **scores**, and `ttr_hours` is `entryTimingScore` (`scripts/export-training-data.ts:35`).
Any model trained on that file as-is is trained on a mislabelled column.

### #1 Price-anchored probability + EV gate (the workhorse)
Fit `P(win) = σ(a + b·logit(price))` (or an isotonic-smoothed band table), then admit iff
`P(win) − price − fee > margin`. Equivalently: model **excess return** `P(win) − price`, which is the
quantity that pays for a binary contract.
*Why:* measured — price-only AUC 0.747, Brier 0.199; smoothed lookup AUROC 0.700–0.870 depending on
sample, calibration slope 0.84–1.08.
*Pitfalls:* (a) it mostly re-expresses the market; the excess it finds sits in cheap contracts whose
payoff asymmetry means excess ≠ $/trade (measured above); (b) it must carry the fee/round-trip cost
explicitly; (c) it will not survive a venue whose prices are already efficient in that band
(the repo's own Wang-λ audit found λ≈0 in 0.40–0.60).

### #2 Penalized refit + shrinkage + calibration layer
Small-N logistic done properly: pre-specify ≤6 predictors (the count matters — with effective N ≈21
on the label set, one predictor is the honest budget; with ≈784, six is defensible), ridge-penalize
or use Firth's bias-reduced likelihood if any cell is separated, then apply a **uniform shrinkage
factor** and fit a 2-parameter calibration map on out-of-fold predictions.
*Why:* the naive refit is measurably overfit (calibration slope 0.37); shrinkage/penalization exists
precisely for this, and calibration slope/intercept is the diagnostic that exposes it.
*Pitfalls:* never tune the penalty on the same rows used to report performance; never report AUC
alone (it is invariant to calibration — a model can have AUC 0.75 and useless probabilities).

### #3 / #4 Wallet effects: partial pooling instead of raw win rates
Replace `walletCategoryWinRate*130 − 15` with a shrunk estimate: beta-binomial posterior for each
wallet's (and wallet×category's) win rate, or wallet random effects inside the logistic. Emit
posterior mean **and** a lower bound; gate on the lower bound, not the mean.
*Why:* ICC(wallet) = 0.225 (188 wallets) / 0.464 (10-wallet label set); one wallet in the label set is
0/68 and another 47/48; and the price→outcome map is not stable under wallet removal — 0.30–0.40:
63.2% win all-sample (n=76) vs **5.6%** with the three largest wallets removed (n=18); 0.60–0.70:
17.1% → 0.0%; 0.10–0.20: 45.0% → 0.0% (`data/pilot-scoring-separation.json`,
`supplementary.band_stability_excl_top3_wallets`). Raw win-rate features are, in this data, wallet
identity in disguise.
*Pitfalls:* with ~10 groups the between-wallet variance τ is poorly identified — use weakly
informative priors and report the posterior interval; and 30 trades is not a wallet assessment.

### #5 Meta-labeling
Primary signal = the wallet's trade (already generated). Secondary model = "will this copy pay",
trained on the price-adjusted label with the primary's context as features. Output = filter + size,
never a *new* directional signal.
*Pitfall:* feature/label overlap (using post-entry information — e.g. any `MarketSnapshot` collected
after the decision — leaks the outcome; check `s.collectedAt > d.createdAt`).

### #6 Evaluation harness
Nested CV for any tuning; **grouped** folds (market and wallet) — never random rows; walk-forward
for time; frozen holdout for promotion; cluster bootstrap for uncertainty; sequential monitoring for
the live window.

### #7 Challengers
TabPFN (small-data tabular foundation model, Nature 2025) and gradient boosting are worth a bake-off
row, not a deployment. With ~1 effective dimension and clustered labels, tree ensembles will memorise
wallet/market clusters and cannot extrapolate to prices outside the training range.

---

## 4. Validation design (offline first — the spec to pre-register)

The user's measure-before-implement rule is enforceable if the following is frozen **before** any
refit. Suggested artifact: `data/score-spec-v<N>.json` (features, functional form, coefficients or
lookup, fee assumption, objective, version), versioned like a `RuleSet`, one change per version.

1. **Population and unit.** One row per decision; unit = decision, cluster = (wallet, market).
   Pick *one* target population per spec (e.g. BANKROLL_200 main lane) and state it.
2. **Splits.**
   - *Walk-forward*: fit on ≤ T, evaluate on (T, T+Δ]; roll forward in ≥4 blocks (60 days available).
   - *Wallet-blocked* (required for any wallet-agnostic claim): fit on all-but-K wallets, evaluate on
     K; repeat over 5 random K-subsets of ~20 wallets. Report per-wallet results, not just the pool.
   - *Market-blocked* for within-wallet claims.
   - Random row-level k-fold is **banned** in this dataset (ICC 0.90 by market, 0.22 by wallet).
3. **Metrics (report all, every time).**
   - Primary: fee-inclusive, size-weighted **$/trade** on the selected subset vs (a) the incumbent
     composite and (b) copy-everything.
   - Secondary: AUC; Brier vs base-rate Brier; **calibration slope** (target 0.8–1.2) and intercept;
     reliability table with n ≥ 50 per bin.
   - Robustness: wallet-cluster bootstrap 95% CI; share of wallets with non-negative $/trade (require
     ≥60% — the current gate is at 65/61 ≈ chance); per-fold dispersion.
4. **Power, stated up front.** With the 688-label set the MDE is ≈$6.16/trade; with the full 9,642-row
   book ≈$1.29/trade. Therefore: pre-register the minimum edge worth deploying (e.g. ≥$1.50/trade over
   the incumbent) and, if the target is not yet detectable, **do not gate** — keep collecting labels.
5. **Sequential monitoring.** Fixed checkpoints (e.g. every +500 labelled decisions) with
   alpha-spending or always-valid confidence sequences, not daily peeking at p-values. The daily
   report may show point estimates but must not gate on them; any gate on a score whose AUC CI
   includes 0.5 is noise-driven by construction (the composite's own CI is [0.465, 0.570]).
6. **Promotion / rollback.** New version promoted only if it beats the incumbent on the *same frozen
   holdout* by more than the pre-registered margin; old version retained; rollback is one rule flag.
   Refit cadence: monthly (or per ≥300 new labels) — daily refits on 60 days of data are noise-fitting.
7. **Search accounting.** Pre-register ≤5 variants per cycle and record the number actually tried;
   beyond that, deflate for selection (deflated Sharpe / Reality-Check style) or the reported effect
   is search artefact.
8. **Shadow phase.** Score every decision with the candidate, store it, gate nothing; compare
   counterfactual admission sets (agreement, marginal $/trade) for the pre-registered window before
   any admission/sizing change. This is also the cheapest way to detect calibration drift in the
   live mix (the label set's mean entry price is **0.748** — a favourites-heavy cohort — which is not
   the live decision mix, so a model calibrated on it arrives miscalibrated in level).
9. **Reproduce in one command.** `./venv-calib/bin/python scripts/pilot-score-separation-papers.py`
   (and the 688-row variant) → JSON artifacts in `data/`.

---

## 5. Pitfalls (each one measured or verified in this repo)

1. **688 rows ≠ 688 samples.** 10 wallets, one day, ICC(wallet)=0.464 → effective N ≈ 21,
   MDE ≈$6.16/trade. Gating on anything measured from this set is procedure, not evidence.
2. **Mixed label semantics.** `wasDecisionGood` = copy-PnL sign for copies but `!won` for skips
   (agreement with the trade's own sign: 70.3%). A single model trained on the mixture learns two
   incompatible tasks.
3. **Wallet identity, not signal.** Two wallets dominate: 0/68 and 47/48; removing the three largest
   wallets collapses the price→outcome map (0.30–0.40: 63.2% → 5.6%; 0.10–0.20: 45.0% → 0.0%). Any
   model that can see wallet identity will memorise it.
4. **Anti-predictive composite.** AUC 0.417 (per-fold 0.32–0.49) and Brier 0.277 > 0.236 base rate on
   9,642 copies. The venue-routing gate built on it is dormant for good reason.
5. **Excess return ≠ $/trade.** The EV gate raises excess (+3.6pp) while lowering $/trade
   ($0.52 vs $0.72). Fees, sizing, and payoff asymmetry decide the answer — choose the objective
   deliberately and report both.
6. **Naive refit overfits silently.** Ridge refit of the 8 stored scores: AUC 0.653, calibration slope
   0.37 — probabilities ~2.7× too extreme. Always report the calibration slope.
7. **Row bootstrap lies here.** Same mean, CI [+0.23,+1.77] row-wise vs [−3.35,+4.14] wallet-clustered.
8. **Regime drift.** The resolved book spans rule sets 2–52 with changing gates, sizing and floors;
   `copyScore` does not mean the same thing across versions. Include version as a stratifier.
9. **Repeated entries in one market.** ICC(market)=0.904; duplicates are one bet counted N times
   (already documented in `analyze-calibration.py --dedupe`).
10. **Isotonic calibration at this N.** With hundreds of rows and many distinct scores it overfits;
    prefer 2-parameter Platt/beta calibration fit inside nested CV.
11. **Costs erase thin edges.** All-time C-200 PnL is negative in every composite band while some
    bands show positive excess — the round-trip cost is the difference.
12. **Label accrual is biased.** `review-outcomes.ts` takes 200 at a time, `paper_copy` first, so skips
    lag and the labelled mix ≠ the live mix; a model calibrated on the label mix will be miscalibrated
    live.
13. **Mislabeled export.** In `training_data.csv`, `spread`/`liquidity` are stored scores and
    `ttr_hours` is `entryTimingScore` — verified in `scripts/export-training-data.ts`.
14. **Category is not a category** (`fifwc` for a France–Spain O/U market), so `categoryFitScore`
    cannot be interpreted as fit by category.

---

## 6. Explicit non-recommendations

- **Gradient boosting / LightGBM / XGBoost as the primary score** — effective N is 21–784 with strong
  cluster effects; trees will memorise wallets/markets and cannot extrapolate price.
- **Deep nets / sequence models** — no data volume, no stationary structure to learn.
- **Isotonic regression as the calibration layer** at this N (2-parameter calibration is enough).
- **Unvalidated LLM/text features** (thesis clarity) as an admission input before they pass the same
  offline gate as everything else.
- **Any method that cannot be evaluated offline first** — including "just retune the weights until the
  daily PnL looks better"; that is the search-artefact failure mode this doc is designed to prevent.
- **Shipping any gate on a score whose AUC CI includes 0.5** (today's composite: [0.465, 0.570]).

---

## 7. Measurement tooling added by this research (read-only)

| artifact | what it does |
|---|---|
| `scripts/pilot-score-separation.py` | 688-row `OutcomeReview` set: 6 model classes, market-grouped OOF CV, per-fold AUC, row + cluster bootstrap CIs, ICC/design-effect/effective-N, MDE table, wallet-blocked EV gate, per-wallet label audit |
| `scripts/pilot-score-separation-papers.py` | same question on all 9,642 resolved copies joined to `DecisionJournal`; adds EV-gate sweep by fee and wallet-blocked gate accounting |
| `data/pilot-scoring-separation.json` | results for the label set |
| `data/pilot-score-separation-papers.json` | results for the resolved book |
| `scripts/build-decision-dataset.py` | builds the labeled decision dataset (`data/decision-dataset.csv` + manifest): price-adjusted targets, fee-adjusted PnL, leakage-safe raw features, dedupe |
| `scripts/fit-price-edge.py` | fits M1/M2/M3, runs the pre-registered acceptance test, emits `data/score-spec-v1.json` + `-eval.json` |
| `src/lib/scoring/price-edge.ts` + `tests/price-edge.test.ts` | the portable shadow-only score and its 16 tests (incl. spec-integrity against the emitted JSON) |

Run: `./venv-calib/bin/python scripts/pilot-score-separation.py` (numpy 2.0.2 / scipy 1.13.1 already in
`venv-calib`; numpy+scipy only, no sklearn). No DB writes; both scripts are pure reads.

Known limits of these pilots (do not over-read them): spread/liquidity/entry-timing inputs are the
stored **scores**, not raw values; `MarketSnapshot` rows exist for all 178 label-set markets and the
earliest snapshot per market is never timestamped after its decision (checked), but they were
deliberately not used as features to avoid post-decision leakage questions; fees are modelled as a
flat probability offset in the gate sweep; the "band lookup" baseline is deliberately crude (12 bands,
Laplace smoothing) so that the comparison is portable to TypeScript, not optimal.

---

## 8. Sources

Calibration / small-N prediction models
- Peduzzi et al. 1996, *A simulation study of the number of events per variable in logistic regression analysis*, J Clin Epidemiol — origin of the EPV≥10 rule. https://www.jclinepi.com/article/S0895-4356(96)00236-3/pdf
- van Smeden et al. 2016, *No rationale for 1 variable per 10 events criterion for binary logistic regression analysis*, BMC Med Res Methodol — EPV=10 has weak evidential basis. https://link.springer.com/article/10.1186/s12874-016-0267-3
- van Smeden et al. 2019, *Sample size for binary logistic prediction models: Beyond events per variable criteria*, Stat Methods Med Res — performance is driven by number of predictors, outcome balance, and total n. https://pubmed.ncbi.nlm.nih.gov/29966490
- Riley et al. 2018, *Minimum sample size for developing a multivariable prediction model: PART II — binary and time-to-event outcomes*, Stat Med; Riley et al. 2019, *Calculating the sample size required for developing a clinical prediction model*, BMJ (m441) — formal computation replacing rules of thumb. https://onlinelibrary.wiley.com/doi/10.1002/sim.7992 · https://eprints.keele.ac.uk/7880/1/bmj.m441.full.pdf ; implementation `pmsampsize` https://cran.r-project.org/package=pmsampsize
- Steyerberg et al. 2014, *Towards better clinical prediction models: seven steps for development and an ABCD for validation*, Eur Heart J. https://academic.oup.com/eurheartj/article/35/29/1925/2293109
- Van Houwelingen & Le Cessie 1990 heuristic shrinkage; current evidence on its agreement with optimal shrinkage: https://link.springer.com/article/10.1186/s41512-026-00222-1
- Separation / bias-reduced estimation: Firth logistic regression in Python (`firthlogist`, sklearn-compatible) https://pypi.org/project/firthlogist/ and R `logistf` https://cran.r-project.org/package=logistf
- van Calster et al. 2016, *A calibration hierarchy for risk models was defined: from utopia to empirical data*, J Clin Epidemiol — weak/moderate/strong calibration; why slope/intercept must be reported. https://pure.eur.nl/en/publications/a-calibration-hierarchy-for-risk-models-was-defined-from-utopia-t

Probability calibration
- Niculescu-Mizil & Caruana 2005, *Predicting good probabilities with supervised learning*, ICML — Platt vs isotonic behaviour by sample size. https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf
- Kull, Silva Filho & Flach 2017, *Beta calibration: a well-founded and easily implemented improvement on logistic calibration for binary classifiers*, AISTATS. https://proceedings.mlr.press/v54/kull17a.html
- scikit-learn probability-calibration docs (sigmoid vs isotonic guidance). https://scikit-learn.org/stable/modules/calibration.html
- Brier score decomposition (reliability/resolution/uncertainty): https://en.wikipedia.org/wiki/Brier_score

Validation under limited data / clustered and temporal structure
- Varma & Simon 2006, *Bias in error estimation when using cross-validation for model selection*, BMC Bioinformatics — nested CV. https://link.springer.com/article/10.1186/1471-2105-7-91
- Roberts et al. 2017, *Cross-validation strategies for data with temporal, spatial, hierarchical structure*, Ecography. https://www.wsl.ch/lud/biodiversity_events/papers/Roberts_et-al-2017-Ecography.pdf
- López de Prado 2018, *Advances in Financial Machine Learning* — purged/embargoed CV and **meta-labeling** (secondary model filters the primary signal). https://quantmemo.com/concepts/meta-labeling · https://quantmemo.com/concepts/purged-embargoed-cv
- Bailey & López de Prado, *The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality*. https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf

Sequential monitoring of the live window
- Howard et al. 2021, *Time-uniform, nonparametric, nonasymptotic confidence sequences*, Ann. Statist. https://arxiv.org/abs/1810.08240
- Johari et al., *Always Valid Inference: Continuous Monitoring of A/B Tests*, Operations Research. https://arxiv.org/abs/1512.04922

Small-data tabular models (challenger only)
- Hollmann et al. 2025, *Accurate predictions on small data with a tabular foundation model* (TabPFN), Nature. https://www.nature.com/articles/s41586-024-08328-6

Prediction-market structure (why price carries information and where it does not)
- Snowberg & Wolfers 2010, *Explaining the Favorite–Long Shot Bias*, JPE — misperception-driven price distortion at the extremes. https://www.nber.org/papers/w15923
- Repo-internal: `drafts/wang-calibration-audit.md` (Wang-transform λ̂ on this bot's entries: λ̂≈0 in 0.40–0.60, strongly negative below 0.20), `scripts/analyze-calibration.py` (excess-return z-stats by band/hour, with the duplicate/dedupe caveat).
