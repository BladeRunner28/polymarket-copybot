# Profit review — 2026-11-07

**Instrument:** `scripts/profit-clip-effect.py` (committed with this file, read-only,
`file:prisma/dev.db?mode=ro`). Reproduce with `python3 scripts/profit-clip-effect.py`;
`--self-test` asserts the BUY payoff identity on every resolved leg (1,273/1,273 exact),
that no zero-stake leg enters an ROI denominator, and that the clip tiers partition the
population.

Population: regime (`ruleSetVersion >= 49`), 1,890 deduped settled legs at bet level
(first leg per wallet|market|outcome|bot). **Cost basis: `simulatedPositionSize` = dollars
at risk.** ROI = realizedPnl / size. Never shares, never × price.

The one thing this file adds that every prior sizing read in this book lacked: **clip
size compared within the same wallet, at the same price, in the same band.** All previous
comparisons — including both of mine this week — compared cohorts of legs, and cohorts
differ in who is in them.

---

## 0. The verdict in five lines

1. **The marginal dollar earns less than the average dollar.** With wallet and price held
   fixed, a leg at clip ≥ $18 books **−18.3pp** (SE 6.7, t = −2.74) against the same
   wallet's legs under $10; raw, **−29.8pp** (t = −3.05). n = 1,890, 1,537 market clusters.
2. **It is not one band.** The per-band coefficient is negative in all four: cheap
   **−107pp**, 0.20–0.40 **−18pp**, 0.40–0.60 **−8pp**, 0.60–0.80 **−8pp** — four band cells
   and the pooled estimate, all agreeing in sign. No single cell is decisive except the
   cheap one; the agreement is the finding.
3. **So every open sizing proposal is priced too high.** Un-rail 0.20–0.40 is worth
   **+$11.7/day**, not the +$16.9/day I quoted yesterday — and **+$7.5/day** if the
   marginal tier is charged the discounted rate instead of the cohort rate.
