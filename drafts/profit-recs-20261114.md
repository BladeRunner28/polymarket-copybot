# Profit review — 2026-11-14

**Instrument:** `scripts/profit-cheap-funnel.py` (committed with this draft; `--self-test` 15/15, one negative control deliberately RED-checks that a positive edge cannot be manufactured by the metric function).
**Reproduce:** `python3 scripts/profit-cheap-funnel.py --resolve`
**Cost basis on every ROI line below:** `PaperTrade.simulatedPositionSize` = dollars at risk. `entryPrice` is a price, never a cost.

---

## The one-paragraph version

Yesterday I killed the booked number: 96% of C-200's profit sat on legs the market never brought to our price. Today I tried to find the replacement money, and the honest answer is that the cheap tail's famous edge is **a mid-price illusion on the one population I could price at the ask** — while the population I *cannot* price is the best-looking cell in the book. The scorer refuses 79% of cheap-tail refusals **before it ever measures the spread**, because drift and confidence are checked first in `trade.ts`. So the book is blind on the exact question that decides whether those refusals were right. That blindness, not the thresholds, is what is costing money.

---

## 1. First, a correction that changes every band table the book publishes

`fillStatus='unfilled'` legs are **not positions**. They book `realizedPnl = 0` but keep their full `simulatedPositionSize` in the denominator — so in a hit-rate table they land in the "lost" bucket, and in an ROI table they add notional with no profit.

Live regime (admitting `journal.ruleSetVersion >= 68`), resolved legs: **340 finished rows, but only 226 positions. 114 are stamped unfilled.**

| band | all finished rows | positions only |
|---|---|---|
| 0.0–0.2 | +1.9pp / eqw **−3.0%** (n=65) | +11.0pp / eqw **+61.6%** (n=39) |
| 0.2–0.4 | −2.4pp / eqw −12.8% (n=119) | +8.8pp / eqw +23.5% (n=84) |
| 0.6–0.8 | **−23.9pp / eqw −35.3%** (n=121) | **+0.3pp / eqw +0.4%** (n=78) |
| 0.8–1.0 | −10.9pp / eqw −11.8% (n=33) | +14.0pp / eqw +16.4% (n=25) |

A 24-point swing on one band, caused entirely by counting legs that never were. This is not a rounding issue: **every band table built on "finished rows" is currently wrong in the direction that makes the book look worse and makes the gates look better.**

Two standing figures do not survive this. The measured baseline says *"64.4% of acted trades sit above price 0.50, where edge is negative."* On positions only, all-time, no band between 0.4 and 0.8 is negative on the calibration test that matters (hit rate vs price paid):

- 0.4–0.6: **+3.9pp** CI [−0.8,+8.6], n=615, dollars at risk $6,279, ROI −3.7%
- 0.6–0.8: **+7.2pp** CI [+3.2,+11.6], n=472, $5,647, ROI +4.7%
- 0.8–1.0: +1.9pp CI [−4.1,+7.3], n=181, $2,647, ROI +2.4%

The upper book is roughly fair, not negative. The 0.4–0.6 *dollar* loss (−$234) with a *positive* hit-rate edge is price dispersion inside the band — wins bought lower than losses — and it is why the ROI and the edge must be printed together, never one of them.

I am not asking anyone to act on that paragraph. It is a correction to the record, and it means the negative-edge case for shutting the upper book has to be re-argued on positions, not rows.

---

## 2. The funnel: where cheap volume actually dies

23,357 candidates in the live regime → 334 copies (**1.43%** admit).

| band | candidates | copies | admit % | candidates/day |
|---|---|---|---|---|
| 0.0–0.2 | 2,269 | 88 | 3.88% | 126.5 |
| 0.2–0.4 | 2,820 | 152 | 5.39% | 157.2 |
| 0.4–0.6 | 9,502 | **0** | 0.00% | 529.6 |
| 0.6–0.8 | 2,039 | 91 | 4.46% | 113.7 |
| 0.8–1.0 | 6,727 | 3 | 0.04% | 375.0 |

The two shut bands are 40.7% of candidate supply. That is a measured, deliberate shutdown (the f* funnel read closed it; I am not reopening it here).

## 3. The refused cheap cohort, priced against the venue's own resolutions

Refused cheap candidates (0.05 ≤ p < 0.20), deduped to the first sighting per market+outcome: **385 markets. 320 resolved from `clob.polymarket.com/markets/<conditionId>` (83% coverage, keyless, retroactive).** Scored as if copied at the detection price.

