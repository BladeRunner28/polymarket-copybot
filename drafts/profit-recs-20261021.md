# Profit review — 2026-10-21

**Verdict: the band doctrine is finished, and it finished without me. v63 applied the dead-zone skip to STANDARD ~16h ago, so the one CI-negative band in the book is now closed on both lanes. What remains is a book with exactly one CI-positive band, and the thing blocking it is not a threshold — it is that we do not know what happens when we put more money through a 10-cent book.**

Every number below comes from `scripts/profit-band-report.py --v2`, committed with this file. Cost basis is `simulatedPositionSize` (dollars at risk), verified against raw rows: a resolved win books `realizedPnl == size*(1-p)/p` to the cent. That check and the Jensen correction are new today — see §0.

---

## 0. Three things I got wrong or nearly got wrong

I am listing these first because two of them were load-bearing at some point during this run.

**(a) I nearly quoted an identity that does not hold.** I wrote a "hit-implied ROI" column as `(hitRate − meanPx)/meanPx` and it printed **−0.64%** for STANDARD against a true equal-weight **+7.47%**. The shortcut replaces `E[1/p]` with `1/E[p]`; by Jensen those differ whenever p varies. The exact statement is per-leg — `ROI = (won − p)/p` — and break-even hit rate is `p` *leg by leg*. Aggregating across a price distribution is not linear in the hit rate. The column is removed from the script, and every hit-rate figure below is labelled as calibration (probability points), never as ROI.

**(b) My wallet-null was degenerate, so I threw it out rather than use it.** A permutation null on per-wallet ROI returned `p95 == p99 == observed max` on every one of 2,000 reps. Cause: ROI's denominator is the wallet's own notional, so the maximum is always taken by the smallest book. I replaced it with an out-of-sample persistence test (§4). The failed version is documented in the script docstring so nobody rebuilds it.

**(c) The 37pp lane gap I found is NOT an execution gap.** On 557 matched (wallet, market) pairs, C-200 books **+49.9%** and STANDARD **+13.0%**. Tempting headline. But the median time delta is **0.0h** and the median price delta is **0.0c**; the mean (+0.9c) is carried by the 28% of pairs that differ by more than 2¢. Both lanes book entry at their own detected price (STANDARD −0.22¢, C-200 −1.33¢ vs `detectedPrice`). So (wallet, market) does not identify a unique trade, the pairing is contaminated, and the gap is **composition**, not latency. I am not using it as evidence for anything.

**(d) Last run's capital-days figure does not reproduce, and the reason is a mixed basis.** It quoted **1,033,886** open capital-days against **566,915** for all finished history. Recomputed on a consistent deduped basis (§L): **377,981** open vs **220,837** finished. The ratio survives almost unchanged (**1.82× → 1.71×**) but the levels are ~2.7× apart because the open side was summed over legs while the count was reported in deduped bets — deduped open notional is **$5,381**, not $13,623. I am quoting the deduped pair throughout, and the conclusion ("the open book holds more capital-days than every trade ever completed") is unchanged.

---

## 1. Where the edge actually is — priced against the spread it has never paid

`src/lib/copy-cost.ts:34` states it plainly: *"the paper fill crosses no spread and pays no fee."* So every ROI this project has ever quoted is gross. Fees on Polymarket peak at p=0.50; spread as a fraction of **stake** peaks at low p. Those rank the bands in opposite directions, so I measured it rather than asserting it: `MarketSnapshot` carries bid/ask, and I can price the cost for **4,153 of 4,153 legs (100%)** at half the quoted spread.

Trailing 90d, deduped, market-clustered CIs, net of half-spread:

- **<0.20 — +69.0% [+11.4, +136.4]** · 402 legs · 19.3% of notional · costs **10.01% of stake** in spread and still pays
- 0.2–0.4 — +10.2% [−2.8, +24.7] · 722 legs · 18.5% · cost 2.90%
- **0.4–0.6 — −8.6% [−15.4, −2.3]** · 1,742 legs · 34.6% · cost 2.78%
- 0.6–0.8 — +1.4% [−4.4, +6.7] · 903 legs · 19.3% · cost 1.67%
- 0.8–1.0 — −1.0% [−6.4, +3.7] · 384 legs · 8.4% · cost 1.01%

