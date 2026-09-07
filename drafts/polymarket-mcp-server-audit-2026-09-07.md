# Audit: caiovicentino/polymarket-mcp-server — adoption fit for Medusa CopyBot

**Date:** 2026-09-07 · **Auditor:** Hermes subagent · **Method:** GitHub API metadata → shallow clone to /tmp/polymarket-mcp → full source inspection (~9,100 LOC Python) → grep-verified tool catalog → per-component fit mapping. **No code was executed** (no venv/deps install, no live API calls); all findings are from static source reading with file:line citations.

---

## 1. What it is

An MCP (Model Context Protocol) server that lets an LLM (Claude et al.) browse Polymarket markets and — when a Polygon private key + L2 API creds are configured — place real CLOB orders. Marketing: "45 tools, real-time monitoring, enterprise-grade safety features."

| Metadata (GitHub API, 2026-09-07) | |
|---|---|
| License | **MIT** (spdx `MIT`) → **borrowable with attribution** |
| Stars / forks | 668 / 139 |
| Pushed / created | 2026-07-30 / 2025-11-11 (~39d stale at audit time) |
| Releases | v0.1.0 (2025-11-11), v0.2.0 (2026-07-30) — v0.2.0 hardened the confirmation gate |
| Contributors | 1 primary (caiovicentino, 37 commits) + 2 one-off |
| Language / default branch | Python / `main` |
| Issues | 9 open |
| Shape | ~9,100 LOC src; **30 root-level .md files** (SUMMARY/INSTALLATION/DEMO_VIDEO_SCRIPT etc. — heavy hype-doc surface vs. code); tests 173 fns / 11 files (mocked, CI present) |

**Architecture:** stdio MCP server (`mcp>=1,<2` SDK, decorator API) over a `PolymarketClient` that is a thin wrapper around **Polymarket's official `py-clob-client`** (order book, orders, positions, signing) plus hand-rolled httpx calls to Gamma (market metadata) and data-api (portfolio history). A `WebSocketManager` maintains dual WS connections (CLOB market/user + live-data) with reconnect/resubscribe, and a FastAPI web dashboard ships alongside.

---

## 2. Verified machinery (from source)

### 2.1 Tool catalog — the real count and read/write split

45 tool names verified (`server.py:110-144` docstring + router at `server.py:259-318` + `name=` scan of tool defs):

| Group | Count | Auth | Reality check |
|---|---|---|---|
| Market Discovery (Gamma) | 8 | public | search / trending / category / event / featured / closing-soon / sports / crypto — all `GET gamma-api.polymarket.com/markets` variants (`market_discovery.py`) |
| Market Analysis (Gamma + CLOB) | 10 | public | details, current_price, orderbook, spread, volume, liquidity, compare, analyze_market_opportunity **real**; **`get_price_history` and `get_market_holders` are STUBS** — both log a warning and return a hardcoded `{"error": "…not available…"}` dict (`market_analysis.py:381-384`, `:414-417`) |
| Trading | 12 | L2 | **8 write** (create_limit_order, create_market_order, create_batch_orders, execute_smart_trade, rebalance_position, cancel_order, cancel_market_orders, cancel_all_orders) · **4 read** (suggest_order_price, get_order_status, get_open_orders, get_order_history) |
| Portfolio | 8 | gated on L2 creds | all read: positions, position_details, portfolio_value, pnl_summary, trade_history, activity_log, analyze_portfolio_risk, suggest_portfolio_actions — hit **public** `data-api.polymarket.com/{positions,trades,activity}` keyed by wallet address (`portfolio.py`), not L2-authenticated CLOB endpoints |
| Real-time (WS) | 7 | 5 auth'd | subscribe_market_prices / orderbook / user_orders / user_trades / market_resolution + get_realtime_status + unsubscribe — **ALL 7 BROKEN AT RUNTIME IN HEAD** (see 2.4) |

Net genuine capability: ~**37 read/control tools that are thin REST passthroughs + 8 real-money write tools**, of which 2 read tools are stubs and 7 realtime tools error out. "45 tools" overstates working surface by ~20%.

### 2.2 Safety layer (the real substance — verified)

