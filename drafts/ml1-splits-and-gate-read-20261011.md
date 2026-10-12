# ML doctrine implemented + the ML-1 gate read, executable

**Cards:** `ml-doctrine-time-and-era-splits` (Scheduled → In Progress) and
`ml1-target-net-pnl-and-price-baseline` (Done — this is the "gate half 2" follow-through).
**Date:** 2026-10-11 · **Mode:** code + docs + one read-only measurement. No RuleSet, no threshold,
no sizing, no published lane number changed.

---

## Part A — the shared split utility (what was actually missing)

The card's gap was **not** bad practice: no fit script in `scripts/` was using random-row folds —
`fit-price-edge.py` carries `folds_wallet` (crc32-wallet-blocked) and `folds_time` (expanding
walk-forward by month), and `shadow-expectancy-model.py` does a purged expanding-window walk-forward.
What was missing is that each design lived as prose in its own header, so nothing could CHECK it and
nothing forced a report to name its split.

**Shipped**

| piece | what it is |
|---|---|
| `src/lib/splits.ts` | canonical helper: `timeOrderedHoldout` (pinned boundary, purge, era provenance), `walkForward`, `blockedFolds`, `eraGroups`, `crc32`/`assignBlockedFold`, `formatProvenance` |
| `scripts/lib/splits.py` | Python mirror — stdlib only (these scripts run under py3.9 **and** system python3), same rules |
| `tests/splits.test.ts` (15) | time-not-index cutting, purge on `labelReadyAt`, era provenance, reproducibility, tie handling, k≥2 guard |
| `scripts/check-split-doctrine.py` | **machine enforcement**: fails on `KFold`/`StratifiedKFold`/`ShuffleSplit`/`train_test_split`/`cross_val_score`/`cross_validate` anywhere in `scripts/`, and fails if the Python fold pin disagrees with the TS `crc32` |
| `scripts/fit-price-edge.py` | first fold owner rewired onto the helper |

**Three rules the helper enforces, and why each is load-bearing here**

1. **Time order, never index.** Every cut is by timestamp. `frac` exists but a gate that names a
   boundary must pass `boundary` — a fraction-derived cut silently moves as the book grows, and a bar
   measured on a moving holdout is not a bar.
2. **Purge.** A train row whose label became knowable inside the test window is dropped and counted.
   On the bar population that is **148 rows** — legs opened before the boundary that settled after it.
   Training on those is training on the future.
3. **Era provenance.** Every split reports per-era train/test counts and which eras sit on both sides.
   The label set spans v1..v6x and the features are policy outputs, so the era mix is part of the
   result, not metadata.

**Cross-language agreement is pinned, not assumed.** `assignBlockedFold` is `zlib.crc32(key) % k`
(the TS module implements IEEE CRC-32 with a table). The same four values are asserted in
`tests/splits.test.ts` and re-checked by the doctrine script — e.g.
`0x85f031d069de3000 → fold 4`, `0xe0e637b08c971c2f → fold 3`. A helper that silently renumbered folds
would make every cross-language read unreproducible.

**The rewiring did not move a number.** `fit-price-edge.py` emits a published spec, so the re-run was
diffed against the pre-change copy (`~/.hermes/cache/scratch/ml1/`):

```
score-spec-v1.json      : only "created_at" differs (+ one object's key order)
score-spec-v1-eval.json : only "generated_at" differs
```

Both published files were then **restored** so the timestamp churn does not land in them; the diff is
the evidence, not a commit. `git status` on them is clean.

**Still on the card (its 7-day verify):** 7 fold owners remain unmigrated — `fit-fill-model.py`,
`shadow-expectancy-model.py`, `wallet-selection-test.py`, `wallet-feature-priors.py`,
`rag-vs-price-baseline.py`, `skip-edge-probe.py`, `label-basis-audit.py`. The checker names them on every
run (warnings, not failures) so the gap cannot go quiet.

---

## Part B — the ML-1 gate read, now executable

`npx tsx scripts/ml1-gate-read.ts` — nothing is trained and nothing is promoted; it reads the
comparators and calibrates itself. Bootstrap 2,000 iters, seed 20261011, clustered by `market_id`.

### 1. Calibration: it reproduces the recorded bar

| read | harness | recorded | |
|---|---|---|---|
| decision-dataset, label `pnl_net_entry>0` | **AUC 0.7292 / Brier 0.2110** | 0.7285 / 0.2115 | ✓ to <0.001 |
| cross-check label `y_win` (`realizedPnl>0`) | **0.7339 / 0.2075** | 0.7331 / 0.2079 | ✓ to <0.001 |
| test n | 1,060 | 1,055 | 0.5% — boundary/tie convention + the purge |

