# STANDARD exit rule — the 168h replay, run and priced

**Card:** `standard-exit-rule-replay` (`t_fe85261a`, approvals id `apr-standard-exit-rule-replay`) · **Lane A — proposal only, nothing applied**
**Instrument:** `scripts/standard-168h-replay.py` (new, read-only) + the already-committed `profit-velocity.py:ground_truth_stop()`
**Run:** `python3 scripts/standard-168h-replay.py` · 2026-11-12 · RuleSet **v72** (live) · DB read via `mode=ro`
**Measured against:** the card's own pre-registered rule — *adopt when capital-days fall ≥50% while booked PnL falls <$150 over 90d.*

---

## Verdict in one line

**DO NOT ADOPT the 168h exit.** Capital-days fall 78.3% (rule met) but booked PnL falls **−$762.62** (rule failed) — and the loss is not noise-spread: a 24h or 72h cut costs **−$12,438 / −$12,623**, because **any calendar cut on this book is a stop on the cheap longshots that carry the lane's edge** (<0.20 band: −$1,082 alone).

The one scope that passes the rule on paper (**entry ≥0.60**, +$62.90) passes by an amount smaller than its own confidence interval (±$1,600) and is the exact scope that, when actually executed on 2026-10-24, cost **−$831.70**. A ≥50%-capital-days rule cannot be met by a PnL number it cannot tell apart from zero.

---

## 1. The premise: reproduced, then shown to have been already (partly) fixed and never as bad as stated

Reconstructing the open book **as of 2026-10-20** from `openedAt / closedAt / resolvedAt` (all lanes, `isDemo=0`):

| | card claimed | re-measured | verdict |
|---|---:|---:|---|
| open legs | 1,269 | **1,261** | reproduces (−0.6%) |
| distinct bets (market+outcome) | 357 | **352** | reproduces |
| open notional | $13,623 | **$13,510** | reproduces |
| weighted age | 76.3 d | **75.9 d** | reproduces |
| open capital-days | 1,033,886 | **1,025,358** | reproduces |
| *finished-history capital-days* | *566,915* | **1,349,228** (all-lane) / 381,669 (resolved-only) | **DOES NOT REPRODUCE** |

So the "live book holds **1.8x** more capital-days than every trade ever completed" clause is **withdrawn**: on the same basis the open book held **0.76x** the finished history, not 1.8x. Nothing printed here lands on 566,915 (C-200 finished = 49,041; STANDARD finished = 1,300,188; resolved-only = 381,669). The defect was real; its stated magnitude was not.

**What has changed since 2026-10-20** (this matters, because the card was written before two rules landed on it):

| | 2026-10-20 | today | |
|---|---:|---:|---|
| open legs (all lanes) | 1,261 | **402** (391 STANDARD) | −68% |
| distinct bets | 352 | **91** | −74% |
| open notional | $13,510 | **$4,745** | −65% |
| open capital-days | 1,025,358 | **401,108** | −61% |

- **v66** (approved 2026-10-23) armed `standardStaleExitHours=168, standardStaleExitBandMin=0.60` — STANDARD's first stale exit. It fired once (2026-10-24) on 701 legs / $7,321.20.
- **v70** (approved 2026-10-29) set it back to `0`, on the measurement that its settled subset cost −$831.70 (one market −$807.01; ex-top-10 −$0.39), and on the premise that STANDARD has no notional cap and its leg cap was never binding.
- Live v72: `standardStaleExitHours=0`, `standardStaleExitBandMin=0.6`, `standardMaxOpenPositions=1300`, `staleExitHardHours=168` (C-200 only), `standardSkipBandRange="0.4-0.6"`, `standardMaxEntryPrice=0.85`.

So this card's first finding — *"STANDARD has no time exit"* — was true on 2026-10-20, **was fixed on 10-23, and was retired on 10-29**. What is still genuinely open is the question the card actually asks: *what does a 168h hard exit do to the whole STANDARD book?* That had never been measured across all bands and all legs. It is now.

---

## 2. The replay

**Arms.** A (hold) = what each leg actually did: `realizedPnl` on closed/resolved, `unrealizedPnl` on open. B (168h) = close at the **first stored mark at or after `openedAt + 168h`**, only for legs still open then; a leg that exited earlier is untouched by the rule.

**Price source.** `PnlSnapshot` — one row per leg per hourly mark, stamped by `priceForOutcome()` at mark time, so **label-correct by construction**. `MarketSnapshot.yesPrice/noPrice` are positional and are used only as the cross-check (below).

**Coverage:** 10,381 of 10,396 STANDARD legs priceable (**99.9%**); 15 legs excluded and named (9 with no mark at all, 3 marker gaps >12h, 3 open past the horizon with no later mark). Median mark lag at the horizon: **0.6h**.

