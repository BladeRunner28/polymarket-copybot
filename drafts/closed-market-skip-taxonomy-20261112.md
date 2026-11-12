# A closed market is not a candidate — the 2% post-close decisions are data-api prints that arrive after settlement

Card `t_d246fc66` · **Lane A proposal — nothing shipped, no rule/gate/size/exit touched** · read
2026-11-12T19:5xZ · instrument `scripts/closed-market-skip-taxonomy.py` (read-only, `mode=ro`) →
`data/closed-market-skip-taxonomy.json` · upstream: `drafts/nearcert-mark-guard-after-20261112.md`

## The decision in one line

**Recommend (a): guard at intake on the venue's own `resolved` flag, stamp the row
`observationOnly`, keep the wallet's fill as `detectedPrice`, add a `[CLOSED-MARKET]` counter line.**
It catches 100 % of the class in the window the card names (103/103) and 86 % over 30 d (846/983), it
is the file's existing convention for a row that is not a candidate, and it is the only option that
also stops the stored detection price from being a settlement value. Option (b) is the 100 % variant
for the 30 d residual and costs a branch on the scoring path; (c) is refuted by the numbers below.

Three of the card's own statements need correcting first, because they change what the guard is for.

## 1. The count reproduces; the 30 d figure is 17 short

| window | the card | re-measured | note |
|---|---|---|---|
| post-fix 3.19 d (11-09T15:15Z → 11-12T19:43Z) | 103 / 5,588 (1.8 %) | **103 / 5,588 (1.84 %)** | exact |
| trailing 30 d (09-29T21:36Z → 10-29T21:36Z) | 966 / 36,655 (2.6 %) | **983 / 36,655 (2.68 %)** | +17 |

The 966 is an **instrument defect in the upstream read**, not a different population: the venue
writes five-digit fractional seconds (`2026-11-10 19:01:58.31905+00`), JS `Date.parse` accepts that,
and Python's `datetime.fromisoformat` requires exactly 3 or 6, so `nearcert-mark-guard-after.py`'s
`parse_ts` returned `None` for those rows and they fell out of its "closed" count as if live. My
instrument hit the same trap on its first run (295 of 5,588 rows read `unknown`) and now normalizes
the fraction, with a self-test line pinning it. **The upstream script is not patched here** — fixing
it moves a published figure, so it is its own Lane A item (follow-up 1).

## 2. The journal does not blame the near-certainty clause — that clause is never first

On a settled market every price/liquidity/spread gate reads a **dead book**, and `risksJson` is
`[...hardSkips]` in gate order. Measured on the 103 post-close rows (post-fix window):

