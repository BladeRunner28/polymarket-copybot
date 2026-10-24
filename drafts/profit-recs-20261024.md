# Profit review — 2026-10-24

http://localhost:3013/drafts/profit-recs-20261024

**Every band ROI in this book — including mine from yesterday's instrument, and my own first cut
three hours ago — is contaminated by conditioning on how a position ENDED.** A leg that ran to
resolution and a leg that was expired when its market died are not two samples of the same
population; in STANDARD they never share a market (0 of 2,305), and they disagree in sign in
three of five bands. So I re-priced all 12,199 finished legs at what their market actually
settled at, using the archived CLOB resolution record, and the band map the last six reviews
argued over flattens almost to nothing.

On that basis the one thing that is both large and wrong is not a band. It is **the bottom sliver
of the cheap tail, which carries the biggest clips in the book and has never won a market.**

Reproduce: `python3 scripts/profit-velocity.py` → `data/profit-velocity-latest.txt` (§AA–§AF are
new in this commit, plus `data/market-truth-clob.json`, `data/cheap-tail-fill-probe.json`).

---

## 1. The instrument that made the old numbers wrong

`§AD`. Settlement truth for **11,146 of 12,199** finished legs (91.4%), from
`clob.polymarket.com/markets/<conditionId> → tokens[].winner`, cached and committed so the section
re-runs offline. The join is name-matched on the token we actually bought (`FNATIC`, `Under`,
`Yes`), not guessed from an index.

**Validation, because an instrument that cannot fail is not an instrument:** for the 3,177 resolved
legs, truth PnL must equal `realizedPnl` by identity — both are `n·(s/p − 1)`. Max absolute
difference: **$0.005**, i.e. the rounding of the position size. If that number were not ~0 the
table would be unreadable.

**The basis difference, on the same band:**

| C-200 0.60–0.80 | legs | notional | ROI |
|---|---|---|---|
| `status='resolved'` only | 203 | $885 | **+25.1%** |
| every leg, at settlement (`§AD`) | 479 | $2,294 | **−0.7%** |

The +25% is the subset whose market reached resolution. That subset is a selection on outcome, not
on decision. I built the resolved-only table first today and nearly shipped it as the review's
central finding; it is wrong, and the correction is the reason §AD exists.

What survives, on truth, all-time, both lanes:

- **<0.20 — $12,201, +71.9%**, CI **[+11.5, +137.5]**, ex-top-10 +21.6, ex-top-3-markets +31.6
- 0.2–0.4 — $18,984, +5.2% [−13.5, +26.0]
- 0.4–0.6 — $49,119, +8.7% [−14.6, +30.6] (90d: **−10.6%**)
- 0.6–0.8 — $19,660, +4.4% [−4.7, +12.0]
- **0.8–1.0 — $20,356, −4.4%** [−11.1, +1.2], ex-top-10 −4.7, ex-top-3-markets −5.4

Book total: **$120,320 of notional, ≈ +$14,000** on truth. The cheap tail is 10% of the notional and
63% of the profit.

**Three claims in the standing baseline do not survive this basis, and I am reporting them rather
than quietly dropping them:**

1. *"64.4% of acted trades sit above 0.50, where edge is negative."* On truth, ≥0.50 nets to roughly
   **flat**: 0.6–0.8 +4.4%, 0.8–1.0 −4.4%. It is a 0.8–1.0 phenomenon, it is CI-including-zero, and
   its 90d read is **+0.3%**. The standing claim is not reproducible as stated.
2. *"0.4–0.60 is the only CI-negative band."* On truth, 90d, it is **−10.6% [−23.4, +2.4]** all-lane
   and **−11.9%** on STANDARD — **v63 vindicated on the best basis anyone has used for it yet**
   (all-time +8.7% is pre-regime history). Not reopening it.
3. Yesterday's TTR floor and 10-22's ≥0.60 stop are untouched by this: neither is a band-edge claim.

## 2. The exit apparatus is a wash, and the tempting repair would have cost $6.8k

`§AB`. This is the first time any leg in this book has been compared to *settlement* rather than to
another mark. 6,503 of 7,369 STANDARD closed legs priced (88%):

- as executed: **+$1,904 (+2.8%)** · held to settlement: **+$1,694 (+2.5%)** · **exit alpha +$211**
- market-clustered CI on that alpha: **[−$3,231, +$3,658]**

The wash is made of two large, opposite, structural errors, split by whether we sold above or below
our entry:

- **sold into strength** — 4,024 legs, $40,652: **+$6,768 of alpha (+16.7%)**. Selling early beat
  holding by 16.7% of notional.
