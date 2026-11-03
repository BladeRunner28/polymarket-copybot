# Profit review — 2026-11-03

http://localhost:3013/drafts/profit-recs-20261103

**Cost basis on every ROI below: `simulatedPositionSize` = DOLLARS at risk, never shares.** A BUY of
`$n` at `p` is `n/p` shares, so settlement at `s` realises `n*(s/p − 1)`. Population: `isDemo=0`,
`DecisionJournal.ruleSetVersion ≥ 49` (the live regime: **1,168 resolved bets, 2026-09-06 → 2026-11-02,
57.4 days, $13,111 notional, +$3,168.84, +55.24 $/day**), bet-level = first leg per
`(wallet, market, outcome)`; the closed-leg population is printed alongside as a cross-check
(527 bets / $6,416 / +23.9%).
Every figure is produced by **`scripts/profit-robustness-alloc.py`** (new, committed with this file):

```
python3 scripts/profit-robustness-alloc.py --selftest    # hurdle / slippage / Kelly / band identities
python3 scripts/profit-robustness-alloc.py               # §1–§8, the whole report
```

Read-only (`mode=ro&immutable=1`). No RuleSet row written, no rule, size, gate or threshold changed.

---

## The finding: the biggest clip in the book is on the cell that is five bets deep

Every band table in this repo pools the two copy lanes. The lanes **disagree in sign inside the same
price band**, so the pooled numbers that have been driving sizing — "<0.20 is the only +EV bucket",
"0.4–0.6 is dead" — are lane averages that are wrong for one lane each. Split them:

| lane | band | n | mkts | clip | notional | ROI | hit vs hurdle | z | ex-top-5 ROI | ex-5 keeps | 95% CI (markets) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| main | <0.20 | 51 | 48 | **$31.64** | $1,613 | +61.9% | 21.6% vs 12.4% | 1.59 | **−56.1%** | **−81%** | [−49.7, +228.1] |
| main | 0.2–0.4 | 109 | 100 | $16.92 | $1,845 | +28.0% | 42.2% vs 32.7% | 2.00 | +10.5% | 34% | [−2.3, +60.4] |
| main | 0.4–0.6 | 197 | 162 | $18.00 | **$3,546** | −7.1% | 46.7% vs 51.5% | −1.36 | −13.8% | 184% | [−22.8, +8.9] |
| main | 0.6–0.8 | 126 | 112 | $17.64 | $2,223 | −0.9% | 67.5% vs 69.6% | −0.51 | −5.9% | — | [−14.2, +12.1] |
| main | 0.8+ | 16 | 14 | $18.12 | $290 | −8.8% | 75.0% vs 83.0% | −0.74 | −28.1% | — | [−39.2, +20.7] |
| shortttr | <0.20 | 65 | 63 | $18.83 | $1,224 | +112.4% | 23.1% vs 11.7% | 2.17 | +8.3% | 7% | [+10.0, +226.8] |
| shortttr | 0.2–0.4 | 145 | 140 | $8.75 | $1,268 | +24.9% | 39.3% vs 32.3% | 1.74 | +5.0% | 19% | [−4.6, +55.3] |
| shortttr | 0.4–0.6 | 307 | 290 | **$1.73** | $532 | +22.6% | 58.0% vs 50.9% | 2.52 | **+18.0%** | **76%** | **[+10.2, +34.9]** |
| shortttr | 0.6–0.8 | 152 | 147 | **$3.75** | $570 | +24.4% | 82.2% vs 69.8% | **4.00** | **+22.2%** | **86%** | **[+14.5, +32.6]** |

`hurdle = p*(1+r*(1−p))` at r=0.05 — the fee-adjusted break-even hit rate, not `p`. `z = (hit − hurdle)/SE(hit)`.

Three things fall out, and none of them is a gate result:

1. **The book's largest clip sits on its least reproducible cell.** `main <0.20` gets $31.64/bet — 8.4x
   the short-TTR 0.6–0.8 clip, 18.3x the short-TTR 0.4–0.6 clip — and its PnL is **108% of one market**
   (the Musk tweet-count 180–199 contract, +$1,076.47) while the other 47 markets net −$78. Drop the
   top five markets and the cell is **−56.1%**.
2. **The cells that survive every robustness test get dust.** short-TTR 0.4–0.6 and 0.6–0.8 are the
   only cells in the book where (a) the market-clustered CI excludes zero, (b) the top five markets are
   only 5% of cell PnL each, and (c) dropping them costs 14–24% of the cell's ROI, not 80%+. They are
   funded at **$1.73 and $3.75 per bet.**
