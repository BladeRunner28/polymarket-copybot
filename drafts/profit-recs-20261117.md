# Profit review — 2026-11-17

**The tape was always able to answer yesterday's question. I asked it, and the answer is that the
book's entire profit sits in two classes that either never traded or that the booking path already
treats as zero.**

All numbers below come from one committed instrument, `python3 scripts/profit-filled-decomp.py`,
run twice: default (`--min-rule 68`, the live regime) and `--min-rule 0` (every settled leg since
2026-09-01). Population: 2,311 settled non-demo legs / $32,922 cost, deduped to the first leg per
`bot|wallet|market|outcome`, 77.0 days. Cost basis = `simulatedPositionSize` = **dollars at risk**.
CIs are market-clustered, 2,000 draws. DB `mode=ro`.

---

## 1. The key insight: yesterday deferred a question the venue answers retroactively

Yesterday's brief pre-registered a *forward* test — adjudicate 150 future unadjudicated legs against
the venue tape, and if ≥60% fill at non-negative ROI, the confirmed-filled basis is wrong. That wait
was unnecessary: `clob.polymarket.com/prices-history` serves minute tape for any token after the
fact, keyless. The instrument adjudicates **2,311 of 2,311 settled legs (100%)**.

| resolver stamp | legs | tape filled | near-miss | tape never traded |
|---|---|---|---|---|
| filled | 272 | 225 (82.7% of all) | 43 | 4 |
| unfilled | 526 | 98 | 192 | 236 |
| NULL (no verdict) | 1,513 | 852 | 161 | 500 |

Two validation results before anything else:

- **The tape is sane on the class we trust:** 225 of 229 *decidable* resolver-filled legs are
  tape-filled (98.3%). The tape is not inventing negatives.
- **The resolver's negative is not trustworthy:** 98 of 334 decidable legs stamped `unfilled`
  (29.3%) trade through our entry price *after* dispatch. All of them are C-200.
- **The touch test is not a t0 artifact.** If we paid the market price, the tape is at our price at
  dispatch, so I re-ran it with a lag floor. Rates barely move: filled 82.7% → 79.4% at lag ≥900s,
  unfilled 18.6% → 16.7%, NULL 56.3% → 51.5%. The test discriminates between classes, which a
  degenerate test would not.

**So the class yesterday called "unadjudicated" is not untested. It is 63.0% filled — and its
positive PnL is in the 37% that never traded.**

## 2. The book's +$6,059, decomposed by whether a trade happened

| class | legs | cost | PnL |
|---|---|---|---|
| resolver-filled | 272 | $3,965 | **−$609.3** (−15.4%) |
| NULL, tape-touched | 852 | $13,377 | **+$284.2** (+2.1%) |
| NULL, tape never traded | 500 | $5,638 | **+$4,458.0** (+79.1%) |
| rows stamped unfilled | 526 | $8,164 | +$2,269.5 |

`+$4,458 + $2,269.5 = $6,727` against a published `+$6,059`. The two positive classes are *exactly*
the two that have no evidence of a fill — one because the market never came to our price, the other
because the resolver said it did not and the read path (`bookedPnl()`) already zeroes it. The
arithmetic closes exactly: +4,458.0 − 609.3 (resolver-filled) − 343.2 (near-miss) + 284.2
(tape-touched) + 2,269.5 = **$6,059.2**, the published number.

And the phantom is not a broad edge, it is a lottery ticket: **ex-top-1 +$2,944.6, ex-top-5 +$291.9,
ex-top-10 −$311.9; 260 of 500 legs positive.** Half the legs win, as they must when you book a
cheap-longshot portfolio at p(fill)=1 — five legs carry all of it.

The basis every other number in this system should read:

| basis | legs | cost | PnL | ROI | $/day |
|---|---|---|---|---|---|
| booked rows | 2,311 | $32,922 | +$6,059 | +18.4% | +$78.7 |
| positions only | 1,785 | $24,758 | +$3,790 | +15.3% | +$49.2 |
| confirmed filled | 272 | $3,965 | −$609 | −15.4% | −$7.9 |
| **REACHABLE (stamp or tape touch)** | **1,124** | **$17,342** | **−$325** | **−1.9%** | **−$4.2** |

