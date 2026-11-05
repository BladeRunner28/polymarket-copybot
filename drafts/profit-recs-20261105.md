# Profit review — 2026-11-05

**Instrument:** `scripts/profit-throttle-read.py` (committed with this file, read-only,
`prisma/dev.db?mode=ro`). Reproduce with `python3 scripts/profit-throttle-read.py`;
`--self-test` asserts the notional-weighted payoff identity per band and exits 1 if it breaks.

Population: regime only (`ruleSetVersion >= 49`), **1,863 bets / $25,036 at risk / +$9,180.11 /
+36.7% [booked] / 59.6 days / $153.98 a day**. Bet = first leg per (bot|wallet|market|outcome).
**Cost basis on every ROI line is `simulatedPositionSize` = dollars at risk** — never shares, never
multiplied by price. Three bases, never mixed:

- **[booked]** `status IN (closed,resolved)` — what the ledger books.
- **[resolved]** `status='resolved'` only — PnL>0 iff the token won, so the hit-rate test is exact.
- **[$/1k-cd]** booked PnL per $1,000 of realised capital-days (`size × hold ÷ 1000`): profit per
  unit of capital per unit of *time*.

---

## 0. The verdict in five lines

1. Capital is not the constraint: **$867 average in flight against a $5,064 cap (17.1%)**, earning
   **$177.6 per $1k-capital-day**. Edge and capital are both fine. **Size is the constraint.**
2. Two ceilings pinch exactly where the edge is: **66.2% of the main lane's cheap legs sit on the
   $100 Kelly clamp**, and **82.2% of the short-TTR lane's cheap legs sit on the legacy $20 lane
   ceiling** — in a cell that yields **$535.5/$1k-cd, the best in the book**.
3. The obvious lever — the band factor — is **mostly a no-op behind a binding clamp**: band factor
   ×1.5 books **+$2,016**; raising the clamp itself books **+$4,590**. Same multiplier, 2.3x the money.
4. **Our size is inverted across lanes.** In 0.40–0.60 the short-TTR lane's legs beat their price by
   **+8.2pp (z=+2.9)** and get **$1.9** a leg; the STANDARD lane's legs are **−3.6pp** and get
   **$18.0**. Same band, same market prices, opposite edges, 9.5x the size on the wrong one. That is
   the cleanest statement of the book's sizing defect I have been able to measure.
5. Two ceilings move; no gate, no band factor, no exit changes.

---

## 1. Where the capital-time goes — and where the profit comes from

| band | n | notional | booked | ROI [booked] | settled n | hit% | price | edge | z | hit$w | edge$w | cd share | $/1k-cd |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.00–0.20 | 278 | $9,849 | +$8,371.0 | **+85.0%** | 154 | 27.9 | 0.117 | **+16.2** | +4.5 | 26.4 | +14.8 | 40.9% | **$395.5** |
| 0.20–0.40 | 469 | $6,307 | +$1,190.2 | +18.9% | 334 | 39.5 | 0.310 | **+8.5** | +3.2 | 38.2 | +7.4 | 17.2% | $133.7 |
| 0.40–0.60 | 671 | $4,725 | −$363.0 | −7.7% | 503 | 53.5 | 0.499 | +3.6 | +1.6 | 48.6 | **−1.7** | 15.4% | **−$45.7** |
| 0.60–0.80 | 426 | $3,812 | +$4.8 | +0.1% | 288 | 73.6 | 0.686 | +5.1 | +1.9 | 69.6 | +1.1 | 21.5% | $0.4 |
| 0.80–1.00 | 19 | $344 | −$23.0 | −6.7% | 16 | 75.0 | 0.823 | −7.3 | −0.7 | 75.2 | −7.1 | 5.0% | −$8.9 |

**0.40–0.80 is 36.9% of the book's capital-days and $4.8 of $9,180 — 0.05% of the profit** (−$358
once 0.40–0.60 is included). The cheap band is 40.9% of capital-days and 91% of the profit, at 395
dollars per $1k-capital-day against the dead block's $0.4.

By lane:

| lane | bets | notional | booked | $/1k-cd | share of capital-time | share of PnL |
|---|---|---|---|---|---|---|
| main (C-200) | 174 | $8,315 | +$6,285.9 | **$431.9** | 28.2% | 68.5% |
| short-TTR | 1,112 | $6,693 | +$1,743.7 | $241.6 | 14.0% | 19.0% |
| STANDARD | 577 | $10,028 | +$1,150.5 | **$38.5** | **57.9%** | 12.5% |

