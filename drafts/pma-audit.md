# Prediction-Market-Analysis Audit — jon-becker/prediction-market-analysis

**Status:** COMPLETE — 2026-08-31. Repo: github.com/jon-becker/prediction-market-analysis (MIT, 3.8k★, actively maintained — updated 2026-08-30). Cloned to /tmp/pma.
**What it is:** a Python framework (duckdb/parquet/matplotlib) for collecting + analyzing Polymarket & Kalshi data, bundled with **the largest publicly available dataset of PM market & trade data (36GiB compressed)** and ~25 statistically rigorous analysis scripts. Cites Becker 2026 "Microstructure of Wealth Transfer" (SSRN 7217640) + 10 other 2026 papers.

---

## 1. What's in it (verified from source)

- **Dataset (36GiB, R2 download `make setup`):** Kalshi markets + full trade history (API, cursor-based, prices in cents); Polymarket markets + full on-chain `OrderFilled` trade history (maker/taker, fees, asset ids) + legacy FPMM trades + block→time map. Resolved markets carry results.
- **Analysis scripts (~25):** win-rate-by-price calibration, calibration-by-bucket (Polymarket deciles), EV yes-vs-no at each price, maker vs taker excess returns (by price / category / direction / over time), maker-vs-taker gap, win rate by trade size (with 95% CIs), returns by hour of day (ET), VWAP by hour, mispricing by price, longshot volume share over time, meta stats, statistical tests (z/p per claim).
- **Methodology quality:** proper excess-return framing (`win_rate − price`), z-stats + p-values per bucket, trade-size CIs, category/venue splits. MIT — no license blocker (unlike Polyseer).
- **Indexers:** Kalshi API client (10 rps rate limit, cursor pagination, resumable parquet) + Polymarket API + Polygon blockchain indexer.

## 2. What's implementable for the copybot

| Item | Fit | Effort | Verdict |
|---|---|---|---|
| **Dataset → Phase C backtest material** | Cross-venue arb needs same-event markets on BOTH Polymarket and Kalshi with full trade histories + resolutions. The copybot's Kalshi leg has 73 trades — no data to validate invariants against. This dataset IS the validation set: exclusivity / YES+NO≠1 / implication violations can be backtested on ~2 years of both venues BEFORE building live. | 36GiB download + duckdb queries (~half day) | 🎯 **Implement — the single biggest win.** Turns Phase C from "build blind" into "validate then build" during its Sep 15–30 design window |
| **Calibration analysis pattern (excess return + z per price bucket)** | The copybot's daily reports bucket PnL and the λ̂ table does Wang calibration, but neither reports statistical significance per bucket. Porting the pattern onto dev.db (sqlite, own paper trades) gives significance-tested bucket edges — strengthens the biweekly calibration review. | ~half day | ✅ **Implement (port pattern to own data; ~80 lines of Python)** |
| **Returns-by-hour / VWAP-by-hour** | Answers *when* the copybot's copies are +EV (retail flows by hour). Runs on existing PaperTrade timestamps — no dataset needed. Feeds the daily report with an hourly heatmap. | ~2–3h | ✅ **Worth adding to the daily report pipeline** |
| **EV yes-vs-no asymmetry + maker/taker findings** | The copybot is a *taker* (crosses spread to copy). Vedova 2026 "Execution, not Information" + the maker/taker analyses quantify the spread/timing tax on takers — direct validation input for the premium overlay (λ̂) and a candidate Kalshi-maker strategy for Phase C. | read-only | ⚪ **Reference for Phase C design** |
| Kalshi API client | Cursor + rate-limit patterns; copybot already has a Kalshi adapter. | — | ⚪ Reference only |
| Blockchain indexers / CLI / parquet framework | Copybot runs sqlite + CLOB API + Next.js; on-chain replay adds nothing for paper trading. | — | ❌ Skip |

## 3. Recommendation

1. **Now (cheap):** port the calibration + returns-by-hour patterns onto `prisma/dev.db` — significance-tested bucket edges and an hourly heatmap for the daily Discord report. MIT, ~80 lines, no new infra.
2. **Phase C design window (Sep 15–30):** download the dataset (36GiB; or start with resolved Kalshi + matched Polymarket markets) and backtest the exclusivity/cross-market invariants. Phase C then ships with validated edge, not hope. This is also the "cross-venue divergence" data source parked in the evidence-aggregation audit (Metaforecast review) — the dataset is the live-API-free way to test it.
3. **Skip:** everything infra (indexers/blockchain/CLI) — different stack, no value.

## 4. Caveats

- 36GiB download needs disk + bandwidth; a filtered subset (finalized markets, both venues) suffices for arb backtests — the parquet globs make partial downloads easy.
- Dataset is a snapshot (fetched periodically); fine for backtests, not a live feed — live Phase C still needs the copybot's own adapters.
- Analysis scripts assume parquet; porting to sqlite means translating duckdb SQL (straightforward, the copybot's dev.db already stores DATETIME as Unix-ms ints).

---

## 5. Dataset verification + market-wide calibration baseline (2026-08-31)

**Download landed:** 50G extracted to `~/prediction-market-data/data` (Kalshi 3.9G: 769 market files, 7,214 trade files; Polymarket 46G: 40,454 trade files, 41 market files, legacy FPMM + blocks). Snapshot vintage: **2026-02-05** (R2 last-modified) — pre-bot-launch, ideal for invariant backtests. Baseline saved to `data/polymarket-calibration-baseline.{csv,json}` (market-wide win-rate-by-price over ~692M trades, via their `polymarket_win_rate_by_price` analysis).

**Sanity check — market-wide Polymarket calibration vs C-200 copied-trade edges:**

| Band | Market-wide excess (N=692M) | C-200 excess (N=1,009) | Relative edge |
|---|---|---|---|
| <0.20 | **−0.009** (longshot bias: slightly overpriced) | **+0.367** (z=4.9) | **+37.6pp — whale alpha, not bias** |
| 0.20–0.40 | −0.013 | +0.098 (z=2.8) | +11.1pp |
| 0.40–0.60 | −0.001 (fair) | −0.021 (n.s.) | −2.0pp (dead zone confirmed) |
| 0.60–0.80 | **+0.013** (favorites slightly underpriced) | −0.091 (z=−2.3) | **−10.4pp** |
| 0.80–1.00 | +0.009 | −0.099 (z=−2.4) | **−10.8pp** |

**Findings:**
1. **The long-shot edge is genuine whale alpha.** Market-wide, longshots are *slightly overpriced* (classic bias); copied whales' long-shot picks resolve +37.6pp better than the crowd's — the edge is selection, not bias. Strongest validation of the copy thesis yet.
2. **The 0.60+ premium drag is a copy-selection artifact, not market structure.** Market-wide, favorites are slightly *underpriced* — yet copied whales systematically overpay there. The wang-audit "favorites pay premium" reading is correct *for the copies*, but the market baseline shows it's whale-specific, so the fix is selection (don't copy favorite-side whale entries) rather than a blanket premium gate.
3. Caveats: different time windows (dataset Feb-2026 vs bot Aug-2026) and populations (all trades vs copied) — the relative comparisons are structural, not point-in-time.
