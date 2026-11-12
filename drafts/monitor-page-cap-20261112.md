# The 84 "print-present, swept, not stored" seat legs were never copyable

**Card** `t_4c9847c9` (raised by `t_52219682`) · **lane** B — read-only measurement, one contained
instrument repair · **instrument** `scripts/monitor-miss-attribution.py` ·
**artifact** `data/monitor-miss-attribution.json` · measured 2026-11-12 on `prisma/dev.db` +
`data/seat-evidence-activity.json` + the venue's own tape.

## Verdict

**Zero of the 84 legs is an instrument miss.** All 84 are legs whose own token never had a copyable
BUY print: the parent probe classified the *first activity row on the market's conditionId*, and on a
two-token market that row is usually the **other** token's fill — which this bot stored, at the very
same second, 84 times out of 84.

* 84/84: the matched print is on the **paired token** (`no`), the leg is the `yes` token. Stored rows
  for that condition: 403, of which **84 sit at the print's exact second**.
* 84/84: **no BUY print exists on the leg's own token** — 52 legs carry only a `REDEEM` on that token,
  16 carry nothing at all, 16 carry `SELL` prints only (13 sell-only, 3 redeem+sell), and those SELLs
  are kept in `data/wallet-sells.jsonl` (2,524 lines across those markets) by design — a SELL is not a
  copyable entry.
* The copyable side was read **completely**: 2,388 distinct venue BUY prints (conditionId, token,
  second) inside the same 61 h window, **2,388 stored, 0 absent**.
* The page cap is real but was not binding: the 24 h window needed **1.9 pages of 4 at the median,
  2.9 at its worst** in the card's window. It was exceeded on the 2026-11-04 burst (4,304 rows = 8.6
  pages) and still lost **nothing** (3,825 distinct BUY prints, all stored), because an 11-minute
  cadence only has to page back to the previous sweep.

So: the "84 instrument misses" figure is a **probe artefact**, the cap is a latent defect worth an
alarm (shipped here), and the copy lane's opportunity set on those markets was untouched.

## 1. The reproduction, and the arm the card was missing

`scripts/monitor-miss-attribution.py` reimplements the parent probe from the same caches and DB and
reproduces its numbers exactly before it says anything:

