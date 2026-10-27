# Profit review — 2026-10-27

http://localhost:3013/drafts/profit-recs-20261027

**Cost basis on every ROI below: `simulatedPositionSize` = dollars at risk, never shares.**
Every figure computed by `scripts/profit-velocity.py` §AM (this commit) and §AN for the live-book
probe. Reproduce: `DATA_MODE=live python3 scripts/profit-velocity.py --only-am` (also runs in the
default pass; `--only-an-depth` for the probe alone).

---

## The week that just happened, and why the obvious fix to it is wrong

Seven days of realised PnL, end-dated by `resolvedAt` or `closedAt`:

| lane | legs | notional | realised | ROI |
| --- | --- | --- | --- | --- |
| STANDARD | 811 | $8,731 | **−$1,167.45** | −13.4% |
| BANKROLL_200 | 52 | $909 | **−$467.34** | −51.4% |
| both | 863 | $9,640 | **−$1,634.79** | −17.0% |

That is 12% of the book's all-time profit given back in a week. It is not spread: **one market is
68% of it and the worst three are 84%** — `will-flvio-bolsonaro-win-the-2026-brazilian-presiden…`.
That market's whole life, not just the week: **148 legs, $1,579 notional, 10 wallets, 71 days,
−$1,053.02, median clip $10.00.** It resolved NO and took the accumulated position with it.

My instinct was to cap it. The data says no (§AM.6). Peak *concurrent* notional per market, all
4,000 finished markets:

| peak concurrent $ in one market | markets | PnL | ROI | share of book PnL |
| --- | --- | --- | --- | --- |
| 0–25 | 2,950 | +$2,785 | +8.4% | 20.0% |
| 25–100 | 800 | +$2,493 | +6.6% | 17.9% |
| 100–200 | 170 | +$571 | +2.5% | 4.1% |
| **200–400** | 56 | **+$3,205** | **+20.1%** | **23.0%** |
| **400+** | 24 | **+$4,872** | **+20.0%** | **35.0%** |

**The deep, concentrated markets are the profitable ones.** A cap at 1% of STANDARD principal ($111)
would have forgone **$6,614** (market-clustered CI [−23,309, +4,033]); at 2% ($222), **$4,667**
([−19,524, +4,993]). Both CIs include zero, i.e. the capped dollars were worth *something*, not
nothing — and the point estimate says the cap costs money. **The concentration that produced this
week's loss is the shape of the only behaviour in this book that has ever paid at size.**
That is 10-22's refutation of a leg cap, confirmed today by a different construction (concurrency
rather than copy index) — two independent constructions, same NO-CHANGE. It does not come back
unless someone brings a measure of *risk*, not of return.

---

## The first measurement of the population we refuse

Every review so far has measured the book the bot owns. The bot refuses ~99% of what it sees, and
that refused population has no `PaperTrade` row — so "the gates earn their keep" has been an
assumption since September. `ObservedTrade` holds it: every print by a tracked wallet, copied or
not, at the wallet's own entry price. Joined to settlement truth (archived CLOB
`tokens[].winner`), it gives the counterfactual directly.

**8,282 bets in 3,691 markets, one row per bet (first print only), 2026-07-14 → 10-24:**

| arm | bets | mean rx | median rx | settle-win | edge |
| --- | --- | --- | --- | --- | --- |
| copied (we hold that exact bet) | 4,401 | +4.5% | +4.0% | 57.1% | **+0.1pp** |
| declined (same wallets, not taken) | 3,881 | +3.4% | +3.8% | 59.8% | **−0.9pp** |

Paired, market-clustered delta on calibration edge (declined − copied): **[−2.9, +1.4] pp over
1,731 markets that contain both arms.** *(edge = settle value − entry price, i.e. the pp by which
the hit rate beats the price paid.)*

**The admission stack does not discriminate.** Where it can be measured, the bets we refuse are
indistinguishable from the bets we take. What does predict is the **price band — and it predicts
the same in both arms:**

