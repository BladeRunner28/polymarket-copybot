# ML-1 target export — IMPLEMENTED (net-PnL target + price-only promotion gate)

**Card:** `ml1-target-net-pnl-and-price-baseline` · **Date:** 2026-10-11 · **Status:** applied, user-approved
("Don't un-gate STANDARD at 20:00, and I approve of the ML-1 export edit", 2026-10-11).
**Spec:** `drafts/ml1-target-and-price-baseline-20261011.md` §5 (written by the read-only measurement worker,
re-verified by the parent in `c53b601`). This file records the *edit* the spec asked for.

**Scope:** one model's training pipeline. No RuleSet, no gate, no sizing, no live path. The file the export
writes is regenerated in place and nothing in the repo reads it programmatically (checked — see §5).

---

## 1. What changed

| file | change |
|---|---|
| `src/lib/training-export.ts` | **new.** Pure helpers: `eraOf`, `feeDecomposition`, `netTargets`, `outcomeLabel`, `dedupeFirstPerPosition`, `round4`. Fee model is **imported** from `src/lib/scoring/price-edge.ts` (the same map `scripts/build-decision-dataset.py` mirrors) — never a third implementation. No DB, no I/O, so the target math is unit-testable. |
| `scripts/export-training-data.ts` | rewritten source + column set (below). Now re-reads `data/decision-dataset.manifest.json` and **prints a reconciliation of rows + all three PnL sums on every run**. |
| `tests/training-export.test.ts` | **new**, 12 tests pinning fee decomposition, the net target + its sign, the dedupe key, era boundaries, and `y_outcome`'s null discipline. |
| `training_data.csv` | regenerated: **7,674 rows × 13 cols → 4,841 rows × 40 cols**. |

**Source re-point (spec §5 rule 6).** Was `OutcomeReview` (a ~1-day / 10-wallet cohort whose `was_good` is
force-stamped on skips). Now `PaperTrade JOIN DecisionJournal JOIN ObservedTrade`, `status IN
('closed','resolved')`, `isDemo=0`, `entryPrice ∈ (0,1)`, deduped first-entry-per-position — the labeled book
that actually exists. Market features are the latest `MarketSnapshot` **collected at or before
`PaperTrade.openedAt`** (one indexed seek per row): no post-decision value can leak in.

