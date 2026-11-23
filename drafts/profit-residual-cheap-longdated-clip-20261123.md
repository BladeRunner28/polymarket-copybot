# Cap C-200 on its long-dated cheap clips — the cell is real, but $40 is the weakest of the four arms and the card's own evidence is 2.5× overstated

**Card** `profit-residual-cheap-longdated-clip` · approvals id `apr-profit-residual-cheap-longdated-clip` · lane A ·
**PROPOSAL ONLY — nothing applied.** No `apply-vNN` run, `prisma/dev.db` not written, nothing merged.
`RuleSet` still reads **v73**: `minTimeToResolutionHours = 2`, `kellyMaxSizeUsd = 100`,
`staleExitHours = 24`, `staleExitAdverseMove = -0.15`, `staleExitHardHours = 168`.
**Instrument** `scripts/profit-longdated-clip.py` (read-only, DB `mode=ro`, `--selftest` 7/7, S7 6/6).
Base read: 578 legs / 476 markets / 32 wallets / 26.3 days, book −$91.05 (−0.8%), **2026-11-23**.

---

## 1. Key insight

**The cell is real and the dollar case survives; the card's hit-rate evidence does not, and its
parameter is the weakest of the four arms available.**

1. **The row the card quotes is not the cell it names.** `profit-clip-tier.py` S4 cuts
   ≥$40 × ttr≥168h and does **not** apply the price filter. The quoted row is **13 legs / $1,200 /
   mean price 0.16**; the cell in the card's title (px<0.20) is **12 legs / $1,100 / mean price 0.107**
   — same −$221.45, because the 13th leg is a $100 clip at **px 0.81** that booked exactly $0.00.
   Consequence: the "0/13 at a 16% break-even = 10.4% chance" is computed on a price-blind mean that
   mixes eleven cheap tickets with one favourite. On the cell as scoped, **P(all 12 lose) = 25.3%**,
   and on the **7 legs that carried any risk, 37.6%**. The hit-rate evidence is *not* significant.
2. **What does carry the case is the dollar CI, not the win count.** −$221.45 on $1,100 is −20.1%,
   market-clustered CI **[−40.1, −5.9]** (excludes zero), ex-top-1 −22%, ex-top-3 −28% — and the
   cap's own delta CI is **[+$30.31, +$262.38]** over 12 distinct markets. Both intervals exclude zero
   while the fair-pricing null does not: this is a **magnitude** finding, not a rate finding.
