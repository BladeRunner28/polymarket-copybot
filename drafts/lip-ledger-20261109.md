# The Kalshi LIP reward leg is 137x below the gate, and adverse selection is not what kills it

**Card:** `lip-ledger-kalshi-reward` (approved 2026-11-09, hard gate 2026-11-24) · **Lane B measurement**
**Instrument:** `scripts/lip-ledger.py` · **Artifacts:** `data/lip-ledger.json`, `data/kalshi-lip-programs.jsonl.gz`
**Served at:** `http://localhost:3013/drafts/lip-ledger-20261109`

---

## 1. Answer

**CLOSE.** Over **17,405 counted program-hours** (the rule asks for ≥ 50) the measured leg pays
**$0.000096 per contract-hour net of adverse selection** against a gate of **$0.0131** — **1/137th** of it.
Reward alone is $0.000195/contract-hour — 1/67th of the gate. The best program we can measure has a
**structural ceiling of $0.001120**, so it cannot clear the gate even if we took **100% of the reward pool**
with no competition and no adverse selection at all.

The hypothesis was that the reward leg is profitable gross and adverse selection is the whole question.
The measured answer is the opposite in the first half and confirmed in the second:

| Arm | $/contract-hour | vs gate $0.0131 |
|---|---|---|
| Reward only (gross) | +0.000195 | **1/67** |
| Reward + adverse drift (the card's rule) | **+0.000096** | **1/137** |
| Reward + drift + half-spread capture (a full market-making leg) | +0.000150 | 1/87 |
| Best measured program's ceiling (100% share, free) | 0.001120 | 1/12 |

Adverse selection is real and it is large — it eats **187% of the half-spread** on the fills we would take
(§5) — but the leg never reaches the question, because the reward on the markets we can see is two orders
of magnitude too small.

**The gate is not a measurement of this leg. It is a measurement of program selection**, and the programs
that clear it are in families we have never captured (§4). That is the finding worth acting on.

---

## 2. What was actually built

`scripts/lip-ledger.py` (rewritten from the crashed attempt; 6 defects fixed, §7) produces three measurements
in order of decisiveness:

**A. Structural ceiling — `pool / (2 · target · hours)`.** A hard upper bound on gross reward per
contract-hour for every program in the feed: a sole participant's snapshot score tops out at 1.0 per side, so
their share is 1, reward = pool, and contract-hours = 2 · target · hours. Resting *less* than target does not
raise it (the qualifying walk stops at Target Size, so reward/contract-hour stays `pool/(total·hours)`). This
needs no book data, so it decides eligibility for all 229,636 programs.

**B. Measured ledger.** For programs where we hold book snapshots: our normalized share per snapshot, valued
at the program's own rate, with counted hours = **observed** snapshots, never the window's calendar duration.

**C. Adverse selection.** Every taker print inside a program window fills the resting bid on the opposite
side. Booked **separately** as
`capture = fair_before − fill_px` (the half-spread a maker earns) and
`drift = fair_after − fair_before` (the move after the fill; negative = adverse). The crashed draft reported
`mid_after − fill_px` under the name "adverse selection"; that quantity *contains* the half-spread, so a
genuinely adverse book could read as a gain (it did: the first run printed adverse selection **as a $33.86
profit**).

### The unit is the one number that decides the verdict, and it is pinned twice

`period_reward` is **centi-cents**, verified at the primary source rather than inferred:

1. **Kalshi's own OpenAPI** (`docs.kalshi.com/openapi.yaml`, `IncentiveProgram.period_reward`): *"Total
   reward for the period in **centi-cents**"* — the same unit as `max_reward_per_account`.
2. **Kalshi's filed LIP terms** cap the reward at *"no greater than $1,000 per calendar day"* per market.
   Read as **cents**, **95.4%** of the 93,447 programs that span ≥24h would be illegal; read as
   **centi-cents**, **0.0%** are. The modal reward of 1,000,000 is $100/day, not $10,000/day.

This matters because it flips the answer: at the cents reading the same ledger prints **$0.0194/contract-hour
→ KEEP** (`data/lip-ledger-cents-arm.json`). The sensitivity arm is kept in the artifact precisely so a
future reader can see how much the verdict rests on the unit, and the base arm is the verified one.

---

## 3. The feed: where the reward is, and what shape it has

231,158 programs paged to a 2026-03-12 → 2026-11-30 span (the previous fetcher kept 4,000 — see §7.1).
229,636 are usable liquidity programs; the $16.07M of pool is distributed so that **36.8% of programs can
clear the gate on ceiling alone**, and they carry **20.4% of the money**.

| Window length | Programs | Median ceiling | ≥ gate |
|---|---|---|---|
| ≤ 2h | 100,690 | $0.0400 | **83.0%** |
| 2–8h | 2,519 | $0.0096 | 35.0% |
| 8–24h | 52,536 | $0.0031 | 0.2% |
| 24–48h | 27,845 | $0.0007 | 0.1% |
| > 48h | 46,046 | $0.0003 | **0.0%** |

**Every program longer than two days fails the ceiling test, without exception.** The gate is reachable only
on short windows: a fixed pool spread over a shorter period is simply a higher rate per contract-hour.

Above-gate programs concentrate in a dozen families, none of them macro:

`KXCRYPTOLEAD15M` 24,148 · `KXTTELITEMATCH` 15,342 · `KXTEMPMIAH` 10,606 · `KXLIGAPROMATCH` 3,873 ·
`KXNATGAS15M` 3,661 · `KXCOPPER15M` 3,465 · `KXPLATINUM15M` 2,528 · `KXPALLADIUM15M` 2,527 ·
`KXEURUSD15M`/`KXGBPUSD15M`/`KXUSDJPY15M` 2,279 each · `KXTTSTARMATCH` 2,130

These are 15-minute crypto/commodity/FX lead-lag markets, hourly weather brackets and table-tennis/soccer
match markets. `KXTEMPMIAH` alone carried **$289,500** of pool in the 28 days our tape covers.

---

## 4. The capture problem: zero overlap between what pays and what we record

This is the structural finding of the card.

| Capture | Programs in it | Above gate |
|---|---|---|
| Quote universe (`data/kalshi-macro-quotes.jsonl`, 338 tickers) | 473 | **0** — best ceiling $0.001120 |
| Print tape (`data/kalshi-tape-families.json`, 13 families) | 533 (KXCPI 323, KXFED 150, KXHIGHNY 60) | **0** |

And 7 of the 13 tape families have **never had a liquidity incentive program at all** — KXBTC15M,
KXETH15M, KXBTCD, KXNFLGAME, KXNBAGAME, KXMLBGAME and KXWTI return **zero** rows in 231,158 programs. They
are the venue's volume leaders (`KXBTC15M` alone is 13.1M of the tape's ~18.9M prints) and Kalshi does not pay
LIP on any of them.