3. **The dead zone is lane-dependent, and the rule is lane-blind.** 0.4–0.6 is −7.1% in the main lane
   and **+22.6% in short-TTR** (+18.0% ex-top-5, 290 markets, CI lower bound +10.2). `mapBankroll200Size`
   applies one `deadZone ×0.25` and one `premium ×0.5` to both lanes
   (`src/lib/paper.ts:105-113`), so the rule's harshest discount lands on the only mid-band cell that
   clears its CI.

### The Kelly test that decides size, not the headline

`f* = (b·ĥ − (1−ĥ))/b`, `b = (1−p)/p`. The question is not `f*` at `ĥ` — it is whether `f*` keeps its
**sign** two standard errors down, which is the formal version of "does the edge survive its own noise":

| cell | b | f* at ĥ | −1SE | −2SE | half-Kelly $ | clip |
| --- | --- | --- | --- | --- | --- | --- |
| main <0.20 | 7.40 | +11.0% | +4.4% | **−2.1%** | $457 (at point est.) | $31.64 |
| shortttr 0.4–0.6 | 1.01 | +16.6% | +11.0% | **+5.4%** | $690 | $1.73 |
| shortttr 0.6–0.8 | 0.45 | +43.1% | +33.2% | **+23.3%** | $1,795 | $3.75 |

`main <0.20` is the only positive cell in the book whose Kelly fraction **flips negative inside 2 SE of
its own hit rate**. That is a 51-bet, 48-market cell with an 11:1 payoff — the arithmetic says it cannot
carry the largest clip in the book, whatever its realized +61.9% says.

### Fill: 8–13 cents of tolerance, so thin books are not the binding risk on these cells

For a $1 stake at `p`, expected payoff is the hit rate, so ROI = 0 exactly when the effective entry
equals `hit`. Break-even entry slippage per cell: short-TTR 0.6–0.8 **+13.5c**, 0.4–0.6 **+8.4c**,
short-TTR <0.20 +11.9c, main <0.20 +9.7c. The cells I want to fund tolerate two orders of magnitude
more slippage than a tick. (Caveat that travels with the CIs: bets cluster by market, and an 18-char
event-prefix proxy gives 269 clusters vs 435 markets for the two robust cells combined, so the
intervals are ~10–20% too narrow. +10.2% does not become zero from that.)

### Multiple testing, stated rather than hidden

Nine cells were examined. Under a 9-cell correction the 5% bar is roughly `z ≥ 2.8`: **short-TTR 0.6–0.8
(z=4.00) survives, short-TTR 0.4–0.6 (z=2.52) does not.** The recommendation below steps them
proportionally rather than equally for exactly this reason.

---

## What is NOT the answer — measured today so it stops being re-proposed

- **Capital velocity / stranded capital: worth ~$0/day.** 420 of the 447 open STANDARD legs (94.5 days
  old, $4,462) are **pre-v49 legacy**; only 27 legs / $405 are regime, at 27 days. The forward book
  opens ~0.5 bets/day and holds them ~1–3 days. There is no live capital leak to recycle, and with
  ~$8.2k cash against $13.1k of notional over 57 days, capital is not the binding constraint either.
- **A maturity/horizon gate: nothing to block.** Only 18 of 1,168 regime bets were held beyond 7 days.
  (v68's TTR-at-entry schedule is approved and currently OFF — every maturity field is null in the live
  RuleSet v70 — so there is no inverted rule to revert either.)
- **The fee: settled yesterday** (27% of measured edge, 0 of 30 rung flips; withdrawal recommended).
- **Blocking main-lane 0.4–0.6: already carded, and it is worth $250/57d.** Not worth a new proposal.

---

## #1 — Lane A: stop charging the short-TTR lane the main lane's dead-zone tax

**Hypothesis.** The C-200 band map's mid/premium discounts were justified on a pooled population whose
dead zone is a main-lane phenomenon; applied to the short-TTR lane they suppress the book's two most
robust cells, and lifting them adds profit at unchanged per-bet risk of $3–15.