| band | copied n | edge | declined n | edge |
| --- | --- | --- | --- | --- |
| <0.20 | 284 | **+6.1pp** | 338 | +6.4pp |
| 0.2–0.4 | 637 | **+5.5pp** | 537 | +4.0pp |
| 0.4–0.6 | 1,656 | −0.1pp | 1,025 | −1.2pp |
| 0.6–0.8 | 975 | −0.8pp | 802 | −0.6pp |
| 0.8–1.0 | 849 | **−4.3pp** | 1,179 | −5.1pp |

Every paired band delta is inside ±1.5pp of zero. There is no band where admission helps, and none
where it hurts. Two consequences, both uncomfortable:

1. **The scoring stack's value is unproven in the population where it can be checked.** Not refuted
   — unproven, and the honest scope is narrower than it looks (see below).
2. **There is no flow to capture by loosening it.** In the last 14 days there were **35 declined
   bets against 134 copied bets (0.3:1)** in truth-covered markets. The 99% skip rate is not a pool
   of refused dollars sitting inside the markets we already trade; it is mostly decisions about
   markets we never entered, which this instrument cannot price because they have no settlement
   record.

**Scope, stated as a limit and not a footnote:** the declined arm here is *declined bets inside
markets the book was active in*. The gates' value may live entirely in which markets we enter at
all — and that half is unmeasurable without truth on markets we never touched.

**The defect this section almost shipped (§AM.3).** Counting *every print* instead of one row per
bet reverses the sign — copied −2.8% vs declined +7.5%, i.e. "the refused bets were better". That
is a price-averaging artefact: the copied arm averages 13.3 prints/bet against 6.9 for declined, so
per-print weighting favours whichever side the wallet kept adding to. Both versions print in §AM.3
so nobody quotes the wrong one; every number above is the first-print version.

---

## Where the money is, and the one line of code that pins it

The band is the axis with measured edge. STANDARD's realised clip by band (all-time, net of the
live 0.4–0.6 skip):

| band | legs | median clip | ROI | $/1k-capital-day | share of capital-days |
| --- | --- | --- | --- | --- | --- |
| <0.20 | 499 | $10.00 | **+83.1%** | +70.98 | 6.3% |
| 0.2–0.4 | 1,250 | $11.40 | +2.7% | +3.54 | 10.6% |
| 0.6–0.8 | 1,676 | $11.00 | +4.4% | +4.19 | 19.3% |
| 0.8–1.0 | 2,684 | $8.40 | **−3.5%** | −1.29 | **63.8%** |

And in the live era (opened ≥ 2026-09-15) the median clip is **$18.00 in every band** — identical,
not merely close.

The mechanism is not a missing idea, it is a pinned constant. `src/lib/scoring/trade.ts:381-390`
reads `deadZoneSizeFactor` and `longshotSizeFactor` on STANDARD's path **and both are 1.0 in v67**
— neutralised at v41 so the C-200 band map would not double-apply (their comment says so). Kelly
never took over: `scripts/score-trades.ts:826` guards the Kelly path on
`botId === "BANKROLL_200"`, so STANDARD still books `sweetSpotSizeUsd` = $18 whenever the score lands
in 70–79.9 or clears the $18 cap. **STANDARD has no band sizing at all — a factor of one, applied to
every price.**

What would sizing by band have produced? Realised shadow, notional-neutral, clamped to
`BOT_LIMITS.STANDARD {0.25, 20.00}` because `clampPaperSize` runs after any factor:

| window | legs | flat PnL | strong map 2.0/1.5/.5/.4/.2 | Δ | CI |
| --- | --- | --- | --- | --- | --- |
| all-time, all legs | 6,109 | +$5,232 | +$14,867 | **+$9,635** | [+42, +20,407] |
| all-time, **below the live 0.85 ceiling** | 3,710 | +$6,158 | +$11,225 | +$5,067 | **[−294, +11,134]** |
| 90d, below that ceiling | 2,302 | +$1,160 | +$2,854 | +$1,694 | **[−923, +4,296]** |
| live era ≥ 2026-09-15 | 184 | +$301 | +$446 | +$145 | **[−271, +674]** |

