# polyterm (NYTEMODEONLY/polyterm) — adoption audit for Medusa CopyBot

**Audited:** 2026-09-28 · **Clone:** `/tmp/polyterm` (shallow, `--depth 1`, left in place) · **Auditor:** subagent (read-only; nothing in `~/polymarket-copybot` touched except this draft)
**Revision note:** v2 — an earlier pass of this same audit was already on disk. This revision **keeps** its verified metadata, endpoint tables, §5 joinable-time-series finding and P1/P2 proposals, and **corrects/supersedes** four things it got wrong or left unverified: (1) the 31 network-gated tests it did not run — they pass; (2) "our paper fills pay no fee" — we have the same fee curve with a *proxy* rate, and the real gap maps to an existing card; (3) "nothing maps to a named open card" — two cards ask for exactly these things; (4) it did not check polyterm's own `docs/AUDIT_2026-06-01.md` against our adapter's Gamma calls. New sections §2b, §3b, §4b.

## Metadata (GitHub API, verified)

| Field | Value |
|---|---|
| full_name | NYTEMODEONLY/polyterm |
| description | "Polymarket in your terminal." |
| license | **MIT** (`spdx_id: MIT`); `LICENSE` present in clone (1,079 bytes): "MIT License / Copyright (c) 2025 PolyTerm Contributors" |
| stars / forks | 359 / 69 |
| created / pushed | 2025-10-14 / **2026-09-06T02:17:16Z** (≈22 days stale at audit time) |
| size / default_branch / archived | 3317 KB / `main` / false |
| open items | 2 — PR #26 (2026-08-18, unmerged) and issue #13 "safe??" (2026-04-25) |
| version | `setup.py:11` = **0.11.2**; newest release tag **v0.11.6** — **version drift** |
| releases | v0.11.2 (2026-09-01) → v0.11.3/.4/.5 (2026-09-05) → v0.11.6 (2026-09-06T02:17:17Z, one second after `pushed_at`) — four releases inside ~21h, then silence |
| contributors | **1** (`NYTEMODEONLY`, 171 contributions; 100-commit API page spans 2026-02-05→2026-09-06, monthly 19/31/4/21/2/13/10 for Feb–Sep) — bus factor 1 |
| declared python | `python_requires=">=3.8"`; `install_requires` from `requirements.txt` (includes `mcp>=1.0.0,<2`, which itself needs ≥3.10) — the two disagree |

---

## 1. What it is

A **read-only terminal (Textual/Rich) client and analytics surface for Polymarket**, exposed through three surfaces: 89 CLI command modules, an 82-screen TUI, and an **MCP server with 27 typed tools** (`docs/tool-manifest.json`: `schema_version`, `adapters`, `tools` ×27, `cli_commands`; `polyterm/agent/mcp/tools/*.py` holds 58 `def`s including helpers). Measured composition: `polyterm/` package 251 files / 2,030,250 bytes / 57,348 lines (py+md+json); `tests/` 109 files / 24,249 lines; `docs/` 296 files / 26,066 lines; 376 Python files; `core/` 41 modules; 200 test files.

Explicitly **not an execution tool**: `README.md:24` — *"No private keys. PolyTerm does not place orders. A wallet address in config is view-only."* Verified harder than a grep for keys: all 25 calls through the API clients are `_request("GET"…)`; `private_key|eth_account|sign_order|post_order|submit_order|api_secret|passphrase` → **zero** occurrences in `polyterm/`; the only non-GET writes in the tree are Telegram `requests.post` (`core/notifications.py:190,239`) and a Polygon JSON-RPC read (`core/portfolio.py:111`). `quicktrade` only deep-links to `polymarket.com/event/...`.

Its most transferable asset is not the UI — it is **a disciplined data-surface layer**: per-market CLOB primitives (book/spread/price/fee-rate/ticker/prices-history), three more Data-API endpoints than we call, a **lag-labeling doctrine** for those endpoints, and a handful of honest, self-contained formulas (fee curve, risk grade, sybil-cluster score, wash-trade indicators, Brier calibration).

## 2. Verified machinery (file:line)

**API surface (all read-only GET/WS):**

