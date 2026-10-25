# Profit review — 2026-10-25

http://localhost:3013/drafts/profit-recs-20261025

**Cost basis on every ROI below: `simulatedPositionSize` = dollars at risk, never shares.**
All figures computed by `scripts/profit-velocity.py` §AH–§AK (this commit). Windows stated inline.
Reproduce: `DATA_MODE=live python3 scripts/profit-velocity.py` (runs every section, including these);
`--only-ah`, `--only-ai`, `--only-ak` run a subset.

---

## The floor we approved three days ago is half an artefact, and the real lever is one function away

On 10-23 I recommended raising STANDARD's `minTimeToResolutionHours` from 2 to 24 on the strength of
**−13.0% on 3,395 legs, CI [−21.8,−4.0]**. That measurement was wrong in a way I should have caught at
the time: **v63 had been refusing STANDARD's 0.40–0.60 band since 10-20**, and the cohort I measured
included every historical 0.4–0.6 leg opened before that. I priced a population my own live rules
already refuse. The card was approved on it and is now sitting behind a 4-of-150-leg forward shadow
(~35 days out).

Replayed on the shadow's exact cohort (§AK), STANDARD, entry TTL in [2,24)h:

- **as the shadow measures it** — 3,386 legs, $42,018, **−12.9%** CI [−21.9,−3.9] *(its file says 3,405 / −12.78%; the 19-leg gap is the snapshot- vs entry-TTL boundary, not a disagreement)*
- **the legs v63 already refuses** — 1,553 legs, $20,279, **−20.4%** CI [−32.5,−7.6]
- **what the floor would actually bind on** — 1,833 legs, $21,739, **−5.9%** CI [−18.1,+6.9]

**48% of the floor's notional is already gone, and that half is the entire negative.** What remains is
directionally negative and statistically indistinguishable from zero. The floor is not a bad idea; it
is a *duplicate* of v63 wearing a different name, and its case lost its error bars.

So I stopped arguing about blocking that cohort and asked the question underneath it: **does STANDARD
size differently for a market that resolves in 3 hours vs 3 months?** It does not — and it sizes
*smaller* where the money is (§AJ, STANDARD net of the v63 skip, all-time):

| entry TTL | legs | median clip | ROI | $/1k-cd |
| --- | --- | --- | --- | --- |
| <24h | 1,845 | $11.20 | **−6.0%** | −57.08 |
| 24–72h | 704 | $10.00 | +2.0% | +10.10 |
| ≥72h | 3,338 | **$9.00** | **+21.4%** | +7.37 |

A 27-point ROI spread, sized flat within 24%, and the *inversion* is systematic: the worst cohort gets
the largest clip, the best gets the smallest. This is the same defect v63 fixed on the price axis —
`score-trades.ts:1129` books `simulatedPositionSize: positionSize || 0.25` for both lanes, and every
factor that touches `positionSize` above it is `botId === "BANKROLL_200"`, so the lane is blind to
every dimension of the trade. Price got a skip; maturity never got anything. 90d repeats it:
−7.7% / +8.1% / +28.1%.

**Why a size factor and not a skip:** the <24h cohort is −6.0%, not −60%. Blocking it forgoes whatever
convexity it holds and throws away the whole book's fastest-turning capital. Sizing it to a quarter
keeps the convexity and moves the dollars. That distinction is the entire difference between the
pending floor and this proposal, and it is why #1 supersedes #2 rather than stacking on it.

---

## #1 — Give STANDARD a maturity size factor: 0.5 / 1.0 / 1.5 now, 0.25 / 1.0 / 2.0 once the clip cap moves. Lane A.

**Hypothesis.** STANDARD's realised ROI is allocated against its own edge on the maturity axis: dollars
moved from entries resolving inside 24h to entries resolving beyond 72h raise realised PnL at constant
notional, and the effect is not one market.

**Measurement.** `scripts/profit-velocity.py` §AJ (`--only-ak`). Reads `PaperTrade` (closed+resolved,
realised), `MarketSnapshot.timeToResolution` for entry-time TTL, and the active `RuleSet`; applies the
live `standardSkipBandRange` so no leg v63 refuses is credited to the rule. Applies
`BOT_LIMITS.STANDARD` `{0.25, 20.00}` clamping after the factor, because the clamp books after any size
factor and a schedule that asks for more than $20/leg does not happen. Market-clustered bootstrap,
1,500 reps, CI on the PnL **delta** vs the flat baseline. Notional-neutral arm renormalises so total
dollars are unchanged — that is the reallocation, and it is the arm I am proposing.

