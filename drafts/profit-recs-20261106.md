# Profit review — 2026-11-06

**Instrument:** `scripts/profit-band-rotation.py` (committed with this file, read-only,
`prisma/dev.db?mode=ro`). Reproduce with `python3 scripts/profit-band-rotation.py`;
`--self-test` asserts the BUY-payoff identity per resolved leg and fails on a bandless leg.

Population: regime (`ruleSetVersion >= 49`), 1,874 deduped settled legs. Bet = first leg per
(wallet|market|outcome|bot). **Cost basis on every ROI line is `simulatedPositionSize` =
dollars at risk**, never shares, never multiplied by price.

Two new tests, both absent from the last three briefs:

- **ex2** — remove the two wallets with the largest summed PnL *in that cell*. Sizing is per
  leg; a band whose edge is one wallet's run is not a band edge, and an ex-top-N **markets**
  test cannot see this (one wallet trading 43 markets passes it trivially).
- **month cut** — the same cell, Sep / Oct / Nov, so a rotating edge shows up as a trend
  instead of averaging into a two-month lie.

---

## 0. The verdict in five lines

1. **The size chain is a photograph of September.** Booked ROI, ex-top-2-wallets, by month:
   `<0.20` **+31.3% → +12.4% → −44.8%**; `0.20–0.40` **−5.5% → +7.2% → +3.2%**;
   `0.60–0.80` **−0.6% → −14.6% → −31.5%**. The edge moved, the factors did not.
2. **The clamp's own cohort is now the cheap band's worst cohort:** 24 legs pinned at $100
   book **+46.1%**, the 69 sub-clamp legs book **+135%**. Yesterday's opposite read was a
   60-day window.
3. **Do not ship yesterday's `kellyMaxSizeUsd` 100 → 150.** Its breadth test was over markets;
   over wallets the band's residual is negative on the last 30 days, and 13 of the 24 clamp
   legs belong to wallets whose aggregate in that band is **−$313**.
4. **The band where size and edge agree is 0.20–0.40** — 216 legs, 7.2/day, **+27.0%**,
   ex2 **+9.7%**, settlement edge **+10.5pp** — and it is capped at **$20** by a rail whose
   entire evidence base is **8 legs from September**. No leg in that band has exceeded $25 in
   thirty days.
5. **v71 doubled the clip in the only band whose three months are monotone down** (shipped
   11-03: shttr `0.60–0.80` clip $2.39 → $9.42; Nov cohort −15.5%).

---

## 1. What the book is doing now

Last 30 days, settled legs, booked:

| band | legs | legs/d | $/d at risk | clip | booked | ROI | ex2 ROI | wallet |
|---|---|---|---|---|---|---|---|---|
| 0.00–0.20 | 93 | 3.1 | $125 | $40.30 | +$2,925.7 | **+78.1%** | **−14.6%** | 17 |
| 0.20–0.40 | 216 | 7.2 | $94 | $12.99 | +$756.7 | +27.0% | +9.7% | 27 |
| 0.40–0.60 | 110 | 3.7 | $35 | $9.57 | −$9.0 | −0.9% | −8.9% | 19 |
| 0.60–0.80 | 72 | 2.4 | $16 | $6.46 | −$94.4 | **−20.3%** | −23.9% | 17 |
| **total** | **493** | **16.4** | **$270** | $16.45 | **+$3,586.4** | **+44.2%** | | |

**$119.55/day.** The last 7 days read $368.68/day on $390/day at risk (+94.5%) — that is a hot
week, not a new rate, and it is the cheap band at +135.5% doing it.

**Capital is not the constraint, and this is now measurable rather than asserted.** Peak
simultaneous in-flight over the last 30 days is **$720 — 14.2% of the $5,064 effective cap** —
with $9,928.54 cash and 8 legs / $211.93 open. Profit is edge × clip × **count**, and count is
daily notional over clip; at $270/day of notional against a $5,064 cap, no size change is
limited by capital. It is limited by the clip on the legs that exist.

---

## 2. The rotation — the load-bearing table

Booked ROI and ex2 ROI, per band per month:

