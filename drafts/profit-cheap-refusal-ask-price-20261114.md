# The 189 were never unpriced — they were refused by a gate that already measured the spread

**Card:** `t_eafa7261` · approvals `apr-profit-cheap-refusal-ask-price` · LANE A — **PROPOSAL ONLY, nothing applied**
**Instrument:** `scripts/profit-cheap-ask.py` (new, committed with this draft; `--self-test` 15/15, one negative control)
**Reproduce:** `python3 scripts/profit-cheap-ask.py` (cache-only, read-only) — raw run appended at the end
**Read at:** 2026-11-14 10:50 CST · DB opened `mode=ro`
**Cost basis:** every ROI line is a return on **dollars at risk** (one leg = one unit); hits pay `(1−entry)/entry`, losses `−1`.

---

## The one-paragraph version

The measurement clears its bar: all 189 candidates resolve to a real quoted ask, and at that ask they still earn **+12.6pp over breakeven / +124.6% eqw ROI** — six times the +20% the decision rule required. But **the action the rule authorised is void**: the spread check is already the *second* gate in the hard-skip list, ahead of drift, TTR and confidence, and it **did not fire on any of the 189 — it passed**. A passing gate writes nothing, which is why the row carries no spread string; the value is on the row anyway in `DecisionJournal.spreadScore`, which inverts to the spread **exactly** (validated 48/48, 0.00 mc error). So the 189 were never unpriceable. Their spread gate had already cleared them at a **median 2.0c**, and the ask sits **+1.0c** above the detection mid. Re-ordering `trade.ts` would move no threshold, admit no candidate, and record nothing new. **I am withdrawing the re-order and proposing nothing on the live lane today** — except one admission question the measurement surfaced that is not about fills at all: the cheap candidates refused *only* for resolving inside 2 hours.

---

## 1. The claim that failed

`profit-recs-20261114` §3 said the scorer "refuses 79% of cheap-tail refusals **before it ever measures the spread**, because drift and confidence are checked first in `trade.ts`." Both halves of that are wrong, and the correction is cheap to check:

`src/lib/scoring/trade.ts:108-134,196` builds `hardSkips` in this order, **evaluating every test unconditionally** on every candidate:

| # | gate | line |
|---|---|---|
| 1 | wallet score | 109 |
| **2** | **spread > maxSpread** | **111** |
| 3 | liquidity | 113 |
| 4 | adverse drift | 120 |
| 5 | TTR | 124 |
| 6 | near-certainty price | 126 |
| 7 | OBI | 132 |
| 8 | confidence floor | 196 |

And the scorer's own input default is `spread = input.spread ?? 0.1` against `maxSpread = 0.06` — so an **unknown** spread fires the gate and writes `spread 0.100 > max 0.06`. There are only three outcomes, and the data confirms which one happened:

- **0** of the 238 rows with no spread blocker mention a spread anywhere → the value was known.
- the spread blocker is present on **148** rows, every one of them as `spread <value> > max 0.06` (`scripts/profit-cheap-funnel.py --resolve`, reproduced).
- therefore the passing arm is exactly the set of rows where `spread ≤ 0.06` **and the gate ran and passed**.

The code probe (`probe_order.ts`, output in the appendix) settles the ordering with the live RuleSet v73 values, not by reading:

```
spread 20c FAILS + drift 5c FAILS   -> risks = ["spread 0.200 > max 0.06", "price drifted ... (too late)"]
   spread=0  drift=1  ttr=-1  confidence=-1  wallet=-1
spread 20c FAILS + TTR 1h FAILS + confidence FAILS
                                    -> spread=1  ttr=2  confidence=3  wallet=0
spread 2c PASSES + drift 5c FAILS   -> risks = ["price drifted ..."]      (no spread entry at all)
```

**"Refused before the spread is read" does not hold. The spread is read on every candidate, second, and on these rows it passed.**

## 2. The value was on the row all along — `spreadScore` inverts exactly

`DecisionJournal.spreadScore` is written on **every** scored row (`scripts/score-trades.ts:658`) and `trade.ts:166` makes it a deterministic function of the spread, so it is invertible:

```
spreadScore = clamp(100 − (spread / maxSpread) × 70)      trade.ts:166
spread      = (100 − spreadScore) × maxSpread / 70        (maxSpread = 0.06)
```