4. **The rail is not a tax.** Controlled test, 15 wallets with both rail-bound and unbound
   legs in that band: rail **+30.3%** vs unbound **+31.7%**, diff **−1.4pp**, CI
   [−28.1, +24.3], 7/15 better on the rail. And it caps a tier that pays *less* per dollar
   than the one beneath it: $18–20 books **+22.9%** (CI [−8.0, +56.7]) while $10–18 books
   **+38.5%** (CI [+7.2, +70.6], the band's only tier whose CI excludes zero).
5. **The escalation clause in yesterday's #1 is dead.** The 12 legs in 0.20–0.40 that ever
   exceeded $25 book **−18.4%** (−$115.1 on $626). That is the rail's original 8-leg
   objection reproducing on a fresh sample, and it is exactly the cohort the clause would
   have expanded into.

**No new size is proposed today.** What is proposed is the deletion of an escalation, a
trigger that would cut the book's dominant risk if its breadth decays further, and an
instrument that stops the next proposal from being priced at the average.

---

## 1. The measurement

30-day allocation, per dollar of notional (all lanes):

| band | legs | notional | share | $/1k booked | $/1k ex-top-2 | clip |
|---|---|---|---|---|---|---|
| 0.00–0.20 | 98 | $4,070 | **48.3%** | **+697** | **−190** | $41.53 |
| 0.20–0.40 | 218 | $2,839 | 33.7% | +308 | **+111** | $13.02 |
| 0.40–0.60 | 97 | $1,003 | 11.9% | −6 | −72 | $10.34 |
| 0.60–0.80 | 71 | $462 | 5.5% | −156 | −189 | $6.51 |
| **total** | **487** | **$8,433** | 100% | **+432** | | |

Half the book's capital goes to the band that pays most per dollar on the headline and
least per dollar once its two best wallets are removed. That is the allocation question,
and it was already visible yesterday. What was not visible is *why sizing cannot fix it*:

| clip tier | n | wallets | notional | ROI | 95% CI |
|---|---|---|---|---|---|
| **0.00–0.20** $18–20 | 176 | 32 | $3,403 | +48.6% | [−0.9, +107.0] |
| **0.00–0.20** ≥$25 | 73 | 29 | $6,356 | +90.3% | [+18.3, +172.3] |
| **0.20–0.40** $10–18 | 76 | 23 | $1,357 | **+38.5%** | [+7.2, +70.6] |
| **0.20–0.40** $18–20 | 98 | 23 | $1,792 | +22.9% | [−8.0, +56.7] |
| **0.20–0.40** ≥$25 | **12** | 7 | $626 | **−18.4%** | [−75.9, +55.2] |
| **0.40–0.60** <$5 | 456 | 41 | $855 | +5.1% | [−4.8, +14.6] |
| **0.40–0.60** $18–20 | 216 | 35 | $3,888 | **−10.1%** | [−24.4, +4.8] |
| **0.60–0.80** <$5 | 270 | 32 | $1,106 | +3.9% | [−3.1, +10.5] |
| **0.60–0.80** $18–20 | 144 | 16 | $2,594 | −0.5% | [−12.3, +11.0] |

Every band tells the same story in a different costume: **the cheap legs pay and the shelf
does not.** In the two expensive bands — where 66% and 63% of the notional sits at $18–20 —
the shelf books −10.1% and −0.5% while the sub-$5 legs book +5.1% and +3.9%. In 0.20–0.40 the $18–20 shelf is fourth of five tiers and the $10–18 tier is the best tier
whose CI excludes zero.

The cohort view can be an artefact of *who* bets the shelf (the STANDARD lane, $18.00 flat),
so the coefficient below is the one to trust: same wallet, same 2c price bin, same band,
market-clustered SE.

| specification | clip ≥ $18 coef | SE | t |
|---|---|---|---|
| raw ROI, wallet + price FE | **−29.8pp** | 9.8 | **−3.05** |
| winsorised ±300%, wallet + price FE | **−18.3pp** | 6.7 | **−2.74** |
| raw, wallet FE only (no price control) | −30.3pp | 9.8 | −3.10 |
| winsorised, wallet FE only | −20.5pp | 6.9 | −2.98 |

Per band (winsorised, wallet + price FE, reference = the $10–18 tier):

- 0.00–0.20: clip ≥ $18 **−107.3pp** (SE 59.9, t −1.8)
- 0.20–0.40: clip ≥ $18 **−18.3pp** (SE 17.3, t −1.1)
- 0.40–0.60: clip ≥ $18 **−7.9pp** (SE 8.0, t −1.0)
- 0.60–0.80: clip ≥ $18 **−7.9pp** (SE 5.9, t −1.3)

Two honest limits, stated before they are used against me: only the pooled estimate is
significant; the per-band ones are not, and the cheap-band one is identified off 33 small
legs. And a mechanical cause is ruled out — the paper ledger books the same price
regardless of size, so this is **not** a fill effect. It is either the size chain selecting
legs that look strong and are not (Kelly/confidence/band factors all steer the big clips),
or wallet-level noise surviving the fixed effect. Either way the direction of the next
proposal should not assume the average rate holds at the margin.

---

## 2. What it does to the three open proposals

| proposal | priced yesterday | re-priced today | change |
|---|---|---|---|
| Un-rail 0.20–0.40 to 2× | +$16.9/day | **+$11.7/day** cohort rate; **+$7.5/day** at the marginal rate | −31% / −56% |
| `kellyMaxSizeUsd` 100 → 150 | withdrawn, +$31.22/day if shipped | **stays withdrawn**; +$31.37/day is a cohort rate on a tier the FE discounts most | unchanged |
| shttr premium 2.0 → 0.5 | +$1.43/day | +$1.10/day (rotation §7c) | unchanged |

The un-rail re-price is arithmetic, not opinion: 30d, 37 legs sit at ≥ $18 in 0.20–0.40 for
$694 of notional ($23/day). Doubling them adds $23/day of risk; at the cohort rate +50.6%
that is **+$11.7/day**; at the FE-discounted rate (+50.6 − 18.3 = +32.3%) it is **+$7.5/day**.

**And the rail's own evidence gap is closed in the opposite direction from the way I read
it yesterday.** The complaint was that the rail's justification was 8 legs from September.
Controlled (`§6`), the rail is worth zero: 15 wallets with ≥2 rail-bound and ≥2 unbound legs
in the band come out **+30.3% vs +31.7%, −1.4pp, CI [−28.1, +24.3]**. But zero is not the
same as free — the rail sits *on top of* the band's best cell, not on its worst. Un-railing
buys notional at +22.9% when the tier below it earns +38.5%.

---

## 3. The cell that looks under-sized and is not

The strongest settlement edge in the book is the STANDARD lane's cheap band: 56 resolved
legs, hit **35.7%** against a **0.123** mean price — **+23.4pp, z = +3.7** — booked +93.3%
on 74 legs, clip median $18.00 and **100% at or under $20**. On the headline it wants 4x
($+36.39/day at the regime rate, $+79.25/day at the 30d rate).

It does not get 4x, and this is the most useful thing I found today: **its breadth is
dying at the same speed as the band it sits in.**

| month | legs | ROI | ex-top-2 ROI | wallets |
|---|---|---|---|---|
| Sep | 39 | +46.5% | **+3.7%** | 14 |
| Oct | 20 | +86.5% | **−16.4%** | 12 |
| Nov | 15 | +331.4% | **−32.4%** | 6 |

Regime ex2 +36.1%, top wallet 35% of PnL, top market 25%. The z-score measures the hit
rate, not the breadth, and a z that high on a book whose residual is −32% this month is a
statement about two wallets. **No size increase here.**

---

## 4. Recommendations, ranked by expected value

### 1 — LANE A (decision, 0h): **strike the clamp-escalation clause** from yesterday's
0.20–0.40 un-rail. Ship 2× of legacy-equivalent or nothing; never the $100 clamp.

**Hypothesis.** The escalation ("raise to the clamp once ex2 ≥ +15% on 150 legs") would
expand the band's weakest clip tier at the exact moment the tier is proven weak, and the
≤$20 cap is doing real work rather than starving the band.

**Measurement.** `scripts/profit-clip-effect.py` §2 and §5. 0.20–0.40 legs above $25:
**12 legs / 7 wallets / $626 / −18.4%** — the only tier in the band that loses money, and
the first sample of it larger than the 8-leg September objection that put the rail there.
Within wallet and price bin, the ≥$18 tier books **−18.3pp** against the $10–18 tier.

**Decision rule.** Delete the escalation. Keep the 2× step, priced at **+$11.7/day**, and
cap any 0.20–0.40 clip at twice legacy-equivalent.

**Refutation.** If 25 settled 0.20–0.40 legs at clip ≥ $25 book **≥ the band's own rate**,
the escalation was right and should be restored.

**Expected effect:** avoids expanding a −18.4% cohort (≈ −$115 per 12 legs at that size);
preserves +$11.7/day. **Cost: 0h** — it is a deletion from a proposal that is still pending.

---

### 2 — LANE A (propose, 0.5h to card): **pre-register a breadth stop on the cheap band.**
Do not apply it today.

**Hypothesis.** 48.3% of notional sits in 0.00–0.20, which books +$697/$1k on the headline
and **−$190/$1k ex-top-2**, with a monthly residual of **+31.3% → +12.4% → −50.4%**; the
book's PnL is a two-wallet bond, and the correct response is a pre-committed cut, not a
guess made in the middle of a losing week.

**Measurement.** `scripts/profit-clip-effect.py` §1 and §9; `scripts/profit-band-rotation.py`
§1b. Cheap band 30d: 98 legs, $4,070 (48.3% of notional), +69.7% booked, −19.0% ex2,
clip $41.53, 27.6% at the $100 clamp. STANDARD's cheap cell: ex2 +3.7 → −16.4 → −32.4 by
month, 6 wallets in November.

**Decision rule.** On the next **100 settled cheap-band legs**, if ex-top-2-wallet ROI is
**≤ 0**, cut `c200LongshotBandFactor` 3.5 → 1.0 (clip $41 → ~$12). Do not act before the
100th leg.

**Refutation.** If those 100 legs come back with ex2 **≥ +20%** *and* the clamp cohort ≥ the
sub-clamp cohort, the trigger was wrong, the band is broad, and the factor should stay —
measure again at 250.

**Expected effect:** bounds the book's dominant risk. At −19% forward, the full notional
loses ≈$26/day; cutting two-thirds of it saves ≈$17/day of expected loss while forgoing
≈$63/day if the band keeps paying — which is why it is a trigger and not an action.
**Cost: 0.5h** to card, 0h to decide.

---

### 3 — LANE B (done): **the marginal-rate instrument, and the standing pricing rule.**
Performed directly, no approval needed, nothing about the bot changed.

**Hypothesis.** Sizing proposals in this book are routinely priced at the average rate; a
marginal-rate read plus a break-even slippage line would have caught the $16.9 → $11.7
error before it was published.

**Measurement.** `scripts/profit-clip-effect.py` §8 prints, for each paying band, the
doubling shadow at the cohort's own rate and the **break-even entry slippage** — the price
worsening at which the added notional stops paying: **15.7c** in 0.20–0.40 (mean entry
0.311), **6.8c** in the cheap band (mean entry 0.124, i.e. 55% of the price). The mid-band
number is the answer to "is a thin-book boost real": at a $13 clip the fill can be 15c worse
and the added dollar still breaks even, so fillability is not the binding risk here — size is.

**Decision rule.** Every future Lane A sizing proposal must quote (a) the cohort rate,
(b) the marginal-tier rate, (c) the break-even slippage. A proposal missing any of the
three is not ready.

**Refutation.** If, on the next 150 legs, the marginal-tier coefficient comes back ≥ 0
with a CI excluding zero, the discount is an artefact and pricing at the average is
correct again.

**Cost: 0h** (shipped with this file).

---

**IF YOU WEREN'T HERE:** strike the escalation clause and hold the 0.20–0.40 step at 2×
(+$11.7/day, not +$16.9), and pre-register the cheap-band breadth stop at ex2 ≤ 0 over 100
legs. Do not add size anywhere: the marginal dollar is worth 18pp less than the average and
the best-looking cell in the book (STANDARD cheap, z = +3.7) has a November residual of −32%.

---

## 5. Contradictions, corrections, dead ends

- **My own naive within-wallet read was a price artefact and I am not quoting it.** §3
  compares each wallet's big-clip ROI to its small-clip ROI with no price control and
  returns **−232.9pp** in the cheap band (0/4 wallets better on the big clip). That is the
  payoff identity, not sizing: a win at 0.05 returns +1900%, at 0.19 +426%, so a wallet
  whose small legs sit lower in the band looks like it "earns more on small clips". Adding
  2c price bins moves the pooled estimate from −41.7pp to −18.3pp. Same class of error as
  yesterday's share-count assertion: the self-test was the thing that caught both.
- **The rail's 8-leg objection is now 12 legs, and it still holds** (−18.4% at ≥$25 in
  0.20–0.40). I proposed un-railing this band yesterday on the grounds that the rail's
  evidence was thin; the thin evidence reproduced.
