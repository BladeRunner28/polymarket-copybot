# The sub-0.001 marks were never a bad mid — they were the sibling token, and that operand is now fixed

Card `t_4d29ae55` (Lane A decision, approved 2026-11-12; the approved action had already shipped
under `price-side-inversion` on 2026-11-09, so this read is the **before/after the card owed**) ·
read 2026-11-12T19:40Z · instrument `scripts/nearcert-mark-guard-after.py` (read-only) →
`data/nearcert-mark-guard-after.json` · prior reads: `drafts/nearcert-mark-guard-20261029.md`,
`drafts/nearcert-tail-shadow-20261029.md`

## Answer to the card's question

**No tick-floor guard, no one-sided-book guard, and no re-fetch on the detection mid.** The
sub-0.001 marks the card found were not failed reads; they were the **sibling token's** price, and
the operand that produced them was fixed in production on 2026-11-09. Measured either side of
that cut, the class the card was filed on is gone:

| strict test (decisions stamped *after* the market's `closedTime`, where the venue's
`outcomePrices` are frozen 0/1 and the true price of the traded token is knowable) | pre-fix
30d 2026-09-29..10-29 | pre-fix week 11-02..11-09 | **post-fix 11-09 15:15Z..11-12 19:40Z** |
|---|---|---|
| second-listed token, mark = **our** token's settled price | 0 / 359 | 0 / 17 | **87 / 87** |
| second-listed token, mark = the **sibling's** price | 359 / 359 | 17 / 17 | **0 / 87** |
| first-listed token, mark correct | 371 / 371 | 2 / 2 | 16 / 16 |
| YES/NO market, mark correct | 172 / 172 | — | — |

Zero exceptions on either side of the cut. A failed read cannot be 100 % correlated with token
position; a positional label bug is exactly that, and it stops the moment the label is used.

## What shipped, and why this card's own options were not it

The recommended option on 2026-10-29 was "fix the operand, don't guard the mid". That landed as
commit **`fbf9073`** (2026-11-09 09:15 CDT, Lane A, approved): `priceForOutcome()` in
`src/lib/outcome-price.ts` reads the price of the token the leg actually holds from the venue's
`outcomeLabels`/`outcomePrices`, falling back to binary yes/no semantics and to *no claim* when the
payload carries no token list. All four call sites now use it:

| call site | what it prices |
|---|---|
| `scripts/monitor-trades.ts:175` | the detection price stored on `ObservedTrade` (the field the card is about) |
| `scripts/score-trades.ts:480` | the scoring operand — `currentPrice`, i.e. what every gate reads |
| `scripts/update-pnl.ts:224` | the P&L mark |
| `src/lib/exit-recovery.ts:178` | early-exit value |

`tests/outcome-price.test.ts` (10 tests, `npx vitest run` → 10 passed) pins the semantics,
including the "cannot price a named outcome without a token list → return undefined, caller keeps
its previous value" case that makes the change safe when a payload is thin.

## The card's three numbers, re-measured with the same instrument on the same window

The instrument reproduces the 2026-10-29 read exactly (1,443 cheap rows, 521 below the tick floor,
all exactly `0.000000`, 232 of them on second-listed tokens), so the comparison below is
apples-to-apples rather than a new cohort definition.

| figure | card (2026-10-29 read) | re-measured today |
|---|---|---|
| sub-0.05 near-certainty rows, trailing 30d | 1,443 | 1,443 |
| of those, mark below the 0.001 tick floor | 521 (36.1 %) | 521 (36.1 %) |
| … all exactly `0.000000` | 521 | 521 |
| … on a market that had already closed before the decision | 521 / 521 | 524 cheap rows on closed markets (521 of them below the tick) |
| marks that are the sibling token's settled price (strict test) | 359 / 359 second-listed | 359 / 359 second-listed |

## Before → after, same-length windows