Read that as a portfolio: **one band with an edge, one band with a leak, three bands that are indistinguishable from zero.** Net of the full spread the picture hardens — 0.6–0.8 goes to **−0.3%** and 0.8–1.0 to **−2.0%** — but those CIs still include zero, so they are zeros, not losses, and I am not proposing to cut them.

The dead zone's sign deepens rather than washes out once you charge it the spread it never paid: **−5.9% gross → −8.6% net**, and the CI tightens to [−15.4, −2.3].

### Calibration, which is the basis-independent version of the same question

For a BUY at p the break-even hit rate is exactly p. Measured:

- <0.20: pays **0.101**, hits **21.9%** → **+11.8pp [+6.9, +17.5]**
- 0.2–0.4: 0.313 → 37.4% → **+6.1pp [+1.9, +10.3]**
- 0.4–0.6: 0.498 → 46.4% → **−3.4pp [−6.3, −0.6]**
- 0.6–0.8: 0.686 → 67.0% → −1.6pp [−5.0, +1.9]
- 0.8–1.0: 0.884 → 86.5% → −1.9pp [−6.7, +2.3]

Per lane, and this is the sharpest single line in the review:

- **STANDARD: avg entry 0.526, hit 52.9%, edge +0.3pp** (n=2,348)
- **C-200: avg entry 0.313, hit 47.8%, edge +16.5pp** (n=1,805)

STANDARD is not "worse at picking" — it is perfectly calibrated to the price it pays. It has no informational edge at all, and it is that way because it buys at 0.526. C-200 buys at 0.313 and is a fifth of a point from being a fair coin.

---

## 2. Breadth — the cheap band's edge is real; its ROI is a tail, and both are true

This is the distinction that decides whether to size up, and last run's draft only had half of it.

| Band | markets | wallets | ex-5 legs | ex-10 legs | H1 edge | H2 edge |
|---|---|---|---|---|---|---|
| <0.20 | 284 | 63 | +30.6% | **+7.0%** | +11.3pp | **+11.3pp** |
| 0.2–0.4 | 567 | 105 | +8.9% | +6.2% | +9.3pp | +3.4pp |
| 0.4–0.6 | 1,330 | 139 | −6.7% | −7.5% | −1.8pp | **−5.4pp** |
| 0.6–0.8 | 730 | 84 | +2.4% | +1.8% | −0.8pp | −2.2pp |
| 0.8–1.0 | 291 | 28 | −0.6% | −1.2% | +0.1pp | **−6.8pp** |

The cheap band's **calibration edge is identical in both halves of the sample** (+11.3pp, +11.3pp) across 284 markets and 63 wallets. That is the most stable statistic in the book. Its **dollar ROI** is still tail-driven — remove its 10 best legs and +79.0% becomes +7.0%.

Both facts are load-bearing and they point the same way: the edge is in the probability, not in the payout. Which means **sizing up the cheap tail raises variance far faster than it raises expectation**, and with ~4.5 cheap legs/day on a $500 bankroll that is a variance decision masquerading as an EV decision. I am not recommending a clip increase on this band.

---

## 3. The lane anatomy nobody has written down

- **STANDARD**: +$972.32 on $31,198 = **+3.12%**. Its <0.20 book is +$1,162.52 on $2,434 = **+47.75%** — **7.8% of its notional produces 120% of its profit.** Everything else is **−$190.20 on $28,763 = −0.66%**.
- **C-200**: +$6,572.23 on $15,245 = **+43.11%**. <0.20 is +$5,926.18 on $6,537 = **+90.65%** (42.9% of notional), and **everything else still makes +7.42%**.

C-200 has a portfolio. STANDARD has one convexity and a 92% book that loses money. And STANDARD's cheap book is thinner in every direction: ex-10 legs **−24.9%** (vs C-200's −10.1%), top wallet **41%** of its cheap PnL (vs 25%), 157 markets (vs 189).

PnL basis, 90d deduped — worth knowing before anyone reads a "win rate":

