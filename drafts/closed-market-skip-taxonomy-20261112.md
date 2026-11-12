# A closed market is not a candidate — the 2% post-close decisions are data-api prints that arrive after settlement

Card `t_d246fc66` · **Lane A proposal — nothing shipped, no rule/gate/size/exit touched** · read
2026-11-12T19:52Z, rev 4 2026-11-12T20:20Z (review round 1: the wallet-print cell is now
instrument-emitted and the (a) sketch is price-only; round 2: the "Refutation / re-read" recipe now
names flags the script actually parses — `--pre-days` plus its `--ship-at` anchor — and the window
each run produced is pasted below; round 3: the (b) column is restated as "same rows journaled, first
reason fixed, volume unchanged", the sketch now moves the run counters with the write, and the
`m.resolved` vs `closed or closedTime <= now` deviation is measured instead of assumed) · instrument
`scripts/closed-market-skip-taxonomy.py`
(read-only, `mode=ro`) → `data/closed-market-skip-taxonomy.json` · upstream:
`drafts/nearcert-mark-guard-after-20261112.md`

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

The 966 is an **instrument defect in the upstream read** — the card's prior read of the same
population, `drafts/nearcert-mark-guard-20261029.md` (and `scripts/nearcert-mark-guard-after.py`),
not a different population: the venue
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

Scope of the 103/103: it is the **post-fix window only**. Over the 30 d the first-risk histogram is
not 983 × liquidity — it is 915 `liquidity…`, 59 `observation-only: wallet outside the current top-N
copy set`, 8 `price drifted … > max`, 1 `spread … > max` (the 30 d rows include wallet-filtered
observations that were never candidates anyway). Don't generalise the post-fix cell to the wider
window.

| what is actually wrong | rows (post-fix) |
|---|---|
| decisions stamped on a market already closed | 103 |
| rows storing a **settled 0/1** as `detectedPrice` | 103 (10 × `0.000`, 93 × `1.000`) |
| wallet's own fill on those same rows | **0.1731 – 0.71**, mean 0.4793; 21 of 103 below 0.34 (group min 0.34 on the `det=0` rows, 0.1731 on the `det=1` rows) |
| `paper_copy` / `watchlist` among them, legs booked | 0 / 0 — **admissions 0 → 0 confirmed** |
| sub-0.05 near-certainty rows that are settled prices | 10 of 182 |

The wallet-fill cell is emitted by the instrument (`post_close.wallet_entry_price` in
`data/closed-market-skip-taxonomy.json`: `{n, min, max, mean, below_0_34,
by_detected_price_group}`), not hand-computed. Round 1 of review caught the first draft quoting
`0.34 – 0.71` here: 0.34 is the minimum of the `det=0` group alone, and the real range starts at
0.1731 on a `det=1` row.

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