**Target (spec §5 rules 1–5).**
```
pnl_net_entry = realizedPnl - entry-leg taker fee     ← regression target (magnitude-bearing)
y_net_entry   = 1[pnl_net_entry > 0]                  ← classification form of the same label
pnl_gross, pnl_net_full, fee_rate, fee_entry_usd, fee_exit_usd, exit_price   ← auditable decomposition
```
Also applied: `confidence` is **not emitted** (it is 0 by construction on skips → it encoded decision type,
not signal); the mislabeled columns are split — stored component **scores** keep `*_score` names and the raw
market values get `raw_*` names (old `ttr_hours` held `entryTimingScore`; old `spread`/`liquidity` held
scores); `legacy_was_good` is kept for continuity but is neither target nor feature; `y_outcome`
(`didOutcomeWin` against the venue's own winning label) ships as the second, where-determinable label.
Horizon features named in the gate: `horizon_to_resolution_hours`, `entry_price`, `raw_spread`,
`raw_liquidity`, `raw_volume`, `size_usd`.

---

## 2. Gate check (the card's own two conjuncts)

> "training_data.csv carries pnl_net_entry as the target (not the binary wasDecisionGood) plus the horizon
> features; ML-1's promotion gate is restated as 'beats price-only … on a time-ordered holdout'."

- **Target half — MET.** Header carries `pnl_net_entry` + `y_net_entry`; `legacy_was_good` is demoted to a
  continuity column. Verified on the written file, not on intent (below).
- **Gate-restatement half — DONE** on the roadmap: `phase-ml1`'s gate no longer says "beats copyScore"
  (copyScore measures AUC 0.474–0.481 — *below chance*, so that bar was free). The restated bar, with the
  corrected time-ordered numbers:
  > promote only if the candidate beats the **price-only baseline on a frozen TIME-ORDERED holdout** of the
  > decision dataset (train ≤ 2026-08-21, test n = 1,055, label `pnl_net_entry > 0`, test base rate 0.533):
  > **AUC ≥ 0.729 AND Brier ≤ 0.212** (price-only: 0.7285 / 0.2115; realizedPnl-sign label 0.7331 / 0.2079;
  > full finished book 0.7357 / 0.2088 vs constant-Brier 0.2500), with a market/wallet-**clustered** 95% CI
  > excluding the baseline.

---

## 3. Evidence — what the edit actually produces

Run: `npx tsx scripts/export-training-data.ts` (309 ms, re-run by the parent on the committed tree):

```
Exported 4841 rows to training_data.csv (raw 11307, dropped 6466 duplicate-accumulation rows)
  columns: 40 | target = pnl_net_entry (regression) + y_net_entry (classification)
  target distribution: y_net_entry=1 2641/4841 (54.6%) | mean pnl_net_entry $1.272
  sums: pnl_gross $7412.82 | pnl_net_entry $6157.0029 | pnl_net_full $5908.5582
  label arms: y_net_entry vs y_outcome — determinable on 3408/4841 rows (70.4%), disagree on 303 (8.9% of those)
  market features: 4765 rows carry a prior snapshot, 76 have none (horizon/raw_* blank)
  pre-kelly-v1-48: n=3389 y_net_entry=1 58.8% meanNetEntry=$0.338
  kelly-window-v49-57: n=832 y_net_entry=1 45.9% meanNetEntry=$1.506
  exposure-v58plus: n=620 y_net_entry=1 42.7% meanNetEntry=$6.060
Reconcile vs data/decision-dataset.manifest.json (generated 2026-09-13, span 2026-07-15..2026-09-12, raw 9735 -> 3516):
  rows: dataset 3516 vs export 3516 OK
  pnl_gross: dataset $1067.89 vs export $1067.89 OK
  pnl_net_entry: dataset $297.6 vs export $297.6193 OK
  pnl_net_full: dataset $168.56 vs export $168.5627 OK
  reconciliation: IDENTICAL on the state that dataset saw — today's file adds 1325 positions settled since 2026-09-13
```

**Reconciliation is the load-bearing check:** the TS fee model reproduces the frozen Python artifact on the
state that artifact saw — rows exact, all three sums to the cent. (The comparison is as-of
`terminal_at <= manifest.generated_at` **then** the same dedupe, not a date span: positions opened inside its
span but settled later are growth, not drift. Comparing on the span alone read as DRIFT on a first attempt.)

**Parent re-derivation from the written CSV** (not from the script's own print):

| check | result |
|---|---|
| sums recomputed from `training_data.csv` | gross $7,412.82 / net-entry $6,157.0029 / net-full $5,908.5582 — matches the print exactly |
| `y_net_entry=1` count | 2,641 / 4,841 (54.6%) — matches |
| era split recomputed | n=3,389 / 832 / 620, win% 58.8 / 45.9 / 42.7, meanNet $0.338 / $1.506 / $6.060 — matches |
| identity `gross − fee_entry = net_entry` | **4,841 / 4,841 rows** within $0.01 |
| identity `gross − fee_entry − fee_exit = net_full` | **4,841 / 4,841 rows** within $0.01 |
| `y_outcome` blank discipline | 1,433 blank (29.6%), 3,408 determinable (70.4%) — matches |
| decision mix | `paper_copy` 4,841; status `closed` 3,370 / `resolved` 1,471 |

**Tests:** `npx tsc --noEmit` clean · `npx vitest run` → **441 passed / 39 files** (12 new, 0 broken).

---

## 4. Findings the edit surfaced (report-only, no action taken)

1. **Label coverage falls 7,674 → 4,841 rows, and the drop is the *declined* arms.** The old `OutcomeReview`
   export carried `paper_copy 5,869 / watchlist 1,605 / skip 200`; the re-pointed source has no `PaperTrade`
   for a declined decision, so all 4,841 rows are `paper_copy`. This is what spec §5 rule 6 asked for, but it
   means `training_data.csv` no longer carries *would-have-copied* labels — the counterfactual side of the
   book. The 77k counterfactual labels from ML-1a are a separate artifact; a model trained on this file alone
   cannot see the declined population. **Carded** (`ml1-declined-arm-coverage`), not decided here.
2. **The era read inverts, so it must be re-derived, never carried over.** The old export's era note
   ("pre-kelly 60.2% good +$0.22 | kelly 44.9% good −$0.24 | exposure-v58 n=1") called the live era the worst
   cohort. On the new file the acted book reads pre-kelly 58.8% / +$0.338, kelly-window 45.9% / +$1.506,
   exposure-v58plus 42.7% / +$6.060 — win-rate ordering *lower* in the live eras while mean net-entry PnL is
   *higher*. Both are true statements about different populations and different targets (the old note used a
   binary `was_good` on a 1,855/782/1 row set). Any era claim quoted from the old numbers is stale.
3. **Exit contamination is now visible and quantified in-file.** `y_outcome` vs `y_net_entry` disagree on
   303 / 3,408 determinable rows (8.9%): early exits that book a profit on a token that resolved against us.
   A PnL-sign target scores those as wins; `y_outcome` is the label that does not, and it ships alongside so
   the choice is explicit rather than implicit.
4. **`fee_rate` is keyword-inferred** (there is no per-market fee column), so `fee_entry_usd` / `fee_exit_usd`
   ship alongside the target precisely so it stays reproducible if the map changes.

---

## 5. Why nothing downstream broke

`search_files 'training_data'` → the only *code* reference is the exporter writing it. No fit script, dashboard
page, cron job or skill in this repo reads `training_data.csv`; the live shadow scorer refits from the DB
(`data/shadow-score-model.json`), not from this CSV. So the 13→40 column change has no consumer to break.
The file itself is regenerated in place by `npm run export:training`, and the previous revision is preserved
at `~/.hermes/cache/scratch/training_data.bak-20261011.csv` for the before/after in §1.

## 6. Reproduce

```
npx tsx scripts/export-training-data.ts        # 309 ms; prints the reconciliation
npx vitest run tests/training-export.test.ts   # 12 tests
npx vitest run                                 # 441 tests / 39 files
```
