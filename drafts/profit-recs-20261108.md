# Profit review — 2026-11-08

**Instrument:** `scripts/profit-price-side.py` (committed with this file, read-only
`file:prisma/dev.db?mode=ro`). Reproduce with `python3 scripts/profit-price-side.py`;
`--self-test` runs inside it and passes (payoff identity 1,219/1,219 on resolved legs not
zeroed by the fill resolver; the classification partitions the population; a synthetic
reprice returns the hand-computed answer). `--no-snapshot` skips §3.

Population: regime (`ruleSetVersion >= 49`), 2,102 finished legs, $29,671 of notional at
**dollars at risk** (`simulatedPositionSize`, never shares). ROI = PnL / notional.

---

## 0. The verdict in five lines

1. **On 87 legs the ledger books the complement of the price that was paid.** Not close to
   it — mirrored about 0.50 to a **median of 0.007** (p90 0.020). The control class is off by
   0.295 on the same statistic. Two independent fields mirror together: booked entry (0.007)
   and the market read at detection (0.005).
2. **They are 4.1% of legs and 56.3% of the book.** 87 legs, $2,362 of notional,
   **+$4,965 of the book's +$8,817 (+29.7%)**. Booked, they return +210%.
3. **The defect is visible without any external data.** They hit **59.8%** at a booked
   average price of **0.246** — a +35pp "edge" on 87 legs. The price the copied wallet actually
   paid for the same labelled outcome averages **0.746**, and at that price the class books
   **+$15, not +$4,965**.
4. **The market quote says which side is wrong.** On the 40 biggest of them, `MarketSnapshot` at
   the trade minute puts the booked price on the **YES side 40 times out of 40**, at a median
   distance of **0.000**, while the wallet's fill sits on the **no** quote to within 0.005.
5. **The ladder is advancing on it.** The C-200 7-day gate reads **+$2,151** and passes
   Phase 1 ($250/day). Corrected, the same window reads **−$109** and passes nothing.
   **107% of the gate sum is the class.**

**Nothing was applied.** No RuleSet row, no rule, no size, no gate, no exit, no prisma write.
Every number below is a read.

---

## 1. The class

| class | legs | notional | booked PnL | ROI | % of book | hit | booked px | wallet px |
|---|---|---|---|---|---|---|---|---|
| **INVERTED** | 87 | $2,362 | **+$4,965** | +210.2% | **56.3%** | 59.8% | **0.246** | 0.746 |
| consistent | 1,981 | $26,849 | +$3,947 | +14.7% | 44.8% | 41.0% | 0.439 | 0.448 |
| neither | 34 | $460 | −$94 | −20.5% | −1.1% | 52.9% | 0.435 | 0.544 |
| **total** | **2,102** | **$29,671** | **+$8,817** | **+29.7%** | | | | |

Definition, so nobody can widen it after the fact: **INVERTED** = `|booked − (1 − wallet)| < 0.06`
*and* `|booked − wallet| > 0.10` *and* the mirror is the closer of the two hypotheses.
**consistent** = `|booked − wallet| ≤ 0.06`. The separation requirement is what stops a 0.49
leg being called inverted because the complement of 0.51 is also 0.49; it is also why 87 is a
**lower bound on the count and not a lower bound on the dollars** — an inversion near 0.50 is
invisible to the test and worth nothing either way.

**It starts on a date.** First leg in the class opened **2026-10-26**; none in September, 26
in October, 61 in November. 8 wallets carry it; two carry 66 of the 87 (`0xf5a3504a` 33,
`0x885ffdf3` 33). These are the two wallets the cheap-band concentration findings of the last
two weeks kept pointing at.

---

## 2. Why this is a price-side defect and not a statistic

**(a) The mirror is arithmetic, not movement.** Within the class, `|booked − (1 − wallet)|`
has median 0.007 and p90 0.020 — and so does `|detected − (1 − wallet)|` at 0.005. Price
movement does not produce complements to a cent in two separate fields. The control class has
`|booked − wallet|` median 0.011, which is what a correctly-copied book looks like.

**(b) The hit rate is the tell, and it needs no second data source.** A BUY at 0.246 breaks
even at a 24.6% hit rate. This class hits 59.8%, and 61.1% in the top wallet-price quintile
where the booked price is 0.105. A 0.105 bet that wins 61% of the time is either the greatest
edge in the history of this book or a 0.105 that is not the price. Against the wallet's price
the same class runs **−14.9pp**, i.e. slightly worse than break-even — the normal signature of
a copied book.