| validation | n | result |
|---|---|---|
| rows that name a spread **and** sit inside the clamp (≤8.6c) | 48 | **exact within 0.06c on 48/48**, median error 0.00 mc |
| rows whose recorded spread is beyond the clamp (score pinned at 0) | 100 | read as "at least 8.6c", median recorded 11.0c — not a value |
| passing arm with no `spreadScore` at all | 0 of 238 | — |
| **decoded spread on the passing arm** | 238 | **median 2.0c, p90 5.0c, max 6.0c** |

Two independent readings of the same fill now agree:

- from the snapshot: **ask − detection mid = +1.0c** (median), p90 +2.5c
- from the row: **half the decoded spread = +1.0c** — and priced this way the cohort returns **+124.3%**, against **+124.6%** from the snapshot ask.

That 0.3pp agreement is the strongest thing in this brief. It means the instrument defect the review found is a **reader** defect, not a recorder defect: the funnel script's `spread_of()` only looks in `risksJson`, where a passing gate leaves nothing.

## 3. The measurement: what the 189 cost at the ask

189 of 238 rows resolve from the venue archive (79%); **an ask is recoverable for 189 of 189 (100%)** from `MarketSnapshot`, written by the monitor in the same sweep as the detection — quote age **median 10s**, p90 14s, and the snapshot mid equals `detectedPrice` to **0.00c** on every row. Token identity is decided by comparing the detection price to the snapshot's two token mids (never by the outcome label, which is worthless on the 34% named-outcome markets); **0 ambiguous rows**, and on YES/NO labels the price-based identity agrees 99/99.

