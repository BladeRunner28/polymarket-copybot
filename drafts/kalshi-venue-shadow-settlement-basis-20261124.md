# Kalshi venue-shadow: the settlement basis now exists, and 12 of 37 legs were mislabelled

**Card** `kalshi-venue-shadow-pnl-exit-sign-basis` · Lane B instrument repair · 2026-11-24

## Key insight

The ledger's `won` field was `realizedPnl > 0` — the **exit sign of our own paper leg** — and the
Kalshi book was priced from it. A column named `won` plus a summary field named `delta` reads as a
cross-venue *settlement* comparison; it is an *exit* comparison. The fix is not to restate history:
it is to record what the venue says in its own fields and keep the exit-sign figures where they were.

## What is measured

| item | value |
| --- | --- |
| population | `detVerdict==EQUIV` legs with a settled paper leg: **37 legs / 36 markets** |
| clock | `openedAt` 2026-11-16 → 2026-11-23; read 2026-11-24T15:1xZ |
| level | one ledger leg |
| knowable | **37 / 37** (venue result + adjudicated side) |
| agree with exit sign | 25 |
| **disagree** | **12** — all booked a *loss* that settled a *win*; 0 the other way |

Exit-sign wins 5, venue wins 17: the exit sign does not merely flip a direction, it hides two thirds
of the wins.

**Cross-check.** `scripts/kalshi-pair-settlement-read.py` prints the same 12 independently
("ledger `won` (EXIT sign) vs PM settlement, relabelled: 12 of 41"). Two code paths, one number.

## What is deliberately not measured

The venue-basis **PnL**. `detEntry` exists on 5 of 41 pairs and only 1 of those is settled, so
`matchedPriced` is `n=1, exit -$10.13 vs venue -$10.13, delta $0.00`. The leg-level reading is the
deliverable; a PnL restatement would be one leg dressed as a book.

## A defect found in my own first version

My first pass derived "did our side win" from the ledger's stored `detOurSideIsYes`. It produced
**3 flips in the opposite direction**. The pair audit measures that flag against our outcome's side:
**13 of 41 pairs disagree**. So the ledger now *consumes* the audit's adjudication and never
re-derives it — the three phantom flips disappeared and the count landed exactly on 12.

That flag also picks `detEntry` in the resolver. If it is the wrong one, the deterministic book's
entry price — and its `detPnl` — are priced on the **other side** of the contract. Carded as
`det-our-side-flag-defect`; it is the next measurement, not a guess to build on.

## Verification

- `npx tsc --noEmit` clean
- `npx vitest run` **1213 / 1213 in 113 files** (was 1196/112) — 17 new tests in
  `tests/kalshi-venue-settlement.test.ts`; `src/lib/kalshi-venue-settlement.ts` holds the arithmetic
- ledger reread: `settlementBasis.known=37`, `disagree=12`, `storedSideFlagDisagreements=13`

**Rollback:** `git revert` the commit — the exit-sign columns were never touched.
