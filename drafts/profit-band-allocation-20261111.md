# Band allocation under negative f* — what a 0.4–1.0 notional cut would actually reach

**Card:** `profit-band-allocation-negative-fstar` · **Lane B (measurement only)** · 2026-11-11
**Instrument:** `scripts/profit-band-allocation-preflight.py` (branch `wt/profit-band-allocation-negative-fstar`) → `data/profit-band-allocation-20261111.json`

**This card proposes nothing.** No rule, size, gate, booking or threshold was read into a decision
path, and `prisma/dev.db` was opened read-only (`file:…?mode=ro`). Two things below need a **decision
by the operator** and I am explicitly not making them (§7).

---

## 0. Basis (state it or the numbers mean nothing)

| item | value |
|---|---|
| population | finished legs (`closed` \| `resolved`), `isDemo=0`, deduped first leg per `bot\|wallet\|market\|outcome` |
| risk legs | `fillStatus='unfilled' AND realizedPnl=0` excluded (risk nothing) |
| cost | `simulatedPositionSize` = **dollars at risk**, never shares |
| true price | wallet fill for the INVERTED class, booked `entryPrice` otherwise |
| **two PnL arms** | **booked** = stored `realizedPnl`; **repaired** = price-side repair (**PENDING approval**) |
| book | **5,679 legs / $64,150** at risk, 2026-07-15 → 2026-11-11 (card said 5,680 / $64,168 — reproduced to 1 leg, $18) |
| live regime | opened ≥ **2026-10-26** (drift gate went directional): 246 legs / $5,037 |

**The two arms do not agree and the disagreement is one defect class.** Booked +$12,536.50 vs repaired
+$6,901.91 over the whole book; the 115 INVERTED legs carry **$5,598.58 of booked profit** (45% of the
booked total) and are the entire gap. Every 0.4–1.0 PnL figure below therefore has two signs, and the
sign that survives depends on `apr-ledger-price-side-repair` — which is still pending.

Self-checks in §8 of the script all pass (dedupe identity, booked-PnL partition, repricing identity
max error 1.4e-14, band partition 5,679/5,679).

---

## 1. The headline reproduces — but one of the three negative bands is indistinguishable from zero

`f* = (h − p)/(1 − p)`, market-clustered bootstrap CI (2,000 reps). All-time, finished basis:

| band | n | notional | share | ROI(rep) | hit% | avg p | f* | f* CI95 |
|---|---|---|---|---|---|---|---|---|
| 0.0–0.2 | 508 | $11,679 | 18% | +53.3% | 20.5 | 0.113 | **+10.3** | [+5.7, +15.1] |
| 0.2–0.4 | 904 | $10,705 | 17% | +14.7% | 37.6 | 0.312 | **+9.3** | [+4.0, +15.0] |
| 0.4–0.6 | 1,928 | $18,114 | 28% | −5.6% | 46.9 | 0.497 | **−5.6** | [−11.0, −0.2] |
| 0.6–0.8 | 1,167 | $11,726 | 18% | +2.0% | 66.5 | 0.688 | **−7.6** | [**−18.7, +2.3**] |
| 0.8–1.0 | 1,172 | $11,926 | 19% | −1.0% | 84.9 | 0.925 | **−101.3** | [−136.8, −70.2] |

The card's five f* figures reproduce to the decimal. Two corrections travel with them:

1. **0.6–0.8's negative f\* is not established.** CI [−18.7, +2.3] spans zero; ROI +2.0% [−3, +7].
   "Three bands whose record says bet nothing" is, at this sample, **two** bands plus one that reads
   negative but cannot be distinguished from no edge in either direction.
