# Profit review 2026-11-21 — the book is 17 legs, and the cap is aimed at the wrong part of them

http://localhost:3013/drafts/profit-recs-20261121

**Instrument:** `scripts/profit-tenor.py` (**new**, committed with this doc; `--selftest` 9/9).
It is the first read in this repo that joins each leg's **tenor at entry** to its realised outcome
*and* to the sizing channel that booked it (Kelly path vs the $10 short-TTR lane), so a loss can be
attributed to a clock, a price or a clip instead of described as a band.
**Basis:** `PaperTrade` isDemo=0, `DecisionJournal.ruleSetVersion ≥ 68`, settled, deduped to the
first leg per `bot|wallet|market|outcome` — **487 legs / 397 markets / 24.3 days / $10,267 of
dollars at risk**. Cost = `simulatedPositionSize` = **dollars at risk** (never shares).
Tenor = `MarketSnapshot.timeToResolution` (hours) from the last snapshot at or before entry+15m;
0 unclassified. CIs are market-clustered bootstraps, 2,000 draws. DB `mode=ro`; no RuleSet read or
write.

**Basis warning, printed by §S14 and not resolved by it:** the book labels 230 of these legs
`unfilled` while still booking **+$370.8** of PnL on them. On the owned-only basis (261 legs,
$5,105) every cell below keeps its sign and gets *worse*: book −9.1%, 2-24h main path −38.4%,
cheap ≥$60 −41.5%, 7d+ −30.7%, 72h-7d +82.5%. Nothing here rests on the ambiguous legs.

---

## Verdict

**One 17-leg cell — cheap longshots resolving inside 24 hours — carries the entire loss
(−$1,091.7 on $1,700, −64.2%), and it is a subset of a tier whose other half is profitable
(+$113.8 on 15 legs). The approved 24h floor removes exactly that cell. The approved $25 clip cap
removes it too, and also guts the profitable half.**

Yesterday I ranked the clip cap first. That ranking is **withdrawn today**, not because the cap's
numbers moved but because the cross-tab now says where they live. Details in §2 and R2.

---

## 1. The tenor table (settled, 24.3 days)

| tenor at entry | legs | notional $ | PnL $ | ROI | $/1k capital-day |
|---|---:|---:|---:|---:|---:|
| 2-24h | 370 | 6,810 | **−636.9** | **−9.4%** | −181.0 |
| 1-7d | 87 | 1,960 | +758.0 | +38.7% | +402.9 |
| 7-30d | 17 | 707 | −29.3 | −4.1% | −21.0 |
| 30-90d | 7 | 436 | −153.4 | −35.2% | −93.0 |
| 90d+ | 6 | 354 | −60.4 | −17.1% | −53.4 |

- **76% of legs and 66% of the dollars go into the 2-24h window, and it loses.** CI on the cell's
  PnL is [−1,698, +468]; both halves of the window are negative (−1.5%, then −17.9%).
- The 7d+ cohort (30 legs, −$243.06, **CI [−528.7, −11.2]** — excludes zero) is the only
  sub-population with a negative CI that is not the cheap-clip cell.
- The book's whole realised rate is **−$12.73 per $1,000 of capital-day**, and the 2-24h window
  eats 37% of the capital-days at −$181.

## 2. The 17 legs (this is where the cap's premise dies)

Cross-tab of the cheap ≥$60 tier by tenor at entry:

| slice | legs | notional $ | PnL $ | ROI |
|---|---:|---:|---:|---:|
| cheap (px<0.20), clip ≥$60, **ttr 2-24h** | 17 | 1,700 | **−1,091.7** | **−64.2%** |
| cheap, clip ≥$60, **ttr ≥24h** | 15 | 1,500 | **+113.8** | **+7.6%** |
| whole cheap ≥$60 tier | 32 | 3,200 | −977.9 | −30.6% |

The "$100 clip loses money" finding that three briefs and two cards are built on is **one same-day
cell**: −$1,092 on 17 legs. The 15 cheap $100 clips that are *not* same-day made +$114. A cap
scoped to clips alone therefore does two things at once — it removes the leak, and it removes a
profit centre — which is why its measured value (+$26.02/day, §S12 arm B) is smaller than the leak
is.

Inside 2-24h, the clip split is not monotone; the $60+ tier is the whole of it:

| clip | legs | notional $ | PnL $ | ROI |
|---|---:|---:|---:|---:|
| <$15 | 249 | 2,235 | −23.8 | −1.1% |
| $15-30 | 91 | 1,725 | +191.3 | +11.1% |
| $60+ | 27 | 2,700 | **−1,044.7** | **−38.7%** |

