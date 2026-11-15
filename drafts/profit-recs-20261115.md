# Profit review — 2026-11-15

**Instrument:** `scripts/profit-supply-ladder.py` (committed with this draft; `--self-test` 5/5, including a RED-check that a fair book cannot read a positive edge under the metric used here).
**Reproduce:** `python3 scripts/profit-supply-ladder.py` (read-only, `mode=ro`)
**Cost basis on every ROI line:** `PaperTrade.simulatedPositionSize` = **dollars at risk**. `dw ROI` = ΣrealizedPnl / Σdollars-at-risk. `eqw ROI` = mean per-leg ROI. They are printed side by side below because on this book they can disagree in **sign**.

---

## The one-paragraph version

Yesterday I quoted the cheap band at **+61.6% equal-weight**. At dollars at risk the same population is **−17.0%**. That is my error and it is the thread that unravels the whole ladder: **the book does not bet equal dollars**, so equal weight is a summary of a book that does not exist. Re-read at cost basis, the live regime (v68+, 17.8 days) earns **+3.1% on 222 settled positions = $7.1/day**, not the $57-60/day the settled column shows, because **182 settled rows stamped `unfilled` still carry +$370.8** — legs that earn exactly zero in live trading. Strip them and the last 14 days are **−$84 (−2.5%, −$6.0/day)**. The rung is 35x away on the positions-only rate; a bootstrap of the book's own outcomes gives a **0.7% chance** of clearing $1,750 in any week at today's volume, and 17% at ten times today's volume — which the funnel cannot supply.

---

## 1. The number that changes the picture: 182 legs that never filled are 55% of the last 7 days

The advance rule reads a settled 7-day sum. This asks which legs are inside it (S5, same 17.8-day regime, same clock):

- **last 7d, booked rows:** 169 legs, $3,843 at risk, +$424, **$60.6/day**
- **last 7d, positions only:** 82 legs, $1,645, +$303, **$43.4/day**
- **last 14d, booked rows:** 350 legs, $7,631, +$293, **$20.9/day**
- **last 14d, positions only:** 182 legs, $3,406, **−$84, −$6.0/day**
- **regime, booked rows:** 404 legs, $8,757, +$505, $26.8/day
- **regime, positions only:** 222 legs, $4,288, +$134, **$7.1/day**

The 182 unfilled settled rows carry **+$370.8 of realised PnL on $4,469 of notional**. `src/lib/paper.ts::bookedPnl()` already zeroes them; the `realizedPnl` column does not. So the honest run rate is anywhere from **$7/day to $43/day** depending on the window, and the number that gets quoted ($57-60/day) is the one that counts legs that never traded.

This is not a new defect — the 2026-11-13 fill-tape card established that 96% of C-200's booked profit sat on legs the market never brought to our price. What is new is that the defect **still owns the current week**, and that it flips the sign of a fortnight.

## 2. The cheap band, both bases — my yesterday's headline was wrong

Same legs, same regime, both bases printed (S2):

- **cheap band, both lanes:** 37 legs, $1,504 → **dw −17.0%**, eqw −6.0%
- **STANDARD cheap:** 17 legs, $199, **+$117 (+58.9% dw)** at a $11.7 average clip
- **C-200 cheap:** 20 legs, $1,305, **−$372 (−28.5% dw)** at a $65.3 average clip, median clip **$100**

Same band, same signals, opposite signs — and the difference is the clip. Six of the twenty C-200 cheap legs are $100 tickets that went to zero. At the band's own median clip ($20) the combined cohort reads **−11.9%**, not −17.0%.

So the +61.6% I published yesterday was the equal-weight answer to a question the book does not ask. **At cost basis the cheap band lost money in the live regime.** It is 37 legs; that is thin; but it is the dollar number, and it is the one that would have funded the ladder.

## 3. Clip tiers: 37% of the live dollars ride a tier that loses

Live regime, dollars at risk (S3):

- **$100 tier:** 16 legs, **37.3% of notional**, **−8.5%**
- **$40-99:** 3 legs, 3.5% of notional, −1.6%
- **$20-40:** 31 legs, 14.5%, **+30.6%**
- **$12-20:** 45 legs, 18.7%, +12.0%
- **<$12:** 127 legs, 26.0%, −1.2%

Cap shadow (linear rescale of every leg above the cap, no re-selection, S3):

- **$25 cap:** 19 legs touched → **+$102.9** vs uncapped, book ROI +3.1% → +7.9%
- **$40 cap:** +$81.9
- **$60 cap:** +$54.3

