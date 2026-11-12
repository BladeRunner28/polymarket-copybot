# Seat evidence coverage — why 12 of 25 seats cannot be priced on the legs we would copy

**Card** t_52219682 (Lane B, read-only measurement — no rule, gate, size or tracking change was made).
**Instrument** `scripts/seat-evidence-coverage.py` → `data/seat-evidence-coverage.json`
(caches it owns: `data/seat-evidence-open-positions.json`, `data/seat-evidence-market-truth.json`,
`data/seat-evidence-activity.json`; closed books: `data/wallet-seat-positions.json` from the parent card).
Measured 2026-11-12T21:15Z against `prisma/dev.db` (SELECT only), active rule set **v72**.

---

## Answer

The 12/25 headline reproduces exactly, and it is **not a rotation problem and not an instrument
problem**. Decomposed on both populations:

* **Of the 21,573 legs this bot has observed, 36.7% (7,907) are still unsettled.** That share is
  calendar, and for the 12 thin seats it is **60.9%**.
* **Of the 27,917 venue-settled legs the bot never observed, 57.0% predate the wallet's first
  observed row at all** — history that no policy can reach — and another 40.6% were entered while the
  wallet was being swept but produced no stored row.
* Measuring that 40.6% against **the venue's own event tape** (the `/v2/activity` feed, all types)
  splits it: **29.9% of those legs never had a copyable BUY print** (the position was born of a
  REDEEM / CONVERSION / MERGE — a market maker's book, not a flow of copyable fills), **67.5% had a
  copyable BUY print that nobody was watching for** (the wallet held no seat and was outside the
  sweep set), and **2.6% were print-present, swept, and not stored** — the only true capture failure,
  and it is 84 legs out of 3,218 probed.
* **`MAX_OBSERVE = 40` is not binding.** The observation pool is 1,775 wallets, a full pool sweep is
  45 cycles ≈ **8.25 h** at the measured 11.0-minute cycle against a 24-hour monitor lookback, and a
  wallet gets ~20 sweeps inside its 7-day eligibility. Legs lost to "not swept while eligible" across
  all 25 seats: **668, i.e. 2.4% of the never-observed gap**. The cap could carry a pool of ~5,200
  wallets (130 cycles × 40; a 131st cycle would be 1,441 min and start losing fills).
* **The operative constraint is when observation starts and how long the market takes to settle.**
  418 wallets have *ever* held a copy seat; 6 of today's 25 seats have been copy-eligible for less
  than 7 days and 12 for less than 30. A wallet that has never held `status='track'` is outside
  `observeWhere()` and accumulates **zero** observed keys, so its evidence clock always starts at
  admission. At the pool's median settled flow (**0.983 settled observed legs/day**) 30 legs take
  **30.5 days**; the distribution across seats is p25 5.7 d, median 30.5 d, p75 52.3 d, max 752.5 d.

**The card's refusal fires.** For the thin seats the never-observed gap is 99.8% pre-observation
(431 of 432) and 1 leg is rotation-attributable; 61% of what they *have* observed is unsettled.
Thinness is calendar time plus admission tenure, not observation policy. That is a complete answer;
the one policy change it implies (observation *before* admissibility) is written below as a proposal
with its measured before/after, and was **not applied**.

---

## 1. What reproduces, and on what basis

| quantity | value |
|---|---|
| seats | 25 |
| seats with <30 observed settled legs | **12** (parent: 12) |
| seats with zero observed legs | 1 (`0x167d74fc`) — parent said 2 zero *settled*; both re-measured below |
| observed keys (identity-deduped) | 21,573 |
| of which settled on the parent's basis (our own venue leg reads terminal) | 12,505 |
| of which settled only via the independent market oracle | +945 → **13,450 settled all-in** |
| unsettled | 7,907 |
| observed in a settled market with no venue position to settle against | 638 |
| settlement unknown on both surfaces | 216 |

Per-seat settled counts reproduce the parent card exactly except the subject (**7,796 vs 7,798**).
The 2-leg difference is identified: `0x19d2ff72e3…` and `0x4d09a64f4f…` have a wallet mark that reads
terminal on an `end_date` in the past while the CLOB oracle reports `closed=false` with no winner
(postponed/void markets). This instrument prefers the oracle; both were counted settled upstream.

Settlement authority: `https://clob.polymarket.com/markets/<conditionId>` (`closed` + `tokens[].winner`),
cached for 4,784 markets; where a leg's market is absent from the oracle the wallet's own terminal mark
on a passed `end_date` is used, exactly as upstream.

## 2. Coverage, decomposed (the four populations the headline blends)

The 25 seats' venue books hold **40,430 settled legs** (identity-deduped, full walks, none capped).
27,917 of them were never observed at all; 12,513 were observed, of which 12,505 settle on the
wallet's own record and 8 are legs whose market has already resolved while their `end_date` has not
yet passed (they sit in the +945 oracle-settled bucket below). The observed side carries 21,573 keys,
which split as:

| population | legs | share |
|---|---|---|
| observed & settled (b) | 13,450 | — |
| **observed & unsettled (a)** | **7,907** | 36.7% of all observed keys |
| observed, settled market, no venue position (d) | 638 | 3.0% of all observed keys |
| observed, settlement unknown | 216 | 1.0% |
| venue settled legs never observed (c) | 27,917 | — |
| … of which entered **before** the wallet's first observed row | 15,920 | 57.0% of (c) |
| … of which entered while a sweep would have covered them (c-miss upper bound) | 11,329 | 40.6% of (c) |
| … of which entered with no sweep inside the 24 h lookback (not swept) | 668 | 2.4% of (c) |

Split the same way for the 12 thin seats and the 13 healthy ones:

| population | thin 12 | healthy 13 |
|---|---|---|
| observed keys | 304 | 21,269 |
| settled | 99 (32.6%) | 12,406 (58.3%) |
| **unsettled** | **185 (60.9%)** | 7,722 (36.3%) |
| venue settled legs never observed | 432 | 27,485 |
| … pre-observation | **431 (99.8%)** | 15,489 (56.4%) |
| … not swept | 1 | 667 |
| … swept-and-missed (upper bound) | 0 | 11,329 (11,252 of them the subject) |

The thin seats' missing evidence is almost entirely *before we ever looked*; the one seat with a
swept-and-missed mass is the market maker (`luciebot`), and section 4 shows most of that mass was
never copyable at all.

## 3. Per-seat coverage table

`obs keys` = distinct (market, outcome) identities observed; `settled` = those whose venue leg reads
terminal (parent's basis); `never obs.` = venue settled legs with no observed key; `pre-obs.` = of
those, entered before the seat's first stored row; `span` = first→last stored row; `days→30` = days of
observation this seat needs to reach 30 settled observed legs at its own measured rate (blank = it
cannot at its own flow, or has no observed span yet).

| seat | obs keys | settled | unsettled | venue settled, never obs. | of which pre-obs. | span | days→30 |
|---|---|---|---|---|---|---|---|
| 0x167d74fc | 0 | 0 | 0 | 8 | 8 | 0.0 d | — |
| 0xe1c08abf | 31 | 0 | 30 | 31 | 31 | 0.6 d | — |
| kjhgkltivtvriur | 10 | 2 | 6 | 5 | 5 | 5.2 d | 78.7 |
| bitcoin9 | 4 | 3 | 1 | 22 | 22 | 0.0 d | — |
| ThisAgain | 11 | 4 | 5 | 11 | 10 | 100.3 d | 752.5 |
| 0x06081d47 | 12 | 4 | 8 | 6 | 6 | 0.3 d | — |
| illenial | 10 | 6 | 4 | 2 | 2 | 8.3 d | 41.3 |
| legioncre | 32 | 7 | 25 | 4 | 4 | 39.4 d | 168.8 |
| lstpetr | 15 | 9 | 6 | 23 | 23 | 87.8 d | 292.8 |
| KongX | 53 | 16 | 36 | 233 | 233 | 68.1 d | 127.7 |
| M4ken168 | 41 | 21 | 20 | 13 | 13 | 26.1 d | 37.3 |
| 0xe156c859 | 85 | 27 | 44 | 74 | 74 | 38.7 d | 43.0 |
| 0xc576775e | 87 | 31 | 34 | 9 | 9 | 26.9 d | 26.0 |
| DelidelaDele | 93 | 42 | 51 | 4 | 4 | 42.7 d | 30.5 |
| GAMBLINGISCANCER69 | 289 | 60 | 37 | 0 | 0 | 104.5 d | 52.3 |
| 0x3d5a9e66 | 153 | 61 | 92 | 456 | 378 | 20.1 d | 9.9 |
| randypunt | 248 | 74 | 164 | 79 | 79 | 60.2 d | 24.4 |
| RJW1 | 195 | 85 | 71 | 73 | 73 | 119.2 d | 42.1 |
| JoeyAroyyOO | 257 | 108 | 149 | 70 | 70 | 9.6 d | 2.7 |
| TheOmniussiah | 200 | 114 | 86 | 1165 | 1165 | 49.4 d | 13.0 |
| Kyn008 | 554 | 261 | 257 | 85 | 85 | 27.4 d | 3.2 |
| SimpleTony | 1177 | 370 | 774 | 2857 | 2845 | 70.1 d | 5.7 |
| GamblingAddict12345 | 3134 | 1555 | 902 | 3987 | 3333 | 102.2 d | 2.0 |
| forecastication4 | 3511 | 1849 | 1532 | 1819 | 1819 | 47.7 d | 0.8 |
| luciebot | 11371 | 7796 | 3573 | 16881 | 5629 | 38.7 d | 0.1 |

Two readings worth keeping: the table is not sorted by flow but by settled stock, and the seats at the
bottom are not the ones with the deepest *record* — they are the ones with the longest *tenure*. The
subject holds 62% of the entire observed settled base (7,796 of 12,505) and is the seat the parent card
already showed reads flat on its copy legs.

## 4. The "never observed" legs, measured on the venue's own tape

Proximity (`a sweep happened within 24 h of the entry`) is an upper bound on what was *missable*; it
says nothing about whether a copyable fill existed. The venue's own activity feed does. For each seat I
read the feed newest-first (≤10 pages / 5,000 rows) and classified the **first** venue event on every
never-observed leg that falls inside that window:

* **no copy print** = the market's first event for this wallet is REDEEM / CONVERSION / MERGE / SELL —
  the position was acquired without a BUY fill, so there was never a leg to copy;
* **print, unwatched** = a BUY print exists but no sweep of that wallet falls inside the 24 h lookback
  (the wallet held no seat at the time);
* **print, missed** = a BUY print exists *and* a sweep would have covered it — a real instrument miss.

| seat | activity window | legs in window | no copy print | print, unwatched | print, missed |
|---|---|---|---|---|---|
| TheOmniussiah | 06-17→11-12 | 1165 | 2 | 1163 | 0 |
| luciebot | 11-10→11-12 (cut) | 700 | 616 | 0 | 84 |
| 0x3d5a9e66 | 08-23→11-12 | 455 | 337 | 118 | 0 |
| GamblingAddict12345 | 09-04→11-12 (cut) | 307 | 3 | 304 | 0 |
| KongX | 06-18→11-12 (cut) | 233 | 3 | 230 | 0 |
| randypunt | 07-03→11-12 | 79 | 0 | 79 | 0 |
| 0xe156c859 | 10-14→11-12 | 74 | 0 | 74 | 0 |
| JoeyAroyyOO | 10-26→11-12 | 70 | 0 | 70 | 0 |
| 0xe1c08abf | 06-16→11-12 | 31 | 0 | 31 | 0 |
| lstpetr | 06-15→11-03 | 23 | 0 | 23 | 0 |
| bitcoin9 | 03-18→08-17 | 22 | 0 | 22 | 0 |
| M4ken168 | 09-17→10-30 | 13 | 0 | 13 | 0 |
| 0xc576775e | 09-14→11-12 | 9 | 0 | 9 | 0 |
| ThisAgain | 06-11→11-12 (cut) | 8 | 0 | 8 | 0 |
| 0x167d74fc | 10-12→10-22 | 8 | 0 | 8 | 0 |
| 0x06081d47 | 11-06→11-12 | 6 | 0 | 6 | 0 |
| kjhgkltivtvriur | 11-03→11-12 | 5 | 0 | 5 | 0 |
| legioncre | 08-21→11-05 | 4 | 0 | 4 | 0 |
| DelidelaDele | 09-14→11-09 | 4 | 0 | 4 | 0 |
| illenial | 10-24→11-04 | 2 | 0 | 2 | 0 |
| **all 25** | — | **3218** | **961** | **2173** | **84** |

Consequences:

1. **The instrument itself is not the problem.** 84 of 3,218 probed legs (2.6%) were print-present,
   swept and still not stored — all of them on `luciebot`, whose own activity feed carries ~3,800
   TRADE rows in 85 h and whose monitor fetch is capped at 4 pages × 500 rows per sweep. That cap is
   worth a separate look, but it moves 84 legs, not 12 seats.
2. **A market maker's "missing" legs are mostly not legs.** 616 of luciebot's 700 probed legs and 337
   of `0x3d5a9e66`'s 455 begin with a non-fill event; 46.2% of the subject's own activity rows are
   REDEEM/CONVERSION/MERGE. Counting those against the observed base overstates thinness on exactly
   the seats whose venue record looks deepest.
3. **The fixable mass is "nobody was watching"** — 2,173 legs (67.5%), concentrated on
   `TheOmniussiah` (1,163), `GamblingAddict12345` (304), `KongX` (230), i.e. wallets observed only
   from the date they first held a seat. That is an admission-sequencing question, not a rotation one.

## 5. Rotation arithmetic

| quantity | value | source |
|---|---|---|
| monitor cycle (median / p90 / max) | 11.0 / 16.5 / 1,254 min | 14,407 ingest runs, 2026-07-14 → now |
| `MONITOR_HOURS` (lookback per sweep) | 24 h | `scripts/monitor-trades.ts:23` |
| `MAX_OBSERVE` | 40 / cycle | `src/lib/wallet-universe.ts:41` |
| observation pool now (`status!='track'` ∧ `lastTrackedAt` ≥ now−7d) | 1,775 | DB |
| cycles to cover the pool | ⌈1775/40⌉ = 45 | — |
| **sweep period per observe-pool wallet** | **45 × 11.0 min ≈ 8.25 h** | — |
| sweeps a demoted wallet gets inside its 7-day eligibility | 20.4 | — |
| pool size at which a sweep would first exceed the 24 h lookback | **~5,200** (130 cycles × 40; a 131st cycle is 1,441 min) | — |
| legs lost to "not swept while eligible", all 25 seats | **668 (2.4% of the never-observed gap)** | per-seat classification |

**Seats are not in the rotation at all.** `copyWalletSet()` returns every `status='track'` row (≤25) and
`monitor-trades.ts` queues all of them every cycle; `observeWhere()` explicitly excludes
`status='track'`. A seat is swept every ~11 minutes with a 24-hour lookback, so rotation cannot account
for a single missing seat leg — which is what the per-seat numbers show (0 swept-and-missed legs on 23
of 25 seats; the two exceptions are the subject at 11,252 and `0x3d5a9e66` at 77, both explained in §4).

What the rotation *does* bound is the evidence a **demoted** wallet keeps accruing: it is observed for
7 days after it loses the seat, then falls out of `observeWhere()` for good. The seat set's own
coverage holes total 13,025 hours — **77.5 wallet-weeks** of history inside which nothing could be
observed at all (19 of 25 seats have at least one hole >24 h; median 152 h per seat).

## 6. Time-to-evidence

Measured rate = settled observed legs ÷ days of observation, per seat (needs ≥0.5 d of span).

| statistic | value |
|---|---|
| median settled observed legs per day | **0.983** |
| **days to reach 30 settled legs at the pool median** | **30.5** |
| distribution across seats (p25 / median / p75 / max) | 5.7 / 30.5 / 52.3 / 752.5 days |
| seats that reach 30 within 7 days of observation | 6 of 25 |
| seats that reach 30 within 30 days of observation | 10 of 25 |
| seats that never reach 30 at their own flow | 4 (two have no measurable observation span yet — `0x167d74fc`, `0x06081d47`; two have no settled leg at their rate — `0xe1c08abf`, `bitcoin9`) |

**For a new wallet admitted today the minimum age is not a policy number at all.** It is
`30 ÷ (its own settled observed flow)`, and the clock only starts once the wallet is inside a sweep
set — 1,583 of the 3,602 watch wallets have never been tracked and therefore carry no observed keys at
all today (the only exceptions, 30 legacy wallets with 9,998 rows between July and September, were
written before `lastTrackedAt` existed in v61). At the pool median that is **30.5 days after
admission**, before any floor becomes decidable; for the slowest live seat it is 752.

## 7. The two zero-evidence seats

**`0x167d74fc517d` — dead seat.** Its entire venue life is one burst: 10 TRADE prints, every one
between 2026-10-12T05:38Z and 2026-10-13T03:59Z. The feed holds 20 rows in total for the wallet —
10 TRADE, 5 REDEEM, 2 MERGE, 2 YIELD, 1 SPLIT — and **its last event of any kind is a redeem on
2026-10-22; it has not printed a trade in 30 days** (`trade_rows_24h/7d/30d = 0/0/0`). Its 10 closed
legs are large (five at ~20,005 USDC, two at 120,000, 20,010, 2,843, 194) with `end_date` from
2026-10-17 to 2028-11-08; 8 settled as winners on mark 1.0, 2 sit in 2028-dated markets it has already
exited. The stored profile carries `tradeCount30d = 10`, `resolvedTradeCount30d = 10` — the scoring
sample *is* that burst, now sitting at the edge of the 30-day window. Every one of its 8 settled legs
is pre-observation (`c_pre = 8`) and the bot has never stored a row for it (`first_ingest = null`). It
is not mislabelled (same address the profile was scored on) and not structurally invisible (its 10
prints are on the tape) — it simply does not trade. **It can never accumulate observed evidence
without new flow, so any observed-legs rule scores it 0 forever.**

**`0xe1c08abf3f7d` — live seat, 15-hour evidence clock.** 514 activity rows total, 443 of them TRADE;
**201 trades in the last 7 days and 116 in the last 24 hours** (all of its 30-day trade flow falls
inside the last 7 days). 160 positions: 56 closed, of which 31 settled, and 104 open — outcomes are
tennis players (`Adrian Andreev`, `Coco Gauff`, …), with open legs resolving to 2026-11-19. Its first
stored row is 2026-11-12T04:59Z, ~15 h before this read. Its 31 observed keys are **all unsettled** and
its 31 settled venue legs all predate that first row (`c_pre = 31`, `c_capture_miss = 0`). At its
measured pace (58 legs entered in the last 7 days) it will clear 30 settled observed legs on its own
within days. **Tenure/calendar, not a dead, mislabelled or invisible seat.**

## 8. Coverage over time (all 25 seats, venue settled legs first entered per week)

| week | venue settled legs first entered | observed ever | observed within 3d | coverage |
|---|---|---|---|---|
| 2026-07-08 | 180 | 2 | 1 | 1% |
| 2026-07-22 | 686 | 0 | 0 | 0% |
| 2026-07-29 | 271 | 13 | 13 | 5% |
| 2026-08-01 | 653 | 258 | 258 | 40% |
| 2026-08-08 | 566 | 243 | 243 | 43% |
| 2026-08-15 | 547 | 201 | 201 | 37% |
| 2026-08-22 | 403 | 8 | 8 | 2% |
| 2026-09-01 | 499 | 15 | 15 | 3% |
| 2026-09-08 | 898 | 52 | 46 | 6% |
| 2026-09-15 | 2185 | 98 | 54 | 4% |
| 2026-09-22 | 2362 | 367 | 287 | 16% |
| 2026-09-29 | 608 | 120 | 88 | 20% |
| 2026-10-01 | 2749 | 1189 | 1150 | 43% |
| 2026-10-08 | 1976 | 1099 | 1099 | 56% |
| 2026-10-15 | 1948 | 1184 | 1184 | 61% |
| 2026-10-22 | 4383 | 2057 | 2057 | 47% |
| 2026-10-29 | 1848 | 757 | 757 | 41% |
| 2026-11-01 | 7645 | 3439 | 3439 | 45% |
| 2026-11-08 | 3345 | 1408 | 1408 | 42% |

The shape is the whole story: coverage was 0–6% until late September, jumped when the observation
universe landed (v61/v62), and has plateaued at **41–47%** of venue settled legs since — not because
rotation is starved, but because the other ~55% is pre-admission history, demoted-wallet gaps and
non-copyable prints. "Observed within 3 days of entry" converges on "observed ever" from mid-October
(97% in the first week of October, 100% from 2026-10-08 on): where a wallet is watched, capture is
effectively complete.

## 9. Verdict

**Can the observed-legs evidence base be made thick enough for an admissibility rule to be decidable by
observation policy alone? No — and the part that policy can fix is smaller than the part it cannot.**

| component | share of the never-observed gap | fixable by? |
|---|---|---|
| entered before the wallet was ever observed | 57.0% | nothing (history) |
| no copyable fill ever existed (REDEEM/CONVERSION/MERGE) | ~30% of the probed remainder | nothing (not evidence) |
| copyable print, wallet outside the sweep set | 67.5% of the probed remainder | **observation *before* admission** (Lane A knob) |
| copyable print, swept, not stored | 2.6% of the probed remainder | monitor page cap (Lane B instrument, 84 legs) |
| not swept while eligible | 2.4% of the gap | rotation policy — not binding |

And the calendar half cannot be compressed: **36.7% of everything observed is unsettled**, 60.9% for the
thin seats. An observed-settled floor of 30 legs is therefore a *minimum-age* rule in disguise, and the
age it imposes is 30.5 days at the pool median.

**Refusal (per the card): it fires.** The thinness is mostly (a) unsettled markets plus pre-admission
history, not (c) rotation. The constraint is calendar time. Stated and stopped.

## 10. Proposal only — observation priority (Lane A knob, NOT applied)

The one lever the data supports, written as before/after, applied nowhere:

**Before.** `observeWhere()` = `status != 'track'` ∧ `lastTrackedAt ≥ now − 7d`. A wallet's evidence
clock starts when it first holds a seat. Today: 12 of 25 seats are under 30 settled observed legs; 6 of
25 have been copy-eligible <7 days; 1,583 watch wallets have never been observed at all.

**After (proposed).** Admit an observation cohort: wallets that out-score the current cut (today 15, all
already tracked-and-demoted) plus a bounded top-K of never-tracked watch wallets, observed for N days
*before* they may hold a seat. Measured effect on today's 25 seats, as an upper bound (it counts legs
first entered in the trailing window that have already settled):

| pre-admission observation window | seats with ≥30 settled legs at admission |
|---|---|
| none (today) | 13 of 25 (their post-hoc observed base), 0 of 25 at admission |
| 7 days | **6 of 25** |
| 14 days | **7 of 25** |

Pool cost: adding K wallets raises the pool sweep to ⌈(1775+K)/40⌉ cycles — K = 200 gives 50 cycles
≈ 9.2 h, still inside the 24 h lookback, so no fills are lost.

Read the table before wanting it: even a full 7-day pre-admission window leaves **19 of 25 seats**
below a 30-leg settled floor, because those seats do not trade 30 resolved legs in a week. The policy
buys a decidable basis for the top quartile and converts the rest into a hard admission bar — which the
parent card already priced at 60% of decisions and −$256 of paper PnL over 7 days. This is a Lane A
decision, not a measurement result.

## 11. Method limits

* Venue records are the parent card's full `CLOSED` walks, re-read here; all 25 end `done`, none capped
  (subject 640 pages / 31,993 positions). `OPEN` books were walked fresh for this card.
* Settlement: CLOB `closed` flag where known, else the wallet's terminal mark on a passed `end_date`.
  Two subject legs disagree between the two and are counted unsettled here (documented in §1).
* `c_capture_miss` (11,329) is inferred from stored-row proximity, **not** from a seat-status history
  (none is stored). The activity probe shows only ~12% of those legs had a print at all for the
  subject, so treat it as an upper bound on missable legs, never as a miss count.
* The activity probe is bounded (newest-first, ≤5,000 rows/wallet): its window is 2 days for `luciebot`
  and months for low-flow seats. The print split characterises each window, not all history.
* Observed keys dedupe by `(conditionId, normalised outcome)` — one copy opportunity per market/outcome;
  a seat that trades one market fifty times contributes one leg. Venue legs are deduped the same way.
* Seat tenure is reconstructed from copy-eligible rows (`observationOnly = 0`); the first such row is a
  **lower bound** on admission, because a seat admitted before monitoring could not have stored one.
* 638 observed keys (3.0%) are settled markets with no venue position on either book (`592` of them on
  `GamblingAddict12345`). They are real observed legs whose position was closed by merge/redeem and has
  left the position API; anyone pricing "observed settled" off a position walk alone will miss them.
* Nothing here changes a rule, gate, size, or tracking decision. The only writes are `data/` caches and
  this draft.
