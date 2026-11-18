# Profit review — the entry question is closed, and the only money left is in the exit

**Date:** 2026-11-18 · **Lane A throughout** — nothing applied, no RuleSet write, no prisma write, DB `mode=ro`
**Instrument:** `scripts/profit-taker-entry.py` (committed with this doc; every figure below re-runs from it)

Basis, stated once and used everywhere: regime = `DecisionJournal.ruleSetVersion >= 68`
(2026-10-27..2026-11-17, **21.1 days**, 449 settled intents, $9,788 of intent cost, deduped to the
first leg per `bot|wallet|market|outcome`); cost = `PaperTrade.simulatedPositionSize` = **dollars at
risk**; CIs are market-clustered bootstraps (2,000 draws); entry prices are the **quoted book at
dispatch** (`MarketSnapshot.bestBid/bestAsk`, snapshot age median **11s**, p90 17s, and its mid
agrees with the venue tape's mid to 0.00c median) re-mapped to the side the leg is actually on.

---

## The question I asked, and the answer I got

Yesterday established *what we own*. Today prices the thing that decides whether the book can be
scaled at all: **is there an entry mechanism at which this signal pays?** Three prices, one exit —
our resting bid, the market's own mid, and the quoted ask a taker must pay to be certain of the fill.

| arm (per intent-dollar) | legs | intent $ | PnL | EV | $/day |
|---|---|---|---|---|---|
| maker — ours, at our bid | 249 | $4,938 | −$600.2 | −12.2% owned / **−6.1% per intent $** | −28.40 |
| taker — every intent at the ask | 449 | $9,788 | −$667.7 | **−6.8%** | −31.60 |
| taker + 1c of slippage | 449 | $9,788 | −$1,026.6 | **−10.5%** | −48.58 |

Both negative. The taker is 0.7pp *worse* per intent-dollar and 2.2pp worse once it pays a cent of
slippage. **Crossing the spread does not solve the fill problem; it converts a losing maker book into
a losing taker book that fills every time.**

The depth ladder says the same thing from the other side — and this is the part nobody had measured:

| posted depth under the mid | fill rate (60m) | ROI on fills | EV per intent |
|---|---|---|---|
| at the mid | 92.9% | −2.9% | −2.7% |
| 0.5c | 48.6% | −4.4% | −2.1% |
| 1c | 37.9% | −7.0% | −2.6% |
| 2c | 24.1% | −0.7% | **−0.2%** |
| 3c | 17.8% | −1.1% | −0.2% |
| 5c | 12.0% | −53.5% | −6.4% |
| 8c | 8.5% | −60.5% | −5.1% |

The maker's efficiency frontier peaks at break-even (2–3c deep, 18–24% fill) and collapses below it at
5c+ because the only legs that trade 5c through us are the ones where the market knew something. **No
posting depth pays, no crossing pays.** The mechanism is not the problem.

## Why the book loses: the fills are the bad half

- We are filled **71.7%** of the time within the hour — this was never a book that "couldn't get in".
- The 249 legs we own return **−12.2%** at our own bid; ex-top-1 **−23.8%**.
- The 200 rows we never owned (`fillStatus=unfilled`, $4,850) would have returned **+16.4%** at the
  same prices, valued at their **real settlement prices** (`currentPrice` = 0/1 on resolved rows —
  not the phantom marks of the 2026-11-17 read, and not the ledger's zero, which is a booking
  convention).
- The ledger's published −$256.9 (−2.6%) is the sum of those two: +$343.3 of PnL still sitting on
  rows the resolver stamped unfilled, against −$600.2 on the rows we actually hold.

And the fill *timing* is the tell. Same signal, sorted by how fast the fill arrived:

| time from dispatch to touch | legs | ROI at our bid |
|---|---|---|
| ≤60s | 160 | −17.2% |
| 1–5m | 23 | −35.0% |
| 5–30m | 38 | −39.6% |
| >30m | 18 | **+58.9%** |
| no touch stamp | 10 | +20.8% |

A bid that fills *immediately* fills because the market is coming through us. A bid that fills after
half an hour fills because the market came back. The book's entire positive side lives in the slow
fills, and it is 18 legs.

## Where the money actually is, and why I am not betting the book on it

One cell has a CI that excludes zero at the price a taker pays:

**band 0.80–1.01 — 26 positions, $814, +15.4% at the ask, CI [+12.9,+17.7], ex-top-3 +13.8%,
26 of 26 legs positive, every one provenance-`consistent` (|booked − wallet fill| ≤ 1.5c), breakeven
premium +14.1c against a median ask−bid premium of 0.96c.** It is the only cell in the book where a
high fill rate (91.4%) and a positive edge coexist — the exact inverse of everywhere else.

It still does not clear its own bar — and the way it fails is instructive. The 26 legs are **19
distinct market bets** (both lanes hold several of the same markets). A 95% one-sided binomial lower
bound on **19/19 is 85.41%**, against a **cost-weighted breakeven price of 85.62%**: it fails by
0.2pp. Scored on legs instead of bets, the same test reads 89.12% and *passes* — the 4pp gap between
those two numbers is the correlation, and that is the whole reason the cell is a lead rather than an
edge. The post-repair half of the band has **fewer than 5 legs**, so the entire cell is pre-2026-11-11
vintage, and the `profit-c200-price-frame-sizing` census is right that this is where the suspect $100
bookings used to live.

## The ladder arithmetic, on this basis

$463.9/day of notional at −6.1% per intent-dollar is **−$28/day**. For $250/day you need a positive
rate; the best measured positive rate on any material cell is the favourite band's taker arm at
+14.0%, which needs **$1,782/day of notional** in that band — the band does **$77.5/day**. That is 23x
in the only cell that pays, against a measured-exhausted gate surface. The rung is not a scaling
problem.

## Contradictions reported rather than resolved

1. **The cheap band's record is a booking, not an edge.** 0.00–0.20 is **45.3% of intent notional at
   −15.4% EV per intent-dollar** (−$684, against +$84 for the rest of the book). Its *booked* record
   is +40.7% on 316 legs; its **reachable** record is **−20.0% on 132 legs** pre-repair and **−35.4%
   on 43 positions** in the live regime. The `+48.7%` on 65 cheap legs above $25 that sized the C-200
   cheap clip is a booking artifact of the same class. Against that: `profit-cheap-refusal-ask-price`
   measures +13.9pp of calibration edge on 189 refused candidates at the mid, and the long-shot shadow
   reads +81.7% on 113 resolved would-admits. **Both are true**: the cheap tail has a positive
   calibration edge at the mid and a negative realised result at any price we can pay. I am not
   proposing a change to it and I am not signing off a cap raise on the booked number.
2. **The "0.8–1.0 is destroyed" premise (baseline f* −101.3%, 1,172 legs) does not reproduce in the
   regime.** On repaired rows, v49+ since 2026-09-01: 55 legs booked **+6.4%** CI [−0.1,+11.5], 41
   reachable **+9.0%** CI [−2.5,+16.7], **0% of them complement-class** (the defect the 2026-11-11
   repair removed). The 1,172-leg figure is off-regime and pre-repair. I am not acting on it either —
   the post-repair band has no sample — but the premise should stop being quoted as a reason to
   suppress favourites.
3. **The venue tape is a midpoint series, not executed prints.** On markets quoted with a 1c spread,
   **89.8% of 16,675 tape points sit exactly at the half-cent the midpoint must sit at** (7.8% at the
   whole cent; the bid/ask edges are noise). So `profit-fill-tape.py`'s model statement ("a print at or
   below our resting bid") was wrong: the measured object is *the midpoint reaching our bid*, which is
   a weaker fill proof pointing the same direction. Yesterday's 98.3% / 29.3% agreement figures
   measure midpoint-crossing, not trades. Repaired in the same commit — docstring corrected and §1b
   now measures the half-cent share on every run; no verdict logic changed.

## Recommendations, ranked by expected value

### R1 — A fast adverse stop on the owned class. **+$630 / 21 days in-sample, the only positive-dollar lever in the book.**

- **Hypothesis.** At least half of the owned class's −12.2% accrues in the first 30 minutes after the
  fill, so exiting when the marked bid is ≥8% below the fill, checked at +5m, keeps ≥$300 of the $600
  the book loses per 21 days.
- **Measurement.** `scripts/profit-taker-entry.py` §S10: for the 249 owned legs with tape, the
  leg-side bid (mid − half the quoted spread) at +5/+15/+30/+60m, re-priced against the leg's own
  realized exit, over a 4×4 threshold grid, with an ex-top-3 cut and a per-lane split. Data:
  `PaperTrade`, `MarketSnapshot` within ±5m of dispatch, cached venue tape.
- **Measured.** 5m / ≥8%: PnL **+$30.0 (+0.6%)** vs hold **−$600.2 (−12.2%)** = **+$630.1**; 29 legs
  stopped (11.6%); ex-top-3 **+$375.9**; C-200 +$556.6 (23 stopped) and STANDARD +$73.5 (6) — it does
  not eat the one profitable lane. **12 of 16 grid cells positive**; all four 60m cells negative, so
  the horizon matters and the stop must be fast.
- **Decision rule.** Ship write-only now (a `*/5` mark loop against `MarketSnapshot` + a RuleSet field
  defaulted `0` = off). Apply when **150 forward owned legs** give delta ≥ **+$150** with a
  market-clustered CI excluding zero, trigger rate ≤ 25%, and ex-top-3 delta > 0.
- **Refutation.** Forward delta ≤ 0 at 150 legs; or trigger rate > 40% (firing on noise); or ex-top-3
  delta ≤ 0 (three legs, i.e. a tail cut dressed as a rule); or the +5m mark is already below the fill
  on the large majority of eventual losers — which would mean the damage is instantaneous and the
  "stop" is only re-pricing at t+5 with nothing left to save.
- **Effect.** +$630 per 21 days ≈ **+$30/day**; the owned class goes from −12.2% to ≈ +0.6%. **Cost 3h**
  (the mark loop is the work; the existing PnL job runs hourly and an hourly tick cannot capture this
  — every 60m cell in the grid is negative).

### R2 — The favourite band is the only cell where fills and edge move together; price it, don't ship it.

- **Hypothesis.** In 0.80–1.01 the fill filter *hurts* rather than helps (91.4% touch, taker EV +14.0%
  vs maker +8.2% per intent-dollar), so the one place where the mechanism question has a positive
  answer is being suppressed by a premise that no longer reproduces.
- **Measurement.** Same instrument, §S4(b) (every intent at the ask), §S5 (maker vs taker EV per
  intent-dollar), §S4b (ex-top-3, provenance class, sub-bands, per-leg), and the binomial bound on
  distinct bets vs the weighted breakeven price.
- **Decision rule.** Propose a band-scoped sizing uplift only at **150 settled favourite intents** with
  taker EV ≥ **+5%**, ex-top-3 ≥ **+5%**, and the binomial 95% lower bound on the hit rate above the
  weighted breakeven. Today: 35 intents, 26 positions, 19 distinct bets — 85.41% vs a 85.62%
  breakeven, not met.
- **Refutation.** At 150 intents the binomial lower bound stays below breakeven, or taker EV ≤ 0 →
  the cell is 19 correlated wins and the current suppression is correct.
- **Effect.** At +14.0%, $250/day needs **$1,782/day** of notional in this band against $77.5/day
  today. Even if it clears, it is a 23x flow problem, not a rung. **Cost 2h** to wire the shadow print.

### R3 — Record the entry question as closed, and repair the tape's model statement. **$0 direct; it protects the two numbers above.**

- **Hypothesis.** Every future review that re-opens "cross the spread to fix fills" will spend a day
  and land on the same answer, because the taker arm is now measured at −6.8% and the depth ladder is
  negative at all seven depths.
- **Measurement.** §S2, §S5, §S11 of the committed instrument; §S1b plus the half-cent diagnostic for
  the tape basis (this commit's Lane B change to `scripts/profit-fill-tape.py`).
- **Decision rule.** Close `paid-up-entry-cohort`'s mechanism half (its aim — don't pay up — is
  confirmed; the branch "or cross instead" is refuted), and quote the tape as a midpoint series
  wherever "touch" is used as fill evidence.
- **Refutation.** A forward 150-leg cohort of taker entries at the ask returning ≥ +5% with a CI
  excluding zero, or a depth of 2–8c producing positive EV per intent on a forward sample →
  re-open.
- **Effect.** $0; it stops a measured dead end from being re-derived. **Cost 0.5h.**

**Not recommending:** any gate change (measured exhausted), any band cut, any lane reallocation. The
lane split looks strong — C-200 maker −9.9% per intent-dollar vs STANDARD +14.9%, difference at the
ask **+38.7pp CI [+7.5,+67.9]** — but STANDARD's own ex-top-3 is **−2.8%**: three legs carry the entire
lane difference, and a reallocation on three legs is a coin flip with extra steps.

**IF YOU WEREN'T HERE:** stop out at −8% within five minutes of a fill. It is the only line in the
book that turns a −12.2% class into roughly flat, it helps both lanes, and — unlike every other
proposal here — it does not require the copy signal to be right.

---

## Self-checks printed by the instrument (all PASS)

mapped book ordered bid ≤ mid ≤ ask 449/449 · booked entry at or below the ask 448/449 · re-pricing at
the booked price reproduces `realizedPnl` to $0.0000 on unmasked rows · snapshot mid within 2c of the
tape mid on 90.9% of legs · side map 193 own / 256 complement (expected on named-outcome markets) ·
`--selftest` covers the re-pricing identity, the side map in all three cases, and the ambiguity refusal.

## Reproduce

```
python3 scripts/profit-taker-entry.py            # ~35s warm, cached tape
python3 scripts/profit-taker-entry.py --selftest
python3 scripts/profit-taker-entry.py --snap-window=60
```