Ex-top-1 the reachable book is −$877 (−5.1%); ex-top-10, −$2,980 (−17.5%).

## 3. Yesterday's card is refuted by the test it wrote itself

`ladder-credit-confirmed-filled` (Backlog, awaiting approval) carries this refutation, verbatim:

> a 150-leg forward sample of the unadjudicated class, adjudicated against the venue tape, showing
> >=60% actually filled at a non-negative ROI -> that class is real positions, belongs in the
> credit, and this change is withdrawn.

Measured on the whole population rather than a forward sample: **63.0% tape-filled, +$284.2 (+2.1%).**
Both conditions met. **The card should be withdrawn, not approved.** Crediting the confirmed-filled
basis would pin the ladder to the *worst-selected* subsample of the book: resolver-filled legs are
the ones where the L2 window happened to catch a fast fill, and they read −15.4% against the tape
book's −1.9%.

This is the third consecutive day that a basis proposed as "the honest one" turned out to be a
selection effect — and it is the first time the refutation condition was written down before the
measurement, which is why it can be settled in one run instead of a week of argument.

## 4. What actually decides the sign: the entry, not the fill

`gap` = the price we paid minus the market price at dispatch (tape `p0`). Negative = we rested under
the market; positive = we paid up to be filled.

| gap bucket | legs | cost | PnL | ROI | CI |
|---|---|---|---|---|---|
| paid at/below market | 875 | $13,383 | +$730.9 | +5.5% | [−10.5,+24.1] |
| paid 0..+2c above | 161 | $2,469 | −$435.9 | −17.7% | [−42.5,+13.6] |
| paid ≥+2c above | 88 | $1,490 | −$620.0 | −41.6% | [−65.6,−10.9] |

A monotone dose-response: the more we pay up, the more we lose, and the top bucket's CI excludes
zero on 88 legs. **Removing the 249 paid-up legs moves the reachable book from −$325 (−1.9%,
−$4.2/day) to +$731 (+5.5%, +$9.5/day)** — a $1,056 swing, on 22% of the notional.

Three things I had to check before believing it:

- **It is not a C-200 artifact.** Paid-up splits almost evenly: 131 C-200 legs / $1,849 and 118
  STANDARD legs / $2,110. The 2026-11-13 card framed this as a C-200 dispatch problem; it is a
  booking problem in both lanes.
- **It is not stale detection.** Crossed against wallet-trade→dispatch lag, paying up loses at every
  lag: −68.9% at <2m (46 legs, CI [−88.0,−36.5]), −8.5% at 2-10m, −39.4% at >10m (55 legs, CI
  [−62.3,−13.9]). Meanwhile paying at/below with fast detection is the best cell in the book
  (+24.0%, 112 legs, $1,727). Speed is good; speed *plus paying up* is the worst cell we have.
- **The pre-registered bar is not met.** Post the 2026-11-09 price-side fix: 55 paid-at/below legs
  at +11.4%, 19 paid-up legs at −17.0% (CI [−77.8,+91.4]). The direction holds after the fix; the
  sample is 19 of the 150 the earlier read demanded.

## 5. The rung is reading one tennis match, and throughput is the real gap

| basis | last 7d | vs $1,750 bar | ex-top-1 |
|---|---|---|---|
| booked rows | +$422.8 | 24.2% | −$129.5 |
| confirmed filled | +$225.6 | 12.9% | −$326.6 |
| reachable (tape) | +$290.8 | 16.6% | **−$261.5** |

The single leg is `atp-shevche-ruud-2026-11-11`, +$552.2. On every basis the seven-day number is one
ATP match, and ex-that-leg every basis is negative. The 14-day reachable sum is −$218.1.

Throughput, which nobody has quoted: the reachable book is **14.6 settled legs/day and $225/day of
notional**, turning over in a median 1.0 day (mean 2.2). At +5.5% that is **~$12/day**. To reach
$250/day at +5.5% you need ~$4,500/day of notional deployed — **20x today's**. That is the ladder's
binding constraint, and it is not capital (C-200 carries $196 of open notional against a $3,723
cap): it is that the only volume which fills instantly is the paid-up class that loses.

That is the central economics of this book, stated plainly: **fill probability and edge are
inversely related.** The profit we think we make is in fills we do not get; the fills we get lose.