| band | month | legs | wallets | notional | booked | ROI | **ex2** | legs ex2 |
|---|---|---|---|---|---|---|---|---|
| 0.00–0.20 | Sep | 153 | 20 | $5,178 | +$4,404.6 | +85.1% | **+31.3%** | 124 |
| | Oct | 89 | 19 | $3,117 | +$2,073.9 | +66.5% | **+12.4%** | 78 |
| | Nov | 39 | 8 | $1,531 | +$2,074.6 | +135.5% | **−44.8%** | 11 |
| | regime | 281 | 36 | $9,827 | +$8,553.1 | +87.0% | +58.2% *(CI +3.0, +123.2)* | 221 |
| 0.20–0.40 | Sep | 205 | 26 | $3,018 | +$293.9 | +9.7% | **−5.5%** | 119 |
| | Oct | 204 | 29 | $2,492 | +$484.4 | +19.4% | **+7.2%** | 169 |
| | Nov | 63 | 11 | $821 | +$442.8 | +53.9% | **+3.2%** | 40 |
| | regime | 472 | 47 | $6,331 | +$1,221.0 | +19.3% | +11.8% *(CI −6.2, +30.6)* | 388 |
| 0.40–0.60 | Sep | 459 | 36 | $3,427 | −$377.6 | −11.0% | −12.6% | 454 |
| | Oct | 212 | 26 | $1,298 | +$14.5 | +1.1% | −8.5% | 146 |
| | regime | 671 | 52 | $4,725 | −$363.0 | −7.7% | −10.6% *(CI −23.2, +3.8)* | 549 |
| 0.60–0.80 | Sep | 340 | 21 | $3,316 | +$74.6 | +2.2% | **−0.6%** | 127 |
| | Oct | 68 | 16 | $369 | −$36.0 | −9.7% | **−14.6%** | 60 |
| | Nov | 23 | 9 | $175 | −$41.5 | −23.7% | **−31.5%** | 20 |
| | regime | 431 | 36 | $3,861 | −$2.9 | −0.1% | −5.4% *(CI −17.7, +7.0)* | 218 |

Three readings, and only the third is comfortable:

- **The cheap band is decaying on the residual.** +31 → +12 → −45 is a monotone slide in the
  population that does *not* include the two hot wallets. The regime ex2 (+58.2%, CI excludes
  zero) is still the strongest breadth evidence in the book — the band is not dead — but the
  trend line and the six-week-old breadth test point in opposite directions.
- **0.20–0.40 is the only band whose residual never went negative for two consecutive months
  and whose November is positive on both bases.** It is also the only band where the monthly
  direction (+9.7 → +19.4 → +53.9 headline) and the breadth direction (+7.2 → +3.2) agree in
  sign.
- **0.60–0.80 is a straight line down on both bases**, and it is the one band where a live rule
  is currently *adding* size.

Honest caveat, stated before it is used against me: the November ex2 cells are 11 and 40 legs.
None of the single-month ex2 point estimates is significant; only the regime cheap-band ex2 CI
excludes zero. What is actionable is the *ordering across three months*, which is consistent in
all three bands — not any one cell.

---

## 3. The size chain vs the edge rank

| band | legs 30d | clip | % at $100 | % at $18–20 | max | legs >$25 | ROI 30d | edge rank |
|---|---|---|---|---|---|---|---|---|
| 0.00–0.20 | 93 | $40.30 | **25.8%** | 52.7% | $100 | 29 | +78.1% | 1 |
| 0.20–0.40 | 216 | $12.99 | 0% | **40.7%** | **$20.00** | **0** | +27.0% | 2 |
| 0.40–0.60 | 110 | $9.57 | 0% | 50.0% | $18.00 | 0 | −0.9% | 3 |
| 0.60–0.80 | 72 | $6.46 | 0% | 15.3% | $20.00 | 0 | −20.3% | 4 |

The chain that produces this: STANDARD-scale parent (0.25–20) → linear remap → band factor
(`c200Longshot 3.5`, `0.20–0.40 ×1.0`, `c200DeadZone 0.125`, premium) → `BOT_LIMITS` $20 or
`kellyMaxSizeUsd` $100 → and, for Kelly admits in **[0.20, 0.60)**, `applyKellyBandRails` cutting
the Kelly output back to the legacy-equivalent.

So the band that ranks #2 on booked edge gets **one third of the belt-and-braces clip of the
band that ranks #1**, and it cannot exceed $20 by any path. The modal clips in it are $17.99 and
$20.00 — the rail and the cap, visible in the distribution.

---

## 4. Why yesterday's #1 should be withdrawn

Yesterday's brief ranked "raise `kellyMaxSizeUsd` 100 → 150" first, on `+16.2pp` band edge,
ex-top-**10 markets** `+9.6pp`, "time split +13.7pp early / +18.7pp late", and `+$4,590 /
59.6d = +$77/day`. Four things happen to that case under today's cuts:

1. **The breadth test was over the wrong unit.** One wallet (`0x885ffdf3`) trades 53 cheap legs
   across 43 markets and books +$2,264. An ex-top-N-markets test deletes *markets*, and that
   wallet's edge is spread across 43 of them — it survives by construction.