2. **In the live regime the negative set is ONE band, not three.** Regime, finished basis:

   | band | n | notional | share | ROI(rep) | hit% | avg p | f* | f* CI95 |
   |---|---|---|---|---|---|---|---|---|
   | 0.0–0.2 | 47 | $1,968 | 39% | −53.4% | 12.8 | 0.127 | +0.1 | [−11.0, +12.8] |
   | 0.2–0.4 | 90 | $1,149 | 23% | +25.6% | 37.8 | 0.302 | +10.9 | [−4.3, +26.7] |
   | **0.6–0.8** | 80 | $932 | 19% | −11.1% | 58.8 | 0.686 | **−31.3** | [−69.6, +7.6] |
   | 0.8–1.0 | 29 | $987 | 20% | +0.8% | 93.1 | **0.851** | **+53.8** | [−7.5, +100.0] |

   0.4–0.6 does not appear: **zero legs admitted in the regime.** 0.8–1.0 flips positive because its
   average price paid in the regime is **0.851**, not 0.925 — the live entry caps only let the 0.80–0.85
   sliver through. The −101% reading is a population the current ruleset cannot produce (§3).

   The cheap band's regime ROI (−53.4%) with tol +0.1pp is not a contradiction: at p≈0.13 the payoff is
   ≈+6.9x on a win against −1x on a loss, so an arithmetic expectation of zero can realise as −53% on
   47 legs (three weeks, ~6 wins expected) — which is exactly why the hit-rate tolerance, not the ROI,
   is the evidence test in that cell. It also means the cheap band's −$62/day regime figure below is
   tail noise, not a leak you can size against.

---

## 2. The admission funnel — 0.4–1.0 is already almost entirely closed

Live regime, 21,201 scored candidates, banded on `ObservedTrade.detectedPrice` (the price the gates see):

| band | candidates | admitted | admit % | candidates/day |
|---|---|---|---|---|
| 0.0–0.2 | 2,091 | 91 | 4.35% | 127.5 |
| 0.2–0.4 | 3,213 | 162 | 5.04% | 195.9 |
| **0.4–0.6** | **8,656** | **0** | **0.00%** | 527.8 |
| 0.6–0.8 | 2,586 | 89 | 3.44% | 157.7 |
| **0.8–1.0** | **4,655** | **3** | **0.06%** | 283.9 |
| all | 21,201 | 345 | 1.63% | 1,292.8 |

**0.4–1.0 receives 15,897 candidates (75% of all scoring work) and admits 92 of them (0.58%).**
The parent card's "65% of notional" is a statement about *admitted* notional; the opportunity flow in
those bands was already 99.4% rejected before any new cut is considered.

### Blocker-set size (how many distinct gates fired on a declined row)

| band | 1 gate | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| 0.4–0.6 | 1,422 | 3,842 | 2,911 | 217 | 91 |
| 0.6–0.8 | 323 | 777 | 580 | 168 | 38 |
| 0.8–1.0 | 1,220 | 1,685 | 1,075 | 566 | 88 |

82–87% of declined 0.4–0.8 rows carry two or more gates — the card's own "a cut whose candidates are
already blocked by another gate is worth zero" applies hardest to *loosening*, and it is severe.

### Sole blockers (blocker set has exactly one member)

| band | declined | sole | leading sole blockers |
|---|---|---|---|
| 0.4–0.6 | 8,640 | 1,422 (16.5%) | TTR < min 863 · blacklist 338 · hour blackout 124 · **band skip 46** · liquidity 24 · spread 16 |
| 0.6–0.8 | 2,472 | 323 (13.1%) | blacklist 117 · TTR 73 · drift-too-late 46 · confidence 32 · liquidity 23 · kelly no-edge 20 |
| 0.8–1.0 | 4,651 | 1,220 (26.2%) | **near-certainty band skip 972** · liquidity 97 · confidence 68 · high-entry cap 44 · drift 12 · blacklist 10 |

**The 0.4–0.6 band skip is almost entirely redundant**: only **46 of 8,640** declined rows in that band
were blocked by it and nothing else — the band was dying of TTR, blacklist and drift regardless. As a
*cut* it is already in force and cost 46 candidates in 17 days; as a *lever* ("un-skip the band") it
would admit 46 candidates, not 8,656.

Unclassified bucket: 2 rows total (a `token circuit breaker (flash move …)` string not in my gate
table). A two-row OTHER on 21,201 rows means the classifier is not silently mis-bucketing.

