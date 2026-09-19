# Attention → price lead test — design (option C, pre-execution)

**Date:** 2026-09-18 · **Status:** design only, nothing implemented · **Scope:** measurement lane (no live-path change)
**Predecessor:** `drafts/trendradar-audit.md` (TrendRadar audit — salience router framing)
**Question this answers before any code:** *is there a tradeable lead between a news item's salience and a
Polymarket price move, and can we measure it with data we already have?*

---

## 1. Hypotheses (signed and mutually exclusive)

Let `E` = a news story cluster about subject `S` at event time `t0`, and `M` = the live Polymarket market whose
subject is `S`. Let `Δ = p_M(t0+h) − p_M(t0)` signed toward the news direction (bullish-for-YES news ⇒ positive).

| | claim | observable signature |
|---|---|---|
| **H1 underreaction** | the market absorbs the news slowly | `Δ > 0` for `h ∈ {15, 60, 240} min`, decaying to 0 by `h ≈ 24h` |
| **H0 already priced** | the move happens at/before `t0` | `Δ ≈ 0` for all `h > 0`; `|p_M(t0) − p_M(t0−1h)|` carries all the response |
| **H2 overreaction** | the crowd overshoots then mean-reverts | `Δ < 0` at `h ≥ 60 min` after an initial positive move |

Only H1 is tradeable, and only if the effect exceeds the fee. H0 is the expected outcome. **A design that cannot
distinguish H0 from H2 is not worth running** — hence the pre-event window is measured, not skipped.

## 2. Data inventory — measured 2026-09-18 (this is the feasibility core)

### 2a. Price resolution grid (CLOB `/prices-history`, keyless, **requires a browser User-Agent** — a bare
urllib request gets 403)

| request | result | usable horizon |
|---|---|---|
| `interval=1h|6h|1d&fidelity=1` | **60-second bars** (61 / 361 / 1,441 points) | h ≤ 24h at 1-min |
| `interval=1m&fidelity=10` | 10-minute bars, 743.9h span (n=4,456) | 31 days at 10-min |
| `interval=max&fidelity=1` | clamped to **10-minute bars**, 31 days | 31 days at 10-min |
| `interval=1w` | rejected: minimum fidelity 5 | 7 days at 5-min |

⇒ **1-minute resolution exists only for the trailing 24 hours.** Any longer retrospective runs at 10-minute
granularity, so `h` must be ≥ 30 min there. This is a hard constraint on the design, not a preference.

### 2b. Microstructure corpus (`data/l2/`, own recorder)

- 28,710 asset files · **7.45 GB** · since **2026-08-31** (18 days) · 5-second book snapshots.
- Universe = markets with an observed trade in the last 2h, **MAX_MARKETS = 25 concurrent**, rotating
  (~2,344 assets touched per 24h) → *selection into L2 is our own pipeline's attention*.
- **Data-integrity flag: 0 trade prints found in 1,200 sampled files.** The book side works; the trade-print
  path (`record-l2.ts` ~L181, the stated raw material for a fill-probability model) appears to be producing
  nothing. Verify before relying on it.

### 2c. News side (as stored today)

- `data/gdelt-shadow.jsonl`: 1,702 rows · 1,554 cloud + 148 legacy · since **2026-09-01** (~86 cloud rows/day
  over 6 category queries) · `significance` 0.08–0.66 (mean 0.10), `article_count`, `geo`,
  `matched_categories`.
- **Event-time gap, and it is one line of work:** the Cloud API returns `processed_at` and `updated_at` as ISO
  timestamps (`"2026-09-18T07:24:58Z"`) and the collector **discards both**, storing only `story_date`
  (day granularity). The legacy DOC feed *does* store `seendate` at 15-minute granularity.
  ⇒ storing two fields converts this from "daily buckets only" to a timestamped event stream.
- `entity_refs` arrive as `{name, type, wikipedia_url}` and are stored as names only; many stored rows are
  empty because the six standing queries returned entity-less clusters.

## 3. Design