- STANDARD: early exits +$313.90 on $18,137 (+1.73%); settlements +$658.42 on $13,061 (**+5.04%**)
- C-200: early exits +$3,003.66 on $9,289 (**+32.34%**); settlements +$3,568.57 on $5,956 (**+59.92%**)

### Where the open book actually is — and the asymmetry that decides the exit question

471 open bets (deduped), **$5,381** notional, MTM +$119.27, weighted age **70.2 days**, **377,981 capital-days** — against **220,837** capital-days for all 5,013 finished bets in history. The open book holds **1.71×** the capital-days of every completed trade in the project.

But the stranded capital is not spread evenly. It is almost entirely in one band:

- **0.8–1.0: 287 bets · $3,054 · MTM −$6.83 · 62.4% of all stranded capital-days · 77.2 days old**
- 0.4–0.6: 47 bets · $639 · 10.3%
- <0.20: 54 bets · $636 · 10.3%
- 0.6–0.8: 46 bets · $572 · 9.1%
- 0.2–0.4: 37 bets · $480 · 8.0%

And here is the sentence that settles where an exit rule belongs. A held BUY at p can still return at most `(1−p)/p` on its stake, so remaining upside per band is:

- **<0.20: $636 of stake still has $29,949 of upside left — 47× its own capital**
- **0.8–1.0: $3,054 of stake still has $261 of upside left — 0.086× its own capital**

A 550:1 difference in remaining payoff per stranded dollar, in opposite arms of the same book. The largest, oldest block of frozen capital is the one with the least left to win: **11.7:1 against, held for 77 days.** That is the actual reason to act on exits — not the dead zone, which is now closed to new flow, and not the shallow "1.29M positions" framing. It is that 62% of the stranded book is sitting in positions that cannot pay much more.

---

## 4. Wallet rank has no forward information (axis 4, finally measured)

Split the 90d book at its midpoint (2026-08-30). Rank the 16 wallets with ≥4 legs in H1 and ≥3 in H2 by H1 ROI, then look at H2:

- H1 **top** third: H1 **+27.5%** → H2 **+31.8%**
- H1 **bottom** third: H1 **−21.6%** → H2 **+130.2%**
- Spearman rank correlation H1 vs H2: **−0.018** · permutation p = **0.942**

The wallets that looked worst did best. With n=16 wallets this is not proof of anti-skill, but it is a clean failure to find persistence, and it is the multiple-testing answer this project has never had: 226 wallets were screened, and the per-wallet ranking is what a screen of 226 looks like when there is nothing underneath it.

**Consequence:** sizing is currently driven by `walletQualityScore` → copyScore → confidence → Kelly. On this evidence the wallet layer has admission value at best and **no sizing value**. The band is the thing that predicts; the wallet is not. (This also explains why the band doctrine — not wallet selection — is where every dollar of measured improvement has come from.)

---

## 5. What v63 already did, and what v54 proved

`standardSkipBandRange = "0.4-0.6"` shipped in **v63** (2026-10-20 15:59). I found it while preparing to propose the same thing. **Last run's Rec #1 is applied** — as a hard skip on STANDARD, which is stronger than the ×0.5 I would have proposed. `scripts/score-trades.ts:998` reads it and `scripts/verify-v63-band-skip.ts` probes it. The last STANDARD dead-zone leg opened 2026-10-20 08:59, i.e. before v63, so the rail has had no organic flow yet — the probe exists for exactly that reason and I ran it rather than waiting.

v54's band map on C-200 is the one production experiment available, and it moved the lever:

| | dead-zone share of notional | cheap share | lane ROI |
|---|---|---|---|
| C-200 pre-v54 | 25.9% | 29.6% | +15.5% |
| C-200 post-v54 | **5.4%** | **56.2%** | **+70.6%** |
| STANDARD pre-v54 | 38.9% | 6.6% | +2.6% |
| STANDARD post-v54 | **45.4%** | 10.0% | +7.9% |

The share shift is mechanical and verified. The ROI improvement is confounded with v55–v64 and with the cheap band's own luck, so I am not claiming attribution — only that the lever does what it says.

