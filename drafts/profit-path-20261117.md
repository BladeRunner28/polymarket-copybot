# Path to profitability — CopyBot and the ML lane, across prediction venues

**Date:** 2026-11-17 · **Status:** research, nothing applied · **Instrument:** `scripts/profit-path-research.py`
(committed with this doc — every number here re-runs from it)

Basis for every figure: cost = `simulatedPositionSize` (**dollars at risk**, not notional);
PnL = `realizedPnl` where `status IN ('closed','resolved')` (TR-15 OR), `isDemo=0`;
dedupe = first leg per (botId, walletAddress, marketId, outcome); label = `realizedPnl > 0`
(a PnL label, **not** the market outcome); clock = entry vintage, never settlement date;
CI = market-clustered bootstrap (resample markets, not legs).

---

## The question, stated plainly

The user's premise — *"we are chasing profit that isn't really there"* — is correct as a description
of the accounting, and this doc tests it rather than assuming it. Two questions:

1. On the class of leg we can **prove** we held, does the book make money?
2. If not there, is a profit pool visible on **any** venue we can measure?

## Finding 1 — the profit is entirely in legs with no fill evidence

C-200 by fill class, all time:

| fill class | legs | at risk | PnL | ROI |
|---|---|---|---|---|
| filled (provable) | 278 | $4,205 | **−$807** | **−19.2%** |
| unfilled (never traded) | 532 | $8,242 | +$2,270 | +27.5% |
| NULL (never adjudicated) | 1,368 | $11,830 | +$4,364 | +36.9% |

STANDARD: 3,725 legs, **0% adjudicated**, +$1,446 (+3.2%).

By vertical, all settled legs both lanes (better powered, n=5,903):

| vertical | legs | cost | PnL | ROI | of which fill-confirmed |
|---|---|---|---|---|---|
| question (`will`/`highest`/`lowest`/`elon`) | 3,018 | $36,058 | **+$6,382** | +17.7% | 58 legs, **−$773** |
| mma | 84 | $924 | +$822 | +88.9% | 15 legs, −$88 |
| football/soccer | 665 | $8,086 | +$766 | +9.5% | 51 legs, +$565 |
| tennis | 317 | $4,058 | +$664 | +16.4% | 7 legs, +$576 |
| basketball | 263 | $3,565 | −$276 | −7.7% | 44 legs, −$278 |
| esports | 789 | $9,074 | **−$1,032** | −11.4% | 66 legs, −$754 |

**The tension is the finding.** Question markets carry the entire +$6,382 on the full book — and
lose −$773 on the 58 legs of that class we can actually prove. That is not a contradiction to
explain away; it is the measurement the book currently cannot resolve, because the lane that trades
most of it (STANDARD) has **no fill adjudication at all**.

## Finding 2 — the loss concentrates in two decisions, not in the forecasts

Fill-confirmed, by clip size:

| clip | legs | at risk | PnL | ROI | win% vs breakeven |
|---|---|---|---|---|---|
| <$18 | 240 | $1,755 | −$90 | −5.1% | 44.2 vs 46.4 |
| $18–39 | 15 | $300 | −$96 | −32.0% | 6.7 vs 10.0 |
| **$100** | **20** | **$2,000** | **−$510** | **−25.5%** | 10.0 vs 14.1 |

**20 legs carry $510 of the $807 filled loss (63%).** The earlier paid-up-entry read points the same
way: 88 legs that paid ≥2c above the market returned −41.6%, CI [−65.6, −10.9]; stripping the
249 paid-up legs moves the book from −1.9% to **+5.5%**.

Market-clustered CI on the filled class: **−19.2%, CI [−54.0, +27.8]** (n=278, 258 ex-$100).
It spans zero. The honest statement is *"the point estimate is negative and underpowered"*, not
*"the filled class is proven to lose"* — which is exactly why the next step is more adjudication,
not a new rule.

## Finding 3 — the cross-venue inventory

| venue / path | can we play it? | verdict | evidence |
|---|---|---|---|
| Polymarket copy | yes | loses on the provable class | −19.2% filled; +$6,634 in unverified fills |
| Kalshi copy | **no, permanently** | no wallet attribution exists | keyless surface publishes no wallet identity |
| Kalshi LIP (rewards) | yes | **empty right now** | **0 of 7,608** live/upcoming programs clear $0.0131/contract-hour; max live ceiling **0.00446**, ~3x below the gate |
| Kalshi maker | yes | available, unfilled question | maker fee **0** on standard series; 20.4M qualifying prints, 591 captured hours, pre-registered card |
| Polymarket maker | yes | the measured leak's mirror | paid-up legs −41.6%; maker-first captures that instead of paying it |
| cross-venue arb | marginal | 0.2–0.3% cross-listing | too thin to carry a lane |

The LIP numbers are decisive and closed: the historic feed shows 36.8% of 229,636 programs clearing
on ceiling, but **those are short-window programs (83% of ≤2h, 0.0% of >48h)** and the currently
live menu is **90% >48h windows**. The qualifying families (`KXCRYPTOLEAD15M`, `KXTTELITEMATCH`,
`KXTEMPMIAH`, 15-minute commodity/FX) are not on the live menu today.