### 2.1 All legs — the headline

| cohort | legs | fired | $ notional | hold (A) | 168h (B) | **B−A** | mkt-clustered 95% CI |
|---|---:|---:|---:|---:|---:|---:|---|
| **ALL** | 10,381 | 26% | $119,300 | +$9,288 | +$8,526 | **−$762.62** | [−5,682, +3,628] |
| open | 391 | 95% | $4,318 | −$19 | −$176 | −$157.07 | [−1,405, +1,000] |
| closed | 7,356 | 25% | $78,289 | +$1,595 | +$1,603 | +$8.22 | [−2,641, +2,611] |
| resolved | 2,634 | 20% | $36,712 | +$7,712 | +$7,098 | −$613.77 | [−3,974, +2,362] |

Capital-days: **1,698,890 → 369,225 (−78.3%)**. The rule's first half is met with room to spare; the second half is where it dies.

### 2.2 Settlement truth — the only arm that is not a mark

Legs the rule would have stopped **and** that have since settled (518 legs, 149 markets, $6,125 notional):

| | $ | % of notional |
|---|---:|---:|
| hold to settlement | **+1,435.73** | +23.44% |
| 168h exit at mark | **+821.96** | +13.42% |
| **exit alpha (B−A)** | **−613.77** | **−10.02%** |
| CI | [−4,326, +2,276] | |
| ex-3-worst-3-best markets | **+370** | |

Marks at 168h are, on average, **unbiased** against settlement (mean `mark − settle` = −0.009; mean |error| 0.326) — so the loss is not a stale-mark artifact: **selling at 7 days forfeits about 10pp of a +23% hold return**, concentrated in the cheap band.

### 2.3 The band map — and it is the inverse of what the live code comment says

| entry band | legs | fired | $ ntl | **B−A** | % ntl | CI |
|---|---:|---:|---:|---:|---:|---|
| <0.20 | 786 | 56% | $8,800 | **−1,082** | −12.3% | [−4,854, +2,080] |
| 0.20–0.40 | 1,336 | 18% | $16,100 | **+819** | +5.1% | [−588, +2,724] |
| 0.40–0.60 | 3,811 | 7% | $48,000 | **−562** | −1.2% | [−1,511, +240] |
| 0.60–0.80 | 1,746 | 20% | $20,900 | −39 | −0.2% | [−838, +1,112] |
| 0.80–1.00 | 2,702 | 53% | $25,600 | +102 | +0.4% | [−787, +1,155] |
| **scope ≥0.60 (v66)** | 4,448 | 40% | $46,500 | **+63** | +0.1% | [−1,105, +1,608] |
| scope <0.60 | 5,933 | 16% | $72,800 | **−826** | −1.1% | [−5,072, +3,093] |

**The live code comment is wrong-signed on the band that matters.** `src/lib/rules.ts` justifies the ≥0.60 scope with *"the same stop at 0.20-0.40 **DESTROYS $1,064** on 135 legs"*. Measured today, by the same committed instrument (`profit-velocity.py:ground_truth_stop`, no changes), on settled legs:

| band | n | hold | 168h | delta | CI (% ntl) | ex-top-10 |
|---|---:|---:|---:|---:|---|---:|
| <0.20 | 100 | +$1,722 | +$333 | **−$1,389** | [−323%, +97%] | −$559 |
| **0.20–0.40** | 107 | −$1,008 | +$98 | **+$1,106** | **[+28%, +107%]** | **+$1,211** |
| 0.40–0.60 | 96 | +$382 | −$29 | −$411 | [−82%, +20%] | −$222 |
| 0.60–0.80 | 35 | +$31 | +$5 | −$26 | [−23%, +26%] | +$38 |
| 0.80–1.00 | 100 | −$111 | −$18 | +$93 | [−7%, +32%] | +$133 |

The 0.20–0.40 figure is **+$1,106 on 107 legs, CI excluding zero, stronger ex-top-10** — the opposite sign, and the "135 legs" in that comment is the ≥0.60 row's own n in this very table. Two independent price sources agree on the sign (PnlSnapshot +$1,122 vs MarketSnapshot +$1,106 on the same 107 legs), so this is not the positional-price defect.

What that means mechanically: in 0.20–0.40, a leg that has not resolved within 7 days **wins only 6% of the time** and loses **−79.3% held to settlement**; a 168h stop keeps **+7.7%**. The time stop in that band is a **loser filter**, not a capital recycler — and the first-best fix for a band that loses 79% held is to *not buy it*, which is an admission question, not an exit one.

### 2.4 Horizon — 168h is not a special number, and the cheap band is why

