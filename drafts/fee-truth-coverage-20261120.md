# The fee rate is no longer a guess for 99.7% of the book — and the coverage push disabled two checks before it was caught

**Run:** 2026-11-20 09:00 backlog worker · **Card:** `paper-ledger-fee-fidelity` · Lane B (label/measurement; no rule, size, threshold or gate touched)

## What was finished

The card's own NEXT step: *"run the capture across the export's market set, then re-export and re-measure the delta. Needs no approval, it is the same instrument."* It had been open since 2026-10-26 with venue fee truth on **9 markets** out of ~4,400.

## Measured

Basis: population = `training_data.csv` rows (acted legs, isDemo=0), level = one export row / one venue market, clock = export generated 2026-11-20T15:2xZ; fee model = the venue's `shares × rate × p × (1-p)`.

| | before | after |
|---|---|---|
| rows on venue truth | 35 | **5,912 / 5,930 (99.7%)** |
| distinct markets with truth | 9 | **4,389 / 4,400 (99.75%)** |
| modelled entry fee | $1,740.65 | **$1,607.70 (−7.64%)** |
| `pnl_net_entry` sum | — | **+$134.43** |
| `y_net_entry` flips | — | 4 (0.07%) |

- 1,070 rows (18.0%) across 710 markets were re-priced.
- Venue rates found: 0.05 × 3,468 · 0.04 × 410 · **0.03 × 289** · **0 × 184** · 0.07 × 41. The keyword proxy **can never produce 0.03 or 0** — that is 473 markets on a rate the old model could not express.
- 714 of 4,392 captured markets (16.3%) disagree with the proxy. Both directions are real: 468 rows 0.05→0.03 and 183 rows 0.05→0 (proxy over-charged, edges rejected) against 87 rows 0.04→0.05 and 81 rows 0.07→0.04 (proxy under-charged, trades admitted with less edge than believed).
- 10 export markets have no truth: every one is a venue **404 `slug not found`** (deleted/renamed markets), not a capture failure.

## The defect this created, and the repair

Coverage alone broke two instruments, and neither said so:

1. **Export reconciliation** filtered comparison rows by fee label ("a truth-bearing row disagrees with a proxy-built manifest by construction"). With truth on 9 markets that excluded 35 rows; with truth on 4,389 it excluded 3,498 of 3,516 — the check ran on **18 positions** and printed DRIFTED because the excluded mass moved out from under it.
2. **Drift localisation** had the same filter, so it reported **"0 of 18 positions moved"** instead of 47 of 3,516.

Both now price every in-window position on the **frozen artifact's own model** (the keyword proxy) and print the label-basis figure beside it. Restored read: **3,516/3,516 joined, 47 moved, Σ Δgross +$10.1400** — reproducing the 2026-11-19 localisation exactly, with the fee-truth effect stated separately (+$31.91 net_entry on the frozen window).

Also recorded: `GET /markets?slug=<slug>` returns `[]` for every CLOSED market unless `&closed=true` is added (open-only is the endpoint default). The capture uses `/markets/slug/<slug>`, which serves both; a query-form capture finds nothing for the entire settled book.

## Verification

`npx tsc --noEmit` clean · `npx vitest run` **1,180/1,180 in 111 files** (was 1,165/110) · export re-run reproduces the manifest check · `npm run export:drift-localise` reproduces its own manifest-level Δ.

## Rollback

`git revert <sha>`; `data/fee-schedules.jsonl` is append-only and the export's `fee_rate_source` column labels every row, so reverting restores the proxy basis without touching stored data.

## What this is NOT

Not a rules change. `categoryFeeRate` has two consumers (`training-export.ts`, a comparison script); the live C-200 path never read it. No trade was admitted, sized or exited differently because of this run. The ML promotion bar and any model trained on this export DO see the corrected fee column — that is the point, and it moves `pnl_net_entry` by +$134 over 5,928 rows.