| arm | n | hit% | be% | edge | eqw ROI | 95% CI |
|---|---|---|---|---|---|---|
| A detection mid (the review's number) | 189 | 25.4 | 11.5 | +13.9 | **+150.6%** | [+84.1,+221.9] |
| B snapshot mid (same instant) | 189 | 25.4 | 11.5 | +13.9 | +150.6% | [+84.1,+221.9] |
| **C ASK at detection — the answer** | **189** | **25.4** | **12.8** | **+12.6** | **+124.6%** | **[+66.7,+187.8]** |
| D ask + taker fee (`rate·p·(1−p)`, rate by category) | 189 | 25.4 | 13.3 | +12.1 | +115.1% | [+59.7,+175.6] |
| E mid + maxSpread (worst fill the passed gate permits) | 189 | 25.4 | 17.5 | +7.9 | +50.8% | [+13.0,+90.6] |
| G mid + decoded `spreadScore` (independent of the snapshot) | 189 | 25.4 | 14.1 | +11.3 | +104.8% | [+52.3,+163.2] |
| H mid + half decoded spread | 189 | 25.4 | 12.8 | +12.6 | +124.3% | [+66.4,+187.2] |
| F ask at the next observed sweep | 66 | 13.6 | 12.4 | +1.2 | +0.4% | [−64.6,+74.9] |

Arm F is printed for completeness and **is not an execution-lag estimate**: `MarketSnapshot` is event-driven (a wallet trade in that market), so "the next snapshot" is whatever sweep came next, and it exists for only 66 of 189 rows. The lag question it was meant to answer is answered better by the join itself: the scorer journals **10s** after the monitor's quote.

**Positive control (the arm whose spread gate fired):** the 148 spread-blocked candidates, priced the same way, return **−6.0%** at the ask (n=118, hit 19.5% = its own breakeven). The instrument reads one arm positive and the other negative on the same join — it is measuring fills, not noise.

**Robustness of the +124.6%:**

| cut | n | hit% | ROI at ask |
|---|---|---|---|
| full arm | 189 | 25.4 | +124.6% |
| ex-top-5 | 184 | 23.4 | +88.0% [+34,+145] |
| ex-top-10 | 179 | 21.2 | +56.4% [+9,+105] |
| **ex-top-20** | **169** | **16.6** | **+3.2% [−31,+39]** |
| 5–10c entries | 66 | 22.7 | +203.3% |
| 10–15c entries | 57 | 22.8 | +93.7% |
| 15–20c entries | 57 | 28.1 | +64.7% |

State it plainly: **the edge is carried by roughly twenty legs.** Beyond the top 20 it is a coin flip (+3.2%, CI across zero). The hit rate beats breakeven in every price band and by a similar margin (edge +14.6 / +10.6 / +10.5pp), which is the reassuring half — this is not one band — but the dollar return is tail-driven, and payoff shape is 48 wins / 141 losses at mean win **+784%**, mean loss **−100%**. At full size it compounds to ruin; at 5% of bankroll per leg the geometric return is +4.48%/leg, at 2% it is +2.17%. **This is a fractional-stake instrument and its value depends on the size discipline that sits around it**, not on the entry price alone.

## 4. What the measurement actually licenses

At the ask, split by the gate that fired first:

| first blocker | n | hit% | ROI at ask |
|---|---|---|---|
| liquidity < $750 | 76 | 11.8 | **−6.9%** |
| **resolves in <2h** | **58** | **39.7** | **+270.9%** |
| adverse drift | 22 | 13.6 | +34.5% |
| confidence floor | 7 | 14.3 | −0.8% |
| category blacklist (`lol` 7 / `cs2` 4 / `nfl` 3) | 14 | — | +214% to +900% (n=3–7, unreadable) |
| near-certainty | 3 | — | noise |

The liquidity gate is **doing its job** (−6.9%), which is the second thing the review got backwards: it treated the cheap tail as one population; split by gate, half of it is correctly refused and the other half is the best cell in the book.

Sole blockers are the ceiling on any single-gate change (82 rows). But a sole blocker is not an admission — the score floor fires next, and it kills most of the ceiling:

| sole blocker | rows | stored `copyScore ≥ 70` | reachable ROI at ask |
|---|---|---|---|
| resolves in <2h | 34 | **34** | +455.0% |
| confidence floor | 7 | 2 | +247.2% |
| liquidity < $750 | 18 | **1** | −100% |
| near-certainty price | 2 | 1 | +1566.7% (one leg) |
| **total reachable** | **38 of 61** | | |

The confidence-only rows are the cleanest example of the trap: `longshotMinConfidence 0.55` ≡ `copyScore 70.75`, while `longshotMinCopyScore` is 70 — the two gates differ by **0.75 score points**, so relaxing the confidence floor admits a sliver and nothing else. The liquidity-only rows: 18 sole-blocked, **1** clears the score floor.

**The one population worth a decision** — cheap candidates whose only refusal is "resolves in <2h", score ≥ 70:

| cut | n | hit% | ROI at ask |
|---|---|---|---|
| all | 34 | 58.8 | +455.0% CI [+271,+633] |
| ex-top-3 | 31 | 54.8 | +362.8% |
| ex-top-5 | 29 | 51.7 | +307.1% |
| ex-top-10 | 24 | 41.7 | +169.7% |
| TTR ≥ 10 min | 23 | 65.2 | +568.4% |
| TTR ≥ 15 min | 18 | 66.7 | +603.3% |
| TTR ≥ 30 min | 17 | 70.6 | +644.6% |

(34 legs across 33 markets over the 18.1-day live regime window = **~1.9 reachable legs/day**.)

Median TTR at decision **0.40h**; median ask paid **10.5c**; families `nba 8, epl 4, nfl 3, mls 3, cfb 2, ucl 2` — live in-game sports markets. The edge *strengthens* as the race window widens, which is the opposite of what a "we can't fill before settlement" artifact would look like. Flow, from the independent long-shot shadow ladder (9,797 candidates / 63 days): cheap candidates with TTR<2h arrive at **7.5/day** (9.2% of cheap flow), median spread **1.0c**, `copyScore ≥ 70` on 242 of 473.

## 5. Verdict on the pre-registered decision rule

> *"If ≥120 of the 189 resolve to an ask and their ask-adjusted mean ROI is ≥ +20%, propose exactly one change: move the spread check ahead of drift/confidence."*

**Measurement bar: PASS** — 189/189 priced (bar: 120), **+124.6%** (bar: +20%), +115.1% after fees, +50.8% at the worst fill the gate that passed permits.
**Named action: REFUTED — already implemented.** The spread check is hard-skip #2; re-ordering it ahead of drift and confidence changes the array from `[spread, drift, confidence]` to `[spread, drift, confidence]`.
**Refutation clause as written** ("asked-adjusted ROI < +5% → I withdraw") did not trigger; the *action* clause is withdrawn because the code it proposed to change does not have the defect the proposal assumed.
**Nothing applied. No threshold moved, no `apply-vNN` run, no prisma write, no merge.**

## 6. Flags — one line each, with the number that moves and the revert

These are yours to override; nothing below has been executed.

- **F1 — WITHDRAW the re-order (recommended, default).** `trade.ts` already tests spread at position 2 of 8. Moving it changes 0 of 23,590 candidate outcomes. Revert: none needed, nothing changed.
- **F2 — `minTimeToResolutionHours` for the long-shot band: keep 2h / exempt when TTR ≥ 15 min / exempt the band entirely.** Exempting at ≥15 min would have admitted **18 legs** in the live regime at **+603%** counterfactual ROI at the ask (ex-top-5 +307%); flow would be ~**2 legs/day**. Revert: one RuleSet field (`minTimeToResolutionHours` → `longshotMinTtrHours`, default = legacy 2h, so an unpatched ruleset behaves identically).
- **F3 — FIX THE READER, not the scorer.** `scripts/profit-cheap-funnel.py:spread_of()` should decode `spreadScore` (exactly as §2) instead of regexing `risksJson`; every row then carries a spread and the "UNPRICED" label disappears (the 131/189 gate split stays, both arms become priced). That **changes a published figure**, so it is Lane A by the standing rule and is **not** applied here. Revert: one function body.
- **F4 — the category blacklist (`lol`, `cs2`, `nfl`) is not readable at this sample** (n=3–7 per family). No action; it needs its own card with ≥30 resolved legs per family before anyone touches a v45 blacklist.
- **F5 — size, not entry, is the lever on the main arm**: 20 legs carry the return and the geometric read only survives at fractional stake. Any change that adds clip to the cheap band without a tail limit is the wrong direction; this is unchanged from the review's own "no clip change" call.

## 7. What I am NOT proposing, and why

- **No gate relaxation for the liquidity blocker.** 76 rows at −6.9% at the ask, and 17 of its 18 sole-blocked rows fail the score floor anyway.
- **No confidence-floor change.** It is redundant with the score floor inside 0.75 points.
- **No "record the spread" schema change.** It is already recorded; only the reader was blind.
- **No re-litigation of the 0.4–0.6 / 0.8–1.0 shutdowns, no clip change, no drift change.**
- **No claim that these legs would have filled.** Arm C is a taker fill at the quoted ask. The live lane rests a maker bid under the mid; on a 1c-spread live sports market that is a real conversion risk, unmeasured here. Any admission change must be priced again through the fill instrument, not through this counterfactual.

## 8. Contradictions and open items

1. **The cohort grows with the DB.** 386 deduped rows at 10:50 vs the review's 385 at 07:51; 189 resolved both times. Rates reproduce; counts are read-time dependent.
2. **49 of 238 rows are unresolved** (20% — the archive has no winner, mostly live markets). The review's pessimistic bound (unresolved as losses) put the mid arm at +7.2pp; the same bound on the ask arm is not computed here because the 49 are *unresolved*, not *lost*, and only 1 of them is uncached.
3. **`walletEntryPrice` still disagrees with `detectedPrice`** on this cohort by ~7.6c (see the review §"Contradictions 2"). Untouched by this card; every number above prices at the market, never at the wallet's fill.
4. **A `--fetch` run is needed** to fill the single uncached resolution; it does not move any figure above (1 row of 238).

---

## Provenance

- **Lane A: nothing applied.** No RuleSet row read or written, no `apply-v*.ts`, no prisma write, no gate/threshold/size/booking change, no merge to main.
- **One new read-only instrument:** `scripts/profit-cheap-ask.py` — 15/15 self-tests including two negative controls (a synthetic cohort whose ask arm must come in *below* its mid arm; a spread string that must not leak into the passing arm) and a frame test that flips identity on a named market.
- **DB opened `mode=ro`.** The only writes are the venue-archive cache under `data/cheap-funnel-cache/` (gitignored, refetchable keyless), reused from the funnel instrument so both reads score the same population.
- Revert: `git revert <this commit>` — the instrument and the draft are the whole change.

## Appendix — probe output (code order, decided by running it)

```
spread 2c PASSES + adverse drift 5c FAILS  (the 189's shape)
    entry=0.13 now=0.18 drift=0.050 tolerance=0.0144 spread=0.02 ttr=72
    risks = ["price drifted 0.050 against us since entry > max 0.0144 (too late)"]
spread 20c FAILS + adverse drift 5c FAILS
    risks = ["spread 0.200 > max 0.06","price drifted 0.050 ... (too late)"]
spread 20c FAILS + TTR 1h FAILS + confidence FAILS
    risks = ["wallet score 20 < min 40","spread 0.200 > max 0.06",
             "resolves in 1.0h < min 2h","confidence 0.21 < min 0.55 (long-shot floor)"]
order: spread=1 ttr=2 confidence=3 wallet=0
```

---

## Appendix B — the raw run (2026-11-14 10:50 CST, read-only)

```
============================================================================================
0. THE COHORT, AND THE CLAIM THAT IT IS REFUSED BEFORE THE SPREAD IS READ
============================================================================================

  23590 candidates in the live regime -> 386 refused cheap candidates (deduped to the first sighting per market+outcome)
  spread blocker PRESENT on 148 rows | ABSENT on 238 rows

  trade.ts builds the hard-skip list in this order:
    1 wallet score   2 SPREAD   3 liquidity   4 drift   5 TTR   6 near-certainty   7 OBI   8 confidence
  every test runs unconditionally on every candidate, and the scorer's own input
  default is `spread = input.spread ?? 0.1` against maxSpread = 0.06. So:
    - spread MISSING  -> blocker 'spread 0.100 > max 0.06' is written
    - spread > 0.06   -> blocker 'spread <value> > max 0.06' is written
    - spread <= 0.06  -> the gate PASSES and writes nothing

  rows with no spread blocker that mention a spread at all: 0 -> the spread check RAN and PASSED on 238 rows
  => 'refused before the spread is read' does not hold. What is missing is the
     VALUE (a passing gate records nothing), not the test.

  what actually refused them (full blocker SET, first blocker shown):
      82   34.5%  liquidity # < min #
      66   27.7%  resolves in #h < min #h
      37   15.5%  price drifted # against us since entry > max #
      26   10.9%  confidence # < min #
       8    3.4%  STANDARD: v# blacklist category "lol"
       7    2.9%  short-ttr lane
       4    1.7%  STANDARD: v# blacklist category "cs#"
       3    1.3%  STANDARD: v# blacklist category "nfl"
       2    0.8%  price # near certainty
       1    0.4%  Price already near certainty

  co-blocking: how many hard skips fired together
    1 blocker(s): 82
    2 blocker(s): 77
    3 blocker(s): 60
    4 blocker(s): 17
    5 blocker(s): 2

  SOLE blockers (82 rows -- the ceiling on removing any one gate):
      36  resolves in #h < min #h
      26  confidence # < min #
      18  liquidity # < min #
       2  price # near certainty
  rows that never reached the scorer (pre-scorer journal paths): 0

============================================================================================
1. THE SPREAD IS ALREADY ON THE ROW -- spreadScore inverts it exactly
============================================================================================
  DecisionJournal.spreadScore is written on every scored row (score-trades.ts:658).
  trade.ts:166 makes it an exact function of the spread, so a spread-blocked row
  can validate the inversion and an unblocked row can be priced by it:
     spreadScore = clamp(100 - (spread / maxSpread) * 70)
     spread      = (100 - spreadScore) * maxSpread / 70

  validation on the 148 rows that name a spread explicitly:
    48 sit inside the clamp range (<=8.6c): exact within 0.06c on 48 (100%), median |delta| 0.00 mc, max 0.0 mc
    100 sit beyond it (score pinned at 0, median recorded 11.0c) -- those rows are 'at least 8.6c wide', not a value
    over all 148: median |delta| 14.29 mc (the clamp cases carry the error)

  rows in the passing arm with no spreadScore at all: 0 of 238
  decoded spread on the passing arm: median 2.00c, p90 5.00c, max 6.00c
  (maxSpread is 6c, so every row here is inside the gate)

============================================================================================
2. THE ASK -- joining each row to the quote that stood beside it
============================================================================================
  window +/-2h around DecisionJournal.createdAt, same marketId;
  identity decided by price comparison against the snapshot's two token mids.

  resolution: 237 from cache, 1 uncached (run --fetch to fill)
  resolved from the venue archive: 189 of 238 (79%)
  an ask is recoverable at-or-before the journal row : 189 (100% of resolved)
  an ask is recoverable at-or-after  the journal row : 66 (35%)
  identity AMBIGUOUS (both tokens within 1c of the detection price): 0  <- excluded from the ask arm, kept in the mid arm
  quote age at the journal row: median 10s, p90 14s, max 26s (the monitor writes the snapshot, the scorer journals seconds later)
  snapshots later than the journal row exist for 66 rows: MarketSnapshot is
  EVENT-driven (a wallet trade in that market), not a quote series, so arm F is a
  selection-biased look at whatever sweep came next -- printed for completeness, not
  as an execution-lag estimate.
  snapshot mid vs detection price: median 0 (1e-5 c), max 0.00c -- the join lands on the quote the detection price was read from
  frame check: on YES/NO labels the price-based identity agrees 99x, disagrees 0x (named outcomes excluded -- the label test cannot see them)

============================================================================================
3. THE ARMS -- same hits, different entries. ROI on dollars at risk, market-clustered CI
============================================================================================

  arm                                   n   hit%    be% edge_pp     ROI%  95% CI
  A detection mid (review)            189   25.4   11.5   +13.9   +150.6 [  +84.1, +221.9]
  B snapshot mid                      189   25.4   11.5   +13.9   +150.6 [  +84.1, +221.9]
  C ASK at detection  <-- answer      189   25.4   12.8   +12.6   +124.6 [  +66.7, +187.8]
  D ask + taker fee                   189   25.4   13.3   +12.1   +115.1 [  +59.7, +175.6]
  E mid + maxSpread (gate bound)      189   25.4   17.5    +7.9    +50.8 [  +13.0,  +90.6]
  G mid + decoded spreadScore         189   25.4   14.1   +11.3   +104.8 [  +52.3, +163.2]
  H mid + half decoded spread         189   25.4   12.8   +12.6   +124.3 [  +66.4, +187.2]
  F ask, next snapshot after           66   13.6   12.4    +1.2     +0.4 [  -64.6,  +74.9]

  ask minus detection mid: median +1.0c, mean +1.3c, p90 +2.5c, max +4.2c
  breakeven entry at the cohort's 25.4% hit rate: 25.4c -- the fill can be +13.9c worse than the detection mid before the edge is gone

============================================================================================
4. ROBUSTNESS OF THE ASK ARM -- is the return a book or three legs?
============================================================================================
  ex-top-5   n= 184 hit  23.4% ROI    +88.0% CI [+34,+145]
  ex-top-10  n= 179 hit  21.2% ROI    +56.4% CI [+9,+105]
  ex-top-20  n= 169 hit  16.6% ROI     +3.2% CI [-31,+39]
  full arm n=189 ROI +124.6%

  by price band at the ask:
    5-10c  n= 66 hit  22.7% be   8.1% edge  +14.6pp ROI   +203.3%
    10-15c  n= 57 hit  22.8% be  12.2% edge  +10.6pp ROI    +93.7%
    15-20c  n= 57 hit  28.1% be  17.6% edge  +10.5pp ROI    +64.7%

  payoff shape: 48 wins / 141 losses (25.4% hit), mean win +784%, mean loss -100%
  breakeven hit rate = the entry paid = 12.8%
  geometric mean at FULL size is -100% (any total loss zeroes the product), so this
  cohort is a FRACTIONAL-stake instrument; at a stated stake per leg it compounds as:
    5% of bankroll per leg -> geometric +4.48% per leg (+847% over 189 legs)
    2% of bankroll per leg -> geometric +2.17% per leg (+410% over 189 legs)

============================================================================================
5. WHICH GATE IS REFUSING THE MONEY (ask arm, split by first blocker)
============================================================================================
  first blocker                                           n   hit%    be%  ROI@ask%
  liquidity # < min #                                    76   11.8   12.9      -6.9
  resolves in #h < min #h                                58   39.7   12.6    +270.9
  price drifted # against us since entry > max #         22   13.6   11.8     +34.5
  short-ttr lane                                          7   14.3   14.9     -20.6
  STANDARD: v# blacklist category "lol"                   7   85.7   15.6    +433.9
  confidence # < min #                                    7   14.3   13.8      -0.8
  STANDARD: v# blacklist category "cs#"                   4   25.0   14.8    +212.5
  STANDARD: v# blacklist category "nfl"                   3  100.0   10.0    +900.0
  price # near certainty                                  2   50.0    6.5    +733.3
  Price already near certainty                            1    0.0    6.0    -100.0
  STANDARD: v# blacklist category "bitcoin"               1    0.0   11.1    -100.0
  STANDARD: v# blacklist category "dota#"                 1    0.0   14.0    -100.0

  SOLE-blocker subset at the ask: n=61 hit 41.0% ROI +287.4% CI [+163,+418] -- the only rows a single-gate change could admit

============================================================================================
6. REACHABILITY -- a sole blocker is a CEILING; the score floor fires next
============================================================================================
  Live RuleSet v73: longshotMinCopyScore 70 (price < 0.20), minCopyScore 80,
  longshotMinConfidence 0.55 (== copyScore 70.75 via confidence=(score-35)/65),
  highScoreCapMin 80 with highScoreMaxDrift 0.004 (the v29 late-entry filter).
  So a row whose only hard skip is gate G is ADMITTED only if its stored copyScore
  clears 70 and it does not trip the late-entry filter on the way through.

  sole blocker                                   n score>=70  reach ROI@ask
  resolves in #h < min #h                       34        34        +455.0%
  liquidity # < min #                           18         1        -100.0%
  confidence # < min #                           7         2        +247.2%
  price # near certainty                         2         1       +1566.7%

  REACHABLE ceiling across all sole-blocked rows at the ask: 38 legs (of 61 sole-blocked, 189 resolved)
  still not evaluated here: the lane's per-market / per-wallet / per-cycle caps,
  the category blacklist, the hour blackout and the dedupe coalesce -- all of which
  fire AFTER the scorer, so the true admitted count is <= this number.

  THE TTR-REACHABLE POPULATION (sole blocker 'resolves in <2h', score >= 70):
    n=34 across 33 markets, hit 58.8% vs breakeven 11.8% = +47.0pp, ROI at ask +455.0% CI [+271,+633]
    ex-top-3  n=31 hit  54.8% ROI   +362.8%
    ex-top-5  n=29 hit  51.7% ROI   +307.1%
    ex-top-10 n=24 hit  41.7% ROI   +169.7%
    these settle within 2h of the decision, so the counterfactual is a pure
    settlement hold: no exit policy, no mark, no stale-exit dependency.
    TTR at decision: median 0.40h, min 0.00h, max 1.40h
    market-slug families: nba 8, epl 4, nfl 3, mls 3, cfb 2, ucl 2
    ask paid: median 10.5c, mean 11.8c, max 20.0c
    TTR >= 0.10h: n=23 hit  65.2% ROI   +568.4%
    TTR >= 0.25h: n=18 hit  66.7% ROI   +603.3%
    TTR >= 0.50h: n=17 hit  70.6% ROI   +644.6%

============================================================================================
7. POSITIVE CONTROL -- the arm whose spread check FIRED, priced the same way
============================================================================================
  If the instrument is honest, the spread-gate arm must read NEGATIVE at the ask
  and the passing arm positive; if both read the same, the join is measuring noise.

  spread-gate arm at the ASK: n=118 hit 19.5% be 19.5% ROI -6.0% CI [-40.9,+33.4]

============================================================================================
8. FLOW -- how often this population appears (independent source: the long-shot shadow ladder)
============================================================================================
  9797 sub-$20c candidates over 63.0 days (2026-09-12 .. 2026-11-14)
  cheap 0.05-0.20: 5134 (81.5/day)
  of those, TTR < 2h: 473 (7.51/day, 9.2% of cheap)
  their spread: median 1.00c, p90 13.00c, max 37.00c
  their copyScore: median 71.7, >=70 on 242 of 473
  families: epl 113, highest 87, lal 33, nfl 31, mlb 29, cfb 25, dota2 23, ucl 22
```