- **Pre-trade gate `SafetyLimits.validate_order`** (`utils/safety_limits.py:97-189`): five checks, hard-blocking (`(False, msg)`):
  1. order USD value `size×price` ≤ `MAX_ORDER_SIZE_USD` (default $1,000);
  2. projected total exposure — BUY adds `size×price`; **SELL subtracts `min(order_value, existing_position.value_usd)`**; a SELL with no position is treated as a short and *adds* exposure (`:128-137`) — correct conservative handling;
  3. per-market exposure cap (same side logic) (`:145-168`);
  4. book liquidity `Σ_{top10} bid px×sz + ask px×sz` ≥ `MIN_LIQUIDITY_REQUIRED` (default $10k) (`:170-175`);
  5. spread `(ask−bid)/bid` ≤ `MAX_SPREAD_TOLERANCE` (default 5%) (`:177-186`).
  Exposure metric: `Σ |pos.value_usd|` (`:283-285`). Note: **`AUTO_CANCEL_ON_LARGE_SPREAD` is misnamed** — it *rejects* the order when true; when false it logs and *proceeds anyway* (`:183-186`). Nothing ever cancels.
- **Confirmation gate (hard block, verified):** `create_limit_order` returns `status="confirmation_required"` with full order details and refuses to place when `should_require_confirmation()` is true and `confirm=False` (`trading.py:213-246`). Confirmation is required when `ENABLE_AUTONOMOUS_TRADING=false` (**default**) for *every* order, or above $500 when true. `execute_smart_trade` and `rebalance_position` surface the gate at top level (`trading.py:1038-1044`, `:1174-1180`) so callers can't misread success. CHANGELOG v0.2.0 confirms the gate was **previously broken** (orders placed without confirmation) and was fixed 2026-07-29 — the default flip to `false` is the fix.
- **Key handling:** private key from env only (`config.py:132-159`, validated hex, never logged, masked in `to_dict`); L2 API creds either from env or **auto-created** by signing a wallet-attestation nonce via `py-clob-client` (`auth/client.py:120-141`); order/cancel signing delegated to `py-clob-client` (`client.py:245-302`). The custom `OrderSigner` EIP-712 class (`auth/signer.py`, full Order/CancelOrder types) is instantiated but **vestigial in the order path** — orders never go through it. `DEMO_MODE` substitutes a *publicly known* dummy key (0x…0001) — acceptable only because it gates to read-only.
- **Operational:** `CANCEL_ON_SHUTDOWN` defaults true — SIGTERM/SIGINT cancels all open orders before exit (`server.py:64-99`); per-category async rate limiter incl. a `TRADING_BURST` bucket (`utils/rate_limiter.py`).

### 2.3 Deterministic "analysis" core — honestly thin (no quant)

Domain greps (`kelly|edge|calibrat|arbitrage|signal|feature`) over `src/` return **no sizing, no edge, no calibration math anywhere**. What passes for AI analysis is threshold rules with **arbitrary constants**:

- `analyze_market_opportunity` (`market_analysis.py:424-534`): risk = high if liquidity<$10k **or** spread>5%, medium if vol24h<$1k; recommendation AVOID (confidence hardcoded 30) / BUY if spread<2% (65) / HOLD (50–70); `price_trend_24h = "stable"` **hardcoded** (`:511`).
- `analyze_portfolio_risk` (`portfolio.py:966-1190`): concentration % of largest position/market; diversification = `min(100, nPos×10 + nMarkets×20)` (arbitrary); risk score 0–100 from bucketed penalties (conc>50%→40pts, market conc>60%→30pts, low-liq share>50%→20pts, minus `divScore//5`); thresholds <$1,000 top-5 book depth per position (N+1 orderbook calls).
- `suggest_order_price` (`trading.py:471-576`): passive = best ± **10% of spread**, aggressive = cross the book, mid = mid; **fill probability hardcoded per strategy** 0.95/0.4/0.7 (`:544-550`) — no queue/depth modeling. Useful mainly as a list of what *not* to do.

### 2.4 Realtime layer: broken dispatch (verified, HEAD b30d643)