2. **The clamp cohort is now the band's worst.** 30d: the 24 legs pinned at $100 book
   **+$1,106.55 on $2,400 = +46.1%**; the 69 sub-clamp legs book **+$1,819 on $1,348 = +135%**.
   Yesterday's §3(b) reported the opposite ordering (+125.3% clamp vs +103.1% sub-clamp) on the
   0.05–0.20 slice of the 60-day book. That is a **reproduction failure of a load-bearing claim**
   — different window, same instrument question — and I am reporting it rather than choosing the
   friendlier number.
3. **The clamp is a bet on the two wallets that already carry the band.** Of the 24 clamp legs,
   11 belong to the top-2 wallets (+$3,239 on 39 legs). The other 13 belong to wallets whose
   aggregate in the band is **−$313 on 54 legs**. Raising the clamp to $150 is not a
   diversification of the bond; it is a 1.5x on the concentrated half plus a 1.5x on the losing
   half.
4. **The forward price is a third of the quoted one.** At today's leg rate (24 clamp legs / 30d,
   band rate +78.1%) the shadow is **+$31.22/day**, not +$77/day. The 59.6-day book was built
   when Kelly was admitting 13 legs a day at the clamp; the lane now opens 3.1 cheap legs a day
   and carries $212 in flight.

None of that says the cheap band is dead — regime ex2 +58.2% with a CI excluding zero is the
best breadth number in the book. It says the *case for increasing the clip now* does not
survive, and an ambiguous change should lose to the default.

**Separately and honestly:** yesterday's ex-top-10-markets +9.6pp is not wrong, it is
under-powered for the decision it was used for. The correct breadth unit for a per-leg sizing
change is the wallet, because a single wallet's run can supply the whole band and the clip
multiplies it.

---

## 5. The rail

`applyKellyBandRails` (src/lib/paper.ts:133) caps Kelly output at the legacy-equivalent size for
every entry in **[0.20, 0.60)**. Its justification, in the comment: the band "has a SIGNIFICANT
POSITIVE entry edge (+6.4pp, z=+2.37) yet −$429.77 realized all-time", and the explaining split
was 14 days of September — `≤$15 → +$149 on 84` · `$15–30 → −$116 on 17` · `≥$30 → −$331 on 8`.
**Eight legs at ≥$30 carried the entire objection**, and they were pre-rail Kelly admits riding
to the $100 ceiling in a book whose band map was then ×1.0.

Today the band, at $12.99 a leg, is the second engine: 216 legs in 30 days, +$756.7, **+27.0%
booked**, ex2 +9.7%, settlement edge **+10.5pp (z=+1.8, n=72 resolved)**, and its legs land
across 27 wallets. It is not a tail: November's winners are atp/cfb/ucl/elc/spread markets at
$18–20 with the largest single leg +$73 and the worst −$20.

The rail is a live, binding, measurable ceiling on the one band whose size and edge agree.

---

## 6. v71's premium half — shipped into a falling band

v71 (2026-11-03) set `shortTtrPremiumBandFactor 0.5 → 2.0`, justified on "short-TTR 0.60–0.80
n=152, **+24.4% ROI**, hit 82.2% vs hurdle 69.8%, z=4.00". On booked dollars the same cell is
**+2.4% on 279 legs** ($29.10 on $1,195). The +24.4% is a settlement-truth figure; the book pays
the stop. That gap (+18.7% on resolved legs, +2.4% booked) is the exit eating the band, and it
is the reason a 2x clip there is 2x on the leakage.

It is exercising as designed — shttr ≥0.60 clip $2.39 → $9.42 — into a band at
+2.2% / −9.7% / −23.7% over Sep/Oct/Nov and −15.5% on the 17 legs opened in the last two days.

---

## 7. Confirmed, not re-litigated

- **The 0.004 drift bar is correct — split by band this time.** Post sign-fix (≥2026-10-26),
  edge on the blocked price: `0.20–0.40` **+10.6pp (n=41, z=+1.4)** · `0.40–0.60` +0.5pp (n=263) ·
  `0.60–0.80` **−22.4pp (n=105, z=−4.6)** · `0.80+` **−38.3pp (n=71, z=−6.5)**. At $10/leg the
  gate refuses ≈$58 of bargains and avoids ≈$507 of losses over eleven days. **The pooled
  −9.3pp is entirely the expensive bands; the gate is doing exactly what it should. No
  change, and I did not re-propose it.**