| horizon | legs fired | capital-days cut | Δ all | Δ ≥0.60 | Δ <0.60 | Δ resolved | CI |
|---|---:|---:|---:|---:|---:|---:|---|
| 24h | 6,510 | −95.3% | −12,438 | +117 | −12,555 | −7,936 | [−29,856, −1,637] |
| 72h | 4,763 | −86.3% | −12,623 | +371 | −12,995 | −8,317 | [−28,436, −2,434] |
| **168h** | 2,710 | −78.3% | **−763** | +63 | −826 | −614 | [−5,565, +3,692] |
| 336h | 2,031 | −67.9% | −1,416 | +219 | −1,635 | −900 | [−6,093, +3,075] |
| 720h | 1,647 | −49.7% | −1,089 | +224 | −1,313 | −717 | [−5,106, +3,109] |
| 1,440h | 1,234 | −23.0% | +1,408 | −30 | +1,439 | +1,453 | [−617, +4,552] |

The sign is governed by the cheap bands until the cut is so late (60 days) that it no longer binds. That is the same (1−p)/p arithmetic the code comment already states: **a time stop cannot be applied to a lottery ticket.**

---

## 3. The card's decision rule, applied as written

| population | Δ capital-days | Δ booked PnL | cd ≥50% | PnL > −$150 | verdict |
|---|---:|---:|---|---|---|
| whole book (10,381 legs) | −78.3% | −$762.62 | yes | **NO** | **DO NOT ADOPT** |
| fired legs only (2,710) | −87.1% | −$762.62 | yes | **NO** | DO NOT ADOPT |
| fired, exited in last 90d (1,916) | −89.8% | **−$1,585.54** | yes | **NO** | DO NOT ADOPT |
| open book, first tick (391) | −92.7% | −$157.07 | yes | **NO** (by $7) | DO NOT ADOPT |
| scope entry ≥0.60 (4,448) | −79.4% | **+$62.90** | yes | yes | **ADOPT on the letter of the rule** |
| scope entry <0.60 (5,933) | −77.0% | −$825.52 | yes | **NO** | DO NOT ADOPT |

Per band (fired legs): `<0.20` DO NOT ADOPT (−$1,082); **`0.20–0.40` ADOPT (+$819)**; `0.40–0.60` DO NOT ADOPT (−$562); `0.60–0.80` ADOPT (−$39); `0.80–1.00` ADOPT (+$102).

**Why I do not recommend acting on the two passing scopes.** The ≥0.60 pass is **+$62.90 against a 95% CI of [−$1,105, +$1,608]** and a 90-day read of the same scope is negative in its settled subset (−$36 on $2,036). When the same scope was actually executed (v66, 2026-10-24) it cost **−$831.70**, dominated by one market that settled against the mark. A rule that resolves a $150 threshold with a ±$1,600 instrument has not resolved anything; adopting it would be deciding on the sign of a rounding error. The 0.20–0.40 pass is better supported (+$1,106, CI excludes zero) but it is a *loss-avoidance* rule sitting on top of an *admission* defect — and it needs code that does not exist (see §5).

**The card's pre-registered refutation did not fire, and the roadmap note's expectation was wrong.** Refutation was "if a 168h exit turns the ≥0.8 band from −1.23% to worse than −8%". Measured on ≥0.80: hold −$846 on $25,600 (**−3.3%**), 168h −$744 (**−2.9%**), Δ **+$102 (+0.4pp)**. The near-certainty band is *not* where the exit loses money; the cheap band is. The card's note predicted "the ≥0.8 band should turn sharply worse" — it did not. The null comes from the other direction entirely.

---

## 4. Is the freed capital worth anything? No — the resource is not scarce