- **Do not read the 4x shadows as available.** STANDARD cheap: +$79.25/day at the 30d rate
  is arithmetically right and decisionally wrong — 6 wallets in November, ex2 −32.4%.
- **Not re-litigated:** the 0.004 drift bar (correct: it refuses +10.4pp bargains in
  0.20–0.40 and −21.9pp / −29.8pp legs above 0.60); the 0.40–0.60 skip; the $100 clamp
  itself (stays at $100 — cutting a +46% clamp cohort is not a trade); exit alpha (its
  measured CIs span zero in every read since 2026-10-28); the 25-slot track list (no
  candidate-level flow measurement exists, so the flow gain is still an estimate).
- **Live negative flow, measured and not proposed:** shttr 0.20–0.40 **−7.8%** on 97 legs
  30d (−$71.4, $30/day at risk, CI [−33.7, +19.2]) and std 0.60–0.80 **−24.3%** on 18 legs
  (−$61.7, $8/day). Together ≈ −$4.4/day. The CIs span zero and no size lever moves them;
  they are logged as ceilings on what tuning can buy, not as proposals.
- **Rates vs levels.** The book is $121.43/day at +43.2% on 16.3 legs/day and $281/day of
  notional; peak in-flight $740 = 14.6% of the $5,064 cap. Capital is not the constraint,
  and after today's discount, neither is the clip.

