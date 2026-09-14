SOURCE: https://raw.githubusercontent.com/sachacoemelck/polymarket-edge/main/README.md

# Polymarket Edge — Research Report

**Summary.** On resolved Polymarket Yes/No markets in 2025-2026, the
classical favorite-longshot bias hypothesis (longshots overpriced) is not
confirmed — instead, we observe a **reversed, statistically significant
pattern**: low-probability outcomes are slightly **underpriced**, favorites
slightly overpriced. This signal concentrates in the Sports/Politics
categories and in the most heavily-traded markets, it **survives** an
event-clustering robustness test, and its arithmetic edge remains
**positive net of measured fees and a spread proxy**. It is, however, **not
judged exploitable at scale**: the market depth available at the relevant
price level (~$11 per typical trade) is too thin to deploy meaningful
capital without execution itself destroying the edge.

## Research question and methodology

**Hypothesis tested**: does the favorite-longshot bias exist on resolved
Polymarket markets (2025-2026) — are outcomes priced at low probability
systematically overpriced? This bias is well documented on traditional
betting markets (horse racing, sports bookmakers): "longshots" tend to be
overpriced relative to their actual realization frequency, favorites
slightly underpriced. The goal was to check whether this bias shows up on
an on-chain prediction market with a different pricing mechanism (AMM /
CLOB order book), and, if confirmed, to assess whether it is exploitable net
of fees and execution costs.

**Data sources** (Dune, `polymarket_polygon` schema):
`market_details` (metadata and resolution), `market_prices_hourly` (hourly
price), `market_trades` (individual trades: price, amount, fee, maker/taker
side). The full schema exploration and the empirical verification of the
`outcome` column's semantics (per-market, not per-token — see below) are in
`queries/00_schema_exploration.md`.

**Steps**:

1. **Calibration** — each resolved outcome token is grouped into 10%
 implied-probability buckets (0-10%, 10-20%, ..., 90-100%), measured at
 T-7 before resolution; for each bucket, the average implied price is
 compared to the actual resolution frequency, with a binomial confidence
 interval (Wilson, 95%).
2. **Segmentation** — the calibration is redone by market category and by
 market volume tercile, to locate where any bias concentrates rather than
 averaging it over a heterogeneous universe.
3. **Robustness test** — tokens are not independent draws (a single
 real-world event often resolves several markets at once); the
 calibration of the most significant bucket is redone with an event-
 clustered confidence interval.
4. **Cost analysis** — the gross edge is netted of Polymarket fees
 (directly measured) and an effective spread proxy (in the absence of
 historical order-book data), to judge real-world exploitability.

## Project structure

```
polymarket-edge/
├── queries/
│ ├── 00_schema_exploration.md # Dune schema exploration + empirical verification
│ ├── 01_calibration.sql # Overall calibration (10 buckets, 95% CI)
│ ├── 02_calibration_by_category.sql # Calibration split by market category
│ ├── 03_calibration_by_volume_tercile.sql# Calibration split by volume tercile
│ ├── 04_cluster_robustness.sql # Event clustering (Sports/Politics, high tercile)
│ └── 05_cost_analysis.sql # Spread, Polymarket fees, depth (same scope)
├── src/
│ ├── build_calibration_results.py # Builds CSVs/charts from the Dune outputs
│ ├── cluster_robustness_bin0.py # Naive vs per-event vs cluster-bootstrap CI
│ └── cost_analysis_bin0.py # Net edge = gross - fees - spread
├── notebooks/ # Exploration notebooks (empty at this stage)
├── results/
│ ├── calibration_overall.csv / .png # Overall calibration + binomial CIs
│ ├── calibration_by_category.csv / .png # Calibration by category (small multiples)
│ ├── calibration_by_volume_tercile.csv / .png # Calibration by volume tercile
│ ├── cluster_bin0_sports_politics_t3.csv # Per-event data (robustness test input)
│ ├── cluster_robustness_bin0.csv # Naive / per-event / bootstrap comparison
│ └── cost_analysis_bin0.csv # Net edge under spread/fee scenarios
└── README.md
```

## Results

### 1. Calibration: a reverse favorite-longshot bias

Across all resolved Yes/No markets in 2025-2026 (249,840 tokens priced at
T-7), Polymarket is overall well calibrated, and where a gap exists, it
runs **in the opposite direction** of the classical favorite-longshot bias.

![Overall calibration](results/calibration_overall.png)

- 0-10% bucket: average implied price **2.55%** vs. realized frequency
 **3.88%** (95% CI [3.75%, 4.02%], n=75,699) — statistically significant
 gap, of opposite sign to the initial thesis (longshot **under**priced).
- 90-100% bucket: average implied price **97.29%** vs. realized frequency
 **96.20%** (95% CI [96.06%, 96.34%], n=74,909) — extreme favorites are
 slightly overpriced, consistent with a reversed pattern.
