# ML-1 target & price-only baseline — measurement report

**Card:** `ml1-target-net-pnl-and-price-baseline` (column: Backlog)
**Date:** 2026-10-11 · **Mode:** read-only measurement. No repo edits, no git writes, no DB writes,
no rule/threshold/size change. Only write is this file.
**Measurement code (scratch, read-only):**
`/Users/xsnyde2/.hermes/cache/scratch/ml1_measure.py`, `ml1_training_check.py`, `ml1_outcome_arm.py`
(venv `/Users/xsnyde2/.hermes/cache/scratch/ml1venv`, py3.11 + sklearn 1.9.1 / pandas 3.0.6).

**Gate text (verbatim from the card):**
> training_data.csv carries pnl_net_entry as the target (not the binary wasDecisionGood) plus the
> horizon features; ML-1's promotion gate is restated as 'beats price-only (AUC 0.747 / Brier 0.199
> vs base rate 0.236) on a time-ordered holdout' - beating copyScore proves nothing.

---

## 1. Files confirmed

| file | card says | measured | note |
|---|---|---|---|
| `scripts/export-training-data.ts` | "emits 8 columns" | **emits 13** | `ruleSetVersion`/`era`/`decision_at`/`simulated_pnl` were added later (tuning review #31). Header line 46. |
| `training_data.csv` | (8) | **7,674 rows × 13 cols** | `review_id,decision,confidence,wallet_score,trade_size,spread,liquidity,ttr_hours,was_good,ruleSetVersion,era,decision_at,simulated_pnl`. Target = `was_good` = `wasDecisionGood`. `spread`/`liquidity` are stored **scores**, and `ttr_hours` is written as `entryTimingScore` (`export-training-data.ts:61`, `// proxy for ttr`). Decision mix: paper_copy 5,869 / watchlist 1,605 / skip 200. `confidence==0` on **all 200 skip rows** (card's claim — confirmed). |
| `data/decision-dataset.csv` | "3,516 deduped rows × 40 cols" | **3,516 rows × 38 cols** | 2026-07-15 → 2026-09-12, 2 venue (3481 Polymarket / 35 Kalshi), 188 wallets. |

Commands used:
```
sqlite3 'file:prisma/dev.db?mode=ro&immutable=1' ".schema PaperTrade"
./venv-calib/bin/python - <<'EOF'  # csv header/row count + sum(pnl_*)
/Users/xsnyde2/.hermes/cache/scratch/ml1venv/bin/python ml1_measure.py
```

### Headline sums reproduced (data/decision-dataset.csv)
```
SUM pnl_gross      =   +1067.89   ✓ card +$1,067.89
SUM pnl_net_entry  =    +297.60   ✓ card +$297.60
SUM pnl_net_full   =    +168.56   ✓ card +$168.56
```
All three reproduce **exactly** (n=3,516 each). No delta.

**Stale card claims (do NOT reproduce):**

| card claim | measured today | why |
|---|---|---|
| export "emits 8 columns" | 13 | later review added era/version/timestamp/pnl |
| decision-dataset "40 cols" | 38 | — |
| "62.8% 'good' with -0.98 average PnL" | training_data.csv: **51.2% good, +$0.23 mean**; paper_copy subset **53.9%, +$0.33** | file regenerated since the card (card 2026-09-16) |
| "avg winner +5.28 vs avg loser -11.28" | training_data.csv **+6.02 / −5.84** (paper_copy +9.89 / −10.84); decision-dataset gross **+7.13 / −9.07** | same |
| "73.7% of finished legs exit early" | **73.1%** (8,267 early-exit / 11,307 finished, live DB today) | book grew |

---

## 2. The target question (measured): why `wasDecisionGood = 1[PnL>0]` is the wrong target

On the 3,516 decision-dataset rows (label basis printed for every figure):

- win rate **57.8%** (2,034/3,516, `realizedPnl>0`) — a win-rate target calls this a *good* book —
  while **mean `pnl_net_entry` is only +$0.08** (median +$0.11). The lane is negatively skewed:
  avg winner gross **+$7.13** vs avg loser gross **−$9.07** (skew −$1.94). Maximising the count of
  wins is not the objective that pays.
- `pnl_net_entry>0` base rate **57.3%** (2,014/3,516). The two sign-labels move only **20 rows**
  (0.6%): on the acted book fees are small relative to the ±$9 PnL swings, so "net of fee" barely
  *flips* the label. The reason to switch targets is **magnitude weighting**, not label flips — a
  binary target treats a −$50 loss and a −$0.10 loss as the same event.
- Ranking agreement: Spearman(rank `y_win`, rank `pnl_net_entry`) = **0.855** — mostly co-ordered,
  but the residual is exactly where the money is. Top decile by `pnl_net_entry` is 100% winners;
  the 20 rows that are `y_win=1` yet net-negative carry −$0.91.

**Decision-level n, win rate, mean/median net-entry PnL** (the numbers requested):

| scope | n | win rate | mean pnl_net_entry | median |
|---|---|---|---|---|
| all rows | 3,516 | 57.8% | **+0.08** | +0.11 |
| `y_win=1` ("good") | 2,034 | 100% | +6.97 | +3.70 |
| `y_win=0` | 1,482 | 0% | −9.36 | −9.32 |

---

## 3. The baseline arm — time-ordered holdout

**Split (Part A, decision-dataset):** first 70% by `opened_at` = train, last 30% = test.
No random fold, no statistic computed over a row's own past.

- **Split boundary date: 2026-08-21** (test starts there; test ends 2026-09-12).
- train **n=2,461** (2026-07-15 → 08-21); test **n=1,055**.
- **TEST base rate `realizedPnl>0` = 0.548; TEST base rate `pnl_net_entry>0` = 0.533** (train base 0.592 — drift).

Labels are named on every row. AUC via `sklearn.roc_auc_score`; Brier = mean((p−y)²). The
"[constant base rate]" row is the Brier of predicting the test base rate for every row.

### Arm table — label = `realizedPnl > 0` (`y_win`), TEST n=1,055

| arm | AUC | Brier |
|---|---|---|
| **price-only (entry_price)** | **0.7331** | **0.2079** |
| price-only (detected_price / mid) | 0.7311 | 0.2092 |
| copyScore alone | 0.4742 | 0.3090 |
| raw weighted composite (6 stored scores) | 0.5315 | 0.2727 |
| **price + wallet+exec (LR, 15 feats)** | 0.7190 | 0.2199 |
| [constant base rate] | 0.500 | 0.2477 |

### Arm table — label = `pnl_net_entry > 0` (`y_net_entry`), TEST n=1,055

| arm | AUC | Brier |
|---|---|---|
| **price-only (entry_price)** | **0.7285** | **0.2115** |
| copyScore alone | 0.4812 | 0.3143 |
| raw weighted composite | 0.5366 | 0.2775 |
| price + wallet+exec (LR) | 0.6924 | 0.2407 |
| [constant base rate] | 0.500 | 0.2489 |

**Read-outs.** Price is the only arm that beats the constant base-rate Brier (0.208 / 0.212 vs
0.248). The composite and copyScore are at/below chance (AUC 0.47–0.54) with Brier **worse** than
the constant. Adding wallet+exec features makes price **worse** (0.719 vs 0.733; on the net label
0.692). Within price quintiles (test, label `realizedPnl>0`) the composite AUC is
**0.414 / 0.521 / 0.484 / 0.561 / 0.572** — i.e. 0.41–0.57, no information (card said 0.42–0.52).

### Part B — the card's own population (finished book, label `realizedPnl>0`)
Live DB, `PaperTrade(resolved|closed, isDemo=0, 0<entryPrice<1)` JOIN DecisionJournal JOIN ObservedTrade,
n=**11,307**, base rate 0.602, mean PnL +$1.339.

| method | price-only AUC | Brier | constant-Brier | base rate |
|---|---|---|---|---|
| market-grouped 5-fold OOF (card's method) | **0.7414** | **0.2032** | **0.2397** | 0.602 |
| time-ordered 70/30 (train 7,914 / test 3,393, boundary 2026-08-15) | 0.7349 | 0.2097 | 0.2500 | **0.497** |

Per-fold AUC spread (5-fold): 0.691 – 0.776, mean 0.746. ★ Note the time-ordered test base rate
collapses to **0.497** (near coin-flip) vs train 0.60 — a regime shift the pooled 5-fold hides.

---

## 4. Label basis (this repo's own standard)

Every AUC/Brier above names its label. The two label arms, **on the same rows**:

| population | n | realizedPnl-sign rate (`y_win`) | market-outcome rate (`didOutcomeWin`) | **disagreement** |
|---|---|---|---|---|
| decision-dataset rows with an `OutcomeReview.finalOutcome` | 2,755 / 3,516 | 54.5% | 46.8% | **500 = 18.1%** |
| live DB book with a finalOutcome | 5,869 | 0.539 | 0.543 | **594 = 10.1%** |

`didOutcomeWin` replicates `src/lib/resolution.ts:44` (normalised alnum compare of the traded token
label vs `OutcomeReview.finalOutcome`). **Arm table under the outcome label** (n=2,755; train=1,928,
test=827, test window 08-28→09-12, test base rate 0.548):

| arm | AUC | Brier |
|---|---|---|
| price-only (entry_price) | 0.7336 | 0.2061 |
| copyScore alone | 0.4470 | 0.3124 |
| raw weighted composite | 0.4937 | 0.2735 |
| price + wallet+exec (LR) | 0.7206 | 0.2201 |
| [constant base rate] | 0.500 | 0.2477 |

**Why this matters:** 18.1% of the decision rows disagree between "was this leg profitable" and
"did the token we bought actually win" — these are early exits (73.1% of finished legs) that book a
profit on a token that resolved against them, or the reverse. A `realizedPnl>0` target scores those
rows as a *success* even though the directional signal was wrong; the exit policy, not the signal,
earned the point. The market-outcome label (`didOutcomeWin`) is the correct target for a probability
arm — and it is derivable on only **78%** of decision rows (needs `OutcomeReview.finalOutcome`).

---

## 5. The spec — what `scripts/export-training-data.ts` must emit instead

**Current (13 cols):** `review_id,decision,confidence,wallet_score,trade_size,spread,liquidity,ttr_hours,was_good,ruleSetVersion,era,decision_at,simulated_pnl`
— target is a binary win flag; two columns are mislabeled scores; no price, no fee, no horizon.

**Proposed columns (one row per decision):**

```
# identity / provenance
review_id, decision_id, paper_trade_id, wallet, market_id, outcome, decision, status
# split + label-time
ruleSetVersion, era, decision_at, horizon_to_resolution_hours
# TARGET (required) — fee-aware, plus its sign for classifiers
pnl_net_entry, y_net_entry          # y_net_entry = 1[pnl_net_entry > 0]
# cost decomposition (so the target is auditable / the exit-contamination is visible)
pnl_gross, pnl_net_full, entry_price, exit_price, fee_rate, fee_entry_usd, fee_exit_usd
# features (decision-time, leakage-safe)
detected_price, wallet_entry_price, size_usd, observed_size_usd,
raw_spread, raw_liquidity, raw_volume,
wallet_quality_score, category_fit_score, entry_timing_score,
spread_score, liquidity_score, thesis_score, copy_score
# OPTIONAL second label — the repo's own "correct" target, where derivable (78% of rows)
y_outcome                            # didOutcomeWin(token, finalOutcome), blank if undeterminable
# legacy only, never a feature
legacy_was_good
```

Rules the spec encodes:
1. **Target = `pnl_net_entry`** (regression) and its sign `y_net_entry` (classification). `legacy_was_good`
   stays for continuity but is **not** the target and **not** a feature.
2. **Drop `confidence` as a feature** — it is 0 by construction on skips (verified: 200/200), so it
   encodes *decision type*, not signal.
3. **Fix the mislabeled columns:** `spread`/`liquidity` are stored **scores**; `ttr_hours` currently
   holds `entryTimingScore`. Emit the raw `raw_*` values under their own names and the scores under
   `*_score` names.
4. **Carry the horizon features** named in the gate: `horizon_to_resolution_hours` (time to the
   market's resolution), `entry_price`, `raw_spread`, `raw_liquidity`, `raw_volume`, `size_usd`.
5. **Emit the fee decomposition** (`fee_rate`, `fee_entry_usd`, `fee_exit_usd`, `exit_price`) so a
   consumer can rebuild `pnl_net_entry`; the fee model is keyword-inferred from the question slug.
6. **Re-point the source.** today the exporter reads `OutcomeReview` (a ~1-day / 10-wallet cohort).
   The labeled book that actually exists is `PaperTrade JOIN DecisionJournal JOIN ObservedTrade`
   (3,516 deduped rows → ~11,307 finished legs) — that is what `data/decision-dataset.csv` already
   carries, and what the horizon features require.

**What the data cannot support (flagged):**
- A market-outcome label for **all** rows — only 2,755/3,516 (78%) carry an `OutcomeReview.finalOutcome`.
- `pnl_net_entry` **without** the keyword-inferred fee rate — there is no per-market fee column; the
  export must ship `fee_entry_usd` alongside so the target is reproducible.
- Any **pre-2026-07-15 / post-2026-09-12** claim from this export — that is the file's span.

### Restated promotion gate (with the measured baseline substituted)

> **ML-1 promotes only if it beats the price-only baseline on a frozen TIME-ORDERED holdout** of the
> decision-dataset — **train ≤ 2026-08-21, test 2026-08-21 → 2026-09-12, n_test = 1,055**, label =
> **`pnl_net_entry > 0`** (test base rate 0.533). Baseline: **price-only AUC 0.729 / Brier 0.212**
> vs a constant-predictor Brier of 0.249. Promotion requires the candidate's **AUC ≥ 0.729 AND
> Brier ≤ 0.212** on that holdout, with a wallet/market-**clustered** 95% CI that excludes the
> baseline. Beating `copyScore` (AUC 0.48) proves nothing — it is already below chance.
> (If the realizedPnl-sign label is used instead: price-only AUC 0.733 / Brier 0.208. On the full
> finished book, market-grouped 5-fold: price-only AUC 0.741 / Brier 0.203.)

---

## 6. Verdict

**YES — the price-only baseline is reproducible at the card's numbers**, on the card's own
population and method (finished book, label `realizedPnl>0`, market-grouped CV): measured
**AUC 0.741 / Brier 0.203 / constant-Brier 0.240** vs the card's **0.747 / 0.199 / 0.236**.
On a strict time-ordered holdout — the basis the gate actually names — it is **AUC 0.735 / Brier 0.210**
(book) and **AUC 0.729 / Brier 0.212** (decision-dataset, net label), so the gate must be restated on
the time-ordered numbers, not the card's 5-fold ones.

**One card number is not what it says:** "base rate 0.236" is the Brier of a constant predictor
(b·(1−b) with b≈0.60), **not** a class prevalence (which is 0.602 on the book / 0.548 on the
decision test split). Compare it as a Brier, never as a rate.