- `server.py:288` dispatches every realtime tool to **`realtime.handle_tool(name, arguments, websocket_manager, server)`** — but the module defines only `handle_tool_call(name, arguments)` (`realtime.py:218`). No `handle_tool` exists → **AttributeError on every call**, caught by the generic handler → `{"success": false, "error": …}`. All 7 realtime tools are dead in HEAD.
- Even if dispatch worked, `WebSocketManager(config)` is constructed **without `notification_callback`/`log_callback`** (`server.py:422`, manager `__init__` defaults `None`), and nothing ever sets them — so subscription events (price/orderbook/order/trade) only bump internal counters (`events_received`, `message_buffer`). Nothing is ever pushed to the MCP client. "Real-time monitoring / receive notifications" is a facade; the only live read path is REST polling via the analysis tools.

### 2.5 Endpoints wrapped (verified)

| Source | Endpoints | Access |
|---|---|---|
| Gamma API | `/markets`, `/markets/{id\|slug}` (metadata: tokens, volume24hr/7d/Num, liquidity, outcomes) | public REST |
| CLOB REST | orderbook, market price, create/cancel/orders, positions — **all via `py-clob-client`**, `clob.polymarket.com` | L2-signed |
| data-api | `/positions`, `/trades`, `/activity` keyed by `user` address | public REST |
| WS | `wss://ws-subscriptions-clob.polymarket.com/ws/market` + `/ws/user` (L2 auth msg), `wss://ws-live-data.polymarket.com`; reconnect + backoff + resubscribe in manager | mixed |

---

## 3. Fit table vs. Medusa roadmap

Lens: paper-only stack (assertPaperOnly tripwires), Node/TS scorer with **existing `src/lib/adapters/polymarket.ts`** (data-api leaderboard/activity + Gamma markets — i.e., the copy-trading read surface is *already adapted*), Rust execution sidecar, Python research bot, Next.js dashboard; Kelly window Sep 8–Oct 8 = nothing ships pre-Oct 8. Hermes `~/.hermes/config.yaml` already has an `mcp_servers:` block (gdelt-cloud), so an MCP server *could* be added mechanically.

| Component | Verdict | Roadmap gap | Notes |
|---|---|---|---|
| Confirmation-gate semantics (block → `confirmation_required` → re-issue with `confirm=true`; top-level status surfacing) | ⚪ **concept-only** | sidecar/paper order flow (post-Oct-8) | Paper stack doesn't need it, but it's the *correct* shape for any future real-money gate and the changelog shows they paid real cost to fix it. Steal the semantics (2h to spec in Rust), not the code. |
| SafetyLimits exposure math: SELL reduces by `min(order_value, pos_value)`; no-position SELL = short adds exposure | ⚪ **concept-only** | TR-14 / v46 gross-exposure caps (already richer in-stack) | Stack's existing cap suite (TR-14 in-loop increment, v46 equity cap, TR-15 daily-loss) is *more* sophisticated; only the SELL/short edge-case handling is a worthwhile cross-check. |
| L2 creds auto-create flow (nonce → wallet-attestation signature → API key; secret ≠ passphrase) | ⚪ **concept-only** | rust-sidecar Polymarket adapter hardening | `py-clob-client` already ships it; sidecar should use the official lib/REST, not this repo's copy. |
| Read tool set (Gamma discovery/analysis + data-api portfolio) | ❌ **not-portable / redundant** | research bot + dashboard | 1:1 with `adapters/polymarket.ts` + research bot direct calls; 2 of 10 analysis tools are stubs; trend hardcoded "stable". Zero net data access gained. |
| `analyze_market_opportunity` / portfolio-risk scoring | ❌ **not-portable (quality)** | A2 evidence tiers, Phase B | Arbitrary thresholds + fabricated confidence constants (30/50/65/70) + hardcoded trend would *pollute* the calibrated-edge pipeline. Do not route through the Wang λ̂ / evidence layer. |
| `suggest_order_price` heuristics | ❌ **not-portable (quality)** | C-200 exec / TR-16 adapter | mid-or-worse pricing with made-up fill probabilities; stack already has real-book depth work. Reference of what not to do. |
| WebSocket manager (dual-conn, backoff, resubscribe) | ⚪ **concept-only** | research-bot live prices (if ever needed) | Plumbing pattern is sound but **unusable here** (broken dispatch + no callback wiring); sidecar/scorer already own WS ingestion with real-book Kalshi adapter. |
| Web dashboard (FastAPI) | ❌ **not-portable** | Next.js dashboard exists | 528 LOC; no feature the dashboard lacks. |
| The "45 tools / AI trading" framing | ❌ **not-portable (honesty)** | — | Overstates working surface ~20%; relevant only as a *don't-trust-README* calibration point. |

