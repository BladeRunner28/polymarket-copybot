http://localhost:3013/drafts/profit-recs-20261127

# Profit review — 2026-11-27

**The cheap band's edge is an artifact of the pre-v68 era. On the live era it is gone, and the book buys above its own hit rate in every band it still trades — while paying 0.83c LESS than the wallets it copies. The loss is not execution and not clip size: the copy source stopped clearing its own price.**

Instrument: `scripts/profit-band-report.py --v4` (§E1–E7, `--selftest-v4` 7/7), committed with this file. Cost basis = `simulatedPositionSize` = dollars at risk. Population: C-200, `ruleSetVersion` ≥ 68, 60 days, deduped per (bot|wallet|market|outcome) — **542 decided legs, 172 carried**, DB read 07:5x. CIs are cluster bootstraps, market- and wallet-clustered; **below 6 clusters the CI prints `n/a`** rather than an interval, because a bootstrap over four strategies describes which ones were drawn.

---

## 1. The cheap band's edge died at v68

This is the contradiction the record needs, and it re-prices every card that up-sizes the cheap band:

| era / base | legs | hit% | paid | edge | hit CI |
|---|---|---|---|---|---|
| **pre-v68** C-200 carried | 169 | 24.9 | 10.8c | **+14.0pp** | [18.3, 31.7] |
| **pre-v68** C-200 mixed | 228 | 23.7 | 10.7c | **+12.9pp** | [18.2, 29.4] |
| **v68+** C-200 carried | 34 | 11.8 | 13.4c | **−1.7pp** | [2.9, 23.5] |
| **v68+** C-200 mixed | 120 | 6.7 | 12.0c | **−5.4pp** | [2.5, 11.7] |

The standing "+5.4pp cheap-band edge" is the pre-v68 population (it reads +12.9pp there). On the era the bot actually runs, it is −5.4pp mixed / −1.7pp carried. The hit rate fell from ~25% to ~12% at a roughly constant 11–13c price.

**Two things follow, and they are different:**

- The λ̂ that funds the cheap band (`q ≈ 28%` for 0.00–0.20) was **not mis-specified — it went stale.** 24.9% was true on the population it was fitted on. Refitting on v68+ carried legs yields **q ≈ 12%**, which at a 12c ask gives f\* ≈ 0: the correct sizing for this band is *no size*, not a smaller clip.
- Every "cheap band is underpriced" card (λ̂ refit as written, longshot ladder, cheap up-size) is priced on a regime that ended. The refit is still the right instrument; its *scope* and its *expected output* were both wrong in the record.

## 2. Negative headroom in every band we still trade

For a BUY at price p the break-even price *is* the hit rate, so (hit − paid) is how many cents the fill can worsen before the edge is zero.

| band | n | hit% | paid | headroom | hit CI |
|---|---|---|---|---|---|
| 0.0–0.2 | 34 | 11.8 | 13.4c | **−1.7c** | [2.9, 23.5] |
| 0.2–0.4 | 72 | 26.4 | 30.8c | **−4.4c** | [16.7, 37.0] |
| 0.6–0.8 | 59 | 64.4 | 68.2c | **−3.8c** | [52.5, 76.3] |
| 0.8–1.0 | 7 | 100.0 | 86.4c | +13.6c | [100, 100] |

Three bands, same sign, none rescued by a CI. The favourite cell is 7 legs and 0 fills — a streak.

**And it is not our execution.** Same headroom at the copied wallet's own entry price:

| band | n | hit% | our px | wallet px | ours | **wallet** |
|---|---|---|---|---|---|---|
| 0.0–0.2 | 34 | 11.8 | 13.4c | 15.4c | −1.7c | **−3.6c** |
| 0.2–0.4 | 72 | 26.4 | 30.8c | 32.4c | −4.4c | **−6.0c** |
| 0.6–0.8 | 59 | 64.4 | 68.2c | 67.7c | −3.8c | **−3.3c** |
| **ALL** | **172** | **39.5** | **42.5c** | **43.3c** | | |

Copy cost = **−0.83c**: the fill model hands us the reversion price, *below* the wallet's. Every latency story in the record dies here (the drift gate already holds admitted legs to ≤0.4c, and its own shadow says the skipped flow is worth ~$0.02/signal). The wallet's own entry sat 3.3–6.0c above the outcome it got. Copying was not a worse version of a good trade; it was a clean execution of nothing.

## 3. The book trades 2.87 times a day

542 decided legs, $11,442 of intent, **$4,122 carried** (172 legs, 36.0%); 328 legs (60.5%) void-unfilled booking $0.00, 42 late-stamped, 18 unstamped. **2.87 positions/day, $68.70 of risk/day, mean carried clip $23.97.** At a 2% edge that is **$1.4/day**; at 20%, $13.7/day. The $1,750/day bar needs ~$87,500/day of risk at 2% — **1,274× the current flow.** No clip rule closes that.

---

## The denominator flatters us by 5.6×