**(c) The market agrees with the wallet, not the ledger.** §3 of the script looks up
`MarketSnapshot` within ±15 minutes of the trade and asks which side the booked price sits on.
Top 40 by |PnL|: **YES side 40, NO side 0, neither 0.** The booked price is not *near* the
market's yes quote — median distance **0.000** — while the wallet's fill price is the no quote
to within a median **0.005**. The legs are `UNDER` and away-team / second-player outcomes (66
team-or-player labels, 21 UNDER, zero `NO`), so the ledger is holding the *sibling token's*
price. Worked example, `ucl-mnu-rom-2026-11-03-total-5pt5`: snapshot at the trade minute reads
yes 0.115 / no 0.885; we hold `UNDER`; the wallet paid 0.880; we booked 0.113 — and then
collected **+$782** on a $100 clip as if a 0.113 longshot had won.

(Stated honestly: with yes+no=1, "booked = 1 − wallet" already implies "booked = yes quote" up
to the spread, so §3 is not a second independent statistic. What it adds is that the **market**,
not only the wallet, is on the other side — the wallet is not an outlier against the book.)

**(d) Direction is one-sided.** A win at the complement pays `(1−0.12)/0.12 = +633%` instead
of `(1−0.88)/0.88 = +14%`; a loss costs −notional on either basis. So the defect cannot make a
leg look worse — it manufactures winners and leaves losers alone. That is exactly the shape of
the class's PnL distribution: repriced at the wallet's price it earns **+0.6%** on $2,362 while
booked it earns +210%.

---

## 3. The date explains the mechanism

On **2026-10-26** the drift gate was made directional (Lane A, approved; `f61fdbe`): a price
that *fell* below what the copied wallet paid stopped being "too late" and became a bargain.
Before that change the gate compared `|current − walletEntry|` against 0.004, so a leg whose
read price was 0.113 against a wallet price of 0.880 — a 0.767 "fall" — was **blocked**. Every
leg in the class was opened on or after the day that test was removed.

So: **the drift gate was accidentally the filter for a price-read defect, and removing the
filter exposed it.** The fix was right in principle (refusing better prices is wrong) and I am
not proposing to revert it. But its scoreboard is now the defect's scoreboard:

| post-2026-10-26 settled cohort | legs | notional | booked | inverted share | ex-inverted |
|---|---|---|---|---|---|
| favourable drift > 5c | 99 | $2,662 | **+186.6%** | 87 of 99 inverted | **12 legs, +$1.40 (+0.5%)** |
| favourable drift 0.4–5c | 68 | $1,260 | +4.0% | none | +4.0% |
| adverse drift > 0.4c | 99 | $1,460 | **−22.9%** | none | −22.9% |

The card's verify clause was "the favourable-admitted cohort settles above +20%; refuted if it
settles below +5% on ≥150 legs". At 99 legs the population clause is not yet met, but there is
nothing to wait for: **ex-inverted, that cohort is +0.5% on 12 legs.** The adverse branch it
keeps blocking still books −22.9%, so the gate is doing the useful half of its job; the
"favourable drift is where the edge is" reading of the last two weeks is this defect.

---

## 4. What it does to every number in the book

Reprice = the class's wins paid at the wallet's own price; losses unchanged; legs the fill
resolver already booked at zero left alone. It is an **estimate** and it is biased one way: the
wallet's price is the only independent estimate of what the token cost, it carries no slippage,
and on an inverted leg it is always the higher price. The corrected totals are therefore a
*floor* on the correction, not a symmetric adjustment.

| book | booked | corrected |
|---|---|---|
| all regime legs | **+$8,817 (+29.7%)** | **+$3,867 (+13.0%)** |
| C-200 | +$8,415 (+47.7%) | +$5,067 (+28.7%) |
| STANDARD | +$402 (+3.3%) | **−$1,200 (−10.0%)** |

By band (deduped, where the ledger filed each leg):

| band | legs | booked ROI | inverted in band | corrected ROI |
|---|---|---|---|---|
| 0.0–0.2 | 302 | **+85.3%** | 32 | **+46.8%** |
| 0.2–0.4 | 503 | +18.9% | 52 | +7.8% |
| 0.4–0.6 | 672 | −7.4% | 0 | −7.4% |
| 0.6–0.8 | 440 | −0.2% | 0 | −0.2% |
| 0.8–1.0 | 21 | −4.5% | 0 | −4.5% |

Three things follow, and the first two are what I got wrong in the last two reviews:

- **The cheap band's edge survives, at half strength.** +85% → **+46.8%**. "Cheap is where the
  money is" is still true; the size of it was inflated by fake longshots.
- **The 0.2–0.4 band was mostly the defect** (+18.9% → +7.8%). Yesterday's 0.20–0.40 un-rail
  was priced at a cohort rate that is now roughly halved. Its decision — do not escalate, hold
  at 2× legacy-equivalent — gets *more* right, not less.
