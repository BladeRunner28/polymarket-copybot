# One wallet produced 96% of the near-certainty cohort in six days — its seat was bought by a 100-row tail sample

Card: `t_6d17488d` (Lane B measurement — read-only). Parent read: `t_4d29ae55`
(`drafts/nearcert-mark-guard-after-20261112.md`). Measured 2026-11-12 ~20:00Z.
Instrument: `scripts/wallet-17dd-cohort-read.py` → `data/wallet-17dd-cohort-read.json`.
Venue inputs: data-api **v2** positions (keyless), cached in `data/wallet-17dd-positions.json`
(re-fetch: `--fetch-venue --refetch-subject`); market settlement from the existing label cache
`data/nearcert-market-meta.json`. DB read: `prisma/dev.db` (SELECT only).

---

## 1. Answers to the card, in order

### 1.1 Why it appeared on 11-06, and on what score basis

**It was not discovered on 11-06.** The wallet (`0x17dd123a…`, venue name `luciebot`) entered the
`WalletProfile` table on **2026-10-05 03:00:28Z** from the monthly-PnL leaderboard at **sourceRank 304**
of a 500-wallet scan. Between then and 11-06 the monitor swept it continuously — **20,969 observed
fills over 33.5 days, every one stamped `observationOnly = 1`** — because it sat outside the 25-seat
copy set. Its last `ObservedTrade` before the flood is stamped 2026-11-06 10:31Z; the first row it
ever produced as **copy-eligible** is **2026-11-06 10:48:48Z**, and the scorer journaled its first
decision at **15:40:10Z** the same day. No rule changed with it: RuleSet v71 was active 11-03 → 11-11.

So the trigger is the hourly wallet scan and nothing else: on 11-06 the scan's ranking placed it inside
the top 25. It sits at **seat 24 of 25** now, with the 25th-place wallet at 83.4 against its 83.9 — a
0.5-point margin.

**The basis is a tail sample, and it reproduces exactly.** `scan-wallets` scores a wallet from the
adapter's *profiling* read, which is not the wallet's record: it is **the 50 best + 50 worst closed
positions by realised PnL, plus the 100 open positions with the largest current value**. For this
wallet that is **100 of 31,991 closed positions (0.3%)**. Re-running that sample against the venue's
own position data reproduces the stored figure to within 1%:

| Basis | Positions | Cost | Realised | ROI | Win rate |
|---|---|---|---|---|---|
| Adapter tail sample (what the score reads) | 100 (50 best + 50 worst) | $32,921 | $54,249 | **+164.8%** | 50.0% (by construction) |
| Stored `WalletProfile.roi30d` | — | — | — | **+163.3%** | — |
| **Full venue record** | **31,991** | **$433,961** | **$76,052** | **+17.5%** [+12.1, +24.3] | **19.3%** |

Two consequences, both mechanical:

* the sample is *built* to be 50% winners, so its win rate says nothing; its ROI is the ratio of two
  tails and can be pushed arbitrarily high by one extraordinary winner;
* the score **saturates** on it: `roiScore = clamp(40 + 90·roi)` is clamped at 100 for any `roi ≥ 0.67`,
  so +67% and +16,000% are indistinguishable. This wallet's globalScore recomputes to **83.9**
  (100·0.35 + 70.9·0.35 + 80.2·0.30) with an ROI term pinned at the ceiling.

`WalletInsiderScore` — a different read of the same wallet — disagrees with the profile and looks closer
to the record: score 0.432 on 39 resolved legs, win rate 0.423, concentration 0.9993.

### 1.2 Concentration: it is re-observing, not trading thousands of distinct NO legs