---

## 3. What the cut would reach — the reachable slice is a third of the band

The live RuleSet (v71) already contains the cut this card was contemplating:

| knob | value | in force since |
|---|---|---|
| `c200SkipBandRange` / `standardSkipBandRange` | **0.4-0.6** | v62 (2026-10-12, C-200) / v63 (2026-10-20, STANDARD) |
| `c200MaxEntryPrice` / `standardMaxEntryPrice` | **0.80 / 0.85** | v47 (2026-09-03) |
| `c200BandSizeFactor` on 0.6-0.8 | 0.5 | v60 (2026-09-21) |

Finished 0.4–1.0 legs by the ruleset they were **decided** under (not their open date):

| bucket | 0.4–0.6 | 0.6–0.8 | 0.8–1.0 | reachable under v71? |
|---|---|---|---|---|
| rv<47 (no cap) | $13,139 / 1,226 legs | $6,969 / 657 | $10,596 / 1,124 | 0.4–0.6: no. 0.8–1.0: 940 of 1,124 legs priced >0.85 = no |
| rv47–61 | $4,166 / 657 | $3,663 / 401 | $324 / 18 | 0.4–0.6: no |
| rv62 (C-200 skip only) | $810 / 45 | $73 / 18 | $18 / 1 | 0.4–0.6: no |
| **rv63+ (live structure)** | **$0 / 0** | **$1,021 / 91** | **$987 / 29** | **yes** |

Splitting all-time 0.4–1.0 ($41,766 / 4,267 legs / 65% of notional) by reachability under the live
ruleset — in the 0.4–0.6 skip band, or priced above 0.85:

| slice | legs | notional | booked PnL | repaired PnL |
|---|---|---|---|---|
| unreachable under v71 | 2,882 | **$27,228 (65% of the band)** | +$1,454.38 | **−$1,159.44** |
| still reachable | 1,385 | $14,538 | +$3,307.85 | **+$261.98** |

**The loss the card points at lives in the slice the live ruleset already stopped producing.** The
still-reachable part of 0.4–1.0 was, on the repaired arm, *positive* — though +$262 on $14.5k is not a
finding either.

The 0.8–1.0 band is two populations, and the negative f* is not in the reachable one:

| price slice | legs | notional | booked | repaired |
|---|---|---|---|---|
| ≤0.86 (the cap sliver) | 244 | $3,068 | +$2,218.57 | −$36.52 |
| **>0.86 (unreachable)** | **928** | **$8,857** | +$2,513.99 | −$80.32 |

74% of the band's legs and notional sit above 0.85; the 0.98–1.00 bin alone is 385 legs — pre-cap
"buy the favourite at 0.99" copies that no current lane can place. Removing the unreachable slice
leaves a cap sliver that is, on both arms, roughly flat: the −101.3% f* is an artefact of a price
range the ruleset no longer reaches.

### Reach in daily terms (live regime, 17 open days)

| band | legs | legs/day | $ at risk/day | repaired PnL | repaired $/day |
|---|---|---|---|---|---|
| 0.0–0.2 | 47 | 2.76 | $116 | −$1,051.44 | **−$61.85** |
| 0.2–0.4 | 90 | 5.29 | $68 | +$294.12 | +$17.30 |
| 0.4–0.6 | 0 | 0.00 | $0 | — | — |
| 0.6–0.8 | 80 | 4.71 | $55 | −$103.24 | −$6.07 |
| 0.8–1.0 | 29 | 1.71 | $58 | +$8.30 | +$0.49 |
| **0.4–1.0** | **109** | **6.41** | **$113** | **−$94.94** | **−$5.58** |

So the honest size of the lever: **$113/day of notional reach, worth −$5.58/day on the repaired arm**
(+$324/day on the booked arm — the cut would *destroy* booked profit). Neither number is approvable:
they differ in sign and the difference is the pending price-side repair.

The rv63+ cohort ($2,009 / 120 legs over 22 days) shows the same inversion at cohort scale:
**booked +$5,528.52, repaired −$84.11.**