- **The concentration was the defect.** ex-top-5 the booked book is +$4,117 (+14.1%); corrected
  it is **−$64 (−0.2%)**. ex-top-10, +$1,383 (+4.8%) → −$1,197 (−4.2%). The book is not
  "two wallets and a bond"; the residual is flat.

And the ladder:

| C-200 gate, 7 local days (2026-11-02 … 11-08) | booked | corrected |
|---|---|---|
| legs | 124 | — |
| sum | **+$2,151.04** | **−$109.06** |
| of which the class | **+$2,306.29 = 107% of the sum** | +$46.19 |
| $250/day phase (needs $1,750) | **PASS** | **fail** |

The lane has not earned its first rung. It is passing it on 28 legs whose price is the
complement of what was paid.

---

## 5. What this does to yesterday's two findings

**Yesterday's #1 (the marginal dollar earns 18.3pp less) does not survive as stated.** The
class holds **48% of the ≥$18-clip PnL** and is 4.5% of ≥$18 legs. Excluding it, the raw clip
contrast runs the other way:

| deduped tier | legs | booked ROI | inverted | ex-inverted ROI |
|---|---|---|---|---|
| clip ≥ $18 | 758 | +40.0% | 34 (4.5%) | **+22.7%** |
| clip $5–18 | 405 | +41.1% | 44 (10.9%) | **+23.6%** |
| clip < $5 | 775 | +12.7% | 6 (0.8%) | +6.3% |

Big clips no longer earn *less* than small ones — the small tier is the worst one. That is a
raw tier comparison, not the wallet+price fixed-effects estimate yesterday published, so the
honest statement is: **the −18.3pp coefficient was estimated on a population where half the
big-clip PnL is a pricing artifact, its sign is not safe, and it must be re-run before any
proposal is priced on it.** I am not asserting the opposite number; I am withdrawing the
basis of yesterday's.

**Yesterday's #2 (the cheap-band breadth stop) keeps its conclusion and loses its inputs.** The
trigger is pre-registered on cheap-band ex-top-2 ROI ≤ 0. On the corrected basis the cheap band
is +46.8% and its concentration is materially weaker than the booked version showed, so the
trigger will fire late rather than early. Re-base it on the corrected series when the price
read is fixed; do not fire it on the booked one.

---

## 6. Recommendations, ranked by expected value

### 1 — LANE A (propose, 1.5h): **book the price of the token that was bought.**

**Hypothesis.** The leg's `entryPrice` (and the `detectedPrice` that feeds it) is read from the
YES side of the market irrespective of which outcome the leg holds, so on a NO-side / second-
outcome leg the ledger pays a favourite at a longshot's price and the book overstates PnL by
~56% of its total.

**Measurement.** `scripts/profit-price-side.py` §1–§4: 87 legs mirrored to a 0.007 median;
59.8% hit against a 0.246 booked price; `MarketSnapshot` YES-side 40/40; class PnL +$4,965
booked, +$15 at the wallet's price. Regression date 2026-10-26 (drift gate went directional).

**Decision rule.** Fix the outcome→token price read at its source (one site: the read that
populates `detectedPrice` / booked entry). Acceptance: on the next 150 settled regime legs, §1
reports **INVERTED n = 0**. Do **not** touch the drift gate, the band map, the clip, or the
RuleSet — the drift gate is behaving correctly on a bad input.

**Refutation.** If a tape check of ≥20 of the 87 legs (v2 trades feed, `condition_id` + the
outcome label per token) shows the booked price is what those tokens actually traded at, then
the wallet's price is the wrong one and this is a wallet-side recording defect instead — a
different fix in a different file. §3's snapshot check covers 40 of the 87 and none disagrees;
the tape is the next step only if the fix is disputed.

**Expected effect:** removes +$4,965 of the book's +$8,817 and re-bases every band, ladder and
concentration read in this project on a real price. It does not itself make a dollar — it stops
the book from being read at 2.3× its true size, which is what every pending size proposal is
currently priced off. **Cost: 0.5h to card, ~1h to fix + verify.**

---

### 2 — LANE A (decision, 0h): **do not advance the C-200 ladder into Phase 2, and re-base the
advance sum net of the class.**

**Hypothesis.** The 7-day gate sum currently reads +$2,151 and passes $250/day; 107% of that
sum is legs whose booked price is the complement of what was paid, and the corrected window is
−$109.

**Measurement.** `scripts/profit-price-side.py` §7 — the dashboard's own basis (C-200,
`closed|resolved`, 7 local calendar days, T+0 included).

