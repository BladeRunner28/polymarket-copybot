# Profit review — 2026-10-30

http://localhost:3013/drafts/profit-recs-20261030

**Cost basis on every ROI below: `simulatedPositionSize` = dollars at risk, never shares.**
A BUY of `$n` at `p` is `n/p` shares; settlement at `s` realises `n*(s/p − 1)`.

Every figure in this file is computed by **`scripts/profit-maker-credit.py`** (§MC.1–MC.8, new
this commit) plus the pre-existing **`scripts/profit-velocity.py --only-am`** (§AM, quoted with
its scope). Reproduce:

```
python3 scripts/profit-maker-credit.py            # offline, DB only, no wire calls
python3 scripts/profit-maker-credit.py --selftest # identity checks only
python3 scripts/profit-velocity.py --only-am      # §AM declined arm (truth cache, no fetch)
```

Dedupe convention is the canonical one — first leg per `(wallet, market, outcome)` — so every
table here is comparable to the band ROIs already quoted in `drafts/`. The DB is live: a re-run
moves the 90d window by ~1pp as new legs land. Figures below are the 2026-10-30 07:5x CDT run;
§MC.5–MC.8 come from a single load and are internally consistent with each other.

---

## The one fact that decides everything else: return per bet is monotone in entry price, in both arms

§AM.2, settlement truth, one row per BET (not per print), 4,489 copied bets in 3,743 markets:

| band | copied rx | declined rx |
| --- | --- | --- |
| <0.20 | **+49.5%** | +46.4% |
| 0.2–0.4 | +15.1% | +8.7% |
| 0.4–0.6 | −0.2% | −2.6% |
| 0.6–0.8 | −1.6% | −0.4% |
| 0.8–1.0 | **−4.5%** | −4.9% |

Two independent populations — the bets we took and the bets we refused — produce the same
monotone decay, and **both are negative above 0.60**. The calibration edge is +0.1pp for the
copied arm and −0.9pp for the declined arm: on the honest basis this engine is a **zero-edge
operation on both sides of its own gate**. That is not a wallet problem, a timing problem or a
liquidity problem. It is the payoff asymmetry (`buy at p → break-even hit rate is p`) showing
up in our own book twice.

And here is where the volume sits against that (§MC.3, 90d, STANDARD, current rule):

| band | notional | ROI | share of lane notional |
| --- | --- | --- | --- |
| <0.20 | $2,666 | **+54.4%** | 7.6% |
| 0.2–0.4 | $4,743 | +11.1% | 13.5% |
| 0.4–0.6 | $12,983 | −7.3% | (skipped since v63 — legacy) |
| 0.6–0.8 | $7,758 | +2.2% | 22.1% |
| 0.8–1.0 | $6,915 | −0.6% | 19.7% |

**41.9% of the lane's 90-day notional sits at 0.60 and above and returns +$129 of $1,154.** The
region both arms agree loses money is the region we allocate the second-most capital to, and
nobody has ever priced it as a *skip* — only as a size factor.

---

## The arithmetic the ladder has been missing: it is a flow equation, not a capital one

§MC.7, measured today:

- C-200 last 30d: 443 legs, $4,866 → **$162/day** of notional (last 7d: $178/day)
- STANDARD last 30d: 136 legs, $2,407 → **$80/day** (last 7d: $71/day)
- open book: 467 legs, $5,087

$5,000/day at the measured 1.11% per capital-day needs $449,000 of capital *held*. At 76-day
holds that is **~$5,900/day of new notional sustained — 24× what we deploy**. Sizing cannot
close it: the clip is $11 and the C-200 cap ($100) is 9× and does not bind. Admission volume
cannot close it either: §AM.4 measures the reachable declined pool at **23 bets/14d against 117
copied** (0.2:1) in truth-covered active markets, so the refused flow is *smaller* than the
taken flow, not 24× bigger.

That is the sentence this review exists to write: **every lever measured in the last ten days —
bands, exits, fills, latency, wallets, sizing — is worth 5–10% of a number that needs 2,400%.**