| basis | legs in window | no print | print, unwatched | print, missed |
|---|---|---|---|---|
| parent (first row on the **condition**, either token) | 3,218 | 961 | 2,173 | **84** |
| **token-matched** (first row on the **leg's own token**) | 3,218 | 1,039 | 2,179 | **0** |

`reproduces parent 3,218/961/2,173/84: True` — printed by the instrument on every run. The 78 legs
that move from "print present" to "no print" plus the 6 that move from "watched" to "unwatched" are
exactly the legs where the row the probe matched belongs to the other side of the pair.

The 84 also reproduces under the wallet-mark settlement basis (`--settlement mark`), so the finding
does not depend on the CLOB oracle arm of the parent's `key_state`.

## 2. Per-leg attribution — why each of the 84 is absent

Instrument verdict per leg (`data/monitor-miss-attribution.json → legs[].verdict`), with the cause
order the card asked for:

| cause | test | result |
|---|---|---|
| (a) pre-filter / dedupe mask | is a row already stored under this leg's identity? | 0/84 on the leg's token. The 403 stored rows on the same conditions are the **other** token — the dedupe key carries `outcome`, so they cannot mask |
| (b) activity-feed lag | a sweep covered the print but the feed hadn't published it | superseded: 0 prints are absent from the DB in the window (2,388/2,388) |
| (c) 429 / failure cycle | did the covering sweep log a fetch failure? | 0 sweeps inside the window logged any failure; luciebot appears in **0** of the 68 `Failures (…)` lines in 11,761 runs |
| (d) page-cap truncation | rows newer than the print at the first covering sweep vs 2,000 | max **33** (wallet-wide); the sweep had to page 1,148 rows at p50, 1,463 max (cap 2,000) |
| **token_absent** | is the matched print even on this leg's token? | **84/84 no** — it is a `no`-token BUY; the leg is the `yes` token |

Per-leg detail (all 84, ledger-style, every column straight from the artifact) is in the
[appendix](#appendix-all-84-legs). Summary of the own-token side:

| what the venue printed on the leg's own token | legs | reading |
|---|---|---|
| `REDEEM` only (redeemed at 0) | 52 | position was bookkeeping residue, never a fill of that token |
| nothing at all | 16 | no event on that token in the 61 h feed |
| `SELL` prints only | 16 | the exit side; kept in `data/wallet-sells.jsonl`, not in `ObservedTrade` by design |
| `TRADE/BUY` | **0** | — |

Cross-checks that do not depend on outcome *text* (the parent's cache dropped `token_id`):

* a fresh token-identity read of 3,000 venue TRADE rows back to `2026-11-10T07:23Z`: **0 BUY prints**
  on any of the 84 legs' `token_id`s, while the paired token of the same 84 conditions carries 423
  TRADE rows (median 3 per condition);
* the 16 legs with a SELL on their own token all have that print in the sell sidecar — captured, just
  not in the copy-entry table.

## 3. Price of the miss

The card asked for the settlement outcome of the 84 legs so the cost of the miss is known. Both halves
matter and they point the same way:

| quantity | value |
|---|---|
| copyable events forgone | **0** (no BUY print on those tokens, so nothing could have been crossed) |
| legs' own terminal mark | 25 resolved `1.0` / 59 resolved `0.0` (all settled) |
| wallet's own realised PnL on those 84 position rows | **+$130.22** (won legs +$203.50, lost legs −$73.27) |
| their cost basis | $123.74 total; median $0.82 a leg, max $10.69 — dust |
| markets that reached the copy lane anyway | 84/84 have a `DecisionJournal` row; 4 produced a `paper_copy` |

Read the two PnL rows together: the mark column is the **token's** settlement and the PnL column is the
**wallet's** realised result on that position, so a "lost" mark can still be a positive PnL (the wallet
sold the dust before it expired — legs 20, 31, 34, 36, 40, 49). Neither is a copy opportunity: a dust
position acquired outside a printed fill cannot be mirrored, which is why the forgone count is the only
number that prices the miss, and it is zero.

## 4. The page cap, priced

`src/lib/adapters/polymarket.ts → fetchRecentTrades` reads `4 × 500 = 2,000` rows per wallet per sweep,
newest-first, server-filtered to `type=TRADE` and `start=now−24h`.

| measurement | value |
|---|---|
| 24 h TRADE rows the sweep must page (333 sweeps inside the cache window) | p50 **966**, p95 1,370, max **1,463** = 2.9 pages of 4 |
| daily venue volume, last 8 days | 1,095 / 1,251 / 1,191 / 1,281 / 1,305 / 1,471 / 1,367 rows — and **4,304 on 2026-11-04** (8.6 pages) |
| prints absent from the DB on the burst day | **0** of 3,825 distinct BUY prints |
| prints absent from the DB across the card's window | **0** of 2,388 |
| sweep gaps in the card's window | p50 = p95 = max = **11.0 min** |

Why a saturated day still loses nothing: the cap bounds **rows read per sweep**, not the window. A
sweep only has to reach back to the previous sweep, and at 11 minutes that is ~33 rows even on the
burst day. The cap can only drop a print when `gap_hours × rows_per_hour > 2,000` — at the measured
rates (46–179 rows/h) that is a **11–43 hour monitor gap**. The whole-log worst gap is 20.9 h, so the
mechanism is reachable but needs an outage, not a busy day.

## 5. What was repaired here (Lane B)

Two contained instrument repairs, both committed with tests/verification, neither touching page size,
lookback or dedupe:

1. **The cap is no longer silent.** `fetchRecentTrades` now reports `cappedAtPageLimit` + `rowsFetched`
   on the existing `PrintFilterReport`, and `scripts/monitor-trades.ts` logs
   `[monitor] ALERT page cap: <wallet>… read 2000 activity rows (4 x 500) and the venue still had more
   — prints inside the 24 h window were NOT seen this cycle`. Before this, a capped read was
   indistinguishable from a quiet wallet: every number in the run stayed clean.
   Proof: `tests/adapter-page-cap.test.ts` (3 cases — a capped read reports, a short read is silent, a
   single short page is silent) plus the existing print-guard suite, `7 passed`.
   *Revert:* `git revert <commit>` — the fields are optional and additive, so no caller breaks.
2. **The seat-evidence probe now names its basis.** `scripts/seat-evidence-coverage.py` keeps the card's
   condition-basis fields untouched (so `3,218 / 961 / 2,173 / 84` still reproduces) and adds a
   token-matched twin: `c_no_copy_print_token`, `c_print_not_stored_token`,
   `c_print_unwatched_token`, `unobserved_first_event_token`, printed as two labelled lines on every
   run. Token-matched totals: **1,039 / 2,179 / 0**.
   *Revert:* the fields are additive — delete the `token-matched` block and the two `print()` lines.

Not repaired, deliberately: the `failures` path. Failures are logged with `logError`, the all-wallets-failed
case already throws, and 68 of 11,761 runs logged any failure (5 of them all-fail); luciebot has never
appeared in one. A single wallet failing every cycle would still not page — that needs cross-cycle state
and is named in the reopen conditions rather than shipped blind.

## 6. What was NOT priced into a change (Lane A)

Raising the page budget or widening the lookback changes what the monitor can see, so it stays a Lane A
call and is not taken here. Priced for the record:

* **4 → 8 pages** costs `+4` venue GETs per saturated wallet per sweep. Measured need is ≤2.9 pages on
  7 of the last 8 days, so today the change buys **nothing**; its value only materialises after a
  >11 h gap at burst density. With the new alarm, that situation now announces itself.
* **Lookback 24 h → 48 h** doubles every wallet's row budget for a case that has not occurred (0
  prints absent in either window measured). It also re-pays `fetchMarket` + `marketSnapshot` for
  duplicates the `seen` pre-filter exists to skip.
* Recommendation: **no change**; reopen only on the alarm.

## 7. Reopen conditions

1. `[monitor] ALERT page cap` appears in `logs/cron/copybot-monitor-score.log` — then price the page
   budget on the wallet that fired it.
2. Any seat's 24 h venue volume stays above 2,000 TRADE rows across consecutive days (the burst day
   here was one-off).