**The recency contradiction you should hold onto:** STANDARD's dead zone is **−6.9% over 90d but −0.7% over 30d** (n=77) and **+1.0% over 14d**. Its calibration edge by window is −3.4 / −6.4 / −0.5pp (90/60/30d). The band's *loss* has faded; its *no-edge* has not. v63 removed a band that had stopped bleeding — the case for it is capital efficiency, not loss avoidance, and saying otherwise would be overclaiming. Meanwhile C-200's dead zone calibration is *deteriorating* (−3.2 → −4.7 → **−6.2pp**, n=246 at 30d) but v62 already caps its notional share at 5.4%.

---

## RECOMMENDATIONS — ranked by expected value

### #1 — STANDARD gets the stale exit, scoped 0.2–1.0, with <0.20 explicitly exempt

**Hypothesis.** STANDARD's hold time is set by market term rather than information decay because the entire stale-exit block is scoped `botId === "BANKROLL_200"` (`scripts/update-pnl.ts:240`), so 62.4% of the book's stranded capital-days sit in 287 ≥0.8 bets that hold $3,054 of stake against only $261 of remaining upside — and extending the exit will cut stranded capital-days by more than half while making money on the bands it applies to, provided it is scoped to exclude the cheap band, which is the one band an exit rule destroys.

**Measurement.** `scripts/profit-band-report.py --v2` §G for the lane split, plus the project's own pre-registered instrument `data/band-exit-exemption*.json`, which marks every cut ticket to its counterfactual settlement. That instrument already answers the question per band, and it says the cut is right-signed in the middle of the book and wrong-signed at the bottom:

- 0.2–0.4 all-time: cuts **−$75.92** vs settlement **−$333.83** (41 priced) → **cut wins**
- 0.4–0.6: cuts **−$51.65** vs settlement **−$83.57** (41 priced) → **cut wins**
- <0.20: cuts **−$179.63** vs settlement **−$38.82** (5 priced); second arm cuts −$191.85 vs settlement −$19.95 (n=10) → **cut loses**

The cheap-band arms are below the instrument's own ≥20-priced guarantee rule, so I am reading direction, not magnitude. The direction is exactly what convexity predicts: a time-stop on a bet whose payoff is `(1−p)/p` monetises the loss and forgoes the win, so **you cannot time-stop a longshot**. That is the reason for the exemption, and it is the part of this recommendation that is new — last run proposed the exit without it.

**Decision rule.** Adopt for 0.2–1.0 when (i) the exemption instrument shows cuts beating settlement on ≥20 priced tickets in that band — **met** in 0.2–0.4 and 0.4–0.6 — and (ii) a 168h replay over deduped STANDARD legs cuts capital-days ≥50% while booked PnL falls <$150/90d. Condition (ii) has not been run yet and is the gate; this is a proposal to run it and ship on the result, not a ship-now.

**Refutation.** If the 168h replay costs more than $150/90d, or if it makes the ≥0.8 band worse than −8% (monetising noise and paying spread to do it), the exit is wrong and hold-to-settlement stands. Second refutation: if exempting <0.20 is unnecessary — i.e. the cheap band still returns >+40% net *after* a 168h stop on the replay — then the exemption was superstition and should be dropped rather than kept "for safety".

**Expected effect.** Capital-days **377,981 → ~170,000** (the ≥0.8 block alone is 235,685 of it), concentrated where the payoff arithmetic says it should be: the 287 open ≥0.8 bets hold **$3,054 of stake against $261 of remaining upside** at 77 days. PnL **±$150/90d** either way. This is bought for turnover and solvency, not profit, and I will not dress it up as more. The prior that makes it more than housekeeping is the project's own instrument: cuts beat settlement by $258 in 0.2–0.4 and by $32 in 0.4–0.6, and lose by $141–$172 at <0.20.

**Cost.** 3h.

---

### #2 — Price the cheap band's capacity from the recorded L2 before any size-up

**Hypothesis.** <0.20 is the only CI-positive band in the book (+69.0% net, [+11.4, +136.4], edge stable at +11.3pp in both halves of the sample across 284 markets), and the only reason it is 19.3% of notional rather than 40% is that **we have never measured whether the book absorbs size at that price** — so every capacity decision is being made on a fill assumption that nobody has tested.