**The only CI that excludes zero is the one I must throw away.** 2,399 of the 6,109 all-time legs sit
above the live `standardMaxEntryPrice` = 0.85 ceiling — history the gate already refuses. Strip them
and every window's interval spans zero. My own shadow nearly shipped a result manufactured by
already-gated history; §AM.7 prints the ceiling-restricted line for exactly this reason.

Three things do survive, directionally, in every window: the delta is positive, the **inverse**
schedule (up-weight the top band) *loses* (−$1,620 / −$672 / −$80), and ex-top-10 ROI improves
(+9.8 → +18.5 all-time reachable; −2.2 → −0.4 over 90d). The ordering is real in sign. It is not
established in size.

---

## #1 — Give STANDARD a band size factor, in a shadow ledger first. Lane A, proposed.

**Hypothesis.** STANDARD's size is a band-blind step function of score (a factor of 1.0 on both band
fields), so realised PnL rises when notional is reallocated from 0.6–1.0 into <0.40 at constant
notional, and the effect survives the inverse-schedule control.

**Measurement.** `scripts/profit-velocity.py` §AM.7 — `PaperTrade` closed+resolved, realised,
net of the live `standardSkipBandRange`, restricted to legs below the live
`standardMaxEntryPrice`, PnL scaled linearly in notional, clamp {0.25, 20.00}, market-clustered
bootstrap (1,500 reps) on the PnL **delta** vs flat. Four windows printed.

**Decision rule.** Ship the strong map when a forward shadow — same legs, predicted size recorded,
zero decision influence — shows a delta **> 0 with a market-clustered CI excluding zero on ≥150
forward legs, AND ex-top-10 ROI improves ≥3pp**. Today: point estimate positive in all three
reachable windows, CI includes zero in all three (best case +$5,067 on $44,001, +11.5pp of ROI).
**Not met. Hence shadow, not ship.**

**Refutation.** If the forward shadow's delta is ≤ 0, or ex-top-10 ROI does not improve, the band
ordering was an artefact of the pre-0.85-gate book and this question closes for a quarter. I will
not re-open it on the all-time number that includes legs the live gate refuses.

**Expected effect.** +$1,700/90d at the current-era point estimate, ~+$5,000/90d if the all-time
reachable estimate is the right one, $0 until it ships. It also converts ~64% of STANDARD's
capital-days out of the one band whose edge is negative on *both* instruments.

**Fillability.** The map doubles the cheap band: a $10.00 median clip becomes $20.00, and the
cheap-band break-even slippage is its edge, **6.1¢/share**. §AF measured median +2¢ depth on cheap
books at $1,881 — 94× the doubled clip. Depth is not the constraint on the half that receives the
dollars, and the other half only shrinks. **Cost: 2h** (a nullable predicted-size column on the same
path `FillIntent` already hooks, plus the re-read).

---

## #2 — The pending maturity factor's last unmeasured input is now measured. Lane B, done.

§AJ's maturity size factor (2026-10-25: +$5,028 all-time, +$4,397/90d, CI excludes zero in both
windows, control validated) sends extra notional to legs entered with ≥72h to resolution, whose
notional-weighted entry price is **0.605** — and its own fillability note says depth at 0.6–0.85 was
**unmeasured**. That was the only thing standing between it and a decision, and it is the largest
CI-positive sizing change in the book.

§AN closes it on live books (read-only, cached in `data/mid-band-depth-probe.json`). Sample: markets
our tracked wallets were printing in at 0.60–0.85 in the last three days — the population a doubled
clip would land in:

- **12 live books, best ask 0.62–0.83**
- depth within +2¢: p10 **$876**, median **$4,317**, p90 $55,738
- **12/12 absorb 2× the ≥72h median clip ($21.60) within +2¢; 12/12 absorb 4× ($43.20)**
- median book carries **200×** the doubled clip at +2¢, against a break-even slippage of 17.0¢/share