| Surface | Location |
|---|---|
| `GET /book` (order book), `/price`, `/spread`, `/last-trade-price`, `/fee-rate`, `/ticker`, `/markets` (sampling), `/depth` | `polyterm/api/clob.py:116, 144, 156, 168, 180, 192, 733, 252` |
| `GET /prices-history` with interval/fidelity + `[start_ts,end_ts]` clamp | `polyterm/api/clob.py:81`; windowing `polyterm/core/price_history.py:39-63` |
| CLOB WSS market channel (trades **and** orderbook subscribe, reconnect/timeout logic) | `polyterm/api/clob.py:567, 580, 605` |
| Data-API `GET /positions`, `/activity`, `/trades`, `/holders`, `/value`, `/closed-positions`, `/v1/leaderboard`, `/profit`-style summary | `polyterm/api/data_api.py:66, 81, 103/119, 137, 148, 161, 175, 225` |
| `lb-api.polymarket.com/profit` cross-check | `polyterm/core/pnl_cashflow.py:19-20` |
| Gamma `/markets`, `/markets/keyset` (keyset pagination), `/markets/{id}`, `/markets/slug/{id}`, `/public-search`, `/markets/{id}/liquidity`, `/markets` resolved | `polyterm/api/gamma.py:279, 306, 326/336, 407, 495, 614` |
| Shared Gamma rate limiter (`requests_per_minute=60`) | `polyterm/api/gamma.py:28-106` |
| `status.polymarket.com` (Statuspage parsing), Kalshi `api.elections.kalshi.com/trade-api/v2`, RSS (theblock/coindesk/decrypt), Telegram + Discord webhook notify | `polyterm/api/status.py:14`; `polyterm/core/cross_venue.py:38`; `polyterm/core/news.py:21-23`; `polyterm/core/notifications.py:6,183` |
| The Graph subgraph client | `polyterm/api/subgraph.py` — **ships disabled**: `subgraph_endpoint: ""` with comment *"The Graph subgraph was removed; do not ship a dead URL"* (`polyterm/utils/config.py:37`) |

**Real formulas (not cosmetic):**

| Primitive | Formula / behaviour | Location |
|---|---|---|
| **CLOB V2 taker fee curve** | `rate · (p·(1−p))^exponent`, `p` clamped [0,1]; schedule read per-market from Gamma `feesEnabled`/`feeSchedule {rate, exponent, takerOnly}` / `takerBaseFee/10000`; CLOB `/fee-rate` `base_fee/10000`; default `GENERIC_FEE_SCHEDULE(rate=0.05, exp=1.0)` labelled source `"generic"`; `fee_source_label()` reports which source produced the rate | `polyterm/core/fees.py:32-70, 73-87, 90-95, 110-118` |
| **Breakeven price** | `min(entry·(1+fee_rate(entry)), 1)` | `polyterm/core/fees.py:103-107` |
| **Kelly + EV sizing** | net payout `b = (1−p)/p − fee_per_dollar`; `EV/$ = q·b − (1−q)`; `f* = max((q(1+b)−1)/b, 0)`, fractional Kelly multiplier, fixed 1/2/5% comparators | `polyterm/cli/commands/size.py:121-175` |
| **P&L cashflow identity** | `SELL + REDEEM + MERGE + REBATE − BUY − SPLIT + open-size mark`; module docstring explicitly warns `SUM(cashPnl)` drops redeemed winners and `makerPnl` is untrustworthy; documents pagination caps (activity offset ≤5000, positions ≤9500) | `polyterm/core/pnl_cashflow.py:1-8`, `17-25` |
| **Smart-money wallet score** | `40·win_rate + 20·min(trades/min_trades,3)/3 + 15·min(vol/250k,1) + recency(≤7d 10 / ≤30d 6 / ≤90d 3) + 5·min(focus,5)/5 − 15·risk/100`, plus noisy-reason flags (`limited_trade_sample`, risk ≥70, win_rate ≥0.95 on <25 trades) and explicit `realized_pnl_available: False` (refuses to invent PnL) | `polyterm/core/wallet_intelligence.py:29-79`; metrics at `:593-625` |
| **Sybil cluster score (0-100)** | timing ≤40 (10 per coincident print, 30s window) + market Jaccard×35 + shared rounded sizes ≥2 → ≤25 | `polyterm/core/cluster_detector.py:36-69, 144-195` |
| **Market risk grade** | weighted sum of 6 sub-scores: resolution_clarity .25, liquidity .20, time_risk .15, volume_quality .15, spread .15, category .10 → letter grade; liquidity penalty tiers 0/15/30/50/70/90 | `polyterm/core/risk_score.py:45-52, 172-179, 239-255` |
| **Wash-trade indicators** | thresholds: `vol/liq > 3.0`, `trades/trader > 5/10/20`, `median/avg size > 0.8/0.9`, yes/no balance `> 0.95`; weighted aggregate, bands ≤25/≤45/≤65 | `polyterm/core/wash_trade_detector.py:67-69, 144-156, 181-260` |
| **Intra-market arb** | buy YES+NO when `cost < $1`, subtract fee on the winning leg, require `net_profit > 0`, sort by net | `polyterm/core/arbitrage.py:135-221` |
| **Cross-venue spread** | Polymarket vs Kalshi normalised YES price, `min_spread=0.025` default | `polyterm/core/cross_venue.py:38-47` |
| **Pearson correlation** | on DB `market_snapshots` price series, timestamp alignment tolerance 15 min, refuses <5 aligned points; ASCII category heatmap | `polyterm/core/correlation.py:111-162, 179-217, 461-488` |
| **Calibration** | Brier score `Σ(p−o)²/n` + five probability buckets (50-60 … 90-100) with accuracy | `polyterm/cli/commands/calibrate.py:403-443` |
| **Verified-print ingest** | whitelists trade types, excludes `split/merge/redeem/reward/conversion/liquidity/deposit/withdrawal`, counts `skipped`, flags `empty_data_api_page` rather than synthesising rows | `polyterm/core/print_scanner.py:15-31, 38-80, 149, 174`; wallet rollup `polyterm/core/whale_prints.py:76-112` |
| **Data-API lag doctrine** | every Data-API payload stamped `lag=true, lagged=true` + `quality_flags: ["lagged_data_api"]`, strips a `live_data_api_trades` misnomer, and *"Do not invent a lag duration"* | `polyterm/api/data_api_lag.py:1-84` |
| **Archive freshness self-report** | per-table `fresh`/`stale`/`missing` status → `stale_market_snapshots`, `missing_market_snapshots` flags | `polyterm/core/archive.py:120-164` |
| **Backtest** | **quarantined demo**: refuses without `--demo`, then seeded-random trades (md5 of strategy name); docs say "do not use these metrics to choose a strategy" | `polyterm/cli/commands/backtest.py:17-55`; `polyterm/core/demo_strategy_sim.py:1-80` |