---

## What I measured and had to correct in my own work

**The 2¢ maker credit is worth 5.7%, not 75.7%.** `src/lib/fill-intent.ts` opens by claiming
the credit is "$1,732.88 of the lane's $2,288.52 realized PnL (75.7%)". That claim is priced per
share. The correct identity, from `pnl = n*(s/p − 1)`:

```
s = p*(pnl + n)/n        →   pnl_at_intent = p*(pnl + n)/ip − n
```

and its consequence is not a rounding detail: **a losing leg's credit is worth exactly zero.**
At 0.48 vs 0.50 a winner gains 8.3% of stake; at 0.12 vs 0.14 the same 2¢ gains 119% (§MC
selftest prints all three cases; `max|pnl_at(entry) − realizedPnL| = $0.000000` over the whole
book, so the identity is exact). Re-priced correctly (§MC.2/MC.5, 90d):

- C-200 **as booked +42.7%** → **current rule (unfilled = 0) +38.6%** → **+38.2%** both
  corrections; **ex-top-10 −2.4%**
- credit total **+$403.37** on the 386 intent-stamped legs = **5.7% of the lane's $7,051 booked
  PnL** — a real, band-shaped subsidy (7.0% of stake at <0.10, 0.0% at 0.60+), not the lane's edge

**The fill flip cost C-200 more than its credit is worth.** §MC.4: 248 pre-flip legs priced as
fills but stamped `unfilled` carry **+$680**; zeroed, the 90d book goes **−$681 (−4.1pp)** and the
30d **+51.6% → +36.5% (−15.1pp, −$748)**. The rule itself verifies clean: **0
violations on the 7 legs that ended on/after 2026-10-28**, 246 on the pre-flip ones. So the
historical numbers circulating for the "profitable lane" are 4–15pp too high, and the fix is
already in place prospectively.

**The 2¢ is no longer a flat 2¢** (§MC.1): September 76/76 legs exactly 2.00¢; October 182/314
exactly, **mean 1.32¢, min 0.06¢**. The measured-credit mode is live and is already pricing the
lane's entry advantage down by a third.

**The band schedule — the standing 10-27 Lane A proposal — does not survive its own ex-top-10
read.** `profit-velocity.py --only-am` shadows the schedule on 2,592 STANDARD 90d legs net of
the live skip: flat **+$1,508 (+4.5%, ex-top-10 −0.9%)**; mild **+$3,031 (+1,523, CI
[−456,+3,794], ex-top-10 +0.3%)**; strong **+$4,094 (+2,586, CI [−588,+6,371], ex-top-10
+1.7%)**. The inverse control correctly loses (−$1,085), so the ordering is doing the work —
but the work converts a −2% lane into a **0% lane**. It is a guard against loss, not a source of
edge, and it should stop being quoted as +$2.6k.

---

## The number that decides the fill question (axis 5, computed for the first time here)

§MC.6 solves, per band, **how much worse the fill can be before that band's realised PnL hits
zero** — the entry price is shifted on every leg of the band and each leg keeps its own outcome.
This is the breakeven slippage the process asks for on any thin-book recommendation.

| band | C-200 ROI | C-200 breakeven | STANDARD ROI | STANDARD breakeven |
| --- | --- | --- | --- | --- |
| <0.10 | +74.1% | 4.6¢ | +55.7% | 3.7¢ |
| 0.10–0.20 | +107.8% | **15.8¢** | +53.5% | 7.9¢ |
| 0.20–0.40 | +17.4% | 5.2¢ | +11.1% | 3.6¢ |
| 0.40–0.60 | +1.8% | **0.9¢** | −7.3% | none |
| 0.60–0.80 | +4.6% | 3.2¢ | +2.2% | 1.5¢ |
| 0.80–1.00 | +3.9% | 3.4¢ | −0.6% | none |