This is not a band story, which is why it differs from the pending card (`profit-band-clip-rebalance`, which caps 0.0-0.2 at $25). The negative cell here spans bands: `profit-clip-effect.py` §4 puts clip≥$18 at **−12.1pp vs clip<$10 with wallet, band and 2c price bins held fixed (t = −1.92)**, and §3's within-wallet paired read is **−58.1pp, CI [−108.1, −16.6], only 16 of 43 wallets better at the big clip**. Two instruments, same direction: **big clips earn less per dollar than small ones, and the cheap band is where the discount is worst** (§5: 0.00-0.20 clip≥18 at −103.1pp, t = −2.12).

Counter-evidence, stated: the live window's **$20-40 tier is the best cell in the book (+30.6%)**, which the pooled fixed-effects read does not predict. Those two readings disagree. The cap I recommend ($25) is above the whole $20-40 cell, so it does not bet on which of them is right.

## 4. The ladder as arithmetic — and why the rung is not reachable by tuning

`PnL/day = admitted bets/day × dollars per bet × ROI per dollar`. Live regime, positions only:

- **11.8 settled bets/day × $19.32/bet × +3.1% = $7.1/day.** Rung $250/day → **35.09x**.
- close it by **supply alone:** 412.7 settled bets/day (35x today)
- close it by **clip alone:** $677.78 per bet (35x, and refuted in §3)
- close it by **edge alone:** +110% per dollar

Measured supply: **22,900 priced candidates, 336 copies = 1.47% admit, 1,284 candidates/day.** At today's admit rate the rung needs **45,062 candidates/day** — 35x the entire candidate stream, which is not a lever, it is a different business.

Bootstrap of the advance rule itself, drawing from the regime's own 222 per-position outcomes (S4, 4,000 draws):

- **82 legs/week (today):** median **−$22.7**, P(≥ $1,750) = **0.1%**, P(week ≥ 0) = **47.6%**
- **247 legs/week (3x):** median +$69, P(advance) = **2.4%**
- **412 legs/week (5x):** median +$165, P(advance) = **5.2%** — $7,952 of notional/week
- **823 legs/week (10x):** median +$434, P(advance) = **16.9%** — $15,872/week

Read that last row plainly: **even at ten times the book's actual throughput, the rung is a 1-in-6 week.** At today's throughput the median week loses money.

## 5. Yesterday's rec 2, closed by inspection

I asked for the 391-leg open STANDARD book to be adjudicated against the venue archive, refuted if <50% resolved. The inspection answer is cheaper than the archive: the open book is **82 markets, $4,563, and its top six markets are 47% of it** — Barcelona to win the 2026-27 UCL (63 legs), ETH dip to $1,500 by 31-Dec-2026 (39), no Fed cuts in 2026 (32), Man Utd 2026-27 EPL (27), Vancouver 2026 MLS Cup (25), Yal Braun-Pivet 2027 French presidential at 0.003 (20). These are season futures and year-end macro. They are **not stale-detection failures**; they cannot resolve for months, and 27% of open notional carries 2027 or Dec-2026 in the slug by direct text match.

So the honest closure: the open book is **genuinely live**, which is the card's refutation branch, and that is the finding — a quarter of STANDARD's capital-time is parked in positions whose earliest possible settlement is 2027, with unrealised −$83. Extending the stale-exit sweep to STANDARD would free **nothing**, because there is nothing to settle. I withdraw the "extend the exit" framing.

---

# Recommendations, ranked by expected value

### 1. Cap C-200's per-leg clip at $25, lane-wide — LANE A, propose only

**Hypothesis.** The $100 Kelly ceiling is the book's only losing dollar tier in the live regime; capping C-200 at $25 leaves the same signals, raises the book's dollars-at-risk ROI, and removes 37% of notional from the single most fragile cell.

**Measurement.** `scripts/profit-supply-ladder.py` S3 (live-regime tier table + cap shadow) and `scripts/profit-clip-effect.py` §3/§4/§5 (within-wallet paired, wallet+band+price fixed effects). Cap shadow at $25: **+$102.9 over 17.8 days** on 19 touched legs.

**Decision rule.** Apply as a new RuleSet field (`c200ClipCapUsd`, defaulted 0 = off, byte-identical today) if, on the re-read, the $25 shadow is ≥ +$50 over the regime **and** the fixed-effects coefficient at clip≥$18 stays ≤ −8pp with price and wallet held. Both hold today.

