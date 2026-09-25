# Backtesting engine + training-data platform — design (Polymarket + Kalshi)

**Date:** 2026-09-25 · **Status:** DESIGN — nothing implemented, no live-path change · **Scope:** measurement/research infrastructure (new `~/pm-backtest/` stack, read-only against `prisma/dev.db`)
**Requested by:** Xman — "a full backtesting engine for both Polymarket and Kalshi, along with dataset recommendations… built with two goals: (1) pure backtesting, (2) training an AI model for trade decisioning and automated quantitative trading."
**Constraint in force:** the Kelly measurement window is frozen through **2026-10-08**. Data acquisition and storage are observability (allowed now); anything that changes a rule, a size, a gate or a published number is not.

---

## 0. Verdict up front

**We cannot backtest today, and the reason is not the engine — it is the data.** Three measured facts decide the whole design:

1. **Both venues expose a rolling window, not an archive.** Polymarket `/prices-history` is reachable arbitrarily far back **but capped at ~145–180 rows per request**, so history must be *paged* (≤1 day at 10-min, ≤3 h at 1-min fidelity). Kalshi's keyless trade tape **only reaches back to ~2026-07-18** (binary-searched today) — roughly a 10-week rolling window. **Every day we do not capture is data that no longer exists anywhere.** Data acquisition is therefore the critical path, and it is the one piece that can start *now*, during the freeze, because it changes no rule.
2. **Our own corpus is not a market archive.** `MarketSnapshot`'s 15.2M rows are a side effect of wallet-following (`scripts/monitor-trades.ts:103`): the universe it covers collapsed from **2,773 distinct markets/day (Sep 17) to 114 (Sep 25)**. `data/l2/` holds 9.6 GB of 5-second books, but its **trade-print path produces zero prints** (verified: 0 `"t":` lines in 300 files) and its universe is "markets we happened to be watching" capped at 25 concurrent. Neither can serve as the price-history layer. The price layer must come from the venues' APIs, keyed by token/ticker, not from our tables.
3. **The labels we already store are fiction for training.** The paper ledger books C-200 entries at `intent − $0.02` (a maker assumption worth **$1,525.76 of $2,534.58 = 60%** of C-200 PnL) and charges **no fees** (measured drag: gross +$5,397.60 → net +$2,933.77, 238 winner→loser flips, C-200 negative under every fee assumption). A model trained on stored `realizedPnl` learns the fill fiction and the missing vig. **Labels must come from the simulator, under a declared fill tier, never from `PaperTrade.realizedPnl`.**