| measure | value |
|---|---|
| `standardMaxOpenPositions` | 1,300 |
| STANDARD open now | 391 (**909 slots of headroom**) |
| open notional | $4,318 — the $1,000 gross cap is applied to C-200 only |
| leg blocks naming `open-position cap`, last 30d | **0** (v70's re-arm trigger is ≥20) |
| trailing 30d flow | 213 opens vs 389 resolutions = **−5.87 legs/day** |
| open book, mark-to-market | **−$18.57 (−0.43%)** on $4,318 |

And the capital is **committed, not stranded**: for all 391 open legs, from the latest `MarketSnapshot.timeToResolution` per market —

| market end date | legs | % legs | $ notional |
|---|---:|---:|---:|
| past (implied overdue) | 9 | **2.3%** | $81 (1.9%) |
| within 30d | 10 | 3% | $168 |
| 30–90d | 196 | 50% | $2,276 |
| 90–365d | 172 | 44% | $1,720 |
| >365d | 4 | 1% | $72 |

This independently reproduces the 2026-10-20 falsification note on the roadmap card (3.6% overdue then, 2.3% now): **$3,996 of the $4,318 open notional (92.5%; 368 of 391 legs, 94%) sits in markets with a scheduled end between 30 and 365 days out.** A 168h exit would liquidate that book a quarter of the way into its own term, at the mark, before the events it is paying for have happened.

---

## 5. Options, ranked (nothing applied)

**1 — RECOMMENDED: no change to the exit rule.** Keep `standardStaleExitHours=0`. The whole-book exit fails the pre-registered rule by $613; the scoped version passes by less than its own error bar; the resource it frees is 909 idle slots the lane is not even refilling. This is a **recorded NULL**, and it should be recorded as such rather than re-litigated next window.

**2 — If the 0.20–0.40 bleed is to be attacked, attack it at ADMISSION, not exit.** The band's legs lose **−79.3% held to settlement** and win **6%** of the time when they survive a week. An exit rule captures **+$1,106** of a **−$1,008** bleed on 107 settled legs; not buying them captures the whole thing without mark risk, haircut, or a new rail. That is a *band skip / entry floor* question (`standardSkipBandRange` currently skips only `0.4-0.6`) and needs its own card, its own pricing, and its own approval — I have deliberately not priced it here.

**3 — Re-arm v66 exactly (`168h`, `entry ≥0.60`).** +$62.90 on 4,448 legs (CI [−1,105, +1,608]); the identical scope executed on 10-24 cost −$831.70. Not recommended.

**4 — Re-arm 168h scoped to 0.20–0.40.** The only scope with CI-excluding-zero support (+$1,106, ex-top-10 +$1,211). Costs a **code** change, not just a ruleset change: `standardStaleExitFires()` tests a floor only (`entry ≥ standardStaleExitBandMin`), so a 0.20–0.40 *window* needs a new `standardStaleExitBandMax` field + helper predicate + tests + `apply-v73`. Effort ~2h; earns less than option 2 for more moving parts. Do not do this before option 2 is decided.

---

## 6. Overridable flags (each carries the number that moves)

1. **Exit-rule verdict: DO NOT ADOPT** — whole book −$762.62; ≥0.60 scope +$62.90 inside a ±$1,600 CI. *Override to adopt anyway:* set `standardStaleExitHours=168` (band `0.60` already stored); the **first tick sells 371 of 391 open legs at current marks for ≈ −$157.07**, then ~2–3 legs/day thereafter. *Revert:* set the same field back to `0`.
2. **Band scope correction (a documentation/write-up change, no rule moves):** `src/lib/rules.ts`'s v66 comment says 0.20–0.40 "DESTROYS $1,064 on 135 legs"; measured today the same instrument reads **+$1,106 on 107 legs, CI [+28%,+107%]**. *Override: leave the comment as-is.* I did not edit it — a comment that carries a measurement is part of the rule's record and rewriting it is Lane A.
3. **Instrument committed:** `scripts/standard-168h-replay.py` is new, read-only, prints its own coverage. *Revert:* delete the file; nothing else references it.

---

## 7. Refutation of my own verdict — what would reopen this

- **Reopen if** the STANDARD leg cap starts binding: **≥20** `open-position cap` leg blocks in a 30-day window (v70's trigger, re-tested here: 0). Then capital-days become a real resource and the exit is worth re-pricing regardless of its alpha.
- **Reopen if** the open book's implied-overdue share exceeds ~10% of notional (now 1.9%): that would mean legs are genuinely stuck past their own end dates, which is a different defect.
- **Refuted today if** a 168h exit at ≥0.60 shows alpha outside [−$100, +$300] on ≥150 newly settled legs, or if 0.20–0.40's +$1,106 fails to reproduce on a forward cohort of ≥150 legs. Neither has been established.
- **Do not reopen on** "capital-days are high". That number is a property of instrument term, not of the exit rule (50% of open legs end in 30–90 days; 2.3% are overdue).

---

## 8. Method & limits

- Everything above is from `scripts/standard-168h-replay.py` (§S.1–S.9 of its stdout) plus an unchanged run of the committed `profit-velocity.py:ground_truth_stop()`. All reads are `mode=ro`; **no Prisma write, no RuleSet row, no `apply-vNN.ts` run, no merge to main.**
- Cross-check between the two instruments on 436 overlapping legs: median |PnlSnapshot mark − MarketSnapshot mark| = **$0.286**; sums $495.21 vs $389.41 — same order, different source, consistent sign on every band (§S.9).
- Arm B is a **mark-based** exit by construction (that is what the rule does); arm A on still-open legs is also a mark, so the open-book row is mark-vs-mark. The only truth-anchored comparison is §2.2 (518 settled legs).
- `closed` legs (7,356) include the v66 sweep and dead-slug 404 expiries; their B−A (+$8.22) is early-exit-vs-earlier-exit, not truth.
- Sample is one book over ~4 months with a regime break at the v66/v70 pair; the market-clustered CIs account for leg clustering but not for that regime change.
