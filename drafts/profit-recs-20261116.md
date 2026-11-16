# Profit review — 2026-11-16

**The ladder is now measured four ways, and only one of those ways is a measurement. It says −$23/day.**

Yesterday I published three bases (booked $26.8/day, positions-only $7.1/day) and proposed moving the
credit to positions-only. Today the same script, run a day later, splits the same population a third
way, and the answer is not "positions-only is the honest basis". It is that **positions-only is a
second unadjudicated basis**, and that the two lanes are not even on the same accounting.

All numbers below come from two committed instruments run today:
`python3 scripts/profit-supply-ladder.py --regime 68` (new §S6) and
`DATA_MODE=live python3 scripts/profit-exits.py --live-closes --since=2026-09-01` (new §AO.11),
plus the repaired `scripts/standard-fill-stamp-merge.py` (the Lane B fix in §4).

---

## 1. Four bases, same legs, same clock (live regime, v68+)

| basis | legs | cost | PnL | ROI | $/day |
|---|---|---|---|---|---|
| booked rows | 421 | $9,141 | +$406.3 | +4.4% | +$20.5 |
| positions only | 230 | $4,387 | +$35.5 | +0.8% | +$1.8 |
| unadjudicated (`fillStatus IS NULL`) | 141 | $2,281 | +$490.9 | +21.5% | +$24.8 |
| **confirmed filled** | **89** | **$2,106** | **−$455.4** | **−21.6%** | **−$23.0** |

Read the bottom two rows together and the whole review falls out of them: **the book's positive
number is the class no fill model has ever looked at, and the only class we can prove we own loses
21.6 cents on the dollar.** Every dollar of the regime's +$35.5 of "positions" PnL is inside the
141 unadjudicated legs; take them out and the book is −$455.

Per lane, which is where it gets structural:

- **C-200 positions-only: 107 legs, $2,883, −$354.3 (−12.3%, −$17.9/day).** Every C-200 leg carries
  a fill stamp: 89 filled (−$455.4), 18 unadjudicated (+$101.1), 191 unfilled (+$370.8, excluded).
- **STANDARD positions-only: 123 legs, $1,504, +$389.7 (+25.9%, +$19.7/day) — and 123 of 123 are
  unadjudicated.** STANDARD has never received a single fill stamp. Its booth
  (`src/lib/standard-fill-stamp.ts`) is deliberately measurement-only and writes nothing to
  `PaperTrade`; the C-200 resolver (`scripts/c200-fill-resolve.ts`) is scoped `botId: "BANKROLL_200"`.

So yesterday's cross-lane comparison — and mine, in the 11-15 brief — compared an adjudicated book
against an unadjudicated one and called the difference "the cheap band". It is not the band. In the
same price band the two lanes disagree in sign because one lane's legs have been tested for fill and
the other's have not.

## 2. Why yesterday's card under-reaches

`ladder-credit-positions-only` (Backlog, awaiting approval) proposes crediting the ladder on
positions-only, citing the 182 (now 191) `unfilled` rows worth +$370.8. That fix is real but
insufficient: it moves the published rate from $20.5/day to $1.8/day while leaving the +$490.9 that
actually decides the sign untouched. Approving it alone would publish $1.8/day as if it were a
measurement of a book that earns money. **The card should ship, and it should ship printing all four
bases, not one.**

The decay is also now visible inside the instrument: yesterday positions-only read $7.1/day; today
$1.8/day; the last 14 days on the same basis are **−$5.6/day** (yesterday: −$6.0). That is not noise
trending my way — it is the same mechanism, settling: as legs get adjudicated they move from the
positive unadjudicated class into the negative filled class.

## 3. The exits are not the leak, and I have to retract a hypothesis I formed this morning

I opened this review expecting to find the C-200 exit rails destroying value: in the live window, 21
positions closed early for −$360 (−49%) while the bands that produced them read positive elsewhere.

Measured properly (settlement truth, both arms on the same legs, cost = dollars at risk):

- **Live window (since 2026-10-27):** 14 legs with truth, alpha (hold − exit) = **+$643.18**. One
  market carries it: `will-bitcoin-dip-to-77pt5k-in-october-2026`, alpha **+$659.36**. Ex-top-market
  alpha is **−$16.18** (−4.8%). A rail's verdict cannot rest on one leg.
- **Since 2026-09-01: 637 legs, 443 markets, 88% truth coverage, two independent truth bases
  (archived CLOB winner and the exit-recovery final marks) agreeing on 280/282 (99.3%).**
  held-to-settlement +$249.77 vs exited +$1,315.41 → **alpha −$1,065.64 (−12.4% of cost),
  market-clustered 95% CI [−$2,517, +$667]**. Ex-top-market alpha is −$1,725, so the direction is
  not a single event.