### 2b. What is wired vs library-only (new in v2 — matters for "is it a capability?")

| Module | Wired to | Evidence |
|---|---|---|
| Market risk grade | **CLI + MCP**: `polyterm risk`, `analytics.risk` (which feeds `volume_24h` from Gamma `volume24hr` and returns `quality_flags: ["heuristic_risk_score"]`) | `cli/commands/risk.py:12`; `agent/mcp/tools/analytics.py:26-49` |
| Wash-trade | **CLI, but only the 2-arg shortcut**: `quick_wash_trade_score(volume_24hr, liquidity)` behind `polyterm monitor --show-quality`, warning at 75/55. The full 4-indicator `WashTradeDetector` has **zero** non-test callers | `cli/commands/monitor.py:272-275`; only other hits are `wash_trade_detector.py` and `tests/test_core/test_wash_trade.py` |
| Sybil cluster score | **CLI**: `polyterm clusters` | `cli/commands/clusters.py:45` |
| Cross-venue Kalshi | **CLI + MCP** | `cli/commands/arbitrage.py:266`; `agent/mcp/tools/analytics.py:6,13` |
| `/holders` holder client | **nothing** — `get_holders` has zero callers anywhere in the repo (only `get_value` is used, inside `get_wallet_profile`) | `api/data_api.py:137-144` vs `:210-231` |
| Corpus design | the two most attractive analytics (risk grade, wash) are wired, but the risk grade is self-labelled *heuristic* and the wash indicator set is not surfaced at all | — |

**Test suite — ran all of it, including what their CI skips (Python 3.11.15, throwaway venv, deps from `requirements.txt`):**

```
uv venv --python 3.11 .venv && uv pip install -r requirements.txt
.venv/bin/python -m pytest tests --ignore=tests/test_live_data \
  --ignore=tests/test_tui/test_integration.py -q
=> 1393 passed, 0 failed, 89 warnings in 76.83s          (their CI-equivalent set)

.venv/bin/python -m pytest tests/test_live_data tests/test_tui/test_integration.py -q
=>   31 passed in 29.66s                                  (green: the live-network set)
TOTAL 1424 passed, 0 failed
```

No `pyproject.toml` → `uv sync --extra dev` is **inapplicable** here (`setup.py` `extras_require["dev"]` ships only build tooling); `pip install -e .` failed on system `python3` (3.9.6 — `mcp` needs ≥3.10), succeeded on 3.11. The 31 network tests (live Gamma / Data-API / CLOB assertions) **pass today** — the previous revision left these unrun; this supersedes that caveat.

## 3. Capability diff vs our stack (verified absences)

Absence proved by grep over our `src/` + `scripts/` (`--include=*.ts --include=*.py`); match counts are literal.

