# Audit — atilaahmettaner/tradingview-mcp

**Date:** 2026-09-29 · **Mode:** read-only (nothing in the donor was patched or copied) · **Clone:** `/tmp/tradingview-mcp` (`--depth 1`)
**Repo:** https://github.com/atilaahmettaner/tradingview-mcp — "TradingView MCP server — real-time market data, technical analysis, screeners & backtesting for Claude, ChatGPT, Cursor & any MCP client. Stocks, crypto, forex & futures across global exchanges. Hosted or self-host." · pyproject name `tradingview-mcp-server` v0.9.0 · homepage `pro.cryptosieve.com` (their hosted deployment of this same OSS server)

**Prior-work check:** no prior audit. `grep -ril "atilaahmettaner\|tradingview" drafts/ data/roadmap.json data/github-scout-seen.json` → one hit only, `drafts/_research_cache/...capitalspectator...` (a news scrape, unrelated). `drafts/` has no `tradingview*` file, so this is a first pass, not a re-audit.

---

## What it is (tree census)

| Fact | Value | Source |
| --- | --- | --- |
| Stars / forks / watchers | **4,848 / 983 / 72** · 17 open issues | GitHub API |
| License | **MIT** — `spdx_id: "MIT"` **and** `LICENSE:1` `MIT License`, `Copyright (c) 2025 Ahmet Taner Atila` | API + `LICENSE` |
| Created / last push | 2025-08-08 → **2026-09-01T15:15:48Z** (4 weeks stale) · **0 releases** | GitHub API |
| Commits since 2026-09-01 | **1** (merge of PR #94, egx-smart-money) | `/commits?since=` |
| Upstream CI (`test.yml`) | last 3 runs **not green**: 2× `action_required` (unrun), 1× `failure` (2026-09-14) | Actions API |
| Files (excl `.git/.venv`) | **190** · 4.41 MB · `.py` 59 files / 608 KB | `os.walk` |
| Python LOC | **15,351** total — `src/` 11,679 · `tests/` 3,576 | `wc -l` |
| Test functions | **252** (`tests/unit` 31 files + `tests/stress` 1) | `grep -c def test_` |
| MCP tools | **40** `@mcp.tool` registrations | `server.py` |
| Third-party contamination | **none** — zero `Copyright`/`SPDX-License` headers outside `LICENSE` | grep |
| Telemetry / phone-home / key wall | **none** — zero refs to `cryptosieve`, `api_key`, `x-api-key`, `Bearer` in `src/`; the only "telemetry" matches are comments about *their* support evidence. `.env.example` marks `MARKETAUX_API_TOKEN` (news tools go empty without it) and the Webshare proxy as **optional** | grep + `.env.example` |

The transferable part is two **stdlib-only, dependency-free** modules — `core/services/indicators_calc.py` (268 lines) and `core/services/backtest_service.py` (960 lines). Everything else is venue plumbing for stocks/crypto/forex/EGX/futures (Yahoo Finance, TradingView screener, Kucoin, EGX, Marketaux news).

---

## Verified machinery (real vs stub, formulas re-derived by hand)

**Stub scan: clean.** `TODO|FIXME|not implemented|placeholder|coming soon|mock|stub` across *all* `src/**.py` → **0 hits** (both core modules: 0). Nothing here is a scaffold.

**Not a formula orphan.** `backtest_service` → `server.py:88-91` → three MCP tools (`backtest_strategy:792`, `compare_strategies:826`, `walk_forward_backtest_strategy:846`); `_fetch_ohlcv` is also imported by `smart_money_service.py:28`; `indicators_calc` is consumed by both services. The arithmetic is wired to the product surface.

**I re-derived each formula and matched it numerically against the library** (their `.venv/bin/python`, my own script — not their tests):

| Function | Claim in source | My re-derivation |
| --- | --- | --- |
| `calc_atr` (Wilder) | `:178-183` seed = mean(TR[1..period]), then `(atr·(p−1)+TR)/p` | `ATR[14] = 0.529286` **=** hand `mean(TR[1..14])`; every later bar matches the hand recursion to 1e-12 ✅ |
| `calc_rsi` (Wilder) | `:60-85` seed = 14 diffs, then Wilder smoothing | hand `65.9951` = lib `65.9951` ✅ (seed consumes **14** diffs — the source's own convention) |
| `calc_ema` | `:30-35` seed = SMA(period), `k = 2/(p+1)` | hand recursion `8.5` = lib `8.5` exact ✅ |
| `calc_bollinger` | `:106` variance/period | uses **population** σ: `upper[4]=5.8284` (= pop), sample σ would give `6.1623` — matches TradingView's own convention ✅ |
| `calc_macd` | `:127-149` EMA12−EMA26, signal = EMA(9) of the MACD line only over valid values | `histogram == macd − signal` on every valid bar (1e-12) ✅ |
| `calc_donchian` | `:261-266` rolling max/min **including the current bar** | `upper[19] == max(last 20 highs)` ✅ — and the *strategy* compensates by testing `highs[i] > upper[i−1]`, with the bug documented in-comment (`:227-229`: including bar i makes the channel unreachable → 0 trades) |
| `calc_supertrend` | `:216-242` hl2±mult·ATR, no-widening band adjust, direction flip on band cross | band-adjust matches the standard rule on a monotone series (lower band non-decreasing, no re-widening) ✅; nit: on the tie `closes[i−1] == prev_upper` it keeps `u` where the textbook keeps `prev_upper` — measure-zero, immaterial |

**No look-ahead in any of the 9 strategy runners** (read line-by-line): every runner reads indicator *and* price at the same index `i` and fills at `candles[i]["close"]` — the value is known at that bar's close. Costs are applied as a **round trip** (`_apply_costs:350` `(commission+slippage)×2` subtracted from the % return — a linear approximation, correct to first order).

**Walk-forward is NOT classical walk-forward optimisation.** Folds are contiguous non-overlapping slices, each split 70/30, with **fixed default parameters on both slices** — the code says so itself in a `caveat` field (`:943-946`): it measures *regime consistency across windows*, not parameter overfitting. No purge, no embargo, no parameter re-fit. The robustness score is `te/tr` (or `tr/te` when both negative — a real **sign bug they fixed**, see below), capped ±2.0, and warmup-starved test folds are flagged `insufficient_data` and excluded rather than scored 0.0.

**Metrics worth naming** (`_calc_metrics:455`): Sharpe from a **per-bar mark-to-market equity series** (`_mark_to_market_equity:412`), annualised `252` / `1638` for 1h, risk-free default 4% — **both parameterised** (so a PM lane could pass `365`); Calmar, profit factor (from **% sums** → equal-notional, inconsistent with the compounding equity path), expectancy. The MTM path exists because their earlier exit-only equity hid intra-trade drawdowns (their own comment: a trade that rode −40% before exiting +2% showed near-zero drawdown).

**Their test suite, run by me in a throwaway venv** (`uv sync --dev`, 1.7 s):

| Command | Result |
| --- | --- |
| `uv run pytest tests/unit -q` (their CI command) | **285 passed, 1 failed** in 19.4 s |
| `uv run pytest tests/unit/services/test_async_handlers.py -q` (the failure, ×3) | 16 passed, **2 failed — reproduced 3/3** |
| `uv run pytest -m stress tests/stress -q` (**CI-ignored**, live upstream) | **8 passed** in 12.8 s (real TradingView/Yahoo calls) |

The failure is a **wall-clock assertion, not a logic defect**: `test_top_gainers_offloads_to_thread` / `test_multi_timeframe_analysis_offloads` assert `elapsed < 0.32` (their own comment "bound midway to absorb CI jitter") and measure 0.34–0.35 s on this Mac. 293 of 294 green. The live-upstream stress suite passing is the strongest quality signal available here.

**Self-documented defects — the highest-signal evidence in this repo** (`CHANGELOG.md` 0.9.0, 2026-08-26): `top_losers` **returned gainers** (sorted desc, truncated, then re-sorted); the volume-breakout scanner **fabricated breakouts** (a fallback ratio that was always exactly 2.0 and passed the default gate on price change alone); **walk-forward robustness inverted for losing strategies** (a strategy losing *more* out-of-sample scored a capped 2.0 = "maximally robust"); strict input validation replaced **silent default substitution** (`exchange="KRAKEN"` used to return KUCOIN data with no warning). A repo that writes down its own silent-numeric bugs is the kind that is worth reading even when it is not worth adopting.

---

## Polymarket-vs-TradingView relevance split

| Class | Share of the repo | Usable here? |
| --- | --- | --- |
| Venue plumbing — Yahoo Finance, TradingView screener, Kucoin/EGX/US-futures/options tools, Marketaux news, Webshare proxy | ~85% of `src/` | ❌ venues we do not trade |
| Deterministic core — `indicators_calc.py`, `backtest_service.py` (stdlib-only) | 1,228 lines | ⚪ arithmetic transfers, venue does not |
| MCP surface — 40 tools, FastMCP, error envelopes (`INVALID_*`, `PARTIAL_DATA`), thread offload | `server.py` 1,284 lines | ⚪ patterns we already own |
| Agent packaging — `openclaw/SKILL.md` + `trading.py` (in-repo agent skill wrapping the MCP) | 2 files | ❌ their client is OpenClaw, ours is Hermes-native |

There is **no prediction-market content of any kind** in this repo: no PM venues, no probability series, no binary contracts, no event markets. Every price it touches is a continuous instrument.

**Capability-gap probe on our side (behaviour, not names):** RSI / ATR / Bollinger / MACD / Supertrend / Donchian / Sharpe / Calmar / profit-factor hits in `src/`, `scripts/`, `tests/` = **zero in code**; they appear **only in `drafts/`** (auditor prose: 1–3 files per term). Our metric vocabulary is net-of-fee PnL and expectancy. But **walk-forward is not a gap** — we already run expanding-window, time-ordered, purged walk-forward (`scripts/fit-price-edge.py`, `scripts/shadow-expectancy-model.py`, `src/lib/scoring/price-edge.ts`), and `drafts/backtest-engine-design-20260925.md` §7 specifies a **stricter** split discipline than the donor's (purged embargo, era-aware by `ruleSetVersion`, market-clustered bootstrap, leakage tests in §6 with `as_of ≤ decision_ts` and shuffled-label ablations). Deflated Sharpe is already named in §7 → **unimplemented-by-plan, not missing**.

---

## Fit table

| Component | Verdict | Card it answers | One-line reason |
| --- | --- | --- | --- |
| `indicators_calc.py` (EMA/SMA/RSI/BB/MACD/ATR/Supertrend/Donchian/ADX, stdlib, verified) | ⚪ concept-only | **no card asks for it** | Nearest cards are `decay-bar-tripped-oct8-decision` and `drift-gate-band-winrate-shadow` (should drift tolerance scale with the band?) — an ATR-normalised drift is a *derived* idea, not carded work; and any scoring touch is frozen until 2026-10-08 |
| Walk-forward fold harness + **`insufficient_data` warmup guard** | ⚪ concept-only | `bt-ml-lane`, `ml-doctrine-time-and-era-splits` | Our §7 splits are already stricter (purge + embargo + era + bootstrap); the one portable idea is "a window too small to trade is not evidence of OOS failure" — a guard our design doc does not state |
| Per-bar **mark-to-market equity → drawdown/Sharpe** + parameterised annualisation | ⚪ concept-only | `bt-sim-replay`, `bt-engine-design` §7, `bt-ml-lane` | Our doc names a `drawdown.py` port and deflated Sharpe but never the bar-frequency MTM construction; this is the cheap arithmetic worth keeping |
| Cost model `(commission+slippage)×2` linear | ❌ not portable | superseded by `bt-fee-maker-calibration` | Our fee law is `C×rate×p(1−p)` measured on 1.2B fills; a flat % is strictly worse for PM |
| Buy-and-hold benchmark with matched costs | ❌ not portable | superseded by `ml1-target-net-pnl-and-price-baseline` | We already own the price-only baseline, which is the stronger bar |
| Data layer (Yahoo OHLCV, TradingView screener, EGX/Kucoin/futures, Marketaux, proxy) | ❌ not portable | `bt-data-capture` is our equivalent | Venues we don't trade; our price surface is the paged `/prices-history` path |
| `PARTIAL_DATA` / strict-validation envelopes; per-scan telemetry | ⚪ concept-only | `tr28-rec2-connector-retry` (APPLIED), `tr31-rec3-scan-partial-loud` | Same pattern, already in our stack — read as confirmation, nothing to take |
| `openclaw/SKILL.md` + `trading.py` | ❌ not portable | — | OpenClaw client wrapper for a stock/crypto MCP |
| Whole repo as a run-it-don't-vendor-it service (TA/macro context feed) | ⚪ concept-only | **no card asks for it** | Would be a new external dependency on a 4-week-stale repo to inform a paper-only PM book; not recommended without a card + pre-registered measurement |

---

## Integration proposal

**Nothing to integrate now — and no repo write was made on the donor side.** Two artifacts are worth keeping *as references only* (MIT, attribution required if a line is ever copied):

1. **Bar-frequency MTM equity/drawdown arithmetic** (`_mark_to_market_equity:412`, `_calc_metrics:485-522`) — cheap, and it is the difference between "the strategy's max drawdown" and "the drawdown a holder actually experienced". Fits `bt-sim-replay` when the engine is built (post-Oct-8, P1).
2. **The `insufficient_data` fold guard** (`backtest_service.py:852-869`) — one boolean that stops a warmup-starved window being read as out-of-sample failure. Fits `bt-ml-lane` / `ml-doctrine-time-and-era-splits`.

**The one genuinely new idea, and I am deliberately NOT carding it:** an ATR-style volatility normaliser over a market's *own* price series, as the denominator for the drift gate instead of a fixed `maxPriceDrift` — i.e. "tolerance scales with the market's realised volatility, not only with its band's win rate". No card asks for it; it touches admission behaviour; and it is dead code until the `bt-data-capture` price archive (D2) exists. If you want it, it needs a card **and** a pre-registered measurement after the 2026-10-08 window close. Say the word and I'll write it up as a carded proposal; I have not created one.

**Effort/risk if either reference is ever used:** ~1–2 h of pure arithmetic inside an engine that does not exist yet; flag-revertible by construction; zero effect on any live rule, size or published number.

---

## NOT portable (summary list)

1. Yahoo Finance OHLCV fetching, TradingView screener service, `tradingview-screener`/`tradingview-ta` deps.
2. All coin/EGX/futures/options/news tools and the Marketaux + Webshare-proxy config surface.
3. The linear commission+slippage cost model (our `C×rate×p(1−p)` law is ahead and archive-calibrated).
4. Buy-and-hold benchmark (superseded by the price-only baseline).
5. The 9 long-only single-instrument TA strategies (`rsi`, `bollinger`, `macd`, `ema_cross`, `supertrend`, `donchian`, `rsi_pullback`, `keltner_breakout`, `triple_ema`) — discrete position, full-capital compounding per trade, no portfolio, no gates. None of it describes a binary-contract book.
6. FastMCP server surface / MCP registry + Docker publishing workflows (we are not an MCP server).
7. `openclaw/` agent-skill packaging.
8. The hosted `pro.cryptosieve.com` service (paid path to the same OSS server).

---

## Honest caveats + verdict

- **Quality ≠ fit.** This is a well-built repo: 0 stubs, 252 test functions, 293/294 green in my run, MIT with no contamination, no phone-home, no key wall, and a changelog that documents its own silent-numeric bugs. It is also **venue-mismatched at every point that matters** to a paper-only Polymarket book.
- **Stars are not a maintenance signal here.** 4,848 stars vs **1 commit in the last 4 weeks, 0 releases, and upstream CI runs sitting `action_required`/`failure`**. My green suite is a snapshot of a 2026-09-01 commit.
- **The 1 test failure is a timing bound**, reproduced 3/3 locally (0.34–0.35 s vs `< 0.32`), not a logic failure — and I did not patch it.
- **Reference-series caveat.** I did not compare against published RSI/ATR tables (seed conventions differ between sources). What I claim is the stronger thing: hand-derived Wilder recursions match the library **exactly**, bar for bar.
- **Do not quote their "ROBUST / OVERFITTED" verdicts as OOS validation** — by their own admission the score measures regime consistency, since no parameter is fitted on the train slice.
- **No strategy was executed, no PnL claim of theirs was tested.** I ran their tests and their math, not their README's performance claims.
- **Freeze respected:** nothing here proposes a rule, size, gate or published-number change before the 2026-10-08 window close.

**Verdict: SKIP as an adoption target — read-only MIT reference for two pieces of arithmetic.** Not a rights concern, not a quality concern: a *venue* concern plus an *ownership* concern (our `bt-*` doctrine is already stricter than theirs on splits, fee law and leakage). Take nothing today; if the backtest engine is ever built, the MTM-equity construction and the warmup guard are the two lines worth re-reading. Carded as an `AUDIT INPUT` block on `bt-engine-design` only — no new card, no code, no dependency.

*(Ready-to-paste registry block, for the record — already applied to `data/roadmap.json` → `bt-engine-design.note`:)*

```
AUDIT INPUT (2026-09-29, user-supplied repo; drafts/tradingview-mcp-audit-2026-09-29.md):
atilaahmettaner/tradingview-mcp (MIT, 4,848★, last push 2026-09-01, 0 releases) — SKIP as an
adoption target. Transferable: bar-frequency mark-to-market equity/drawdown arithmetic
(_mark_to_market_equity:412) and the insufficient_data warmup guard (:852-869); both are
references for the engine specified in drafts/backtest-engine-design-20260925.md §7.
Our splits (purged + embargo + era-aware) and fee law (C×rate×p(1−p)) are already stricter.
Its 9 TA strategies, Yahoo/screener data layer and liner cost model: not portable.
Uncapped, uncarded idea NOT adopted: ATR-style volatility normaliser over a market's own
price series as the drift-gate denominator (nearest cards: decay-bar-tripped-oct8-decision,
drift-gate-band-winrate-shadow) — needs a card + pre-registered read after 2026-10-08.
No rule/size/gate/number change proposed.
```