| cohort | n | markets | hit% | breakeven% | edge | eqw ROI |
|---|---|---|---|---|---|---|
| **REFUSED** (at detection mid) | 320 | 319 | 23.1% | 12.0% | **+11.1pp** CI [+6.8,+16.0] | +108.5% |
| **ADMITTED** control (realized) | 39 | 32 | 23.1% | 12.1% | +11.0pp CI [−2.9,+26.7] | +61.6% |

Identical hit rate. My first pass read that as *"the gate refuses candidates exactly as good as the ones it admits"* — and that reading is **wrong**, because it prices the fill at the mid.

**Split by whether the scorer recorded a spread on the row** (it records one only when the spread check fires):

| subset | n | edge at mid | eqw ROI at mid | at half-spread | at full spread |
|---|---|---|---|---|---|
| spread recorded (median 10.0c) | 131 | +7.1pp | +47.8% | **−2.9%** | −26.5% |
| **no spread recorded** | 189 | **+13.9pp** | **+150.6%** | *unpriced* | *unpriced* |

The 131 I can price say the spread gate is **right**: at half the quoted spread the edge is gone. The 189 I cannot price — refused for drift, confidence, timing or blacklist before the spread was ever read — carry the best measured edge in the book and **nobody knows what they would have cost.**

That is the finding. The gate is not mis-set; the check *order* is. `src/lib/scoring/trade.ts` tests drift and confidence before spread, so on four fifths of cheap refusals the row records a reason that carries no fill information, and the book cannot learn whether it refused a 12c fill or a 25c one. The funnel card documented this as a check-order artifact on 2026-10-12 ("the 47% drift headline is the scorer's own check order"). Nobody drew the consequence: it is not a reporting artifact, it is the reason the refusals are unfalsifiable.

Robustness: the 65 unresolved candidates booked as **losses** still leave **+7.2pp** (19.2% hit vs 12.0% breakeven). Breakeven entry for the cohort is **23.1c** against a 12.0c detection mid — 11.1c of tolerated slippage, which is why the mid-priced version looked indestructible and why the 10c-spread subset is where it dies.

Cross-check, independent instrument, not mine: the live long-shot shadow ladder (`data/longshot-shadow-summary.json`, running since 2026-09-12) reads **133 would-admit of 9,785 candidates, 113 resolved, 24 wins (21.2%), +$1,845.52 on $20 stakes = +81.7% ROI.** A different population, a different screen, the same +9-11pp above breakeven. Two instruments agreeing is the strongest thing in this brief.

---

## 4. The scoreboard, honestly

Regime positions: **$1,025 realized on $4,253 of notional.** By settle day over the last 16 days: **$934 total = $58/day, 9 of 16 days negative**, with two days (+$461, +$653) carrying $1,114 — i.e. the entire 16-day profit is two days and the other fourteen are −$180.

The rung is $250/day (gate: settled 7d sum ≥ $1,750). **The book is 4.3x short, and no sizing change closes 4.3x.** Deployment is $600–1,080/day of notional; the missing lever is not capital (93% of the bankroll is idle cash) and not clip — it is admitted flow at the same edge.

Also live and unresolved: **391 STANDARD legs, $4,318 cost, −$82 marked, average age 99.2 days**, still open because the stale-exit block is scoped `botId === "BANKROLL_200"`. That is 74 days of the book's entire live output sitting in positions the resolver should already be able to adjudicate.

---

## Recommendations

### REC 1 — Measure the 189 cheap refusals at the ask, then re-order the scorer's checks (LANE A; 2h measure, 1h change)

**Hypothesis.** The 189 cheap candidates the scorer refuses before it reads the spread are profitable at the executable ask, and the book refuses them on a gate that carries no fill information.

**Measurement.** `python3 scripts/profit-cheap-funnel.py --resolve` produces the 189-row cohort and its mid-priced result (+13.9pp, eqw +150.6%). The next step joins each of the 189 to `MarketSnapshot.bestAsk` within ±2h of `DecisionJournal.createdAt` and recomputes at the ask. Read-only; no rule, no threshold, no prisma write.

**Decision rule.** If ≥120 of the 189 resolve to an ask and their ask-adjusted mean ROI is **≥ +20%**, propose exactly one change: move the spread check ahead of drift/confidence in the hard-skip order in `src/lib/scoring/trade.ts`, so a candidate is refused by the gate that costs money rather than by the first gate that fires. **No threshold moves.** The drift HOLD and the liquidity NO-CHANGE are untouched by an ordering change, which is the whole point of proposing it this way.