**Event definition.** A cloud story cluster is admitted if: (a) it has ≥1 usable entity with `type ∈
{person, org, country}`; (b) `article_count ≥ 2` OR `significance ≥` the 80th percentile of its category;
(c) it is not a market-derived story (exclude domains/hosts matching `polymarket|kalshi|betting|odds` —
protects against reverse causality where the article is *about* the price move).

**Event time `t0`** (three candidates, sensitivity-tested): (i) `processed_at` once stored; (ii) the earliest
`seendate` among the cluster's articles via the DOC feed (15-min granularity); (iii) `story_date` 00:00 UTC as
the pessimistic bound. Primary = (ii); jitter test ±15 min and ±1 h.

**Market matching** (the yield-determining step; reuse the house matcher doctrine from the tennis audit —
similarity ladder, both-sides-must-agree via min, ambiguity margin ⇒ return None rather than guess):
1. Entity string → market question/slug token overlap, with a legal-suffix and stopword normalizer.
2. Require the market to be **live** at `t0` (not resolved, `endDate > t0`).
3. Require liquidity ≥ the market universe's median at `t0` (MarketSnapshot) and TTR ≥ 24h.
4. Reject if > 3 markets match the same entity at the same time (ambiguity) — report those as unmatched.
5. **Precision audit:** hand-label 50 matches before any measurement; publish precision. A matcher with < 85%
   precision invalidates the test.

**Estimand (fee-units, not percent):** per event, `edge = Δ_favourable − round_trip_fee`, where
`round_trip_fee ≈ 2 · rate · (1 − p)` in per-dollar terms (Polymarket taker form `shares·rate·p·(1−p)`; at
p=0.50 and a 4% rate this is ~2% of notional **per side**). Report `Δ` in both probability points and fee
multiples. Primary horizon: **h = 60 min**; secondary: 15 min, 240 min (10-min bars only), 24h.

**Control:** each event is matched to a same-category, same-price-band (within 0.10), same-TTR-band market that
has no admitted story in the window, and `Δ_abnormal = Δ_treated − Δ_control`. This is what separates "the news
moved it" from "the whole book drifted".

**Prices used:** mid where only `prices-history` exists; where the market is in the L2 corpus, the **ask** for
entry and **bid** for exit (never the midpoint) — the house execution rule. L2 is a cross-check on a biased
subsample, never the primary source.

