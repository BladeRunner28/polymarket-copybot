# Thin-record floor: measured on our own legs — no depth effect, and the naive floor removes profit

**Card:** `polycopy-thin-record-floor-test`. **Status: closed on a NULL for the feature**, plus two
findings that matter more than the null: the stored depth field **cannot** grade the deep end at all,
and a minimum-depth floor would have removed **profitable** legs while making the lane's edge % look
better.

**What shipped:** `scripts/wallet-depth-floor-test.py` — read-only, one command re-runs everything
below, stdlib-only Python 3, writes nothing. Nothing was gated, no rule changed, no shadow lane.

---

## 1. The claim being tested

Polycopy's Sep-8 report flags a record as **thin** when it holds few resolved positions (12 of 88
scoreable wallets on their 30-day board, 34 of 65 all-time) and warns that a spectacular number over a
handful of bets is often one good week — their shrink moves the all-time median ROI from 10.52% raw to
2.07%. We have **no explicit depth floor**: `globalScore` blends ROI / consistency / copyability, and
`scan:wallets` profiles whatever the 25 least-recently-scanned wallets are. So the question is: do our
legs from thin-record wallets underperform, and what would a floor at N actually do?

## 2. Two depth measures — because the stored one is capped

| measure | definition | problem |
|---|---|---|
| **(a) stored snapshot** | `WalletProfile.resolvedTradeCount30d` | **clamped at 100** |
| **(b) as-of-entry (ours)** | distinct markets we had already observed that wallet trade **before** the leg was opened (`ObservedTrade.timestamp < PaperTrade.openedAt`) | lower bound (our observation window starts 2026-07-13) |

**The cap is the first finding:** over all 3,201 wallets, `resolvedTradeCount30d` is
min 0 · p10 11 · p25 61 · **p50 100 · p75 100 · p90 100 · max 100** — **65.3% of every wallet in the DB
sits exactly at the cap**, so the field cannot distinguish a 100-position record from a 900-position one.
The whole deep end is one bucket. `tradeCount30d` is capped too (p90 = max = 200). The field is also a
**live snapshot, not an as-of-entry value**: `lastScannedAt` spans 2026-09-18 → 2026-09-23, and the
spearman between the stored snapshot and the depth our scanner had actually seen at entry is **−0.21
(C-200) / +0.35 (STANDARD)** — they are not the same number, in either direction.

## 3. Population

Settled legs only (`status IN ('closed','resolved')`, `isDemo = 0`, `closedAt ?? resolvedAt`,
`realizedPnl NOT NULL`), split by lane. Independently re-derived from SQL:

| lane | legs | source wallets | cost | realized | edge |
|---|---|---|---|---|---|
| C-200 | 1,960 | 101 | $14,844.22 | +$2,426.31 | +16.3% of cost |
| STANDARD | 8,693 | 184 | $99,672.80 | +$8,951.40 | +9.0% of cost |

Caveat that applies to every C-200 number below: the Rust sidecar books C-200 buys 2¢ inside the spread,
so the lane's **edge % is inflated by construction** (measured 2026-09-23: +24.4% booked vs +9.7%
without it). The depth *comparison* is unaffected — both sides carry the same fill model.

## 4. Results

### 4.1 C-200 by stored snapshot (a) — nothing there

| bucket | wallets | legs | realized | mean leg | median leg | win | edge % | med entry |
|---|---|---|---|---|---|---|---|---|
| <25 | 6 | 31 | +$23.14 | +$0.75 | +$2.12 | 68% | +10.2 | 0.535 |
| 25–99 | 33 | 714 | +$170.88 | +$0.24 | −$0.30 | 45% | +2.5 | 0.495 |
| 100 (clamped) | 62 | 1,215 | +$2,232.29 | +$1.84 | +$0.16 | 52% | +28.5 | 0.500 |

Wallet-clustered 95% CI on the mean leg: <25 [−$5.69, +$3.75] · 25–99 [−$3.18, +$1.75] ·
100 [−$0.41, +$3.91]. Thin(<25) vs deep(100) — wallet-clustered permutation **p = 0.841 (mean),
0.263 (median)**. The thinnest bucket has **31 legs from 6 wallets** — it cannot carry a claim either
way, and the within-band price control (below) is not even testable on this lane.