| arm (notional-neutral, clamp applied) | all-time PnL | 90d PnL | 90d ROI | 90d $/1k-cd |
| --- | --- | --- | --- | --- |
| flat (live) | +$5,980 | +$2,842 | +8.1% | +7.90 |
| 0.5 / 1.0 / 1.5 | +$9,297 | +$5,515 | +15.7% | +15.33 |
| **0.25 / 1.0 / 2.0** | **+$11,008** | **+$7,239** | **+20.6%** | **+20.12** |
| inverse 2.0/1.0/0.5 *(control)* | +$2,099 | +$577 | +1.6% | +1.60 |

- Delta vs flat: **+$5,028 all-time, +$4,397 per 90d**, CI **[+1,778, +8,628]** / **[+1,018, +8,275]** — excludes zero in both windows.
- **Ex-top-10 markets**: strong +13.0% vs flat +2.9% on 90d → **+10.1pp**. Survives every tail cut (ex-top-1 +12.2pp). Not one market.
- **The control is the load-bearing part.** The inverted schedule (up-weight the short cohort) *loses* $6,939 all-time with CI excluding zero. If the TTL effect were an artefact of shuffling clips, the inverse would be flat, not reliably negative.
- **Fillability.** ≥72h cohort, 90d: notional-weighted entry 0.605, ROI +28.1% → **breakeven entry slippage 17.0¢/share**. Doubling the median $10.80 clip needs **$21.60 of depth at the ask**. Yesterday's live-book probe measured median +2c depth $1,881 (229× the clip), so depth is not the binding constraint — but that probe covered sub-0.20 books only; I have not measured depth at 0.6–0.85, which is where most of this notional lands. **Stated as unmeasured, not as satisfied.**

**Decision rule.** Act when all three hold: (a) the ≥72h cohort's realised ROI exceeds the <24h cohort's
by ≥ 5pp on both the all-time and 90d windows; (b) ex-top-10 on the sized book beats flat by ≥ 3pp;
(c) the inverse control is not positive. All three met.

**Refutation.** Revert to flat if, on **150 forward STANDARD legs** opened after activation: (a) the
≥72h cohort's **ex-top-10 ROI goes below 0%**; or (b) the <24h cohort's ROI rises to **≥ +3%**, i.e. the
down-weight cost more convexity than it saved; or (c) the median <24h clip after the factor falls below
$2.00, at which point the factor is a de-facto skip and should be evaluated as one.

**Expected effect.** +$4,397 per 90d at current flow (**~$49/day, ~$17.8k/yr**); ROI +8.1% → +20.6%;
**$/capital-day +7.90 → +20.12, which cuts the capital required for $5,000/day from $632,911 to $248,509
(−61%)**. Set against the ladder, $49/day is 1.0% of the $5,000/day target: this is a 2.5× on the
compounding rate, not a solution, and I will not dress it as one.

**Cost: 1.5h.** One rule field (`standardTtlSizeFactor` + two hour boundaries, default 0 = disabled so
landing the code changes nothing), one call site between the v63 skip at `score-trades.ts:1002` and the
shared booking line at `:1129`, 9–10 unit tests mirroring `applyBandSizeFactor`, and an `apply-vNN.ts`
that prints the affected population before activation. `clampPaperSize` (`paper.ts:142`) runs after the
factor in `openPaperTrade`, so the $20 ceiling binds regardless of what the factor asks for.
**The 0.5/1.0/1.5 tier needs no cap change; the 2.0 tier asks `maxPositionSize` $20 → $40 and
additionally raises per-leg exposure, so I would ship 0.5/1.0/1.5 first and read it.**

---

## #2 — Do not flip the 2h→24h floor. Retire it as superseded. Lane A, costs nothing.

**Hypothesis.** The approved floor's incremental value over the live v63 skip is not established, and
shipping it alongside #1 places two instruments on one axis where the blunter one (a hard skip) can
only subtract convexity the finer one (a quarter-size clip) preserves.

**Measurement.** §AK above — identical cohort, shown with and without `standardSkipBandRange`
applied. The leg that matters is the third row, not the first.

**Decision rule.** Hold the flip. If #1 activates, the <24h clip becomes ~$3 and the floor's residual
is a $3 clip it cannot remove — retire it at that point rather than stacking.

**Refutation.** Ship the floor after all if the post-factor <24h cohort still returns **below −10% on
150 forward legs** — that would mean a quarter-size clip is not enough and a hard skip is the right
instrument after all. Note this is a *different* refutation from the card's current one, which is
written against a −12.78% baseline that no longer describes the population.

**Expected effect.** Avoids a change whose measured effect is ~half a duplicate of one already shipped,
and avoids a rule interaction (skip-then-size) that nobody has measured. **Cost: 0h** — the "change" is
not making one.