- **The 0.40–0.60 skip: correct.** 62.0 distinct signals a day, 434 a week, convert at 0.0%;
  the band is −7.7% regime / −10.6% ex2. This is 49% of all distinct candidate flow being
  refused and it should be.
- **Capital velocity is a non-issue for C-200**: 30d holds are short (resolutions and the 24h
  tier-1 rail), peak in-flight $720. The STANDARD open book (385 legs / $4,203.80 / mean age 94.3
  days) is still stranded by design since v70 set `standardStaleExitHours` to 0 — reopening it
  needs the card's own ≥20-blocked-copies-in-30-days trigger, which has not fired.

---

## 8. Recommendations, ranked by expected value

### 1 — LANE A (propose): un-rail 0.20–0.40 — raise the `applyKellyBandRails` cap from
legacy-equivalent to **2× legacy-equivalent**. Cost: 0.5h.

**Hypothesis.** The 0.20–0.40 band's edge survives the two breadth tests that killed the cheap
band's case (ex2 positive in Oct and Nov, −5.5% in the one month that set the rail), while its
clip is pinned near $18–20 by a rail whose evidence is 8 legs from September; doubling the rail
cap adds 1.5–2x notional on the 88 of 216 legs that are rail-bound and earns the band's own rate
on it.

**Measurement.** `scripts/profit-band-rotation.py` §1b, §2, §3, §7(a). Band 30d: 216 legs,
$94/day at risk, clip $12.99, +27.0% booked, ex2 **+9.7%** (CI −16.2, +35.7), settlement edge
**+10.5pp** (z=+1.8) at a 0.298 mean price; **0 legs above $25** in thirty days, 40.7% of them at
$18–20. Monthly ex2 −5.5 / +7.2 / +3.2. Shadow: **+$14.47/day at the band's cohort rate**
(+$20.76/day in-sample), scaling the 88 legs at ≥$15.

**Decision rule.** Ship at **2× only** — not to the clamp — because the ex2 CI includes zero.
Escalate to the $100 clamp only if, on the next 150 legs at the higher cap, ex2 ROI ≥ +15% and
the ≥$30 clip tier earns ≥ the band rate.