3. `c_print_not_stored_token` returns non-zero for any seat — that is a genuine instrument miss and
   the four causes above should be re-run for that seat.
4. A copy seat fails repeatedly while other wallets in the same cycle succeed (the failure path named
   in §5).

## Appendix: all 84 legs

Columns: `print on` = the token of the BUY print the parent probe matched; `own-token rows` = what the
venue printed on the leg's own token in the 61 h feed; `sweeps covering` = monitor runs whose 24 h
window contained the print; `leg mark` = the token's terminal price (WON = 1.0), which is a different
target from `wallet PnL $` (see §3).

| # | conditionId | leg token | print (UTC) | print on | own-token rows | 1st sweep lag | sweeps covering | paired-token rows stored | of which same second | leg mark | wallet PnL $ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `0xd2d54f6d…` | yes | 2026-11-10 09:01 | no | REDEEM+SELL | 8.9 min | 131 | 4 | 1 | lost | -1.4292 |
| 2 | `0xb1ad999b…` | yes | 2026-11-10 10:47 | no | no row | 2.3 min | 131 | 5 | 1 | lost | -0.0001 |
| 3 | `0xaa090e5a…` | yes | 2026-11-10 11:23 | no | SELL only | 9.9 min | 131 | 3 | 1 | lost | -1.3906 |
| 4 | `0x0a38c1c9…` | yes | 2026-11-10 11:51 | no | REDEEM only | 4.2 min | 131 | 2 | 1 | WON | +22.7272 |
| 5 | `0x0dcd0d69…` | yes | 2026-11-10 11:51 | no | REDEEM only | 4.2 min | 131 | 1 | 1 | lost | -4.2727 |
| 6 | `0x0262710b…` | yes | 2026-11-10 11:51 | no | REDEEM only | 4.2 min | 131 | 1 | 1 | lost | -4.2727 |
| 7 | `0xcba2aaf6…` | yes | 2026-11-10 11:52 | no | REDEEM only | 2.8 min | 131 | 3 | 1 | lost | -0.4520 |
| 8 | `0x62942bcc…` | yes | 2026-11-10 11:52 | no | REDEEM only | 2.8 min | 131 | 3 | 1 | lost | -0.4545 |
| 9 | `0xca4b2c43…` | yes | 2026-11-10 12:14 | no | REDEEM only | 3.4 min | 131 | 2 | 1 | WON | +4.5430 |
| 10 | `0x7a8cf35d…` | yes | 2026-11-10 12:55 | no | REDEEM only | 6.2 min | 131 | 1 | 1 | WON | +10.0000 |
| 11 | `0x5f4ee50a…` | yes | 2026-11-10 12:55 | no | REDEEM only | 6.2 min | 131 | 2 | 1 | lost | -0.1972 |
| 12 | `0x50522f0a…` | yes | 2026-11-10 13:20 | no | REDEEM only | 3.3 min | 131 | 2 | 1 | lost | -0.0154 |
| 13 | `0x836d258b…` | yes | 2026-11-10 14:20 | no | no row | 9.7 min | 131 | 6 | 1 | WON | +0.0019 |
| 14 | `0xe8737440…` | yes | 2026-11-10 14:54 | no | REDEEM only | 8.3 min | 131 | 1 | 1 | lost | -0.2736 |
| 15 | `0x2557dff0…` | yes | 2026-11-10 18:02 | no | REDEEM only | 7.2 min | 131 | 3 | 1 | lost | -0.1624 |
| 16 | `0x6f1ebe7c…` | yes | 2026-11-10 18:08 | no | REDEEM only | 1.1 min | 131 | 8 | 1 | lost | -4.2972 |
| 17 | `0x59c78566…` | yes | 2026-11-10 19:05 | no | no row | 10.2 min | 130 | 4 | 1 | WON | +2.8636 |
| 18 | `0x7427ef61…` | yes | 2026-11-10 19:05 | no | SELL only | 10.2 min | 130 | 2 | 1 | lost | -1.1588 |
| 19 | `0xd1140a10…` | yes | 2026-11-10 19:56 | no | no row | 3.2 min | 131 | 2 | 1 | WON | +0.0009 |
| 20 | `0x2a72df72…` | yes | 2026-11-10 19:57 | no | REDEEM only | 2.3 min | 131 | 2 | 1 | lost | +0.8920 |
| 21 | `0x66a623ac…` | yes | 2026-11-10 19:57 | no | REDEEM only | 2.3 min | 131 | 3 | 1 | lost | -0.1365 |
| 22 | `0x3143b498…` | yes | 2026-11-10 20:00 | no | REDEEM only | 10.3 min | 130 | 1 | 1 | lost | -0.4545 |
| 23 | `0x8d3976be…` | yes | 2026-11-10 20:05 | no | no row | 5.3 min | 131 | 4 | 1 | lost | -0.0001 |
| 24 | `0x39988363…` | yes | 2026-11-10 20:35 | no | REDEEM only | 8.6 min | 131 | 3 | 1 | WON | +9.0909 |
| 25 | `0xbb4bf04d…` | yes | 2026-11-10 20:35 | no | REDEEM only | 8.6 min | 131 | 2 | 1 | lost | -10.6909 |
| 26 | `0x6f63a332…` | yes | 2026-11-10 20:41 | no | REDEEM only | 2.6 min | 131 | 6 | 1 | lost | -0.5663 |
| 27 | `0xe3bae4d3…` | yes | 2026-11-10 22:12 | no | REDEEM only | 10.1 min | 130 | 7 | 1 | lost | -5.7581 |
| 28 | `0x1d1db815…` | yes | 2026-11-10 23:05 | no | no row | 1.5 min | 131 | 2 | 1 | WON | +0.0043 |
| 29 | `0xff4e23d5…` | yes | 2026-11-10 23:21 | no | REDEEM only | 7.0 min | 131 | 2 | 1 | lost | -1.5581 |
| 30 | `0x85a5f56a…` | yes | 2026-11-10 23:59 | no | REDEEM only | 2.2 min | 131 | 2 | 1 | lost | -0.3016 |
| 31 | `0xae526f8a…` | yes | 2026-11-11 03:50 | no | SELL only | 1.8 min | 131 | 5 | 1 | lost | +1.7402 |
| 32 | `0x72228eb5…` | yes | 2026-11-11 03:50 | no | SELL only | 1.8 min | 131 | 2 | 1 | lost | -3.3110 |
| 33 | `0x517e59ed…` | yes | 2026-11-11 04:14 | no | REDEEM only | 0.5 min | 131 | 8 | 1 | WON | +6.2944 |
| 34 | `0x3f32405c…` | yes | 2026-11-11 04:41 | no | REDEEM only | 6.5 min | 131 | 23 | 1 | lost | +3.4345 |
| 35 | `0xd5291b00…` | yes | 2026-11-11 04:50 | no | REDEEM only | 8.7 min | 131 | 1 | 1 | WON | +2.3000 |
| 36 | `0x7b80ede3…` | yes | 2026-11-11 04:53 | no | REDEEM only | 5.2 min | 131 | 22 | 1 | lost | +2.8565 |
| 37 | `0xfc75ecd9…` | yes | 2026-11-11 04:58 | no | REDEEM only | 0.1 min | 131 | 23 | 1 | WON | +50.8771 |
| 38 | `0x3c26ba54…` | yes | 2026-11-11 05:03 | no | SELL only | 6.6 min | 131 | 8 | 1 | lost | -4.9962 |
| 39 | `0x10a9e362…` | yes | 2026-11-11 05:05 | no | no row | 4.3 min | 131 | 2 | 1 | lost | -0.0001 |
| 40 | `0x4999f41f…` | yes | 2026-11-11 05:38 | no | REDEEM only | 4.5 min | 131 | 21 | 1 | lost | +4.4281 |
| 41 | `0xbf5e8051…` | yes | 2026-11-11 05:49 | no | REDEEM+SELL | 4.2 min | 131 | 3 | 1 | lost | -1.4792 |
| 42 | `0x70190af7…` | yes | 2026-11-11 05:52 | no | REDEEM only | 1.2 min | 131 | 1 | 1 | lost | -0.9090 |
| 43 | `0x1e042933…` | yes | 2026-11-11 05:56 | no | SELL only | 8.0 min | 131 | 14 | 1 | lost | -3.4872 |
| 44 | `0xe82959d4…` | yes | 2026-11-11 06:05 | no | REDEEM only | 10.6 min | 130 | 12 | 1 | WON | +26.7324 |
| 45 | `0x1b8b1290…` | yes | 2026-11-11 06:25 | no | no row | 1.2 min | 131 | 2 | 1 | WON | +0.0037 |
| 46 | `0xc74da83e…` | yes | 2026-11-11 06:39 | no | no row | 9.2 min | 131 | 5 | 1 | WON | +0.0032 |
| 47 | `0x934fb509…` | yes | 2026-11-11 06:39 | no | SELL only | 9.2 min | 131 | 3 | 1 | lost | -0.6267 |
| 48 | `0x9dd9a2d1…` | yes | 2026-11-11 07:00 | no | REDEEM only | 9.9 min | 131 | 5 | 1 | WON | +8.8660 |
| 49 | `0x15e93dbd…` | yes | 2026-11-11 07:01 | no | REDEEM only | 9.6 min | 131 | 5 | 1 | lost | +0.7200 |
| 50 | `0xfba410e9…` | yes | 2026-11-11 07:17 | no | REDEEM only | 4.7 min | 131 | 7 | 1 | lost | -5.5287 |
| 51 | `0x20f428b8…` | yes | 2026-11-11 07:17 | no | REDEEM only | 4.7 min | 131 | 18 | 1 | WON | +1.0863 |
| 52 | `0xf08ffcd4…` | yes | 2026-11-11 07:17 | no | REDEEM+SELL | 4.7 min | 131 | 12 | 1 | lost | -3.4487 |
| 53 | `0x2189890a…` | yes | 2026-11-11 08:17 | no | REDEEM only | 10.5 min | 130 | 14 | 1 | lost | -3.9705 |
| 54 | `0x9dcd033c…` | yes | 2026-11-11 08:30 | no | REDEEM only | 8.7 min | 131 | 6 | 1 | WON | +16.6500 |
| 55 | `0x4612b72d…` | yes | 2026-11-11 09:02 | no | SELL only | 9.6 min | 131 | 6 | 1 | lost | -0.8910 |
| 56 | `0xb4e8211e…` | yes | 2026-11-11 09:02 | no | REDEEM only | 9.6 min | 131 | 5 | 1 | lost | -0.9000 |
| 57 | `0x002bf7b2…` | yes | 2026-11-11 09:05 | no | REDEEM only | 6.1 min | 131 | 2 | 1 | lost | -0.2836 |
| 58 | `0xb6c2720e…` | yes | 2026-11-11 09:05 | no | no row | 6.0 min | 131 | 2 | 1 | WON | +2.0863 |
| 59 | `0x60561d7d…` | yes | 2026-11-11 11:25 | no | REDEEM only | 9.0 min | 131 | 3 | 1 | WON | +6.5545 |
| 60 | `0x53af89f2…` | yes | 2026-11-11 11:25 | no | SELL only | 9.0 min | 131 | 3 | 1 | lost | -0.5286 |
| 61 | `0xa45b04b6…` | yes | 2026-11-11 11:26 | no | SELL only | 8.4 min | 131 | 7 | 1 | lost | -3.7176 |
| 62 | `0xf9a716f4…` | yes | 2026-11-11 11:33 | no | no row | 1.4 min | 131 | 3 | 1 | WON | +0.0015 |
| 63 | `0x8c7487ec…` | yes | 2026-11-11 11:33 | no | REDEEM only | 1.4 min | 131 | 2 | 1 | lost | -1.7618 |
| 64 | `0x4e93e065…` | yes | 2026-11-11 12:56 | no | REDEEM only | 6.1 min | 131 | 2 | 1 | lost | -0.0772 |
| 65 | `0x6d92d0f2…` | yes | 2026-11-11 12:56 | no | REDEEM only | 6.0 min | 131 | 3 | 1 | WON | +10.2954 |
| 66 | `0x5d21b8ff…` | yes | 2026-11-11 13:00 | no | no row | 2.4 min | 131 | 3 | 1 | WON | +0.4671 |
| 67 | `0xca520c09…` | yes | 2026-11-11 13:00 | no | REDEEM only | 2.4 min | 131 | 1 | 1 | lost | -0.8488 |
| 68 | `0xb09f09e0…` | yes | 2026-11-11 13:16 | no | REDEEM only | 8.2 min | 131 | 3 | 1 | lost | -0.1715 |
| 69 | `0xae8a6bc4…` | yes | 2026-11-11 14:26 | no | REDEEM only | 4.7 min | 131 | 1 | 1 | lost | -5.1270 |
| 70 | `0x7aa3fd94…` | yes | 2026-11-11 14:40 | no | REDEEM only | 0.9 min | 131 | 1 | 1 | lost | -0.4545 |
| 71 | `0xf48d546f…` | yes | 2026-11-11 19:37 | no | SELL only | 1.0 min | 131 | 5 | 1 | lost | -2.6210 |
| 72 | `0x4ed9b668…` | yes | 2026-11-11 20:02 | no | SELL only | 9.6 min | 131 | 4 | 1 | lost | -0.8100 |
| 73 | `0x5d67e818…` | yes | 2026-11-11 20:12 | no | SELL only | 9.8 min | 131 | 5 | 1 | lost | -0.5097 |
| 74 | `0xcb2a973f…` | yes | 2026-11-11 20:12 | no | REDEEM only | 9.8 min | 131 | 5 | 1 | lost | -0.8663 |
| 75 | `0x34e28d8b…` | yes | 2026-11-11 20:35 | no | REDEEM only | 9.5 min | 131 | 2 | 1 | WON | +4.5454 |
| 76 | `0xff0c8295…` | yes | 2026-11-11 20:50 | no | REDEEM only | 5.2 min | 131 | 4 | 1 | WON | +17.4909 |
| 77 | `0x8f1902d5…` | yes | 2026-11-11 20:52 | no | REDEEM only | 2.9 min | 131 | 3 | 1 | lost | -0.5200 |
| 78 | `0x215e54d1…` | yes | 2026-11-11 21:45 | no | REDEEM only | 5.6 min | 130 | 7 | 1 | lost | -0.0081 |
| 79 | `0x36c8fb71…` | yes | 2026-11-11 21:54 | no | REDEEM only | 7.6 min | 129 | 1 | 1 | lost | -1.4888 |
| 80 | `0x1db9777f…` | yes | 2026-11-11 23:51 | no | no row | 11.0 min | 118 | 2 | 1 | lost | +0.0013 |
| 81 | `0x26bc1282…` | yes | 2026-11-11 23:51 | no | no row | 11.0 min | 118 | 2 | 1 | lost | +0.0013 |
| 82 | `0x95406e84…` | yes | 2026-11-11 23:51 | no | no row | 11.0 min | 118 | 2 | 1 | lost | +0.0013 |
| 83 | `0xffde9b3c…` | yes | 2026-11-12 08:57 | no | no row | 4.5 min | 69 | 2 | 1 | WON | +0.0118 |
| 84 | `0x851ce926…` | yes | 2026-11-12 08:57 | no | REDEEM only | 4.5 min | 69 | 1 | 1 | lost | -0.1636 |