STANDARD spends **57.9% of the book's capital-time for 12.5% of its PnL**, 11x worse per
capital-day than the main lane. Its open book — 382 legs, $4,121, **average age 94.8 days,
mark-to-market −$64.7** — is dead but honest: there is nothing left to recover, so no "release the
stranded legs" argument has dollars in it. It also isn't taking on new mid-band flow: **0 STANDARD
opens in 0.40–0.60 in the last 7 days**, 83.5% of its last-14-day opens below 0.40.

---

## 2. The inversion: which lane gets the size, and which one earns it

Lane × band settlement truth (resolved legs, leg-weighted):

| cell | n | hit% | price | edge | z | clip | booked ROI |
|---|---|---|---|---|---|---|---|
| main/0.00–0.20 | 29 | 31.0 | 0.118 | **+19.3** | +2.2 | $86.7 | +93.9% |
| main/0.20–0.40 | 72 | 40.3 | 0.298 | +10.5 | +1.8 | $21.0 | +23.3% |
| shttr/0.00–0.20 | 71 | 21.1 | 0.111 | **+10.0** | +2.1 | $18.6 | +59.0% |
| shttr/0.20–0.40 | 156 | 35.9 | 0.310 | +4.9 | +1.3 | $8.8 | +8.2% |
| **shttr/0.40–0.60** | 306 | 57.8 | 0.496 | **+8.2** | **+2.9** | **$1.9** | +5.1% |
| **shttr/0.60–0.80** | 157 | 79.6 | 0.687 | **+10.9** | **+3.4** | **$4.2** | +3.2% |
| std/0.00–0.20 | 54 | 35.2 | 0.125 | +22.7 | +3.5 | $16.4 | +93.7% |
| std/0.20–0.40 | 106 | 44.3 | 0.318 | +12.5 | +2.6 | $16.6 | +25.8% |
| **std/0.40–0.60** | 197 | 46.7 | 0.503 | **−3.6** | −1.0 | **$18.0** | −10.5% |
| **std/0.60–0.80** | 131 | 66.4 | 0.683 | **−1.9** | −0.5 | **$17.5** | −1.2% |

Read the two middle rows against the two bottom rows. **Every short-TTR cell has a positive
settlement edge, including the mid bands everyone has written off, and every one of them is sized at
$1.9–$18.6. STANDARD's two mid cells are the only negative cells in the table and they are sized at
$17.5–$18.0** — flat, because that lane has no band factor at all.

That is the same defect yesterday's draft found from the other direction (settlement edge and booked
result disagree because the stop intervenes), but the cause here is upstream of the exit: the size
never tracked the edge in the first place. In 0.40–0.60 the pooled dollar-weighted edge is −1.7pp
while the pooled leg-weighted edge is +3.6pp; the gap is not noise, it is STANDARD's $18 sitting on
a −3.6pp cell and the lane's $1.9 sitting on a +8.2pp one.

The book has already stopped opening the bad half of this (v63 band skip; 0 opens in 7 days), so
this is a *sizing* wound, not a flow wound. That is why the recommendations are ceilings, not gates.

---

## 3. What the clamps actually bind

Live RuleSet v71: `c200LongshotBandFactor 3.5`, `c200DeadZoneBandFactor 0.125`,
`shortTtrDeadZoneBandFactor 0.5`, `shortTtrPremiumBandFactor 2.0`, `kellyMaxSizeUsd 100`,
`maxGrossExposureUsd 1000`.