Read it as a capital-allocation table: **the dead zone survives nine-tenths of one tick**, the
0.60–0.85 region one to two ticks, and only the 0.10–0.20 longshots tolerate a fill that is
more than a dozen cents worse than the mid. If the book is going to carry fill risk anywhere, it
should carry it where a cent is 4% of the stake rather than 4% of nothing.

And the cheap tail's own robustness, §MC.8 (market-clustered CI, 1,500 resamples):

- C-200 <0.20: **+89.5% CI [+15.7, +165.1]** on 190 legs/167 markets — but **ex-top-10 −19.0%**
- STANDARD <0.20: +54.4% CI [+0.8, +116.8] on 204 legs — **ex-top-10 −11.1%**
- C-200 0.10–0.20 alone: +107.8% CI [+17.7, +200.1], ex-top-5 +8.9%, **ex-top-10 −36.5%**
- C-200 0.00–0.10 alone: +74.1% **CI [−22.7, +196.4]**, ex-top-5 −33.6%

**Nothing in the cheap tail survives removing its ten best legs.** The CI-excludes-zero property
is real and the ex-top-10 property is not, which is the same tail-dependence the whole book has.
Any future cheap-band proposal has to clear both.

---

## #1 — Extend STANDARD's hard skip from 0.40–0.60 to 0.40–0.85. Lane A, proposed.

**Hypothesis.** Above 0.60 both arms lose on settlement truth and the band's realised return is
within a tick or two of zero, so the territory is not a return source at any size — it is
occupancy, and removing it costs nothing while freeing 42% of the lane's notional and
capital-days.

**Measurement.** §AM.2 (copied −1.6% at 0.6–0.8 and −4.5% at 0.8–1.0; declined −0.4% and −4.9%,
one row per bet, 8,523 truth-joined bets in 3,743 markets) plus §MC.3/§MC.6 (STANDARD 0.60–1.00
= $14,673, **+$129**, breakeven 1.5¢ and none) plus §MC.7 (freeing notional is the only lever
that scales).

**Decision rule.** Apply when, over ≥300 forward STANDARD legs in 0.60–0.85, realised ROI is
< **+2%** ex-top-10 — i.e. when the band cannot pay for its own capital-days. The whole
0.60–1.00 block reads **+0.9% on $14,673** today (1,181 legs), and both arms' settlement edge is
negative, so the number is already below the bar on the basis that matters.

**Refutation.** If a forward 300-leg sample of 0.60–0.85 STANDARD legs clears **+8% ROI**
ex-top-10 (4× the breakeven-slippage buffer, so it cannot be one tick of noise), the band is a
real return source, the skip was wrong, and it comes back at full size. Counted from
PaperTrade + settlement truth, not argued.

**Expected effect.** +$129 → 0 of direct PnL given up, and 41.9% of the lane's notional-capital-
days released. Small in dollars, first in ranking because it is the only proposal available that
is **corroborated by both arms independently** — the figure cannot be an artefact of our
selection, which is the failure mode of every previous band proposal. **Cost: 0.5h** (one
RuleSet field, `standardSkipBandRange` → `0.40-0.85`; the v63 parser and its tests already
handle ranges).

---

## #2 — Restate the ladder's advance gate on throughput, and print the ratio in the EOD. Lane A, proposed.

**Hypothesis.** The ladder's constraint is not capital, edge, or sizing but **notional/day**
($242/day today against ~$5,900/day required) and the admission pool cannot supply more (0.2:1
reachable refused:taken), so any further quality-tuning is a 5% lever on a 24× gap and the
advance gate is currently measuring the wrong thing.

**Measurement.** §MC.7 (notional/day by lane, 7d and 30d, and the 76-day-hold implication of
$449k) and §AM.4 (23 declined vs 117 copied bets/14d in truth-covered active markets) and §AM.2
(calibration edge +0.1pp copied / −0.9pp declined).

