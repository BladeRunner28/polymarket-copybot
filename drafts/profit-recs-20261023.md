# Profit review — 2026-10-23

**The book's biggest losing block is not a band, a wallet or a market. It is a CLOCK.**

STANDARD puts **40% of its finished notional into markets that resolve within 24 hours**, and that
block returns **−13.0% on 3,395 legs**, market-clustered CI **[−21.8, −4.0]**. Everything entered with
more than a day left earns **+24.7%**. The gate that should prevent this already exists and is set to
**2 hours**. One number, 2 → 24, is the highest-expectancy change available today.

The honest discount, stated up front: **76% of the loss sits in 0.40–0.60, which v63 already closed on
2026-10-20.** So the gross number is −$5,464 and the *marginal* number — what a floor adds on top of a
rule already live — is **−$1,303** all-time, **−$1,528** over 90d. I report both because only the second
one is a decision.

Reproduce: `python3 scripts/profit-velocity.py` → `data/profit-velocity-latest.txt` (§T–§Z4, §X2 are new
in this commit). Cost basis on every ROI line: `simulatedPositionSize` = dollars at risk, never shares.

---

## 1. The clock, measured

`§Z`, all lanes, TTL = hours remaining at the fill (last snapshot within 15 min of entry — a
decision-time variable, no lookahead; 11,335 of 11,495 finished legs priceable, 98.6%).

- **<6h** — 1,844 legs, $20,773, **−7.4%** · ex-top-10 **−19.2%**
- **6–24h** — 2,965 legs, $32,490, **−5.7%** · ex-top-10 **−13.5%**
- **1–3d** — 1,732 legs, $18,403, +7.2% · ex-top-10 −4.6%
- **3–7d** — 2,110 legs, $22,543, **+46.4%** CI [+11.8, +61.8] · ex-top-10 **+42.7%**
- **7–30d** — 1,357 legs, +20.5% · ex-top-10 −2.8%
- **30–90d** — 462 legs, +46.3% · ex-top-10 +14.5%
- **>90d** — 865 legs, +20.8% · ex-top-10 +12.9%

Reading it as a trader: **both short buckets are negative before the tail is cut and worse after** —
that is what a real negative edge looks like, because removing the 10 best legs from a genuinely
positive bucket should *lower* it, not deepen the loss. 3–7d is the only bucket that stays above +40%
once the tail is removed.

**On STANDARD, the split is stark** (`§Z3`): <24h **3,395 legs, $42,121, −$5,464 (−13.0%)** vs ≥24h
**5,455 legs, $60,519, +$14,932 (+24.7%)**. That is 38% of the lane's legs and 40% of its finished notional
earning a negative return while the other 60% carries the entire lane.

## 2. Why the clock is the right variable, not a proxy

Four checks, because every prior "finding" in this book has died on one of them (`§Z4`):

- **Not one market.** The 5 worst markets inside the short block total −$2,132; **ex-top-5-loss-markets
  the block is still −$3,332 on $39,987**. The losses are spread across a UCL match ($684), three CS2
  events, a tweet-count market, a tech-model market and MLB totals — none above $684.
- **Not one wallet.** The largest wallet in the block is 5.5% of its notional; **ex-top-3-wallets it is
  −$5,185 on $35,780 (−14.5%)** — worse, not better.
- **Not the skipped band wearing a hat.** Within *every* band, the short half is worse than the long half:
  <0.20 −60.4% vs +175.0% · 0.2–0.4 −3.5% vs +22.8% · 0.4–0.6 −20.5% vs +28.1% · 0.6–0.8 +1.4% vs +10.1%
  · 0.8–1.0 +3.7% vs −6.9%. The only two cells where short wins are flat (+1.4%, +3.7%) on 1,055 legs.
- **Not one month.** Short-block ROI Jul **−24.2%**, Aug **−5.0%**, Sep **−21.0%**, Oct +9.3% (n=82, a
  throttled fortnight — not evidence).