- The negative alpha is not uniform: the cheap band (entry <0.60) supplies −$1,033 on $5,732 while
  0.60-0.80 is only −$47.85. Which is the honest reading of a stop on a longshot: at 0.05, a mark is
  noise, and this rail sells noise.

**Verdict: no change, in either direction.** The point estimate says the rails saved $1,066 by
selling below settlement; the CI spans zero; the live-window sign is opposite and is one leg. A
proposal to widen, shorten or remove this rail would be a proposal built on a coin flip. The finding
worth keeping is narrower and firmer: **the cheap band's loss is an entry loss, not an exit loss** —
the rails already harvest what is harvestable after entry.

## 4. LANE B — the STANDARD fill booth had met its own gate and could not read it (fixed, verified)

`standard-fill-stamp` is the instrument that decides the lane's booking question, with a
pre-registered rule: *ship a booking change only once stamped fills exist on ≥300 STANDARD legs; the
claim "a 1c improvement is worth +$1,439.33" is refuted if stamped fills land within ±0.3c of the mid
on ≥300 legs.*

The chain runs hourly, each tick stamping only the legs opened since the last tick, then merging into
a union (`data/standard-fill-stamp.jsonl`). The union today holds **1,011 legs, 380 of them with a
book snapshot and a mid — 80 past the gate.** And the artifact's own verdict read:

    refutation.book: {"n": 1, "gateMet": false, "reason": "NOT EVALUABLE: n=1 of the required 300..."}

because the merge kept the *newest tick's* aggregate blocks and (correctly, in a comment) declared
that they describe one run only. Net effect: the gate's population was met months ago and the file
could never say so. **That is an unfalsifiable probe — a condition the instrument structurally cannot
cross — and it is the third instance of this defect class in three days.**

Fixed in `scripts/standard-fill-stamp-merge.py`: the union now computes and stores `unionRefutation`,
taking the gate and band **from the snapshot's own refutation block** so there is no second definition
of the test, and printing it on every merge. Verified against the live artifact:

- gate **MET**: n = 380 / 1,011 stamped
- `(attainable − mid)` mean **+0.26c**, median +0.00c, **70% within ±0.3c** → **the pre-registered
  refutation FIRES.** There is no cent to harvest; the "+$1,439.33 for a 1c better entry" claim is
  dead.
- `(attainable − booked)` mean **+1.05c**, median +0.50c, at-or-better **10.0%**, worse-by-1c-or-more
  **35.5%**; on $6,091 of booked notional the same-legs money weight is **+$257.52 = +4.23%**.
- It is spread, not drift: the 0-10s lag bucket (165 legs) already reads **+0.97c**, and 10-30s
  +0.92c. The cost is there before any latency.

So the lane's picture is now two-sided and neither side is a scandal: **STANDARD books at the mid
while a taker pays about a cent above it, which costs 4.2% of notional — and its +25.9% survives
that as roughly +21.7%.** The lane's edge is not an artifact of the fill model. It is, however, 4.2%
smaller than every surface currently reports.

---

# Recommendations, ranked by expected value

### 1. The ladder and the EOD print all four bases; the credit line is the confirmed-filled one — LANE A, propose only

**Hypothesis.** The advance rule currently reads a basis that includes 141 legs no fill model has
examined (+$490.9 in the live regime). Publishing the confirmed-filled line beside the other three
stops the ladder from advancing on positions that may never have existed.

**Measurement.** `scripts/profit-supply-ladder.py --regime 68`, §S6 (four bases per lane, same
clock); §S5 for the 7d/14d/regime windows. Regime: filled −$455.4 / −$23.0 per day on 89 legs;
unadjudicated +$490.9; positions-only +$35.5.

**Decision rule.** Ship as a *read-path* change with no rule value touched: every surface that feeds
the rung or the EOD prints `filled / unadjudicated / unfilled` counts beside the number, and no rung
may be reported "reached" on a basis that includes unadjudicated legs. Approve together with
`ladder-credit-positions-only` (that card is a prerequisite, not an alternative).

**Refutation.** Withdraw if a 150-leg forward sample of the unadjudicated class, adjudicated against
the venue tape, shows ≥60% of them filled AND a non-negative ROI — then the class is real positions
and belongs in the credit.

**Expected effect.** No PnL. It changes what the ladder is allowed to claim: +$20.5/day → −$23.0/day
on the only basis that is a measurement, which is the difference between "4.4x from the rung" and
"moving backwards". Cost: **1h**.

### 2. Price the STANDARD lane's booked PnL at the attainable ask — LANE A, propose only

**Hypothesis.** STANDARD books `entryPrice = currentPrice` (a mid read at scoring time) and books
`p(fill) = 1` at it. On the 380 union legs with a book snapshot, the best ask at/after the decision
sits +1.05c above the booked price; the lane's realisable PnL is therefore ~4.2% of notional lower
than reported, on every surface that reads it.

