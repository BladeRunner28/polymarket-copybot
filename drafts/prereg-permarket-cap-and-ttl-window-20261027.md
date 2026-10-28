# PRE-REGISTRATION — per-market leg cap, and the TTL window that actually pays

**Date:** 2026-10-27 · **Status:** PROPOSED — nothing applied, nothing in the live path changed
**Lane:** A (sizing / admission). Both parts need the user's explicit yes before any code change.
**Trigger:** user reported "a large drop in wins" and asked where to concentrate fast-resolving,
medium-to-high-return positions.

---

## Part 0 — what the win-rate scare actually was

Win rate by **entry** cohort (12,332 settled legs) falls monotonically, so the observation was right:

| entered | legs | win rate | ROI | PnL |
|---|---|---|---|---|
| Jul | 5,498 | 71.7% | +16.7% | +$9,212 |
| Aug | 4,598 | 54.3% | +1.5% | +$712 |
| Sep | 1,707 | 44.6% | +12.6% | +$2,932 |
| Oct | 529 | 41.2% | **+17.4%** | +$1,100 |

Average win rose $6.67 → $19.17 → $23.30 while average loss went −$9.05 → −$12.36 → −$12.80, and the
share of entries below 0.20 went 4% → 6% → 12% → 15%. **Win rate fell because payoff rose.** October
is the best ROI month in the series. Win rate alone cannot tell this apart from a collapse, which is
the reporting defect Part C fixes.

The genuinely bad window (115 legs settling from 10-26, −$1,169.87) is **old vintage arriving**:
median holding 66 days, max 103. 58 of those legs are one wallet on one market
(`will-flvio-bolsonaro-win`, 0/58, entries 0.229–0.329, −$679 = 58% of the loss).

---

## Part A — per-market leg cap

### Hypothesis
Correlated legs on a **single-outcome market** behave as one bet, so an uncapped book turns one
resolution into a portfolio-level loss. Capping leg COUNT per market bounds that without touching the
size or existence of the best positions.

### Measured exposure today (before any change)
- Open book: **470 legs / 93 markets / $5,131**
- **14 markets hold ≥10 legs → 315 legs, $3,257 = 63% of open notional**
- Worst: `will-barcelona-win-the-2026-27-uefa-champions-league` **63 legs @ 0.145**,
  Ethereum-dip 39 @ 0.546, Fed-no-cuts 32 @ 0.155, Man Utd 27 @ 0.115, Whitecaps 25 @ 0.142
- **440 of 470 open legs (94%) were entered before 2026-09-01**, median entry 0.145–0.197 — the same
  vintage that has been resolving badly. The lumpy losses are not finished.
- **There is no per-market leg cap in the code.** Not a regression: it never existed.

### Measurement
1. For every settled leg, the realised ROI of the book **as if** a cap of N legs/market had applied at
   entry (N = 3, 5, 10, 20), applied chronologically (first N kept, later legs dropped, no re-entry).
2. Report: total PnL, ROI, $/1k-capital-day, ex-top-10 ROI, and **worst-day PnL** — the tail is the
   point of the change, so a cap that improves the mean while worsening the worst day is a fail.
3. Split by market type: single-outcome prop vs. multi-leg parlay-style market, because a cap is only
   defensible where legs are genuinely correlated.
4. Market-clustered bootstrap on the delta, not leg-level.

### Decision rule
Adopt iff a cap of some N (i) leaves total PnL within −5% of uncapped, (ii) **improves the worst-day
PnL by ≥50%**, and (iii) ex-top-10 ROI does not worsen, on both all-time and 90d windows.

### Refutation
Drop the proposal if no N satisfies all three, or if the PnL cost exceeds 5% for every N ≤ 20 — i.e.
the concentration is load-bearing for returns, not merely for variance.

### Known conflict, stated up front
This sits against two prior measurements (10-22 and 10-27): the 200+ concurrent-notional bucket carries
**58% of book PnL at +20%**, and a 1%-of-principal notional cap forgoes **$6,614**. Those measured a
**notional** cap. A **leg-count** cap is a different restriction — it removes duplicated ways to lose
the same bet while leaving the size of a position intact. That distinction is the entire basis for
reopening the question, and if the measurement above cannot tell them apart, the answer is NO CHANGE.

### Cost / reversibility
Read-only measurement (~2 h) then, if adopted, one ruleset field (`maxLegsPerMarket`, default 0 =
unlimited) + one check in the scoring path. Revert = the field to 0.

---

## Part B — the TTL window that pays (refines v68, shipped today)

### Measured, market-clustered CIs, 12,168 legs with a usable TTL join
TTL = hours to resolution **at entry** (last snapshot within 15 min of the fill; decision-time, no
lookahead).

