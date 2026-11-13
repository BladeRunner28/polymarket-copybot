# PnlSnapshot mark restatement — apply-ready proposal (Lane A)

**Card:** `pnlsnapshot-mark-restatement` · **Lane:** A (published figure — waits for the operator)
**Approval:** `apr-pnlsnapshot-mark-restatement` (approved 2026-11-12T16:45:08Z, link, no expiry)
**Status:** **NOT APPLIED.** Nothing in `prisma/dev.db` was written for this document: the DB was opened
`mode=ro` throughout, no `apply-vNN.ts` was run, nothing was merged. Deliverables are two read-only scripts
plus this write-up.
**Re-measured:** 2026-11-12 (all figures below are today's run; the 2026-11-11 run is kept beside them).
**Companion:** `drafts/pnlsnapshot-mark-restatement-20261111.md` (full mechanism/derivation — unchanged and
still correct; this document supersedes its numbers only where marked).
**Instrument:** `scripts/pnlsnapshot-mark-restatement-measure.py` (read-only, `mode=ro`)
**Write path:** `scripts/restate-pnl-marks.py` (**dry-run by default**, `--apply` + ledger dump + `--rollback`)

---

## 1. Verdict in one line

The class is real, it re-measures **identical to the cent** a day later, and the recommended write is
**2,070 marks restated for +$391.02 net, moving 712 of 5,232 rollup cells** (largest single cell ±$365.46).
The card's `$5,690` "inflated marks" does **not** exist — the marks carry the **sibling token's return,
sign-flipped** (corr(stored, restated) = **−0.710**), which is why the aggregate looked quiet and the
individual rows were off by up to a full position. The fix is the same either way; what it is *worth*
changes: this is a **correctness** write on a published chart series, not a PnL recovery.

## 2. Reproducibility — 2026-11-11 vs 2026-11-12

| figure | 2026-11-11 | **2026-11-12** |
|---|---|---|
| marks on the 233 repaired legs | 2,680 | **2,680** |
| non-appended marks (2,448 pre-fix + 36 post-fix) | 2,484 | **2,484** |
| arm **B** rows / net Δ | 2,070 / +$391.02 | **2,070 / +$391.02** |
| arm **A** rows / net Δ | 1,250 / +$818.09 | **1,250 / +$818.09** |
| arm **C** rows / net Δ | 2,481 / +$450.40 | **2,481 / +$450.40** |
| rollup cells moved (B) | 712 / 5,190 | **712 / 5,232** |
| largest moved cell | −$365.46 | **−$365.46** |
| rule-vs-venue agreement | 1,341 / 1,374 = 97.6 % | **1,341 / 1,374 = 97.6 %** |
| pre-fix corr(stored, restated) | −0.710 | **−0.710** |
| seam closes (last mark vs appended final) | 195 / 195 | **195 / 195** |

The plan is byte-stable because its **population is frozen**: re-checked today, **0** `PnlSnapshot` rows on
these legs were written after the repair (the 233 legs are **144 closed + 89 resolved, 0 open**), so no new
mark can drift into the target set. The series total did grow (+$2,471.70, from unrelated live legs), and
the rollup is **in sync today** (`SUM(PnlHourlyRollup) − SUM(PnlSnapshot.pnl) = +0.0000`), so the before/after
below is clean.

## 3. What the card asked, answered (today's numbers)

**(a) Before or after the write fix?** 2,448 pre-fix marks (written before `fbf9073`, 2026-11-09T15:15:16Z),
36 written between the fix and the repair, 196 **repair-appended finals** (identified by `snapshotId` in the
applied ledger, not by timestamp — the repair backdates them). The appended finals sum **+$538.68**, which
reproduces the card's figure; they are final and are **not touched**. The card's "2,484 pre-fix" is the
2,448 + 36 — kept apart because they need different corrections.

**(b) Is the mark the sibling's price or already ours?** Tested against the venue's own token list
(`CLOB /markets/<conditionId>` → `tokens[].outcome`, keyless) and the nearest `MarketSnapshot` price.

| window | decidable pre-fix marks | closer to OWN | mean d_own | mean d_mirror |
|---|---|---|---|---|
| ≤ 30 min | 1,012 | **6.3 %** | 0.382 | **0.030** |
| ≤ 180 min | 1,374 | **6.9 %** | 0.465 | **0.056** |

Split by the leg's own token index — the finding that decides the arm:

| leg's own token | decidable pre-fix marks | closer to OWN |
|---|---|---|
| **index 1** (225 of 233 legs) | 1,312 | **2.5 %** |
| **index 0** (7 of 233 legs) | 62 | **100 %** |

The positional read `outcome === "NO" ? noPrice : yesPrice` returns the FIRST token, so it is wrong exactly
when the leg holds index 1 and was never wrong for index 0. Token order itself is validated: for the 97 legs
with a decisive final print, `tokens[0].winner` agrees with the stored `yesPrice` **97 / 0**. Rule vs venue:
**1,341 / 1,374 = 97.6 %** of measurable rows.

**(c) What should the mark have been where the own token had no print?** The question dissolves: the own
price always exists, because the stored price *is* the sibling's and the pair is complementary at every
instant (`mean |(1 − mark) − own| = 0.030` at ≤30 min — lag + spread, not a missing print). **No value is
guessed.** How much of the write is venue-confirmed vs structural: of the 2,073 restatable marks, **1,265
have a venue print within 180 min**, **808 do not** — i.e. **61 % venue-confirmed, 39 % structural**, all of
the structural rows being the same single writer (`update-pnl.ts`'s one positional read) on legs whose token
index is known from the venue. That is the honest split between the two arms below.

**Mapping validation:** pre-fix corr(stored, restated) = **−0.710** (n=2,049; idx-1 subset −0.730, n=1,984);
post-fix corr **+0.744** (n=24 — same sign, only the entry was rebased); the seam test — |last mark − the
repair's independently-fetched appended final| — goes from **median $18.37 / mean $20.78** to **median $0.00
/ mean $1.11** and closes on **195 / 195** legs.

## 4. The three arms (all dry-run on today's DB; nothing written)

| arm | rule | rows | net Δ pnl | rollup cells moved | SUM(PnlSnapshot.pnl) |
|---|---|---|---|---|---|
| **A** `--only-measured` | only marks the venue can decide; the rest keep their value | 1,250 | **+$818.09** | 396 | 1,789,977.63 → 1,790,795.72 |
| **B** *(default)* | structural: pre-fix & idx 1 → `price' = 1 − price`; idx 0 and post-fix keep the price; every restatable mark rebased onto the repaired entry; appended finals and unfilled legs untouched | 2,070 | **+$391.02** | 712 | 1,789,977.63 → **1,790,368.65** |
| **C** `--zero-unfilled` | B plus the 411 marks on 25 never-filled legs set to 0 | 2,481 | +$450.40 | 759 | 1,789,977.63 → 1,790,428.03 |

Per bot under **B**: STANDARD 1,778 rows **+$760.10**; BANKROLL_200 292 rows **−$369.08**.
Days touched: **37** (2026-07-15 … 2026-11-09); largest day 2026-07-25 **+$831.74**; largest cells
−$365.46 (2026-08-02 03:00 STANDARD) and +$313.88 (2026-08-02 00:00 STANDARD).

**Recommendation: B.** A leaves 44 % of the really-marked rows in the sibling frame and fixes only the hours
`MarketSnapshot` happens to cover — the thin-coverage hours, which are exactly the hours that stay wrong.
C is a different question (whether a never-filled position should carry a mark at all) and is not folded in.

The net (+$391) is **not** the interesting number: the chart plots a per-hour **level** (sum of open
positions' marks at that hour — `hourlyPnlSeries()` → `src/app/performance/page.tsx`), so the honest summary
is "**712 levels move, 23 of them by more than $100**".

## 5. What moves, and what does not

| reader | affected? |
|---|---|
| `/`, `/performance`, `/analytics` hourly + daily charts | **yes** — 712 cells, 37 days |
| `PnlHourlyRollup` totals from `npm run rollup:pnl` | yes (same total after `--rebuild`) |
| `scripts/verify-dashboard-parity.ts`, `scripts/verify-chart-geometry.ts` | yes — re-run them after the write |
| `/paper-trades` last-snapshot column | **no** — every repaired leg's last snapshot is the appended final |
| live gates (drawdown, exposure, wallet-cap MTM, day-PnL open MTM) | **no** — they read `PaperTrade.unrealizedPnl` on `status='open'`; 0 of the 233 legs is open, and the script aborts on any open leg |
| `BotBankroll`, `PaperTrade.realizedPnl`, `DailyReport`, `RuleSet` | **no** — not written by this change |

## 6. Apply sequence (operator, 5 commands)

```bash
cd ~/polymarket-copybot
COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/restate-pnl-marks.py            # dry run — re-prints the 2,070 / +$391.02 diff
COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/restate-pnl-marks.py --apply    # 2,070 guarded UPDATEs + pre-image ledger
npm run rollup:pnl -- --rebuild                                               # 5,232 rows, ~30–60 s; the incremental path cannot see history
npx tsx scripts/verify-dashboard-parity.ts && npx tsx scripts/verify-chart-geometry.ts
```

Post-apply assertions (must all hold, else `--rollback`):

1. `SUM(PnlHourlyRollup.totalPnl) − SUM(PnlSnapshot.pnl)` within **$0.01** (today it is **$0.00**).
2. `SUM(PnlSnapshot.pnl)` = **1,790,368.65** ±$0.01 under arm B.
3. Per leg, |last mark − appended final| still closes on **195 / 195** legs (it closes today at median $0.00).
4. Rollup cells moved = **712**; total hour-rows **5,232**.

## 7. Rollback (exact, nothing recomputed)

`--apply` writes `data/repair-manifests/mark-restatement-applied-<ts>.jsonl` **before** the transaction
commits — one header + one full row per touched mark (`snapshotId`, `paperTradeId`, `pre`/`post`
price+pnl, delta), the same shape as `ledger-price-side-applied-*.jsonl`.

```bash
COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/restate-pnl-marks.py --rollback data/repair-manifests/mark-restatement-applied-<ts>.jsonl
COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/restate-pnl-marks.py --rollback data/repair-manifests/mark-restatement-applied-<ts>.jsonl --apply
npm run rollup:pnl -- --rebuild
```

Every UPDATE (and every restore) is guarded on the full pre-image (`WHERE id=? AND price=? AND pnl=?`), so a
row that moved since the write aborts the whole run rather than half-restoring.

## 8. Judgment calls, as overridable flags

- **`arm`** — default **B**. `arm A` = the card's literal gate (1,250 rows, +$818.09, 44 % left in the
  sibling frame); `arm C` = also zero the 411 marks on unfilled legs (+$450.40).
- **`unfilled-marks`** — default **leave alone** (25 legs never filled; 99 of their 411 marks carry a
  non-zero pnl written before fill-aware booking existed). `arm C` reverses this at −$59.38 relative to B.
- **`post-fix-marks`** — default **rebase the 36 marks on 3 legs** written between the code fix and the
  ledger repair (own price, sibling entry → −$449.08). Excluding them leaves three legs whose marks jump at
  the seam; that is available as a manual skip.
- **`chart-label`** — the `/performance` caption says "Cumulative PnL" over a per-hour **level**. That is a
  one-line Lane B text repair, deliberately **not** bundled here so the diff stays data-only.

## 9. Refutation — any one of these and the write stops

1. Rule-vs-venue agreement falls below **~85 %** on a re-measure (today **97.6 %**) — then the positional
   frame is not what produced these marks and `1 − price` is not the own price.
2. The seam survivor-check fails: after the write, the per-leg last mark no longer lands within tolerance of
   the accepted final on **≥ 90 %** of legs (today 195/195, median $0.00).
3. The pre-fix stored-vs-restated correlation is not negative (today **−0.710**) — a near-zero or positive
   value would mean these marks were never sibling-frame.
4. `SUM(rollup) ≠ SUM(PnlSnapshot.pnl)` beyond $0.01 after `rollup:pnl -- --rebuild`.
5. Any repaired leg is open at apply time — the script's own guard aborts (today: 0 open).

Already-failed premises, kept on the record: the card's "~+$5,690 of inflated marks" does **not** reproduce
under six definitions (stored sum +$403.32; |per-hour level| $6,635.90; |restated − stored| $11,174.98 — none
is $5,690). The only ~$5.3 k figure in the repair ledger is its row-level `rowDelta −$5,342.93`
(`realizedPnl` over 233 trades) — a different population from the marks.

## 10. Reproduce

```bash
cd ~/polymarket-copybot
COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/pnlsnapshot-mark-restatement-measure.py   # ~60 s warm (venue cache /tmp/mark-restatement-tokens.json)
COPYBOT_DB=$PWD/prisma/dev.db python3 scripts/restate-pnl-marks.py                      # dry run, all arms via flags
```

Both scripts are read-only without `--apply`; the measure script opens the DB `mode=ro`. Every figure in this
document comes from those two runs on 2026-11-12 (run log `/tmp/mark-measure-20261112.txt`).
