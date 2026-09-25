# Evaluation — "Quant-backtesting.docx" dataset recommendations

**Date:** 2026-09-25 · **Status:** EVALUATION ONLY — nothing adopted, nothing downloaded, no rule/PnL/number change
**Input:** user-supplied `Quant-backtesting.docx` (LLM-authored; see §4 provenance note)
**Method:** every named source re-verified against the primary source today (GitHub API, Hugging Face API + datasets-server, arXiv full text, live endpoint probes). Doc claims are quoted, then marked verified / partly wrong / mislabeled / unverifiable.

---

## 1. Verdict in one paragraph

**The document is roughly half right and its single best recommendation is one we already executed and then discarded.** Five of its named sources are real and correctly characterised (Becker's framework, SII-WANGZJ, the arXiv Polymarket-v1 paper, quant-bench, Karmane), but the scale figures are stale, one is mislabeled as "official" when it is a paid reseller, one data table is claimed to exist in a repo where it does not, and its top-line recommendation (Becker's 36GiB dataset) is a dataset we downloaded on 2026-08-31, mined for a 692M-trade calibration baseline, and no longer have on disk. What the doc does hand us that we do **not** have is genuinely valuable and it is *not* the dataset it headlines: **`TimeSeventeen/Polymarket-v1`** — 52.7 GB, CC-BY-4.0, ungated, 1.20B trades with **blockchain ground-truth aggressor direction**, plus ready-made daily-aligned panels. That is the one input our fill/fee model has been missing, and it is free.

---

## 2. Claim-by-claim verification (2026-09-25)

| # | Doc claim (source) | What I verified | Verdict |
|---|---|---|---|
| 1 | **Jon-Becker/prediction-market-analysis** — "largest publicly available dataset for both Polymarket and Kalshi… 36GiB+… 400+ million historical trades with true tick-level data" | Real, MIT, **3,858★**, pushed 2026-09-21, Python, not archived. **Already audited by us 2026-08-31** (`drafts/pma-audit.md`) and **already downloaded**: 50 GB extracted (Kalshi 3.9 GB / 769 market files / 7,214 trade files; Polymarket 46 GB / 40,454 trade files), snapshot vintage 2026-02-05; the derived `data/polymarket-calibration-baseline.{csv,json}` (win-rate-by-price over ~692M trades) is **still in-repo**. **The extracted dataset itself is GONE** (`~/prediction-market-data` absent today). "400M+ trades" understates the archive we processed (692M PM trades in one analysis pass). | ✅ real · ⚠️ **already in hand once, since deleted** · doc treats it as new |
| 2 | **SII-WANGZJ/Polymarket_data** — "1.1 billion trades across ~268,000 markets, 107 GB of clean Parquet, MIT" | Real, MIT, 839★. **Today's release is 232.5 GB / 5,412,260,320 rows** across 5 tables: `orderfilled.parquet` **110.3 GB**, `users.parquet` 47.7 GB, `trades.parquet` 37.5 GB, `quant.parquet` 36.7 GB, `markets.parquet` 0.29 GB. The dataset card's own README now says **"1.9 billion trading records."** Doc's "107 GB" ≈ the single `orderfilled` file; its trade count is a release behind. Market count not checkable without downloading. | ⚠️ **partly wrong** (stale/conflated scale) — usable, but bound the download |
| 3 | **"Polymarket-v1 Database (arXiv)"** — "1.20 billion trade records across 1.30 million markets ($61B)… late 2022 to April 2026… exact transaction direction directly from the blockchain layer" | **Correct on every figure.** arXiv **2606.04217** (Boka Qin, Rui Yang, Jun 2026): on-chain CTF Exchange archive, **2022-11-21 → 2026-04-28**, 1.20B trades / 1.30M markets / $61B, "**100% ground-truth aggressor direction**… unavailable in existing prediction market archives, which rely on heuristic inference." Data is public: HF **`TimeSeventeen/Polymarket-v1`**, **CC-BY-4.0 (card)**, ungated, **52.7 GB**, last modified 2026-08-30, configs `orderfilled` **1,201,580,990 rows / 27.4 GB**, `ctf` 838.7M / 8.5 GB, **`daily_aligned` 601.9M / 13.2 GB**, `daily_aligned_multi` 144.2M / 3.6 GB. Doc missed the daily-aligned panels (the best artifact in it). Paper text is CC BY-SA 4.0 while the HF card says CC-BY-4.0 → reconcile before redistributing. | ✅ **verified exactly — the best lead in the document** |
| 4 | **Karmane/polymarket-prediction-markets-enriched** — "curated… over 28,000 rows… flattens the nested structures from Gamma API" | Real, MIT, but **`gated: "manual"`** (approval required), **7 downloads**, ~28k rows, 5 files. | ⚪ **skip** — we can build the same table from `gamma /markets/keyset` in minutes, with no approval gate and no third-party provenance |
| 5 | **jdkatz21/Prediction_Markets_Public** — "public replication package containing historical data pulled from Kalshi's public API" | Real (47★; Diercks/Katz/Wright, *Rise in Macro Markets*). **License: none → all-rights-reserved, copy nothing.** The README's data table claims `data/trade_level_data` and `data/orderbook_data` are provided — **there is no `data/` directory in the repo** (contents: `code/`, `docs/`, `output/`, `.RData`, **`API Developer Agreement.pdf`**). And its own README says: *"In March 2026 Kalshi updated their API endpoints… the current code will work to pull data before the historical cutoff (**100 days is how Kalshi has it set currently**)."* | ❌ **package real, data absent, no license** · ⚪ reference only · **its 100-day cutoff independently corroborates our measured ~2026-07-18 Kalshi tape floor — a venue-imposed window, not a bug on our side** |
| 6 | "**Official Kalshi Historical API**… complete launch-to-present catalog of trades, order book states, and candlesticks through their dedicated historical endpoints" (ref [8] = `lycheedata.com`) | **False as stated, and mislabeled.** `lycheedata.com` is a **commercial reseller**, not Kalshi: Basic **$19.99/mo**, Pro **$39.99/mo** (Stripe checkout links in its own JSON-LD), selling "charts, dashboards, exports, and backtests." Against the actual venue: `/markets/{ticker}/candlesticks` and `/series/{s}/markets/{t}/candlesticks` both **404** (no candle endpoint), `/markets/trades` is keyless but **rolling to ~2026-07-18**, and per-fill Kalshi history sits behind paid tiers. | ❌ **reject** — do not subscribe on this doc's say-so; keep the forward-capture plan |
| 7 | **smf-ulm/polymarket-quant-bench** — "pre-computed OHLCV candlesticks (1m, 5m, 1h, 1d resolutions)" | Real, ungated, **CC-BY-4.0**, **603 MB / 14,154,379 rows**: `bars_daily` 1,462,282 · `bars_hourly` 12,655,266 · `markets` 36,831. **Only daily + hourly exist — no 1m or 5m directories.** | ✅ real · ⚠️ **the 1m/5m claim is false** · cheap, worth having as a cross-check |
| 8 | **Dune "curated Prediction Markets hub"** | Vendor page is **Cloudflare-gated** (direct fetch and headless fetch both blocked; no Chrome on this host today). Search index describes: **free = 5 tables (3 Polymarket: trades, market details, hourly prices; 2 Kalshi aggregate reports); Enterprise = 9 more, incl. Kalshi per-fill data and positions.** | ⚪ **unverified by direct fetch** — plausibly useful for breadth, but the free tier gives us nothing our keyless APIs don't, and Kalshi per-fill is paid |
| 9 | Hybrid sentiment × tick feature matrix / temporal aggregation recipes | Standard feature-store advice; our design doc's **D6** already specifies it (point-in-time joins, tier flags, cross-venue columns). Nothing new. | ⚪ adds nothing |