## Method limits

* **Cache-bounded.** The activity caches are snapshots: luciebot's is the newest 5,000 all-type rows,
  `2026-11-10T07:23Z → 2026-11-12T20:32Z`, truncated at that boundary. Every statement about "no print
  on this token" is a statement about that window, which is the window the card is about.
* **Text-matched, then token-verified.** The capture test in §Verdict keys on
  `(conditionId, outcome label, second)` because `ObservedTrade` stores no `token_id`; the token-identity
  read (§2) validates that on the label-free basis and gives the same answer on all 84.
* **`swept_after` is an ingest proxy.** "A sweep covered the print" is inferred from a stored row's
  `createdAt` inside the print's 24 h carry window; a swept-but-empty cycle leaves no trace, which can
  only make this test *conservative* (fewer legs classified as covered), never invent a miss.
* **Dust PnL is not a strategy.** The 84 legs' +$130.22 is what luciebot's own residual `yes` book did;
  it was never copyable, so it is context, not a counterfactual return.
* **The probe is cache-fixed; the trailing-7d figures are not.** Re-running `seat-evidence-coverage.py`
  today returns the same activity-probe numbers (961 / 2,173 / 84) because the caches are static, while
  its venue-side 7-day fields drift with the clock (`venue_legs_entered_7d` read 9,264 then 9,246 in two
  runs 20 minutes apart). Compare probe numbers to the parent draft, never the 7-day ones.