- **cut into weakness** — 2,427 legs, $27,946: **−$6,417 of alpha (−23.0%)**. Holding beat cutting
  by 23%.

That split is the trap. The obvious repair suggested by the second line is "stop expiring dead
slugs at the last mark — the archived CLOB knows the winner, 88% of the time". Applied to the
whole population it would *gain* $6,417 on the weakness half and *lose* $6,768 on the strength
half: **net −$350.** The mark we expire at is not stale-low; it is momentum-extrapolated, which is
why it is too low where price collapsed and too high where price ran. Symmetric repair, zero
expectation.

**Verdict: no change to exits.** Not because the exits are good — 23% of notional in error is
bad — but because the two errors cancel and nothing in the data says which way to lean. The one
thing this does establish: `§AB`'s 90d alpha (+$544 on $38,347) is the same order as its CI, so
every future exit proposal should be required to beat ±$2.5k before it is discussed.

## 3. Why the band axis is now exhausted — from a third direction

`§AD` ex-top-3-markets, all-time: `<0.20` **+31.6%** · 0.2–0.4 **−3.2%** · 0.4–0.6 **−9.2%** ·
0.6–0.8 **+0.1%** · 0.8–1.0 **−5.4%**.

Remove each band's three best markets and **nothing in the book pays except the cheap tail**. The
"gates are exhausted" verdict was reached from shadow reads; this is an independent confirmation
from settlement truth and from the tail-robustness direction. It also explains it: bands were never
the variable. A handful of individual markets are.

That kills, permanently, the class of proposal that says "shift size from band X to band Y" — except
at the bottom, where the two halves of the cheap tail are not the same bet at all.

## 4. The sub-0.05 region: the largest clips in the book, zero settlement wins

`§AE`, the cheap tail decomposed:

| sub-band | legs | markets | notional | clip | avgP | hit | truth ROI | ex-top-10 | ex-3-mkts | realized |
|---|---|---|---|---|---|---|---|---|---|---|
| **0.00–0.05** | **66** | **33** | **$1,694** | **$25.66** | 0.034 | **0.0%** | **−100%** | −100% | −100% | **−$1,041** |
| 0.05–0.10 | 253 | 131 | $4,469 | $17.66 | 0.072 | 14.5% | +98.7% | −11.3% | +13.8% | +$5,491 |
| 0.10–0.15 | 155 | 84 | $2,754 | $17.77 | 0.126 | 25.3% | +98.0% | +10.9% | +0.3% | +$2,626 |
| 0.15–0.20 | 240 | 105 | $3,285 | $13.69 | 0.169 | 33.4% | +102.2% | **+49.9%** | **+30.5%** | +$3,175 |

Two facts, and they point in opposite directions:

- **The bottom sliver is the biggest bet in the book.** Average clip **$25.66**, against $13.69 in
  the cell that actually survives tail removal. C-200 alone: 29 legs, $1,381, **$47.62 average, $100
  maximum**, at an average price of **0.034**.
- **It has never won.** 0 of 66 at settlement; 0 of 33 markets. Realized −$1,041 (−61%); on truth,
  −$1,694 (−100%). The six legs in that region with positive realized PnL are early exits whose
  markets settled at zero — which is exactly the "sold into strength" alpha in §2, not a win.

The code puts it there on purpose. `paper.ts:59` — `if (entryPrice < 0.2) size *= longshot` — applies
`c200LongshotBandFactor` (**3.5x**, the largest factor in the ruleset) with **no lower bound**, and
`applyKellyBandRails` then *floors* Kelly at that size ("must never shrink the one proven winner").
So the book is not drifting into 0.002-priced lottery tickets; it is instructed to buy them at 3.5x
and forbidden from shrinking them. 46 STANDARD legs are open there right now at an average entry of
**0.0029**.

**The honest discount, stated before the pitch:** 0/66 is not proof of mispricing. At a fair price
of 0.034 you expect ~2.2 wins in 66 draws; seeing zero is a ~10% event. This is not "the region is
mispriced" — it is "the region has no measured edge, the break-even hit rate is 3.4%, we have hit
0.0%, and it is the single largest position size the book takes". A fair-priced bet at 3.5x the
size of a proven one is a sizing error even when it is not a pricing error.

## 5. Fillability, measured for the first time

`§AF` (Lane B, read-only, no bot behaviour touched). Live order books for 22 open positions below
0.20, depth on the side we would have to buy — as printed by the committed run:

