# ML lane settlement source — the proxy is losing ~86 % of resolutions

**Date:** 2026-10-22 · **Status:** PROPOSED (Lane A — feeds the promotion gate) · **Author:** Hermes

## The question this answers

"How long before the ML lane has enough settled legs to be judged?" The answer was being set by a
settlement *derivation* that does not work, not by training time and not by patience.

## What the lane does today

`scripts/ml-observe-read.py` derives each market's outcome from **our own last `MarketSnapshot`**:

```sql
SELECT s.marketId, s.yesPrice FROM MarketSnapshot s
JOIN (SELECT marketId, MAX(collectedAt) mx FROM MarketSnapshot WHERE isDemo = 0 GROUP BY marketId) l
  ON l.marketId = s.marketId AND l.mx = s.collectedAt
-- then: yesPrice >= 0.90 -> resolved YES ; yesPrice <= 0.10 -> resolved NO ; else NOT SETTLED
```

The docstring already calls it "a proxy, not a resolution".

## Two measurements showing it under-captures

### 1. The last snapshot is usually mid-priced

Markets whose last snapshot was **within 12 h of resolution** (the population where a decisive price
should exist), from the 7-day window:

| last-snapshot price | markets | share |
|---|---|---|
| mid 0.10 – 0.90 (**would not settle**) | **201** | **85.9 %** |
| ≤ 0.10 | 21 | 9.0 % |
| ≥ 0.90 | 12 | 5.1 % |

Collection generally stops while the market is still mid-priced, so the `>= 0.90 / <= 0.10` rule fires
for roughly **one market in seven**.

### 2. Markets are already settled at the venue while the lane reports zero

Live check on the six soonest-resolving markets in `data/ml/observe-log.jsonl`, joined
`observe.market_id -> MarketSnapshot.marketId -> conditionId`, then
`GET https://clob.polymarket.com/markets/{conditionId}`:

```
ja2-ven-yok-2026-10-21-yok                 closed=True  winner Yes
ucl-psg-fcb-2026-10-20-corners-total-7pt5  closed=True  winner Under
cs2-faze-ast-2026-10-20-game2              closed=True  winner FaZe
cs2-g1-bw-2026-10-20                       closed=True  winner Bushido Wildcats
sud-vas-boc-2026-10-20-boc                 closed=True  winner Yes
bknbl-tas-bri-2026-10-21-total-186pt5      closed=True  winner Over

CLOB reachable 6/6 · decisive winner present 6/6
```

**Six of six have a venue-resolved winner. `data/ml/observe-report.json` says
`settled_observations: 0`.** The lane is not waiting for markets to resolve; it is failing to see
that they already have.

## Why `OutcomeReview` cannot fix this

The obvious source is wrong, and it was my first answer, so it is recorded here as a refuted option.
`OutcomeReview` columns are:

```
id, decisionJournalId, paperTradeId, reviewTime, priceAfter1h, priceAfter6h, priceAfter24h,
finalOutcome, simulatedPnl, wasDecisionGood, lessonsJson, createdAt
```

There is **no `marketId` and no `conditionId`**. It keys on `paperTradeId` / `decisionJournalId`, so it
can only settle markets we actually took a position on. The observe lane opens **no positions** — that
is the point of observe-only — so `OutcomeReview` has no row for any observed market. (Its 99.5 %
agreement in the docstring is on the *acted* population, which is a different set.)

## Proposed change

Derive settlement from **venue truth**, not from a snapshot price:

1. `observe.market_id` -> `MarketSnapshot.marketId` -> `conditionId` (**46,227 markets already carry
   one**)
2. `GET https://clob.polymarket.com/markets/{conditionId}` -> `tokens[].winner`
3. `winner=True` on the YES token -> `y_yes = 1`; on the NO token -> `y_yes = 0`; market not closed ->
   unsettled

Keep the snapshot derivation behind `--settlement-source=snapshot`, compute **both** for one week, and
report them side by side so the switch is reversible and the disagreement is visible rather than
implied.

## Pre-registration

**Hypothesis.** The snapshot proxy under-captures settlement, so the observable sample accrues ~7x
slower than possible; venue resolution recovers it and moves `n >= 400` settled from early December to
~2026-11-01.

**Measurement (read-only, ~2 h).** For all 85 observed markets: resolve `conditionId`, fetch CLOB, and
report (a) coverage — how many markets carry a conditionId and a closed status; (b) agreement with the
snapshot proxy on the overlap where both are decisive; (c) the restated settled count and the projected
date to `n >= 400`.

**Decision rule.** Adopt venue resolution as the read **only if** coverage >= 90 % of observed markets
have `conditionId` + a retrievable CLOB record, **and** agreement with the proxy >= 95 % on the decisive
overlap. Both conditions, not either.

**Refutation.** The proxy stands, and the ETA reverts to early December, if **any** of:
- coverage < 70 %, or
- disagreement > 5 % on the decisive overlap (that would mean the proxy and the venue disagree about
  what happened, which is a data-integrity problem larger than this fix), or
- > 20 % of observed markets have no `conditionId`.

**Cost.** ~2 h, read-only, no live-lane risk. **Reversibility:** one function plus a flag; both sources
computed and reported for a week before the switch is trusted.

## What this does NOT change

- The §8 promotion bar is untouched: `n >= 400` **plus** four other conditions, all five needed.
- The lane stays at zero size. Nothing here opens a position.
- Promotion remains human-gated. The design's own expectation is that it **does not clear** (OOS
  −29.84 %), and this fix makes that verdict arrive sooner, not differently.

## Honest limits

- The 6/6 probe used the six *soonest* markets — a biased sample that over-represents the resolvable
  end. It proves the mechanism works; it does not prove 90 % coverage across all 85.
- Coverage depends on `MarketSnapshot.conditionId` being populated for observe-lane markets
  specifically. 46,227 markets carry one, but that is the whole table, not this 85.
- Venue resolution also removes a small amount of information the proxy had: the proxy could in
  principle flag a market that trades to 0.97 while still formally open. That case is rare and is
  worth reporting as a divergence rather than silently preferring either source.
