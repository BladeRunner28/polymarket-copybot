# Profit review — 2026-11-04

**Instrument:** `scripts/profit-lane-scale.py` (committed with this file, read-only).
Reproduce with `python3 scripts/profit-lane-scale.py --since-v49`.
Population unless stated: regime only (`ruleSetVersion >= 49`), **1,812 bets / $23,911 at risk /
+$8,490.62 / +35.51% / 58.7 days / +$144.70 a day**. Bet level = first leg per
(bot|wallet|market|outcome). **Cost basis on every ROI below is `simulatedPositionSize` = dollars at
risk**, never shares, never multiplied by price. Lane = the label the scoring path stamps in
`DecisionJournal.reasonsJson` ("Short-TTR lane"), not a snapshot proxy — the proxy agrees on only
32.7% of main-lane legs, so using it moves every cell.

---

## 0. The correction first, because it changes what is safe to ship

Yesterday's v71 was justified on four numbers. **They reproduce exactly — on the resolved-only
basis** — and I nearly retracted them.

| basis | shttr 0.40–0.60 | shttr 0.60–0.80 |
|---|---|---|
| yesterday's draft | +22.6% CI [+10.2,+34.9] | +24.4% CI [+14.5,+32.6] |
| **resolved only** (`status='resolved'`) | **+22.6% CI [+9.7,+35.6]**, n=307 | **+23.9% CI [+14.9,+32.0]**, n=154 |
| **closed + resolved** (the book as booked) | **+5.1% CI [−5.0,+14.3]**, n=456 | **+3.9% CI [−2.7,+10.4]**, n=270 |

