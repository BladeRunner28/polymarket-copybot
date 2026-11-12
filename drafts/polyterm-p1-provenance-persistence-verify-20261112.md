# Polyterm P1 (second half) — provenance persistence: VERIFIED, plus the queue defect that re-opened it

**Card:** `polyterm-p1-provenance-persistence` · Lane B · commit `61487e1` (work) + `17633b8` (this session's repair)
**Read taken:** 2026-11-12T19:2x–19:39Z · `prisma/dev.db` · population = `ObservedTrade`, level = one observed print, clock = `createdAt` (ingest, UTC)

## 1. Why this run happened at all

The approvals inbox surfaced the card as a **pending decision** on 2026-11-11 and the operator
approved it on 2026-11-12T19:32:43Z, which created kanban task `t_4bd56a95`. But the card's own note
already carried `DONE 2026-11-09 (Lane B instrument repair, commit 61487e1)` — the work had shipped
three days earlier. So this card asked for work that a **different** run had finished.

The right response was not to re-do it: it was to (a) **verify** the shipped claim independently,
and (b) find out why a closed card entered the queue as an open decision.

## 2. Verification — the persistence is real, and it is measuring

| Check | Result |
|---|---|
| `prisma/schema.prisma` | `provenanceSource`, `provenanceLagged`, `provenanceFlags` on `ObservedTrade` (nullable) |
| live DB columns | all three present (`PRAGMA table_info`) |
| commit `61487e1` | on `main`, contained in `origin/main` |
| write path | `scripts/monitor-trades.ts:147` (BUY) and `:228` (SELL sidecar) — and it is the **only** `observedTrade.create` in the repo |
| lifetime rows | 6,544,876 · stamped **274,925** (4.2%) · unstamped 6,269,951 = legacy NULL by design |
| epoch | first stamped row `2026-11-10T02:06:24.316Z`; last unstamped `2026-11-10T02:01:52.250Z` |
| **unstamped at/after epoch** | **0** |
| newest-500 window | **500/500 = 100.0%** readable stamps |
| newest row flags | `["lagged_data_api","activity_endpoint","short_window"]` |
| instrument verdict | `OK: every row at/after the epoch carries a readable stamp` (exit 0) |
| tests | `vitest run tests/provenance.test.ts tests/provenance-persistence.test.ts` → **16/16 in 2 files** |

The card's original complaint — "every stamp dies with the process, so the C-200 print-through work
is not auditable" — is **false as of 2026-11-09** and the guarantee is holding 2 days later on live
ingest. Nothing to rebuild.

**Scope limit, restated (it is the card's own words, not a new gap):** this stamps the **data-api read
rows**. The C-200 print-through join reads fills from the CLOB archive, so per-fill provenance on the
fill ledger is a *separate* card, not a shortfall of this one.

## 3. The defect that actually needed fixing

`scripts/approvals-intake.py::closure_evidence()` decides which cards leave the queue. It splits a
card note on `(?<=[.;])\s+|\n` — which **consumes the whitespace** — and then required a closure stamp
to be *preceded* by one of `[\s\-—–:|*]+`. Since no segment ever begins with whitespace, a note line
opening exactly on the stamp could never match. Only stamps behind a literal dash (`, then:\n--- APPLIED …`)
did.

This card's note opens its closure sentence exactly that way (`…\n\nDONE 2026-11-09 (…`), so the
filter returned `''`, the item stayed **pending**, and a decision slot was spent on a closed card.

**Fix:** separator class optional (`*` not `+`). Nothing else about the rule moved — a stamp must still
*open* a segment, `… IF` clauses are still rejected, mid-sentence "shipped" is still prose.

| Measurement | Before | After |
|---|---|---|
| cards carrying a pending tag | 41 | 41 |
| closed by the filter | 18 | **19** |
| **cards that change classification** | — | **1 (`polyterm-p1` — the card above)** |
| `--self-test` | none existed | **PASS 6/6** (4 negative controls) |
| full intake run | — | `30 items · pending 0 · new 0 · refreshed 24 · excluded 17 · retired 0`, exit 0 |
| decided record `apr-polyterm-p1-provenance-persistence` | — | **preserved** (decided items are never excluded) |

Deliberately **not** added: `column == "Done"` as a closure signal. Of the four Done-column cards
still pending-tagged, `ml1-price-baseline-drift` is genuinely awaiting a decision (its BAR change was
never approved) — column would have hidden a live question. Stamps only, which is the safe direction.

**Revert:** `git revert 17633b8` (queue hygiene only; no rule, size, threshold or gate touched).

## 4. Residual, for the operator (not auto-closed)

Four cards sit in column **Done** with a pending tag and no closure stamp:
`polyterm-p3-hygiene-preregistered-read`, `polyterm-p5-holders-concentration`,
`standard-exit-rule-replay`, `ml1-price-baseline-drift`. Three look like de-tagging hygiene for
whoever closed them; `ml1-price-baseline-drift` is a real open decision and must stay in the queue.

## 5. Judgment calls (overridable)

- **Did not re-run the provenance work.** Its claim verified against the live DB, so re-shipping it
  would have been churn. Revert: nothing to revert.
- **Fixed the filter instead of de-tagging the card.** De-tagging fixes today's card; the filter bug
  would re-open the next card whose note opens on a stamp. Revert: `git revert 17633b8`.
- **Committed the script only, not `data/approvals.json`.** The store churns on every intake run;
  the 22:30 backup carries it. Revert: n/a.