### 4.2 C-200 by as-of-entry depth (b) — non-monotone

| depth bucket (distinct markets seen at entry) | wallets | legs | mean leg | median leg | win | edge % |
|---|---|---|---|---|---|---|
| <66 | 72 | 501 | −$0.60 | $0.00 | 49% | −8.6 |
| 66–227 | 31 | 387 | +$1.65 | +$0.37 | 53% | +25.6 |
| 228–1152 | 15 | 386 | −$0.58 | −$0.25 | 46% | −7.8 |
| ≥1153 | 8 | 686 | +$3.38 | +$0.01 | 50% | +38.7 |

Every wallet-clustered CI includes zero (≥1153: [−$1.06, +$7.13]). The middle is worse than the tail and
the deepest bucket's median leg is **$0.01** — its mean is one or two Kelly-sized wins, the same tail
artifact the PSMI measurement ran into.

### 4.3 STANDARD — the one nominally significant contrast, and why it is a price artifact

| bucket | wallets | legs | mean leg | win | edge % | med entry |
|---|---|---|---|---|---|---|
| <25 | 15 | 191 | −$1.77 | 40% | −15.3 | 0.482 |
| 25–99 | 53 | 1,952 | +$1.64 | 65% | +12.0 | 0.580 |
| 100 (clamped) | 116 | 6,550 | +$0.93 | 64% | +8.6 | 0.585 |

Thin vs deep: **p = 0.092 (mean), p = 0.068 (median)** — not significant — with CIs [−$7.20, +$4.80]
vs [+$0.05, +$1.75]. Inside entry-price quintiles the thin wallet's 191 legs live almost entirely in
the low price bands (median entry 0.482 vs 0.585), and only three bands are testable at all: within
0.41–0.53 thin is worse (−$7.71 vs −$0.39, p = 0.022, 91 legs), within 0.00–0.41 thin is *better*
(+$5.56 vs +$5.02, p = 0.946) and within 0.53–0.60 better again (+$1.79 vs +$0.26, p = 0.740) —
one of three bands, sign inconsistent, i.e. a mix effect with one band carrying the contrast
(and the 0.60+ bands hold **zero** thin legs: thin wallets do not trade favourites). The honest reading:
**thin wallets in the STANDARD lane skew to cheap longshots, and cheap longshots are where the lane's
losses live.**

**Estimator note (applied, not just caveated):** every two-group test here permutes the **group label at
the wallet level** — the pooled wallets are re-split on each draw, never the legs. The first version of
this instrument shuffled legs and reported **p = 0.008 / 0.000** for the STANDARD contrast above; the
clustered test returns **0.092 / 0.068**. A leg-level shuffle treats 191 legs from 15 wallets as 191
independent draws and manufactures significance that does not survive the clustering — that correction
is the difference between "a depth effect worth carding" and "no depth effect".

### 4.4 Rankers vs "leg won" (AUC) — price still beats every wallet feature

AUC 95% CI via Hanley–McNeil at A = 0.5; the sample's MDE is **±0.026 (C-200, 972W/988L)** and
**±0.013 (STANDARD, 5,545W/3,148L)** — anything inside 0.50±MDE is indistinguishable from no information.

| feature | C-200 AUC | STANDARD AUC |
|---|---|---|
| resolvedTradeCount30d (stored snapshot) | 0.526 [0.500, 0.551] | 0.512 [0.500, 0.525] |
| tradeCount30d (scan) | 0.518 [0.492, 0.544] | **0.581 [0.568, 0.593]** |
| as-of-entry depth (ours) | 0.496 [0.470, 0.521] | 0.523 [0.510, 0.535] |
| roi30d | 0.496 | 0.426 |
| globalScore | 0.497 | 0.496 |
| entryPrice (price baseline) | **0.653 [0.628, 0.679]** | **0.758 [0.745, 0.770]** |

Two things to carry forward: (1) as a *depth* feature, nothing here separates winning from losing legs
beyond the noise floor on C-200, and on STANDARD the stored `tradeCount30d` (0.581) beats every depth
measure — but that is a 30-day activity count, i.e. it may be capturing "busy wallet = liquid market"
rather than record quality; (2) `roi30d`, `globalScore` and the other selection scores are **coin flips**
at leg grain on both lanes, while the market's own price is 0.65–0.76. (AUC on "leg won" is not EV — the
book is profitable at 50% win rate because winners are sized/carried differently — but it does say the
scores we select wallets with carry almost no leg-level rank information.)