- within **+1c**: median **$128** (p10 $17, p90 $4,283) — **10.8x** the current clip
- within **+2c**: median **$1,881** (p10 $21, p90 $8,073) — **229x** the current clip
- within **+5c**: median **$6,085** (p10 $98)
- books that cannot carry 2x the clip within +2c: **2/22 (9%)**; 10x: **6/22 (27%)**

**Instrument caveat, because this one is a snapshot and not a measurement:** the +1c median read
**$1,452 (105x)** on the run 20 minutes earlier and **$128 (10.8x)** here. One deep book in or out of
a 22-name sample moves it 10x. The load-bearing numbers are the +2c depth (~$1.9k in both runs) and
the 9% / 27% book fractions, which did not move.

So the standing caveat — *thin books dominate every cheap-tail result* — **does not bind at current
sizes**: median +2c headroom is two orders of magnitude above the clip, and only 9% of books cannot
absorb a doubling. It binds if a clip goes up ~10x, or in the p10 tail ($17–21 of depth), which is
where the sub-0.05 names live.
The breakeven entry slippage that would erase the 0.15–0.20 edge is **16.4 probability points ≈
9.7¢ per share** — we would have to pay 0.266 instead of 0.169 to lose it. That is the number that
authorises an up-size there; it is not the headline ROI.

---

# RECOMMENDATIONS

## #1 — Put a floor under the longshot size factor: 0.05, not zero. LANE A, proposed.

**Hypothesis.** Entry prices below 0.05 have no measured edge, require a 3.4% settlement hit rate to
break even, and receive the largest clips in the book; scoping the longshot factor (and its Kelly
floor) to `entryPrice >= 0.05` raises realised PnL per dollar of cheap-tail exposure and removes the
book's largest variance source.

**Measurement.** `scripts/profit-velocity.py` §AE (sub-band decomposition on settlement truth),
§AF (fill headroom), against the live map in `paper.ts:45-64` (`mapBankroll200Size`) and
`applyKellyBandRails`, active RuleSet **v66**
(`c200LongshotBandFactor = 3.5`, `longshotMaxPrice = 0.2`). Cost basis: dollars at risk.

- 0.00–0.05: **66 legs / 33 markets / $1,694 / clip $25.66 / avgP 0.034 / hit 0.0% / −$1,041 realized**
- 0.05–0.20: **648 legs / $10,508** / clip **$16.22** / **+98% to +102% truth ROI**, ex-3-markets
  positive in two of three sub-bands, **+30.5% in 0.15–0.20**

**Decision rule.** Act when the region has ≥50 settled legs, a settlement hit rate **below its own
average entry price** (the break-even), and a clip ≥1.5x the lane's own 0.05–0.20 clip. Met and
exceeded: 66 legs, 0.0% vs 3.39%, $25.66 vs $16.22 pooled — and on C-200 alone **$47.62 vs $26.11**.

**Refutation.** Withdraw if, in the 30-day forward shadow of the blocked region, 0.00–0.05 candidates
settle as wins at **≥5% (≥3 of 60)** — above break-even with margin, meaning the region is fairly
priced and the floor is pure opportunity cost. Second clause: withdraw if the 0.05–0.20 cell's truth
ROI falls **below 0% on a 60-day read**, which would mean the cheap tail is not the edge and the
freed size had nowhere to go.

**Effect.** Removes **−$1,041 realized / −$1,694 truth** all-time and frees **$1,381 of C-200
notional** (29 legs at −62%) to be redeployed in a cell earning ~+98%. Removes the $100-clip-at-0.002
exposure, which at ladder scale is the fastest-growing loss in the book: the 3.5x factor means this
region grows three and a half times faster than every correctly-sized one. **Cost: 1h** — two keys
(`c200LongshotBandFactor` scope in `mapBankroll200Size` + the matching Kelly rail; STANDARD's floor
reuses the existing `standardSkipBandRange` as `0.00-0.05,0.4-0.6`).

**Fillability note:** this REMOVES volume, so no fill assumption is smuggled in.

## #2 — Move that size to 0.15–0.20, where the edge survives every tail cut. LANE A, shadow-gated.

**Hypothesis.** The robust half of the cheap tail is 0.15–0.20 — the only sub-band with positive
ex-top-10 (+49.9%) and ex-top-3-markets (+30.5%) — and a flat 3.5x across `<0.20` under-sizes it
relative to 0.05–0.10, whose ex-top-10 is **−11.3%**.

**Measurement.** §AE (sub-band truth table), §AD (band table, ex-tail columns), §AF (depth vs clip).
Clip in 0.15–0.20 is $13.69 vs $17.66 in 0.05–0.10 — the larger clip is in the weaker cell.

