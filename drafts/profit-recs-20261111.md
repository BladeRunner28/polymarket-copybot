# Profit review 2026-11-11 — the edge is a hit rate, not a tail; and the ladder is reading a rung it never climbed

http://localhost:3013/drafts/profit-recs-20261111

**Instrument:** `scripts/profit-postfix-integrity.py`, sections **G/H/I/J** added today (read-only,
self-tests pass, committed with this file). Run: `python3 scripts/profit-postfix-integrity.py`.
Basis as yesterday: cost = `simulatedPositionSize` = **dollars at risk**, deduped first leg per
`bot|wallet|market|outcome` within status class, price = the price of the token we actually bought,
CIs market-clustered (2,000 draws), `tol` = realised hit% − average price paid in points.

---

## 0. Two corrections to the instruments — both mine, both before quoting anything

**(a) Unfilled legs were in every ROI denominator.** 121 of the 367 deduped legs opened since
2026-10-26 are `fillStatus='unfilled'` with a zero payoff — orders the venue says never traded. They
carry **$3,042 of the regime's $8,079 notional: 38% of the money and a third of the legs**. Excluding them (new `risk_legs()`) moves the
regime book from **−11.9% (yesterday's figure) to −16.9%**, and the cheap band from −33.2% to
**−53.4%**. Direction: worse, not better. Every regime number below excludes them and every affected
line prints the exclusion.

**(b) "Ex-top-10 collapses the book" is not an edge test for this book.** The standing claim — PnL is
95% ten legs, therefore no edge — applies a favourites test to a lottery. In a cell with a 20% hit
rate and a ~+780% payoff, the top 10 of 509 legs holding the profit is *arithmetic*, and ex-top-N
destroys the mean **even when the edge is exactly the measured one**. For a BUY at p the payoff is
(1−p)/p on a win and −1 on a loss, so the cell has edge iff **hit rate > price paid**. That test's
standard error depends on the number of *draws*, not on how fat the tail is.

On that test the cheap band is not a lottery ticket that got lucky. It is **calibrated**: 104 wins of
509 legs, **20.4% against an 11.3% break-even, +9.1pp, Wilson [ +5.9, +12.9 ]**. My own ex-top-10
figure for the same cell is −2.4%. Both are true, and only one of them is evidence.

---

## 1. Where the edge is, and where the volume is (all-time, 5,680 legs that traded, $64,168)

| band | n | notional | share | ROI | CI95 | hit% | avgP | tol pp |
|---|---|---|---|---|---|---|---|---|
| 0.0–0.2 | 509 | $11,697 | 18% | **+53.2%** | [+10.3,+105.7] | 20.4 | 0.113 | **+9.1** [+5.9,+12.9] |
| 0.2–0.4 | 904 | $10,705 | 17% | **+14.7%** | [+2.6,+27.5] | 37.6 | 0.312 | **+6.4** [+3.3,+9.6] |
| 0.4–0.6 | 1,928 | $18,114 | 28% | −5.6% | [−11.6,+0.6] | 46.9 | 0.497 | **−2.8** [−5.0,−0.6] |
| 0.6–0.8 | 1,167 | $11,726 | 18% | +2.0% | [−2.9,+6.9] | 66.5 | 0.688 | −2.4 [−5.1,+0.3] |
| 0.8–1.0 | 1,172 | $11,926 | 19% | −1.0% | [−4.0,+1.5] | 84.9 | 0.925 | **−7.6** [−9.8,−5.7] |

Two cells have a measured edge. Two have a measured deficit, and their tol CIs exclude zero.
**47% of the notional sits in the two deficit cells; they lose about $1,134 between them.**

And the clip is inverted against all of it:

- **0.0–0.2 average clip $23.0, p90 $75.1** — the best edge, and the biggest bets.
- **0.2–0.4 average clip $11.8, p90 $18.0** — the second edge, and the smallest bets in the book.
- 0.8–1.0 average clip $10.2 — the worst calibration, bet at half the cheap band's size.

Nothing in the sizing path reads either number. It is not "flat across bands" (the form the 2026-10-20
finding took); it is **inverse to evidence** — the closest thing to a Kelly rule we have is pointed
backwards.

---

## 2. The live regime: the accuracy holds, the money doesn't

Opened ≥ 2026-10-26, legs that traded (246 legs, $5,037):

| band | n | notional | share | ROI | CI95 | tol pp |
|---|---|---|---|---|---|---|
| 0.0–0.2 | 47 | $1,968 | **39%** | **−53.4%** | [−84.0,−9.1] | **+0.1** [−6.7,+12.5] |
| 0.2–0.4 | 90 | $1,149 | 23% | **+25.6%** | [−13.5,+65.3] | **+7.6** [−1.7,+17.9] |
| 0.6–0.8 | 80 | $932 | 19% | −11.1% | [−32.1,+9.0] | −9.8 [−20.8,+0.3] |
| 0.8–1.0 | 29 | $987 | 20% | +0.8% | [−25.7,+19.4] | +8.0 [−7.1,+13.0] |

This is the most useful thing in today's numbers: **the cheap band's calibration is still ~0 (+0.1pp,
12.8% hit on 12.7% average price) while its realised ROI is −53.4%.** The accuracy did not break; the
tail did not land in three weeks, and a cell that loses 87% of every losing ticket shows a −53% ROI
from a break-even hit rate. That is what this distribution looks like over 47 draws — and it is why I
will not read a sign into the cheap band's ROI either way.

**The one cell that improved is the one we bet smallest.** 0.2–0.4 at +25.6% and +7.6pp in the regime,
on $1,149. Two windows, same sign, and the only cell where the sign never changed.

The clean post-fix cohort (35 legs that traded after the write fix, $681) says the same in miniature:
cheap 11 legs −87.1% [−100.0,−25.6], 0.2–0.4 18 legs **+59.4%**, book **−31.9%**. n is far too small
to carry a verdict; it is consistent with §2 and nothing more.

---

## 3. The ladder is a read, not a milestone — and it is reading a rung that was never climbed

`query_bankroll.js` computes the phase **at read time**: walk the rung table, advance while the
trailing 7 *settled* days sum to ≥ target × 7. Nothing stores "we earned Phase 2", and the sum reads
booked rows. So the rung is a rolling function of a number the 2026-11-09 fix disproved. Over the
whole book (106 rolling 7-day windows, 2026-07-23 → 2026-11-11):

- **$1,750 (Phase 1's need, $250/day): 14 of 106 windows clear on booked rows; 8 of 106 on true rows.**
- **6 of the 14 booked-clearing windows are false.**
- **$3,500 (Phase 2): 0 of 106 on either basis, ever.**
- Last booked window clearing $1,750 ends **2026-11-09**; last true one ends **2026-10-04**.

Reproducing the live read exactly (settled window 2026-11-02..11-08):

- booked: **+$2,687.34 → Phase 2 ($500/day), 76.8% of $3,500** — the number the tuning review quotes.
- true: **−$227.17 → Phase 1 ($250/day), −13.0% of $1,750.**

The ladder has not cleared even its first rung since the first week of October. It reports Phase 2
because one contaminated 7-day window is still inside the roll.

**The capital series that follows from it** (30 local days, the `/capital` chart's own rows):
**booked +$3,244.93, true −$757.58 — a $4,002.51 gap.** Apply the standing 50%-of-daily-profit sweep
to that series and it would have taken **$2,295.99 booked against $621.00 true: $1,674.99 of
withdrawal that was never earned.** In paper that is a reporting error. In production (2027-01-02
anchor) it is cash out of the book and a taxable event on fictional profit.

---

## 4. Prior measurements I am *not* overturning — and one that does not reconcile

- **Exit alpha stays closed.** The closed-vs-resolved split by band (H2) looks like the exit policy
  costs the 0.6–0.8 cell ~7pp (+$14 on 673 closed legs vs +$223 on 494 resolved). It is not evidence:
  those are different legs, and the same-leg measurement already exists — **−$621, CI [−4,405,+3,240]
  over 6,670 legs, spanning zero.** Resolved-only calibration is selected on survival and is an upper
  bound for exactly this reason. No exit proposal.
- **Three instruments, three true figures for the same 7-day window:** −$227 here (deduped legs that
  traded, entry+booked exits), −$348 in `profit-ledger-repair-preflight` (rows, entry+exit), −$377
  yesterday (163 legs, entry only). All negative, all fail rung 1. Quote the script you ran.
- **The 233-row repair is still pending** in the approvals inbox (`apr-ledger-price-side-repair`).
  Nothing today changes its evidence; §3 raises what it is worth, because the rung and the sweep read
  the same column, not just the gate.
- **Gate tuning stays exhausted** (liquidity, copy cap): the deficit cells above are price bands, and
  the two gate levers that were meant to address them closed NO-CHANGE under their own shadow reads.

---

# Recommendations

Ranked by expected value. Everything that changes what the bot decides or how much it risks is
**Lane A — propose only.**

### 1. Rebalance the clip: cap 0.0–0.2 at $25, lift 0.2–0.4 to $25 (Lane A, 1h)

- **Hypothesis:** the book's sizing is inverse to its evidence, so moving clip from the cell whose
  forward ROI is contested into the cell whose sign never changed raises PnL at identical gross.
- **Measurement:** §J, `_shadow()` over realised legs, PnL re-scaled linearly in dollars at risk with
  no re-selection, delta CI market-clustered. All-time **+$78** (CI [−5.8,+5.3]); regime **+$935**
  (CI [+5.5,+29.9]); clean cohort **+$287** (CI [+0.5,+74.6]). Notional under the plan:
  **$5,037 → $5,038 in the regime** — the same gross, a different cell. Split: the cap alone is
  −$2,108 all-time / +$790 regime (a window bet); the lift alone is **+$2,186 all-time** (CI
  [+1.2,+5.8]) / +$145 regime / +$63 clean — **the lift has never changed sign**. The package exists
  so that the history pays for the regime.
- **Decision rule:** apply the package; if only one half is approved, apply the **lift**. Size
  $25 = 2.1x the cell's current notional (from $10.7k to ~$22.9k over the same 904 legs), against an
  open book of $1,068–$1,146 under a $5,461 exposure cap (19–21% deployed).
- **Refutation:** (a) the book-walk shows a **median fill premium > 6.4c** in 0.2–0.4 — that cell's
  `tol` is +6.4pp, so a premium above it prices the whole lift away; or (b) 150 settled legs of the
  new mix with 0.2–0.4 ROI ≤ 0 **and** the cheap band back above +40% — that is the cheap band's edge
  returning at scale, and the cap was wrong.
- **Expected effect on profit:** +$2.4/leg on the ~900 legs that bind ≈ **+$9–13/day** at current
  volume; history-neutral (+$78 on $64k), forward-positive in both post-fix windows.
- **Cost:** 1h (band-relative min-clip in `score-trades.ts` sizing), plus the fill read before it goes
  live.

### 2. Make the rung and the sweep read the true basis, and let the rung fall (Lane A, 2h after the repair)

- **Hypothesis:** the ladder's phase and the production sweep are functions of booked rows, so both
  report one rung and ~$1,675/30d of profit that the true basis does not contain.
- **Measurement:** §I. 6 of 14 booked-clearing windows false; last true clearing window ends
  2026-10-04; live read Phase 2 at 76.8% booked vs Phase 1 at −13.0% true; 30-day booked +$3,244.93 vs
  true −$757.58.
- **Decision rule:** when `apr-ledger-price-side-repair` lands, the gate recomputes itself (it reads
  rows) — **accept the printed fall to Phase 1 and do not "fix" it back**. Then pre-register the
  sweep: 50% of **true** daily profit, `max(0, ·)`, and **no sweep on any day whose rows are inside
  the repaired class**. Store the rung with its basis string so a later read can say which ladder it
  is quoting.
- **Refutation:** if a repaired-row replay still clears $1,750 in the 7-day window ending 2026-11-08,
  the fall is an artefact of my estimator and the rung stands.
- **Expected effect on profit:** **$0 in paper.** In production it is the difference between sweeping
  50% of a real gain and withdrawing principal, taxed as profit: **−$1,675/30d** at current volume.
- **Cost:** 2h, most of it in the report string; the repair itself is already scoped at 1h + restatement.

### 3. Keep unfilled legs out of every ROI the system prints (Lane B instrument, reader change is a decision)

- **Hypothesis:** the 121 unfilled-and-unpaying legs in the regime are treated as $3,042 of risk that
  lost nothing, which dilutes every ROI toward zero and makes the book look 40% larger than it is.
- **Measurement:** §G/H/G3 exclusion line; regime book −11.9% (diluted) vs **−16.9%** (legs that
  traded); clean cohort 31 of 66 legs (47%) unfilled.
- **Decision rule:** every ROI surface (dashboard book, EOD, `/capital`, capital series) excludes
  `fillStatus='unfilled' AND realizedPnl=0` from both numerator and denominator, and prints the
  excluded leg count beside it.
- **Refutation:** if those legs are in fact filled and the zero payoff is a booking gap, the dilution
  is real risk and the exclusion understates the loss — check 10 of them against the venue's fill
  record before changing a reader.
- **Expected effect on profit:** $0; it stops the *decision* inputs reading 40% smaller losses.
- **Cost:** 45 min.

---

**IF YOU WEREN'T HERE:** lift the 0.2–0.4 clip to $25 and cap the cheap clip at $25 — it is the only
sizing change in this book whose counterfactual is positive in the post-fix windows at unchanged
gross, and it is the half of the book where the sign has never moved.

---

### Instrument repairs performed directly (Lane B, no approval needed)

- `scripts/profit-postfix-integrity.py` +4 sections, read-only, no prisma write, no RuleSet read or
  write, nothing in a decision path: **G** calibration (hit vs price with Wilson CIs), **H** clean
  cohort + closed/resolved split + band ROI by window, **I** ladder provenance and the 30-day capital
  series, **J** sizing shadow with clustered delta CIs. Self-tests extended (resize identity, risk-leg
  exclusion exact, reprice identity 12,781/12,781 legs) and passing.
- Two of my own basis errors were caught and fixed **before** quoting: unfilled legs in the
  denominator (§0a), and a first-draft sizing plan that capped and lifted the same band, which printed
  the lift-only delta for the combined arm (§J docstring).
- Nothing else touched: no rule, threshold, size, gate or lane moved; no `apply-v*.ts` run.