| polyterm has | our repo | verdict |
|---|---|---|
| CLOB REST `/book`, `/depth` (`clob.py:116,252`) | **0 matches** for `getOrderBook|/book` in `src/`,`scripts/` `*.ts` | **absent** |
| CLOB `/spread`, `/price`, `/last-trade-price`, `/ticker` (`clob.py:144-216`) | **0 matches** for `/spread`, `last-trade-price`; `ticker` only 9 incidental hits | **absent** |
| CLOB `/fee-rate` (`clob.py:180`) | **0 matches** for `fee-rate|feeRate` in `*.ts` — our rate is a **proxy**, see §3b | **absent** |
| CLOB `/prices-history` (`clob.py:81`) | **0 matches in code** — but our `drafts/backtest-engine-design-20260925.md` already names it as the price layer, with its ~145–180-row page cap and the required paging. So it is *known*, not missing | **not a gap** |
| Data-API `/holders` (`data_api.py:137-146`) | **0 matches** for `/holders` | **absent** (and unused by polyterm itself, §2b) |
| Data-API `/value` (`data_api.py:148-152`) | **0 matches** for `"/value"` | **absent** |
| `lb-api.polymarket.com/profit` (`pnl_cashflow.py:19-20`) | **0 matches** for `lb-api` | **absent** |
| The Graph subgraph (`subgraph.py`) | **0 matches** for `subgraph`/`graphql` | absent both sides (they ship it disabled) |
| Global print tape `GET /trades?takerOnly=false` (`data_api.py:119-136`) | adapter has **none**; one ad-hoc study script uses it market-scoped and documents that the default `takerOnly=true` hides maker prints: `scripts/c200-printthrough.py:151,163` | **absent from the adapter** |
| Data-API lag labeling (`data_api_lag.py`) | no equivalent module — `grep -rniE "quality_flags|qualityFlags|lagged" src/lib` → **0** systematic stamps (`polymarket.ts:53-59` mentions 429s; `:225` flags a censored page) | **absent** (doctrine only) |
| Gamma `volume24hr` (input to risk grade + wash) | **0 matches** for `volume24|volume_24` in `src/`,`scripts/` — our adapter reads `volumeNum`/`volume` (`polymarket.ts:446`) | **absent** (prerequisite) |
| CLOB WSS market channel (`clob.py:567`) | **already have**: `scripts/record-l2.ts:41` (`wss://ws-subscriptions-clob.polymarket.com/ws/market`) | present |
| Data-API `/positions`, `/closed-positions`, `/activity`, `/v1/leaderboard` | **already have**: `src/lib/adapters/polymarket.ts:109,153,191,245,254,280` (with our own empirically-derived page-cap notes at `:226-228`) | present (ours is deeper) |
| Gamma `/markets?slug=` | **already have**: `polymarket.ts:384` | present (theirs adds `/markets/keyset` pagination, `/public-search`, `/markets/{id}/liquidity`) |

Also verified about *our* side:
- Repo-wide `clob.polymarket.com` appears only in 4 ad-hoc scripts hitting `GET /markets/{condition_id}` (`src/lib/dead-market-resolution.ts:19`, `scripts/review-outcomes.ts:14`, `scripts/check-misresolved-trades.py:20`, `scripts/audit-misresolved-trades.py:81`) — **not** a CLOB client.
- Our Rust sidecar is **Kalshi-only** (`rust-sidecar/src/adapters.rs:213` → `{KALSHI_BASE}/markets/{event}/orderbook`); there is **no** Rust Polymarket CLOB client.
- **`cashPnl` appears 0 times in our repo.** Our realized PnL is computed from our own paper fills (`src/lib/paper.ts:298,324,334,402,412`), so the exact failure mode polyterm's `pnl_cashflow.py` warns about does not exist for us. That is a real (negative) finding: **no fix needed**.

### 3b. Two corrections to this audit's own earlier pass (new in v2)

**(i) "Our paper fills deliberately pay no fee" is half true and leads to the wrong verdict.** `copy-cost.ts:34` is about the *copy-cost metric* (paper fills cross no spread and pay no fee). But we do model the taker fee for admission: `src/lib/scoring/price-edge.ts:57-59` `takerFeePerShare = feeRate · p · (1−p)` — **the identical curve** to polyterm's `fees.py:90-95` with `exponent = 1` — and the *rate* is a proxy: `defaultFeeRate 0.05` (`:40-49`) plus a keyword table (crypto `.07`, politics/finance `.04`, else `.05`, `:66-75`) *because* `MarketSnapshot.category` is NULL on every row. The portable part is therefore not the curve, it is the **rate source and its provenance label**: Gamma `feesEnabled` / `feeSchedule{rate, exponent, takerOnly}` / `takerBaseFee÷10000`, with CLOB `/fee-rate base_fee÷10000` as fallback. And this is not speculative: `drafts/backtest-engine-design-20260925.md` prices the missing vig at gross +$5,397.60 → net +$2,933.77 with 238 winner→loser flips. **Corrected verdict: ⚪ → ✅ (measurement-only), and it maps to the existing card `paper-ledger-fee-fidelity`.**

**(ii) The endpoint-compat item was missed.** polyterm's own `docs/AUDIT_2026-06-01.md` records that Gamma market discovery now uses `/markets/keyset`, that legacy `/markets` offset pagination is deprecated and returns a `Deprecation: true` header with a **May 1 2026 sunset**, and that slug lookup is `/markets/slug/{slug}`. Our adapter still fetches `gamma-api.polymarket.com/markets?slug=` (`polymarket.ts:384`). That is a live-compat risk on our side, independent of adoption — worth its own card (none exists).

## 4. Fit table

Verdict key: ✅ adopt · ⚪ concept-only · ❌ not-portable