- **Carried** (a position existed): 172 legs, $4,122, **−$677.49 = −16.44%**.
- **Mixed** (all decided, void legs at $0.00 in the denominator): 542 legs, $11,442, **−$316.24 = −2.92%**.

Every clip card in the queue was fitted on the second number. Everything below uses the first.

| tier | n | risk | P&L | ROI | wins | mkt CI | wallet CI | % of net |
|---|---|---|---|---|---|---|---|---|
| <$15 | 96 | $907 | −$57.57 | −6.3% | 43 | [−28.4, +17.2] | [−29.1, +10.6] | +8.5% |
| $15–30 | 52 | $965 | +$18.09 | +1.9% | 17 | [−45.1, +54.4] | [−37.9, +62.3] | −2.7% |
| $30–60 | 3 | $150 | −$2.36 | −1.6% | 2 | n/a | n/a | +0.3% |
| **≥$60** | **21** | **$2,100** | **−$635.65** | **−30.3%** | **6** | **[−76.4, +40.0]** | **[−83.4, +59.3]** | **+93.8%** |

## Every pending variant, priced on the same 172 legs

| variant (legs touched) | touched | delta $ | post-rule book | wallet CI |
|---|---|---|---|---|
| **block ≥$60, ttr 2–24h** | 12 | +$853.06 | **+6.01%** | [−26.8, +63.1] |
| cap ≥$60 at $18, 2–24h | 12 | +$699.51 | +0.70% | [−32.1, +55.0] |
| block px<0.20 & ≥$60 | 16 | +$722.14 | +1.77% | [−18.9, +18.4] |
| block ≥$60, any tenor | 21 | +$635.65 | −2.07% | [−21.9, +18.6] |
| cap px<0.20 at $25 (band card) | 34 | +$547.13 | −4.50% | [−30.2, +18.1] |
| cap px<0.20 at $18 | 34 | +$589.94 | −3.19% | [−27.5, +16.8] |
| **block px<0.20 (λ̂-refit proxy)** | 34 | +$662.44 | **−0.70%** | [−24.2, +15.4] |
| block ≥$60, ttr ≥24h | 9 | −$217.41 | −27.77% | [−59.4, +2.1] |

Three things this decides that the record has not:

- **Nothing in the queue produces a profitable book.** The most aggressive cheap-band intervention (block it entirely, the λ̂-refit proxy) reaches **−0.70%**. The best variant, +6.01%, is +$6 above breakeven on $2,922 and is **−13.35% ex-top-1** (one +$552.23 tennis leg at ttr 162.7h) and −22.18% ex-top-3. Every cap is worse than the block at the same scope.
- **The tenor scope is load-bearing on that one leg.** The long-dated ≥$60 cell is +$217.41; blocking all tenors makes the book worse.
- **The delta CI is degenerate and I am not quoting it as edge.** All 12 blocked legs are −100%, so any resample containing one is positive; the interval measures inclusion, not expectation. Yesterday's `[+622, +1666]` carries the same defect. Read the post-rule ROI column.

---

## Categories: the blacklist is the wrong lever

`c200Blacklist` holds cs2/lol/val/nfl/mls/itf/sea — all **zero** legs this window, so it binds. The obvious next move, "add nba/dota2/will", is wrong:

| cat (carried) | legs | wallets | ROI | market CI | wallet CI | top wallet |
|---|---|---|---|---|---|---|
| dota2 | 34 | 5 | −71.4% | [−90.8, −36.8] | **n/a** | **88.2%** |
| will | 24 | 6 | −50.3% | [−81.3, −1.8] | [−69.6, −32.8] | 33.8% |
| nba | 25 | 4 | −47.2% | [−76.1, −2.9] | **n/a** | 49.8% |

- **dota2 is one wallet** — `0x52b7fc8a…` (SimpleTony), 41 of 47 legs, −60%, whose **own short-TTR slice in the same category is +$33.60 at +13.2%**, and which is already off `track` (status `watch`, last leg 2026-11-18).
- **nba is the book's best wallet** (240 legs, +7.3% overall) at −8.1% inside one category; 4 strategies → no CI.
- **will survives clustering** only because it is 8 filled $100 legs at a 10% price; 0/8 at p=0.10 is p=0.43. And `will-` is a slug prefix, not a category — the field cannot bind on it.

---

## Recommendations (ranked by expected value)

