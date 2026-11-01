# Profit review — 2026-11-01

http://localhost:3013/drafts/profit-recs-20261101

**Cost basis on every ROI below: `simulatedPositionSize` = dollars at risk, never shares.**
A `$n` buy at `p` is `n/p` shares; settlement at `s` realises `n*(s/p − 1)`. `edge` = hit% −
mean entry px, which is the break-even-conditioned statistic (break-even hit rate **is** p).
Every ROI line states its window and basis; the edge statistic carries the conclusions, the
ROI headline does not.

Every figure is computed by two committed scripts. Reproduce:

```
python3 scripts/profit-wallet-breadth.py --only-wb6        # WB.6 + WB.7 (first run fetches truth)
python3 scripts/profit-wallet-breadth.py --only-wb6 --offline   # cache only, same numbers
python3 scripts/profit-wallet-breadth.py --selftest        # identity checks
python3 scripts/profit-velocity.py                         # T, U, V, W, X, Y, Z (unchanged)
```

Window for WB.6/WB.7 is anchored to UTC midnight (so a same-day re-run samples the same bets);
the truth archive is resumable and now 17,159 markets deep. The DB is live.

---

## The gate I was told to wait on came back null, and it took the last alternative with it

The 2026-10-31 review pre-registered one question and said everything else should wait for it:
**does a wallet's measured edge persist into its own next 30 days?** §WB.6 answers it on a panel
built for the purpose — 200 observation-only wallets sampled by reservoir, split by **time**
(half A = day −60…−30, half B = day −30…−7, so no market leaks across the split), first print
per `(wallet, market, outcome)`, settlement truth on 7,179 distinct markets (5,602 of 5,661
uncached fetched, **99.0%**).

**158 wallets clear ≥8 settled bets in each half: 3,557 bets in A, 3,972 in B.**

| read | result |
| --- | --- |
| pool edge, half A / half B | **+0.15pp / +0.28pp** — the universe is a zero-edge book |
| cross-wallet spread vs sampling noise | 80.3 pp² observed vs **114.6 pp² noise → reliability 0.00** |
| implied true cross-wallet edge sd | **0.0pp** (observed sd 9.0pp) |
| pre-registered split-half Spearman | **ρ = +0.058**, permutation p = 0.482 (null 95% band −0.161…+0.159) |
| **bar: ρ ≥ +0.30 with a CI excluding zero** | **NOT MET** |
| top-25 by half-A edge → half-B edge | **+1.02pp [−2.76, +5.09]**, permutation p(selection) = 0.385 |
| bottom-25 by half-A edge → half-B edge | −2.10pp |
| top-50 vs bottom-50 | **+1.41pp vs +1.47pp** — the extremes are identical |
| production ranker (`WalletProfile.globalScore`) | **ρ = −0.006, p = 0.930** on 158 wallets |

Three things follow, and the third is the one that matters.

1. **The spread across wallets is not real.** Observed cross-wallet variance is *smaller* than
   the noise a 30-bet half injects, so there is nothing to rank: reliability is 0.00, not "low".
   Quintiles are not monotone in the right direction — **Q4 (worst-but-one by half A) is the best
   cohort in half B at +4.91pp [+1.81, +9.13]**, Q1 is +1.22pp. A ranker built on this would
   pick the fourth quintile.
2. **The ranker we actually run has no information.** `globalScore` reads ρ = −0.006 (p 0.93) on
   158 wallets. The 2026-10-31 §WB.3 read (ρ +0.20, p 0.67, 24 wallets) was underpowered and is
   superseded by this one; the larger sample moved it to zero, not up.
3. **Even the good case is $1.92/day.** The top-25 by measured edge trade **18.8 bets/day** of
   their own flow; at +1.02pp and a $10 clip that is **+$0.10/bet, +$1.92/day**, against a
   $500/day rung — and that edge is the one the same test cannot separate from zero (p = 0.39).

### WB.7: the market-feature alternative measures zero too