**Decision rule.** No rung advance while the class is >20% of the gate sum. After rec 1 ships,
require one full 7-day window on the corrected basis to clear the target before any advance;
advance is then judged on the corrected number only.

**Refutation.** If, after rec 1, the same class is found to be genuine (rec 1's refutation), the
gate sum stands at +$2,151, the phase is earned, and the advance should proceed unchanged.

**Expected effect:** prevents the one mechanism that increases real risk (the ladder) from
scaling on phantom profit — at Phase 1 that is the difference between scaling into $2,151 of
"earned" daily profit that does not exist and holding a $250/day rung the lane can actually
clear. **Cost: 0h** — it is a decision not to act.

---

### 3 — LANE B (done): **a price-side census in the review path, and the two open tests
re-stated.**

**Hypothesis.** A five-line classification (`|booked − wallet|` vs `|booked − (1 − wallet)|`)
would have caught this on the first day of the class instead of after $4,965 accumulated, and
the two pre-registered tests it contaminates (the drift card's verify clause, the cheap-band
breadth trigger) were both being read off it.

**Measurement.** `scripts/profit-price-side.py` §1–§3 and §9, shipped read-only with this file.

**Decision rule.** Every profit review prints §1. If INVERTED n > 10 in a 7-day window, the
review must open with it before any sizing or band claim.

**Refutation.** If §1 reports INVERTED n = 0 for two consecutive weeks after rec 1, the check
can be demoted to a monthly line and the drift cohort's +186.6% can be taken at face value.

**Cost: 0h** — written, run, and committed with this file.

---

**IF YOU WEREN'T HERE:** fix the price read before anything else changes, and do not advance the
ladder this week. The book is +$3,867 (+13.0%), not +$8,817 (+29.7%); the C-200 7-day gate is
−$109, not +$2,151; and the cheap band is +46.8%, not +85%. No size, no clip, no gate, no band
map.

---

## 7. Contradictions, corrections, dead ends

- **I am contradicting two of my own recent readings and naming the reason.** "The marginal
  dollar earns 18.3pp less" (yesterday) and "STANDARD's cheap cell is the best edge in the book,
  z = +3.7" (yesterday's §3) were both computed on this class. STANDARD books +$402 as a lane;
  corrected it is **−$1,200**. The conclusion "no size increase in STANDARD" was right; its
  stated basis was not.
- **Not the same as the fill-aware card.** That one (68.6% phantom) is about legs that were
  never positions. This is about legs that were positions, booked at the wrong price. They
  compound in the same direction and they must not be added together.
- **The 252 `unfilled` legs that still carry PnL are not this defect** — the fill resolver
  zeroes a leg only when settlement happens after the stamp, so 188 stamped-unfilled legs still
  book their original PnL. That is the known stamp-latency residue on the fill card, and I am
  not re-proposing it here; my §2 self-test excludes those legs rather than counting them as
  broken identities.
- **Not re-litigated:** the 0.4–0.6 skip (−7.4% corrected, unchanged by this); the $100 clamp;
  the liquidity blocker and wallet copy cap (closed NO-CHANGE); the 25-slot track list (no
  candidate-level flow measurement exists); exit alpha (CIs span zero); wallet persistence
  (split-half ρ = +0.058).
- **Capital velocity:** unchanged by this — capital-days are still legacy residue, and the
  corrected book makes the argument weaker, not stronger, because the dollars that were being
  recycled were partly fictional.
- **One number I could not settle:** whether the read is inverted only on multi-outcome sports
  markets (66 team/player labels + 21 UNDER, no `NO` label among the 87) or on every market
  whose outcome is the second token. The class has zero `NO` legs, which suggests the sports
  markets' token ordering rather than a general yes/no bug — but that is a hypothesis about the
  fix site, not a measurement, and rec 1's acceptance test (INVERTED n = 0) covers both.

---

## 8. Instrument

`scripts/profit-price-side.py`, read-only, Python 3 stdlib. §1 classification ledger with the
class's date range, month split and wallet concentration; §2 the mirror statistic against the
control; §3 the `MarketSnapshot` side check; §4 the hit-rate test plus wallet-price quintiles;
§5 reprice by class and by lane with the book totals; §6 booked-vs-corrected band table on
deduped legs (first leg per bot|wallet|market|outcome, the base instrument's rule); §7 the C-200
ladder gate on the dashboard's own basis with phase verdicts; §8 ex-top-N both ways; §9 the two
open tests; §10 self-tests (payoff identity, partition, synthetic reprice, zero-stake guard).

**No prisma write. No RuleSet row touched. No rule, size, gate, threshold or exit changed.**
Rec 1 and 2 are proposals; rec 3 is an instrument, shipped.