| Component | Maps to our gap? | Verdict | Why |
|---|---|---|---|
| **Per-market fee schedule + `fee_source_label` provenance** (`fees.py:32-118`; `clob.py:180`) | **yes — `paper-ledger-fee-fidelity`** | ✅ **adopt (capture only)** | Same curve we already run (`price-edge.ts:57`); the upgrade is the *rate source*. Capture `feesEnabled`/`feeSchedule`/`takerBaseFee` per market and `/fee-rate` per token into a new table with source + fetch time; nothing reads it in the live path. Read at window close. |
| **Data-API lag stamping + archive freshness flags** (`data_api_lag.py:1-84`; `archive.py:120-164`) | **yes — `data2-per-decision-provenance`** | ✅ **adopt (cheap)** | We have 0 systematic lag stamps; every Data-API-derived row (activity, positions, closed-positions, leaderboard, `takerOnly=false` prints) should carry `source` + `lagged=true`. Never invent a lag duration. Precondition for trusting any timing analysis on those surfaces. |
| **Wash-trade indicator thresholds** (`wash_trade_detector.py:67-69,181-260`) | no card; market-hygiene | ✅ **adopt (shadow only)** | Deterministic + unit-tested; our side has **0** matches for `wash`. Requires Gamma `volume24hr`, which our adapter does not parse. Do **not** wire into `rules.ts` gates on the strength of this audit. |
| **Market risk grade** (`risk_score.py:45-52,74-195`; wired `risk.py:12`, `analytics.py:26-49`) | no card; market-hygiene | ✅ **adopt (shadow only)** | Our side: **0** matches for `riskScore|risk_score`. Caveat: heuristic and self-labelled `heuristic_risk_score`; clarity factor is a subjective-keyword scan. Score the observed universe offline; no admission effect. |
| **CLOB REST read primitives + shared throttle; Gamma keyset/slug/`public-search`** (`clob.py:116-267`; `gamma.py:56-106,289-448`; rationale `docs/AUDIT_2026-06-01.md`) | no card; maintenance | ✅ **adopt (partial)** | We have zero CLOB REST calls in TS and one Rust Kalshi-only sidecar; the WS book recorder is our only CLOB surface. Depth/spread/fee-rate feed the fill model in `drafts/backtest-engine-design-20260925.md`. Separately: move off legacy `/markets?slug=` (§3b-ii). |
| TUI (82 screens, Textual/Rich) | none — our surface is the web dashboard + Discord | ❌ | No terminal surface exists or is planned |
| MCP server, 27 tools (`docs/tool-manifest.json`; `polyterm/agent/mcp/`) | none | ❌ (⚪ at most) | No MCP consumer in our stack (`grep -rl mcp src scripts` → 0); no roadmap card. Its `market.orderbook`/`wallet.whale_trades` schemas are a reference *if* we ever expose the dashboard to an agent |
| CLOB REST book/spread/price/ticker/depth | none named | ⚪ | We already record real L2 over WSS (`record-l2.ts`); a REST book is a stale fallback |
| CLOB `/prices-history` | none named | ⚪ | Already the designated price layer in our backtest design; their contribution is the granularity/window helper (`price_history.py:39-63`) |
| Data-API `/holders` (+ concentration stat) | nearest to `phase-data1` (new data surfaces, shadow-first) | ⚪ **queue candidate** | Keyless, additive, measurement-neutral; enables holder-concentration analytics we have zero of (`holders` = 0 matches). But note polyterm never calls it (§2b) — port the **endpoint**, not a client |
| Data-API `/value` | none | ⚪ | Trivial account-value read; low value for paper trading |
| P&L cashflow identity + `lb-api /profit` check | none — our PnL is self-computed | ⚪ | Useful doctrine; the bug it guards against is provably absent from our repo |
| Smart-money wallet score (`wallet_intelligence.py:45-59`) | overlaps `src/lib/scoring/wallet.ts`, `src/lib/insider.ts:8-38` | ⚪ | Heuristic, unvalidated; ours is already weighted + thresholded and shipped (`v40-homerun`) |
| Sybil cluster score (`cluster_detector.py:36-195`) | overlaps `src/lib/insider.ts:164-196` (`clusterCorrelation`, weight `0.08`) | ⚪ | Genuinely new *feature ideas* (30s co-print timing, Jaccard market overlap, shared size lattice) but their timing arm rides lagged Data-API rows, so the 30s window is not trustworthy until we move clusters to the L2/WS tape |
| Wash-trade indicators (dup of row 3) | — | — | see above |
| Intra-market / correlated-market arb | nothing named | ⚪ | Real math, but paper execution cannot capture arb, and our sidecar is Kalshi-only |
| Cross-venue Kalshi spread monitor | our Kalshi lane (18 files; `scripts/reprice-kalshi-92.ts`) + parked cards | ❌ | Adjacent-but-already-have; and maps to `kalshi-lane-ontology-not-coverage` ("0% is a CONTRACT-ONTOLOGY problem, not matcher coverage") — a title-query matcher is what our card says does not solve it |
| Pearson correlation + snapshot alignment | nothing named | ❌/⚪ | Depends on a snapshot recorder polyterm does not actually run (§5); we already have 2M `PnlSnapshot` rows + L2 files |
| RSS news ingest | `reddit-intel-digest` is Reddit/HF/arXiv; `phase-gdelt` is OSINT | ⚪ | Different sources; 3 generic crypto feeds, no scoring math — ingest/de-dupe pattern only |
| Brier score + 5 probability buckets | we already have calibration analysis (`scripts/analyze-calibration.py`; 55 `brier|calibrat` hits in `src/lib`) | ⚪ | Already covered — and their buckets start at 0.50, so a long-shot book like ours would be mostly unmeasured by their grid |
| Verified-print ingest + `NON_TRADE_TYPES` exclusion set | nothing named | ⚪ small | The split/merge/redeem/reward exclusion list is an honest, cheap hardening idea for our print path |
| Data-API lag labeling doctrine | `trading-data-integrity` intent | ⚪ → ✅ | see row 2 (now mapped to a card) |
| Quarantined demo backtest | we have a real backtest design doc | ⚪ | Interesting disclosure pattern (`backtest.py:17-55`), not a capability |
| Predicted-signal layer (`predictions.py`, `signals.py`) | vs our calibrated log-odds aggregation (`src/lib/forecasting/`, `phase-a2`) | ❌ | Additive hand-set signal strengths; ours is calibrated evidence aggregation |
| SQLite schema + queries (`db/database.py`, 15 tables) | n/a — we are Prisma/SQLite with 2M+ rows | ❌ | Their schema is materially thinner than ours |
| External datasets (PMA / Manifold / Odds API / CFTC COT) | `phase-data1`, `phase-evidence-cot` | ❌ | Absent from their repo entirely |
| Any ML | `phase-ml1`, `phase-ml2`, `ml-u1`, `ml-u2` | ❌ | No `sklearn`/`torch`/fit anywhere; `predictions.py` is threshold arithmetic |
| Order placement / keys / signing | `live-execution-reference` (Harrier is the reference) | ❌ | Zero key material and zero signed writes — by design |