If wallet identity does not rank edge, the only remaining candidate for a non-copy mechanism is
the market's own features. TTL at entry is the one a rule can act on, and it had only ever been
measured on **our own book — which is selected by the rules under test**. §WB.7 prices it on the
out-of-gate panel: 4,223 settled bets with a usable scheduled end (51.4% of 8,215; the coverage
hole is real and is #2 below).

| TTL at entry | n | mean px | hit | edge | edge CI (95%) | ROI | ex-top-10 ROI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <6h | 764 | 0.489 | 48.7% | −0.24pp | [−3.2, +2.5] | +5.4% | −9.6% |
| 6–24h | 975 | 0.525 | 53.7% | +1.24pp | [−1.3, +3.8] | +5.0% | −4.6% |
| 1–3d | 549 | 0.532 | 55.7% | +2.50pp | [−0.4, +5.3] | +2.2% | −13.0% |
| 3–7d | 968 | 0.485 | 49.8% | +1.29pp | [−1.2, +4.0] | −2.7% | −11.9% |
| 7–30d | 699 | 0.487 | 49.4% | +0.61pp | [−2.6, +3.7] | +5.3% | −8.6% |
| ≥30d | 268 | 0.527 | 53.7% | +1.05pp | [−3.0, +4.9] | +25.8% | −23.6% |

Pool edge **+1.03pp [−0.2, +2.2]**. **No bucket has an edge CI excluding zero**, and the
band×TTL grid (§WB.7) has no cell at n≥100 that clears. Scope limit stated plainly: our book's
`3–7d` cell reads **+52.1% [+22.9, +65.5]** on 2,140 legs, and this out-of-gate arm reads
**+1.29pp / −2.7% ROI** for the same maturity. The difference is that ours includes exits and the
gate's own selection; on an exit-free, hold-to-settlement basis in a population no rule chose,
the maturity axis carries no edge either.

**So both selection axes — which wallet, and when in a market's life — measure to zero on ~11,700
out-of-gate settled bets.** That is the finding, and it is the reason this brief does not propose
a threshold.

---

## Where the money actually goes, measured fresh (§T, §U, §W)

12,411 finished real legs, $135,093 at risk, +$15,374 = +11.4%, **+12.09 $/1k-capital-day**.

| lane / band | legs | notional | ROI | $/1k-cd | share of capital-days | ex-top-10 ROI |
| --- | --- | --- | --- | --- | --- | --- |
| STANDARD <0.20 | 523 | $6,105 | **+84.3%** | **+60.87** [CI +8.5, +131.9] | 6.9% | +55.4% |
| STANDARD 0.2–0.4 | 1,276 | $15,412 | +4.3% | +5.65 [−19.6, +59.3] | 9.6% | +1.2% |
| STANDARD 0.4–0.6 | 3,681 | $46,368 | +6.6% | +23.99 [−71.3, +93.5] | 10.4% | +6.1% |
| STANDARD 0.6–0.8 | 1,680 | $20,008 | +4.2% | +4.03 [−4.6, +15.6] | 17.0% | +3.6% |
| STANDARD 0.8–1.0 | 2,685 | $25,435 | **−3.5%** | **−1.28** [−3.7, +0.4] | **56.1%** | −3.7% |
| C-200 <0.20 | 276 | $8,493 | +75.7% | +345.08 | 42.1% | **−6.4%** |
| C-200 0.4–0.6 | 1,054 | $4,356 | **−7.3%** | −44.91 | 16.1% | −10.3% |
| all lanes | 12,411 | $135,093 | +11.4% | +12.09 | 100% | +6.3% |

The allocation is still inverted against the measurement: **56.1% of STANDARD's capital-time sits
in the one cell that returns less than zero per capital-day** (−1.28 $/1k-cd, ex-top-10 −3.7%),
while the cheapest band returns +60.87 on 6.9%. This is not new — it is the input to the
**2026-10-27 band-factor shadow proposal, which is still unapproved**, and I am not stacking a
second proposal on top of it. Today's numbers are that card's current evidence.

Open book (§U, time-integrated, mark basis): **445 STANDARD legs, $4,856 at risk, 423,151
capital-days at +0.36 $/1k-cd unrealised, median age 92d** = 25.6% of the lane's capital-time.
`standardStaleExitHours` is **0** in the active v70 ruleset, so that rail is inert by parameter,
not by scope — the 2026-10-24 v66 sweep (701 legs closed, −$350.52) already took the ≥0.60 stock.

---

## #1 — Record the null and freeze both selection axes for 30 days. Lane A, propose only.

**Hypothesis.** The copy mechanism has no selection axis with measurable edge: neither wallet
identity nor entry TTL separates outcomes in a population no rule selected, so any future
admission/sizing/band/wallet change built on this signal cannot be distinguished from noise.

**Measurement.** §WB.6 (`scripts/profit-wallet-breadth.py --only-wb6`): ρ = +0.058, p = 0.482,
reliability 0.00, top-25 → +1.02pp [−2.76, +5.09] at p(selection) = 0.385, globalScore ρ = −0.006
(p 0.93), on 158 wallets / 7,529 settled bets. §WB.7: no TTL bucket clears its edge CI on 4,223
out-of-gate bets.

**Decision rule.** Freeze wallet- and maturity-based **selection** changes for 30 days (sizing
changes already in flight are unaffected: the 10-27 band-factor shadow and the v54 band factors
stay live). Reopen only on a read that clears the bar below.

**Refutation.** Reopen if either fires: (a) the same split-half on a **90-day** window with
**≥300 wallets** reads **ρ ≥ +0.30 with permutation p < 0.05**; or (b) a TTL bucket at **n ≥ 500**
reads **edge CI lower bound > +1.0pp**. Both are one re-run of the committed script.

**Expected effect.** **$0 of PnL directly** — it is #1 because it stops the next month of work
being spent re-deriving an axis that has now measured zero twice, and it is the pre-committed
consequence of the 10-31 rule ("below that, no wallet-based change is admissible for 30 days").
**Cost: 0.5h** (close the card, write the refutation clause into it).

---

## #2 — Close the TTL coverage hole before anyone closes the TTL axis. Lane B, propose.

**Hypothesis.** The half of settled bets with no usable scheduled end (48.6%) are why no TTL cell
clears its interval; at ≥90% coverage the `1–3d` (+2.50pp) and `6–24h` (+1.24pp) cells either
clear zero or collapse to it, and the answer becomes decidable instead of "unresolved".

**Measurement.** §WB.7 takes `end_date_iso` from the archived CLOB record. Fallback order to
implement: gamma `endDate` for the same conditionId, then `MarketSnapshot.timeToResolution` at
the bet hour. Re-read `python3 scripts/profit-wallet-breadth.py --only-wb6 --offline`; the
coverage line and every CI print.

**Decision rule.** If coverage reaches **≥90%** and any TTL bucket at **n ≥ 500** has an edge CI
lower bound **> +1.0pp**, bring a TTL-based sizing change (Lane A) at that point. Otherwise the
axis is dead and this card closes against it.

**Refutation.** Coverage ≥90% **and** every bucket CI spans zero **and** band×TTL shows no
monotone gradient → the hypothesis is wrong, the TTL axis closes for good, and #1's freeze
becomes permanent for maturity rather than 30 days.

**Expected effect.** $0 direct, and it is the only measurement left that could unlock a rule:
the best out-of-gate cell is worth **+$0.13/bet** at a $10 clip today, so the decision it gates
is whether the lane gets its capital-time back from the 0.8–1.0 tail. **Cost: 1h** (no wire; the
truth is archived).

---

## #3 — The instrument, and the defect that made this panel unaffordable. Lane B, done.

`scripts/profit-wallet-breadth.py` (§WB.6, §WB.7 new this commit; no RuleSet touched, read-only DB):

1. **The truth fetch was ~5× slower than the network allows, and my own first fix oversold
   itself.** `_fetch_one` called `os.system("curl …")` inside a 24-thread pool, which serialises
   on the GIL at fork/exec: **3.3 fetches/s** measured on the 2026-10-31 panel, i.e. an hour for a
   12k-bet panel. The same request through `urllib` with a User-Agent header (the CLOB answers
   **403** without one — the reason the code shelled out at all) sustained **17 fetches/s** on
   this panel: **5.5 min instead of 57 min**. A micro-benchmark of the same URL repeated hits
   79.5/s, but that is a warm-cache ceiling, not a sustained rate, and quoting it as the
   speed-up would be exactly the kind of better number this section is supposed to stop.
2. **A rate-limited response is no longer recorded as an unsettled market.** The archive is
   written only after the body parses; a 403/429 is a retry with backoff, not a fabricated
   "unsettled" that silently shrinks coverage.
3. **Sampling is one pass, not 400 round trips.** A per-wallet query costs ~2.2s on a whale
   (27k prints); 200 wallets × 2 halves was 400 queries for a 60-bet sample. Reservoir sampling
   over a single indexed pass: 10s, uniform per wallet-half, memory O(wallets × 60).
4. **Bulk-walk characterised, kept opt-in.** `/markets?next_cursor=` returns 1,000 markets in
   ~0.4s (2,000 markets/s), and the id space is **sparse and ~6.45M wide** (probed: `id:6,300,000`
   returns live 2026-11 markets, `id:6,600,000` returns none). A full walk is 6k+ pages, so
   per-cid at 79/s wins for panels under ~100k bets; `--bulk` exists for larger ones.

Two hypotheses also died on measurement rather than argument, which is the cheapest kind of
prevention: **wallet-edge persistence** (§WB.6, above) and **TTL-as-edge out of gate** (§WB.7).

---

## Contradictions I am not resolving silently

- **The 10-31 breadth arithmetic was right about the conclusion and wrong about the reason.**
  It said "×40 → 685 bets/day, 91× short of a rung", closing the supply question. Today's panel
  shows 200 active wallets alone print **5,827 distinct bets/day** (whale-dominated). Supply was
  never the binding constraint — but the flow that carries the best measured edge is **18.8
  bets/day**. The ladder is edge-limited, not flow-limited. Same verdict, sharper reason.
- **§Y: "the 0.40–0.60 band is dead" depends on the basis, and the bases disagree.** All-time,
  first-fill (the basis v63 used) is **−6.17%** while repeat fills are **+13.28%** and all legs are
  **+6.63%**; on 90d every basis is negative (first fill −5.74%, adds −17.44%, all legs −11.15%).
  The live skip is consistent with 90d and inconsistent with all-time. Reported; not re-litigated.
- **The open book shrank, so no "stranded capital" alarm should be re-raised.** Today: 445 legs /
  423,151 capital-days. The 10-20 brief's 1,269 legs / 1,033,886 capital-days is superseded by the
  v66 sweep, and `standardStaleExitHours` is 0 in v70 — the rail is inert by parameter. Both
  figures are time-integrated and neither is comparable to a leg count.
- **globalScore's rank read moved from +0.20 (p 0.67, n=24) to −0.006 (p 0.93, n=158).** The
  smaller read was underpowered; this one supersedes it, in the direction of no information.
- **C-200 ex-top-10 is negative on 2,566 legs** (1× +$6,526 → −$388 ex-top-10, −1.9%) while the
  lane reads +75.7% ROI in <0.20. I am **not** proposing a clip cut: the 10-18 one-leg day was
  refuted as a clamping problem (capping at $18 would have cut $568 → $152) and a size cut on a
  tail-carried lane needs its own pre-registered trial. Flagged, not proposed.

---

**IF YOU WEREN'T HERE:** I would record the null on the ladder card today and stop proposing
threshold changes to the copy mechanism. Two selection axes now measure zero on ~11,700
out-of-gate settled bets, the ranker we run has ρ = −0.006, the best 25 wallets by measured edge
trade 19 bets/day and would earn **$1.92/day**, and the lane's biggest capital-time allocation
(56.1%) sits in the only negative cell. Every threshold left on this board is a rearrangement of
noise. Close the axis, close the TTL coverage hole, and make the next proposal earn its place
against a population that our own gate did not choose.

---

### Provenance

| figure | source |
| --- | --- |
| wallet persistence, quintiles, top-k, globalScore, flow, dollars | §WB.6, `scripts/profit-wallet-breadth.py --only-wb6` |
| TTL at entry out of gate, band×TTL | §WB.7, same script |
| truth coverage 5,602/5,661, 7,179 markets | §WB.6 run, `data/.clob-truth-raw` |
| band ROIs, $/capital-day, CIs, ex-top-10, capital-day audit, open book | `scripts/profit-velocity.py` §T/§U (2026-11-01 07:44 CDT run) |
| ex-top-10 lane scaling, 0.8–1.0 capital-time share | same, §W |
| dedupe-basis audit for 0.40–0.60 | same, §Y |
| TTL in our own book (3–7d +52.1%) | same, §Z |
| active ruleset v70 fields (`standardStaleExitHours`=0, `standardMaxEntryPrice`=0.85) | `RuleSet` row, read-only |

*Lane B applied directly this commit: `scripts/profit-wallet-breadth.py` (§WB.6, §WB.7, the
fetch-reliability fix, reservoir sampling, opt-in bulk walk) and this file. Read-only DB
throughout. **No RuleSet row touched, no rule edited, no `prisma/dev.db` write.***