## 6. One contradiction with a prior measurement, reported not resolved

Band 0.80-1.01 is the only cell with a positive CI excluding zero in the live regime: 24 legs,
+16.4%, CI [+13.8,+18.8]. All-history it is 59 legs / 48 markets / 11 wallets, +$91.1 (+6.7%), CI
[−5.0,+14.8] — the interval includes zero. **This contradicts the standing baseline** (`0.80-1.0`
f* −101.3% on 1,172 legs, all-time finished basis), and I am not going to pick the flattering one.
The likely reason the two disagree is visible in the leg list: several are already-decided entries
("highest temperature in X on September 5" bought at 0.80-0.81 after the date passed) — near-certain
outcomes that the training-exclusion card already wants out of the model. I am not acting on this
cell; 24 legs of near-decided favourites cannot carry $250/day.

---

# Recommendations, ranked by expected value

### 1. Withdraw `ladder-credit-confirmed-filled`; make the tape the fill verdict — LANE A, propose only

**Hypothesis.** The resolver's `unfilled` stamp is a false negative on ≥25% of decidable legs, so the
split into "confirmed filled" (which reports as −15%) and "unadjudicated" (which reports as +$491) is
an artifact of a 5-minute L2 window, not of which positions existed. A tape-backed verdict collapses
the four bases into one and moves $4,458 of phantom PnL and $2,269 of stamped-unfilled rows out of
the book the ladder credits.

**Measurement.** `scripts/profit-filled-decomp.py --min-rule 0` (S2, S2b, S3, S4, S10): 2,311 legs,
100% tape coverage; 98/334 (29.3%) of decidable `unfilled` legs trade through our entry after
dispatch; the 500 never-traded NULL legs carry +$4,458 (+$2,945 in five legs); the reachable book is
−$325 (−1.9%, −$4.2/day) against a published +$6,059.

**Decision rule.** Ship as a read-path change with no rule value: `bookedPnl()` (and the rung, the
EOD, and the C-200 bankroll input) use `filled = resolver stamp OR venue tape touched at or below our
entry within 1h`, and zero the tape-never-traded class. Print all four bases for one week beside the
number. Approve the withdrawal of `ladder-credit-confirmed-filled` in the same decision — the two are
one change, and approving the card alone pins the ladder to the −15.4% subclass.

**Refutation.** Withdraw if a forward 150-leg sample of the tape-never-traded class, checked against
a second source that is not the price tape (L2 book capture or venue trade prints at our bid), shows
≥60% of them actually filled at non-negative ROI — then "never traded" is not "never filled", and the
phantom is real profit.

**Expected effect.** $0 directly; it is the difference between the system believing it is +18.4% and
measuring −1.9%, and it also unwinds the mechanism that currently grants risk headroom: C-200's
`BotBankroll.realizedPnl` of $5,445.72 sets net worth $7,345.72 and an exposure cap of $3,722.86
against a $1,000 base (the card `profit-fill-never-reachable` P2 prices the restatement at
$3,840.16 → $1,000.00 — my arithmetic reproduces it). Cost **2h**.

### 2. Price the paid-up dispatch rule now, ship it when the bar clears — LANE A, propose only

**Hypothesis.** Legs whose booked entry is above the market price at dispatch lose money at every
detection lag, monotonically with the size of the overshoot, and suppressing them leaves a
positive book.

**Measurement.** `scripts/profit-filled-decomp.py --min-rule 0` S8 / S8b / S12: 249 paid-up legs,
$3,959, −$1,055.9 (−26.7%); dose-response −17.7% (0..+2c) → −41.6% (≥+2c, CI [−65.6,−10.9]); worst at
every lag bucket; post-2026-11-09 cohort 19 legs at −17.0%.

**Decision rule.** No change today. Ship when the post-fix paid-up cohort reaches **150 legs at ≤ −10%
ROI with a market-clustered CI excluding zero** — the bar the 2026-11-13 read pre-registered. Today:
19/150. At ~2.4 paid-up legs/day that is ~55 days; there is no honest way to shorten it (shadowing
cannot create the sample without changing dispatch, which is the thing under test).