## 5. Its wallet/whale tracking: is there a joinable time series? **No.**

- `market_snapshots` **is** a real price series — `(market_id, market_slug, title, probability, volume_24h, liquidity, best_bid, best_ask, spread, timestamp)` — `polyterm/db/database.py:102-115`, reader `get_market_history` `:1146-1161`, index on `(market_id)` + `(timestamp)` `:289-290`.
- **But nothing records continuously.** The only writers of `insert_snapshot` (`:1122-1144`) are two user-invoked commands: `polyterm/core/archive.py:46` and `polyterm/core/market_research.py:122`. There is no daemon/loop calling it (verified: no other `INSERT INTO market_snapshots` anywhere; the CLI `snapshot --save` writes a *separate* `market_snapshots_v2` table, `polyterm/cli/commands/snapshot.py:73,182`). So the price series is sparse and populated only when the user runs a command — `correlation.py` is effectively dormant without user discipline.
- **Wallet tables are snapshot-overwritten aggregates, not history**: `Wallet(total_trades, total_volume, win_rate, avg_position_size, total_wins, total_losses, largest_trade, favorite_markets, risk_score, first_seen, updated_at)` (`polyterm/db/models.py:10-26`), refreshed via monotone `max()` merge (`wallet_intelligence.py:153-161`) and `upsert_wallet`. No per-wallet time series exists.
- `trades` is written only while the live monitor runs (`whale_tracker.py:62-135` → `insert_trade`).

**Conclusion for (c):** copying the schema is possible but pointless — we already store 2M `PnlSnapshot` rows plus `data/*.jsonl` L2 shadow files, which is strictly more than polyterm ever holds. **No joinable time series is on offer.**

## 6. Integration proposal

**Recommendation: no adopt-now item on the live path. Three of the four ✅ rows are observability-only (allowed during the freeze); the fourth is a maintenance fix.** The two things that would touch money math directly (fee *application*, sizing) are excluded by the frozen Kelly window (through 2026-10-08) and by our paper fills' intentional zero-fee model. What is *not* excluded is capturing better inputs and *labelling* them — that changes no rule, no size, no gate and no published number.

**P1 — provenance/lag stamping (do first; cheapest).** Stamp every Data-API-derived row with `source` + `lagged=true`; add archive-style freshness flags per table. Schema/write change only; makes the existing C-200 print-through work auditable and is the precondition for any timing analysis on these surfaces. ~2h. Flag-free, revertible.

**P2 — fee-input capture (measurement-only).** New table: per market/token `feesEnabled`, `feeSchedule{rate,exponent,takerOnly}`, `takerBaseFee`, CLOB `/fee-rate base_fee`, source label, fetch time. Nothing reads it live. **Baseline required:** today's proxy (flat 0.05 + crypto .07/politics .04 keyword table). **Read at window close:** distribution of resolved rates vs proxy, and the change in `feePerShare` on markets we actually traded — reported with both numbers, after the window. ~3h. Maps to `paper-ledger-fee-fidelity`.

