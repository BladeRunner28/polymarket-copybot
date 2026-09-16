# Tuning #27 recs applied (2026-09-16): [CAP-SHADOW] · copy-label backfill

**Approver:** user ("I approve") in the tuning-review thread
**Source:** `logs/cron/tuning-review.md` Cycle #27, recs 1–2. RuleSet unchanged (v54).

---

## Rec 1 — `[CAP-SHADOW]` (exposure-caps axis, measurement) — APPLIED

The equity-linked gross-exposure cap now derives from the declared basis (#26 rec 2), and the
declared basis is **MTM** — so the book's own unrealized marks inflate its own ceiling. If those
marks revert, the same book sits far above the realized-only cap and the entry gate freezes with no
advance warning. That gap is now logged every run, next to `[DRAWDOWN-SHADOW]`:

```
[CAP-SHADOW] declared(mtm) cap $1367 vs realized-only cap $1000 (base $1000 + 50% above principal $1900)
             | NW mtm $2634 / realized-only $1695 | gap $367
```

Measurement only — no behaviour change. **Verified on the first post-apply scorer run.**
7-day check: the line appears on ≥95% of `score:trades` runs.

## Rec 2 — pre-fix childless copy rows relabelled (data quality) — APPLIED

`scripts/backfill-copy-labels.ts` (dry-run by default; `--apply` to write) relabels journal rows
written before the Rec 1 fix (2026-09-15 17:09Z): they were stamped `paper_copy` **before any gate
ran**, so the stored book claimed ~5× the copies it made (Sep 15 EOD printed "copy 381" against 108
real opens).

**4,998 rows relabelled, 0 failures — and the split mattered:**

| cause | rows | tag written to `risksJson` |
|---|---|---|
| fill **coalesced** into an existing open position (v52 sweep-dedupe) — same (wallet, market, outcome) within ±2h | **686** | `relabelled copy→skip — fill coalesced into an existing open position, no new leg` |
| **no leg ever opened** (gate-blocked or sidecar dispatch failed) | **4,312** | `relabelled copy→skip — no leg ever opened` |

Those 686 are not plain skips: the position exists, the decision just created no new leg. Tagging
them separately keeps the audit trail honest while still satisfying the verify line.

**Safety:** only rows older than 2h are touched (a sidecar webhook can lag its decision row), and
reversal is exact — every tagged row was `paper_copy` by construction (that was the selection
filter).

**Verified:** childless copy rows **4,998 → 0**. Post-backfill reconciliation (stored copy
decisions vs opened legs): Sep 12 62/65 · Sep 13 61/63 · Sep 14 69/74 · Sep 15 **103/108** ·
Sep 16 54/56. Stored copies should sit at or just below opens (one decision can open two legs), and
they now do — versus "copy 381 vs 108".

## Not proposed, correctly held

Cadence axis stays QUIET (6th consecutive miss — WAL/retention), and size/entry changes stay iced to
the Oct 8 window close. Both were left alone.

## Files

`scripts/score-trades.ts` (CAP-SHADOW line) · `scripts/backfill-copy-labels.ts` (new) ·
`data/roadmap.json` (2 cards). tsc clean.