---

## 6. Instrument

`scripts/profit-clip-effect.py` (read-only): allocation-vs-breadth per dollar; clip-tier
table with market-clustered CIs; within-wallet paired contrast with a wallet bootstrap;
two-way fixed effects (clip tier + 2c price bin + wallet) with market-clustered SE and a
no-price-FE robustness arm; per-band FE; the 0.20–0.40 rail test with entry-price columns;
30-day lane × band; and the under-sized-cell audit. `--self-test` fails on a broken payoff
identity, a zero-stake leg in an ROI denominator, or an uncovered band/tier.

**Two instrument notes worth recording.** (a) Price bins *nest* bands, so including both
leaves the design rank-deficient by exactly the number of band dummies; I verified the
`clip ≥ $18` coefficient is identical under `pinv` and `lstsq` before shipping the design.
(b) Units: the payoff identity is `pnl = ntl×(1−p)/p` on a win and `−ntl` on a loss; it
holds on 1,273 of 1,273 resolved legs, which is what makes every ROI here dollars-over-
dollars rather than a share-count approximation.

**No prisma write. No RuleSet row touched. No rule, size, gate, threshold or exit changed.**
Recommendation 1 is a deletion from a pending proposal, 2 is a pre-registered trigger, 3
shipped as an instrument.