**Refutation.** Withdraw if a forward **40-leg $100-tier sample** earns ≥ the sub-$40 tiers' ROI, or if any month's capped book underperforms its own uncapped shadow by ≥ $50. A cap is variance reduction bought with expected PnL; if the $100 tier is actually the good cell, this loses money and I would be wrong.

**Expected effect.** +$103 realised over 17.8 days ≈ **+$5.8/day**, and the drawdown tail shrinks: 37% of notional stops riding sixteen legs. Cost: **1h** (one RuleSet field + one apply script).

### 2. Credit the ladder on positions only — LANE A, read path

**Hypothesis.** The settled 7-day sum that advances the rung includes 182 settled rows stamped `unfilled`, worth **+$370.8**, which earn zero in live trading; the ladder is advancing on dollars that never existed.

**Measurement.** `scripts/profit-supply-ladder.py` S5 (both clocks, three windows) cross-read against `src/lib/paper.ts::bookedPnl()`. Regime: **$26.8/day booked → $7.1/day positions-only**. Last 14d: **+$20.9/day → −$6.0/day**.

**Decision rule.** Pin every surface that feeds the ladder and the EOD to `bookedPnl()`; if any of them sums the `realizedPnl` column directly, change that one and print both bases for one week before publishing only the positions-only number.

**Refutation.** If the venue tape shows **≥ 70% of those 182 legs filled** within 24h of dispatch, they were real positions, the booked basis stands and this change is wrong. The 2026-11-13 tape read measured **7.5%** touch on an 80-leg 1-minute re-check, but that was C-200 only and a different sample — this is the test to run, not a settled fact.

**Expected effect.** No PnL change. It moves the published run rate from **$60.6/day to $43.4/day** (7d) and **+$20.9 to −$6.0/day** (14d), which is what anyone steering by the ladder believes. Cost: **1h**.

### 3. Do not raise size, and do not steer toward the rung — the measurement is not there

**Hypothesis.** The book's live-window dollar-basis edge is not distinguishable from zero (222 positions, +3.1%, and −2.5% over the last 14), so any size increase multiplies an unmeasured quantity and any rung-chasing is a lottery.

**Measurement.** S4's bootstrap (P(advance) = 0.7% today, 16.9% at 10x), S1's factor decomposition, and yesterday's carded cheap-refusal read (189 cheap refusals unpriced at the ask).

**Decision rule.** **No change** to clip, gates or bands until a forward sample clears the bar below.

**Refutation of this "hold".** **200 forward settled positions at ≥ +20% dollars-at-risk ROI with ex-top-10 ROI still positive** would refute "edge unproven" and justify scaling. Today nothing is close. The measurement that unlocks it is the carded one: price the 189 cheap refusals at the ask, because the cheap band is the only cell that reads positive at equal weight and negative at cost.

**Expected effect.** Zero by construction; the value is not spending money on a 1-in-6 lottery. Cost: **0h**.

---

**IF YOU WEREN'T HERE:** re-point the ladder's credit at positions only. A rung measured on 182 legs that never filled is not a measurement, and it is the cheapest thing on this page to fix.

**What I did not re-litigate, and why.** Gate tuning (liquidity and wallet cap both closed NO-CHANGE under their own shadow reads); the 0.4-0.6 skip; band-factor sizing on STANDARD (the 90d shadow is +$822 with CI [−978, +2,922] and the live-era arm is +$243 CI [−96, +632] — no recent support); the $100-clamp *raise* (refuted 2026-11-06 and again by §3); the TTL-floor flip (net of the live band skip the 24h floor's blocked cohort is +0.8% with CI [−11.1, +14.7] on `profit-velocity.py` §AI).

**Supporting claims kept separate.** §3's clip-tier finding (a CI-significant fixed-effects coefficient plus a small live-window cell) is independent of §1's fill-basis finding (an accounting identity on 182 stamped rows). Either can be approved without the other.

**Caveats that travel.** 222 settled positions is a thin live window; the $100 tier is 16 legs; the $25 cap shadow is therefore noise-adjacent, which is why rec 1's refutation is a forward 40-leg sample rather than a re-read. The bootstrap treats legs as i.i.d. across markets, which overstates precision when the book piles into one market (top six markets = 47% of the open book) — the real p05 is worse than printed.

**Lane discipline.** Nothing applied. No RuleSet read or write, no prisma write, DB opened `mode=ro`, no `apply-v*` script written. Both cards added to `data/roadmap.json` as `awaiting-approval`.