| Metric | Value |
|---|---|
| Decisions journaled (11-06 → 11-12) | 6,641 |
| Distinct markets / distinct (market, outcome) keys | 3,159 / 3,159 (all `NO`) |
| Rows per key | mean 2.10, max 24 |
| Rows that are a re-observation of a key already seen | **52.4%** |
| Re-observation gap | median 22 min, p10 0.12 s (bursts) |
| Mean detected price / wallet's own entry | 0.7685 / 0.7748 |
| Marks ≥ 0.95 / ≤ 0.05 | 3,682 (55.4%) / 416 (6.3%) |

The stream is 3,159 NO positions, each seen ~2.1 times (one Fed market was re-observed 24 times), with
half the rows being repeats. It is a dust-scale market-maker's tape: mean fill 9.7 shares,
~$10 per fill, 11,371 distinct markets in 40 days.

### 1.3 Quality on the venue's own settlement

Every leg is settled at the venue's own 0/1 `outcomePrice` for the token traded — no `won`, no
`realizedPnl` on our side — and the CI resamples whole markets. Entry-price bands are the leg's own
average entry.

| Arm (settled legs) | Legs / keys | Cost | ROI | 95% CI | Win rate |
|---|---|---|---|---|---|
| Its legs from the flood window, entry = **its own price** | 1,899 keys | $34,848 | **−1.47%** | [−3.43%, +0.18%] | 79.4% |
| Same legs, entry = **our detection mid** (what we would pay) | 1,899 keys | $34,376 | **−0.12%** | [−2.07%, +1.54%] | 79.4% |
| Venue record, all 31,991 positions (realised PnL) | 31,991 | $433,961 | **+17.5%** | [+12.1%, +24.3%] | 19.3% |

The two numbers disagree in sign, and the band split says exactly why:

| Entry band | Its positions | Cost | ROI | 95% CI | Win rate |
|---|---|---|---|---|---|
| 0.00–0.05 | 8,389 | $9,947 | **+985.6%** | [+768%, +1256%] | 29.8% |
| 0.05–0.20 | 11,118 | $35,818 | −48.2% | [−54.7%, −40.6%] | 10.9% |
| 0.20–0.40 | 611 | $7,412 | +96.5% | [+11.8%, +157.6%] | 64.5% |
| 0.40–0.60 | 468 | $3,199 | +71.5% | [+64.8%, +80.1%] | 94.0% |
| 0.60–0.80 | 595 | $12,359 | +30.0% | [+26.8%, +32.6%] | 93.8% |
| 0.80–0.95 | 1,208 | $29,397 | +5.5% | [+3.0%, +7.3%] | 57.7% |
| **0.95–1.01** | **9,602** | **$335,828** | **−5.8%** | **[−7.2%, −4.1%]** | **3.8%** |

**Its entire positive record is the sub-0.05 tail (+986% on $9.9k) and the 0.20–0.60 middle. The band
that generates our cohort — 0.95+, 77% of its capital — loses money, with a CI that excludes zero.**
Its flood-window vintage, priced on its own book, is +2.8% [−0.7%, +6.5%]: indistinguishable from zero.

Against the copy set measured on the same basis (all 24 other tracked wallets walked to completion —
none censored):

| | This wallet | Other 24 tracked |
|---|---|---|
| Venue ROI | **+17.5%** | min +53.6%, median **+91.9%**, max +857.9% |
| Win rate (positions) | **19.3%** | 56.8% – 100% |
| Positions | 31,991 | median 106 (8 – 5,735) |

It is the **lowest-ROI wallet in the 25-seat copy set** by a wide margin, and it carries 300× the
position count of the median member. (Scale caveat: its median position costs $2.18 against the
others' $100k-class positions — this is a dust market-maker being ranked against directional whales on
a ratio that ignores scale.)

### 1.4 What the 58 admitted legs did, and whether the near-certainty clause is doing the work

| | Legs | Size | Realised PnL |
|---|---|---|---|
| C-200 `filled` | 18 | $252.57 | −$18.08 |
| C-200 `unfilled` (fill model refused) | 19 | $569.27 | $0.00 |
| C-200 unstamped (pre-instrument) | 15 | $395.41 | −$171.95 |
| STANDARD (open + 1 resolved) | 16 | $259.12 | −$18.00 |
| **All 68 legs** | **68** | **$1,476** | **−$208.03** |