### 4.5 Floor simulation — the trap

In-sample, on the legs we actually took (`removed$` = realized PnL of the legs the floor would drop):

| floor | C-200 legs kept | % of cost kept | removed PnL | kept PnL | kept edge % | tracked kept |
|---|---|---|---|---|---|---|
| none | 1,960 | 100% | — | $2,426.31 | 16.3 | 13/13 |
| snapshot ≥ 25 | 1,929 | 98.5% | +$23.14 | $2,403.17 | 16.4 | 10/13 |
| snapshot ≥ 100 | 1,215 | **52.8%** | **+$194.02** | $2,232.29 | **28.5** | 5/13 |
| as-of-entry ≥ 50 | 1,527 | 79.1% | **−$207.49** | $2,633.80 | **22.4** | 5/13 |
| as-of-entry ≥ 100 | 1,310 | 70.6% | **−$572.73** | $2,999.04 | **28.6** | 4/13 |
| as-of-entry ≥ 250 | 1,065 | 58.4% | +$262.98 | $2,163.33 | 25.0 | 1/13 |

Read the two middle columns together: **the C-200 floor at 100 raises edge from 16.3% to 28.5% while
throwing away half the lane's volume and $194 of realized PnL**, and the as-of-entry floor at 100 gets
its better edge by dropping legs that net **−$573** — a genuine tail-trim, but it also drops 71% of the
cost basis and 9 of the 13 tracked wallets. At ≥250 the removed legs turn **positive** again
(+$263), so even the "trim the tail" story is not monotone.

The STANDARD lane shows the same trap from the other side: `as-of-entry ≥ 10` keeps 82% of the volume
and cuts edge from **9.0% to 2.1%**, because the removed thin legs carried **+$7,233** of PnL.

**The ladder is a PnL goal, not an edge-% goal.** A depth floor optimises the denominator: it makes
edge % look better while removing absolute profit and copy volume on both lanes.

## 5. Verdict

**No measured depth effect worth a rule.** Specifically:

- C-200: no monotone dose-response in either depth measure; every wallet-clustered CI spans zero; the
  storage field is capped exactly where a floor would operate; and the thinnest bucket (31 legs, 6
  wallets) is too small to test within price bands at all.
- STANDARD: a thin-vs-deep contrast that does **not** clear α = 0.05 under wallet clustering
  (p = 0.092 mean / 0.068 median) and whose single testable within-band effect (p = 0.022) is
  contradicted in sign by the band below it.
- The **mechanism** the vendor describes is real in one narrow sense — thin wallets in this book skew to
  cheap longshots (median entry 0.482 vs 0.585) — but on our data that is a **price** effect, and price
  is a feature we can already measure directly (AUC 0.65–0.76) instead of via a proxy.

**What this does not exclude:** C-200's thin bucket is 31 legs from 6 wallets, and the as-of-entry
measure is a lower bound (our observation window starts 2026-07-13, so a genuinely deep wallet that went
quiet before that reads thin). A depth effect smaller than ~$3/leg on C-200 or a moderate intradecile
effect is not excluded — this design says there is **no strong, monotone depth signal**, not that
depth is irrelevant.

**Follow-ups this measurement does earn** (each its own card, none of them a rule):

1. `resolvedTradeCount30d` / `tradeCount30d` are clamped in the scanner — the clamp is a data-integrity
   defect regardless of what anyone wants to do with depth, and the fix is one field on the scan path
   (store the raw count, keep the score input clamped if that is intended).
2. `tradeCount30d` (0.581 on STANDARD, outside its MDE) is the only wallet feature in this stack that
   beats chance on leg outcome — it deserves its own pre-registered test before anyone reads it as a
   selection signal, because it may just be a liquidity proxy.

## 6. Reproduce

```bash
python3 scripts/wallet-depth-floor-test.py      # the whole measurement above; writes nothing
```
stdlib-only Python 3, reads `prisma/dev.db` (read-only URI). Permutation draws are budgeted by pool
size (2,000–20,000, printed per section); bootstrap CIs resample **wallets**, not legs; `prisma/dev.db`
datetimes are Unix-ms.