| figure | pre-fix (3.18 d, 11-06 → 11-09 15:15Z) | post-fix (3.18 d, 11-09 15:15Z → 11-12 19:40Z) |
|---|---|---|
| decisions journaled | 7,279 | 5,588 |
| cheap (<0.05) near-certainty rows | 281 | 182 |
| marks below the 0.001 tick floor | 2 (0.7 %) | 10 (5.5 %) |
| … all exactly `0.000000` | 2 | 10 |
| … on a market already closed at decision time | 2 | 10 |
| decisions stamped on an already-closed market | 2 (0.03 %) | 103 (1.8 %) |
| post-close drift rows with a knowable, **inverted** sign | 15 / 15 (all second-listed) | 0 / 82 |
| second-listed cheap rows in the cohort (30d basis: 232 — the sibling-price tail) | 1 | 17 |

Two things move in opposite directions and both are correct:

1. **The sibling-price tail is gone.** The 232 second-listed cheap rows per 30 d were a ≥0.95
   market read upside-down. They now read their own price and land on the rich side of the same
   symmetric clause — still rejected ("price 0.97x near certainty"), for a true reason.
2. **The zero marks that remain are truthful.** Every one of the 10 post-fix zeros is a market that
   had already resolved, on a token that lost: the venue's own `outcomePrices` for those markets are
   frozen `["1","0"]` / `["0","1"]` and the token we hold is the `0` (e.g.
   `itf-wang3-ishii1-2026-11-11` — SAYAKA ISHII at `0`, four wallet fills at 0.36–0.45;
   `atp-ayeni-bolt-2026-11-11` — ALAFIA AYENI at `0`, wallet 0.49–0.51). A settled loser *is* worth
   0.000. The near-certainty clause rejecting it is right, and a tick-floor guard would now be
   relabelling a correct price as "no data" — the same objection the
   2026-10-29 read made, with none of the ambiguity left.

## What is still worth doing (not done here — needs its own Lane A yes)

One residual, unrelated to the tick floor: **the pipeline still scores trades observed after their
market resolved**, so the journal prints "price 0.000 near certainty — limited upside" about a
match that already ended. Measured cost:

* 103 / 5,588 decisions (1.8 %) stamped after `closedTime` in the last 3.18 d; 966 / 36,655 (2.6 %)
  in the trailing-30 d window ending 2026-10-29. Rate varies by day, not by fix.
* **0 admissions change** from skipping them: every decision in the window whose market reads
  `resolves in 0.0h` is already a `skip` (955 / 955 in the same window; 3,975 / 3,975 over the 30 d).
* 10 of the 182 post-fix cheap near-certainty rows would leave the cohort, and the reason string
  would become true ("market already closed at decision time, settled 0.000") instead of
  "limited upside".

Filed as its own card rather than shipped, because it changes the skip taxonomy (what the bot says
it decided, and on what evidence) and this card's approval was for the mid.

## One observation that changes how the cohort should be read

Since **2026-11-06 15:40Z** a single wallet — `0x17dd123a…` — accounts for **6,639 of the
decisions journaled** (≈1,100/day, all `outcome = NO`, mean mark 0.769, mean wallet entry 0.775,
58 `paper_copy`) and **4,073 of the near-certainty rows**, which is why that population went from
~50/day to ~650/day on 11-06, three days *before* this fix. Any near-certainty statistic computed
on a window that includes 11-06 onward is dominated by one wallet's expensive outcomes, not by the
mark defect. Flagged as its own measurement card; do not read the cohort's post-11-06 mix as
evidence about this gate.

## Instrument

`scripts/nearcert-mark-guard-after.py` — read-only (`mode=ro`) on `prisma/dev.db`; reuses
`data/nearcert-market-meta.json` and fetches only markets missing from it (4,887 fetched this read,
0 errors). Windows are anchored on the fix commit `fbf9073` (2026-11-09T15:15:16Z) and can be cut
anywhere (`--pre-days`, `--custom-from/--custom-to`). Writes `data/nearcert-mark-guard-after.json`.

```
python3 scripts/nearcert-mark-guard-after.py --pre-days 7 --custom-from 2026-09-29T21:36:00 \
        --custom-to 2026-10-29T21:36:00
```

Nothing in the trade path was touched by this read; no rule, gate, size, band or exit changed.