(Variant table: `scripts/profit-v71-basis-repro.py`, committed here. Variant C — resolved only,
deduped, journal lane label — reproduces yesterday's pair to within 0.5pp and both CIs.)

My first pass today ran the closed+resolved basis, got +4.9% / +3.8%, and I was one step from
writing "v71's premise is a selection artifact." That would have been wrong. The premises are two
different questions and both are true:

- **resolved-only = the conditional edge** — what the band pays when our own exit does not
  intervene. That is the number to size on.
- **closed+resolved = the realised expectation** — what the book actually books. That is the number
  to report.

**The defect was not the number, it was the unstated basis** — the same failure mode the 2026-10-20
run was cited for. Every ROI line in this draft now carries its basis, and section G of the
instrument prints both halves side by side so the gap cannot go unmentioned again.

Two live facts about v71, verified on the three 0.60–0.80 lane legs opened since it landed:
the clip books **$9.92**, not $19.95 — it is `10 × 0.5` (v60 band factor on 0.60–0.80, still in the
ruleset) `× 2.0` (v71 premium) through the non-linear `mapBankroll200Size` curve. v71 doubled the
clip ($4.99 → $9.92) and is **not** at the $20 clamp. The deadZone half is **inert**: the lane
opened exactly **1** leg in 0.40–0.60 in the last 7 days.

---

## 1. Where the edge is, on settlement truth

Resolved legs only, so PnL > 0 iff the token won and the payoff identity `ROI = hit·(1/p−1) −
(1−hit)` is exact — the instrument prints an `implied` column that agrees with realised ROI on
every row, so these are not basis artifacts. Breakeven hit rate **is** the entry price.

| cell | n | avg p | hit | edge | z | ROI |
|---|---|---|---|---|---|---|
| standard 0.05–0.20 | 48 | 0.125 | 31.2% | **+18.8pp** | +2.8 | +118% |
| standard 0.20–0.40 | 97 | 0.320 | 43.3% | **+11.3pp** | +2.3 | +29% |
| standard 0.40–0.60 | 197 | 0.503 | 46.7% | **−3.6pp** | −1.0 | −7% |
| standard 0.60–0.80 | 128 | 0.685 | 68.0% | −0.5pp | −0.1 | −1% |
| main 0.05–0.20 | 26 | 0.119 | 30.8% | **+18.9pp** | +2.1 | +121% |
| main 0.20–0.40 | 63 | 0.302 | 42.9% | **+12.7pp** | +2.0 | +37% |
| shttr 0.05–0.20 | 67 | 0.109 | 22.4% | **+11.4pp** | +2.2 | +109% |
| shttr 0.20–0.40 | 147 | 0.305 | 38.1% | **+7.6pp** | +1.9 | +24% |
| shttr 0.40–0.60 | 306 | 0.506 | 57.8% | **+7.3pp** | +2.6 | +22% |
| shttr 0.60–0.80 | 153 | 0.690 | 81.0% | **+12.0pp** | +3.8 | +24% |

Three things follow.

**a. The cheap band is the only place all three lanes agree.** +18.8 / +18.9 / +11.4pp. That is the
strongest cross-lane agreement in the book and it is where 38% of notional ($9,176) sits.

**b. The same prices carry opposite signs in different lanes.** 0.40–0.60 is **−3.6pp in
STANDARD** and **+7.3pp in short-TTR**; 0.60–0.80 is −0.5pp vs +12.0pp. v71's lane-scoping premise
is not just right, it is the best-supported structural finding in the book — and it is supported by
the two highest z-scores in the table (+2.6, +3.8). The cell that pays worst is the one that still
holds the most STANDARD notional ($3,870, 16% of the regime total, −10.5% closed+resolved). That
flow is already gone (0 STANDARD opens in 0.40–0.60 in the last 7 days, v63 skip live), so it is
history, not a leak — but it is the reason STANDARD earns $9.92 a day on 41% of the notional.

**c. Capital is not the constraint; size is.** Notional continuously in flight = capital-days ÷
span = **$868** against a ~$4,760 exposure cap. The cap is 5.5x away, cash is ~$8.9k. Nothing in
this book is starved of capital. Every remaining lever is either *which* bets or *how big*, and the
per-bet ceilings are $20 (lane) / $100 (Kelly), both hard constants in `src/lib/safety.ts`.

---

## 2. Is the cheap band's edge broad, or is it the ten biggest wins re-counted?

This is the question that decides whether the biggest clip in the book is too big. It is also the
question yesterday's cap proposal got wrong, and the reason is subtle.

**For a 0.11 band, ex-top-N ROI always collapses.** A win pays ~8x, so deleting the ten biggest
winners deletes the arithmetic by construction. Pooled 0.05–0.20 (closed+resolved): +83.9%
headline → +28.9% ex-top-5 → **−7.6% ex-top-10** → −40.9% ex-top-20. Read alone, that says "cap
it." But the same table on the test that is not fooled by the payoff shape — the **hit rate**
against each bet's own entry price — says:

| cut | n | wins | hit% | breakeven% | edge | z |
|---|---|---|---|---|---|---|
| none | 239 | 58 | 24.3 | 11.2 | **+13.1pp** | +4.7 |
| ex-top-1 market | 237 | 56 | 23.6 | 11.2 | +12.4pp | +4.5 |
| ex-top-5 | 230 | 49 | 21.3 | 11.3 | +10.0pp | +3.7 |
| ex-top-10 | 220 | 39 | 17.7 | 10.9 | **+6.8pp** | +2.7 |
| ex-top-20 | 207 | 26 | 12.6 | 10.8 | +1.7pp | +0.8 |

And it is time-stable, which is the one breadth test that is not outcome-selected: early half
**+13.0pp (z=+3.4)**, late half **+13.2pp (z=+3.4)**. 45 of 179 markets produced a winning leg.

So the honest read is neither "one market carries it" nor "broad edge":
**the band wins more often than its price even after the ten biggest markets are removed (+6.8pp,
z=2.7); past the top twenty it is at breakeven (+1.7pp, z=0.8).** The flow is a longshot book whose
money is in a ~20-event right tail — which is what a longshot book looks like, and is not by itself
a reason to cut the clip. But it is emphatically a reason not to raise it: the marginal bet outside
those events has no measurable edge.

Per lane, same test, same band: standard **+13.9pp on 66 bets but 0 wins in 46 bets once its top 20
markets are removed**; main +23.1pp on 53 bets (clip $87.94); short-TTR +7.7pp on 120 bets (clip
$18.46). The standard lane's cheap band is five markets wearing sixty-six bets — do not size it up.

---

## 3. What our own exit does, and it is not what I expected

The 24h adverse stop (`staleExitHours=24`, `staleExitAdverseMove=−0.15`, `adverseOnly=1`) closes
**38% of the short-TTR lane's bets (421 of 1,094 in the regime)**, at a median age of **25.0h**. It
is almost certainly the only thing that closes them: every stopped cell books −11.9% to −22.5%, and
a stop at −15% produces exactly that.

The natural hypothesis is "the stop is destroying a +22% band." **It is not.** Holding the stopped
legs to their market's final mark:

| cell | booked | held | delta | CI95 | ex-top-5 | settled delta | W/L |
|---|---|---|---|---|---|---|---|
| shttr 0.20–0.40 | −$94 | +$364 | **+$458** | [+181,+734] | **+36.5%** | +$84 | 26/18 |
| shttr 0.40–0.60 | −$73 | −$45 | +$28 | [−31,+90] | 0.0% | +$5 | 56/34 |
| shttr 0.60–0.80 | −$94 | −$111 | **−$16** | [−69,+38] | −7.3% | +$2 | 32/45 |
| main 0.20–0.40 | +$62 | +$454 | +$392 | [−47,+924] | −6.9% | +$272 | 6/10 |
| main 0.00–0.20 | +$2,447 | +$6,727 | +$4,280 | [−1895,+11716] | −49% | +$4,312 | 9/3 |

The stop is **approximately right everywhere except 0.20–0.40**. In 0.60–0.80 holding is actively
*worse* (−$16, and only 32 of 77 settled stopped legs came back). In the main lane's cheap band the
"delta" is an 8x-payoff lottery whose CI spans ±$11,700 — not evidence of anything.

So the realised-vs-settlement gap in §1 is **selection, not a mis-set exit**: the legs the stop cuts
are a genuinely worse subset, and holding them would have earned about the same. That is a useful
thing to know and it is why I am *not* proposing to relax the stop across the lane.

The one exception is 0.20–0.40: 26 of the 44 settled stopped legs went on to settle our way, and the
counterfactual is the only one in the table whose CI excludes zero with a positive ex-top-5. Its
settled-only delta is small (+$84), which is the number I trust most here.

---

## 4. Recommendations, ranked by expected value

### 1 — LANE A (propose): withdraw the approved `-2SE Kelly` clip cap on `main <0.20` before it is implemented. Cost: 0h.

**Hypothesis.** The cap was justified by "drop the top five markets and the cell is −56.1%", but
that is the payoff structure of a 0.11 band, not evidence the edge is absent; on the hit-rate test
the band's residual still clears breakeven, so capping the book's largest earner at $7.50 would
forgo real money.

**Measurement.** `scripts/profit-lane-scale.py --since-v49`, sections A, J. The cell the cap targets
is the journal-label main lane at 0.05–0.20: 67 bets, **$85.40 average clip (63% at the $100 Kelly
clamp)**, $5,722 at risk, +$5,254, **+91.8% closed+resolved**, settlement-truth +18.9pp (z=2.1). It
is **62% of the regime's entire PnL** ($5,254 of $8,491). Capping to $7.50 would book ~8.8% of the
notional, i.e. **−$4,800 over 58d ≈ −$82 a day in-sample**; the prior draft's own estimate was
−$13.3 a day. Either way it is negative. The population it was computed on cannot be reproduced on
either attribution (journal-label: 63 markets / $85 clip / +91.8%; snapshot proxy: 56 bets / $43
clip), so the −56.1% number should not be acted on without restating its basis.

**Decision rule.** Withdraw if the band's residual (ex-top-10 markets) hit rate clears its own entry
price with z ≥ 2. Measured: **+6.8pp, z=+2.7 → withdraw.**

**Refutation.** If, on the next 100 settled longshot bets, the residual (ex-top-10 markets) hit rate
falls **below** the average entry price, the cap was right and should be reinstated at the −2SE
Kelly level. Second falsifier: if the band's settlement-truth edge drops under +5pp at n ≥ 100
(resolved), stop citing it as the book's earner at all.

---

### 2 — LANE A (propose): exempt short-TTR legs entered 0.20–0.40 from the 24h adverse stop. Cost: 1h.

**Hypothesis.** For legs admitted by the short-TTR lane at 0.20–0.40, the 24h adverse stop closes
positions that would have finished above their entry more often than not, and holding them to
settlement beats the stop.

**Measurement.** `scripts/profit-lane-scale.py --since-v49`, sections G1/G2. 90 stopped legs, $787
of stopped notional: booked **−$94**, hold-to-final-mark **+$364**, **delta +$458, market-clustered
CI [+181,+734]** — the only cell in the table whose CI excludes zero with a positive ex-top-5
(**+36.5%**). 26 won / 18 lost of the 44 whose market has settled; settled-only delta **+$84**. The
cell's realised ROI goes from **+10.5% to +32.5%** (closed+resolved basis) if the stop is removed.
Counterfactual is priced at the market's last recorded mark for the held outcome, with the settled
subset reported separately because the mark basis depends on 46 markets that have not settled.

**Decision rule.** Ship if the counterfactual delta's CI excludes zero **and** the settled-only delta
is positive — both hold (+$458 [+181,+734]; settled +$84).

**Refutation.** If the first 40 organically-held (un-stopped) 0.20–0.40 short-TTR legs realise worse
than the matched stopped cohort by more than 2% of notional on settled truth, or if fewer than 40%
of settled stopped legs in this cell turn out to have settled our way on a fresh sample (currently
59%), withdraw it.

*Implementation note (Lane B, not a decision):* `PaperTrade` carries neither lane nor TTR, so the
cleanest scoping today is a journal join on `reasonsJson LIKE '%Short-TTR lane%'` in the
`BANKROLL_200` block at `scripts/update-pnl.ts:239`. If that is judged too fragile, an
entry-price-only scope (`0.20 ≤ entryPrice < 0.40`) also has a positive delta (+$392) but its CI
includes zero, so it is the weaker version of the same change.

---

### 3 — No size change is justified today. Here is the measurement that would unlock one. Cost: 0h now.

**Hypothesis.** Every band that carries enough notional to matter is sized where the *marginal* bet
has no measurable edge, so any uniform up-sizing multiplies a tail rather than an edge.

**Measurement.** Sections B, I, J. Per-bet ceilings are $20 (lane) / $100 (Kelly); notional in
flight is $868 against a $4,760 cap, so capital is not the blocker. The cheap band (38% of notional)
clears breakeven only down to its top-20 markets (+1.7pp, z=0.8); the standard lane's version of it
is 0/46 after its top 20. The mid bands are +7.3pp/+12.0pp in short-TTR but realise +5.1%/+3.9%
because 43% of their bets are stopped, and holding those legs is worth −$16 to +$28 — so the
settlement edge is not recoverable by sizing.

**Decision rule.** Size up when the **residual** flow (ex-top-10 markets) clears its entry price by
**≥ +3pp with z ≥ 2** on **≥ 100 settled bets** in a single cell. Then raise that cell's clip 1.5x
first, not 2x. Nothing in the book clears that bar today except the pooled cheap band (+6.8pp,
z=2.7) — and its own ex-top-20 read (+1.7pp) is why this is a hold, not a raise.

**Refutation.** If a cell clears the bar and a 1.5x clip produces less than 0.8x the expected PnL
delta over 60 days — i.e. the fills worsen faster than the size — the ceilings, not the band, are
the binding constraint and this whole axis is closed.

**IF YOU WEREN'T HERE:** withdraw the longshot cap (rec 1) and ship the 0.20–0.40 exit exemption
(rec 2). Do not touch a single size field: the book's edge is a ~20-event tail wearing 1,812 bets,
and the cheapest way to lose the next month is to lever it before the residual flow earns it.

---

## 5. Contradictions and dead ends I am logging, not re-proposing

- **"1,269 open legs / 76.3-day weighted age"** (standing baseline) still does not reproduce: 432
  open legs now, 420 of them pre-v49. With $868 in flight against $4,760, it is worth ~$0/day.
  Not chased again.
- **STANDARD 0.40–0.60 (−10.5%, $3,870, the largest STANDARD band)** and **short-TTR 0.40–0.60**:
  both already closed by v63/v62. 0 STANDARD and 1 lane open in the last 7 days. No proposal.
- **The sub-0.05 longshot leak** (c200LongshotBandFloor): dead. Zero B200 legs below 0.05 since
  v67; the −53.2% sub-band is all pre-2026-10-08. The floor works.
- **`shortTtrPremiumBandFactor` further increases** would be a no-op above ~2.0 only after the v60
  band factor is removed; today the 0.60–0.80 clip is $9.92 and composed of three multiplicative
  levers that partly cancel. Not proposed — the band's realised edge is +3.9%.
- **Gate tuning** is not revisited (baseline: both shadow reads closed NO-CHANGE).

## 6. What changed in the instrument

Two scripts are committed with this file, both read-only:

- **`scripts/profit-lane-scale.py`** — new, carries §1–§5's numbers: lane attribution from the
  journal (with the proxy-disagreement count printed, because the proxy is wrong on 68% of
  main-lane legs), per-bet ceiling census, capital-days and in-flight notional, the status split
  and the hold-to-settlement counterfactual with market-clustered CIs, pooled band breadth,
  settlement-truth calibration with an implied-ROI cross-check, and the hit-rate breadth test.
- **`scripts/profit-v71-basis-repro.py`** — the diagnostic that attributes yesterday's numbers to
  `status='resolved'` rather than letting the basis go unstated (again).

Every ROI either prints its basis in the section header or is labelled in the line. No prisma write,
no RuleSet row touched, no rule, size, gate or threshold changed.