---

## 4. Concentration: ex-top-5 wallets and ex-top-5 markets (finished basis)

Dropping the 5 wallets / 5 markets with the largest PnL contribution **within each band**:

**All-time**

| band | arm | n | ROI | CI95 | tol (h−p) | f* |
|---|---|---|---|---|---|---|
| 0.4–0.6 | all | 1,928 | −5.6% | [−12, +1] | −2.8pp | −5.6 |
| | ex-top5 wallet | 1,794 | **−8.0%** | [−14, −2] | −3.8pp | −7.6 |
| | ex-top5 market | 1,906 | **−7.4%** | [−13, −2] | −3.4pp | −6.8 |
| 0.6–0.8 | all | 1,167 | +2.0% | [−3, +7] | −2.4pp | −7.6 |
| | ex-top5 wallet | 820 | −1.1% | [−7, +4] | −2.5pp | −7.8 |
| | ex-top5 market | 1,145 | +0.9% | [−4, +5] | −3.0pp | −9.6 |
| 0.8–1.0 | all | 1,172 | −1.0% | [−4, +1] | −7.6pp | −101.3 |
| | ex-top5 wallet | 987 | −2.7% | [−6, +0] | −9.1pp | −134.4 |
| | ex-top5 market | 1,162 | −1.9% | [−5, +1] | −7.8pp | −104.9 |

0.4–0.6's deficit **survives** both cuts and the hit-rate test (tol −3.8pp, f* −7.6) — the one deficit
band whose record is not a concentration artefact. 0.6–0.8 straddles zero on every arm.

**Live regime** (small n, so read the CIs as the result, not the point estimates):

| band | arm | n | ROI | CI95 | tol | f* |
|---|---|---|---|---|---|---|
| 0.2–0.4 | all | 90 | +25.6% | [−14, +65] | +7.6pp | +10.9 |
| | ex-top5 wallet | 69 | **−13.8%** | [−51, +24] | **−0.4pp** | −0.6 |
| | ex-top5 market | 80 | **−9.9%** | [−43, +26] | **0.0pp** | 0.0 |
| 0.6–0.8 | all | 80 | −11.1% | [−32, +9] | −9.8pp | −31.3 |
| | ex-top5 wallet | 53 | −26.9% | [−54, −1] | −21.5pp | −68.8 |
| | ex-top5 market | 71 | −23.0% | [−43, −2] | −15.3pp | −49.0 |
| 0.8–1.0 | all | 29 | +0.8% | [−26, +19] | +8.0pp | +53.8 |
| | ex-top5 market | 19 | −22.4% | [−54, +20] | +4.1pp | +28.2 |

**The regime's one positive band is a four-wallet result.** 0.2–0.4 regime: 90 legs, 18 wallets,
72 markets, +$294.12 total; the top four wallets hold **$374.33 (127% of the band total)** and the top
wallet alone $106.45 (36%). Removing the top 5 wallets takes ROI from +25.6% to −13.8% and the
hit-rate tolerance from +7.6pp to −0.4pp. That matters to the parent card's *lift* arm, which rests on
this cell — it is a measurement, not a proposal, and it is the same "a delta that lives in one wallet
is not a band effect" test the parent recommended applying.

---

## 5. The card's own refutation cannot be run on most of 0.4–1.0

The card pre-registers: "if a forward 300-leg finished-basis sample keeps f* > 0 for 0.6–1.0, the
negative-f* reading is a history artefact." At live admission rates:

| band | regime legs / 17 days | legs/day | ETA to 300 legs |
|---|---|---|---|
| 0.4–0.6 | 0 | 0.00 | **never** (band skipped) |
| 0.6–0.8 | 80 | 4.71 | **64 days** (~2027-01-14) |
| 0.8–1.0 | 29 | 1.71 | **176 days** (~2027-05-06) |

Only 0.6–0.8 is testable on a plausible horizon. For 0.8–1.0 the refutation is effectively
unfalsifiable inside the live ruleset, which is an argument for restating the gate on the population
that actually exists (0.6–0.8 only) rather than for waiting.

