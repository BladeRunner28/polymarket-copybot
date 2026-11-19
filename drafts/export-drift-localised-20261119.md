# Export drift, localised — 2026-11-19

**Card:** `export-reconciliation-localisable` · Lane B instrument repair · nothing applied to rules,
sizing, strategy or the training target.

## The question the card left open

The ML export reconciles its own output against the frozen Python artifact
(`data/decision-dataset.manifest.json`, generated 2026-09-13) and prints `DRIFTED` when the sums
disagree. The card's conclusion was that this is unfixable: *"the manifest stores SUMS ONLY … post-hoc
localisation is impossible: the pre-change currentPrice is not stored anywhere."*

## Why that is wrong

The frozen artifact is not only a manifest — it is a **3,516-row CSV** with `fee_rate`,
`fee_entry_usd`, `fee_exit_usd`, `pnl_gross`, `pnl_net_entry`, `pnl_net_full` **per `trade_id`**.
And since `fee_exit = shares · rate · p · (1-p)`, the exit fee inverts: `p(1-p)` is recoverable, so
the mark the artifact was priced against is recoverable too (two roots, both printed).

## What was measured

- **Basis:** population = the 3,516 positions of `data/decision-dataset.csv` (artifact generated
  2026-09-13); level = one `PaperTrade`; re-priced from the live DB through the export's own
  `feeDecomposition`; read 2026-11-19T02:06Z.
- **Coverage:** 3,512 joined, 4 truth-bearing excluded (venue fee rate — they disagree with a
  proxy-priced baseline by construction), 0 missing, 0 unparsed lines.
- **Moved:** 47 of 3,512 positions. Σ Δgross **+$10.1400**, Σ Δnet_entry +$10.4603,
  Σ Δnet_full +$10.9819.
- **COMPLETE:** per-position Σ Δgross (+$10.14) equals the manifest-level Δ (+$10.14) exactly;
  net_full closes to $0.002 (2-dp rounding in the manifest).
- **Cause, row for row:** all 47 trade ids appear in
  `data/repair-manifests/ledger-price-side-applied-20261111T123934.jsonl` (the 2026-11-11 ledger
  price-side repair, 233 rows), and each row's measured Δgross equals its repair-manifest delta to
  within $0.005. **The drift is that repair, not the fee math.**
- **Concentration:** largest single position 3.5% of Σ|Δnet_full| — this is 47 real restatements,
  not one whale.
- **Recovered frozen marks:** 18 of the 47 invert to a non-terminal mark (0.46|0.54, 0.275|0.725,
  0.4247|0.5753 …); the other 29 sit on the 0.0005|0.9995 terminal fringe.

## Two card claims corrected

1. *"Localisation is impossible"* — false, as above. The manifest's shape did **not** need to change
   and the frozen file was never written.
2. *"roughly $0.043 sits in the exit fee of early-closed positions"* — barely. Exactly **one** of the
   47 rows moved with gross unchanged, and that one (`cms8cc8js000au6h1n7069hmp`, Marlins vs Mets)
   moved on **both** fee legs equally (−$0.0392 each): entry 0.405 → 0.425 and exit 0.595 → 0.575,
   i.e. the complement-to-price-side repair, not an exit-only reprice.

## What shipped (Lane B)

- `src/lib/decision-dataset-drift.ts` — pure parser, fee→mark inversion, per-position delta and
  concentration summary.
- `scripts/decision-dataset-drift-localise.ts` (`npm run export:drift-localise`) — the standalone
  read, with `--json data/decision-dataset-drift.json`.
- `scripts/export-training-data.ts` — one added line on every run: `drift localisation: 47/3512
  positions moved — Σ Δgross $10.1400 …`. The `DRIFTED` sentence no longer blames "the fee/target
  math"; it states that the data moved and names the instrument.
- `tests/decision-dataset-drift.test.ts` — 11 arms (round-trip through the fee parabola, a row that
  must NOT be called moved, gross-vs-fee separation, truth exclusion, missing-id, rate-basis change).

## Not changed

No re-baselining (that would erase the evidence), no manifest shape change, no edit to
`data/decision-dataset.csv`, no rule/size/threshold. `training_data.csv` is computed from live data,
so the training target was never affected — only the check's *message* was misleading.

## How to re-run / roll back

```
npm run export:drift-localise                 # names the positions behind any future drift
npm run export:training                       # the reconcile block now prints the localisation line
```
Rollback: delete the two files, the test, the npm alias; revert the one log line in the exporter.
Nothing reads them.