**Decision rule.** The advance gate becomes: 7 consecutive days at goal **and** rolling-90d
ex-top-10 ROI ≥ **+5%** **and** notional/day ≥ **$400** (the level at which the funnel is no
longer the binding constraint at a $20 clip). The EOD report prints notional/day next to PnL.

**Refutation.** If any week delivers **> $1,000/day** of notional without a rule change, the
funnel is not the constraint, the throughput thesis is wrong, and the ladder goes back to being
an edge problem — in which case #1 is the only lever left and the target is out of reach at this
flow for reasons other than admission.

**Expected effect.** $0 of PnL, and it stops the next month of engineering being spent on 5%
levers. It also stops the book from "advancing" on a 10-leg tail: nothing in this file survives
ex-top-10, so an advance gate that ignores ex-top-10 is measuring luck. **Cost: 0.5h.**

---

## #3 — The credit is now priced correctly, and the lane numbers are restated. Lane B, done.

`scripts/profit-maker-credit.py`: the re-pricing identity with a selftest that reproduces
`realizedPnl` to $0.000000 across the whole book and pins the three cases that break the naive
per-share formula (loser = $0 credit, 0.48 winner = 8.3% of stake, 0.12 winner = 119%); the
credit census by month and band; the booked / current-rule / intent-priced / both ladder for
both lanes at 30d, 90d and all-time; the fill-flip verification with its violation count; the
breakeven-slippage solve; the cheap-tail split at 0.10 with a market-clustered bootstrap; and
the throughput block. Read-only DB, no RuleSet row touched, no prisma write, no wire call.

`npx tsc --noEmit` untouched (Python only); the script is import-free beyond stdlib.

---

## Contradictions I am not resolving silently

- **The band schedule is already proposed and I am not re-proposing it** — but its shadow, read
  ex-top-10, is +0.3% (mild) / +1.7% (strong), not the +$2.6k headline. The approval should be
  made on the ex-top-10 line, and #1 is the cheaper half of the same idea (skip, don't weight).
- **STANDARD's 30-day result depends on the dedupe, and the sign flips with it**: −0.2% on
  $12,546 over all legs by close date, +12.8% on $7,468 deduped to one leg per bet. The marginal
  second leg into a bet is the loser (all-time ordinal: 1st +12.9% on 4,615 legs, 2nd +0.9% on
  1,585). `maxMarketLegsPerMarketId` is already 2 — and I am **not** proposing to cut it to 1,
  because with flow as the binding constraint the freed slots would not refill and the change
  would cost the $156 the second legs earn. Recorded so it stops being re-derived.
- **Yesterday's #2 is moot**: `standardStaleExitHours` is **0** in the active v70 RuleSet, so the
  STANDARD calendar rail is already inert by parameter. No code deletion is needed to retire it;
  the branch is unreachable. Say that in the approval thread rather than shipping a diff.
- **The 168h exit horizon and the cheap-tail CIs both span zero** (C-200 <0.10: [−22.7,
  +196.4]). Two of the load-bearing "cheap band works" numbers in this file are CI-positive and
  ex-top-10-negative at the same time. Both are printed above; neither is a licence to size up.
- **My own earlier arithmetic today was wrong** and I caught it before it shipped: pricing the
  credit per share (`pnl − shares*Δ`) charged losers for an improvement they never received and
  made the credit look like 30–40% of the lane's ROI. The corrected figure is 6.3%. The selftest
  in the committed script exists so the next review cannot repeat it.

---

**IF YOU WEREN'T HERE:** I would extend STANDARD's skip to 0.85 this morning. It is the only
change in this book whose sign is confirmed by two independent populations — the bets we took and
the bets we refused — and at 42% of the lane's occupied notional it is the largest block of
capital currently earning nothing. Everything else on the table, including the band schedule I
have been carrying for three days, moves a number that is already inside its own confidence
interval.

---

*Lane B, applied directly this commit: `scripts/profit-maker-credit.py` (new, §MC.1–MC.8 and
the selftest). Read-only DB throughout. **No RuleSet row touched, no rule edited, no
`prisma/dev.db` write.***
