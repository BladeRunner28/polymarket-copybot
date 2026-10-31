# Profit review — 2026-10-31

http://localhost:3013/drafts/profit-recs-20261031

**Cost basis on every ROI below: `simulatedPositionSize` / `$10` clip = dollars at risk, never
shares.** Settlement basis = `settle/px − 1` held to resolution; `edge` = hit% − mean entry px,
which is the break-even-conditioned statistic (break-even hit rate IS p). Both are printed because
they diverge across prices: a cheap winner carries ROI the edge number never shows.

Every figure is computed by **`scripts/profit-wallet-breadth.py`** (§WB.0–WB.5, new this commit).
Reproduce:

```
python3 scripts/profit-wallet-breadth.py            # first run fetches truth (~2.1k markets)
python3 scripts/profit-wallet-breadth.py --offline   # cache/archive only, no wire
python3 scripts/profit-wallet-breadth.py --selftest  # identity checks only
```

Window is anchored to UTC midnight, so a re-run the same day samples the same bets; the truth
archive under `data/.clob-truth-raw` makes the fetch stage resumable. The DB is live: two counts in
this file (514 vs 516 copies/30d) differ for that reason and both are printed.

---

## The population that had never been priced

Eleven reviews have measured the bets we took and the bets we refused — both drawn from the same
**25 wallets**. The containment rule in `src/lib/wallet-universe.ts` ("an observation row must never
reach a copy decision or a published number") means every script in `scripts/` obeys it, so the
**1,348 wallets whose trades we see and do not act on had never been valued at settlement.**

§WB.2 prices them: 60 seeded wallets, first print per `(wallet, market, outcome)`, bets 7–60 days
old, **2,287 settled bets in 2,222 markets (88.0% truth coverage; unresolved markets dropped, never
counted as losses).**

| population | n bets | mean px | hit | edge | ROI (ex-dust) | ex-top-10 ROI |
| --- | --- | --- | --- | --- | --- | --- |
| **uncopied, 1,348 wallets** | 2,287 | 0.567 | 57.5% | **+0.8pp [−0.6,+2.3]** | **+3.2%** (n=2,154) | **−5.4%** |
| copied, same window/basis | 3,758 | 0.559 | 55.0% | **−0.9pp [−3.1,+1.3]** | +7.2% | +3.1% |
| copied (yesterday's "arm 1") | 4,489 | 0.570 | 57.1% | +0.1pp | — | — |
| declined (yesterday's "arm 2") | 4,034 | 0.614 | 60.5% | −0.9pp | — | — |

The two bottom rows are **the same 25 wallets measured twice** — taken vs refused. Yesterday's
headline ("two independent populations agree") is therefore not independence at all; it is one
wallet set, one gate. I wrote that sentence and I am retracting it here.

Against a genuinely independent population, **the wallet universe has no measurable edge at any
width**: +0.8pp ± 1.5 over 2,287 bets is indistinguishable from the copy set's −0.9pp, and both are
indistinguishable from zero.

### By band, the independent population disagrees with our book in the middle and the top

| band | uncopied edge [CI] | uncopied ROI | n | our book (copied) |
| --- | --- | --- | --- | --- |
| 0.00–0.10 | −0.6pp [−2.2,+1.3] | +15.9% (convexity) | 273 | +74.1% (C-200) |
| 0.10–0.20 | +0.9pp [−5.4,+7.5] | +4.1% | 128 | +107.8% (C-200) |
| 0.20–0.40 | **+4.1pp [−0.6,+9.0]** | +11.1% | 369 | +17.4% (C-200) |
| 0.40–0.60 | −0.3pp [−4.9,+4.3] | −0.3% | 419 | +1.8% (C-200), −7.3% (STD) |
| 0.60–0.80 | −1.0pp [−5.8,+3.9] | −2.0% | 351 | +4.6% (C-200), +2.2% (STD) |
| 0.80–1.00 | **+1.0pp [−0.3,+2.3]** | +1.2% | 747 | −4.5% / −4.9% (both arms) |

Two consequences, and they are not symmetric:

1. **The rich-band deficit does not replicate.** −4.0pp and −4.4pp (both arms of the 25) versus
   **+1.0pp [−0.3,+2.3] on 747 independent bets**. The one fact yesterday's #1 leaned on hardest
   does not survive an independent population. (Scope limit, stated rather than buried: the
   independent rich bets average px 0.949, i.e. mostly above our 0.85 live ceiling, so this
   population does not tightly cover the 0.80–0.85 slice we actually buy.)
2. **The cheap-band premium also fails to replicate** — +0.9pp at 0.10–0.20 on 128 bets versus
   +5.4pp in our book. At this n the independent population cannot separate +7 from −5, so this is
   "unconfirmed", not "refuted". Either way it is not licence to size up.

What *does* survive every population: **nothing in the middle is positive, and nothing is large.**
The book's entire edge, on the honest basis, is +3.1% ex-top-10 (copied arm, 3,743 bets), which is
also what makes the ladder arithmetic below so brutal.

---

## The ladder, restated in the unit that actually binds

§WB.1/§WB.4, live funnel:

- 7d: **1,199,970 prints from 1,026 wallets in 62,185 markets**, 6,565 skips, 63 copies →
  **0.94% of decisions taken, 9.0 trades/day**
- 30d: 4,004,028 prints, 1,362 wallets, **514–516 copies = 17.1/day** at a ~$10 clip → **$171/day
  of notional**
- observed supply is not the constraint and never was: **1,348 observation-only wallets in 30d**
- and the uncopied population's edge is +0.8pp ± 1.5, ex-top-10 **−5.4%**

So: at the measured +3.2% ROI, a $500/day rung at a $10 clip requires **1,556 bets/day — 91×
current flow**. Expanding the copy universe to every wallet we observe (×40) yields ~685 bets/day
and **$22/day at ×4, $66/day at ×12, $220/day at ×40** — still 2.3× short of one rung, at an edge
that is statistically zero and negative ex-top-10.

**More wallets is not the lever either.** That closes the last supply-side hypothesis in the book.

The funnel also shows where the vetoes actually land (7d, 6,620 non-copy decisions):
**confidence < min 3,856 (58%)**, resolves in <2h 2,807, price drift 4,120 (both directions),
band skip 775, **C-200 "kelly no-edge" 739**, coalesced 660, spread 386, liquidity 358.
The Kelly gate is worth a sentence on its own: 739 times a week the lane's own edge model says
*no edge* and vetoes the bet. That is the system agreeing with this review.

---

## Two hypotheses killed here, so nobody proposes them again

§WB.0, our own book:

**"We are only duplicating a bet; cap legs per bet."** Ordinal ROI by `(bot, market, outcome)`:
1st +13.04% (4,733), 2nd +0.36% (1,599), 3rd–4th +6.20% (1,513), **5th+ +15.15% (4,532)**. The
marginal leg is not the loser — the late legs are the *best* cohort. A legs-per-market cap is
refuted on the book it would be applied to.

**"Wallet consensus is the signal."** 4+ wallet bets: +48.97% ROI on $15,862 raw, but **+4.67%
once the single largest bet is removed** (Spain to win the World Cup, 782 legs, $9,726, +$7,028 —
46% of the book's entire realized PnL). Incidence is also collapsing: 15.3% of legs (epoch 688) →
7.0% → 1.5% → **0.9%** (epoch 691). There is no flow left to size a consensus rule on.

---

## #1 — Withdraw the 2026-10-30 skip extension (STANDARD 0.40→0.85). Lane A, propose withdrawal.

**Hypothesis (the one being withdrawn).** Above 0.60 the territory "is not a return source at any
size", established by both arms agreeing on a negative rich-band edge.

**Measurement.** §WB.2 (independent population: 0.80–1.00 **+1.0pp [−0.3,+2.3] on 747 bets**;
0.60–0.80 −1.0pp [−5.8,+3.9] on 351) plus the existing §T/§AM.7 reads on our own book
(STANDARD 0.60–0.80 **+4.2%**, ex-top-10 +3.7%, 1,678 legs; C-200 +0.1%). The claim that made the
proposal rank #1 yesterday — two independent populations — is retracted above.

**Decision rule.** Withdraw when the independent population's 0.80–1.00 edge is **≥ 0 with a CI
that excludes −3pp**: measured +1.0pp [−0.3,+2.3] — met. The extension now rests on a band that is
positive in our own book and non-negative in the only population that was never selected by our
gate.

**Refutation.** Put it back on the table if a forward **300-leg** STANDARD 0.60–0.85 sample reads
**< −4pp edge ex-top-10**, i.e. loses on the break-even-conditioned statistic, not on a booked ROI
that is already conditioned by our exits. Counted from PaperTrade + settlement truth.

**Expected effect.** Preserves **+$845 of realized PnL on $19,990 (1,678 legs, +4.2%)** and 17.2% of
STANDARD's capital-time that the extension would have removed, and stops a rule landing on a
selection artefact. **Cost: 0.5h** (no code; close the card, record the refutation clause so the
question can reopen on data).

---

## #2 — Wallet-edge persistence is now the gate for every future proposal. Lane A, measure only.

**Hypothesis.** The only axis on which the book shows a measured spread is *which wallet*
(copied ex-top-10 **+3.1%** vs uncopied ex-top-10 **−5.4%**, and the uncopied pool's
score-vs-ROI rank read is underpowered at 24 wallets, ρ=+0.20, p=0.67). If per-wallet edge
persists, concentration is real and worth engineering; if it does not, no admission, band, size or
breadth change can ever be more than noise, and the ladder has no edge axis at all.

**Measurement.** `scripts/profit-wallet-breadth.py` supplies the population and the settlement
truth; the persistence read is a split-half of each wallet's per-bet edge (first 30d vs last 30d,
≥8 settled bets per wallet), market-clustered, with the multiplicity stated (1,348 wallets
screened, so the threshold must survive a permutation null of the *best* wallet, not of the mean).
Estimate: **2h**, mostly wire time already cached.

**Decision rule.** Act on wallet-based sizing/selection only when split-half per-wallet edge
correlation is **≥ +0.30 with a CI excluding zero at ≥ 100 wallets**. Below that, no wallet-based
change is admissible for the next 30 days regardless of how good a backtest looks.

**Refutation.** Correlation ≤ 0 with a CI excluding zero → wallet selection is noise by
construction; record it on the ladder card and re-derive the $5,000/day target from a mechanism
that does not depend on picking wallets (the band evidence — nothing positive between 0.20 and
0.80 in any population, and a zero-edge flow — says the copy mechanism cannot supply it).

**Expected effect.** $0 of PnL directly. It is #2 because it is the *only* question left whose
answer changes what the next month of work should be, and because the alternative — more gate,
band and breadth tuning — has now been measured to zero in three independent ways.

---

## #3 — The instrument, and three defects it closed. Lane B, done.

`scripts/profit-wallet-breadth.py` (§WB.0–WB.5, read-only DB, no RuleSet row touched):

1. **The uncopied population is priced for the first time** — §WB.2/§WB.3, with coverage,
   dust-floor counts and the market-clustered CI printed next to every number.
2. **Settlement mapping no longer fabricates losses.** The positional Yes/No fallback used by the
   existing readers fires on any two-token market; on a multi-outcome event (`tokens = A, B`) that
   silently converts an unidentified bet into a −100% loss. This script applies the fallback only
   when both token names really are Yes/No, and the selftest pins the refusal. (The same fallback
   still exists in `scripts/profit-velocity.py`; I did not touch that file this commit.)
3. **The truth fetch is resumable.** Records land in `data/.clob-truth-raw` and are read back
   before any wire call, so a re-run costs nothing and the window is anchored to UTC midnight
   instead of a rolling `now` (a rolling window silently invalidated the previous run's archive —
   observed and fixed here, not hidden).

Two hypotheses were also killed by measurement rather than argument (§WB.0 above), which is the
cheapest kind of prevention this review has produced.

---

## Contradictions I am not resolving silently

- **The drift-relaxation trigger is reading a basis that double-counts polls** (§WB.5). The
  pre-registered 2026-09-20 rule (tuning #31 rec 2) was written against the poll-row series, and on
  that series it has been tripped for **26 consecutive days** ($−1.47 trailing-7d cohort vs a
  $0.50 bar) — the relaxation it promises has never been brought forward. On the per-signal basis
  the same rule reads **+$0.85** and is not tripped. Counting poll rows is exactly the defect
  §AM.3 documents, where every-print vs first-print reversed the sign. Reported as an
  inconsistency: the prior reads (10-11, 10-20) found a tolerance move admits 19–21 legs and is
  co-blocked by confidence, so I am **not** re-proposing a drift change.
- **Yesterday's #2 is now moot for a different reason than yesterday's note.** `standardStaleExitHours`
  is 0 in v70 (checked again today), so the STANDARD exit rail is inert by parameter, and the
  decidable capital in the open book cannot be closed by any existing rule. I did not re-derive the
  open-book duration split this commit and am therefore not quoting it.
- **The copied arm reads +7.2% ROI and −0.9pp edge at the same time.** That is not a bug: ROI is
  convex in price, so cheap winners carry it. Every ROI line in this file states its basis and
  every conclusion here rides on the edge statistic plus ex-top-10, never on the headline ROI.
- **Breadth arithmetic uses +3.2% ROI, which is not tail-robust** (ex-top-10 −5.4%). §WB.4 says so
  on the same line; the +$22/+$66/+$220 per-day figures are an upper bound on a zero-edge pool,
  not a forecast.

---

**IF YOU WEREN'T HERE:** I would withdraw the 0.60–0.85 skip extension today. Its whole case was
that the taken and refused arms agreed — and both arms are the same 25 wallets. On 1,348 wallets we
never priced, the rich band is **+1.0pp [−0.3,+2.3]** and the band the extension would delete earns
**+4.2% in our own book**. What the independent population does say is smaller and bleaker: a
zero-edge flow, ~17 bets/day, 91× short of one rung of the ladder, and no wallet, gate, band or
breadth setting that closes it. This mechanism does not have an edge axis — the next month should
prove or kill that with #2, not ship another threshold.

---

### Provenance

| figure | source |
| --- | --- |
| uncopied edge/ROI/CI, band table | §WB.2, `scripts/profit-wallet-breadth.py` |
| copied arm same window/basis | §WB.2 (cached CLOB truth) |
| 4,489 / 4,034 bet arms, band edges | `scripts/profit-velocity.py --only-am` (§AM.2), unchanged |
| ordinals, consensus, podium bets | §WB.0 |
| funnel, vetoes, wallet universe | §WB.1 |
| 514–516 copies/30d, 17.1/day, ×4/×12/×40 | §WB.1 / §WB.4 |
| drift trigger two bases | §WB.5 reading `data/drift-shadow-summary.json` |
| STANDARD 0.60–0.80 +4.2%, 1,678 legs | `scripts/profit-velocity.py` §T (unchanged, quoted with scope) |

*Lane B applied directly this commit: `scripts/profit-wallet-breadth.py` (new), the truth archive it
writes under `data/.clob-truth-raw`, and this file. Read-only DB throughout. **No RuleSet row
touched, no rule edited, no `prisma/dev.db` write.***