**Measurement.** The recorded L2 in `data/l2/` (per-asset book) and `data/l2-events/` (`{ts, price, side, size, bestBid, bestAsk}` prints). For each <0.20 admission, walk the recorded book at the entry timestamp and compute the **volume-weighted fill price for 1×, 2×, 4× and 8× the clip actually taken**, then re-cut the band's ROI at each. This is the missing term in every cheap-tail result this project has produced, flagged as unmodelled in two consecutive reviews.

The number to beat is already known: the cheap band tolerates entry going from **0.101 to 0.213 (+112% worse)** before its edge is gone, and it absorbs **10.01% of stake** in quoted spread. So the question is not "is it thin" — it is "how many multiples of the current clip fit inside a 112% price tolerance".

**Decision rule.** Recommend a clip increase for <0.20 only if the VWAP fill at **4× the current clip** stays inside the band's break-even entry (≤0.213) on **≥70% of admissions**. If 4× breaches it on more than 30% of admissions, capacity is the binding constraint and the correct response to the ladder is "more wallets", not "bigger clips".

**Refutation.** If the L2 walk shows 4× fills already beyond 0.213 on a majority of admissions, then my own framing of this band as under-owned is wrong — it is correctly sized and merely supply-starved, and any upweight would be paying slippage to convert a real edge into a real loss. That result would also retire the "cheap band is under-owned" observation permanently.

**Expected effect.** $0 direct; it gates the only remaining size decision. At 4× capacity the cheap band's contribution scales from ~$12/day to ~$48/day, which is the difference between the current run-rate and something that compounds — and it is exactly the number that a fantasy of scaling gets built on if it is left unmeasured.

**Cost.** 4–5h.

---

### #3 — Wallet quality stops setting size; it stays an admission filter only

**Hypothesis.** Per-wallet ROI has no forward information (ρ = −0.018, p = 0.942, H1-worst third → +130% in H2 vs +31.8% for the H1-best), so routing `walletQualityScore` into Kelly size is sizing on a noise variable — and in a book where one band pays +69% and another loses −8.6%, a noise variable in the size path is strictly worse than no variable.

**Measurement.** §4 of the committed script: half-split rank persistence with a permutation null on the top-minus-bottom H2 spread, plus `WalletProfile.globalScore` and `DecisionJournal.walletQualityScore` to confirm the field is on the sizing path today.

**Decision rule.** Strip wallet quality from the size calculation when the H1→H2 rank correlation is below +0.15 on ≥30 overlapping wallets. **Not met today** — the correlation is −0.018, which is below the bar, but it is measured on **16** wallets. So the honest state is: act when the sample supports it, and do not scale anything on wallet rank in the meantime.

**Refutation.** If, at ≥30 overlapping wallets, H1 rank correlates with H2 ROI above +0.30, wallet selection is real, the band thesis is incomplete, and the correct move is the opposite — rebuild sizing around wallet cohorts and revisit the band factors.

**Expected effect.** $0 direct. It is the guard on the most expensive available mistake: at a 22× flow gap and an unreachable daily gate, size is the lever everyone reaches for, and this is the evidence that the wallet ranking cannot be the thing that authorises it.

**Cost.** 1h to instrument, 0 to hold.

---

## IF YOU WEREN'T HERE

I would write the `<0.20` exit exemption into the rule *before* extending the exit anywhere, because the only CI-positive band in this book is the one an unscoped time-stop kills — and the evidence for that is the project's own exemption instrument, not my opinion.

## Lane note

**Lane B: one repair, done.** The band instrument now prices the spread the paper engine never pays (§1), on 100% of legs, and it fails loudly rather than silently: the wallet-null that returned a degenerate p-value is documented as broken in the script instead of being quoted. No rule was touched, no RuleSet row edited, no sizing changed.

## What I'd watch

The cheap-band capacity number from #2, and `standardSkipBandRange`'s first organic block. If the skip produces no block log line within ~3 days of real STANDARD dead-zone flow, the rail is not firing and that is a Lane B alarm, not a tuning question.