| lane/band | n | avg clip | at $100 | at $20 | median |
|---|---|---|---|---|---|
| main/0.00–0.20 | 71 | $86.7 | **66.2%** | 0.0% | $100 |
| main/0.20–0.40 | 103 | $21.0 | 2.9% | 1.0% | $18 |
| shttr/0.00–0.20 | 135 | $18.6 | 0.0% | **82.2%** | $20 |
| shttr/0.20–0.40 | 247 | $8.8 | 0.0% | 0.0% | $10 |
| shttr/0.40–0.60 | 456 | $1.9 | 0.0% | 0.0% | $1.2 |
| shttr/0.60–0.80 | 274 | $4.2 | 0.0% | 0.0% | $5 |
| std/* (all bands) | 577 | $16.4–18.1 | 0.0% | ≤10.9% | $18 |

**(a) The band factor is not the size lever; the clamp is.** Shadow, per leg
(`new = min(clamp_then, old × mult)`), in-sample, linear in size:

| change | booked delta over 59.6d | per day |
|---|---|---|
| band factor ×1.5, clamp held at $100 | +$2,016 | +$33.8 |
| **clamp $100 → $150**, band factors untouched | **+$4,590** | **+$77.0** |
| clamp $100 → $200 | +$9,180 | +$154.0 |
| lane ceiling $20 → $30, short-TTR only | +$872 | +$14.6 |
| lane ceiling $20 → $30, STANDARD only | +$575 | +$9.6 |

+$4,186 of the clamp change's +$4,590 lands in the cheap band, because that is the only place the
Kelly output exceeds $100. Raising `kellyMaxSizeUsd` is therefore *de facto* a single-cell change —
which is the argument for it, and the reason it is not a blanket "size everything up".

**(b) The clamp is not demonstrably picking winners.** Inside the true main lane's 0.05–0.20:
41 legs at the $100 clamp book **+125.3%**, 18 below it book **+103.1%** (avg price 0.108 vs 0.119).
n=18, confounded with price. So rec 1 is a **band-level** bet, not a conviction-weighted one. That
distinction matters for how it should be watched: the falsifier below is about fills and residual
edge, not about "the sizer's top legs".

---

## 4. What the fill absorbs, and what the exit costs

**Fillability, measured on our own book rather than modelled.** 9 of the cheap band's 154 resolved
legs book **exactly $0.00 on full notional** — `bookedPnl()` books an unfilled leg at zero. That is
5.8% of the band's resolved legs and **11.8pp of resolved ROI** (+135.6% on filled legs, +123.8%
including the zeros). 23 legs / $311 do the same in 0.20–0.40. The drag is already inside every
number in §1.

**Break-even slippage.** A YES bought at p needs hit > p, so a band can pay up to its own hit rate
before the edge is gone:

| band | hit% | price | cushion (cents) | cushion % | realised fill credit |
|---|---|---|---|---|---|
| 0.00–0.20 | 27.9 | 0.117 | **+16.2c** | +138% | +1.05c |
| 0.20–0.40 | 39.5 | 0.310 | +8.5c | +28% | +1.03c |
| 0.40–0.60 | 53.5 | 0.499 | +3.6c | +7% | +1.81c |
| 0.60–0.80 | 73.6 | 0.686 | +5.1c | +7% | +1.29c |
| 0.80–1.00 | 75.0 | 0.823 | −7.3c | −9% | 0.00c |

(fill credit = `intentPrice − entryPrice`, positive = filled *below* intent.) The cheap band has
**16.2 cents of margin against 1.05 cents of measured credit** — a 1.5x clip can worsen fills
fifteen-fold before the band goes negative. 0.40–0.60 has 3.6c of cushion against 1.81c of credit:
half its margin is already spent. On this axis the cheap band is not thin, whatever the books look
like at 5-second resolution; the mid bands are.

**The exit is unchanged and not re-litigated.** 0.40–0.60 books −7.7% against a resolved −3.3%
because its 168 stopped legs book −35.4% while the 503 resolved ones book −3.3%; 0.60–0.80 books
+0.1% against resolved +2.5% on the same split (138 stopped at −7.5%). Yesterday's hold-to-mark
counterfactual put holding the 0.60–0.80 stopped legs at −$16, so the stop is selecting genuinely
worse bets. Nothing here reopens the exit question.

**Drawdown, so the size change is priced honestly.** Worst 7-day run in the cheap band **−$701**,
max peak-to-trough **−$701** (−$550 in the main lane alone). At 1.5x: **−$1,052** on a $9,979 cash
balance, 10.5% of cash, against a book booking $154/day over its whole life and $543/day over the
last 8 settled days — where the two biggest days carry $2,466 of $4,344 (57%).

---

## 5. Recommendations, ranked by expected value

### 1 — LANE A (propose): raise `kellyMaxSizeUsd` 100 → 150. Cost: 0.5h.

**Hypothesis.** The $100 clamp — not the band factor, not the exposure cap — is what limits profit
in the only cell that pays, and raising it 1.5x raises the cheap band's PnL roughly 1.5x because
the band's settlement edge is +16.2pp and its fill cushion is 16.2 cents against 1.05 cents of
measured credit.

**Measurement.** `scripts/profit-throttle-read.py` §B–§F. Cheap band: 278 bets, $9,849, **+$8,371.0
[booked, +85.0%]**, leg edge **+16.2pp (z=+4.5)**, dollar edge +14.8pp, 40.9% of capital-days,
**$395.5/$1k-cd**; 66.2% of the main lane's cheap legs pinned at $100. Clamp-aware shadow:
**+$4,590 over 59.6 days (+$77.0/day)**, +$4,186 of it in the cheap band; in-flight $867 → ~$1,300
(17% → 26% of the $5,064 cap). Breadth: ex-top-5 **+13.7pp (z=+3.8)**, ex-top-10 **+9.6pp (z=+2.8)**;
time split **+13.7pp (z=+2.8)** early / **+18.7pp (z=+3.5)** late. Fill drag already included.

**Decision rule.** Ship if the band's ex-top-10 hit-rate edge is ≥ +5pp at z ≥ 2 (measured +9.6pp,
z=+2.8) **and** its realised edge is positive in both halves of its own history (measured +13.7 and
+18.7pp). Both hold → ship at **1.5x, not 2x**: past the top 20 markets the residual edge is +1.8pp
(z=+0.6), so 1.5x is the largest multiple the outside-the-tail flow can carry.

**Refutation.** Revert to $100 if **any** of: (a) on the next 100 settled cheap-band bets the
ex-top-10 hit rate falls below the band's entry price; (b) the unfilled-leg rate in the band rises
above **12%** of resolved legs (5.8% today) — that is the fill limit, and it is the honest way to
learn the books are thinner than the model; (c) 30 days after the change the band's PnL per
$1k-capital-day is below **1.15x** its pre-change value.

*Dependency:* this is downstream of yesterday's rec 1. If the approved −2SE Kelly cap on `main
<0.20` ships instead of being withdrawn, the cheap-band clip becomes $7.50 and this recommendation
is void, not merely inadvisable.

---

### 2 — LANE A (propose): raise the legacy $20 lane ceiling to $30 for the **short-TTR lane only**. Cost: 0.5h.

**Hypothesis.** The $20 ceiling predates the short-TTR lane; it now pins 82.2% of the lane's cheap
legs and 0% of its mid-band legs are above it, so the lane is capped where its edge is highest and
floored where its clip is smallest — lifting it to $30 adds roughly half the lane's booked PnL.

**Measurement.** Same script, §C/§D/§E. shttr/0.00–0.20: 135 bets, $2,515, **+$1,485.0 [booked,
+59.0%]**, clip $18.6, **82.2% exactly $20**, **$535.5/$1k-cd** — the highest of any cell in the
book. Every short-TTR cell has a positive settlement edge (§2: +10.0, +4.9, +8.2, +10.9pp). Slot-
and-cap-aware shadow with the $100 clamp held: **+$872 over 59.6 days (+$14.6/day)**; at $40,
+$1,744 (+$29.2/day).

**Decision rule.** Ship if the *cell carrying the binding ceiling* clears the book average $/1k-cd
($177.6) by 2x at n ≥ 100 — measured **$535.5 = 3.0x** — **and** the lane's pooled booked ROI is
positive (measured +26.0% on 1,112 bets). Ship at $30; $40 only if the $30 read holds.

**Refutation.** Revert if, over the first 60 days at the higher ceiling, (a) the short-TTR lane's
booked ROI falls below **+15%** (it is +26.0% pooled), or (b) its unfilled-leg rate rises above
**12%** — the same fill bar as rec 1, because this lane trades the same thin books at a quarter of
the size and is the more fragile of the two.

---

### 3 — LANE A (propose): **do not re-open 0.40–0.60 in STANDARD, and do not lift its mid-band ceiling.** Cost: 0h.

**Hypothesis.** 0.40–0.60 will be re-proposed on its leg-weighted settlement edge (+3.6pp pooled);
that is the wrong test, because the pooled number is a mixture of a −3.6pp STANDARD cell and a
+8.2pp short-TTR cell, and re-opening STANDARD's half would restart a −$6.8/day leak.

**Measurement.** §B/§C/§H. Pooled leg edge **+3.6pp (z=+1.6)** vs dollar edge **−1.7pp**; split,
std/0.40–0.60 is **−3.6pp (z=−1.0) at −10.5% booked** on $3,870 and 197 resolved legs, shttr/0.40–0.60
is **+8.2pp (z=+2.9) at +5.1%**. std/0.60–0.80 is **−1.9pp** on $2,666. The band is 15.4% of
capital-days at **−$45.7/$1k-cd**. Standing state: 0 STANDARD opens in 0.40–0.60 in 7 days.

**Decision rule.** Re-open only if STANDARD's **dollar-weighted** edge in the band clears +3pp at
z ≥ 2 on ≥ 300 resolved legs. It has never been above zero on that basis.

**Refutation.** If STANDARD's dollar-weighted band edge reaches +3pp (z≥2, n≥300 resolved) with a
positive booked ROI, then the −10.5% was an artefact of the pre-v63 flow and the band should reopen
at its current 0.125 deadZone factor.

**IF YOU WEREN'T HERE:** raise `kellyMaxSizeUsd` to 150 and the short-TTR lane ceiling to $30, and
touch nothing else. The book runs at 17% of its exposure cap with a 16-cent cushion on its only
4.5-sigma edge and a measured 5.8% fill failure — the ceilings are the only levers left with dollars
behind them, and every gate on the list is either measured correct or a no-op behind a clamp.

---

## 6. Contradictions, corrections and dead ends I am logging

- **My own number moved, and here is why.** Yesterday's cheap-band ex-top-10 hit-rate edge was
  +6.8pp (z=2.7); today's is **+9.6pp (z=2.8)** on a wider window (278 bets vs 239). Direction and
  z are stable, the level is not — do not quote either to a decimal it hasn't earned. Ex-top-20 is
  +1.8pp today vs +1.7pp yesterday: that one is stable.
- **The drift shadow's trailing cohort flips sign, and it is composition, not decay.** Published
  `avgPnlPerTradeExDustPerSignal` is **+$0.80** cumulative but **−$1.65** on the trailing-7d cohort.
  Recomputed by band (§L): 0.00–0.20 **+31.3pp (z=10.5)**, 0.20–0.40 **+14.9pp (z=10.2)**,
  0.40–0.60 +1.8pp, 0.60–0.80 **−15.0pp (z=−12.3)**, 0.80–1.00 **−6.7pp (z=−11.8)**. The recent
  flow is expensive-band heavy (post-fix blocked rows price at 0.582); the cheap band has not decayed.
- **The drift gate is closed and correct — do not re-propose it.** The sign fix shipped 2026-10-26
  (`adverseDrift = max(0, signed)`), and the post-fix population confirms it: **405 adverse rows at
  −9.3pp (z=−3.7)** — correctly blocked — against **18 favourable rows at +16.9pp (z=+1.5)**. Those
  18 are an open instrument question (some path still blocks a bargain, 4.3% of post-fix rows), not
  a proposal at n=18. The cumulative cheap-band counterfactual (+31.3pp) is mostly the pre-fix
  bargains the fix stopped blocking, and must not be cited as current forgone value.
- **Category is not the axis.** PnL splits sports $4,143.6 (506 bets), tech $2,374.3 (14 bets, one
  leg $1,513.3), politics $1,247.0, other $760.7, weather $415.0 — and the negatives are esports
  −$92.7 and econ −$207.9. No category gate would have helped. The concentration is by *price*.
- **Capital-time is not capital.** 382 STANDARD legs / $4,121 / 94.8-day age mark at **−$64.7**.
  The stranded-legs story is worth ~$0/day; the capital-days are real (§1) but they are not dollars.
- **0.60–0.80's +5.1pp settlement edge is not recoverable by sizing.** It books +0.1% because 138 of
  its 426 legs are stopped at −7.5%, and holding them is worth −$16. Sizing a zero-return band is how
  the 21.5% of capital-time gets worse.
- **Gate tuning stays closed.** 6,233 skips vs 108 copies in 7 days; the three largest refusal
  classes are all correct — 1,530 adverse-drift, 920 STANDARD band skip (v63, the cell is −10.5%),
  879 already-open dedupe.

---

## 7. What changed in the instrument

`scripts/profit-throttle-read.py` is new and committed with this file. It carries: the three-basis
band map with **leg- and dollar-weighted** settlement edges side by side (their disagreement is the
sizing diagnosis); lane×band settlement truth and capital-day tables; the clip census read from the
**live RuleSet** rather than hard-coded defaults; **clamp-aware** sizing shadows — the naive linear
shadow would have overstated a band-factor change by 2.3x, because a factor is a no-op behind a
binding clamp; break-even slippage per band against measured fill credit; residual/ex-top-N and
time-split breadth; drawdown at the proposed multiple; the refusal census; category totals; the
drift shadow by band plus the post-sign-fix split; and a `--self-test` that asserts the
notional-weighted payoff identity per band and exits 1 if it fails. The self-test is what surfaced
the 9 fill-aware zero rows rather than letting them silently corrupt the identity.

No prisma write. No RuleSet row touched. No rule, size, gate, threshold or exit changed. Both
recommendations are proposals and nothing was applied.