**Measurement.** `scripts/profit-robustness-alloc.py` §1/§2/§3/§4. short-TTR 0.4–0.6 (n=307, 290
markets): +22.6% ROI, CI [+10.2, +34.9], z=2.52, ex-top-5 +18.0%, f*(−2SE) +5.4%, slippage tolerance
8.4c. short-TTR 0.6–0.8 (n=152, 147 markets): +24.4%, CI [+14.5, +32.6], z=4.00, ex-top-5 +22.2%,
f*(−2SE) +23.3%, tolerance 13.5c. Mechanism: `src/lib/paper.ts::mapBankroll200Size` multiplies 0.4–0.6
by `deadZone` (0.25) and ≥0.6 by `premium` (0.5) for both lanes; removing a ×0.25 factor multiplies a
cell's clip by exactly 4.0, a ×0.5 by 2.0. Proposed change: two lane-scoped fields
(`shortTtrDeadZoneFactor` 0.25 → 0.5, `shortTtrPremiumFactor` 0.5 → 2.0), defaulted to today's values so
the shipped code is byte-identical until a RuleSet sets them — the v67/v68 pattern.

**Decision rule.** Adopt per cell when (a) its market-clustered CI excludes zero, (b) its ex-top-5 ROI is
≥ +10%, and (c) n ≥ 140 bets — both cells pass all three. Step the multiplier in proportion to measured
`z` (4x where z=4.0, 2x where z=2.5), never both at the larger step in one go.