The mechanism is the first principle, not a story: a market with six hours left has no time for the
whale's information to become *our* information — it is already in the price we pay — and the payoff
retains only the spread. Copying is a bet on a **slow**-resolving informational edge. In the last hours
of a market we are not copying, we are paying rent on someone else's exit.

## 3. What is actually running, and what is already gated

- Live ruleset **v65**: `minTimeToResolutionHours = **2**`. The **code default is 12** — the live value has
  been 2 for at least the last eight rulesets (v58–v65). The lane has been buying 2-hour-old markets by
  configuration, not by accident of a dead gate.
- A **short-TTR lane** exists and is enabled (`shortTtrMaxHours 72`, `shortTtrMinHours 2`,
  `shortTtrMinCopyScore 35`, `size $10`, `drift 0.05`), journaled as *"Short-TTR lane: … daily PnL
  channel"*. It fires **only on C-200** (1,318 legs, +$2,165) and it **rescues itself from the TTL gate**
  (`trade.ts:239-247` rescues `"resolves in"` failures when lane-eligible), so a global floor does **not**
  touch it.

That is the clean part of this proposal: raising `minTimeToResolutionHours` to 24 hits the **STANDARD
regular funnel** and leaves the deliberately-built C-200 lane exactly as it is.

## 4. What I tried to break, and one thing I broke

**v63 survives its own audit — and gets stronger** (`§Y`). I suspected the 0.40–0.60 skip rested on a
dedupe artefact, because the all-legs all-time basis reads **+$3,109 (+6.73%)** against the deduped
**−6.42%** it cited. It is an artefact — of *one market*: `will-spain` alone is **+$6,700**, more than the
band's entire profit. In v63's own 90-day window the capital basis is **−11.04%** (first fills −6.51%,
adds −15.48%), i.e. **worse than the number the rule used**. v63 was right; I withdraw the suspicion.

**A standing claim does not survive**: the short-TTR lane was called *"our one profitable channel,
+$538.16"* (2026-09-13) and *"+$1,996"* (2026-10-09). All-time it is **+$2,165 on $7,450 — and
−$473 ex-top-10**. It is a ten-leg outcome, like everything else in C-200. Not a proposal to cut it;
a reason not to grow it.

## 5. Capital velocity — the number that makes the stop worth doing

`§U`:

- finished book: 11,495 legs, **568,546 capital-days**, +$15,598 → **+27.43 $/1k-cd**
- **open STANDARD: 1,255 legs, ~1.07M capital-days → 67.1% of ALL capital-time, at +1.80 $/1k-cd**
  (unrealised, DB mark; the capital-day figure grows with every hour, so read it as a level, not a constant)

Two-thirds of every dollar-day this system has ever held is parked in positions that STANDARD cannot
exit, returning 1/15th of the finished book's rate. That is the case for the 168h stop, stated in the
units that compound rather than in dollars.

## 6. The stop, tested against settlement truth — yesterday's #1 needs its number revised, not its scope

`§V`: 277 settled STANDARD legs on 85 markets resolved **more than 168h after entry** — exactly the legs
the rule would have touched. Hold arm = realised outcome (1.0 / 0.0), not a stale mark.

- **≥0.60 — 135 legs, $1,640: hold −$80, stop −$13, delta +$68 (4.1% of notional)**
- 0.8–1.0 — 100 legs, $1,162: hold −$111, stop −$18, **+$93**
- **0.6–0.8 — 35 legs: hold +$31 (+6.5%, 80% settled hit), stop +$5, delta −$26**
- 0.2–0.4 — 33 legs: hold −$229, stop −$11, **+$218**
- 0.4–0.6 — 33 legs: hold −$142, stop +$10, **+$153**
- **<0.40 — 109 legs, $1,299: hold +$1,744, stop +$294, delta −$1,450** (<0.20 alone: hold +224.6%,
  stop +34.7%, **−$1,669**)

So: **the exemption below 0.20 is confirmed on ground truth**, the ≥0.60 direction is confirmed but worth
**+$68, not the +$326–548 the open-book marks implied**, and 0.6–0.8 is where the stop *loses*. Yesterday's
refutation clause (c) — "if 0.6–0.8's hold-to-settlement turns positive on ≥150 new settled legs the stop
is selling recoveries" — has **fired in direction at n=35, and not at the 150 bar**.