3. **$40 is the worst of the four arms the same 12 legs price.** The cell is **entirely ≥$40**
   (eleven $100 clips and one $50) — there is not a single cheap long-dated leg below $40 in the
   regime — so a $40 cap here is a **cell-wide cap**, not a tier cut, and every lower cap is strictly
   better: $40 → +$4.77/day, $25 → +$6.14/day, $20 (the lane's own legacy ceiling) → **+$6.60/day**,
   full skip → +$8.43/day. The card's $40 has no measured basis: it is `−221.45 × 0.6`, an
   arithmetic that also over-counts by $7.65 because two of the twelve legs are **$50** clips
   (rescaled to 80%, not 40%). The card's "+$132.87 = +$5.27/day" is **+$125.22 = +$4.77/day**.
4. **The 168h boundary is structural, not fitted** — it is `staleExitHardHours`. A leg whose
   time-to-resolution exceeds the hard exit **cannot resolve inside the hold**: **30.0%** of C-200's
   ttr≥168h legs ever resolved vs **88.3%** below it. That cohort is a seven-day mark trade on a
   30–200-day instrument, which is why it loses 18.4% while the rest of the lane is flat (−0.3%).
   This is the mechanism, and it means a cap **salvages dollars from a structural defect** rather
   than monetising a measured edge.
5. **The λ̂ refit card is not a substitute for this one.** The card pre-registers "withdraw this
   entirely if `profit-lambda-owned-population` lands first — the cap only truncates the output of a
   funding input that card corrects." Measured (§6): the `kellyMaxSizeUsd` cap **binds at every
   candidate λ̂ down to −0.20** at these prices (size = $100 at λ̂ ∈ {−0.68, −0.531, −0.30, −0.28,
   −0.20}, and $85.25 only at −0.112). The refit changes the label on the decision, never the clip.
   The "approve one of the three" framing is therefore void: **only this field moves these dollars.**

---

## 2. What the card claimed vs what I measured

| card claim | measured 2026-11-23 | verdict |
|---|---|---|
| "px<0.20 AND ttr≥168h: **13 legs**, $1,200, −$221.45, mean price **0.16**" | the px-scoped cell is **12 legs / $1,100 / mean 0.107**; the 13th leg is px **0.81**, $100, PnL $0.00 | **row mismatch** — S4's row is clip × tenor only |
| "0/13 at a 16% break-even has a **10.4%** chance under fair pricing" | 0/12 at their own prices → **25.3%**; 0/7 on the legs that carried risk → **37.6%** | **overstated 2.5×**; the hit rate is not evidence |
| "$40 cap … **+$132.87 = +$5.27/day**" | **+$125.22 = +$4.77/day** (CI [+30.31,+262.38]); the rescale applied 40% to two $50 legs | **arithmetic slip**, −$7.65 |
| "S6 confirms zero overlap with the floor" | holds, and more strongly than stated: the cell's **minimum** ttr is **488h** (range 488–5,056h), so no floor at 24h can ever touch it | **confirmed** |
| "the floor removes 32 of those 53 legs (the entire −$904.44)" | today the ≥$40 / 2-24h tier is **33 legs / −$904.44** (one leg added in the 5 days since) | **stale by one leg**, no sign change |
| "13 legs, 0/13 won" | **7 of the 12 carried risk** (5 booked exactly $0.00 with `fillStatus='unfilled'`); **45.2%** of the loss is one **resolved** total loss at 5.9c | the sample is 7 legs, not 12 |

Everything else in the card reproduces exactly: the ≥$40 tier is the whole book's loss
(54 legs / $5,100 / −$766.19 / −15.0%; everything under $40 is +$675.14), and the post-floor
cheap survivors are 17 legs / +$94.65, of which the 12-leg long-dated slice is −$221.45 and the
5 legs at 24–168h are **+$316.10 (+63.2%)**.

---

## 3. The cell, leg by leg

12 legs, 5 wallets, 12 distinct markets. `funded` = the sizing path: **every leg is above
`BOT_LIMITS.BANKROLL_200.max = $20`, which only the Kelly path can do** (`clampPaperSize(size, botId,
kellyMaxSizeUsd)`), and the dispatch log confirms it for two of them
(`[KELLY] will-ethereum-reach-2700 … band=[0,0.2) λ̂=-0.680 q=0.414 p=0.185 size=$100.00`).

| opened | size | px | PnL | mark now | exit | ttr (h) | market |
|---|---:|---:|---:|---:|---|---:|---|
| 11-01 | 100 | 0.093 | −47.82 | 0.049 | early | 5,056 | will-liverpool-win-the-2026-27-english-premier-league-epl-championship |
| 11-05 | 100 | 0.183 | −20.90 | 0.145 | early | 613 | will-ethereum-reach-2700-in-november-2026 |
| 11-06 | 50 | 0.089 | −8.07 | 0.075 | early | 1,357 | will-spacex-have-the-highest-ipo-market-cap-2026-516 |
| 11-06 | 100 | 0.059 | **−100.00** | 0.000 | **resolved (NO)** | 1,330 | will-susie-wiles-be-the-next-to-leave-the-trump-cabinet-before-2027-628 |
| 11-08 | 100 | 0.067 | 0.00 | 0.095 | early | 1,297 | will-nicols-maduro-be-the-leader-of-venezuela-end-of-2026 |
| 11-08 | 100 | 0.143 | −16.27 | 0.120 | early | 1,283 | us-x-iran-effective-ceasefire-by-december-31 |
| 11-08 | 100 | 0.069 | 0.00 | 0.095 | early | 488 | will-chang-san-cheng-win-the-next-taoyuan-mayoral |
| 11-08 | 100 | 0.089 | 0.00 | 0.075 | early | 5,045 | will-morena-win-the-most-seats-in-the-2027-election |
| 11-09 | 100 | 0.103 | 0.00 | 0.085 | early | 518 | will-apple-be-the-largest-company-in-the-world-by-market-cap-on-december-31-291 |
| 11-10 | 100 | 0.050 | 0.00 | 0.042 | early | 3,407 | will-the-denver-broncos-win-the-2027-nfl-league |
| 11-10 | 100 | 0.163 | −17.34 | 0.135 | early | 711 | will-the-fed-increase-interest-rates-by-25-bps-after-the-december-2026-meeting |
| 11-10 | 50 | 0.173 | −11.05 | 0.135 | early | 1,237 | will-toy-story-5-have-the-3rd-best-domestic-opening-weekend-in-2026 |

Three facts this table settles:

- **It is not the exit selling the bottom.** Mark-to-today on the same legs is **−$221.46** against
  **−$221.45** realised: the adverse marks persisted. The "just hold them" alternative is dead on
  this population, independently of `profit-exit-counterfactual.py`'s hold-to-resolution arm.
- **It is one resolved total loss plus six adverse marks.** The single resolution carries 45.2% of
  the loss; the other six lose 12–25% of stake on marks that never came back.
- **Half the sample took no risk.** 5 of 12 booked exactly $0.00 with `fillStatus='unfilled'`; they
  contribute nothing to realised PnL and nothing to any cap delta, which is why the effective n is 7.

---

## 4. The arm ladder — what a cap actually buys

Market-clustered bootstrap (resample `marketId`, 2,000 draws) on the **delta**, not on the ROI.

| arm | binds | delta | 95% CI | per day |
|---|---:|---:|---|---:|
| cap $40 (the card) | 12/12 (7 with risk) | **+$125.22** | [+30.31, +262.38] | +$4.77 |
| cap $25 | 12/12 (7 with risk) | +$161.31 | [+43.17, +331.91] | +$6.14 |
| **cap $20** (BOT_LIMITS ceiling) | 12/12 (7 with risk) | **+$173.34** | [+47.84, +354.58] | **+$6.60** |
| skip the cell | 12/12 (7 with risk) | +$221.45 | [+66.14, +445.24] | +$8.43 |

Every arm has a CI that excludes zero, and the ladder is monotone by construction (paper PnL is
linear in size at a fixed exit): so **the only open question is how much of this cell to keep, not
whether to keep it**. A skip captures 100% and forbids learning anything forward; a $20 cap
captures 78% and keeps the leg in the book as a live sample. Given the fair-pricing null is 25–38%,
keeping the sample is worth more than the extra $1.83/day.

**One interaction that decides the scoping.** The sign of a *price-only* cap depends entirely on
whether the 24h floor is live — today it is **not** (`minTimeToResolutionHours = 2`):

| cap | no tenor filter, pre-floor | no tenor filter, **post-floor** | tenor-scoped |
|---|---:|---:|---:|
| $40 | +$606.01 (+$23.06/d) | **−$64.44 (−$2.45/d)** | **+$125.22 (+$4.77/d)** |
| $20 | +$740.13 (+$28.17/d) | **−$79.54 (−$3.03/d)** | **+$173.34 (+$6.60/d)** |

The pre-floor column is the floor's dollars counted twice — the trap `profit-recs-20261122.md §4`
already caught once. Post-floor, a price-only cap is **negative**, because the 5 legs at 24–168h
that survive the floor are **+$316.10**. **The tenor filter is the whole reason the cap is positive**,
and it is what makes this lever additive to the floor (+$216.8/week) instead of a duplicate of it.

---

## 5. Why the boundary sits at 168h (and why that is not curve-fitting)

`staleExitHardHours = 168`. Split C-200 there:

| cohort | n | at risk | PnL | ROI | CI | reached resolution |
|---|---:|---:|---:|---:|---|---:|
| ttr < 168h | 418 | $8,586 | −$28.88 | −0.3% | [−16.3, +18.9] | **88.3%** |
| ttr ≥ 168h | **20** | $1,317 | **−$242.15** | **−18.4%** | **[−35.6, −5.8]** | **30.0%** |

The long-dated cohort is the only part of the lane whose interval excludes zero, it is **0/20
profitable**, and two thirds of it never reaches an outcome — it is closed by a calendar exit at a
mark. The loss is not confined to the cheapest price band, though that is where the dollars are:

| ttr≥168h, by price | n | PnL | ROI |
|---|---:|---:|---:|
| px<0.20 | 12 | −$221.45 | −20.1% |
| px 0.20–0.40 | 5 | −$20.70 | −25.6% |
| px ≥0.60 | 3 | $0.00 | 0.0% |

Boundary sensitivity (§S5): the cut is sharp and the neighbours disagree, which is what a structural
boundary looks like rather than a fitted one — ≥24h is **+$94.65** (21 legs), ≥72h is **+$269.16**
(14 legs), **≥168h is −$221.45** (12 legs), ≥720h is −$183.21 (8 legs).

**Caveat that travels:** this is also why the *skip* arm is not yet safe. Everything between 72h and
168h is carried by 2 legs worth +$490.61; a cut placed 96h earlier would invert the sign of the whole
rule. The 168h boundary is defensible because it is the exit's own horizon, not because the tenor
curve is smooth.

---

## 6. The interaction the card got wrong — the λ̂ refit does not shrink this clip

`q = Φ(Φ⁻¹(p) − λ̂)`, `size = kellyFraction · (q − p)/(1 − p) · available`, clamped at
`kellyMaxSizeUsd`. At the cell's own mean price and today's cash:

| p | λ̂ −0.680 (at booking) | λ̂ −0.531 (live) | λ̂ −0.300 | λ̂ −0.280 | λ̂ −0.200 | λ̂ −0.112 |
|---|---:|---:|---:|---:|---:|---:|
| 0.107 | q 28.7% → **$100** | q 23.8% → **$100** | q 17.3% → **$100** | q 16.8% → **$100** | q 14.9% → **$100** | q 12.9% → $85.25 |
| 0.135 | q 33.6% → $100 | q 28.4% → $100 | q 21.1% → $100 | q 20.5% → $100 | q 18.3% → $100 | q 16.1% → $100 |

Every λ̂ above −0.112 books the maximum clip. `profit-lambda-owned-population-20261120.md §6`
reaches the same conclusion from the other side ("the clip is a `kellyMaxSizeUsd`/cap problem; λ̂ is
a correctness problem"). So the two cards are **complements, not alternatives** — the card's own
"approve one of the three" instruction should be retired, and the withdrawn $25 band cap stays
withdrawn (post-floor it reaches 17 legs worth +$94.65 and costs $64–107 to cap).

---

## 7. Blast radius — what this does not touch

- **STANDARD: nothing.** `BOT_LIMITS.STANDARD.max = $20.00`, so a C-200-scoped field cannot reach it;
  and standalone STANDARD long-dated legs are 10 legs / −$0.91 (flat), so there is nothing to salvage.
- **The 5 cheap legs at 24–168h: nothing** (+$316.10). This is the population a price-only cap would gut.
- **The cheap band at ttr<168h: nothing** — 88 legs, −$254.94 (−6.8%, CI includes zero). That loss is
  the cheap band's own card's business, not this one's.
- **The px 0.20–0.40 long-dated legs: nothing** (5 legs, −$20.70, $81 at risk) — too thin to act on;
  watch item, not a rule.
- **No leg is retro-edited**, no booked figure moves, no admission count changes (a cap does not
  re-select), so the skip histogram and the daily reports stay comparable.

---

## 8. Proposal

### P1 (recommended) — ship the field, defaulted OFF, at **$20**, scoped `px < 0.20 AND ttr ≥ 168h`

**+$6.60/day** (+$173.34 on 12 legs, delta CI [+$47.84, +$354.58]).

Why $20 and not $40:

- **$20 is not a new parameter.** It is `BOT_LIMITS.BANKROLL_200.max`, the ceiling the lane already
  applies to every non-Kelly leg. The Kelly override exists to let Kelly size *above* it where
  Kelly's edge is measured; in this cell the edge claim is the λ̂ input that §6 shows cannot be
  validated on the population we own and cannot even change the clip. "Kelly may not exceed the
  lane's own ceiling where the instrument outlives the exit" is a one-sentence rule with a code
  referent, not a fitted number.
- **$40 keeps no upside worth keeping.** The cell has 0 profitable legs in 12; the 40% that $40
  preserves is 40% of a losing draw.
- It dominates $40 by **+$1.83/day** and its interval also excludes zero.

### P2 — if the operator wants the number the card approved

Same field, same scope, value **$40**: **+$4.77/day** (CI [+$30.31, +$262.38]). One string changes.

### P3 (not recommended yet) — card a **skip**, do not run it

A full skip of the cell is **+$8.43/day** and is better on both point estimate and mechanism (you
cannot hold a 200-day instrument for 7 days and expect the price to mean anything). It is held back
for one reason: it is an admission gate on 20 legs whose fair-pricing null is 25–38%, and the cheap
band loses at *both* tenors (−$254.94 below 168h), so a tenor-scoped skip would remove 46% of a
loss that belongs to a wider card. Convert P1/P2 to P3 only when the forward sample in §9 fires.

### 8b. Implementation (for the apply step, which is yours, not mine)

- **Field** `c200LongDatedClipCap: string`, `DEFAULT_RULES` value `""` (off ⇒ byte-identical to
  pre-vNN). Syntax `"<lo>-<hi>:<minTtrHours>:<capUsd>"`, e.g. `"0.0-0.2:168:20"`.
- **Helper** `applyBandClipCap(sizeUsd, price, ttrHours, spec)` in `src/lib/band-size.ts`, reusing
  the existing `parseBandRange` and its **lo-inclusive / hi-exclusive** convention (so it cannot
  disagree with `isInBandRange`/`applyBandSizeFactor` about a boundary). Empty, malformed, inverted,
  `ttrHours` null/NaN, or `capUsd <= 0` ⇒ unchanged.
- **Call site** `src/lib/paper.ts`, immediately **after** `size = clampPaperSize(...)` and inside the
  `botId === "BANKROLL_200"` branch — downstream of both the legacy band map and the Kelly clamp, so
  nothing can resize past it.
- **Plumbing: none needed.** `params.maturityTtrHours` is already threaded for every leg at
  `scripts/score-trades.ts:1286` and is decision-time ttr (v68) — no new data dependency, no
  lookahead. Rename it `entryTtrHours` in the same change if the naming bothers you; it is one
  declaration and two uses.
- **Interlock** `src/lib/rule-field-guard.ts` refuses to store a field with zero readers, which is
  exactly the trap that has left `c200BandClipCaps` inert since 2026-11-12 (0 readers, absent from
  the active ruleset, guarded in `tests/rule-field-guard.test.ts`).
- **Boundary tests before any apply** (evaluate through loader → field → helper, never off the DB
  row): px exactly 0.20 ⇒ untouched; px 0.199 ⇒ capped; ttr exactly 168 ⇒ capped; ttr 167.9 ⇒
  untouched; ttr null ⇒ untouched; the 5 legs at 24–168h untouched; px 0.20–0.40 long-dated
  untouched; STANDARD untouched; a ruleset lacking the field behaves exactly as pre-vNN.
- **Apply script** `scripts/apply-vNN-c200-longdated-clip.ts` on apply-v73's shape (`--yes` to write,
  `--revert` writes `""`, bare run prints the plan). Not written by me; the apply belongs to you.
- **Revert:** set the field back to `""`. One field, no PaperTrade row touched, no re-baseline of any
  published number.

---

## 9. Decision rule and refutation (pre-registered)

**Ship defaulted OFF.** Turn it on when the forward sample confirms, or immediately if you would
rather stop the bleed than accumulate more evidence — the measured basis already clears the card's
−10% bar; what is thin is n.

- **Forward gate, corrected for flow.** The card's "forward 30 legs" is **~65 days** away: this cell
  opens **0.46 legs/day** (12 legs / 26.3 days) and only **7 of 12 carry risk**. Use money legs:
  **6 forward long-dated cheap legs carrying risk ≈ 22 days**, requiring ROI ≤ −10% with a
  market-clustered CI excluding zero on the delta.
- **R1 refutation — retract the cap:** 6 forward money legs in this cell at ≥ 0 EV. Under fair pricing
  the observed 0/7 has a **37.6%** chance of happening by luck, so this is a live possibility and the
  retraction is not a formality.
- **R2 refutation — widen the rule instead:** if the 24h floor flips *and* the forward ttr<168h cheap
  slice turns negative, the tenor axis is the wrong discriminator and this becomes a lane-wide cheap
  band card. Re-read §4's post-floor column before assuming the cap still works.
- **R3 — if `staleExitHardHours` changes, re-read.** The boundary is derived from it. Move the exit
  horizon and the 168h scope loses its justification.
- **R4 — if the λ̂ refit lands:** re-run `scripts/profit-longdated-clip.py` §S6. If any candidate λ̂
  stops saturating `kellyMaxSizeUsd`, the clip falls on its own and this field becomes redundant.

---

## 10. Reproduce

```bash
python3 scripts/profit-longdated-clip.py            # S1..S7, the numbers above
python3 scripts/profit-longdated-clip.py --selftest # 7 arm/rescale checks
python3 scripts/profit-clip-tier.py                 # the card's own S1/S4/S5/S6 (unchanged)
```

Dashboard: `http://127.0.0.1:3013/drafts/profit-residual-cheap-longdated-clip-20261123`

## Overridable flags — one line each, with the number that moves

1. **Cap value $20 vs $40** — +$6.60/day vs +$4.77/day. Override = the string in
   `c200LongDatedClipCap` (`"0.0-0.2:168:20"` / `"0.0-0.2:168:40"`). Revert = `""`.
2. **Tenor filter present vs absent** — present: **+$6.60/day**; absent (price-only cap, post-floor):
   **−$3.03/day**, because it caps the +$316.10 slice. Dropping the `:168:` segment of the string
   reproduces the losing arm.
3. **Cap vs skip** — +$6.60/day vs +$8.43/day. Skip costs the forward sample (fair-pricing null
   25–38%); carded as P3, not run.
4. **Standalone vs after the 24h floor** — no interaction: the cell's minimum ttr is 488h, so the
   floor can never touch it. The cap is additive to the floor's +$216.8/week, not double-counted.

---

## IF YOU WEREN'T HERE

One sentence: C-200's long-dated cheap clips (12 legs, all $100-ish, ttr ≥ 7 days) lost $221 in 26
days — 0 for 12, and two thirds of that cohort never resolves before the 7-day hard exit fires, so it
is a mark trade, not a forecast — and the cheapest fix is to stop Kelly booking its $100 maximum on a
10.7c ticket that cannot settle inside the hold. The card said $40; the measurement says $20 is worth
more, a full skip is worth most, and the evidence for any of them is a 7-leg dollar interval, not a
win rate.