**Refutation.** If, on the next 150 forward bets, either cell's CI lower bound falls below zero **or**
its ex-top-5 ROI falls below +8% **or** median realised entry slippage on those cells exceeds 4c (half
the smaller cell's tolerance), revert the factor to today's value and the hypothesis is dead.

**Expected effect.** §5 variant (a′): short-TTR 0.4–0.6 notional $532 × 1 × 22.6% = **+$120**; 0.6–0.8
$570 × 3 × 24.4% = **+$417** → **+$537.41 over 57.4 days = +$9.4/day** (+17% of the book's $55.24/day),
on +$2,242 of notional and clips of $3.46 / $15.00. Bankroll impact: 0.18% of net worth per bet at the
top of the range. **Cost: 1h** (two fields in `rules.ts` + lane-scoped lookup + one test).

---

## #2 — Lane A: no clip may exceed what its own two-standard-error Kelly supports

**Hypothesis.** Sizing is band-aware but error-blind: the book pays its largest clip ($31.64) to the one
positive cell whose Kelly fraction is negative at `ĥ − 2SE`, and pays $1.73–$3.75 to the two cells whose
Kelly stays positive at `ĥ − 2SE`. Sizing on the lower bound, not the headline, would move risk from the
five-bet cell into the distributed ones.

**Measurement.** §2: `f*(ĥ−2SE)` = **−2.1%** (main <0.20), **+5.4%** (shortttr 0.4–0.6), **+23.3%**
(shortttr 0.6–0.8). §1: main <0.20's best market is **108%** of the cell's PnL and ex-top-5 ROI is
−56.1% on 48 markets. Proposed cap: main <0.20 clip $31.64 → **$7.50** (0.24x), i.e. no cell carries a
clip more than ~2x the book's most robust cell unless its ex-top-5 ROI is positive.

**Decision rule.** Cap a cell's clip when `f*(ĥ−2SE) ≤ 0` **and** ex-top-5 ROI ≤ 0 **and** the single
best market ≥ 50% of cell PnL. Release the cap when the cell's next 100 bets print ex-top-5 ROI ≥ +10%.

**Refutation.** If the next 100 bets in main <0.20 hold ex-top-5 ROI ≥ +10% (i.e. the tail becomes a
distribution rather than five events), the cap is wrong, remove it, and the "5 bets" claim was a
small-sample artefact.

**Expected effect.** **−$762 over 57.4 days (−$13.3/day) in-sample**; §5 variant (a″) prices #1 + #2
together at **−$224.58/57d (+$51.33 $/day vs $55.24 today)**: roughly PnL-neutral and materially less
tail-dependent. This is a hedge, not an improvement, and I am labelling it as such: it forgoes the cell's
realized +61.9% to stop the book's month depending on one tweet-count contract. **Cost: 0.5h.** I would
**not** take it alone.

*The 4c slippage threshold in #1's refutation is half the smaller cell's measured tolerance (8.4c); for
scale, the STANDARD fill booth measured a median realised entry +0.50c worse than booked
(`drafts/standard-fill-aware-booking-20261029.md`), i.e. 8% of that tolerance.*

---

## #3 — Lane B: the C-200 ladder is ~3x phantom, and that is the scoreboard fact that matters

**Hypothesis.** The lane books one PaperTrade per dispatched intent at p(fill)=1; the resolver's stamped
verdicts now show that two-thirds of those intents were never positions, so every absolute ladder sum
(and the rung test, which reads absolute dollars) is ~3x too high even though the per-dollar ROI is fine.

**Measurement.** §7 of the same script, on the 410 legs stamped since 2026-10-28:
filled 138 legs / $1,333 / **+24.3%** / hit 47.4%; unfilled **275 legs / $2,750 / +25.7%** / hit 31.2%.
Reach rate **33.4% of legs, 32.7% of notional**; phantom PnL **$707.80 of the $1,032.17 booked (68.6%)**.
The near-identical ROI is the important part: this is **not** adverse selection (filled legs are not the
losers), it is a volume/bookkeeping fact — the edge per unit of notional survives, the absolute dollars do
not. For scale: the fee was 27% of booked PnL; the fill verdict is 68.6%.

**Decision rule.** Print modelled reach-rate and reach-weighted PnL as a **one-line EOD caveat** (not a
ledger column) when the 30-day reach rate stays ≤ 50% — the fee card's precedent: booking changes 0 of 30
rung verdicts, a print costs nothing. Card it; do not book.

**Refutation.** If a 30-day forward reach sample comes back ≥ 70%, then today's 33.4% is an artefact of
the 5-minute book window (a resting bid filling at minute 20 is invisible to this resolver) and the 3x
claim is void.

**Expected effect.** **$0 PnL.** It stops the ladder's direction being read off a sum that is 3x the
positions that existed, which is the difference between "$128/day and climbing" and "$46/day". **Cost:
0.5h** to card, 1h if the print is approved.

---

## Contradictions I am not resolving silently

- **"1,269 open legs / 357 bets / weighted age 76.3 days" does not reproduce.** Today: **464 open legs**,
  of which **420 are pre-v49 legacy** (94.5d, $4,462, mark +$132.28) and **27 are regime** (27.0d, $405,
  mark +$36.54). The stranded-capital story is real but it is *legacy residue*, not a forward leak — so
  it cannot be the lever it has been described as.
- **"64.4% of acted trades above 0.50"**: in-regime the ≥0.40 share is **68.3% of bets (798/1,168)** and
  **54.6% of notional ($7,161/$13,111)**. Direction reproduces, the number is basis-dependent.
- **"0.4–0.6 is the only CI-negative band"** is true pooled-for-main and **false for short-TTR**
  (+22.6%, CI [+10.2, +34.9]). Any future band claim must name the lane.
- **Yesterday's fee haircut (27%) vs today's fill haircut (68.6%)** are not comparable units: the fee is a
  cost on realized PnL, the fill verdict is a population count on position existence.

---

**IF YOU WEREN'T HERE:** I would ship #1 — two lane-scoped fields, defaults preserved, +$9.4/day at
$3.46–$15.00 a bet — and I would leave #2's cut on the table despite believing it, because it is the one
change here that loses money on the evidence in front of me and it should be your yes, not mine. The
larger truth is that #1 is the *whole* size prize available today: at $1.7–$15 clips and 57 days of
1,168 bets, no rule change in this book is worth more than ~$10/day, and the ladder's $250/day rung is
4.5x the entire book's current $55.24/day. Size, not selection, is what stands between this book and
rung 1 — and the only defensible place to add size is the two cells above.

---

### Provenance

| figure | source |
| --- | --- |
| lane × band table, hit vs hurdle, z, ex-top-5, best-market share | `profit-robustness-alloc.py` §1/§6 |
| Kelly at ĥ, ĥ−1SE, ĥ−2SE; half-Kelly $ | §2 |
| market-clustered 95% CI (2000 resamples of markets) | §3 |
| break-even entry slippage per cell | §4 |
| allocation counterfactuals (4x robust / 0.4x main <0.20 / robustness-weighted) | §5 |
| fill verdicts, reach rate, phantom PnL | §7 |
| open book by era and age | §8 |
| regime span 57.4 days, 1,168 bets, $13,111 | §0 |
| deadZone ×0.25 / premium ×0.5 mapping | `src/lib/paper.ts::mapBankroll200Size` |
| maturity fields null (v68 OFF), kellyFraction 0.5, shortTtrSizeUsd 10 | live RuleSet v70 `rulesJson` (read only) |
| net worth $8,323 for the half-Kelly column | `drafts/kelly-final-read-2026-11-03.md` |

*Lane B applied directly this commit: `scripts/profit-robustness-alloc.py`, this file, two roadmap cards
(`lane-scoped-band-factors` — Lane A proposal, not approved; `c200-fill-scoreboard-caveat` — measurement).
Read-only DB (`mode=ro&immutable=1`). **No RuleSet row written, no rule/size/gate/threshold changed, no
PnL row touched.***
