# PnlSnapshot mark restatement — measured proposal (Lane A)

**Card:** `pnlsnapshot-mark-restatement` · **Lane:** A (published figure — waits for approval)
**Status:** NOT APPLIED. Nothing in `prisma/dev.db` was written; deliverables are read-only.
**Date:** 2026-11-11 · **Instrument:** `scripts/pnlsnapshot-mark-restatement-measure.py`
(write path, dry-run by default: `scripts/restate-pnl-marks.py`)

---

## 1. Verdict in one line

The class is real and it is measurable: **2,448 pre-fix marks on 232 legs carry the sibling
token's price**, and restating them (plus 36 post-fix marks whose entry was still the sibling's)
moves the published hourly series by **+$391.02 net across 712 of 5,190 rollup cells, max cell
±$365.46**, at a cost of one 5.5 s aggregate and one `deleteMany`+`createMany` of 5,190 rows.
**The card's `$5,690` figure does not reproduce — the marks are not "inflated", they are
sign-flipped** (measured correlation between the stored and the restated mark PnL is **−0.710**).
That distinction does not change the fix; it changes what the fix is worth.

---

## 2. What the card asked, and what was measured

Population: the 233 legs of `ledger-price-side-20261111.jsonl`, appended ledger
`ledger-price-side-applied-20261111T123934.jsonl` (applied 2026-11-11T18:39:34Z), and all
**2,680** `PnlSnapshot` rows attached to them.

| row class | count |
|---|---|
| marks written **before** the write fix (`update-pnl` commit `fbf9073`, 2026-11-09T15:15:16Z) | 2,448 |
| marks written **after** the fix, before the ledger repair | 36 |
| marks **appended by the repair** (196 `snapshotId`s in the applied ledger) | 196 |

The 196 appended finals are identified by id, not by timestamp — the repair backdates them to
`leg end + 1s`, so a timestamp test cannot separate them. Their sum is **+$538.68**, which
reproduces the card's figure exactly.

(The card's "2,484 pre-fix marks" is the row count **before the repair** = 2,448 written before the
code fix + 36 written between the fix and the repair. They need different corrections, so they are
kept apart everywhere below.)

### (a) Was the mark written before or after the write fix?

Cross-tabulating the phase against **which `entryPrice` reproduces the stored `pnl`** from the
stored `price` (`computePnl`, `src/lib/paper.ts:53`):

| phase | sibling entry fits | repaired entry fits | both | neither |
|---|---|---|---|---|
| pre-fix (2,448) | **2,010** | 0 | 133 | 305 |
| post-fix (36) | 23 | 5 | 1 | 7 |

Every "neither" row (312 in total) has `pnl = 0` — those are the unfilled legs, where
`bookedPnl()` forces zero. Nothing else is unexplained.

### (b) Is the stored mark price the sibling's price, or already ours?

This is the question the card flagged as unmeasured. Measured two ways.

**Against the venue.** The leg's own token index comes from the venue's own archived token list
(`CLOB /markets/<conditionId>` → `tokens[].outcome`, keyless); the price comes from the nearest
stored `MarketSnapshot` for that market (`yesPrice` = index 0, `noPrice` = index 1). Per mark:
`d_own = |mark − own_px|` vs `d_mirror = |(1 − mark) − own_px|`.

| window | decidable pre-fix marks | closer to OWN price | mean `d_own` | mean `d_mirror` |
|---|---|---|---|---|
| ≤ 30 min | 1,012 | **6.3 %** | 0.382 | **0.030** |
| ≤ 180 min | 1,374 | **6.9 %** | 0.465 | **0.056** |

**Split by token index — this is the finding the card did not have:**

| leg's own token | decidable pre-fix marks | closer to OWN price |
|---|---|---|
| **index 1** (225 of 233 legs) | 1,312 | **2.5 %** |
| **index 0** (7 of 233 legs) | 62 | **100 %** |

The positional read `outcome === "NO" ? noPrice : yesPrice` returns the FIRST token, so it is
wrong **exactly when the leg holds index 1** and was never wrong for an index-0 leg. The 6.9 %
"already ours" is almost entirely the 7 index-0 legs — i.e. the class is not 93 % clean, it is
**97.5 % sibling-frame inside the mispriced legs and 100 % own-frame inside the correct ones.**

**Token-order check** (the assumption the index test rests on): for the 97 legs whose market has
a decisive final print, `tokens[0].winner` agrees with the stored `yesPrice` **97 / 0** (136 not
decisive: no resolution print stored).

**Control arm (honest negative):** the same test on marks of legs the repair never touched is
**not usable** — `MarketSnapshot` is wallet-following and carries ~1–3 k rows/day against ~10 k
marks/day, so only 2 of 1,010 sampled control marks had a snapshot within 30 min. The claim
therefore rests on the index split plus the token-order check, not on that control.

### (c) What should the mark have been — including legs with no print that minute?