- Intermediate buckets (30-70%) are overall well calibrated (gap
 < 2 percentage points).

### 2. Where does the reversed pattern concentrate?

![Calibration by category](results/calibration_by_category.png)

- **Sports** and **Politics** carry most of the signal: gaps reaching -5.3
 points (10-20% bucket, Sports) and -5.2 points (20-30% bucket, Politics)
 in longshot underpricing, with symmetric overpricing on the high buckets
 (up to +3.9 points, Politics 70-80%).
- **Crypto** (dominated by 5-minute "Up/Down" high-frequency markets) is
 nearly perfectly calibrated on the two extreme, most populated buckets
 (0-10%: -0.1 point gap on 15,579 obs; 90-100%: +0.1 point on 15,928 obs).
 The middle buckets, far less populated (1,500-1,650 observations), are
 noisier (gaps up to ±3.4 points) — consistent with a market mechanically
 replicated from the spot price at extreme probabilities, with no
 conclusion possible on intermediate probabilities for lack of sample
 size.
- **Weather** is too illiquid to draw conclusions from (n=2,256 total, some
 buckets under 30 observations) — the gaps observed there are likely
 noise.

![Calibration by volume tercile](results/calibration_by_volume_tercile.png)

- The reversed pattern is **sharpest and most robust in the highest volume
 tercile** (the most liquid markets): -1.9 to -5.0 points on the low
 buckets, +4.7 to +4.8 points on the 70-90% buckets, with large samples
 (4.5K to 21K observations per bucket) — this is not a thin-liquidity
 effect that would disappear with more volume.
- The middle tercile (average volume) is the best calibrated of the three.
- The lowest tercile (illiquid markets) is noisy in places (samples of
 2,200-3,700 on the middle buckets) and doesn't support a firm conclusion
 on its own.

**Reading**: the signal doesn't look like a classical favorite-longshot
bias diffused across the whole market — it looks like a phenomenon
concentrated in categories with a strong narrative/human component
(Sports, Politics) and in the most heavily-traded markets, running opposite
to the initial thesis. It is this subset (Sports + Politics, highest volume
tercile, 0-10% bucket) that is tested in the next two sections.

### 3. Clustered significance: the signal survives

Before any fee analysis, it was necessary to check that the 0-10% bucket
signal isn't a statistical artifact caused by non-independence of
observations: a single real-world event (a 150-player tournament, a game
with several prop markets) often resolves **several condition_ids
simultaneously**, whereas the naive binomial CI treats every token as an
independent draw.

**Event grouping.** `market_details.event_market_id` natively groups
Polymarket's multi-outcome markets (e.g. one PGA Tour `event_market_id`
groups 159 binary "Will Player X win?" markets, only one possible winner).
For markets without an `event_market_id` (`event_market_name = 'single
market'`, the majority of rows), grouping is approximated by (category,
exact `resolved_on_timestamp`): distinct markets resolved at the identical
second are very likely triggered by the same real-world event. Verified
before use: 22,674 of 88,534 "same timestamp" groups in Sports contain more
than one distinct market (up to 37 simultaneous markets), 1,842 of 13,856
in Politics (up to 15) — this is not a degenerate grouping. Full detail in
`queries/04_cluster_robustness.sql`.

**Calibration and CI recomputed with clustering.** On this subset (3,727
events, 10,140 tokens, 398 winners), three estimates:

| Method | Effective n | Implied price | Realized rate | 95% CI |
|---|---|---|---|---|
| Naive (per token, i.i.d.) | 10,140 tokens | 2.36% | 3.93% | [3.56%, 4.32%] |
| Per event, equal weight | 3,727 events | 3.08% | 6.32% | [5.59%, 7.15%] |
| Cluster bootstrap (10,000 draws) | 3,727 events | 2.36% | 3.93% | [3.55%, 4.33%] |

*(Detail in `results/cluster_robustness_bin0.csv`, computed in
`src/cluster_robustness_bin0.py`.)*

The cluster bootstrap — the most rigorous of the three methods, since it
resamples events (not tokens) while preserving the natural weighting by
position size — gives a CI nearly identical to the naive one ([3.55%,
4.33%] vs. [3.56%, 4.32%]). The average implied price of 2.36% remains
**clearly outside** this interval. The equal-weight per-event grouping
(every tournament or game counts as a single point, regardless of its size)
even points to a **larger** gap (implied 3.08% vs. realized 6.32%), not a
smaller one. Since the average cluster size on this subset is only about
2.7 tokens per event, the information loss from clustering is real but
modest on this particular bucket.

### 4. Net edge: positive, but depth-limited