### R1 — LANE A, propose. Ship the ≥$60 / ttr 2–24h **block** as an interim variance stop; close the rest of the clip queue.
- **Hypothesis:** removing the 12 carried legs of ≥$60 clips resolving in 2–24h turns the carried book from −16.44% to ≥0 and removes the only 93.8%-of-loss concentration.
- **Measurement:** `scripts/profit-band-report.py --v4` §E2–E3 on the 172 carried legs. Reproduces yesterday's 51-leg / $5,100 / −$991.40 cell exactly (see reconciliation); the 21 carried ≥$60 legs are its 16 `filled` + 5 `NULL` subset.
- **Decision rule:** apply if the post-rule book ≥ 0% and the block touches ≥10 carried legs (reads +6.01%, 12 legs). Block, not cap: the same scope capped at $18 reads +0.70%, and a $25 band cap reads −4.50%. Close `profit-c200-clip-cap-25` and `profit-residual-cheap-longdated-clip` as sizing instruments for this cell; amend (not close) the λ̂ card per R2.
- **Refutation:** 20 forward carried legs in the blocked class reading ≥0 → withdraw. **Or** the operator requiring a post-rule book that is positive ex-top-1: it is −13.35%, and no card in the queue clears that bar.
- **Expected effect:** +$853 realized losses avoided per 60d ≈ **+$14/day carried**; the durable effect is that daily P&L stops being three 13%-hit lottery tickets. **Cost: 1h** (field specced, default 0 = off).

### R2 — LANE A, propose. Amend the λ̂ refit card's SCOPE and its EXPECTED OUTPUT before the 2026-12-01 refit re-inflates the cheap clip.
- **Hypothesis:** the cheap band's λ̂ is stale, not mis-specified: fitted q≈28% matched a pre-v68 hit rate of 24.9%, and the live v68+ carried hit is 11.8% at a 13.4c price, so an era-restricted refit returns q≈12% and f\*≈0.
- **Measurement:** §E7 (era cut) + §E5 (headroom). Refit population = v68+ **carried** legs only, printed beside the pre-v68 table.
- **Decision rule:** refit on v68+ carried legs; if q comes back ≤14% at the band's mean price, set cheap-band size to the floor (the λ̂-refit proxy in §E3: blocking px<0.20 takes the carried book to −0.70%). Amend `profit-lambda-owned-population` to say so instead of "refit on owned legs" — as written it would still fund the band.
- **Refutation:** ≥150 v68+ carried cheap legs hitting ≥18% (i.e. within 5pp of the pre-v68 rate) → the regime did not break, the live shortfall is noise, and only R1 is justified.
- **Expected effect:** removes the −$662 cheap-band loss per 60d ≈ **+$11/day**, and it is the only variant that survives the next calibration refit. It creates **no** new profit: post-rule book −0.70%. **Cost: 2h.**

### R3 — LANE A, propose (0h). Do **not** add nba/dota2/will to `c200Blacklist`.
- **Hypothesis:** none of the three is a category effect; each is one or two strategies or the R1 clip cell.
- **Measurement:** §E4 both bases — dota2 88.2% of notional from one wallet (5 strategies, n/a), nba 4 strategies (n/a), will 8 filled legs of the clip cell.
- **Decision rule:** blacklist only at ≥40 carried legs, ≥6 wallets, wallet CI excluding zero, and no wallet >40% of notional. None clears all four.
- **Refutation:** a category clearing all four on forward data → blacklist it.
- **Expected effect:** keeps the +14.8% short-TTR dota2 flow; does not spend the one clean mechanism on a one-wallet artifact. **Cost: 0h.**

**Lane B, done in this commit:** `--v4` now prints carried vs mixed on every line (§E1), both cluster CIs with the k<6 guard (§E2/E4), the post-rule book beside the delta with the degenerate-delta warning (§E3), the source test (§E5) and the era cut (§E7). `--selftest-v4` 7/7, no DB.

---

## IF YOU WEREN'T HERE:

I would apply R1's field today — it is one reversible field and the only lever in the queue that removes a real dollar concentration — and I would stop writing cards that change the *size* of a bet. The book's problem is that the wallet set stopped clearing its own entry price at v68; the next real dollar is a selection project, not a RuleSet field.

---

## What I could not measure, stated as negatives

- **Wallet persistence is UNMEASURED on the live era** — 5 repeat wallets only. It gates every "copy a better wallet" proposal and needs ~8 weeks at 2.87 positions/day.
- **The 0.8–1.0 cell cannot be tested** (7 carried legs, 0/9 fill rate, +13.6c headroom on 7 legs). I am not proposing to open it: the entry-ceiling card already measured the skipped 0.85–0.90 pool at −7.6% (21 bets).
- **"Unfilled" mixes two classes.** 328 legs book $0.00 by design; 42 carry real P&L with no fill stamp (+$343.26 on $1,094). §E1 splits them; no downstream number should quote an "unfilled ROI" until the late-stamp class is resolved.
- **I did not re-test the exit rule** (carded Done 2026-11-22 on a measured +$922; nothing here contradicts it).

## Reconciliation with yesterday's brief

Yesterday's ≥$60 cell reproduces **exactly** — 51 legs, $5,100, −$991.40, −19.4% — but only on a **60-day** window; "29.3 days" was the era length, not the leg span, and the label made the sample look denser than it is. The carried subset is 21 legs. Separately, yesterday's +$39.02/day block value is **not** contradicted on dollars (+$853/60d here, same order) but its CI is degenerate and its post-rule book is negative ex-top-1; both statements belong on the card.
