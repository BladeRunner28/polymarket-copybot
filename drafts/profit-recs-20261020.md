# Profit review — 2026-10-20

**Verdict: the book has no portfolio edge and one lane is sized for a game it isn't playing. The money isn't being left on the table by a threshold — it's being spent on 42% of one lane's notional in the only band whose ROI confidence interval excludes zero on the downside.**

Standing prompt asks where volume is allocated versus where edge is. Measured answer, trailing 90 days, deduped, market-clustered: volume is allocated almost exactly inverted to edge, and the lane that carries 99% of the open book is the lane with none of the rails.

---

## 0. Two contradictions in the standing baseline (reported, not resolved by preference)

**(a) The −3.92% take-all ROI is not reproducible from the files it names.**

| Source | rows | notional | ROI |
|---|---|---|---|
| `data/decision-dataset.csv` (to 09-12) | 3,516 | $35,382 | **+0.84%** net-entry, +2.88% equal-weight |
| `data/decision-dataset-forward-20261010.csv` (to 10-09) | 4,793 | $51,065 | **+12.14%** net-entry |
| `prisma/dev.db`, same window as (row 1), deduped | 3,483 | $35,004 | +2.19% gross |

I cannot reconstruct −3.92% [−5.86, −2.01] from either export. What I *can* reproduce is the **band sign structure**, which is what the recommendations actually rest on: cheap positive, 0.4–0.6 negative. So none of what follows depends on the level, only on the ordering — and the ordering holds on every cut I ran. Flagging it because a baseline nobody can re-derive is a baseline that will drift.

**(b) The dead zone's edge reproduces over 90 days, not over the v58+ era alone.**

Roadmap card *"Rec 3 — re-cut the band evidence on the v58+ era before ANY band-factor change"* applies to my own proposal, so I ran it: STANDARD 0.4–0.6 since 2026-09-19 is **−1.78% [−22.7%, +17.9%] on n=116** — not significant. The 90-day cut is −7.91% [−13.1%, −0.2%] on n=1,076 — significant. Both are honest; the recent half of the era does not confirm the loss rate, it just hasn't accumulated the legs. My decision rule below is written to be falsifiable on exactly this point.

**(c) The 2¢ fill improvement does not explain the C-200 lane's edge.** Every C-200 fill lands 1.62¢ under `intentPrice` (258 of 338 are exactly −2.0¢). Re-pricing at intent gives **+56.25% all-time, +76.9% over 14d** — the fill model contributes −$69 lifetime, −2.7pp. So the lane gap is real and not a sidecar artifact. I checked this before comparing lanes, per the standing caution.

---

## 1. EDGE ATTRIBUTION — right now, not historically

Trailing 90 days, deduped (first leg per bot|wallet|market|outcome), market-clustered bootstrap. `$`/cpday = profit per dollar per day of capital committed.

| Band | legs | notional | ROI | 95% CI | $/cpday |
|---|---|---|---|---|---|
| <0.20 | 422 | $9,058 | **+79.0%** | [+23.9, +137.6] | **0.185** |
| 0.2–0.4 | 739 | $8,699 | +12.5% | [−2.4, +26.4] | 0.045 |
| 0.4–0.6 | 1,807 | $16,737 | **−6.8%** | [−13.1, −0.2] | **−0.030** |
| 0.6–0.8 | 936 | $9,267 | +3.3% | [−1.9, +8.6] | 0.008 |
| 0.8–1.0 | 524 | $5,125 | −0.9% | [−5.2, +3.0] | −0.002 |
| **total** | 4,428 | $48,886 | +15.1% | [+3.4, +27.2] | 0.027 |

Two of five bands have a CI that excludes zero. One of them is the dead zone and it is the **largest** band by leg count — 41% of all legs, 34% of all notional. That is the textbook definition of volume allocated where it is comfortable: 0.4–0.6 is where books are widest, spreads tightest, and admission easiest.

The 30-day cut sharpens the velocity story and is the reason I care about hold time:

| Band | ROI 30d | hold (days) |
|---|---|---|
| <0.20 | +102.4% | 4.43 |
| 0.2–0.4 | +19.6% | 4.03 |
| 0.4–0.6 | −2.5% | 4.03 |
| 0.6–0.8 | +0.3% | **11.24** |
| 0.8–1.0 | −5.1% | **34.41** |

Edge and turnover are **inversely** ordered. The band that pays recycles in four days; the band that returns nothing takes thirty-four. Every dollar parked in ≥0.6 is a dollar earning ~0% for eight times as long as the dollar earning 102%.

### The concentration fact that reframes everything