Only **5 of the 68 legs** carried a near-certainty risk, so the clause is not what keeps this wallet's
copies out — 54 of its 58 `paper_copy` decisions came from the 2,562 near-cert-free rows, and 19 of 68
legs were refused by the fill model rather than by a gate.

The clause's own value ceiling, priced on the rows where it is the **sole** blocker (a row blocked by
three gates is not admitted by removing one):

| Near-certainty rows | Rows | Priceable keys | Cost | Settled-outcome ROI | 95% CI |
|---|---|---|---|---|---|
| All near-cert rows | 4,073 | 1,367 | $28,506 | −0.72% | [−2.60%, +0.64%] |
| **Sole blocker** (ceiling on removing it) | **1,104** | **486** | **$11,105** | **−1.15%** | **[−4.79%, +0.71%]** |

So a narrower clause would admit ~1,100 more of this wallet's rows in six days and earn **roughly zero**
(−1.15%, CI spanning zero) — the clause is not protecting a profit, it is truncating a cohort that is
already flat.

### 1.5 The cohort with and without it

| Day | Decisions (all) | This wallet | Near-cert (all) | Near-cert ex-wallet | Near-cert sole ex-wallet |
|---|---|---|---|---|---|
| 11-01 | 1,569 | 0 | 18 | 18 | 6 |
| 11-04 | 933 | 0 | 137 | 137 | 22 |
| 11-05 | 822 | 0 | 9 | 9 | 1 |
| **11-06** | 1,760 | **669** | **479** | **4** | 4 |
| 11-07 | 2,847 | 1,151 | 712 | 17 | 8 |
| 11-08 | 2,413 | 1,149 | 706 | 10 | 3 |
| 11-09 | 1,531 | 1,015 | 659 | 8 | 4 |
| 11-10 | 1,885 | 1,104 | 675 | 28 | 10 |
| 11-11 | 1,560 | 1,003 | 610 | 18 | 13 |
| 11-12 | 1,431 | 550 | 424 | 107 | 0 |

Window totals 11-06 → now: **13,427 decisions of which 6,641 (49.5%) are this wallet**, and **4,261
near-cert rows of which 4,073 (95.6%) are this wallet.** Ex-wallet the cohort runs 4–28/day (median 13)
across 11-06 → 11-11 against a 9–177/day pre-flood baseline (mean 60); the 11-12 ex-wallet jump to 107
is a different wallet (`0x06081d47…`, the new seat-1 entrant from the 11-12 04:00 scan: 76 rows that
day) and is a separate watch item, not this finding.

The cohort also has history the card's framing misses: the near-cert population was far larger in
Jul–Sep (2,000–5,600/day), collapsed to single digits–~500/day through Oct, and the 11-06 jump restores
it to a level the gate has seen before. Any statistic quoted on "the near-certainty cohort" must name
its window, not just its date range.

---

## 2. The pre-registered bar, evaluated as written

> "material if it accounts for ≥25% of decisions in a 7-day window on more than one day AND its
> settled-outcome ROI on ≥30 settled legs is not >0 with a 95% CI excluding zero."

**Material: yes.** The trailing-7-day decision share crosses 25% on 2026-11-08 and stays above it for
five consecutive days (0.28, 0.35, 0.42, 0.48, 0.49) — "more than one day" is satisfied twice over.

**Not profitable with a CI excluding zero: yes on every arm that prices the legs it produces.**