**Measurement.** `scripts/standard-fill-stamp-merge.py` → `unionRefutation`: n=380, mean ask − booked
+1.05c (median +0.50c), at-or-better 10.0%, worse-by-1c+ 35.5%, money weight +$257.52 on $6,091 =
+4.23%; probe-read in the 0-10s bucket (+0.97c/165) so the cost is spread, not latency.

**Decision rule.** Apply if, on a forward re-read of ≥150 newly stamped legs, mean (ask − booked) is
≥ +0.8c and the money weight is ≥ +3% of notional. Both hold today. Implement as a per-leg realisable
price for reporting and for the ladder credit, not as a change to `entryPrice` (which stays the
decision price) — the paper book must keep its decision and its fill separate.

**Refutation.** Withdraw if a forward 150-leg sample puts the best ask within ±0.3c of the booked
price on ≥50% of legs (i.e. our bookings are attainable at the ask). At 10.0% at-or-better today that
would be a genuine regime change.

**Expected effect.** On the live regime's STANDARD legs: +25.9% → **≈ +21.7%**, i.e. −$63 on $1,504,
and the regime book from +$35.5 to ≈ −$27. Cost: **2h** (read path + a printed two-basis week).

### 3. No change to exits, gates, clips or size — the measurement is not there, and here is what would unlock each

**Hypothesis (of the hold).** The exit rails' alpha is indistinguishable from zero and the
confirmed-filled class is not distinguishable from its own noise, so every available change trades
one unmeasured quantity for another.

**Measurement.** `scripts/profit-exits.py --live-closes --since=2026-09-01` §AO.11 (637 legs, 443
markets, 88% truth, 99.3% base agreement, alpha CI [−$2,517, +$667]); §S6 for the filled class.

**Decision rule.** No change to `staleExit*`, `c200ClipCapUsd`, band factors, gates or size until:
(a) exits — a forward cohort of 200 rail-fired legs whose alpha CI excludes zero; (b) size — 200
forward **confirmed-filled** legs at ≥ +20% dollars-at-risk ROI with ex-top-10 positive. Today: 89
filled legs at −21.6%.

**Refutation of the hold.** Either threshold above, met on a forward sample, refutes "the measurement
is not there" and unlocks the change. The cheapest of the two is the exit cohort: the rail fires
roughly 30 legs/month.

**Expected effect.** Zero by construction. Cost: **0h**.

---

**IF YOU WEREN'T HERE:** make the rung print four bases and credit only the filled one. The book has
89 legs whose fill is proven and they lose 21.6 cents on the dollar; the profit being quoted comes
from 141 legs no fill model has looked at. A ladder that cannot tell those apart is not measuring a
book.

**What I did not re-litigate, and why.** Gate tuning (liquidity and wallet cap both closed NO-CHANGE
under their own shadow reads); the 0.4-0.6 skip (live in both lanes: `standardSkipBandRange` and
`c200SkipBandRange` are both `0.4-0.6`); the $25 clip cap (carded yesterday, unchanged); band-factor
sizing on STANDARD; the TTR/maturity schedule (v68/v69 — and note today's data does *not* support a
further cut of the ≥168h bucket: capital is not the binding constraint, since C-200 carries 6 open
legs / $86 against a $1,000 cap and STANDARD 392 legs against a 1,300-leg cap, so a $/capital-day
argument has no purchase right now); the cheap-refusal ask-pricing (carded, needs MarketSnapshot
coverage).

**Supporting claims kept separate.** §4's union verdict (a measured distribution of 380 legs against
the venue book, CI-free but n-gated) is independent of §1's basis decomposition (an accounting
identity on `fillStatus`). Either can be approved without the other. §3's exit alpha is a third
independent measurement and supports neither.

**Caveats that travel.** (a) The filled class is 89 legs and its spread across weeks is wild — one
day (2026-11-11) contributes +$513. The 2026-11-13 venue-tape read at 515 C-200 legs put the filled
class at −7.7% with CI [−29.3, +17.6]; today's −21.6% is inside that interval, so the **sign** is the
robust part, not the magnitude. (b) The union's 380 stamped legs are those the L2 corpus could cover;
`standardLegsAll` is 10,403, so the stamp speaks to 3.7% of the lane's history and the 4.23% money
weight assumes the unstamped 96% behaves like the stamped 3.7%. (c) `attainable` is reachability, not
a fill: a best ask at or below a price ignores queue and size.

**Lane discipline.** Lane B applied and verified: `scripts/standard-fill-stamp-merge.py` now computes
`unionRefutation` and the live artifact `data/standard-fill-stamp.jsonl` carries it (gate MET,
refutation FIRED). Lane A untouched: no RuleSet read or write, no `apply-v*`, DB opened `mode=ro`, no
prisma write. Instruments committed in the same commit: `scripts/profit-supply-ladder.py` (§S6),
`scripts/profit-exits.py` (§AO.11), `scripts/standard-fill-stamp-merge.py` (union verdict).