90d deduped: **+$7,358.80 on $48,886.** Remove the 10 best bets out of 3,819 and the book is **−$446.50, i.e. −0.91%**.

- ex-top-1: +11.37%
- ex-top-3: +6.65%
- ex-top-5: +4.02%
- **ex-top-10: −0.91%**

And all-time, one market — `will-spain-win-the-2026-fifa-world-cup` YES — is **+$7,027.53 on $9,726 = 45% of the entire $15,560 all-time profit**.

Ten events carry the book. That is not a portfolio edge; it is a fat tail that has been mistaken for one, and every number in every report downstream of it (including "+12.56% all-time ROI") is a statement about ten coin flips.

---

## 2. CAPITAL VELOCITY — the answer to question (1)

**1,269 open legs, 357 distinct bets, 343 markets. $13,623 notional, MTM +$1,594.72, age-weighted 76.3 days.**

The headline comparison:

- Stranded capital-days in the open book: **1,033,886**
- Capital-days consumed by the **entire finished history** (11,461 legs, $123,845, all $15,560 of profit): **566,915**

The live book is holding **1.82× more capital-days than every trade the bot has ever completed**. It is a parking lot with a trading bot attached.

Age distribution of the open book — 80% of it is 60+ days old:

- >60d: 1,006 legs, $9,757, MTM +$1,347
- 30–60d: 240 legs, $3,489, MTM +$169
- 3–30d: 10 legs, $180
- <3d: 13 legs, $197

**Why:** the entire stale-exit / capital-recycling block is scoped `if (t.botId === "BANKROLL_200")` (`scripts/update-pnl.ts:240`). STANDARD exits only on **market resolution** or a **dead-slug 404 older than 24h** (`update-pnl.ts:148–156`, lane-agnostic). It has no time-based exit and no adverse exit — and, separately, no band skip, no per-market leg cap, no per-market notional cap, no per-wallet cap, no gross-exposure cap, no position-count cap, no Kelly. All fourteen `botId === "BANKROLL_200"` guards in `score-trades.ts` plus the one in `update-pnl.ts` mean STANDARD enters and waits for settlement, full stop.