| risk entry | rows |
|---|---|
| `risksJson[0]` = `liquidity $0 < min $500` (or the account's live `minLiquidity`) | **103 / 103** |
| contains `price … near certainty` | 103 / 103 |
| … where near-certainty is the **first** entry | **0** |
| … where near-certainty is the **only** entry | **0** |
| … where a `resolves in …` entry precedes it | 52 (820 / 919 over 30 d) |

So the row's headline claim is already true-ish ("illiquid") and its second claim is an artefact of
the same dead book. The reason it *looked* like a near-certainty problem is that the cohort instrument
parses that string out of the array — and `src/lib/nearcertainty-tail.ts` already separates live from
post-close rows (`decisionLiveness()`), so that one reader is not fooled while any plain count over
`risksJson` is. **The real defect is narrower and cleaner than the card states: an observation that is
not a candidate is being scored, and a settlement price is being stored as a detection price.**

| what is actually wrong | rows (post-fix) |
|---|---|
| decisions stamped on a market already closed | 103 |
| rows storing a **settled 0/1** as `detectedPrice` | 103 (10 × `0.000`, 93 × `1.000`) |
| wallet's own fill on those same rows | 0.34 – 0.71 (avg 0.427 on the zeros, 0.485 on the ones) |
| `paper_copy` / `watchlist` among them, legs booked | 0 / 0 — **admissions 0 → 0 confirmed** |
| sub-0.05 near-certainty rows that are settled prices | 10 of 182 |

## 3. The mechanism is not scoring lag — it is the feed

The card implies the pipeline sits on rows and scores them later. Measured, it does not:

| lag | median | p10 | p90 |
|---|---|---|---|
| ingest → decision (`ObservedTrade.createdAt` → `DecisionJournal.createdAt`) | **0 min** | 0 | 0 |
| trade → ingest (`ObservedTrade.timestamp` → `.createdAt`) | **1,167 min (19.4 h)** | 367 | 1,348 |

Every one of the 103 rows carries `provenanceSource = data-api`, `provenanceLagged = 1`. The wallet
activity feed hands us prints up to **22 hours old**; when the market settled in the meantime, the
monitor fetches a payload whose book is gone and stores its settlement price as the detection price.
That is why the population is **episodic, not a steady 2 %**: the 103 post-fix rows are all stamped
2026-11-12 (top markets `cs2-mouz-g2-…-map-handicap-away-1pt5` 28, `cs2-lgc-fal2` 23,
`cs2-mouz-g2` 11), and the 30 d burst days — 10-05 (191), 10-14 (179), 10-16 (189), 10-24 (209) —
are exactly the days with the worst decision lag (158 / 243 / 195 / 69 min avg, ~23.7 h max).

**Consequence for the option set:** the rows were live when the wallet traded and already closed when
*we* saw them, so the guard's test must be the market's state **at ingest**, not at the print.

## Option coverage — the measurement that decides (a) vs (b)

| window | post-close decisions | already closed when the monitor fetched (→ **(a)** catches) | closed only between ingest and scoring (→ **(b)** only) |
|---|---|---|---|
| post-fix 3.19 d | 103 | **103 (100 %)** | 0 |
| trailing 30 d | 983 | **846 (86.1 %)** | 137 (13.9 %) |
| pre-fix equal window | 2 | 2 | 0 |

## Before / after

| figure | today | **(a) intake** | (b) scoring | (c) leave |
|---|---|---|---|---|
| decisions on a market already closed, 3.19 d | 103 (1.84 %) | **0** | 0 | 103 |
| … 30 d | 983 (2.68 %) | **137 (86 % caught)** | 0 | 983 |
| journal rows whose first reason is a dead-book artefact | 103 | **0** | 0 | 103 |
| sub-0.05 near-certainty cohort (post-fix) | 182 | **172** | 172 | 182 |
| near-certainty cohort, all rows (post-fix) | 1,991 | **1,888** | 1,888 | 1,991 |
| rows storing a settled 0/1 as `detectedPrice` | 103 | **0 — wallet print kept** | 103 (unchanged) | 103 |
| admissions (legs booked on those decisions) | 0 | **0** | 0 | 0 |
| journal volume | 5,588 / 3.19 d | **−103** (−1.8 %) | +103 skip rows | — |
| longshot-shadow rows at `entryPrice 0` (lifetime) | 536 | stops growing | stops growing | grows ~10/3 d |

## Why (a), not (b)

1. **The row was never a candidate.** `scripts/monitor-trades.ts:166-169` already states the
   convention for that: an observation-only row *"keeps the wallet's own fill price … these rows can
   never be copied"*. Marking a print that arrived after settlement `observationOnly` restores the
   invariant the file already documents, instead of inventing a second one.
2. **Only intake can keep a truthful price.** `detectedPrice` is written by the monitor's fetch. Under
   (a) it stays the wallet's print (0.34–0.71). Under (b) the stored value is already the settled
   0/1 before the scorer ever sees the row, and the decision only changes the *string*.
3. **It never touches the scoring path.** `score-trades.ts` carries every gate and every journal
   write; a branch there is the most expensive line in the repo to get wrong. Admissions are 0 either
   way, so (b) buys coverage, not flow.
4. **It keeps the skip histogram honest.** A settled print is not a rejected candidate. Journaling it
   as a `skip` adds 33/day to the "why we did not copy" population — the same class of error the
   funnel forensics rules out (never count non-decisions as decisions).

What (a) does not do: the 137 rows/30 d that close between ingest and scoring keep getting scored.
That is 0.37 % of decisions (13.9 % of a 2.7 % class). **Pre-registered backstop:** if the first
7-day post-guard re-read shows that residual above 0.5 % of decisions, add (b) as the second layer.

## Implementation sketch (for the yes — not applied)

`scripts/monitor-trades.ts`, inside the existing fetch block (`!w.observationOnly && !isBlankMarket`),
before the snapshot write:

```
const m = await adapter.fetchMarket(t.marketId);
+ // t_d246fc66 (Lane A, approved): a print that arrives after the venue closed the market is not a
+ // candidate — the payload's quotes are settlement values, not a book. Same shape as
+ // isBlankMarket: keep the row, stamp it inert, count it, never price it. Can only REMOVE
+ // admissions, so it cannot trip the ordering hazard that comment above documents.
+ if (m.resolved === true) marketClosed = true;
+ if (!marketClosed) { detectedPrice = priceForOutcome(m, t.outcome) ?? detectedPrice; /* snapshot */ }
```

and at the write: `observationOnly: w.observationOnly || isBlankMarket || marketClosed`,
`detectedPrice: marketClosed ? t.price : detectedPrice`, plus `closedMarket++` and a
`[CLOSED-MARKET] N row(s) stored observationOnly — market already resolved at ingest` line next to
`[BLANK-MARKET]`, so the event is counted, not silent.

Guard on **`m.resolved`** (the adapter already derives it: `closed === true || umaResolutionStatus ===
"resolved"`), **not** on `ttr === 0`. The zero-TTR population is not the closed population: 955
post-fix decisions carry `resolves in 0.0h` and only **52** of them are closed — the other **903 are
in-play markets trading past their end date**, where the reason is true and the book is live (30 d:
3,975 rows, 793 closed, 3,182 live). A `ttr`-based guard would relabel 903 true rows to catch 52.

## Refutation / re-read (what would prove this wrong)

Run `python3 scripts/closed-market-skip-taxonomy.py --pre-days 7` seven days after it ships:

* **confirms** if `option_coverage.caught_at_intake` = 0 and `post_close.decisions` = 0 with
  admissions unchanged;
* **refutes** if new decisions still store `detectedPrice ∈ {0, 1}` on a market closed at ingest, or if
  the residual (`scoring_only`) exceeds 0.5 % of decisions — then (b) ships as well.

## Two follow-ups this read found (neither is shipped)

1. **`scripts/nearcert-mark-guard-after.py` undercounts closed-market rows** (966 vs 983 over 30 d)
   because `parse_ts` silently drops five-digit fractional seconds. One-line fix (normalize the
   fraction before `fromisoformat`), then re-run the 30 d window. It moves a published figure, so it
   is Lane A, not an instrument repair I can just commit.
2. **The root is the feed, not the pipeline**: prints arrive with a 19.4 h median lag
   (`provenanceLagged = 1` on 100 % of the class). A freshness guard ("refuse prints older than N
   hours") would change what the bot decides on every lagged print, not just the settled ones — a
   larger Lane A decision that should be carded on its own numbers, not bolted onto this guard.

## Instrument

`scripts/closed-market-skip-taxonomy.py` — read-only (`mode=ro`) on `prisma/dev.db`, reuses
`data/nearcert-market-meta.json` and fetches only markets missing from it. Liveness is the same
three-state rule as `decisionLiveness()` in `src/lib/nearcertainty-tail.ts` (`closed !== true` → live;
closed with no readable clock → unknown, never coerced to live; else compare against `closedTime`),
pinned by seven self-test lines — including the five-digit-fraction case that broke both this read and
the upstream one.

```
python3 scripts/closed-market-skip-taxonomy.py --no-fetch        # no network, cached labels
python3 scripts/closed-market-skip-taxonomy.py --fetch-cap 4000  # refresh missing market labels
```

Nothing in the trade path was touched: no rule, gate, band, size or exit changed; no `apply-vNN`; the
DB was opened read-only.