| TTL at entry | legs | markets | ROI | market-clustered 95% CI | med hold | $/1k-capital-day | ex-top-10 |
|---|---|---|---|---|---|---|---|
| <6h | 1,860 | 651 | **−8.6%** | [−24.0, +7.6] | 1.0d | −96.40 | −20.2% |
| 6–24h | 2,986 | 1,437 | **−6.5%** | [−17.8, +5.1] | 1.0d | −62.48 | −14.2% |
| 1–3d | 1,736 | 979 | +7.5% | [−6.4, +25.8] | 1.7d | +39.10 | −4.2% |
| **3–7d** | **2,114** | **287** | **+46.8%** | **[+12.8, +61.2]** | 3.9d | **+127.85** | **+43.0%** |
| 7–30d | 1,368 | 420 | +19.9% | [−4.2, +53.1] | 1.1d | +29.53 | −3.0% |
| >30d | 2,104 | 451 | +12.8% | [−3.6, +34.5] | 36.7d | **+2.88** | +5.4% |

**The answer to "fast resolving with medium-to-high returns" is 3–7 days, and emphatically NOT the
fastest.** The two fastest buckets lose (−8.6%, −6.5%) with bad ex-top-10 ROI, so they are not
tail-driven — they are broadly negative. 3–7d is the only bucket whose CI excludes zero and the only
one whose ex-top-10 ROI survives (+43.0%).

### Robustness — the check that matters
The bucket is dominated by `will-spain-win-the-2026-fifa-world-cup-963` (757 legs). Excluding it:

- 3–7d **+46.8% → +29.5%** on 1,357 legs / **286 markets** — still strongly positive, now well spread.
- Within it, 0.40–0.60 × 3–7d goes +56.9% → **+21.6%** on 364 legs / 104 markets.
- 77 distinct wallets; the largest is 29% of legs.

So the window is a real edge, not one match.

### What the money is actually in
Market-slug vocabulary of the 3–7d bucket: **world cup / FIFA / golden ball / goalscorer / Spain /
Messi / Mbappé / Kane / Bellingham**. These are tournament props with a **scheduled, knowable
resolution date** — which is exactly what makes a TTL window actionable rather than a hope.

### Why this is a refinement of v68, not a new idea
v68 (shipped 2026-10-27) already sizes by TTL: 0.5 below 24h, 1.0 at 24–72h, **1.5 at ≥72h**. The data
supports the 0.5 on <24h. But v68 puts **3–7d, 7–30d and >30d all in one 1.5× bucket**, and those are
+46.8%, +19.9% and +12.8% — with >30d costing **+$2.88 per $1k-capital-day** versus **+$127.85** for
3–7d, because 1.5× notional does nothing useful when the capital is trapped for 36.7 days.

**Proposal:** split the ≥72h bucket at 168h — i.e. 0.5 / 1.0 / **1.5 (72–168h)** / **1.0 (≥168h)**.
Same direction as v68, one boundary further out.

### Decision rule
Adopt the 168h split iff, on the settled book, moving the ≥168h cohort from 1.5× to 1.0× **raises
$/1k-capital-day for the whole STANDARD book** and does not reduce total PnL by more than 2%.

### Refutation
Drop it if the ≥168h cohort's $/1k-cd is ≥ the 3–7d cohort's on a 90d window, or if the split reduces
total PnL by >2% — meaning the long-dated legs earn their capital cost after all.

### Cost / reversibility
One ruleset field (`standardMaturityHugeHours`, default = 1e9 so the split is inert until set) plus one
branch in `applyMaturitySizeFactor`. Revert = the field. **Note:** this touches v68's schedule one day
after it shipped, which is why it is a separate pre-registration rather than an edit.

---

## Part C — the reporting defect (Lane B, no approval needed)

Win rate is printed without its payoff companions, so a deliberate shift toward higher-payoff positions
reads as a collapse. Fix: every daily block that prints win rate also prints **average win, average
loss, and ROI on the same population, clock and level**. One line, no new computation.

---

## What is deliberately NOT proposed
- **No notional cap.** Prior measurement says it forgoes $6,614 and the 200+ bucket is the only
  behaviour that pays at size.
- **No change to the 0.80+ band.** It is −19.1% (ex-top-10 −20.6%) at 3–7d, but it is already gated
  ahead of the evidence (12 legs since 09-15) and cutting a gated band changes nothing measurable.
- **No unconditional 0.40–0.60 re-entry.** That band is −20.8% (CI [−34.2, −4.8]) at 6–24h and +21.6%
  (ex-dominant) at 3–7d. **v63's flat band skip is over-broad on this axis** — but that is a third
  independent finding against that skip (after burst size), and it deserves its own read, not a
  side-effect of this one.

## Honest limits
- The TTL join covers 12,168 of 12,332 settled legs; 164 legs have no snapshot and are excluded from
  every cell above rather than guessed.
- Leg-level bootstrap would be flattering here (many legs per market); every CI quoted is
  **market-clustered**.
- 3–7d's 287 markets still means the CI is driven by a few dozen independent draws, not 2,114.
- Numbers are historical and the book is 94% pre-September vintage, so the forward population will
  differ from the measured one.