On this same subset, the gross edge is **+1.57 points** (implied price
2.36% vs. realized rate 3.93%). Three execution costs were deducted:

**Effective spread** (proxy, in the absence of historical order-book data
— see limitations below) — gap between average BUY and SELL execution
price, across the 28,880 markets in scope, prices between 0.5 and 10
cents:

| Method | Average BUY price | Average SELL price | Gap (spread proxy) |
|---|---|---|---|
| Dollar-weighted | 2.49% | 2.52% | **0.03 point** |
| Unweighted (simple average) | 3.41% | 4.35% | **0.93 point** |

**Polymarket fees**, directly measured from `market_trades.fee` (BUY side
only — a buy-and-hold-to-resolution strategy has a single leg):

| Contract regime | Fee as % of amount | Fee in price points (on 2.36%) |
|---|---|---|
| v1 (historical, before April 2026) | 0.16% | 0.004 point |
| v2 (current, since April 2026) | 2.72% | 0.064 point |

**Depth** — on the 2-3 cent band specifically, total BUY volume: **$7,040k**
across the 28,880 markets in scope, i.e. an average of **~$244 in total
volume (over the market's whole lifetime) per market** at this price
level, and a typical trade size of **~$11**.

**Net edge, by scenario** (v2 fees, current regime):

| Spread scenario | Net edge | % of gross edge retained |
|---|---|---|
| Optimistic (weighted) | **1.47 points** | 94% |
| Conservative (unweighted) | **0.57 points** | 36% |

*(Detail in `results/cost_analysis_bin0.csv`, computed in
`src/cost_analysis_bin0.py`, queries in `queries/05_cost_analysis.sql`.)*

Under both scenarios, the net edge stays positive — the measured costs
aren't enough to erase it. But the available depth (~$11 per typical
trade, ~$244 in total volume per market over its whole lifetime at this
price level) means no meaningful capital size can be deployed without
execution itself moving the price against the trader — an effect not
captured by these pooled averages.

## Verdict and limitations

**Verdict: a statistically real signal, arithmetically positive net of
measured costs, but not robustly exploitable at scale.** The reversed
pattern (underpriced longshots / overpriced favorites) is confirmed on a
large sample, survives event clustering, and its edge survives fees and a
spread proxy. This is, however, not an operational conclusion: it is a
research signal worth digging into further, not a strategy ready to be
deployed.

**Assumed limitations:**

1. **Uncertain spread proxy.** Dune does not retain historical Polymarket
 order-book data, only executed trades. The spread is therefore
 approximated by comparing BUY vs. SELL execution prices pooled over 2
 years without time-matching by token — the gap partly captures price
 drift (trade composition over time), not just the cost of the spread
 itself. Hence the wide range retained (0.03 to 0.93 point) rather than a
 single figure; a true spread near the top of this range, combined with
 execution slippage not measured here, could bring the net edge very
 close to zero.
2. **T-7 price vs. real execution.** The whole analysis compares the
 resolution to the price displayed 7 days earlier — not to the price at
 which a trade could actually have been executed at that precise moment
 (beyond the spread proxy above). The trader would also have to carry 7
 days of execution/cancellation/repricing risk before resolution, which
 is not priced into the gross edge.
3. **Possible non-stationarity of the bias.** The 2025-2026 sample covers a
 window in which Polymarket experienced rapid growth and a contract
 switch (v1→v2, April 2026); nothing guarantees that trader composition,
 liquidity, or the bias itself remain stable over time — a signal
 measured over one period can fade or disappear once known and arbitraged
 away (market self-correction), or simply reflect a market regime that
 has since changed.
4. **Approximate event grouping** (see section 3) — a proxy by exact
 resolution timestamp for markets without an `event_market_id`, not
 ground truth.
5. **Category/tercile clustering** relies on `market_details.tags` (first
 tag = category) and a volume tercile computed over the market's entire
 lifetime (not the volume available at the precise moment of the trade)
 — two reasonable but inexact approximations.

## Possible extensions (not carried out)

- **Shorter price horizons (T-1, T-3)** — test whether the pattern
 sharpens, stabilizes, or reverses as resolution gets closer; would also
 reduce the unpriced carry risk (limitation 2 above).
- **Real-time order book via Polymarket's CLOB API** — would replace the
 spread proxy with a direct measurement (real bid/ask, depth by price
 level), the main source of uncertainty in the current verdict.
- **Out-of-sample tracking** — freeze the selection rule (Sports/Politics,
 high volume tercile, 0-10% bucket) found on 2025-2026 and prospectively
 retest it on markets resolved after this report's date, to check that the
 signal isn't an artifact of retrospective data snooping on this specific
 window.
- **More precise event grouping** — replace the timestamp proxy with a
 structured match (market title, league/season, shared participants) for
 "single market" entries tied to the same game or news event.