**P3 — market-hygiene shadow scores (off-path).** Implement the wash-trade indicator set and the 6-factor risk grade as offline scores on the observed universe (they need `volume24hr`, which we must first parse). Baselines: (1) incumbent universe filter, (2) random-score null. **Pre-registered read:** rank correlation between hygiene score and subsequent realized copy outcome on the same rows, same sign inside each `ruleSetVersion` era separately; kill rule = fewer than ~150 settled rows per arm is "too few decisions to price the gate", not a verdict. Nothing wires into `rules.ts` on this audit's strength.

**P4 — endpoint-compat fix (maintenance, not adoption).** Move `polymarket.ts:384` from legacy `/markets?slug=` to `/markets/slug/{slug}` (and consider `/markets/keyset` paging), per polyterm's `docs/AUDIT_2026-06-01.md` note about the deprecated offset pagination and its May 1 2026 sunset header. Verify against live Gamma; no card exists — worth one.

**P5 — `GET /holders` holder-concentration metric (⚪→queue, as in v1).** Port only the endpoint usage (`data_api.py:137-146`) — keyless `GET data-api.polymarket.com/holders?market=&limit=` — plus a concentration stat (top-N share of outcome supply). No polyterm code imported; ~40 lines of new TS in a new script; write to a shadow JSONL, no `dev.db` migration; single flag to revert. **Roadmap order: after `phase-data1`** (In Progress) and behind `analytics-heatmap-cost` (1h, low-traffic page).

**P6 — print-type exclusion hardening (⚪, opportunistic).** Reuse the `NON_TRADE_TYPES` idea (`print_scanner.py:15-24,149,174`) to assert our print path rejects `split/merge/redeem/reward/conversion/liquidity/deposit/withdrawal` rows and counts `skipped`. ~30 min, flag-free; it changes classification of *ingest*, so verify before/after print counts on the same window — if counts move, that is itself a finding.

## 7. NOT-portable list

1. **The TUI itself** — 82 screens + 7 infra modules (`polyterm/tui/`). Our user-facing surface is the :3013 dashboard + Discord digests; there is no terminal surface and none is planned. This is the bulk of the repo by file count.
2. **MCP/agent server** (`polyterm/agent/mcp/*`, `docs/tool-manifest.json` 27 tools) — no MCP consumer, no roadmap card.
3. **SQLite schema/queries** (`polyterm/db/database.py`, `models.py`) — materially thinner than our Prisma schema; porting would be a downgrade.
4. **Cross-venue Kalshi monitor** (`core/cross_venue.py`) — we already run a Kalshi lane, and its title-query matcher does not address our carded ontology blocker.
5. **The Graph subgraph client** (`api/subgraph.py`) — the upstream authors removed the URL and ship it disabled (`utils/config.py:37`); dead weight for them and for us.
6. **`polyterm update` / install-from-git self-updater** (`utils/github_update.py`, `install_source.py`) — irrelevant to a repo-owned stack.
7. **Demo backtest / strategy sim** (`core/demo_strategy_sim.py`, `cli/commands/backtest.py`) — seeded random; explicitly not historical. Only the *disclosure text* is worth reading.
8. **Telegram/plyer desktop notifications** (`core/notifications.py`) — our delivery channel is Discord.
9. **`market_snapshots` + Pearson correlation** (`db` series + `core/correlation.py`) — not portable in practice: no recorder feeds the series, and we already hold more history than it would.
10. **Wallet/whale DB tables** (`db/models.py` `Wallet`/`Trade`/`Alert`) — aggregate-only, no time series to join.
11. **`/holders` as a *client*** — the wrapper has zero callers in their own repo; call the endpoint directly (P5).
12. **Kelly/EV sizing calculator** (`size.py:121-175`) — ours is a book-level policy inside a frozen window (`phase-b`, `precommit-mid-oct-kelly-gate`, `kellyfraction-oct8-decision`).
13. **Calibration/Brier tracker** (`calibrate.py:403-443`) — we have an era-aware calibration read; their bucket grid starts at 0.50.

## 8. Honest caveats + verdict