## Finding 4 — why the ML lane has no headway

The bar is relative: beat price-only AUC by +0.0005. On the fit population (n=3,098):

| arm | AUC | delta vs price |
|---|---|---|
| entry_price (the comparator) | 0.7158 | — |
| detected_price | 0.7013 | −0.0145 |
| entry_timing_score | 0.5425 | −0.1734 |
| copy_score | 0.5237 | −0.1922 |
| wallet_quality_score | 0.5132 | −0.2026 |
| thesis_score | 0.4830 | **−0.2328** |

Two arms are **below 0.5** — anti-predictive. Nothing clears the bar, so nothing can promote.

The observe lane (5,766 settled observations / 1,752 markets, venue-truth settled, status
`NOT_ESTABLISHED`) says the same thing more strongly: **all five quintiles lose money net of cost**
(−9.46, −6.58, −2.96, −7.27, −5.18%), including the top quintile winning 76.6% of the time, and
**0 of 15 nominal tests hit** against 0.75 expected by chance.

That is not a stalled lane. It is a lane correctly reporting that **win-probability has no value
after cost, because the price already contains it.**

---

## The path — ranked, each with what would refute it

### 1. Convert entry from taker to maker (Lane A, the largest measured lever)

Every profitable-looking population in this book loses on the legs that crossed the spread. The
paid-up cohort is −41.6% while the at-or-better cohort is +5.5%, on the same signals. That is an
execution defect with a known size, not a forecasting problem.

- **Hypothesis:** crossing the spread is the single largest cost in the book, and resting at or
  inside the mid converts that cost into either a better entry or no trade.
- **Measurement:** shadow-rest the current dispatch at mid (no fill assumption beyond the recorder's
  own coverage), and compare per-band ROI against the booked entries on the same legs.
- **Decision rule:** if the shadow-rested cohort beats the crossed cohort by ≥5pp ROI on ≥200 legs
  with a market-clustered CI excluding zero, ship it as the default dispatch mode.
- **Refuted by:** the shadow-rested cohort failing to reach 200 legs in 30 days (i.e. the fill rate
  is too low for the strategy to exist), which is itself a decisive answer.

### 2. Extend fill adjudication to STANDARD and to the question-market class (Lane B instrument + Lane A read)

The book's profit claim is unresolvable today because the class that carries it is 0% adjudicated.
This is the cheapest possible way to find out whether the +$6,382 is real.

- **Hypothesis:** the question-market profit survives adjudication, or it does not — and we cannot
  currently tell.
- **Measurement:** run the existing booth logic over STANDARD's book (currently 0% coverage vs
  C-200's 96–99%).
- **Decision rule:** if ≥60% of the question-market legs tape-out as filled at non-negative ROI,
  the profit is real and the ladder may credit it. Otherwise it is written off permanently.
- **Refuted by:** an adjudicated ROI that is non-negative — which would mean the "phantom" framing
  was wrong and the profit was real.

### 3. Cap the $100 clip on the lane where it is now provably losing (Lane A, immediate)

20 filled legs, −$510, 63% of the filled loss. This is the smallest, most certain change available.

- **Refuted by:** a forward 40-leg $100-tier sample earning ≥ the sub-$40 tiers.

### 4. Re-point the ML objective from outcome to execution (Lane A design)

Predicting the outcome is predicting the price — 0/15 hits, every arm ≤ price, two below 0.5.
The data that is *not* already in the price is the fill and adverse-selection surface: we hold
20.4M Kalshi prints, an L2 recorder, and a fill tape. An ML lane that predicts **"would this quote
fill, and if it fills am I adversely selected"** has a target that is not a restatement of price.

- **Refuted by:** a fill/adverse-selection model that cannot beat a constant fill-rate baseline on
  held-out data — in which case the ML lane should be retired rather than re-pointed.

### 5. Do not build a Kalshi LIP lane today (0h)

0 of 7,608 live programs clear the gate; max live ceiling is 3x below it. The path reopens only if
the short-window families (`≤2h`) return to the live menu, and the existing `lip-ledger.py` re-reads
that automatically. There is nothing to build now.

---

## What I would stop doing

**Reading the daily PnL as a trend.** Over the last month the daily series moved with fill-adjudication
coverage (0% → 11% → 99% of C-200 legs), not with the strategy. The one stable signal in it — the
fill-confirmed class — has been negative throughout. A trend read off a number whose *definition*
changed underneath it is not a measurement.

**Treating prediction accuracy as the product.** Across 5,903 settled legs and 5,766 ML
observations, no measured population shows a net-of-cost edge that survives being checked for
whether it actually filled. The provable money is in execution and position sizing; the unprovable
money is in fills nobody verified.

## Also worth stating

Prediction-market universe considered: Polymarket and Kalshi are the only two this stack is
instrumented for (tape, shadow arms, LIP feed, cross-venue samplers). **PredictIt** is US-politics
only with position caps; **Betfair/Smarkets** are real exchanges but fee-bearing and outside the
current keyless surface; **Manifold** is play money; **Limitless / ForecastEx / Novig** would each be
a new build with no data on disk. Nothing in this analysis generalises to them without the same
three measurements — provable fills, maker-vs-taker cost, and a reward schedule that clears its gate.