**(a) Read-side tooling for research bot/dashboard:** No. Duplicates existing adapter; 2 stubs; no deterministic core worth calling; data is 3 `curl`s away. **(b) MCP tool for Hermes Agent:** Mechanically possible (read-only mode, no keys → 25 tools) but delivers only thin Gamma passthroughs for ad-hoc market browsing, with prompt-injection surface (market text through tool output) and a broken realtime layer — the stack's research bot already treats market data as untrusted, and paper-only posture argues against ever enabling the 8 write tools. **(c) Execution-layer reference for the Rust sidecar:** The only venue with genuine value, and only at the concept level (gate semantics in §2.2), because the sidecar already implements a *richer* gate suite and real-book adapters.

---

## 4. Integration proposal (if pursued at all)

Nothing is adopt-now. A **concept-borrow** ticket could read: *"Spec: confirmation-gate semantics + SELL/short exposure edges (from polymarket-mcp-server audit) as a one-page risk-gate checklist for the Rust sidecar order path"* — effort ~2–4h spec + review, risk near-zero (documentation only), flag-revertible trivially (no code merged). **Do not** add `polymarket-mcp` as a Hermes MCP server or research-bot dependency: duplicate adapter surface, two stub tools, seven dead realtime tools, and heuristic "confidence" numbers that would cross-contaminate the calibrated pipeline. If the Oct-8 gate passes and the user still wants Hermes-native market lookup, a 30-line stdio MCP wrapping the *existing* `adapters/polymarket.ts` (or direct Gamma calls) would beat this repo's read mode on every axis — effort ~0.5 day.

## 5. NOT-portable list

- Everything under `tools/market_analysis.py`'s opportunity/risk scoring and `portfolio.py`'s risk score (arbitrary constants; would corrupt calibrated signals).
- `suggest_order_price` / `execute_smart_trade` "AI" decomposition (keyword-parsed intents, hardcoded fill probabilities, 2-order naive splits).
- Realtime tool suite (broken dispatch `server.py:288` → missing `handle_tool`; no callback wiring → events never delivered).
- `get_price_history` / `get_market_holders` (stubs).
- `OrderSigner` custom EIP-712 (vestigial; `py-clob-client` owns signing).
- Web dashboard, Docker/k8s scaffolding, the 30-file doc corpus.
- Any Python code wholesale — stack is TS/Rust; MIT license permits copying with attribution, but nothing here survives a language-port cost/benefit test except documented *semantics*.

## 6. Honest caveats + verdict

- **Caveats:** Static audit only — no tests run (heavy deps, no venv), no live endpoint calls; the realtime-dispatch break is a code-level certainty (missing symbol) but I did not execute it; `pushed_at` 2026-07-30 means findings describe a repo that may have moved in ~39 days (9 open issues suggest churn). 668 stars vs. a single author and 2 releases = popularity is README-driven; treat marketing claims as claims. The v0.2.0 changelog, however, shows genuine safety engineering (confirmation gate fix, secret/passphrase split, multi-outcome explicit `outcome`) — the *safety posture* is the one thing in this repo that is more mature than the surrounding hype.
- **Verdict: SKIP** (do not adopt now, do not queue behind any roadmap card). The stack already owns the read surface (`adapters/polymarket.ts`), owns richer risk gates (TR-14/TR-15/v46), is paper-only (making an 8-tool real-money write layer a liability, not an asset), and the repo's only durable value — confirmation-gate and exposure edge-case semantics — is a 2-hour concept borrow into the sidecar's spec, eligible anytime post-Oct-8 without touching the Kelly window. Revisit only if a concrete "Hermes-native market browsing" want appears; if it does, prefer a thin MCP over this server's read mode.
