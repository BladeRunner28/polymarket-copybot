# Repo Audit: OpenBB-finance/OpenBB

**Date:** 2026-09-02
**Repo:** https://github.com/OpenBB-finance/OpenBB
**Verdict:** ⚪ **Concept-only / reference architecture — do NOT vendor code. Reimplement ideas against our own stack only if a roadmap card demands it. No current card does.**

---

## 1. What it is

**Open Data Platform** — a massive (~2.4 GB, 72.6k★) Python data-integration layer: 30+ market-data providers (equities, options, crypto, macro/FRED, CFTC, news, SEC) normalized behind **one unified, typed query interface**. Providers plug in via a registry; users ask for a concept (`/equity/historical?provider=fmp|yfinance|nasdaq`) and get the same schema back regardless of source. Ships an MCP server, a FastAPI platform API, and a desktop "Workspace" (proprietary, separate).

**Default branch:** `develop`. **Pushed:** 2026-07-30 (active). **Language:** Python. **Archived:** no.

## 2. License verdict — READ-ONLY (AGPL v3.0)

- `LICENSE` explicitly: "All files in this repository are licensed under the GNU Affero General Public License v3.0." (GitHub's `NOASSERTION` is a classifier miss, not a license change.)
- Per project precedent (homerun audit): **AGPL = borrow concepts, copy NO code.** Any copied file would force the entire polymarket-copybot repo AGPL if ever distributed.
- The proprietary "Workspace" UI is a separate product — irrelevant to us anyway.
- **Do not copy provider/router/model code. Reimplementation of patterns is fine.**

## 3. What's actually in it (verified in source)

| Area | Reality | Our relevance |
|---|---|---|
| Provider registry + typed query interface | The core value: every provider implements Fetcher/QueryParams/Data contracts; registry routes by name | ⚪ concept — a *data-access abstraction layer* is real engineering, but we already have direct, working integrations per source (Quiver, GovInfo, Odds API, Manifold, GDELT). A unifying layer is overhead without a second provider per concept |
| Econometrics extension | Wraps **statsmodels** (MIT): OLS, Engle-Granger cointegration, Granger causality, unit-root/ADF, VIF, panel models | ⚪ concept — we'd `pip install statsmodels` directly (MIT) if a card needs cointegration/causality. Nothing in the repo is novel math; it's serialization sugar over statsmodels |
| Quantitative extension | Hand-rolled skew/kurtosis/rolling stats, performance metrics | ❌ trivially reimplementable in numpy/pandas; no unique machinery |
| Technical indicators | Hand-rolled SMA/EMA/MACD/RSI/ADX/ATR/VWAP/Ichimoku/CCI/Stoch (no TA-Lib dep) | ❌ pandas_ta (MIT) or our own 10-liners cover these; nothing unique |
| Congress.gov provider | Bills/amendments/committee docs — **no congressional stock trades** | ❌ no overlap with our Quiver lane |
| CFTC provider | Commitment-of-Traders reports | ⚪ possibly interesting for commodity/crypto positioning later; only if a macro-feature card appears |
| Deribit provider | Crypto options chains/futures (async WS + REST) | ⚪ our Phase C arb lane is venues *we already route* (Kalshi/PredictIt/Polymarket); crypto options are a different asset class, not a roadmap card |
| News extension | Wraps FMP/Intrinio/Benzinga/Tiingo news (paid-key feeds) | ❌ we already have GDELT (keyless, broader) + Quiver; these are paid API wrappers |
| MCP server | FastAPI→MCP bridge, per-extension tool categories, skill files, auth | ⚪ concept — mirrors what Hermes MCP already gives us (we installed gdelt-cloud MCP natively). Their skill/progressive-discovery structure is a nice pattern, but we get it from Hermes' own MCP client + our skills |
| **Prediction markets** | **Zero.** No Polymarket/Kalshi/PredictIt anywhere in the platform code | — the core thing we'd care about doesn't exist there |

## 4. Fit table vs roadmap

| Roadmap card | OpenBB component | Verdict |
|---|---|---|
| Phase Data-1 (external datasets) | Provider normalization pattern | ⚪ concept only — adopting means rearchitecting our working direct integrations for no current multi-provider need |
| Phase ML-2 (independent-entry lane) | Econometrics (cointegration/Granger/unit-root) | ⚪ concept only — use `statsmodels` directly (MIT) if feature work needs it; do NOT pull OpenBB's AGPL wrapper |
| Phase C (cross-venue arb) | Deribit/CBOE chains | ❌ wrong asset class — arb is Kalshi↔PM↔PredictIt, already wired |
| GDELT/A2 (sentiment) | News extension | ❌ paid-key wrappers; GDELT keyless already superior |
| Any phase | Prediction-market data | ❌ not present in OpenBB at all |

**Net:** nothing in OpenBB fills a current roadmap gap that our existing stack doesn't already cover with a leaner, license-clean path.

## 5. NOT-portable list

- **Any code file** (AGPL copyleft — would contaminate the whole repo).
- Provider wrappers (we have direct, tested integrations; wrappers add a dependency layer for zero new data).
- MCP server implementation (Hermes native MCP + our gdelt-cloud install already provide this capability).
- Desktop/Workspace UI (proprietary, irrelevant).
- LLM/agent layers (duplicate of our research bot stack; also AGPL).

## 6. Honest caveats

- This is a **data-platform audit, not a signal/edge audit** — OpenBB sells breadth of market *data access*, not predictive alpha. Its 72k★ reflect data plumbing, not trading edge. There is no strategy code, no backtest engine, no risk model of substance to steal.
- If we ever outgrow direct integrations (e.g., needing 10+ equity/options/macro providers under one schema for a broader ML research program), the *pattern* is worth reimplementing — but the right trigger is a specific new-data card, and the implementation should be ours (interface contracts are not copyrightable expression; their AGPL code is not usable).
- statsmodels/pandas_ta (MIT) already give us every econometric/TA function they wrap, with no license friction — that's the honest adoption path for the math.

## 7. Integration proposal (if user later wants it)

1. **Add a roadmap card only when a specific need appears** — e.g. "Phase ML-2 feature: Granger causality screen on whale-wake vs price" → then `pip install statsmodels` in the copybot venv and write a 30-line screen script. No OpenBB dependency.
2. If multi-provider equity/macro data becomes a goal: reimplement a minimal provider-registry (~200 lines, our schema, MIT-friendly deps) rather than importing theirs.
3. **Effort if adopted as pattern:** medium-high (rearchitecting data layer). **Risk:** high (AGPL contamination, dependency churn). **Not currently justified.**

## 8. Bottom line

**Skip / queue-behind.** AGPL read-only + zero prediction-market support + no math beyond MIT-licensed statsmodels wrappers + no current roadmap gap it fills = not worth an integration now. Revisit only if (a) a card needs causality/cointegration features → use statsmodels directly, or (b) a card needs broad multi-provider macro/equity data → reimplement the registry pattern ourselves. Watch, don't vendor.