**Caveats (what I did not verify):**
- I read **code**, not their claims. Their extensive `docs/` (including `docs/AUDIT_2026-06-01.md`, `docs/COMPETITIVE_GAP.md`) is **not** independently substantiated here; doc mentions of features are unverified unless I cited a `polyterm/**.py` line. The exception is the endpoint-compat claim in §3b-ii, which I treat as a lead to verify against live Gamma, not as fact.
- I did **not** drive the interactive TUI, and I did not import all 89 lazily-registered commands (`cli/lazy_group.py`) one by one — command inventory rests on their own `tests/test_cli/test_command_inventory.py`, which passed, not on my execution.
- **MCP server**: verified by source, manifest and the passing offline protocol test (`tests/test_agent/test_mcp_protocol.py`); I did not perform a live MCP handshake.
- **No Polymarket write-path call was made.** The 31 network tests do hit live read-only endpoints (that is why they matter), but I issued no order, no auth, no key operation.
- The copy formula and thresholds in `wallet_intelligence.py`/`cluster_detector.py`/`wash_trade_detector.py`/`risk_score.py` have **no validation or backtest evidence in-repo** — treat them as hypotheses, not edges. `WashTradeDetector` is not even surfaced outside tests.
- `GENERIC_FEE_SCHEDULE(rate=0.05)` is their *generic estimate* (`fees.py:22-27`) — **not** a measured Polymarket fee; its accuracy is unverified, and the same caveat applies to our own `defaultFeeRate 0.05`.
- **Maintenance risk is the dominant caveat.** One contributor, 23 days quiet, four releases inside ~21 hours then silence, `setup.py` two minor versions behind the newest tag, 2 open items — one a 5-month-old issue titled "safe??". A 57k-line tree with bus factor 1 is a *reference*, not a dependency; nothing here should be vendored or pinned.
- The clone in `/tmp/polyterm` contains my throwaway `.venv` (Python 3.11.15); nothing in `~/polymarket-copybot` was modified apart from this file.

**Verdict: SKIP as a dependency; ADOPT three small mechanisms (all freeze-safe) + one maintenance fix; no live-path change.**

polyterm is a well-engineered, honest read-only viewer whose best asset is its CLOB/Data-API *surface breadth* (book, fee-rate, prices-history, holders, value, lb-api) plus a lag-labeling doctrine — but its headline feature (the TUI) is out of scope for us, its analytics are formulas rather than validated edges, and one of its two most attractive modules (`WashTradeDetector`) is never wired to the product at all. Against the earlier pass of this audit, the correction that matters is this: **two of its mechanisms do map to existing open cards** — per-market **fee-schedule resolution** → `paper-ledger-fee-fidelity`, and the **lag/provenance stamping discipline** → `data2-per-decision-provenance` — and neither requires touching money math during the frozen window, because both are *capture and labelling* rather than application. Add the two market-hygiene formulas as off-path shadow scores with a pre-registered read at window close, and the `GET /holders` concentration metric (P5) sitting after `phase-data1`. Alongside those, our adapter's legacy `/markets?slug=` call is a live-compat item worth its own card. Re-audit only if (a) we ever want a visible second source for orderbook/fee-rate cross-checks, or (b) `phase-data1` lands and holder concentration gets a dashboard slot.

---

### Registry entry (ready to paste)

The procedure referenced `docs/GITHUB_REPO_AUDIT.md`, `update_log.md` and `data/github-audits.json`, but **none of those three files exist in this repo** (there is no `docs/` directory at all), and this task's constraint forbids touching any file outside `drafts/`. The entry is reproduced here so it can be pasted into whatever registry lives elsewhere:

```json
{
  "repo": "NYTEMODEONLY/polyterm",
  "url": "https://github.com/NYTEMODEONLY/polyterm",
  "audit_date": "2026-09-28",
  "audit_doc": "drafts/polyterm-audit-2026-09-28.md",
  "audit_revision": 2,
  "head_sha": "c878b592dee6d5ffff6f467607163dba56d7223f",
  "pushed_at": "2026-09-06T02:17:16Z",
  "stars": 359,
  "forks": 69,
  "license": "MIT",
  "license_verified": true,
  "language": "Python",
  "contributors": 1,
  "last_commit_age_days_at_audit": 23,
  "latest_release": "v0.11.6",
  "version_drift": "setup.py declares 0.11.2",
  "tests_run": { "passed": 1424, "failed": 0, "offline": 1393, "network": 31 },
  "verdict": "skip-as-dependency",
  "adopt": [
    { "item": "per-market fee schedule resolution + provenance label (capture only)", "file": "core/fees.py:32-118, api/clob.py:180", "maps_to_card": "paper-ledger-fee-fidelity" },
    { "item": "data-api lag stamping + archive freshness flags", "file": "api/data_api_lag.py, core/archive.py:120-164", "maps_to_card": "data2-per-decision-provenance" },
    { "item": "wash-trade indicator thresholds (shadow only)", "file": "core/wash_trade_detector.py:67-69,144-260", "maps_to_card": null },
    { "item": "6-factor market risk grade (shadow only)", "file": "core/risk_score.py:45-52,74-195", "maps_to_card": null },
    { "item": "CLOB REST read primitives + gamma keyset/slug compat", "file": "api/clob.py:116-267, api/gamma.py:289-448", "maps_to_card": null }
  ],
  "reject_reasons": ["demo-only backtest (no engine)", "no ML", "no execution", "single maintainer", "/holders client unused by polyterm itself", "subgraph dead upstream", "kalshi matcher does not solve contract-ontology blocker"]
}
```
