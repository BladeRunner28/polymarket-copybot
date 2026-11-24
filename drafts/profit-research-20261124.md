# Profit research — 2026-11-24

**Instrument:** `scripts/profit-path-research.py` (unchanged), `scripts/profit-question-fill-read.py`
(re-run on today's 07:14 STANDARD stamp), `scripts/lip-ledger.py` (**extended today**: `--schedules`,
section E). Everything below re-runs.
**Basis (every figure):** cost = `simulatedPositionSize` = dollars at risk; PnL = `realizedPnl`,
`status IN ('closed','resolved')` (TR-15 OR); `isDemo=0`; dedupe = first leg per
(bot, wallet, market, outcome); clock = entry vintage; CI = market-clustered bootstrap, 2,000 draws.

---

## Headline

The approved maker thesis is failing its own fill test on the population that can measure it.
On 90 STANDARD question legs with book evidence, the **32 booked exactly at the mid were reachable
0 times**; of the **58 that paid a median 1.5¢ above the mid, 32 (55%) were reached — and those 32
earned +74.7%** (ex-top-3 −13.8%). Meanwhile the mid-booked legs, the ones no seller ever crossed to,
are the loss: 32 legs, **−$260 on $576, −45.1%, CI [−75.1, −12.7]**. In this class the 1-tick pay-up
is the price of owning a position, not a leak to be optimised away.

Everything else is unchanged: the fill-confirmed book is −15.8% on n=308, and 100% of that loss is
still the 22 $100 clips.

---

## 1. Measure

**Fill-confirmed, all settled (dedupe, C-200 + STANDARD):**

- n=308 · $4,746 at risk · **−$749.18 · −15.8%** · CI **[−48.5, +27.4]** · win 41.2% vs BE 47.5%
- ex-$100 clip: n=286 · $2,546 · **−$39.33 · −1.5%** · CI [−25.7, +26.6]
- Δ vs yesterday: +2 legs, +$40 cost, −$40 PnL (both new legs are full −100% losses)

**The $100 tier (22 clips, 7.1% of legs, 46% of filled at-risk):**