**Key architectural insight:** the engine is **two-level**, and the levels must be kept apart.
- **Level 1 — Replay (exact, cheap, trustworthy):** the event stream is our *recorded* `DecisionJournal` rows (307,726 of them, each carrying every gate's verdict in `risksJson` and its `ruleSetVersion`). We do not re-derive admission; we re-price, re-size, re-gate and re-exit. This reproduces the live book, and is the acceptance test.
- **Level 2 — Counterfactual policy (the actual backtester):** a policy module that re-derives admission for populations we never traded (the 222k skips, the whole market universe). **Hard rule: Level 2 configured with the live RuleSet must reproduce Level 1's journal output on the same rows**, or it is not measuring the strategy — it is measuring a reimplementation bug.

Both goals (research backtesting, ML training) share **one** dataset and **one** simulator; they differ only in what they optimize (a reported PnL with CIs vs. a fitted function). Building them as two systems is how you get a model whose training distribution no longer matches the backtest.

---

## 1. What exists today (measured on this machine, 2026-09-25)

| Artifact | Reality | Usable as backtest substrate? |
|---|---|---|
| `PaperTrade` | 12,155 rows (12,063 PM / 92 Kalshi), 2026-06-18 → now | ✅ as *decisions*; ❌ as labels (fill + fee fiction) |
| `DecisionJournal` | 307,726 rows, era-tagged `ruleSetVersion` v1–v60 (63% from v1–v3) | ✅ **the Level-1 event stream** |
| `ObservedTrade` | 451,966 rows, `observationOnly` split since v61 | ✅ copy-signal source; ⚠️ post-hoc wallet joins |
| `MarketSnapshot` | 15.2M rows / 42,032 marketIds, 2026-07-14 → now, universe collapsing 2,773→114 markets/day | ⚠️ partial, non-stationary, wallet-driven |
| `data/l2/` | 35,966 files · 9.6 GB · since 2026-08-31 (~26 d) · 5 s top-25 books · 4,678 assets mapped | ✅ depth/fill realism **only for the recent window**; ❌ trade prints (0 found) |
| `OutcomeReview` | 3,792 rows (1 h/6 h/24 h marks + final outcome) | ✅ markout labels (bounded) |
| `RuleSet` | 60 versions with apply timestamps | ✅ **the era map** — every split is done through it |
| Existing harnesses | `shadow-expectancy-model.py` (walk-forward), `replay-market-cap.ts`, `replay-slug-cap-basis.ts`, `kelly-window-counterfactual.ts`, `skip-edge-probe.py`, `kalshi-shadow.py` | ✅ methodology precedent; ❌ none is a general engine (all re-rank/re-gate rows we already traded) |

**The six gaps that block backtesting:**

1. No venue-agnostic price/tape archive — we have no way to price a decision on a market we never watched.
2. No fee model in the ledger (measured 45.6% optimism).
3. No fill model — one global 2¢ maker assumption, applied to one lane, unvalidated.
4. No policy module — gates live inline in `score-trades.ts` (≈1,000 lines); they cannot be re-run over history.
5. No point-in-time feature store — `WalletProfile` columns are live snapshots (and `resolvedTradeCount30d` is clamped at 100, `tradeCount30d` at 200), so any join leaks the future.
6. No evaluation discipline as code — the split doctrine (`ml-doctrine-time-and-era-splits`) is carded but the shared helper does not exist; every script re-invents folds.

---

## 2. Verified data surface (probed live today — this is what the dataset can be built from)

### 2a. Polymarket — keyless, **retro-reachable, paginated**

| Endpoint | Verified result today | Use |
|---|---|---|
| `clob.polymarket.com/prices-history?market=<tokenId>&startTs&endTs&fidelity=N` | ✅ arbitrary retro depth (**verified 365 d back**); **~145–180 rows per request** → page in ≤1 d chunks at `fidelity=10`, ≤3 h at `fidelity=1`; 1-min bars exist for historical windows (verified 100 d back, 60 s spacing). Quirk: a `fidelity=1` request can append a stray live point → **validate timestamps against the requested window** and drop outliers. Needs a browser UA. | **the price layer** |
| `data-api.polymarket.com/trades?market=<conditionId>` / `?user=<wallet>` | ✅ trade tape: `proxyWallet, side, asset, size, price, timestamp, conditionId, slug` | **the copy-trade tape** — reconstruct any wallet's history, not just the ones we tracked |
| `data-api.polymarket.com/positions?user=<wallet>` | ✅ `avgPrice, initialValue, currentValue, entryFeesUsdc` | **fee ground truth** for calibrating the cost model |
| `gamma-api.polymarket.com/markets?closed=true` | ✅ resolved markets w/ `clobTokenIds`, `outcomes`, `outcomePrices`, `endDate` | **survivorship-free universe** |
| `gamma-api.polymarket.com/markets/keyset` | ✅ deep pagination (plain `offset` > ~50k → 422 "use /markets/keyset") | full universe enumeration |

### 2b. Kalshi — keyless, **but windowed and identity-blind**

| Endpoint | Verified result today | Use |
|---|---|---|
| `api.elections.kalshi.com/trade-api/v2/markets?status=settled&min_close_ts&max_close_ts` | ✅ settled universe: `expiration_value`, `floor_strike`, `last_price_dollars`, `open_interest_fp`, `close_time` | **settlement labels + universe** |
| `…/markets/trades?ticker=&min_ts=&max_ts=&limit=&cursor=` | ✅ **keyless — this is NEW** (the 2026-09-03 audit recorded `/trades?ticker=` as 404). Tape depth ≈ **2026-07-18 → now** (2026-06 and earlier return empty) | **the Kalshi tape — forward capture is mandatory** |
| `…/markets/{t}/{orderbook}`, `/events`, `/series` | ✅ live book (top-of-book only, dollar strings, `yes_dollars`/`no_dollars` both bid sides) | live/forward microstructure |
| candlesticks (both paths tried) | ❌ 404 — **no candle endpoint**; bars must be built from the tape | — |
| wallet attribution | ❌ never keyless — no per-wallet data exists | **Kalshi copy-trading is out of scope, permanently** |

> **Two asymmetries that shape the whole plan:** (i) Polymarket = *reconstruct the past*, Kalshi = *must record the future*; (ii) Polymarket supports copy/flow research, Kalshi supports only market-level strategies (favorite-longshot, cross-venue parity, market making).

---

## 3. Dataset recommendations

### Store design (all tiers)

- **Format:** Parquet, Hive-partitioned (`venue=/kind=/date=/`), ZSTD, **one row group per day**; a **DuckDB catalog** (`catalog.duckdb`) over the Parquet root as the query surface. Rationale: 10× cheaper than SQLite for column scans, and DuckDB reads our SQLite directly when needed.
- **Manifest discipline:** every dataset gets `manifest.json` = {source URL pattern, fetch params, row count, sha256, min/max ts, coverage gaps, schema version}. A backtest run records the manifest hashes it used → **every result is reproducible from hashes, not from "what was on disk that day."**
- **Immutability:** append-only partitions. Corrections land as `*_rev2` partitions + a tombstone list, never in-place edits (mirrors the `data/phase-streak-log.jsonl` as-recorded doctrine).
- **Retention/volume:** PM price layer 10-min bars ≈ **144 rows/market-day** → 1M market-days ≈ 144M rows ≈ 3–5 GB Parquet. Kalshi tape ≈ 0.5–2 GB/yr at 497-contract print scale. L2 is the only heavy tier (9.6 GB/26 d ≈ **135 GB/yr at current universe; ~2–4 GB/day if the universe is widened**) → compress on write, keep **90 days hot + monthly rollups cold**.
- **Location:** hot on the Mac mini's local SSD; cold tier on the storage fabric (`192.168.30.0/24`) once the Mellanox/Arista path is in production use. Do not put L2 hot path on NFS.

### D1 — Market universe & metadata (Venue: both)

- **PM:** enumerate via `gamma /markets/keyset` (all statuses) + `/markets?closed=true` for resolved; store `marketId, conditionId, clobTokenIds[2], question, slug, category/tags, outcomes, endDate, closedAt, umaResolutionStatus, volume, liquidity`. **This is the survivorship control** — the universe is defined by what *existed*, not by what our funnel saw.
- **Kalshi:** `/series` → `/events` → `/markets` (all statuses, `min_close_ts/max_close_ts` windows) + settled pull. Store `ticker, event_ticker, series_ticker, market_type, floor_strike/cap_strike, open_time, close_time, expiration_value, result`.
- **Cross-venue link table** (`link.csv`): `pm_conditionId ↔ kalshi_ticker`, confidence + method (token overlap on normalized question via the existing `kalshi-slug-matcher.py` / sidecar matcher doctrine: similarity ladder, both-sides-agree, ambiguity margin → NULL rather than a guess). Needed for parity strategies and cross-venue features.
- **Cadence:** universe diff daily; settlement fields re-pulled until terminal (resolutions can be proposed → disputed → final).

### D2 — Price history (the load-bearing dataset)

- **PM:** for every token in the universe, page `prices-history` at `fidelity=10` (backfill) + daily incremental (last 24 h at `fidelity=1`, then downsample). Store `tokenId, ts, p, fidelity, source_window`.
  - **Scoping is required** — cost is linear in markets × days × pages. Concrete: **4,678 assets already in `data/l2-asset-map.jsonl` × 30 days = ~140k requests ≈ 20 h at 0.5 s pacing.** Tier A = every token our funnel ever touched (from `DecisionJournal`/`ObservedTrade`/L2 map); Tier B = all markets live in the rolling 30-day window (incremental only); Tier C = a stratified sample of resolved markets for calibration studies.
  - **Resolution grid is a constraint, not a preference:** 1-min exists only by request and only in ≤3 h windows; anything multi-month is 10-min unless paged obsessively. Declare the grid per dataset (`price_grid` in the manifest) and forbid mixing grids in one comparison.
- **Kalshi:** tape-derived bars, `fidelity=1m`, forward-only (see D3).
- **Our own history, converted:** `MarketSnapshot` is *not* the price layer, but it is the only record of *what our funnel saw at decision time* — export it as-is for point-in-time feature reconstruction (D6), clearly labelled "wallet-following support, non-stationary".

### D3 — Trade tape

- **PM:** `data-api/trades` by market (every market in the universe) **and by wallet** (every wallet that ever appeared in `WalletProfile`/`ObservedTrade`, plus leaderboard cohorts). This is what makes copy-trading research possible on wallets we never tracked — the current stack can only study wallets it happened to follow.
- **Kalshi:** hourly forward capture of `/markets/trades` over rolling 6-hour windows (`min_ts/max_ts`, cursor pagination), dedup on `trade_id`. **Start this before anything else in this document** — the window is ~10 weeks and rolling.
- **L2 prints:** fix or delete the print path — it currently emits nothing (0 in 300 files). The venue tape above is a complete substitute and is retro-fetchable, so the L2 trade-print path is **not** on the critical path; leave it broken and stop advertising it as the fill-model input.

### D4 — Order-book depth (L2)

- Keep `record-l2.ts` as-is (5 s, top-25) but (a) **widen `MAX_MARKETS`** and (b) fix the print path or drop it. Depth is what converts "assumed slippage" into "measured slippage", and it only exists for the recent window, so it is a **Tier-2 fidelity asset that accrues value**: every day of coverage makes future backtests more honest. Suggested: 25 → 100 concurrent markets, prioritizing open positions × the top-volume universe, with per-asset downsampling to 15 s after resolution.

### D5 — Decision/label export (our own book)

Parquet export of `DecisionJournal ⨝ PaperTrade ⨝ OutcomeReview ⨝ (RuleSet era)` with:
- every gate verdict and `risksJson` (already stored since the 2026-09-15 fix),
- `rawConfidence` / `adjustedCopyScore` (the values the gates actually saw),
- `ruleSetVersion` + `era` + `policy_hash`,
- **dedupe key = `(decisionJournalId, marketId, outcome)`** — duplicate-accumulation rows inflate N and every z-stat (measured precedent: 1,473 raw rows vs 785 decisions),
- `observationOnly` filtering applied at export (never re-decided downstream),
- **`realizedPnl` kept but gated**: exported as `pnl_ledger` (for reconciliation only) alongside `pnl_sim_<tier>` (the simulator's, for training).

### D6 — Point-in-time feature store (the ML substrate)

One row per **decision event** (Level 1) or per **candidate event** (Level 2 universe), column groups:

| group | contents | point-in-time rule |
|---|---|---|
| market | price at t, best bid/ask, spread, TTR, liquidity, volume, category class/fine, token/condition ids | from D2/D4 at `t−ε`; no forward fills |
| microstructure | book slope/depth-at-size, recent print flow, realized vol over 5 m/1 h/24 h, drift | L2 where available, else tape-derived (Tier flag) |
| signal | wallet's entry price/size/side, detected-vs-entry latency, wallet age/tracked status **as-of-entry**, observation-only flag | wallet fields must be archived snapshots (see §7 pitfall) |
| cross-venue | Kalshi parity price for the same event, PM−Kalshi spread, venue liquidity ratio | NULL when no link (no imputation) |
| policy-era | `ruleSetVersion`, which gates fired, `policy_hash` | **never a raw version integer as a feature** — map to the gate-parameter vector or exclude |
| text | question embedding (if pursued) | embed at ingest, version the embedder |

### D7 — Reference data

- `rules_history.parquet`: every RuleSet version denormalized to a flat gate-parameter vector + apply timestamp (built from `RuleSet.rulesJson` + `RuleChange`) — the era map for splits *and* the "what policy was live at t" lookup.
- `fee_model.json`, `fill_model.json`: versioned cost/fill parameters with the calibration evidence and date (see §5).
- `calibration_surface.parquet`: the (price × τ) realized-win-rate surface (the TiernanGeary methodology) — the honest benchmark any ML model must beat.

---

## 4. Engine architecture

```
~/pm-backtest/
  data/     ingest/     pm_clob.py  pm_data_api.py  pm_gamma.py  kalshi.py
            store/      parquet_writer.py  manifest.py  catalog.duckdb
            export/     db_export.py  l2_export.py  rules_export.py
  sim/      venue/      polymarket.py  kalshi.py        # instrument specs, fees, tick sizes
            exec/       fills.py  slippage.py  latency.py
            book/       l2_replay.py  tape_bars.py
            portfolio/  sizing.py  caps.py  drawdown.py   # ports of exposure-cap/wallet-cap/kelly
            policy/     gates.py  rules_engine.py          # Level-2: Python port of the live gates
            engine.py                                        # event loop: tick → decide → size → fill → mark → settle
  replay/   level1.py    # drives the engine from RECORDED DecisionJournal rows (exactness lane)
  eval/     splits.py  metrics.py  bootstrap.py  deflated.py  reconcile.py
  ml/       features.py  labels.py  train.py  predict.py
  shadow/   feed.py  mark.py                             # writes shadow-*.jsonl + mark-to-settlement
  cli.py    (backtest | replay | reconcile | train | shadow-mark | ingest-*)
```

**Event loop:** time-ordered cursor over (tape ∪ book ∪ decision) events → *policy* (L1: read recorded; L2: evaluate gates) → *sizing* (the live sizer, ported and parity-tested) → *fill* (venue fill model at declared tier) → *marks* (book/tape) → *exit rules* → *settle* (venue resolution) → *ledger* (net of fees) → analytics.

**Language:** Python 3.11 (own venv, matching `venv-calib` precedent) — the ML goal makes this non-negotiable, and DuckDB/pandas/numpy/sklearn/lightgbm do the heavy work. **The live stack stays Node/Rust.** The contract between them is files + JSONL, exactly like the existing shadow feeds.

**Why not adopt an off-the-shelf framework:** `evan-kolberg/prediction-market-backtesting` is **NOASSERTION** (= no license grant → read-only) and drags NautilusTrader into a Node/Rust stack; general backtesters (vectorbt/LEAN) model continuous-price instruments with fee schedules, not binary resolution markets where a position's terminal payoff is 0 or 1 and *settlement* — not a sell — closes the trade. Our instrument semantics are the differentiating part; adopt ideas (`leakage checklists`, A/B cutover harness with a machine verdict, expected-vs-observed forward loop), not dependencies.

---

## 5. Execution & cost models (per venue, versioned)

**Polymarket fee (official form):** `fee = C × rate × p × (1−p)`; makers 0 (+25% rebate on politics); taker rates politics/finance/tech 0.04, sports/econ/culture/weather/other 0.05, crypto 0.07, geopolitics 0. **Calibrate, don't assume:** `data-api/positions.entryFeesUsdc` gives real per-position fees → fit `rate` per category against actuals. Our own fee measurement stands as the baseline (gross +$5,397.60 → net +$2,933.77 at flat 0.04/0.05 mix).

**Kalshi fee:** taker ≈ `ceil(0.07 × C × P × (1−P))`, maker ≈ `0.0175 × C × P × (1−P)` per the published July-2026 schedule (**must be confirmed against a real fill** — our only Kalshi fills are the 92 phantom-priced rows, so confirm on the first real one or drop to the conservative taker form).

**Fills — three declared tiers** (every result prints its tier):

| tier | entry price | slippage source | available | use |
|---|---|---|---|---|
| **T1 — bar** | bar price + half-spread | none | all history | breadth studies, calibration |
| **T2 — tape** | walk recent prints/quote tape | empirical volume-at-price | since 2026-07-18 (Kalshi) / trading-tape depth (PM) | strategy PnL, most work |
| **T3 — L2** | walk the actual ask ladder for the order size | measured depth | PM since 2026-08-31 (own books) | capacity, fill-probability, execution tuning |

- **Maker modelling:** our C-200 assumption (`intent − $0.02`) is an *assumption*, not a measurement. Ship `maker_fill_prob(P, Δt, book state)` (the Phase D2 / homerun fill-simulator design) and keep the 2¢ as a labelled sensitivity variant. Until then, **every backtest reports both "as-booked maker" and "taker" PnL**, so the 60%-of-PnL assumption is always visible.
- **Slippage honesty rule:** if the tier cannot measure slippage, the result must state the assumed spread and carry a sensitivity band, never a point PnL.

---

## 6. Correctness: what "this engine works" means

Non-negotiable acceptance tests, in order:

1. **Reconciliation (L1):** replay every recorded decision with recorded fills → reproduces `PaperTrade.realizedPnl` **exactly** (exit path re-run through the same exit rules), and reproduces the venue/status mix. Any residual is attributed and *named* (fill model delta, fee delta, resolution delta) in a reconciliation report.
2. **Known counterfactual reproduction:** the engine re-derives results we already trust — `v55` per-market ceiling (`replay-market-cap.ts`: 298 legs → 13 blocked / $283.12 notional / −$144.01 PnL delta), the `v57-B` rail (−51% stake / −62% booked loss), the Kelly-window rail. Matching these within rounding is the test that the sim's gate port is faithful.
3. **Ledger invariants:** `closed_at XOR resolved_at` semantics respected; realized PnL on early exits booked at close, natural resolutions at `resolvedAt`; the same accounting the live stack uses.
4. **Leakage tests (automated):** a feature-audit job asserts every column carries `as_of ≤ decision_ts` and that shuffled-label and future-window ablations collapse to noise. A model that "works" under label shuffling is broken, not brilliant.
5. **Determinism:** same manifest hashes + same seed ⇒ byte-identical output.

---

## 7. ML track — training, evaluation, and the road to automated decisioning

**Labels (from the simulator, never from the ledger).** Primary: `net_return = (terminal_or_exit_value − cost − fees − slippage) / staked`, per decision. Secondary: `edge_vs_price = net_return − price_implied_return` (the honest baseline from `ml1-target-net-pnl-and-price-baseline`), plus markout labels (1 h/6 h/24 h) for short-horizon decisioning, plus a binning for classification (top-tercile edge) if a ranker is wanted.

**Splits (as carded):** time-ordered expanding walk-forward with purged embargo (drop decisions whose market resolves inside the next fold's window), era-aware by `ruleSetVersion`, **market-clustered bootstrap** for CIs, and no random row folds anywhere. Precedent to copy: the existing `shadow-expectancy-model.py` decision-time feature set (excludes `WalletProfile`, which is live-valued).

**Evaluation (what makes a model admissible):**
- rank IC (predicted vs realized edge) **and** net EV per $ staked on the OOS slice, with market-clustered CIs;
- **beat the price-only baseline and the incumbent `copyScore`** — measured today the incumbent is worse than guessing: top-30% by `copyScore` kept −18.0% ROI while the rows it rejected made **+$966.41** (2026-09-13 walk-forward);
- deflated Sharpe / PBO for any sizing claim; capacity from T3 depth;
- **expected-vs-observed forward loop** (the Gurdiel07 pattern flagged in the scoring-repos audit and never carded): persist expected metrics at fit time, then compare against realized forward results as the permanent gap metric.

**Honest state of the current model:** fitted 2026-09-20 (n=1,825), in-sample selected slice **+18.0% ROI**, and the only honest forward read (`oosSinceFit`, n=70 / 56 settled) is **−29.84% ROI vs −50.37% for the rejected slice** — i.e. the model still sorts better than the incumbent but both slices are losing. Nothing may be promoted on the in-sample number.

**Promotion path to automated decisioning (each step user-approved, none during the freeze):** fitted model → **write-only shadow feed** (`shadow-score.jsonl` pattern, mark-to-settlement, OOS clock ≥30 settled and positive net EV with CI clearing zero) → **advisory sizing** (recommendations in the daily report) → **shadow-sized paper lane** (parallel to C-200, no capital effect) → **live lane at fraction-of-Kelly with the exposure rails**, governed by the existing milestone ladder (7 consecutive days at goal to advance).

---

## 8. Reality checks — the biases this engine must not launder

1. **Selection into our own data.** Every row we own was let through by a gate; a model trained on it inherits the gate's support. Fix: Level-2 candidate populations (the 77,353-label skip set + the full universe), never our book alone.
2. **Selection into L2.** L2 covers what our pipeline looked at (25 concurrent, rotating). Never treat L2 as a random sample of the book; report the coverage, and use the venue tape for breadth.
3. **Fill fiction.** The 2¢ maker-improvement assumption is 60% of C-200 PnL. Report both variants, always.
4. **Fee blindness.** 45.6% of gross PnL at the current mix. Every number in every artifact is net, or explicitly marked gross.
5. **Already-decided markets.** 37% of skip-probe rows were already decided at entry (mean price 0.867). Any "edge" concentrated in near-terminal prices is a labelling artifact, not alpha.
6. **Duplicate accumulation.** Rows, not decisions, inflate N and every z-stat. Dedupe at export.
7. **Era mixing.** 63% of the label set is v1–v3 policy output; "the strategy" is not one thing across 60 rulesets. Split by era or state that you didn't.
8. **Clamped/leaky wallet fields.** `resolvedTradeCount30d` is clamped at 100, `tradeCount30d` at 200, and both are live values — as-of-entry measures must be derived from the tape.
9. **Survivorship.** Universe from Gamma keyset / Kalshi settled pulls, never from markets we traded.
10. **Kalshi's identity wall.** No wallet attribution, ever → no Kalshi copy models; cross-venue work is parity/market-level only.
11. **Rolling windows.** Kalshi tape ≈ 10 weeks; PM price API is paged and lossy at 1-min depth. Coverage gaps are recorded in the manifest, and a backtest that spans a gap must say so.
12. **Day-boundary and convention traps.** Local vs UTC midnight (this has caused more false alarms than any bug), `closedAt` vs `resolvedAt`, DATETIME as Unix-ms. The engine uses one convention (UTC, epoch-ms) internally and prints both when reconciling against live reports.

---

## 9. Phasing, effort, and what is allowed now

| phase | work | when | effort |
|---|---|---|---|
| **P0 — Data acquisition** (startable **now**: observation-only, no rule/PnL/number change) | Kalshi tape forward recorder (hourly, rolling window) — **do first, it is irreplaceable**; PM universe enumeration + metadata; PM price-history pager (Tier A backfill); tape capture by market/wallet; L2 universe widen; Parquet + manifest + DuckDB catalog; `db_export.py` | now, during freeze | ~3–4 days |
| **P1 — Simulator + Level-1 replay** | venue specs, cost models, fill tiers T1/T2, portfolio/sizing ports, exit-rule replay, reconciliation + known-counterfactual tests | post-Oct-8 | ~5–7 days |
| **P2 — Level-2 policy + eval harness** | Python port of the gates with **parity vs recorded journal**; era-aware walk-forward; metrics/bootstrap/deflated; pre-registration hooks | post-Oct-8 | ~4–6 days |
| **P3 — ML lane** | feature store, label builder from simulator, trainer, shadow feed + mark-to-settlement, OOS clock, expected-vs-observed loop | after P1+P2 | ~4–6 days |
| **P4 — Automated decisioning** | advisory → shadow-sized lane → live lane under rails and the milestone ladder | only on OOS evidence + user approval | gated |

**Zero-risk items that should not wait:** the Kalshi tape recorder (window rolls off daily), the PM price pager, and the universe snapshots. Everything else can wait for the window close without losing anything.

---

## 10. Open decisions (recommendation FIRST)

1. **Scope of P0 catch-up — recommended: Kalshi tape recorder + PM universe/price pager + Parquet/manifest/catalog, started now.** Alternatives: (b) only the Kalshi tape (minimal), (c) full P0 including L2 widening to 100 markets (~2–4 GB/day).
2. **Universe breadth for the PM price backfill — recommended: Tier A now (every token our funnel touched, ~4,678 assets), Tier B incremental daily.** Alternatives: (b) Tier A only; (c) Tier A+B+C including a stratified resolved-market sample (~weeks of paging).
3. **Language/home — recommended: separate Python stack `~/pm-backtest/` with its own venv, file contract to the Node stack.** (Alternative: extend `scripts/` — rejected: the ML dependency set and the live-path isolation both argue against it.)
4. **Fill model doctrine — recommended: report maker-assumption and taker variants side by side and label both, until a measured fill-probability model exists.** (Alternative: pick one and hide the other — rejected; the 60% figure makes that a measurement-integrity failure.)
5. **Kalshi scope — recommended: market-level strategies only (favorite-longshot surface, cross-venue parity, EV screens), no copy-trade ML.** (No alternative exists: no keyless wallet attribution.)

---

## 11. Probe log (2026-09-25, all keyless, all read-only)

| probe | result |
|---|---|
| `clob.polymarket.com/prices-history?market=<id>&startTs&endTs&fidelity=10` | 1-day window honored 2/5/10/20/40/60/90/120/200/365 days back; **~145–180 rows/request cap** |
| `…&fidelity=1`, 3-hour windows | 60 s bars at 2 d / 30 d / **100 d** ago (n≈180); one request appended a stray live point → window validation required |
| `…&interval=max&fidelity=1` | clamped to 10-min bars (n=351) |
| `data-api.polymarket.com/trades?market=<conditionId>` | 200 — full tape row incl. `proxyWallet`, `conditionId`, `price`, `size`, `timestamp` |
| `data-api.polymarket.com/positions?user=<wallet>` | 200 — incl. `avgPrice`, `entryFeesUsdc` |
| `gamma-api.polymarket.com/markets?closed=true` | 200 — `clobTokenIds`, `outcomes`, `outcomePrices`, `endDate` |
| `gamma-api.polymarket.com/markets?offset=50000` | 422 → `/markets/keyset` for deep pagination |
| `api.elections.kalshi.com/…/markets?status=settled` | 200 — settlement fields present |
| `…/markets/trades?ticker=&min_ts=&max_ts=` | **200 — keyless (changed since the 2026-09-03 audit)**; earliest data ≈ **2026-07-18** |
| `…/markets/{t}/candlesticks`, `…/series/{s}/markets/{t}/candlesticks` | 404 both — no candles |
| own `data/l2/` (300 sampled files) | **0 trade-print lines**; book snapshots only |
| own DB | `MarketSnapshot` distinct markets/day 2,773 (09-17) → 114 (09-25); 15.2M rows total |

---

## 12. References

- `drafts/c200-taker-fee-measurement-2026-09-09.md` — fee-model baseline and the 45.6% optimism measurement.
- `drafts/attention-lead-test-design-20260918.md` — prior measured price-grid limits, L2 integrity flag, house execution rules.
- `drafts/scoring-repos-audit-20260913.md` — audit of ~25 scoring repos: near-zero demonstrated predictive power; the expected-vs-observed forward-test loop; `evan-kolberg/prediction-market-backtesting` license problem.
- TiernanGeary `polymarketbets` backtest methodology (cached): edge surface `edge(price, τ)`, Wilson CIs, isotonic calibration, temporal holdout, survivorship control, cost model, fractional Kelly.
- `data/roadmap.json` cards `ml-doctrine-time-and-era-splits`, `ml1-target-net-pnl-and-price-baseline`, `ml1b-band-readmission-test`, `phase-ml1`, `phase-d2-fill-model`, `phase-c`.
- Skill references: `exit-rules-and-sample-integrity.md` (dedupe, pre-apply replay), `outcome-resolution-and-labels.md` (label traps), `measurement-window-governance.md` (freeze, counterfactual integrity), `kalshi-api-surface-and-adapter-fix.md` (venue surface — the tape finding there is now superseded).

*No fabricated numbers: every figure in this document was read from this machine's DB/files or from a live probe whose result is recorded in §11.*