**Refutation.** Revert to one legacy-equivalent if any of: (a) the first 100 settled legs at the
higher cap book **< +8%**; (b) the band's ex-top-2 ROI is **≤ 0** on ≥100 legs; (c) the ≥$30
clip tier loses money on ≥25 legs (the rail's original 8-leg observation reproducing).

---

### 2 — LANE A (decision): **withdraw** the pending `kellyMaxSizeUsd` 100 → 150. Cost: 0h.

**Hypothesis.** The clamp increase was justified by a band edge that is a wallet edge: the
cohort it would size is now the cheap band's worst cohort, so the change would add notional to
the part of the band that is losing rather than the part that is winning.

**Measurement.** §1b, §4, §7(b). Clamp cohort 30d: **24 legs / $2,400 / +46.1%** vs sub-clamp
**69 legs / $1,348 / +135%**; 13 of the 24 clamp legs belong to wallets whose band aggregate is
**−$313**; cheap-band ex2 **−14.6%** (CI −72.4, +66.2) on 54 legs, monthly ex2 **+31.3 / +12.4 /
−44.8**; forward shadow **+$31.22/day**, not the +$77/day quoted on the 59.6-day book.

**Decision rule.** Do not ship. Re-propose only when the clamp cohort's ROI is **≥ the
sub-clamp cohort's** on ≥100 forward settled cheap legs **and** the band's ex-top-2 ROI is
≥ +20% on ≥100 legs.

**Refutation.** If, over the next 100 settled cheap legs, the clamp cohort earns ≥ the sub-clamp
cohort by 10pp **and** the band's ex-top-2 ROI is ≥ +20%, the withdrawal was wrong and the
original 1.5x should ship immediately.

---

### 3 — LANE A (propose): revert `shortTtrPremiumBandFactor` **2.0 → 0.5**. Cost: 0.5h.

**Hypothesis.** v71's premium doubling was priced off settlement truth in a band where the exit
removes the edge, so it doubles clip into the book's only monotone-declining cell.

**Measurement.** §3, §6, §7(c). shttr `0.60–0.80` regime: 279 legs, **+2.4% booked** vs **+18.7%
on resolved legs** (+10.1pp edge, z=+3.2); monthly **+2.2 / −9.7 / −23.7** (ex2 −0.6 / −14.6 /
−31.5); post-v71 clip $2.39 → $9.42 with −15.5% on the 17 legs opened since. Reverting is worth
**+$1.43/day** on the recent cohort and stops the only place size is growing.

**Decision rule.** Revert to 0.5 if the band's booked ROI is negative in two consecutive months
(it is: −9.7%, −23.7%) **and** its ex2 is more negative than the band. Both hold.

**Refutation.** If the shttr ≥0.60 cohort books **≥ +10%** over the next 60 settled legs, keep
2.0 and treat the November read as composition.

---

**IF YOU WEREN'T HERE:** un-rail 0.20–0.40 to 2× the legacy-equivalent and drop the short-TTR
premium factor back to 0.5; leave `kellyMaxSizeUsd` at $100. The band the chain starves is the
band that still pays after removing its two best wallets; the band the chain just doubled is the
one whose three months are monotone down.

---

## 9. Contradictions, corrections, dead ends logged

- **My own #1 from yesterday fails its forward reprice.** `kellyMaxSizeUsd` 100 → 150: quoted
  +$4,590 / 59.6d = **+$77/day**; at today's leg rate and band rate it is **+$31.22/day**, and
  the cohort it multiplies is the band's worst (+46.1% vs +135%). The 59.6-day shadow was
  arithmetically right and decisionally wrong: it priced a leg rate the lane no longer runs.
- **My clamp-cohort sentence from yesterday inverts on the 30-day window** (+125.3% clamp vs
  +103.1% sub-clamp → +46.1% vs +135%). Different window, same question. Quote neither to a
  decimal; the direction is not stable, and unstable direction is itself the answer.
- **v71's "+24.4%" does not reproduce as booked.** Booked is +2.4% (279 legs). The settlement
  basis is +18.7%. Both numbers are real; the rule was approved on the one the book does not pay.
  Third appearance of this same trap (cf. the card that priced shttr `0.40–0.60` at +22.6% when
  the ledger booked +5.1%): **settlement ROI and booked ROI must be quoted as a pair, always.**
- **The 25-slot track list is a quarter idle and I did not propose touching it.** 4 of 25
  tracked wallets produced **0** fills in 7 days and 7 more ≤14, while the top 7 produced 84% of
  eligible flow; 3,589 wallets sit on `watch`. A "replace dead slots, keep the cap at 25" change
  looks free, and legs booked while their wallet sat in the 60–80 score tier earned +44.9% on
  321 legs (vs +57.7% for the 85–90 tier), so the replacement pool is not obviously worse. I am
  **not** proposing it: the
  cap has a documented failure mode (the 2026-07 drift to 42 re-created floods of 1,109
  trades/run), the flow gain is an estimate I have not measured at the candidate level, and
  estimated flow is exactly what this brief exists to stop being paid for.
- **Rates vs levels.** Last 7 days: $368.68/day, +94.5%. Last 30: $119.55/day, +44.2%. The 7-day
  number is three standard errors of a 16-leg/day book and is not a ladder read.
- **Population note.** 1,874 deduped settled legs here vs 1,863 in yesterday's brief; the
  difference is the dedupe tiebreak and a day of new settlement. Nothing load-bearing.

---

## 10. Instrument

`scripts/profit-band-rotation.py` is new and committed with this file. It carries: the monthly
rotation table with **ex-top-2-wallets** ROI and market-clustered CIs (both the within-cell and
the 30-day variant); the size-chain census read from the live RuleSet (clip, % at clamp, % at
$18–20, max clip, count >$25); lane × band settlement-vs-booked with z on the hit-rate edge; the
capital read (peak in-flight from the leg ledger, not from a snapshot); the candidate funnel at
the **signal** level (deduped by wallet|market|outcome, because 8.0x of the fill rows are
re-offers) with the refusal census by class and band; the post-sign-fix drift read by band; and
three size shadows priced at each band's own forward rate. `--self-test` asserts the BUY payoff
identity on every resolved leg and that the band partition covers the population.

**The self-test caught my own error and it is worth recording:** I first asserted
`pnl = ntl × ((1−p) win | −p loss)` — the share-count form — and 1,307 of 1,307 resolved legs
failed it. The ledger's actual identity is **`pnl = ntl × (1−p)/p` on a win and `−ntl` on a
loss** (the stake is DOLLARS; shares = ntl/p), which now holds on **1,307 of 1,307**, with 44
legs booking exactly 0 (unfilled). So the cost basis is confirmed from the data rather than
assumed, and any instrument here that treats a sized leg as a share count is wrong by a factor
of 1/p — up to 20x on cheap legs.

**No prisma write. No RuleSet row touched. No rule, size, gate, threshold or exit changed.**
All three items are proposals; nothing was applied.