So "1,287 positions at $13,788 against $7,899 cash" is not a leverage decision. It is the arithmetic consequence of the lane that carries 99% of the notional (`$13,552` vs C-200's `$71`) having been left outside every rail, and the lane that has all the rails using **1.85%** of its `$3,809` effective cap.

**Edge per capital-day, measured, trailing 30d:**

- C-200: `$7,115` notional, 1.70d hold → **$0.3818** per capital-day, +64.8% ROI
- STANDARD: `$5,862` notional, 13.89d hold → **$0.0114** per capital-day, +15.8% ROI

**33× apart.** Same notional throughput, 8× the working capital.

### What this does to the ladder

Run-rate on booked PnL: **$184.9/day (30d) → $142.4/day (14d) → $72.1/day (7d).** It is halving roughly every two weeks. Cheap-band leg flow is doing the same: 5.2 legs/day (30d) → 3.4 (14d) → 2.0 (7d).

At the cheap band's measured 79% ROI, $1,750/day needs **$2,215/day of cheap-band notional**. Today it runs **$101/day**. That is **22×**.

At the lane-blended 15% ROI it needs $11,667/day against $163/day — **72×**.

**The $1,750/day phase gate is not reachable by any adjustment of the current configuration.** Not by sizing, not by band factors, not by exits. It needs 22× the leg flow or 22× the clip, and those are blocked by two different things: supply (gates, closed) and fillability (unmodelled, thin books). I'd stop reporting it as a target and treat it as the 2027-01-02 prod anchor it already is in the roadmap. Reporting a gate you cannot mathematically reach is how a system talks itself into leverage.

---

## 3. SIZING VS EDGE CONCENTRATION — the answer to question (2)

### Is 96% of 10-18's PnL from one leg a sizing failure? No. It's a size-cap failure, and the leg was not clamped.

The leg: `swe-org-gais-2026-10-18-org`, entry 0.163, booked **+$512.29 = 90.1%** of that day's $568.46.

The same signal was copied by both lanes:

| Lane | clip | booked |
|---|---|---|
| STANDARD | $18 | +$91.09 |
| BANKROLL_200 | **$100** | **+$512.29** |

Identical market, identical signal, identical day. The entire difference is the clip: C-200's `kellyMaxSizeUsd=100` versus STANDARD's hard `clampPaperSize` ceiling of **$20**. Shadow on that day's realised rows:

- cap $18 → +$152.38 (notional $372)
- cap $50 → +$312.31
- no cap → +$568.46 (notional $458)

So the sizing model did **not** clamp the leg that paid. Kelly let it run to its own ceiling. Lowering `kellyMaxSizeUsd` would have destroyed 73% of the day's profit. That is the opposite of the hypothesis in the question, and it should be said plainly: **on 10-18 the concentration is a $100 clip firing on a 0.163 longshot, which is the system working as designed.**

### But the general question has a bad answer: STANDARD is band-blind.

Average clip by band, 90d deduped:

| Band | STANDARD | C-200 |
|---|---|---|
| <0.20 | $12.5 | **$30.4** |
| 0.2–0.4 | $12.8 | $10.7 |
| 0.4–0.6 | **$13.3** | $3.3 |
| 0.6–0.8 | $13.7 | $4.7 |
| 0.8–1.0 | $10.9 | $5.3 |

STANDARD books **$10.9–$13.7 in every band** — flat to within 26% whether the band returns +79% or −7%. It allocates capital in proportion to leg count, and leg count is highest in the dead zone. C-200 has the right shape: 9× more per leg in the cheap tail than in the dead zone.

The ruleset already contains the levers (`deadZoneSizeFactor`, `longshotSizeFactor`) — both set to **1.0** (neutralised at v41 so C-200's band map wouldn't double-apply). STANDARD reads the shared scorer, gets the 1.0s, and sizes flat. That is the mechanical origin of the whole pattern.

### The 4× cheap-tail shadow is a trap, and I'm reporting it as one

Naive shadow on the deduped book, holding total notional constant, edge-proportional weights (4 / 1.5 / 0.5 / 0.5 / 0):

- as traded: +$7,837.87 on $53,974 (**+14.5%**)
- edge-proportional: +$26,521.19 (**+49.1%**)
- edge-proportional with a **$50 per-leg cap: +$13,568.62** (+33.8%)

The cap destroys **70% of the gain**. Which means the apparent upside is concentrated in exactly the largest cheap-tail clips — the thinnest books — and it is entirely a fill assumption. I am not recommending it on this shadow.

### The one fillability number that actually settles it

Breakeven entry slippage per band (how much worse the fill can be before the band's edge is gone), 90d deduped, from realised hit rates and notional-weighted prices:

| Band | avg entry | breakeven entry | tolerance |
|---|---|---|---|
| <0.20 | 0.100 | **0.213** | **+112% worse fill** |
| 0.2–0.4 | 0.312 | 0.372 | +19% |
| 0.4–0.6 | 0.498 | — | **negative at the recorded price** |
| 0.6–0.8 | 0.687 | — | negative at the recorded price |
| 0.8–1.0 | 0.900 | — | negative at the recorded price |

This is the answer to the fillability question the prompt demands, and it inverts the usual framing. The cheap tail isn't "risky because thin" — its edge survives the entry price **doubling**. Everything at 0.4 and above has a tolerance of zero and is already underwater before any slippage at all. The comfortable volume isn't merely low-edge; it is edge that cannot pay for a fill.

Recorded L2 exists to test this rather than assume it: `data/l2/` (18GB, per-asset book) and `data/l2-events/` (`{ts, price, side, size, bestBid, bestAsk}` prints). Any recommendation adding size to thin books must be gated on that test, not on the shadow above.

---

## RECOMMENDATIONS — ranked by expected value

### #1 — Give STANDARD the band doctrine it never got (skip 0.4–0.6, ×2.5 below 0.20)

**Hypothesis.** STANDARD allocates by leg count, not edge, so 42.4% of its 90-day notional sits in 0.4–0.6 — the one band whose ROI CI excludes zero on the downside — and removing it plus up-weighting the cheap tail raises the lane's ROI without touching a single gate.

**Measurement.** Shadow re-cut of deduped STANDARD legs booked in the trailing 90d, split by band, market-clustered bootstrap; counterfactual = the same book with 0.4–0.6 removed and <0.20 sized ×2.5. Reads `PaperTrade` (status in closed|resolved, isDemo=0, first leg per bot|wallet|market|outcome) and reuses the existing `applyBandSizeFactor` / `isInBandRange` helpers. **Already run above:** skip alone takes the lane from **+2.13% → +9.52%** over 90d (dead zone = 42.4% of lane notional at −7.91%, −$1,132.83).

**Decision rule.** Apply the skip when, on ≥500 STANDARD dead-zone legs in the trailing 90 days, the market-clustered 95% CI upper bound is below 0. **Met:** 1,076 legs, −7.91%, upper bound −0.22%. Apply the ×2.5 cheap factor only when the band's breakeven entry slippage is ≥50% of price. **Met:** +112%.

**Refutation.** If the v58+-only re-cut reaches n≥300 legs with ROI > 0, the band is noise and the skip is a mistake — today's n=116 reads −1.78% [−22.7%, +17.9%], which is not enough to confirm *or* overrule, so this is the number to watch. For the ×2.5: if the L2 fill test shows realised fills on cheap admissions above **2× the recorded entry price**, the boost is a mirage and I revert it.

**Expected effect.** +$12.6/day from the skip (90d-evidenced, CI-backed); the cheap reweight is upside on top, bounded by fill. Realistic combined ceiling at current flow: **~+$30/day, ~$11k/yr**. Small in absolute terms — this is tax removal, not a ladder lever.

**Cost.** 3h (scope the band factor to STANDARD, add the RuleSet fields, shadow re-read before activation).

---

### #2 — Give STANDARD an exit rule (capital recycling)

**Hypothesis.** STANDARD holds to settlement because the entire stale-exit block is `botId === "BANKROLL_200"`-scoped, so its hold time is set by market term rather than by information decay — 34.4 days in ≥0.8 versus 4.4 in the cheap band over the last 30 days — and that is the direct cause of 1.03M stranded capital-days.

**Measurement.** Replay `staleExitDecision` at `staleExitHardHours=168` over deduped STANDARD legs, marking each at its first `MarketSnapshot` with `collectedAt ≥ openedAt+168h` (15.9M rows available). Output: booked PnL and capital-days versus hold-to-settlement, per band.

**Decision rule.** Adopt if capital-days fall ≥50% while booked PnL falls <$150 over 90d.

**Refutation.** If the 168h exit turns the ≥0.8 band's −0.91% into worse than **−8%** — i.e. it monetises noise on near-certainty tokens and pays fees to do it — the exit is wrong and hold-to-settlement stands.

**Expected effect.** 1.03M → ~0.15M capital-days. PnL ambiguous, ±$100/90d. **This is bought for solvency, not profit:** at live scale this book would be 1.7× gross against cash, which is unexecutable, and the ≥0.8 stock alone is $5,661 of notional holding **$469 of remaining upside against $5,661 of downside (≈12:1 against)** at 82 days old.

**Cost.** 3h.

**Why it's ranked below #1:** its expected PnL is ~zero and possibly negative. It earns its place on the risk axis, and honest EV ranking puts it second.

---

### #3 — Declare the portfolio edge unfalsified; freeze the clip size until it isn't

**Hypothesis.** The 90d profit is ten events, not an edge: ex-top-10 bets the book returns −0.91%, and 45% of all-time profit is one World Cup market. Therefore any scale-up now is a bet on a tail that has already happened.

**Measurement.** Leave-one-event-out on the deduped book with market-clustered bootstrap, tracked as a rolling statistic every 500 new legs. Reads `PaperTrade` only.

**Decision rule.** Treat the book as having a portfolio edge only when **ex-top-10 90d ROI > 0 on ≥4,000 deduped legs**. Until then, no clip increase above current ceilings (STANDARD $20, C-200 $100) and no lane reallocation on the strength of "+15%".

**Refutation.** If ex-top-10 ROI > 0 at 4,000 legs, the concentration is a fat tail on a real edge — and then the correct action is the opposite: raise the clip, and #1's cheap ×2.5 becomes the main event rather than a rounding error.

**Expected effect.** $0 direct. It is the guard on the single most expensive available mistake — raising size on a book whose edge is ten coin flips. At $1,750/day ambition and a 22× flow gap, size is the lever everyone will reach for.

**Cost.** 1h.

---

## IF YOU WEREN'T HERE

I would zero the STANDARD 0.4–0.6 band tonight — 42% of the lane's notional at −7.91% with a CI that excludes zero, and zero fill tolerance. It's Lane A (it changes what the bot risks), so I have proposed it and have not touched a RuleSet row.

## Lane note

**Lane B today: nothing.** I looked for a broken instrument and did not find one. The leg cap works (max 2 legs per bet on all 24 legs opened since v55; the 63-leg stacks are pre-v55 legacy), the dedupe works, the C-200 rails fire, the drift gate is not band-biased (the longshot tolerance is 8% of price versus 0.8% at mid — I hypothesised it starved the cheap tail and was wrong). The STANDARD gaps are **design scope, not defects**, so they are proposals, not repairs.

## What I'd watch next

The number that decides between #1 and #3 is STANDARD dead-zone ROI on the v58+ era as n grows past 300. It reads −1.78% at n=116. If it converges on the 90-day −7.91%, #1 is confirmed and the cheap-tail reweight is the next thing to price against L2. If it drifts to zero, the band was noise, the 90-day read was the July tail leaking in, and #3's concentration finding becomes the whole story.