## 3. The approved floor is scoped two ways, and only one of them is the code

`minTimeToResolutionHours` is a **global hard gate** (`src/lib/scoring/trade.ts:124`, one
`scoreTrade(..., rules)` call for every decision in `scripts/score-trades.ts:592`). The approved
change (2 → 24h) therefore binds **both lanes**. The pre-registered shadow that will decide the
flip (`data/ttr-floor-shadow.json`, 99 of 150 legs) measures **STANDARD only**.

Measured today, blocking the 2-24h window:

| population | book legs | book PnL | blocked legs | blocked $ | blocked PnL | kept ROI |
|---|---:|---:|---:|---:|---:|---:|
| all lanes | 487 | −121.9 | **370** | 6,810 | **−636.9** | **+14.9%** |
| STANDARD only | 129 | +214.9 | 87 | 748 | −58.8 | +34.3% |
| **BANKROLL_200 only** | 358 | −336.8 | **283** | **6,062** | **−578.1** | +9.1% |

The lane the shadow does not measure is **3.3× the leg count and 8× the dollars**, and it is the
more negative of the two (−9.5% vs −7.9%). The flip's true value is **+$26.2/day**, not the
STANDARD-only figure the shadow implies. The direction of bias from the scope error is
conservative — correcting it cannot turn a passing rule into a failing one — so this is a basis
correction, not a threshold change.

A price-conditional variant (block 2-24h **below 0.60**, keep same-day favourites) reads +$30.3/day
vs +$26.2 for the blanket floor. That extra $4/day rests on **+$98 across 146 legs**: noise. Do not
take the variant on the strength of it.

## 4. Every positive-looking cell is one wallet

| cell | legs | PnL $ | ROI | concentration |
|---|---:|---:|---:|---|
| short-TTR $10 channel | 239 | +257.2 | +9.4% | **best wallet = 100% of PnL**; ex-top-1 −$10.8 / −0.4% |
| 1-7d tenor | 87 | +758.0 | +38.7% | best wallet 87%; ex-top-3 +$21.4 (+1.2%) |
| 72h-7d main path | 42 | +912.4 | +81.8% | best wallet 72%; $675 of it from the cheap band |
| main path $15-30 clips | 105 | +266.2 | +13.8% | ex-top-3 +$50.7 (+2.7%), both halves positive |

The short-TTR channel is the sharpest case: it is the one channel that survives the same-day window
(+11.5% on 209 legs, −21.0% for the Kelly path in the identical window), and **one wallet is all of
it**. That is not a reason to kill it — a $10 lottery ticket with zero PnL is harmless — but it is
a reason to never size it up on this record.

## 5. The 419k capital-days are legacy, not a live constraint

The open book is 425 legs / $4,880, of which **358 legs / $3,841 sit in markets ≥90 days out**
(Barcelona 2026-27 UCL, MLS Cup, ETH-by-December, 2027 French presidential) with a −$434 booked
mark. That is **419,418 capital-days already carried against 9,577 for all settled history** — a
44× ratio that looks like the biggest finding in the book until you date it:

- **all 357 "older" open STANDARD legs are 105+ days old and predate the regime**;
- **68 legs opened in the last 30 days, all of them <24h.**

The bot has not admitted a long-dated position in a month. A 30-day tenor ceiling would block
**~0 legs/day** going forward — it is paperwork. The futures book is frozen inventory that will
settle over months; it inflates capital-day metrics and constrains nothing live. I am **not**
recommending a tenor exit for it either: the whole-book 168h replay already recorded NULL
(`standard-exit-rule-replay`), and the settled 90d+ sample is **6 legs**.

I also checked the opposite failure — that the open book is quietly holding *decided* markets that
never got booked. **It is not: 0 of 425 open legs sit on a venue-decided market.** 197 have a
conditionId the truth cache does not cover and 228 map to markets the cache still calls open, so
46% of the open book cannot be adjudicated offline, but none of it is a known settlement sitting
unbooked. That hypothesis is dead; do not spend another run on it.

## 6. Contradictions I am reporting, not resolving

- **Above-0.50 edge.** The standing baseline says 64.4% of acted trades sit above 0.50 "where edge
  is negative". Today's 2-24h cells at 0.60-0.80 read **+3.0%** (122 legs) and 0.80-1.00 **+5.5%**
  (24 legs), and the 72h-7d cell at 0.60-0.80 reads **+12.3%** (6 legs). Not enough to overturn a
  baseline measured on thousands of legs, but the two cannot both be quoted without naming the
  tenor cut. I use neither.