**Refutation.** 150 post-fix paid-up legs at ≥0% ROI with a CI excluding zero → the class is noise
and the rule is withdrawn. Second, weaker: if the paid-at/below class' own CI never excludes zero over
those same 150 legs, then "removing paid-up leaves a positive book" is unproven even though the
removal is right, and the expected effect should be re-priced as variance reduction, not +$1,056.

**Expected effect.** +$13.7/day ($1,056 over 77 days) and the book's sign flips from −1.9% to +5.5%.
Cost **1h to wire as a shadow print, 1h to enforce** when the bar clears.

### 3. No change to exits, clips, gates, size or wallet selection — the measurement is not there

**Hypothesis (of the hold).** Every remaining lever either has a measured CI spanning zero or is
already gated by a pre-registered bar that is unmet, so a change today would trade a measured
quantity for an unmeasured one.

**Measurement.** Same instrument: exit alpha already read NO-CHANGE (2026-11-16, CI [−$2,517,+$667]);
gates closed NO-CHANGE under their own shadow reads; wallet pruning measured as not surviving
forward (`drafts/wallet-churn-forward-20261116.md`); the paid-up cell is bar-gated above; the
0.80-1.01 cell is 24 legs with a contradictory prior.

**Decision rule.** Unlock predicates, unchanged and named: exits — 200 rail-fired legs whose alpha CI
excludes zero; size/clips — 200 confirmed-filled legs at ≥+20% with ex-top-10 positive (today 272 at
−15.4%); wallet selection — a forward cohort where the demoted set's edge survives.

**Refutation of the hold.** Any of those thresholds met on a forward sample unlocks the corresponding
change; the cheapest is the exit cohort at ~30 rail-fired legs/month.

**Expected effect.** Zero by construction. Cost **0h**.

---

**IF YOU WEREN'T HERE:** kill `ladder-credit-confirmed-filled` and make the venue tape the fill
verdict. The card's own refutation fires — 63.0% of the "unadjudicated" class traded, at +2.1% — and
the book it would have credited is the one subclass of fills that loses 15.4%, while the +$6,059 it
would have published is five legs the market never brought to our price.

**What I did not re-litigate, and why.** The liquidity and wallet-copy gates (both closed NO-CHANGE
under shadow reads); the 0.4-0.6 skip (live in both lanes; my band table still shows 0.40-0.60 at
−5.4% on 359 legs, which is the same finding as the carded `standard-0.4-0.6` proposal, so no new
card); the $25 C-200 clip cap (carded, its own premise already refuted lane-wide); the
`standard-book-at-ask` cost (unaffected by today's read — the ask premium is a booking cost, not a
fill-verdict issue); the TTR/maturity schedule (capital is not binding: $86 open against a $1,000
cap).

**Supporting claims kept separate.** (a) The fill-verdict correction (§1-§3) is an identity on the
tape and stands alone. (b) The paid-up gradient (§4) is an independent measurement with its own
refutation. (c) The 0.80-1.01 cell (§6) supports neither and is reported as a contradiction with a
prior figure, not as evidence for anything. (d) The throughput arithmetic (§5) is descriptive and
proposes nothing.

**Caveats that travel.** (a) "Touch" is reachability, not a fill: a print at or below our bid ignores
queue and size, so 63.0% is a *lower* bound on fill and "never traded" is an upper bound on never
filling — which is exactly why recommendation 1's refutation names a non-tape second source.
(b) `gap` is measured against a print price, not the book the bot saw; the executable version is
"entry above the best ask at dispatch", and the mapping from print-gap to book-gap is unmeasured.
(c) The reachable population is 1,124 legs of a 2,311-leg book. The other 1,187 split three ways —
526 rows the resolver stamped unfilled, 500 the tape says never traded, 161 near-misses (traded
within 1c of our price but through it) — and each is excluded from the ROI figures on that basis
explicitly, not pooled. (d) The all-history run
includes legs from before the 2026-11-09 price-side repair; the post-fix cells are reported
separately throughout and are the only ones a live rule may be judged on.

**Lane discipline.** Lane A only: no RuleSet read or write, no `apply-v*`, no prisma write, DB
`mode=ro`, `base` untouched. Instrument committed in the same commit:
`scripts/profit-filled-decomp.py` (self-checks 2/2 PASS; `--selftest` passes), full run artifacts
`data/profit-filled-decomp-allhist.txt` and `data/profit-filled-decomp-regime.txt`.