| Arm | ROI | 95% CI | >0 with CI excluding 0? |
|---|---|---|---|
| A. Venue record, all positions | +17.5% | [+12.1%, +24.3%] | **yes** |
| B. Its flood-window legs, its own entry | −1.47% | [−3.43%, +0.18%] | no |
| C. Its flood-window legs, our detected mid | −0.12% | [−2.07%, +1.54%] | no |
| D. Flood-window vintage only (venue record) | +2.84% | [−0.65%, +6.52%] | no |
| E. Rich-side band 0.95–1.01 (venue record) | −5.81% | [−7.20%, −4.12%] | no |

Arm A is the only profitable read, and it is the one basis the card rules out ("not from `won`, not
from `realizedPnl` alone"): it is the venue's lifetime aggregate, dominated by a band we never copy and
a vintage that predates the wallet's admission. On the settlement-based reading — the one the card
specifies — the conjunct is met.

**Verdict: material and not profitable on its settled legs. The card's rule fires → Lane A tracking
change, delta priced below** (carded as `t_6d17488d` follow-up).

The delta a tracking change would move, measured on the same window:

| Item | Value |
|---|---|
| Journal volume removed | 6,641 of 13,427 decisions (49.5%) |
| Near-certainty cohort removed | 4,073 of 4,261 rows (95.6%) |
| Copies removed | 58 of 184 `paper_copy` decisions (31.5%) |
| Legs / PnL removed | 68 legs, **−$208.03** settled (−$18.08 filled-only) |
| Wallet-per-day cap headroom | 40/day cap, ~10/day used — not the binding rail |
| Score-basis repair alone | full-record ROI re-ranks **22 of 25 seats**; this wallet lands at seat 25 of 25 — **inside the cap**, so a basis repair does not remove it by itself |

That last row is the honest complication: fixing the ROI basis is a real defect fix, but on its own it
does not exclude this wallet (68.4 vs a 25th-place cut that also moves). Excluding it needs a rule that
prices *scale and evidence*, not just ratio: a settled-legs ROI floor, a minimum economic size, or a
per-wallet decision-volume ceiling. Each of those is a Lane A proposal with its own before/after — none
is applied here.

---

## 3. What this changes in the parent read

Nothing in `t_4d29ae55`'s conclusion (the price operand fix is what closed the sub-tick class) — that
stands on its own strict test. What changes is the reading of any near-certainty statistic computed on
11-06 or later: **it is a one-wallet cohort**, 95.6% of it, and that wallet's rich-side band loses money
with a CI excluding zero while its cheap-side band pays. A shadow arm, a gate firing rate or a mix
statistic measured on the post-11-06 cohort inherits both properties.

Until a tracking decision is made, quote the cohort **ex-wallet** (4–107/day, roughly the pre-flood
baseline) or name the wallet share beside the figure.

## 4. Instrument honesty / limits

* Settlement covers the **closed** markets only: 4,324 of 6,641 rows (65%) price in, the other 2,317 are
  markets that have not closed yet (mostly 11-10 → 11-12), so the settled arm under-weights the newest
  two days. Zero rows were dropped for outcome-label mismatch.
* Cost basis on venue positions is `total_size × avg_price`. `total_cost_usdc` is unusable (zero on
  28,083 of 31,991 rows); the reconstruction is validated by the venue's own `percent_realized_pnl`,
  which reproduces on it exactly.
* Arm C's cost is concentrated in big keys (top-10 keys = 8.8% of cost, but they carry −654% of the net
  PnL): the cluster CI is honest about market correlation but the *net* is a thin residual of large
  offsetting legs. Read it as "flat", not as a precise zero.
* The tracked-set comparison is on venue aggregate ROI, which ignores scale (median position $2 vs
  $100k-class). It ranks the wallet last; it does not by itself prove the others are better copiees.

## 5. Re-run

```
python3 scripts/wallet-17dd-cohort-read.py --fetch-venue --boot 3000
```

Re-walks the venue (subject 640 pages, 24 tracked wallets), rewrites
`data/wallet-17dd-cohort-read.json`. Read-only against `prisma/dev.db`; writes only under `data/`.
No rule, size, gate, exit or tracking change was made by this card.