---

## 6. What this measurement licenses — and what it does not

**Does it license a cut?** No. Three independent reasons, all measured:
- the 4-1.0 notional the card cites is **65% unreachable** under the live ruleset, and the reachable
  35% reads **+$262 repaired** (all-time) — no deficit to cut;
- the live reach is **$113/day** of notional worth **−$5.58/day repaired / +$324/day booked**; the
  sign is decided by a repair that is still pending;
- the one deficit band that survives concentration and the hit-rate test (0.4–0.6, tol −3.8pp) is
  **already hard-skipped for both lanes** with 0 legs admitted in 17 days.

**Does it license anything?** It retires the parent card's framing: the sizing defect is not "65% of
notional is allocated to bands that don't pay" — in the live regime 19% of notional is in the single
band with a negative f* (0.6–0.8, $932), and 39% is in the cheap band whose f* is +0.1 with a ±12pp
CI. The band-allocation problem the parent review found is, at current flow, a **0.6–0.8 problem worth
~$6/day** — smaller than the cheap band's −$62/day tail noise, and not separable from it on this
sample.

---

## 7. Open decisions (Lane A — I am not making them)

1. **Price-side repair** (`apr-ledger-price-side-repair`, 233 rows). Every 0.4–1.0 figure here flips
   sign on it: booked +$5,519 vs repaired −$95 in the regime; 26 of the 29 regime 0.8–1.0 legs are
   INVERTED and carry $4,848 of booked profit that the repair deletes. **No cut can be priced until
   this lands.**
2. **The parent's 0.2–0.4 lift.** Its regime cell is positive only including its top four wallets
   (§4). Whether a 90-leg, four-wallet result is enough to 2.1× the cell's size is an approval
   question for `profit-band-clip-rebalance`, not a measurement question.

Neither is decided here. Nothing in this run touched a rule, size, gate or reader.

---

## 8. Findings about the instruments themselves (Lane B)

- **The card's reproduce line pointed at a file that does not exist on main.**
  `scripts/profit-band-clip-preflight.py` is an **untracked file inside worktree `t_5d213302`** —
  never committed, so the f* section it cites could not be re-run from the repo. This run re-derives
  it from the committed shared basis (`profit-postfix-integrity.py` imported, not copied) and commits
  its own instrument, so the next reader can re-run the numbers on this page.
- **`profit-postfix-integrity.py` hard-codes `DB = "prisma/dev.db"`** and does **not** honour
  `COPYBOT_DB`, despite the clip-preflight docstring claiming the basis is "imported, not copied" via
  a read-only URI. Run from a worktree it silently creates a **0-byte `prisma/dev.db`** and the only
  signal is `no such table: PaperTrade` — which is exactly how this run's first attempt failed.
  `profit-band-allocation-preflight.py` now sets `ppi.DB` explicitly and refuses to run against a DB
  whose `PaperTrade` is empty. (Not fixed in `profit-postfix-integrity.py` itself: it is being edited
  concurrently in `t_5d213302`.)
- **The 0.85 entry cap is not a ceiling on booked price.** 14 of the 29 rv63+ legs in 0.8–1.0 booked
  above 0.85: the cap tests `currentPrice` at scoring while the leg books at the detection mid. The
  cap is therefore a *scoring-time* filter, not a hard price ceiling — worth knowing before anyone
  quotes "the band is closed above 0.85".

---

## 9. Reproduce

```bash
cd ~/polymarket-copybot/.worktrees/t_7fd6d307
COPYBOT_DB="file:$HOME/polymarket-copybot/prisma/dev.db?mode=ro" \
COPYBOT_JSON=data/profit-band-allocation-20261111.json \
  python3 scripts/profit-band-allocation-preflight.py
```

Read-only throughout; section 8 prints PASS/FAIL self-checks and exits non-zero if any fail
(a failed check invalidates every figure above). Full output: `data/profit-band-allocation-20261111.json`
(71 rows, every quoted number).