The question dissolves under the measurement: the own-token price **always exists**, because the
stored price *is* the sibling's price and the two tokens are complementary at every instant.
`mean |(1 − mark) − own_px|` = **0.030** at ≤30 min and **0.056** at 60–180 min — that residual is
the snapshot-vs-mark lag and the spread, not a missing print. So no mark needs a "no print"
fallback, and none is guessed.

Two independent checks that the mapping (not just the frame) is right:

| check | result |
|---|---|
| stored vs restated mark PnL, pre-fix (n=2,049) | **corr −0.710** (sign-flipped, as a sibling-frame carries the sibling's return) |
| same, post-fix (n=24) | corr **+0.744** (same sign; only the entry is rebased) |
| rule vs venue frame, measurable rows | **1,341 / 1,374 = 97.6 %** |
| seam: \|last mark − the repair's appended final\| | stored median **$18.37** (mean $20.78) → restated median **$0.00** (mean $1.11), closes on **195 / 195** legs |

The seam check is the strongest one available: the early-close exit used an independently
fetched own-token price, and `1 − mark` reproduces it to the cent on the median leg.

---

## 3. What the restatement moves

Three mutually exclusive arms, all measured by running `scripts/restate-pnl-marks.py` in dry-run
mode (nothing written):

| arm | rule | rows | net Δ pnl | rollup cells moved |
|---|---|---|---|---|
| **A** `--only-measured` | card's literal gate: only marks the venue can decide; the rest keep their value | 1,250 | **+$818.09** | 396 |
| **B** (default) | structural: pre-fix & index 1 → `price' = 1 − price`; index 0 and post-fix keep the price; **every** non-appended mark rebased onto the repaired entry; unfilled legs untouched | 2,070 | **+$391.02** | 712 |
| **C** `--zero-unfilled` | B plus the 411 marks on 25 unfilled legs set to price/pnl 0 | 2,481 | +$450.40 | 759 |

**Recommendation: B.** A leaves 44 % of the really-marked rows in the sibling frame and fixes the
series only where `MarketSnapshot` happens to cover it — the hours with thin coverage are exactly
the hours that stay wrong. B does not "guess": the writer is one code path doing one positional
read, 225 of 233 legs hold index 1, and the rule agrees with the venue on 97.6 % of the rows where
the venue can decide. Arm A remains available as the conservative fallback if the literal
pre-registration is preferred; Arm C is a separate question (whether a never-filled position
should carry a mark at all) and I would not fold it into this write.

**Shape of the move under B**

| statistic | value |
|---|---|
| `SUM(PnlSnapshot.pnl)` | 1,787,505.93 → **1,787,896.95** |
| `SUM(PnlHourlyRollup)` after `--rebuild` | same 1,787,896.95 (reconcile tolerance $0.01) |
| rollup cells moved (of 5,190) | **712 (13.7 %)** |
| cells moving > $50 / > $100 / > $250 | 43 / 23 / 5 |
| largest cell | **−$365.46** (2026-08-02 03:00 STANDARD) |
| per bot | STANDARD 1,778 rows **+$760.10**; BANKROLL_200 292 rows **−$369.08** |
| calendar days touched | 37 (2026-07-15 … 2026-11-09); largest day 2026-07-25 **+$831.74** |

The net (+$391) is *not* the interesting number — the chart plots a per-hour **level** (sum of open
positions' marks at that hour, see `hourlyPnlSeries()` → `src/app/performance/page.tsx:18`), so the
honest summary is "712 levels move, 23 of them by more than $100".

### The premise this refutes

The card says the series "keeps the ~+$5,690 of inflated marks". **Not reproducible.** Six
candidate definitions were computed on the 2,484 non-appended marks:

| definition | value |
|---|---|
| `SUM(stored pnl)` | **+$403.32** |
| `SUM(|stored pnl|)` | $7,414.04 |
| `SUM(|per-hour stored level|)` | $6,635.90 |
| `SUM(restated − stored)` | +$450.40 |
| `SUM(|restated − stored|)` | $11,174.98 |
| `SUM(|per-hour Δ|)` | $10,007.50 |

None is $5,690. The only ~$5.3 k figure in the repair's own ledger is the **row-level**
`rowDelta −$5,342.93` (`realizedPnl` across the 233 trades) — a different population from the
marks. So: the marks were never inflated; they carried **the sibling token's return**, which is
why the aggregate was near zero (−$25.29 stored on the pre-fix set) while individual rows were
off by up to a full position. The harm is sign, not size — and a level chart hides it.

---

## 4. What moves in production, and what does not

| reader | affected? |
|---|---|
| `/`, `/performance`, `/analytics` hourly charts (`hourlyPnlSeries`, `dailyPnlSeries`) | **yes** — 712 cells, 37 days |
| `PnlHourlyRollup` totals printed by `npm run rollup:pnl` | yes (same sum) |
| `scripts/verify-dashboard-parity.ts`, `scripts/verify-chart-geometry.ts` | yes — re-run them afterwards |
| `/paper-trades` last-snapshot column | **no** — the last snapshot of every repaired leg is the appended final |
| live gates (drawdown, exposure, wallet cap MTM, day-PnL open MTM) | **no** — they read `PaperTrade.unrealizedPnl` on `status='open'` rows; **0 of the 233 repaired legs is open** (144 closed, 89 resolved) and the script refuses to touch an open leg |
| `BotBankroll`, `PaperTrade.realizedPnl`, `DailyReport` | **no** — not written by this change |

---

## 5. Decision rule

**Apply** if *both* hold (the card's own pre-registration, evaluated):

1. **< 20 % of sampled marks are already in our own frame** → measured **6.9 %** (and the 6.9 % is
   the 7 index-0 legs, which the rule *keeps*). **PASS.**
2. **the restatement moves the curve by more than $100 in total** → measured **+$391.02** under the
   recommended arm. **PASS** (the card's threshold was set to catch a $0 result, not to test the net
   sign; the shape of the move is in §3).

Recommended arm: **B**. Order of operations, on approval:

```bash
COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/restate-pnl-marks.py                  # dry run: reprices, writes nothing
COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/restate-pnl-marks.py --apply          # 2,070 guarded UPDATEs + pre-image ledger
npm run rollup:pnl -- --rebuild                                                    # 5,190 rows; the incremental path cannot see history
npx tsx scripts/verify-dashboard-parity.ts && npx tsx scripts/verify-chart-geometry.ts
```

### What would REFUTE this proposal

Any one of these, and the write stops / the card closes unapplied:

1. **The 97.6 % rule-vs-venue agreement falls below ~85 %** on a re-measure with better snapshot
   coverage — i.e. the positional frame is not what produced these marks and `1 − price` is not the
   own-token price. Re-run `scripts/pnlsnapshot-mark-restatement-measure.py` after any change to
   `MarketSnapshot` coverage; the printed `rule agrees … %` line is the test.
2. **A survivor-check on the seam fails**: if, after the write, the per-leg last mark no longer
   lands within its pre-registered tolerance of the accepted final on ≥ 90 % of legs (measured now
   195/195 with median $0.00), the mapping is wrong and `--rollback` restores it.
3. **The stored-vs-restated correlation is not negative** on the pre-fix set (measured **−0.710**).
   A near-zero or positive correlation would mean these marks were never sibling-frame and the
   class definition is wrong.
4. **`SUM(rollup) ≠ SUM(PnlSnapshot.pnl)`** beyond the $0.01 reconcile tolerance after
   `rollup:pnl -- --rebuild` — the change would then have split the series from its source.
5. **Any repaired leg is found open at apply time** — the script aborts on its own guard, because a
   live mark must never move on a historical rewrite.

---

## 6. Rollback (exact, nothing recomputed)

`--apply` writes `data/repair-manifests/mark-restatement-applied-<ts>.jsonl` **before** the
transaction commits — one header plus one full row per touched mark (`paperTradeId`, `snapshotId`,
`pre`/`post` price+pnl, delta), the same shape as `ledger-price-side-applied-*.jsonl`.

```bash
COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/restate-pnl-marks.py --rollback data/repair-manifests/mark-restatement-applied-<ts>.jsonl          # dry run
COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/restate-pnl-marks.py --rollback data/repair-manifests/mark-restatement-applied-<ts>.jsonl --apply
npm run rollup:pnl -- --rebuild
```

Each restore is guarded on the post image (`WHERE id=? AND price=? AND pnl=?`), so a row that moved
since the write aborts the whole rollback rather than half-restoring.

---

## 7. Judgment calls, as overridable flags

- **`flag: arm`** — default **B** (structural, 2,070 rows, +$391.02). Say `arm A` for the card's
  literal gate (1,250 rows, +$818.09, 44 % of marks left contaminated) or `arm C` to also zero the
  411 marks on unfilled legs (+$450.40). One word; the dry run re-prints the diff either way.
- **`flag: unfilled-marks`** — default **leave alone**: 25 legs never filled, their marks are not
  positions, and 99 of the 411 carry a non-zero `pnl` written before fill-aware booking existed.
  `arm C` reverses this (Δ −$59.38 relative to B).
- **`flag: post-fix-marks`** — default **rebase the 36 marks on 3 legs** written between the code fix
  and the ledger repair (own price, sibling entry → Δ −$449.08). Excluding them leaves three legs
  whose marks jump at the seam; say the word and they are skipped.
- **`flag: chart-label`** — the `/performance` chart captions this series "Cumulative PnL" but plots
  a per-hour **level**; the restatement makes the levels right and does not make the label right.
  Renaming the caption is a one-line Lane B repair — not bundled here to keep the diff to data.

---

## 8. Reproduce

```bash
COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/pnlsnapshot-mark-restatement-measure.py
COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/restate-pnl-marks.py            # dry run, all three arms with flags
```

Both scripts are read-only without `--apply`; the measure script opens the DB `mode=ro` and is the
instrument every figure above comes from (run 2026-11-11; 73 s cold, 6 s warm with the CLOB token
cache at `/tmp/mark-restate-tokens-v3.json`).