- **`fillStatus`.** 230 legs labelled `unfilled` carry +$370.8. Any ROI in this repo that filers on
  `realizedPnl` alone inherits that. My owned-only cut is printed beside every headline.
- **The cap card's own history.** `profit-c200-clip-cap-25` already recorded that lane-wide loses to
  band-scoped (+$102.9 vs +$172.1 on the 2026-11-15 read). Today reproduces the direction (arm A
  +$22.9/day vs arm B +$26.0/day) and adds the reason: the extra legs a lane-wide cap reaches
  include the profitable longer-tenor cheap clips.

---

## Recommendations

### R1 — Flip the 24h floor, and amend the read to both lanes before the flip
- **Hypothesis:** the same-day loss is not a STANDARD phenomenon and the gate is global, so the
  decision population must be both lanes; the flip is worth ~3× what the STANDARD-only shadow says.
- **Measurement:** `python3 scripts/profit-tenor.py` §S15 (block shadow by population) and §S6
  (the 2-24h cell under the knife). Reads `PaperTrade` + `MarketSnapshot`.
- **Decision rule:** flip when the **combined** 2-24h population has ≥150 settled legs AND its ROI
  is ≤ −3%. Measured: **370 legs, −9.4%, PnL −$636.9, both halves negative**.
- **Refutation:** combined 2-24h ROI ≥ +3% at ≥150 legs, or ≥0 on the owned-only basis. Owned-only
  is −38.4% (121 legs), so the refutation is not close — but it is the test.
- **Effect:** **+$26.2/day** (+$637 over the window; kept book +14.9% ROI on $3,457). Cost **0.5h**
  to amend the read; the rule write itself is the operator's one field.
- **Note:** this is the pre-registered n=150 rule, not a new one. It reaches n in ~17 days at the
  current 3.07 band-openings/day. Do **not** flip early on my numbers — amend the population, then
  let the trigger fire.

### R2 — Do not ship the $25 clip cap on top of the floor; its premise is the same 17 legs
- **Hypothesis:** the cap's measured benefit is entirely the same-day cheap clips the floor already
  removes; after the floor the remaining cheap ≥$60 population is profitable, so the cap would
  destroy value and double-count +$26/day in the ladder plan.
- **Measurement:** §S15 overlap block — 17 legs (2-24h ∧ px<0.20 ∧ clip≥$60) = −$1,091.7; residual
  15 legs = **+$113.8 (+7.6%)**; §S12 arms A–G for the cap shadows.
- **Decision rule:** hold the cap while the residual (cheap, ≥$60, ttr ≥24h) has ROI ≥ 0 on ≥15
  legs. Measured: +7.6%.
- **Refutation:** a forward sample of ≥40 cheap ≥$50 clips at ttr ≥24h earning ≤ −10% → the cap
  earns its keep outside the same-day window and this recommendation is wrong.
- **Effect:** avoids cutting ~$114 of profitable risk to ~$30 (−$85 over the window) and stops a
  second +$26/day being booked for the same leak. Cost **0h**.

### R3 — Do not raise size on any of the three "positive" cells
- **Hypothesis:** the short-TTR channel (+9.4%), the 1-7d tenor (+38.7%) and the 72h-7d cell
  (+81.8%) are each one wallet's run, not channel edges; sizing up multiplies a tail.
- **Measurement:** §S6/§S11/§S13 knife blocks — ex-top-N, per-wallet share, halves.
- **Decision rule:** raise `shortTtrSizeUsd` (10) or the Kelly ceiling for 3-7d only when a cell's
  **ex-top-10** forward read is ≥ +3% on ≥200 legs. Measured ex-top-10: −17.5% / −17.2% / −10.6%.
- **Refutation:** 200 forward legs in any one of the three with ex-top-10 ≥ +3% → that cell is an
  edge and the size should go up.
- **Effect:** $0 today; it holds ~$2,500 of notional at current size instead of ~$6,000. Cost **0h**.

**Ranking:** R1 (the only measured dollar gain, and it is the rule already approved) → R2 (prevents
shipping the wrong instrument for the same leak) → R3 (the three temptations, all single-wallet).

## IF YOU WEREN'T HERE

Flip the 24h floor on the **two-lane** read (+$26.2/day, 370 legs, −9.4%, both halves negative) and
do **not** ship the clip cap after it — the cap's entire case is 17 same-day cheap legs that the
floor removes, and the 15 cheap clips it would still reach made +$113.8. One fix, correctly aimed,
beats two that overlap.

---

*Lane B only: new read-only instrument committed with this doc; roadmap cards added for the floor
scope correction and the cap withdrawal. No RuleSet read or write, no prisma write, DB `mode=ro`.
Report-only on anything that changes a decision or a size.*