- $2,200 · **−$709.85 · −32.3%** · win 9.1% vs BE 14.3% · ex-top-3 −$1,757 (−79.9%)
- all 22 sit inside 0.00–0.20 (the approved band cap's class)
- forward sample since the 11-11 approval: 9 settled legs, $900, **−$47.77, 1 win**;
  ex-top-1 **−$600.00 (−66.7%)**. Refutation needs 40 legs — 9 of 40.

**Vertical split, fill-confirmed:**

- question n=55 · $1,539 · **−$776 · −50.4%** · CI **[−73.3, −17.3]** (CI excludes zero)
- esports n=67 · $1,293 · **−$736 · −56.9%** · CI **[−79.5, −21.9]** (CI excludes zero)
- sports n=118 · $1,156 · +$1,131 · +97.8% · CI [−17.6, +210.1] — **ex-top-3 −$104 (−11.1%)**:
  three legs, not a vertical

**Where the filled book is positive (the only cell with n>100 and ex-top-3 positive):**

- 0.40–0.60: n=77 · $97.81 · +$18.71 · +19.1% · CI [−1.3, +40.3] · ex-top-3 +13.6%
- 0.60–0.80: n=61 · $424.40 · +$58.10 · +13.7% · CI [−3.4, +29.4] · ex-top-3 +9.2%
- combined: n=138 · **$522 at risk · +$76.81 · +14.7%** — avg clip **$3.78**
- the losing pools beside it are 1.6× and 3.8× larger: 0.00–0.10 $825 (−97.8%) and 0.10–0.20
  $2,008 (0.0%, ex-top-3 −$1,235)

**Adjudication coverage (the constraint, not a finding):**

- BANKROLL_200: 956/3,003 settled legs = **31.8%** all-time; **100%** on every entry vintage ≥ 11-17
- STANDARD: **0/10,052 = 0.0%** in the DB. The booth itself runs (07:14 today, 368 legs stamped,
  `data/standard-fill-stamp.jsonl`); it writes an artifact, not `PaperTrade.fillStatus`.

## 2. Approved path — deltas only

**Item 1 (maker vs taker shadow): no writer, day 7 of 30.** `grep -rn "MAKER_SHADOW|restAtMid|
makerShadow" src scripts rust-sidecar/src` → nothing. But the retro read now answers the fill-rate
half of the question, and the answer is the refutation clause: at the mid, fill rate 0/32.

**Item 2 (STANDARD fill adjudication): the gate is now computable and it FAILS on every arm.**

- 90 evaluable question legs = 21.1% of the 426-leg post-corpus class, **73.2% of the adjudicable** set
- tol-0 (booked price exactly): 35.6% reachable, ROI +74.7% (n=32) → **FAIL** vs ≥60%
- tick-aligned: 51.1% → FAIL · +1¢ pay-up: 80.0%, ROI +27.1% → **PASS on reachability only**
- every arm's profit is 3 legs (ex-top-3 negative in all six arms)
- live-regime class, whole class not just stamped: **+$128.06 on $7,635.78 = +1.7%**

**Item 3 ($100 clip cap): still unbuilt, 13 days after approval.** RuleSet v73 `rulesJson` has no
`c200BandClipCaps` key and `grep -rn c200BandClipCaps src/` returns nothing — the field has no reader.

**Item 4 (ML re-point): unchanged.** `scripts/fit-fill-model.py` is archive-only (last touched 10-11);
no fill/adverse-selection target on live data.

**Item 5 (LIP): re-read, still zero — see below.**

## 3. Research (external claims cited)

**Polymarket** — `docs.polymarket.com/changelog.md`, read 2026-11-24: latest entry **Nov 20, 2026**
(DeFi fee/rebate change: taker coefficients 0.01/0.05, geopolitics free; maker rebates move to volume
tiers 0–15%; makers still pay no platform fee). **Nothing new since Nov 20.** The **Nov 11** CLOB
deprecations take effect **Dec 14**: `associate_trades` removed, `/data/orders` requires `market` with
`asset_id`, `/orders` loses `asset_id`/`token_id` filters. Checked our code: none of the three is used
(`grep` clean) — non-event for this stack.

**Kalshi** — `docs.kalshi.com/changelog.md`, read 2026-11-24: entries dated **Nov 26** (on-request
concert/weather/flight market limits, `side` now validated on create/amend, `GET /historical/fills`
accepts 100 tickers) and **Nov 19** (new `GET /incentive_schedules`; `GET /incentive_programs` gains
`series_ticker`/`event_ticker` filters). **No fee change; maker fee stays 0 on standard series.**

**LIP gate (Kalshi), `scripts/lip-ledger.py --fetch --schedules`, run 2026-11-24:**

- live menu (active+upcoming): **8,559 programs, 0 above $0.0131/contract-hour**, max live ceiling
  **$0.002976** → **4.4× below the gate** (was 7,608 / max $0.00446 on 11-17: the ceiling *fell*)
- whole feed: 233,687 usable programs; the 75,079 "above gate" are the ≤2h historic families
  (74,142 of the 91,252 ≤2h rows) — none of them live
- measured ledger: net of adverse drift **+$0.0000881/contract-hour** on 24,194 counted hours;
  best measured program ceiling $0.001120 → 11.7× below gate at 100% share → **DECISION: CLOSE**
- **new (section E):** 652 recurring schedules, **0 above gate**, best **$0.002976/ch** (KXONIONACT,
  7d, $1,000 pool) = 4.4× below; window mix 1d:15, 7d:507, 14d:130; **no window ≤2h exists in the feed**
- cross-check that the schedule scale is per market, not per event: 568/650 series match the live
  program ceiling within 25%, top four at ratio **1.00** (KXEOWEEK $0.002083 both). My first pass read
  the schedule as an event pool and "found" a 100× reopening — the cross-check refuted it. Zero
  series cross the gate in either reading.

**arXiv q-fin.TR, 2026-11-24 feed (`rss.arxiv.org/rss/q-fin.TR`; the API returned 429):**

- **2611.27988** — copy-trading blow-up early warning, Hyperliquid, 37,895 addresses → 2,621 blow-ups:
  behavioral drift leads equity in **9%** of cases, median lead **−8 days**, detector AUC **0.49** at 2%
  recall. *Transfer review:* perps with leverage/liquidation, on-chain fills, "master-worth-copying"
  filter — not our population (binary markets, no liquidation, 0-fee maker). What transfers is one
  narrow prior: **conduct features do not lead the damage; a drawdown stop fires as early**. That
  argues against buying wallet-behaviour features (ml-u2) and for the existing 20% drawdown gate.
  Hypothesis, not an import.
- **2611.29576** — Polymarket network structure, 1.14B transactions, 3.1M wallets: 1% of wallets =
  79.2% of financial participation, 1% of events = 64% of volume. *Transfer review:* participation
  shares, no PnL, no fills → describes our flow's concentration, says nothing about whether the
  concentrated wallets are right. Change detection only.

**Forums:** r/Polymarket and r/Kalshi Atom feeds returned **429 / empty** this run — no community
change-detection signal today. Stated as a gap, not as "no news".

## 4. Ranking

**1 — Ship the clip cap (approved, unbuilt 13 days).** Only change in the book with a CI-clean delta:
+$31.74/day at $10 on the 2–24h Kelly scope (booked), CI-clean on all three fill bases; the approved
$25 band-scoped level is the weaker arm. *Refuted by:* the forward 40-leg $100 sample earning ≥ the
sub-$40 tiers — currently 9 of 40 legs, −$47.77, one win.

**2 — Do not convert entry to maker (item 1). Refutation is firing.** 0/32 legs booked at the mid
were ever reachable; of the 58 that paid a median 1.5¢ above it, 32 filled and those 32 are the
profitable ones. The maker thesis needs a *different* population than the one we trade, and the shadow
writer still does not exist. *Refuted by:* a mid-rested shadow cohort reaching 200 legs at non-negative
ROI vs the crossed cohort — at a 0% mid fill rate it cannot reach 200 legs.

**3 — Scale the mid-band clip, as a shadow (new).** 0.40–0.80 filled: n=138, +14.7%, ex-top-3
positive, at $3.78/leg — the only positive filled cell with real n, and the sizer starves it while
$100 clips go to the 0.05–0.19 band. *Measurement:* shadow-rest the same signals at $25 on the 0.4–0.8
band using the existing L2 top-25 ladder (size-aware fill, not min-ask). *Decision rule:* ship if
fill-rate ≥ 50% and ROI > 0 on ≥100 legs with a CI excluding zero. *Refuted by:* fill-rate < 50% at
$25 (depth does not absorb the size) — in which case the mid-band edge is not scalable and stays a
$3.78/leg curiosity.

**4 — Write off the question class as booked, not as traded.** Item 2's rule returns FAIL, and the
consequence on the approved path is a write-off: published all-time PnL falls **+$7,319 → +$1,107**
(question +$6,212 → $0). It costs no live edge — the post-corpus question class is +1.7% — and it
changes no dispatch, so it is a reporting decision. *Refuted by:* the adjudicated class reaching
≥60% at non-negative ROI later, which reverses the write-off.

**5 — Nothing on LIP, nothing on ML.** 0 of 8,559 live programs and 0 of 652 schedules clear the
gate; the ML lane has no live fill target. No work is justified.

## 5. What I did not do, and why

- No new predictor. The one positive cell (0.4–0.8) is a sizing question, and its test is a shadow,
  not a model.
- No repair to the STANDARD path's missing `intentPrice`/`FillIntent` rows. I checked before filing
  it as a defect: STANDARD applies **no** maker credit (`CreditMode "none"`), so its booked price
  *is* the price it was handed and the stamp is correct. Filing it would have been manufactured work.

## 6. Lane B / instrument change committed today

`scripts/lip-ledger.py --schedules` (read-only, no rule and no risk touched): reads the new
`GET /incentive_schedules`, scores each schedule per market, and cross-checks it against the live
program ceiling it describes. Without the cross-check the schedule's scale is ambiguous and a
100× error is invisible (I made exactly that error on the first pass). Revert:
`git revert <commit>` — removes a read, changes no data.

**Negative result:** no new rule is justified today. The measurement that would unlock one is the
30-day mid-rested shadow (item 1), which has no writer, day 7 of 30.