**Refutation.** Ask-adjusted mean ROI **< +5%** on the 189 → the refusals were right for reasons the row never recorded, the ordering change buys nothing, and I withdraw. Also withdrawn if `MarketSnapshot` coverage on those 189 falls below 60%, because then the measurement cannot be made at all.

**Expected effect.** If it clears, admitted cheap flow goes from ~1.3 to ~4 legs/day at the same +11pp; at a $13 clip that is **+$30–50/day**, against a book currently at $58/day. **Cost 3h.**

### REC 2 — Adjudicate the 391-leg open book from the venue archive (LANE A; 1h)

**Hypothesis.** The $4,318 of STANDARD capital sitting in 99.2-day-old open legs is mostly on markets that have already resolved, so the freeze is an accounting failure rather than a genuine open risk.

**Measurement.** Same archive route as section 3, one call per `conditionId` on the 391 open legs (`PaperTrade` status `open`, `isDemo=0`), then a booked-vs-archive PnL for the whole open book. Read-only.

**Decision rule.** If ≥75% of the 391 carry an archive winner, the stale-exit scope (`scripts/update-pnl.ts:240`, `botId === "BANKROLL_200"`) is a defect and gets fixed with the archive as its oracle, one commit, env-revertible.

**Refutation.** <50% of the 391 resolve from the archive → they are genuinely live positions, the freeze is not a defect, and I withdraw rather than touch the exit path.

**Expected effect.** Converts $4,318 / 74 days of book output from unknown to known; sign unknown and could be negative. **Cost 1h.**

### REC 3 — Positions, not rows, in every band and ROI read (LANE B — I fixed the instrument, not the readers; 30 min done)

Done in this commit: `profit-cheap-funnel.py` excludes `fillStatus='unfilled'` from every denominator (`positions()`), with a self-test that asserts it drops exactly those rows. **Not done, deliberately:** I did not edit the dashboard, the EOD or `profit-band-report.py`, because moving published numbers by 24pp on one band is a visible change that should land with its own read. The number to approve it with is in §1.

---

**IF YOU WEREN'T HERE:** move the spread check ahead of drift and confidence in `trade.ts` so the book stops refusing candidates on a reason that cannot be priced. It moves no threshold, it cannot re-litigate the drift HOLD, and it is the only change on the table that makes the next refusal falsifiable.

---

## What I am NOT proposing, and why

- **Gate tuning.** The liquidity blocker and wallet copy cap are dead ends (closed NO-CHANGE under their own shadow reads). The 0.4–0.6 and 0.8–1.0 shutdowns stand.
- **A clip change on the cheap band.** At the ask the spread-matched population is −2.9%; adding size to a zero-edge cell adds variance, not profit. This is the half of yesterday's rec 3 that today's data does not support.
- **Reasserting "the book is 10 legs".** Corrected above: on positions, all-time, the cheap band is +10.9pp CI [+3.7,+17.8] on 185 legs across 47 wallets and 147 markets. It is five wallets deep but not one event.

## Contradictions I found and did not resolve

1. **Inside the shared instrument.** `profit-band-report.py` §E and §J disagree by 5x on the same band and window: §E's 30d 0.0–0.2 is **n=24, $325, +30.8%**; §J's 30d 0.0–0.2 is **n=120, $4,900, −3.7% gross**. Same band, same window, opposite sign. I did not quote either. This is an instrument defect and it should be fixed before any window-based band claim is approved.
2. **`walletEntryPrice` on cheap legs.** On the refused cheap cohort the mean wallet fill is **19.7c** against a mean detection price of **12.1c** — a −7.6c "copy cost", four times larger than the 2c maker credit that explains the rest of it. Either the copy signal is genuinely stale on this band (we see the trade long after a 7.6c fall, which would itself be the edge) or the column is unreliable here. It does not touch this brief — I priced at `detectedPrice`, not at the wallet's fill — but it invalidates any copy-cost figure computed on the cheap tail.

## Provenance

- Lane A: **nothing applied.** No `RuleSet` row read or written, no `apply-v*.ts`, no prisma write, no gate, threshold, size or booking changed.
- Lane B: one new read-only instrument (`scripts/profit-cheap-funnel.py`, 15/15 self-tests) and one `.gitignore` line for its HTTP cache (384 cached `conditionId` responses, refetchable keyless).
- DB opened `mode=ro`.