So the tape whitelist and the reward schedule are almost disjoint by construction. The macro universe we
quote is the *wrong* universe for this leg: its programs are 24h/168h windows paying $0.0003/contract-hour.
The families that can pay $0.0131+ are the ones our capture has never touched.

---

## 5. Measured ledger (KXCPI — the only quote+tape overlap)

166 programs, 17,405 counted hours, 34.8M contract-hours, resting 1,000 contracts a side.

| | value |
|---|---|
| Reward payout | $6,799.54 |
| Counted hours (observed, surviving) | 17,405 (gate ≥ 50 → met) |
| Contract-hours | 34.81M |
| Gross | **+$0.000195 / contract-hour** |
| Adverse drift | −$3,460.38 |
| Net of adverse drift | **+$0.000096 / contract-hour** |
| Half-spread capture | +$1,867.87 |
| Net incl. capture | +$0.000150 / contract-hour |
| Fills taken | 547 — 132,336 contracts |

**Adverse selection, decomposed** (547 fills, 132,336 contracts):

| | per contract |
|---|---|
| Half-spread captured at the fill | +$0.0141 |
| Mid drift after the fill (our side) | **−$0.0264** |
| Net mark-out | **−$0.0123** |

Drift is negative on both sides (YES-side bids −$0.0338, NO-side bids −$0.0193): whichever side we rest,
the book moves against the position after we are filled. **Adverse selection is 1.87x the half-spread** —
a maker resting on these books is not paid to provide liquidity, it is charged for it. That is the card's
hypothesis confirmed on the only population we can test it on.

Two honest limits: the quote file is top-of-book only, so survivor fractions are a **lower** bound (deeper
levels could qualify a snapshot we mark excluded; median observed top-level adequacy is 9%), and hourly
snapshots make "drift" a 1–2.5h move rather than a seconds-scale one. Both push the measured reward *down*
and the drift *towards* zero; neither is worth 67x.