I am not widening the scope to 0.2–1.0 on the strength of the settled test (+$371 there), because the
open-book replay says the opposite for 0.2–0.4 (−$1,341). Two populations, two counterfactuals, opposite
signs — that conflict is reported in §Contradictions, not resolved by picking the friendlier one.

---

# RECOMMENDATIONS

## #1 — Raise `minTimeToResolutionHours` from 2 to 24 on STANDARD. LANE A, proposed.

**Hypothesis.** Copying into a market that resolves within 24 hours has negative expected value because
the copied information is already in the price, so a maturity floor at entry raises realised PnL and
capital productivity without touching C-200's deliberate short-TTR lane.

**Measurement.** `scripts/profit-velocity.py` → `§Z` (TTL at entry, market-clustered CIs), `§Z3` (admission
path), `§Z4` (robustness), `§X2` (book-level effect). Reads `PaperTrade` + `MarketSnapshot.timeToResolution`
at the last snapshot ≤ entry+15min. Cost basis: dollars at risk.

- pooled STANDARD <24h: **3,395 legs, −$5,464, −13.0%, CI [−21.8, −4.0]**
- **marginal on top of v63** (bands v63 leaves open): **1,841 legs, $21,824, −$1,303 (−6.0%)**, CI
  [−18.3, +6.7]; 90d: **1,296 legs, $16,707, −$1,528 (−9.1%)**, CI [−23.3, +6.5]
- book effect (marginal): **+27.43 → +30.99 $/1k-cd**; implied capital for $5,000/day **$182,251 → $161,366**

**Decision rule.** Adopt when (i) the pooled block is CI-negative against zero — **met**, [−21.8, −4.0] —
(ii) the marginal block is negative in **both** the all-time and 90d windows — **met**, −6.0% / −9.1% —
and (iii) the worst case inside the marginal CI (+6.7% on $21,824 ≈ **−$1,462** if the rule is wrong)
is materially smaller than the measured gain (+$1,303). It is not — they are the same order — so
**adopt as a 14-day shadow first, flip live at 14 days unless the shadow is positive**. The
pre-committed bar is **shadow ROI ≥ +3% on ≥150 blocked legs**.

**Refutation.** Revert if any of: (a) the 14-day shadow of blocked short-TTL candidates returns **≥ +3%**
on ≥150 legs — then the block is priced fairly and the floor only removes flow; (b) the ≥0.6-1.0 cells of
the blocked block (currently +1.4% and +3.7% on 1,055 legs) widen to **≥ +10%** on ≥150 forward legs,
meaning the floor is cutting winners; (c) the 3–7d TTL bucket's ex-top-10 ROI falls below **0%** on 60d,
which would mean maturity is not the variable and the whole ladder is drift.

**Effect.** +$1,303 all-time / +$1,528 (90d) on the marginal basis; +13% book capital productivity.
It also stops adding to the stranded open book — short-TTL legs are the fastest-resolving, so this lowers
rather than raises the inflow that feeds the 67%-of-capital-time problem. **Cost: 1–2h** (one key,
plus the shadow marker reusing the `data/drift-shadow.jsonl` pattern).

**Fillability note, inverted:** this rule REMOVES volume, so no fill assumption is needed and no thin-book
boost is being justified. The risk is the opposite one — the block may contain good legs (it contains
1,055 flat ones) — and that is what refutation (b) measures.

## #2 — Carry 10-22's ≥0.60 stop forward, with its expected value revised down and its scope unchanged. LANE A, still proposed.

**Hypothesis.** A 168h hard-age stop applied only to STANDARD positions entered at ≥0.60 improves realised
PnL and releases stranded capital-time; the same stop below 0.20 destroys value.