A harness that cannot reproduce the bar it exists to enforce is not evidence, so this is the first row
of the read, not a footnote.

### 2. Nothing we store beats price on the frozen holdout

Decision-dataset (the bar's own population), ΔAUC vs price-only with a paired market-clustered 95% CI:

| arm | AUC | ΔAUC vs price | CI | P(Δ>0) |
|---|---|---|---|---|
| **entry_price (the bar)** | 0.7292 | — | — | — |
| detected_price | 0.7264 | −0.0028 | [−0.0070, +0.0009] | 0.070 |
| entry_timing_score | 0.5574 | −0.1718 | [−0.2187, −0.1244] | 0.000 |
| wallet_quality_score | 0.5137 | −0.2155 | [−0.2634, −0.1672] | 0.000 |
| copy_score | 0.4827 | −0.2465 | [−0.2974, −0.1935] | 0.000 |
| thesis_score | 0.4008 | −0.3285 | [−0.3877, −0.2671] | 0.000 |

Every stored score's CI sits **entirely below zero**: price-only significantly dominates them, and
`thesis_score` and `copy_score` are below chance outright. This is the same verdict the U2 audit reached
by AUC alone, now with the difference interval attached.

### 3. FINDING — the bar's absolute numbers are population-specific

| population | test n | base rate | price-only AUC | price-only Brier | constant Brier |
|---|---|---|---|---|---|
| decision-dataset (the 2026-09-13 artifact) | 1,060 | 0.535 | **0.7292** | **0.2110** | 0.2488 |
| training_data.csv (re-pointed acted book) | 2,302 | 0.492 | **0.7096** | **0.2184** | 0.2499 |

On the re-pointed acted book, **the baseline itself fails the bar the old population set** (0.7096 <
0.729, 0.2184 > 0.212). The thresholds were measured on one artifact and are being applied to another.
The honest form of the gate is "**beats its own population's price-only baseline** on a frozen
time-ordered holdout, with a clustered CI excluding the baseline" — the absolute AUC/Brier belong to the
artifact they were measured on and must travel with it. Carded (`ml1-price-baseline-drift`), not changed:
this is a gate definition, so it is the operator's call.

### 4. FINDING — price's ranking power decays across eras

| era | test n (new file) | price-only AUC | | era | test n (old file) | price-only AUC |
|---|---|---|---|---|---|---|
| pre-kelly-v1-48 | 850 | 0.7582 | | pre-kelly-v1-48 | 754 | 0.7592 |
| kelly-window-v49-57 | 832 | 0.6727 | | kelly-window-v49-57 | 306 | 0.6265 |
| exposure-v58plus | 620 | 0.6542 | | | | |

Both artifacts agree on the direction: price ranks **best in the retired era and worst in the live one**
(≈0.758 → 0.65-0.67). A model fitted mostly on pre-kelly rows faces a regime where the comparator it
must beat is already weaker — so "beats price" is a different amount of work in each era, and a pooled
number hides that. This is the concrete reason the per-era read belongs in every gate report.

### 5. Money arm — selection is where the claims die

Top tercile by score vs copy-all, mean `pnl_net_entry` per leg, paired clustered CI (new file, test window):

| selector | $/leg vs copy-all | CI |
|---|---|---|
| entry_price (top tercile = the favourites) | **−2.39** | [−4.96, −0.20] |
| thesis_score | −3.34 | [−5.93, −1.16] |
| entry_timing_score | +1.79 | [−2.50, +6.20] |
| copy_score | +1.63 | [−2.58, +5.59] |

Buying the highest-priced legs **loses** money in this window with a CI excluding zero. Note the shape,
because it is the U2 lesson repeating: `copy_score` and `entry_timing_score` look positive — and both
intervals span zero, so neither is evidence. AUC is not money; a selector must clear the money CI.

---

## Reproduce

```
python3 scripts/check-split-doctrine.py                    # enforcement: exit 0 = clean
npx vitest run tests/splits.test.ts tests/metrics.test.ts  # 30 tests
npx tsx scripts/ml1-gate-read.ts --iters 2000              # the read -> data/ml1-gate-read.json
./venv-calib/bin/python scripts/fit-price-edge.py          # rewired fold owner (spec unchanged)
```
