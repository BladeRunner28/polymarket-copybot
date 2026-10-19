# ML data prep — 2026-10-19

Everything below is measured on this machine, from `prisma/dev.db`, by
`scripts/build-ml-dataset.py` + `scripts/ml-prepare.py`. No estimates.

---

## 1. What the training data actually is

| artefact | rows | what it is |
|---|---|---|
| `data/ml/decisions.csv` / `.parquet` | **80,208** | one row per entry OPPORTUNITY: first decision per wallet × market × outcome × side, acted **and** declined |
| `data/ml/markets.csv` | **45,956** | per-market derived resolution + the instant it became decidable |
| `data/ml/report.json` | — | label mix, power, monthly coverage |
| `data/ml/prep-baseline.json` | — | comparator numbers, split sizes, missingness |

The old export (`training_data.csv`, 4,994 rows) is the **acted book only**. A model trained on
it inherits copybot's selection — it learns "of the trades copybot already chose, which were
profitable", which cannot drive a bot that picks its own entries. The decision book keeps the
**75,345 opportunities copybot never acted on**.

## 2. Labels — and where 0.5 % of them are wrong

The declined arm has no `OutcomeReview` row, so its label is derived from the book itself:

> last `MarketSnapshot` for the market: `yesPrice >= 0.90` → **YES**, `<= 0.10` → **NO**, else **NULL**

Validated against `OutcomeReview.finalOutcome` on the resolved acted population:

- **1,387 agree / 1,394 decidable = 99.50 %**
- 7 disagree = **0.50 % label noise**
- 574 abstentions (price still mid-range at the last snapshot)

Abstentions are **NULL, never 0**. A row with `y_side_win` null is excluded from training, not
treated as a loss — otherwise every still-open market would teach the model that copying loses.

Also derived: **`resolved_at`** = first snapshot crossing 0.90/0.10. This is the **purge key**. A
time split must purge on it, because a decision and its resolution are separated by the market's
whole life; splitting on decision time leaks outcomes of still-open positions across the boundary
(495 rows purged in the current build).

## 3. The finding that changes the bar

Price alone, on this population, is far stronger than the ML-1 gate bar assumed:

| label | train | test | price-only AUC | market-clustered 95 % CI | Brier | constant | skill vs constant |
|---|---|---|---|---|---|---|---|
| `y_side_win` | 16,471 (base 0.712) | 46,195 (base **0.826**) | **0.9224** | [0.9181, 0.9266] | 0.0834 | 0.1440 | **+0.4206** |
| `y_yes` | 16,471 (base 0.243) | 46,195 (base 0.169) | 0.9464 | [0.9431, 0.9501] | 0.0666 | 0.1404 | +0.5253 |

**The ML-1 bar (AUC ≥ 0.729, Brier ≤ 0.212) is measured on a different population and a different
label** — the acted book with `y_net_entry` at a 54.2 % base rate. Quoting 0.729 here would let a
model that scores 0.80 "pass" while being **12 points worse than price alone**. The bar for this
dataset is therefore re-derived:

> beat **AUC 0.9224** and **Brier 0.0834** with a market-clustered 95 % CI on the delta excluding 0.

Same trap on Brier: a constant predictor at the 0.826 base rate already scores 0.1440, so
"Brier ≤ 0.212" is satisfied by a model with **zero skill**. Brier skill vs constant is the only
honest form here.

## 4. Power — the number that limits everything

- **49,205 distinct markets** across 80,208 decisions → rows inside a market share one label, so
  effective n is markets, and every CI must cluster on `market_id`.
- **394 distinct wallets** in the whole book (221 train / 180 test). This is the real constraint:
  the model is learning from a few hundred trader behaviours, so wallet-clustered intervals would
  be very wide. Market clustering is the defensible unit; wallet correlation is a documented risk.
- Split at the frozen **2026-08-21** boundary: **train 16,472 / test 46,204**. The split is
  inverted relative to `n` — the July–August book is thin and markets resolve weeks later, so 74 %
  of labelled rows sit in the test window. A model trains on less than it is tested on.

## 5. Leakage controls actually enforced

- **`WalletProfile` is NOT joined.** It is a current-state table (`updatedAt` overwrites in place),
  so every column would be look-ahead. The decision's stored scores were computed live at decision
  time and are as-of by construction; those are kept.
- Every market feature is the **latest snapshot at or before** `decided_at`, never after —
  `snapshot_age_min` is exported so staleness is visible rather than hidden.
- The sentiment aggregate is computed **as-of** the decision (`asOf` door added to
  `aggregateSentimentForCategory`), never from the present.

## 6. Known gaps, stated rather than papered over

- **`size_usd` is 95.3 % missing**, `category_fine` / `category_class` 93.3 %,
  `raw_confidence` / `adjusted_copy_score` 92.6 % (recent rule sets only). Columns that sparse
  cannot carry a model; they are kept for completeness and should be dropped or bucketed.
- **Sentiment is not in the decision book yet, deliberately.** Signals start **2026-08-16**, so a
  sentiment feature would be ~0 % covered in train and partly covered in test — a feature absent
  where it is learned and present where it is judged. It becomes learnable in ~2–3 months. The
  acted book (`training_data.csv`) does carry it for the 140 rows that have it.
- **`research_category` covers 57.7 %** of the decision book (46,258 rows) vs 10.3 % of the acted
  book — the decision book is *more* political than the traded book, which is itself informative.

## 7. Reproduce

```
python3 scripts/build-ml-dataset.py --out data/ml     # ~58 s, read-only on the DB
.venv-ml/bin/python scripts/ml-prepare.py             # ~23 s, parquet + comparator + split
```