**Measurement.** `§V` (settled-leg ground truth, this commit) + `§P` in `scripts/profit-band-report.py`
(open-book replay, committed 10-22). Settled: **+$68 on 135 legs (4.1% of notional)**, positive on both
mark bases; <0.20 **−$1,669**, exempt. `§U`: open STANDARD = **~1.07M capital-days, 67.1% of all
capital-time, +1.80 $/1k-cd** vs finished book +27.43.

**Decision rule.** The 10-22 rule stands as filed (≥0.60, positive on every basis, −81% of the ≥0.60
capital-days). Unchanged. What changes is the *reason*: **not the +$326–548, which the settled test cuts
to +$68 — the capital-time, which is 15× under-earning.**

**Refutation.** Withdraw if 0.6–0.8's hold-to-settlement return stays positive at **≥150 settled legs**
(it is +6.5% at n=35 today); or if the first 20 organically stopped legs realise worse than hold by
>1.0% of notional.

**Effect.** +$68 to +$326 one-off (revised down from +$326–548), **−81% of the ≥0.60 capital-days**.
**Cost: 2–3h.** Do **not** widen the scope to 0.2–0.4 on the settled test — see Contradiction 1.

## #3 — Nothing else today. Four dead ends, named so they are not re-proposed.

- **Reopen 0.40–0.60** — refuted harder than before: 90d capital basis **−11.04%**, adds −15.48%, and the
  all-time positive is one market (`will-spain` +$6,700 of +$3,109). v63 stays.
- **Cut or grow the C-200 short-TTR lane** — +$2,165 headline, **−$473 ex-top-10**. Not measurable at 10 legs.
- **Port the C-200 band map** — 10-22 §O: notional-neutral ex-top-10 **−$77**. Stays dead.
- **Per-market leg cap** — 10-22 §R: lanes disagree in sign. No cap is a repair.

**IF YOU WEREN'T HERE:** I would set `minTimeToResolutionHours` to 24 for the STANDARD funnel and start the
14-day shadow the same hour — because the finding is not the $1,303, it is that **the lane has been buying
markets with six hours left and calling it copying**, and the 3–7d bucket (+46.4%, +42.7% ex-top-10) is
where the same signal, given time, actually pays.

---

## Lane B (instrument, done in this commit — no bot behaviour touched)

`scripts/profit-velocity.py` (new, 871 lines incl. §T velocity, §U capital-days, §V settled-truth stop,
§W sizing headroom, §X implied capital, §Y dedupe-basis audit, §Z/Z3/Z4 TTL). Two defects found in my own
instrument before shipping: the category split (§Z2) is **unmeasurable** — `MarketSnapshot.category` is
populated on **24 rows of 15.9M** — so it now prints coverage and refuses to compute rather than printing
a blank table; and the first §X2 draft credited the floor with the *gross* −$5,464, which double-counts
v63, so it now prints gross and marginal side by side.

## Contradictions I am not resolving silently

1. **0.2–0.4 exit direction, third instalment.** 10-21: cuts beat settlement by **$258** (C-200 tickets).
   10-22: a 168h stop on open 0.20–0.40 loses **$1,341**. Today (settled STANDARD legs): the stop **gains
   $218** there. Three populations, three signs. The exemption in #2 below 0.20 rests on all three agreeing
   only on *that* cell. Nothing is proposed for 0.2–0.4 until one population has ≥150 settled legs.
2. **The short-TTR lane's status.** Called "our one profitable channel" twice in the record; re-measured
   today at −$473 ex-top-10. The headline never disputed, the robustness claim is withdrawn.
3. **What "the band is bad" means.** v63 was justified on a *deduped* basis (first fill per bet). The
   capital basis flips its sign all-time. I resolved it against my own suspicion — 90d capital basis is
   −11.04% — but the lesson generalises: **a dollar conclusion should not be drawn from a per-bet
   statistic**, and one market can carry a band.
4. **Fillability remains unmodelled** (standing caveat). #1 removes flow and #2 exits at marks; neither
   adds volume to thin books, so neither relies on a fill assumption. The 3–7d bucket that #1 points at
   *would* be a volume claim — which is why #1 gates at 24h and does not up-weight anything.