Option **(b)** is the column that is easy to misread, so it is stated as what it actually does: it
**journals the same rows it journals today** (the card's own definition — *"keeps the decision
journaled (auditable) but honest"*) and changes only **the reason on them**. It removes no journal row
and adds none. Review round 3 caught the previous printing of this table claiming that (b) both zeroed
the closed-market decisions *and* grew the journal by 103 rows, which cannot both be true: those 103
rows are already inside the 5,588 (`windows.post.decision_mix["post-close"] = {skip: 103}`), and the
draft itself says two sections earlier that under (b) *"the decision only changes the string"*. So each
figure below is split into **scored** (ran the gate loop) and **journaled** (has a DecisionJournal row).

| figure | today | **(a) intake** | (b) scoring | (c) leave |
|---|---|---|---|---|
| decisions **scored** on a market already closed, 3.19 d | 103 (1.84 %) | **0** | **0** | 103 |
| decisions **journaled** on a market already closed, 3.19 d | 103 | **0** | **103 — same rows, not one fewer** | 103 |
| … **scored**, 30 d | 983 (2.68 %) | **137 left (846 / 86.1 % caught)** | **0** | 983 |
| … **journaled**, 30 d | 983 | **137** | **983 — same rows** | 983 |
| journal rows whose reason names the wrong cause | 103 | **0** | **0** — first reason becomes `market already closed at decision time (settled <price>)` | 103 |
| journal volume | 5,588 / 3.19 d | **−103 → 5,485 (−1.8 %)** | **unchanged at 5,588 — 103 rows keep their slot, first reason rewritten** | 5,588 |
| sub-0.05 near-certainty cohort (post-fix) | 182 | **172** | 172 | 182 |
| near-certainty cohort, all rows (post-fix) | 1,991 | **1,888** | 1,888 | 1,991 |
| rows storing a settled 0/1 as `detectedPrice` | 103 | **0 — wallet print kept** | 103 (unchanged) | 103 |
| admissions (legs booked on those decisions) | 0 | **0** | 0 | 0 |
| longshot-shadow rows at `entryPrice 0` (lifetime) | 536 | stops growing | stops growing | grows ~10/3 d |

## Why (a), not (b)

1. **The row was never a candidate.** `scripts/monitor-trades.ts:166-169` already states the
   convention for that: an observation-only row *"keeps the wallet's own fill price … these rows can
   never be copied"*. Marking a print that arrived after settlement `observationOnly` restores the
   invariant the file already documents, instead of inventing a second one.
2. **Only intake can keep a truthful price.** `detectedPrice` is written by the monitor's fetch. Under
   (a) it stays the wallet's print (0.1731–0.71). Under (b) the stored value is already the settled
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
at the detected-price assignment only:

```
+ let marketClosed = false;   // declared next to isBlankMarket, before the try: the write block reads it
 const m = await adapter.fetchMarket(t.marketId);
+ // t_d246fc66 (Lane A, pending the a/b/c yes — NOT approved): a print that arrives after the venue
+ // closed the market is not a candidate — the payload's quotes are settlement values, not a book.
+ // keep the row, stamp it inert, count it, never price it. Can only REMOVE admissions, so it cannot
+ // trip the ordering hazard the comment above documents.
+ if (m.resolved === true) marketClosed = true;
 // price-side-inversion (2026-11-09, user-approved): ...
- const p = priceForOutcome(m, t.outcome);
- if (p !== undefined) detectedPrice = p;
+ // t_d246fc66: PRICE-ONLY guard. The MarketSnapshot write below stays unconditional for these
+ // rows (see "Blast radius"): it is a shared table and suppressing it is a separate decision.
+ if (!marketClosed) {
+   const p = priceForOutcome(m, t.outcome);
+   if (p !== undefined) detectedPrice = p;
+ }
 await prisma.marketSnapshot.create({ ... });   // unchanged, all copy-eligible fills
```

and at the write: `observationOnly: w.observationOnly || isBlankMarket || marketClosed`, `detectedPrice`
left as the `let detectedPrice = t.price` initialised at :170 (no ternary — the guard is price-only, so
the wallet's own print is already the value), plus `closedMarket++` and a
`[CLOSED-MARKET] N row(s) stored observationOnly — market already resolved at ingest (price-only:
MarketSnapshot kept)` line next to `[BLANK-MARKET]`, so the event is counted, not silent — and so the
next reader can tell this guard from a blank-market one by what it says it touched.

The **run counters have to move with the write**, or the run log and the DB disagree about the same
row (review round 3). `scripts/monitor-trades.ts:233-234` decides what the run summary calls
`copy-eligible`, and the summary at `:271-272` prints it:

```
  let blankMarket = 0;                        // :58
+ let closedMarket = 0;                       // :58, next to it
  ...
  if (isBlankMarket) blankMarket++;           // :232
+ if (marketClosed) closedMarket++;           // counted on its own, like blankMarket
- if (w.observationOnly || isBlankMarket) newObserved++;
+ if (w.observationOnly || isBlankMarket || marketClosed) newObserved++;
  else newTrades++;                           // :233-234
```

Without the third term every closed-market row is stored `observationOnly` (so `score-trades.ts` never
sees it) while `Trade monitor complete: … (${newTrades} copy-eligible, ${newObserved} observation-only)`
counts it as copy-eligible — a log line asserting a decision the DB contradicts, which is the exact
defect class this card exists to remove. `[CLOSED-MARKET]` and `blankMarket` are independent counters
(a row is never both: blank rows have no marketId to fetch), so neither shadows the other.

**Blast radius, stated rather than implied (review round 1).** The guard changes exactly one column
on `ObservedTrade`: `detectedPrice` falls back to the wallet's own print. It does **not** touch:

* **`MarketSnapshot`** — the write stays where it is and still fires once per copy-eligible fill,
  including the closed-market ones (≈103 / 3.19 d, one per fill, no extra fetch). Wrapping it in
  `if (!marketClosed)` was in the first draft of this sketch and is *wrong*: that table is read by
  production code that takes the **latest** snapshot per market — `open-mtm-horizon.ts:437` (the
  unrealised-PnL horizon the daily report quotes) and `rule-updater.ts:53` (latest snapshot per
  resolved sample), plus the hygiene rank reads (`scripts/market-hygiene-rank-read.ts`). Suppressing
  a fill's snapshot changes which row is "latest" for that market, i.e. it is a silent, unmeasured
  change to a shared table in a card about the journal's wording.
* **the fetch** — `adapter.fetchMarket()` already happens on every copy-eligible fill before the
  guard can run, so there is no cost saving and no new request.
* **the journal decision** — the row is `observationOnly`, so `score-trades.ts` never sees it; the
  "admissions change: 0" claim is unchanged either way.

Guard on **`m.resolved`** (the adapter already derives it: `closed === true || umaResolutionStatus ===
"resolved"`), **not** on `ttr === 0`. The zero-TTR population is not the closed population: 955
post-fix decisions carry `resolves in 0.0h` and only **52** of them are closed — the other **903 are
in-play markets trading past their end date**, where the reason is true and the book is live (30 d:
3,975 rows, 793 closed, 3,182 live). A `ttr`-based guard would relabel 903 true rows to catch 52.

**`m.resolved` vs the card's literal trigger — measured, not assumed (review round 3).** The card says
*"`closed` or `closedTime <= now`"*; the sketch tests `m.resolved`, which additionally accepts
`umaResolutionStatus === "resolved"`. The only rows where the two could differ are markets whose
`closed` flag is false/absent while a **readable** `closedTime` is already ≤ the ingest clock. Measured
read-only against `data/nearcert-market-meta.json` (own parser, 5-digit fractions padded to six),
per decision rather than per market. The cells are emitted by the instrument
(`windows.<name>.trigger_check`, plus a cache-wide `trigger_audit`), so they are re-runnable like every
other figure here; the run below is `read_at 2026-11-12T20:22:00Z`:

| window | decisions | `closed` flag true | `closed` flag false | of those: readable `closedTime` | clock **≤ decision** | clock **≤ ingest → guard gap** | uncached |
|---|---|---|---|---|---|---|---|
| post-fix 3.19 d | 5,588 | 3,789 | 1,799 | 0 | 0 | **0** | 0 |
| trailing 30 d | 36,655 | 34,839 | 1,219 | 0 | 0 | **0** | 597 |
| pre_days 7 d | 13,589 | 10,699 | 2,890 | 0 | 0 | **0** | 0 |

and cache-wide (`trigger_audit`): 8,899 labelled markets, **7,438** with `closed: true`, **7,438** with a
readable `closedTime`, **0** with a readable clock but the flag false, **0** with the flag true but no
clock. 81 markets carry `closedTime: null` — all of them open markets, so they are not a gap either.

So the substitution is **empty on this population**: the venue ships no `closedTime` for a market it has
not flagged, and no row is lost by testing `resolved` instead of the literal pair. One honest limit: the
slim label cache keeps only `outcomes`/`outcomePrices`/`closed`/`closedTime`, so this audits the
`closed` half of `resolved`, not `umaResolutionStatus` — a market the venue resolved through UMA alone
would appear above as a readable clock with the flag false, which is exactly the column that reads 0. It
stays a deviation worth one paragraph rather than a silent one — if the venue ever starts publishing a
`closedTime` ahead of its `closed` flag, the guard should be widened, and this table is the check that
would show it.

## Refutation / re-read (what would prove this wrong)

The check has to run on a window that **starts at the guard's ship timestamp**: every row already
journaled keeps reading `post-close` forever, so an unanchored window can neither confirm nor refute
it. Review round 2 caught that the first draft told the reader to run `--pre-days 7` on this script
while only the *upstream* script parsed that flag — here it was silently ignored and the run returned
the frozen windows unchanged. The instrument now implements both the window and its anchor.

Ship at time `T`, then **7 days later**:

```
python3 scripts/closed-market-skip-taxonomy.py --pre-days 7 --ship-at <T> --fetch-window pre_days
```

* `--pre-days 7` adds a `pre_days` window and prints its own clock —
  `windows.pre_days.start_utc`/`end_utc` and `pre_days.window_start_utc`/`window_end_utc`.
* `--ship-at T` clamps that window to `[max(now − 7 d, T), now)` and sets
  `pre_days.valid_confirmation_window: true`; `pre_days.excluded_pre_ship_decisions` reports how many
  pre-guard decisions the clamp kept out, so nothing is silently dropped.
* `--fetch-window pre_days` scopes the label fetch to that window's missing markets, so a re-read
  cannot go hunting labels for the frozen windows. The cache is shared, so a label it does fetch can
  also resolve a row in another window: this run moved 6 previously-`uncached` rows in `post` and 9 in
  `post_now` into `live` and moved **no headline figure** (`post` 103 / 5,588 and `d30` 983 / 36,655
  byte-identical apart from the read clock); d30 was not touched at all.
* The run is **only** a confirmation when `pre_days.valid_confirmation_window` is `true` **and**
  `pre_days.uncached_rows` is `0`; either condition can hold it `false` and `pre_days.note` says which.

**Run today, unanchored** (the committed artifact `data/closed-market-skip-taxonomy.json`,
`read_at 2026-11-12T20:22:00Z`): window `2026-11-05T20:22:00Z .. 2026-11-12T20:22:00Z`
(`read_at − 7 d` on every run), 13,589 decisions, **105 post-close**,
`anchored_at_ship: false`, `valid_confirmation_window: false`, `uncached_rows: 0`. Those 105 are the
frozen pre-ship rows — the class the guard exists to stop stamping — reported as a measurement and
explicitly **not** as a confirmation. (The window is `now − 7 d`, so this count moves with the clock:
13,588 at the 20:12Z read, 13,589 at 20:22Z.)

**Mechanics check with a synthetic anchor** (scratch copy, real DB, `--no-fetch`, anchor
`2026-11-07T00:00:00Z`, inside the span): window `2026-11-07T00:00:00Z .. 2026-11-12T20:20:56Z`,
`excluded_pre_ship_decisions: 1919`, `valid_confirmation_window: true`, 11,670 decisions,
**105 post-close / `caught_at_intake` 105**. So the anchored path works *and* can fail — which is the
property the pre-registered check needs. Anchored at a pre-guard instant it reports the 105; anchored
at the real ship time it should report 0.

* **confirms** if `windows.pre_days.post_close.decisions` = 0 and
  `windows.pre_days.post_close.option_coverage.caught_at_intake` = 0, with admissions unchanged
  (`legs_booked_on_post_close` 0 before and after);
* **refutes** if any decision in the anchored window still stores `detectedPrice ∈ {0, 1}` on a
  market closed at ingest, or `option_coverage.scoring_only` exceeds 0.5 % of the window's decisions —
  then (b) ships as well.

Bad arguments fail loudly rather than being ignored: `--pre-days heck`, `--pre-days 0`, `--ship-at`
without `--pre-days`, and an unreadable `--ship-at` each exit with a message (round 2's defect was
exactly a silently ignored flag).

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
pinned by twelve self-test lines — including the five-digit-fraction case that broke both this read and
the upstream one, the wallet-print cell's pooled-vs-per-group minimum that review round 1 broke, the
three that pin the re-read window (an unanchored `--pre-days` is never a confirmation; `--ship-at` clamps
the start forward; an anchor older than the span still yields a window with nothing pre-ship inside), and
the trigger-gap classifier (`trigger_disagreement()`) that review round 3 added with the audit table.
The wallet-print cell (§2) is `post_close.wallet_entry_price` = `{n, min, max, mean, below_0_34,
by_detected_price_group{0.0,1.0,other}}`, computed by `wallet_print_stats()` in the instrument — so
that cell is re-runnable like every other figure in this write-up. The trigger comparison (§ the
`m.resolved` paragraph) is emitted too, not hand-counted: `windows.<name>.trigger_check` per window and
a one-off `trigger_audit` over the whole label cache, both added in review round 3 for the same reason —
a published cell should be a cell the script prints.

```
python3 scripts/closed-market-skip-taxonomy.py --no-fetch        # no network, cached labels
python3 scripts/closed-market-skip-taxonomy.py --fetch-cap 4000  # refresh missing market labels
python3 scripts/closed-market-skip-taxonomy.py --pre-days 7 --ship-at <T> --fetch-window pre_days
                                                                 # the post-ship check (§ Refutation)
```

Nothing in the trade path was touched: no rule, gate, band, size or exit changed; no `apply-vNN`; the
DB was opened read-only.