---

## 6. Decision rule, applied

Pre-registered: `>= $0.0131/contract-hour NET of adverse selection over >= 50 counted program-hours by
2026-11-24 => keep the reward leg; ELSE close it.`

* counted program-hours: **17,405** → hours condition **met**
* net of adverse selection: **$0.000096** → rate condition **failed by 137x**
* ceiling of the best measured program: **$0.001120** → the failure is **structural**, not sampling

**→ CLOSE the LIP reward leg as scoped.**

What would refute this: a capture of the above-gate families showing ≥ $0.0131 net over ≥ 50 counted hours.
Nothing in the current capture can produce that number, because none of those families is in it.

---

## 7. Instrument defects fixed (Lane B)

The crashed attempt left a 454-line script whose *conclusion* (CLOSE) happened to be right for six wrong
reasons. Each is now fixed and each fix is visible in the output:

1. **Feed truncated at 1,000 rows per status.** `?limit=1000` returns `next_cursor`; ignoring it kept 4,000
   of 231,158 programs and reached back ~12 days instead of 2026-03-12 — i.e. it computed the above-gate base
   rate on exactly the week where short-window programs cluster. `--fetch` now pages to exhaustion and the
   `stats` block records `exhausted` per status.
2. **`target_size_fp` is nullable.** 33 rows lack it; the old loader called `float(...)` and died. Now
   counted and skipped, with every drop reason printed.
3. **Payout valued over the whole window from partial observation.** A 168-hour program observed 12 times
   was paid the *full* $100 pool against 12 hours of contract-time, printing $0.0041/contract-hour against
   its own $0.0003 ceiling — a 14x overstatement. Payout is now scaled by counted coverage, and the
   invariant `gross ≤ ceiling` is checked (max ratio in the artifact: 0.995, zero violations).
4. **`--unit` moved the ceiling but not the payout.** The sensitivity arm printed *identical* numbers to the
   base case. Now both move (and at `cents` the verdict flips to KEEP, which is why the unit is pinned twice).
5. **Sign error + wrong definition of adverse selection.** `net = payout − drift_usd` with a negative drift
   *added* the loss; and `mid_after − fill_px` was labelled adverse selection although it contains the
   half-spread. Capture and drift are now separate series, and net = payout **+** drift.
6. **Fill volume uncapped.** Every taker print was booked as ours, filling 885,717 contracts against
   1,000-contract resting orders. Fills are now capped per side at the resting size.

Reproduce: `python3 scripts/lip-ledger.py --fetch && python3 scripts/lip-ledger.py` (add `--unit cents`,
`--placement join`, `--size N` for the sensitivity arms). Read-only; nothing here touches the DB or a live path.

---

## 8. Recommendation

**Close it as scoped, and do not re-read it on 2026-11-24** — there is nothing left to learn from this
population; the ceiling says so arithmetically.

**If the reward leg is worth pursuing, it is a different build, and it is cheap to test.** Two options:

**A. Close and stop** *(recommended if Kalshi LIP is not a strategic lane)* — the measured leg loses by 137x,
the capture would need new families, and the reward is capped at $1,000/market/day by Kalshi's own filing.

**B. Capture the families that can pay, then re-read with this same script** — add
`KXTEMPMIAH`, `KXCRYPTOLEAD15M` and `KXLIGAPROMATCH` to `data/kalshi-tape-families.json`, run for 14 days,
re-run `lip-ledger.py` unchanged. Those three carry $441,200 of pool per 28 days and 38,627 above-gate
programs in the full feed. Cost is disk plus a whitelist edit (the current 13-family tape is 539MB per 28
days; these families print far less than `KXBTC15M`). **This is the only path that can reverse today's
verdict**, and the refutation is pre-registered above.

**Not recommended:** loosening the gate, or re-basing it on gross. Either would convert a structural loss
into a permission — and a reward of $0.0002/contract-hour does not become $0.0131 by changing the denominator.

---

*Read 2026-11-09. Feed snapshot `fetched_at=2026-11-09T17:47:56Z` (paged, 231,158 rows). Adverse-selection
window 2026-10-12 → 2026-11-09 (quote tape) and 2026-10-12 → 2026-11-08 (print tape). All figures regenerate
from `scripts/lip-ledger.py`; the headline is reproduced independently in the verification pass logged on the
card.*