**Decision rule.** Raise the 0.15–0.20 factor 3.5 → **4.5** only if (i) median +2c book depth stays
≥20x the resulting clip — **met, 228x** — and (ii) the shadow's first 100 forward legs hold truth ROI
**≥ +40%**, roughly 40% of the measured +102%.

**Refutation.** Revert if 0.15–0.20's ex-top-10 ROI falls **below 0% on 150 forward legs**, or if the
§AF p10 depth falls below the new clip (i.e. >20% of books cannot carry it).

**Effect.** +$600–950 all-time-equivalent at today's volume, and it is a *rate* change that scales
with the ladder. Breakeven slippage 9.7¢/share authorises it. **Cost: 1h.**

## #3 — Nothing else. Named dead ends, so they stop coming back.

- **Exit machinery (strength/weakness split).** Measured, net +$211 with a ±$3.4k CI; the two errors
  are opposite and symmetric; the dead-slug resolution repair would net −$350. Do not touch. §AB.
- **Any "shift size between bands" proposal above 0.20.** Ex-top-3-markets kills every band but the
  cheap tail (+31.6% vs −5.4% to +0.1%). §AD. This is the end of the band axis, not a new argument
  about it.
- **The ≥0.80 ceiling.** Two independent populations agree in sign (truth −4.4%, ex-tail −4.7%/−5.4%)
  but the CI includes zero and the band is already dying of attrition: $13,777 of notional in July,
  **$36 in the last 30 days**. A rule here would be a rule about a band the book has stopped trading.
- **C-200's band map is validated, not broken.** On truth it skips 0.4–0.6 (−3.8%) and halves
  0.6–0.8 (−0.7%) — both correct calls. This is the opposite of what the resolved-only table said
  this morning, and it is why I did not ship that table.
- **Reopening 0.4–0.60 on STANDARD.** 90d truth −10.6% [−23.4, +2.4]. v63 stands, third confirmation.

**IF YOU WEREN'T HERE:** I would put a hard floor at 0.05 on both lanes before the next scan — not
because of the $1,041, but because this book's motto for three months has been "the cheap tail is
the only edge", and the bottom of that tail is where it parks 3.5x size on a 3.4%-break-even lottery
while the 0.15–0.20 cell it should own gets a smaller clip.

---

## Lane B (instrument only — no bot behaviour touched, no RuleSet edited)

`scripts/profit-velocity.py`, +6 sections (871 → 1,520 lines): §AA calibration (hit rate vs price,
where `ROI = (hit−p)/p` is exact), §AB exit alpha vs settlement, §AB-validation, §AC high-price
audit, §AD truth-based band table, §AE cheap-tail decomposition, §AF fill probe. New committed
data: `data/market-truth-clob.json` (3,970 markets, the resolution record this whole review rests
on), `data/cheap-tail-fill-probe.json`.

**Two defects found in my own instrument before shipping, both caught by the numbers disagreeing
with themselves:**

1. The first band table was resolved-only. It reported C-200 0.6–0.8 at **+25.1%**; the same band on
   truth is **−0.7%**. Conditioning on `status='resolved'` is conditioning on the exit path. §AD
   exists because of it, and the resolved-only numbers are no longer quoted anywhere in this draft.
2. The first cut of §AE reported "0 wins in 66 legs" from the truth join while `realizedPnl > 0` on
   six of them. Both were right: those six are early exits whose markets settled at zero. The
   section now prints realized and truth side by side so that cannot be misread again.

## Contradictions I am not resolving silently

1. **My own first number today.** C-200 0.6–0.8 at +25.1% (resolved-only) vs −0.7% (truth). The
   second is the answer; the first is in this draft only as the demonstration.
2. **"Above 0.50 the edge is negative"** (standing baseline, quoted in three prior reviews) vs ≥0.50
   flat on truth (+4.4% / −4.4%) with a 90d read of +0.3% on the negative half. Either lane-specific
   or dead; not a book-level fact.
3. **The code's own justification for the longshot factor** — `trade.ts:161` cites the `<0.20` band as
   "the only +PnL band: +$94.59 on 64" and `paper.ts` calls it "the one proven winner". On truth the
   band is +71.9% *in aggregate* and −100% in its bottom third. Both statements are true of different
   populations, which is precisely why the factor needs a floor rather than a value change.
4. **Fillability.** §AF says depth is 228x the clip in the median book and $17–21 in the p10. Both are
   real; the second is where the sub-0.05 names live and it is a second, independent reason to leave
   that region.