**Pre-registration.** Primary spec fixed *before* looking: cloud stories, h = 60 min, salience top tercile,
directional tone from the story's entity-sentiment, matched-control abnormal return, fee-net edge, time-ordered
split (first 70% discovery / last 30% holdout). Everything else (other horizons, other categories, thresholds,
TrendRadar's persistence features) is **secondary/exploratory** and reported as such, with Bonferroni across the
horizon family.

## 4. Acceptance criteria (all four for "real") and kill criteria

- **A1** primary-spec edge is **positive after fees** on the 30% time-holdout.
- **A2** market-clustered bootstrap 95% CI of the edge excludes 0.
- **A3** ≥ 60% of matched *entities* non-negative (concentration guard: no single entity/market family may
  contribute > 20% of the effect).
- **A4** survives event-time jitter (±15 min) and the matched-control baseline.
- **K1** matcher yield < 15 usable events/day after Stage 1, or precision < 85% → stop, report, do not scale.
- **K2** sign flips on the holdout → stop.

## 5. Power vs economics — the bar is fees, not significance

`MDE ≈ 2.8·σ/√N` with σ ≈ 3–4 probability points for a 1-hour move on a mid-priced Polymarket market.

| N events | MDE (1h) | verdict |
|---|---|---|
| 50 | ≈ 1.4 pt | statistically fine, economically meaningless |
| 125 | ≈ 0.9 pt | still under the ~2 pt/side fee at p=0.5 |
| 300 | ≈ 0.6 pt | **still under the fee bar** |

⇒ **The test is not power-limited; it is fee-limited.** Even 300 events can only certify an edge far larger
than a realistic 1-hour news drift. The honest design consequences: (1) the primary criterion is *fee-net*, not
*p*; (2) report the effect distribution rather than the mean (a fat tail of large moves is tradeable even when
the mean is not); (3) the most promising variant is **hold-to-resolution** events (one entry fee instead of a
round trip) with TTR ≥ 24h — i.e. news that changes the *terminal* probability, not the next hour.

**Sample accumulation:** ~86 cloud stories/day → after matching, expect a fraction; **Stage 1 exists to measure
that fraction and it is the go/no-go number.** At 15 matched/day, 300 events ≈ 3 weeks. At 5/day, stop (K1).

## 6. Threats to validity (stated before results, not after)

1. **Selection into the L2 corpus** (25 markets, chosen by *our* pipeline) — neutralized by using
   `prices-history` as the primary source, which covers any market.
2. **Simultaneity / reverse causality** — news and price move together; a story can be *about* the drift.
   Mitigated by the domain exclude-list, first-article event time, and the control market.
3. **Event-time censoring** — `story_date` is daily and `processed_at` lags the first article; hence the jitter
   test, and the DOC-feed `seendate` as the primary time source.
4. **Thin markets / stale bars** — 10-min bars on illiquid markets repeat values; require a minimum trade count
   or liquidity floor, and drop flat-window events.
5. **Multiple comparisons** — one pre-registered spec, Bonferroni over the horizon family, holdout reserved.
6. **Regime drift** — prices-history reaches back 31 days and that window contains several ruleSetVersions;
   split by era, never pool silently.
7. **Attention is likely already in the price** (the base case) — which is why H0 is measured first, and why the
   *routing* use (find markets, don't rank them) survives even a null on H1.

## 7. Stage plan (measurement-only ⇒ does **not** wait for the Oct 8 window)

| stage | work | effort | gate |
|---|---|---|---|
| **0 — plumbing** | store `processed_at`/`updated_at` (+ entity types) in `gdelt_shadow.py`; log the assetId↔marketId map in `record-l2.ts`; note the UA requirement for `prices-history` | ~30 min | no gate — shadow file only, no live path |
| **1 — matcher + yield** | entity→market matcher + `data/attention-events.jsonl`; 50-row hand-labelled precision audit; yield/day report | ~1 day | **go/no-go: ≥15 events/day and ≥85% precision** |
| **2 — event study** | event-study harness over `prices-history` (1-min ≤24h, 10-min 31d) with control matching, clustered CIs, A1–A4 | ~1-2 days | A1–A4 pass ⇒ Stage 3; else publish the null and stop |
| **3 — feature upgrade / wiring** | TrendRadar's rank-persistence + multi-source corroboration as *additional* salience features; A2 evidence-tier wiring as a confidence modifier | ~1-2 days + post-window | **post-Oct-8**, flag-revertible, shadow → paper |

Note the sequencing correction to the audit: **the lead test does not need TrendRadar to start.** The blocking
gap is event timestamps we are already receiving and discarding, plus a matcher. TrendRadar's unique
contribution (rank/persistence over time, cross-source corroboration) is a *second-generation feature* worth
adding only if Stage 2 shows a non-zero base effect.

## 8. Actionable regardless of whether the test runs

1. **Collector fix (30 min):** GDELT Cloud already returns `processed_at`/`updated_at`; we drop them. Storing them
   converts the news feed into a timestamped stream usable by *any* future study — the cheapest option on the
   whole list.
2. **L2 trade-print anomaly:** 0 trade prints in 1,200 sampled files — investigate before the fill-probability
   work depends on it.
3. **`prices-history` needs a browser UA** — record it, or every future backtest script hits a 403 and "discovers"
   that the endpoint is broken.

## 9. Honest verdict

Run **Stage 0 + 1 now** (an afternoon, measurement-only, no live path). They answer the only two questions that
decide everything else: *can we timestamp news properly* (yes, mechanically), and *do enough news events map to
live markets to matter* (unknown — that is the yield number Stage 1 buys). **Stage 2 only if K1 passes**, and its
primary criterion is fee-net edge on a holdout, not a p-value. **Stage 3 only if A1–A4 pass**, post-window.

What would falsify the whole idea: yield < 15/day (K1) — the news universe and the market universe simply do not
overlap enough for a salience router to matter — or an A1/A4 failure with the effect concentrated in one entity
family. Both are cheap outcomes; that is the point of staging it this way.