---

## 3. What this changes in our design (`drafts/backtest-engine-design-20260925.md`)

**Add a Tier 0 "historical depth" dataset — and be precise about what it is not.**

- **`TimeSeventeen/Polymarket-v1` (52.7 GB, CC-BY-4.0) becomes the history-tier price/trade substrate** for anything *before* our own capture window. It supersedes paged `clob /prices-history` for bulk history — but note the boundary: it covers **CTF Exchange v1, which terminated 2026-04-28**, i.e. it ends *before* our bot era (first paper trade 2026-06-18). So it is **training/calibration substrate, not a substitute for our rolling capture**, and it does not price any of our decisions.
- **The ground-truth aggressor direction is the real prize.** We have never been able to measure the maker/taker split on historical Polymarket trades — that missing field is exactly what forced the all-taker upper bound in `drafts/c200-taker-fee-measurement-2026-09-09.md` (gross +$5,397.60 → net +$2,933.77) and what the `c200-maker-fill-assumption` card is blocked on. This archive lets us fit the fee model and a maker-fill probability on **true direction** rather than inferred direction. Its own benchmark finding (tick rule 49.83% / BVC 50.51% aggregate accuracy on PM data — i.e. heuristic classifiers are near-random here) is a direct warning against the heuristic route.
- **`quant-bench` (603 MB)** is a cheap daily/hourly bar layer for breadth studies and an **independent cross-check on our own price pager** (two sources, same market, same day → catches pager bugs). No reason not to have it.
- **Kalshi: nothing in the doc changes the plan.** The doc is right that historical Kalshi data exists; it is wrong that it is freely and programmatically obtainable across the full life of the exchange. It is paid (Dune Enterprise, Kalshi's own historical tier), resold (lychee), ~100 days rolling and keyless, or replicable-only-with-credentials (jdkatz). **Forward capture stays the critical path.**
- **Storage reality check.** Root volume: **183 GB free**. Polymarket-v1 (52.7) + quant-bench (0.6) fit; SII-WANGZJ (232 GB) does **not** fit alongside a growing L2 corpus (~135 GB/yr at current universe) and a 7.7 GB live DB. Therefore: pull the two that fit, take SII as a **bounded subset** (`markets.parquet` + `users.parquet` first, not the 110 GB `orderfilled`), or park archives on the storage fabric once the 10 G path is serving — never on the same volume as the live DB.

**Recommended pull order (smallest-first, each with a clear purpose):**

1. **`quant-bench` (0.6 GB)** — cross-check bars for the pager. Minutes.
2. **`Polymarket-v1`** — start with one month of `orderfilled` + the `daily_aligned` config; purpose: maker/taker split + fee-model calibration on ground-truth direction, and the first real input for the simulator. Full 52.7 GB if disk allows.
3. **Becker's dataset, scoped** — re-acquire only the slice a specific study needs (resolved Kalshi + matched Polymarket), not the full 50 GB; the calibration baseline it produced is already in-repo.
4. **SII-WANGZJ (232 GB) — defer** until the fabric is in use or a study actually needs the user-level tables.
5. **Skip** Karmane (gated, reproducible in minutes), **skip** jdkatz code (no license; data absent), **do not subscribe** to lychee on the doc's evidence.

---

## 4. Provenance note (why the errors are systematic)

The document is LLM-generated: its citation list is unusable (bare hostnames — "https://github.com" ×3, "https://arxiv.org" with no IDs), it closes by asking the reader which backtesting library they use and whether they plan to scrape Reddit/X, and it presents a paid reseller as an official venue API. Its failure mode is exactly the one our own doctrine guards against: **plausible sources with unverified scale figures.** Every number above was re-derived from the primary source today. The one exception is the Dune tier split, which is search-index evidence only (the vendor page is Cloudflare-gated and no headless browser was available on this host) — treat it as unconfirmed.

**Standing rule this reinforces:** a dataset recommendation is not adopted on description — it is adopted after (a) the source resolves, (b) the scale/licence is read off the API, and (c) the artifact is available where the doc says it is. Two of the nine claims failed step (c) outright.

---

## 5. Probe log (2026-09-25, all read-only)

| probe | result |
|---|---|
| `api.github.com/repos/jon-becker/prediction-market-analysis` | MIT, 3,858★, pushed 2026-09-21 |
| `du -sh ~/prediction-market-data` | **absent** — 50 GB extract gone; `data/polymarket-calibration-baseline.{csv,json}` retained |
| `api.github.com/repos/SII-WANGZJ/Polymarket_data` | MIT, 839★, repo 95 KB (data lives on HF) |
| HF tree `SII-WANGZJ/Polymarket_data` | orderfilled **110.3 GB**, users 47.7, trades 37.5, quant 36.7, markets 0.29 → **232.5 GB** |
| HF datasets-server size (SII) | **5,412,260,320 rows**, 232,487,587,426 bytes |
| HF dataset card README (SII) | "**1.9 billion** trading records" |
| `arxiv.org/abs/2606.04217` | Polymarket-v1 Database, Qin & Yang, dataset at HF `TimeSeventeen/Polymarket-v1`, paper CC BY-SA 4.0 |
| `api/datasets/TimeSeventeen/Polymarket-v1` | CC-BY-4.0, **ungated**, last modified 2026-08-30, **52.7 GB** |
| datasets-server size (polymarket-v1) | orderfilled **1,201,580,990 rows**; ctf 838,688,922; daily_aligned 601,934,424; daily_aligned_multi 144,175,988 |
| HF dataset `Karmane/polymarket-prediction-markets-enriched` | **gated: manual**, 7 downloads, 5 files |
| GitHub contents `jdkatz21/Prediction_Markets_Public` | **no `data/` dir**; `API Developer Agreement.pdf` present; README: Kalshi historical cutoff = **100 days** |
| GitHub API license (jdkatz21) | **null** (all-rights-reserved) |
| HF `smf-ulm/polymarket-quant-bench` | ungated, CC-BY-4.0, 603 MB, 14,154,379 rows, **daily + hourly only** |
| `lycheedata.com` JSON-LD | Stripe offers **$19.99 / $39.99** per month; third-party platform, not Kalshi |
| `dune.com/collection/prediction-markets/overview` | **Cloudflare-gated** (curl + headless blocked) — free/Enterprise split unverified |