---

## #3 — Concentration caps: measured, and I am NOT proposing one. Here is what would unlock it.

The cap case looks strong and I want to record why I am declining it, because the numbers invite it
(§AH, all lanes, cost = dollars at risk):

| marginal dollars above | all-time raw | all-time ex-top-5 | 90d raw | 90d ex-top-5 |
| --- | --- | --- | --- | --- |
| $25 | +15.4% | **−2.4%** | +6.5% | **−8.9%** |
| $100 | +23.9% | **−9.2%** | −4.2% | **−28.6%** |
| $200 | +30.0% | **−24.2%** | −24.8% | **−55.5%** |

Every threshold is positive on the raw book and **negative on five markets removed**. That is the
signature of a cap that would print money — except for one thing I checked before believing it (§AH.4):
the three best legs in the book are $100 clips sitting in 1-leg, 3-leg and 5-leg bets, and
**a $100 per-bet cap binds on two of the three**. The tail ex-top-5 removes is the same tail the entire
book's PnL is made of. "Concentration is unprofitable ex-tail" and "the tail is the edge" are the same
sentence here, and I cannot separate them with 12,207 legs of a book whose best day was 96% one leg.

The same logic kills the per-wallet rail: one wallet holds **29.4% of the open book** ($1,818.80 across
184 legs, 12 bets) against a v58 ceiling that is C-200-only. That is genuine unhedged single-wallet
exposure on the lane that carries the book — but capping it cuts the same winners.

**What would unlock a cap:** 300 forward **bets** (not legs) in which the ex-top-5 marginal ROI at $100
stays negative *and* the top-5 markets by notional are not the top-5 by PnL — i.e. concentration stops
being synonymous with the edge. Until then this stays a measured dead end, and I am not re-proposing it.

---

## Also measured, no action

- **v67 (longshot floor) is in and is preventive.** C-200 held 0 open legs below 0.05 at activation, so
  there is no PnL to read yet. The refutation stands as written: blocked sub-0.05 candidates winning
  ≥3 of 60 forward legs, or 0.05–0.20 truth ROI <0% on a 60d read.
- **The stale-exit work held.** Open book fell from 1,269 legs to **563** (554 STANDARD / 99 markets,
  $6,101) with median age still 85d and **484,421 capital-days = 30.0% of all capital-time ever**. v66's
  scope (entry ≥ 0.60, 168h) does not reach the rest, and the settled-truth replay says it should not:
  a 168h stop on <0.4 costs **−$1,450**. Cheap legs are the convexity; time-stopping them is the error.
- **The 0.4–0.6 band contradicts itself by window** (§Y): first-fill basis −6.42% all-time vs −6.73% 90d
  (agrees), but repeat fills **+13.53% all-time vs −17.41% 90d**. v63 skips the band anyway, so nothing
  turns on it today — recording it because a review that quoted one window would have "found" either
  a disaster or a opportunity.
- **Exits, re-checked on capital-days, remain a wash and should stay untouched**: 2,275 STANDARD exits
  released 703,524 capital-days for **+$2 per 1k capital-day released** against a book benchmark of
  $27.43 — i.e. the exits were worth doing for the *capital*, not the alpha, which is exactly what
  already happens. This does not reopen the exit question.

---

**IF YOU WEREN'T HERE:** give STANDARD the 0.5/1.0/1.5 maturity factor today — the lane is currently
sizing its worst cohort the largest and its best cohort the smallest across a 27-point ROI spread, and
that is a one-field fix that pays ~$30/day at current flow with no new risk rail.

---
*Lane B, applied directly: `scripts/profit-velocity.py` §AH–§AK (+585 lines: `active_rules`,
`load_bets`, `apply_bet_cap`, `marginal_bet_dollars`, `boot_pair`, `boot_ratio`, `skip_range`,
`in_range`, `concentration_shadow`, `ttl_floor_ladder`, `ttl_shadow_reconciliation`,
`ttl_sizing_shadow`; wired into the DEFAULT run, with `--only-ah/-ai/-ak` for a subset).
Read-only DB access throughout. **No RuleSet row touched, no rule edited, no `prisma/dev.db` write.***
*Two defects caught in my own instrument pre-ship: the marginal-dollar CI divided a PnL interval by a
fixed notional (understates the interval exactly where big-PnL and big-notional markets coincide — it
does here), and the cap-ladder delta CI bootstrapped kept-minus-dropped instead of minus-dropped, which
reported an interval that did not contain its own point estimate. Both fixed before any number above
was quoted; §AJ also now applies the `BOT_LIMITS` clamp, without which the 2.0× tier overstates by ~$1,300.*