**Verdict: depth is not the binding constraint at 0.6–0.85 either.** Caveats, stated: n=12, one
instant, ask side only, and the sample is markets at that price *today* rather than the book we
would hit at the instant of a copy — it bounds the question, it does not model the print-time
squeeze. The honest position is that the maturity factor's decision is now **on edge alone**, and it
has also never been put on the roadmap (no card exists — I added one this commit, it has been living
only in a draft since 10-25).

**Cost: 0h (done). What it unblocks: a decision, not a measurement.**

---

## #3 — Nothing else. Four dead ends, named.

- **Cap market concentration.** Measured today by concurrency: 200+ bucket = 58% of book PnL at
  +20%. Cap at 1% of principal forgoes $6,614. NO.
- **Cut the 0.80–0.95 top band.** The settlement-truth instrument now agrees with the booked one —
  edge **−4.7pp, CI [−7.3, −2.2]** on 2,028 bets — but the live `standardMaxEntryPrice` = 0.85
  already refuses it: **12 legs since 2026-09-15**, $216, +$0.38. Already done, by a gate, before
  the second instrument existed. Do not propose it again.
- **Loosen admission to capture the refused pool.** 35 declined bets vs 134 copied in 14 days inside
  active markets. There is no pool there, and the refused arm's edge is −0.9pp [−2.9, +1.2].
- **Raise the sub-0.20 size factor.** Proposed 10-24 (floor at 0.05, move size to 0.15–0.20), still
  open. Nothing today changes it; today's truth instrument agrees with its premise (+6.1pp edge on
  284 copied bets) which is the most I can add without re-proposing it.

---

## Contradictions I am not resolving silently

- **0.4–0.6**: §T all-time STANDARD **+6.7%** on 3,678 legs; the 2026-10-20 band report
  **−7.67% CI [−14.48, −0.89]** on 1,027 deduped legs; today's settlement truth **−0.1pp** on 1,656
  bets. Three instruments, three answers. v63 refuses the band live, so nothing is sized on it
  either way — but the next reader should not quote the +6.7%.
- **<0.20 ex-top-10**: §T says **+52.7%** (dollars-at-risk basis, 499 legs); the 10-21 draft says
  **+7.0%** (it was computed on a different basis). I am not using either for a recommendation; if
  someone re-derives it, state the cost basis first — this is the exact error the brief warns about.
- **The standing −3.92% take-all ROI is not used anywhere in this review** and is still unreproduced
  from the files it names.

---

**IF YOU WEREN'T HERE:** I would start STANDARD's band-size shadow ledger today — the mechanism is a
pinned `1.0`, not a missing idea, and the only reason it is not live tomorrow is that the
reachable-window CIs include zero. Two hours gets the forward sample that decides it.

---

*Lane B, applied directly this commit: `scripts/profit-velocity.py` §AM (+~470 lines:
`declared_flow` covering the 7d realised bridge with market attribution, the declined-signal
counterfactual on one-row-per-bet with market-clustered paired intervals, the every-print/first-print
sign check, reachable declined flow at three clips, the 0.80–0.85 two-instrument table, peak
concurrent market notional with a cap shadow at four ceilings, and the band-sizing shadow in four
windows) and §AN (`mid_band_depth_probe`, live CLOB books, cached in
`data/mid-band-depth-probe.json`), both wired into the **default** run with `--only-am` /
`--only-an-depth` for a subset. Read-only DB. **No RuleSet row touched, no rule edited, no
`prisma/dev.db` write.** Roadmap: one card added for the maturity factor (it had none), one for the
band-shadow.*

*Defects caught in my own work before any number shipped: (1) the every-print version of the
counterfactual reverses the sign and would have shipped "the refused bets were better" as a finding;
(2) my first band-sizing shadow reported +$9,635 all-time with a CI excluding zero — which survives
only because 2,399 of those legs sit above a live gate. Both corrected above and both printed in the
script.*
