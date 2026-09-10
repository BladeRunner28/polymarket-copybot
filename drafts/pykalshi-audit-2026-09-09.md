# Repo audit — arshka/pykalshi (Python client for Kalshi trade API v2)

**Date:** 2026-09-09 · **Auditor:** subagent (repo-audit workflow) · **Status:** QUEUE (pre-Oct-8 freeze — recommendation only)
**Source of truth:** shallow clone at /tmp/audit_triage/clones/arshka_pykalshi (HEAD as of 2026-09-09); GitHub API metadata re-fetched 2026-09-09.

## What it is

Unofficial, **MIT-licensed** (LICENSE file present, © 2024 Arsh Koneru; GitHub API confirms spdx `MIT`) typed Python client for Kalshi's `trade-api/v2` REST + WebSocket. v2.0.0, **123★ / 23 forks**, created 2026-02-01, last push 2026-07-29 — young but actively maintained, single maintainer, breaking-change discipline documented in CHANGELOG.md. Ships sync **and** async clients (async handwritten, sync **auto-generated** by `scripts/generate_sync.py` with a parity test in `tests/test_codegen.py`), Pydantic v2 models, WebSocket feed with typed messages + reconnect/resubscribe, local `OrderbookManager`, exponential-backoff retries, pluggable rate limiter, typed exceptions, pandas/Jupyter sugar.

**License verdict: MIT → borrowable with attribution.** No restrictions on porting wire/domain semantics to the Rust sidecar.

## Verified quality (ran locally)

- Python ≥3.9, dev on 3.12 (`.python-version`); deps only `httpx`, `pydantic>=2`, `cryptography`, `python-dotenv`, `websockets` (+pandas/fastapi as extras).
- **527 unit tests pass** in 2.7 s in a fresh `uv sync --dev` venv (`pytest tests/ --ignore=tests/integration`). Auth + HTTP fully mocked — no network. CI matrix runs these on py3.9–3.13 plus demo-credential integration tests on main pushes (`tests/integration/`, `skipif` no-cred-safe).
- Test surface is domain-heavy, not stub-heavy: direction semantics (`test_direction.py`), order workflow place→fill→cancel (`test_workflow.py`), rate limiter, feed reconnection, sync/async codegen parity, series/dataframe.
- Changelog shows real battle fixes, e.g. batch-cancel receipts reporting every order `resting` (status inversion bug, fixed), silent-no-op `buy_max_cost_dollars` removed (server ignored it), WS fill `market_ticker` alias bug. Credible production intent.

## Auth model (the Phase C/D core)

- `pykalshi/_base.py` L30-31: `DEFAULT_API_BASE = https://external-api.kalshi.com/trade-api/v2`, demo base on `external-api.demo.kalshi.co`. **Same host the keyless sidecar already uses.**
- RSA-PSS/SHA-256 signing over `timestamp+method+path` (`_sign_request` L92), headers `KALSHI-ACCESS-KEY/SIGNATURE/TIMESTAMP`. Constructor **requires** creds (`KALSHI_API_KEY_ID` + PEM key path) — **no keyless mode**; cannot drop into the keyless market-data path unchanged.
- Retries: 429/500/502/503/504, exp backoff `min(2^attempt × 0.5, 30)` honoring `Retry-After`, max 3 (L33, L189-206). Pluggable `rate_limiter` (313-line module) consuming `X-RateLimit-Remaining/Reset` + local throttle.
- Error taxonomy maps Kalshi error codes to typed exceptions (`_handle_response` L118-187): `AuthenticationError`, `ResourceNotFoundError`, `InsufficientFundsError`, `OrderRejectedError` (order_rejected / market_closed / market_settled / invalid_price / self_trade / post_only_rejected), `RateLimitError`.

## Verified REST coverage (grep of `pykalshi/_sync/*` + `_async/*`; both clients)

Market data (public REST — the keyless sidecar's lane):
- `GET /markets`, `/markets/{ticker}` (+filters/status), batch `/markets/orderbooks`, single `/markets/{ticker}/orderbook` (`_sync/markets.py` L121)
- Candles `GET /series/{series}/markets/{ticker}/candlesticks` (L139) + batch `/markets/candlesticks` (`_sync/client.py` L399)
- Tape `GET /markets/trades` (multi-market, L377) — real-time Kalshi trade REST
- `GET /events`, `/events/{ticker}`, `/events/multivariate`, `/events/{ticker}/forecast/percentile_history`
- `GET /series` / all-series; `/multivariate_event_collections` (+`/{ticker}/lookup`)
- `GET /exchange/status`, `/exchange/schedule`, `/exchange/user_data_timestamp`
- `GET /historical/markets`, `/historical/trades` (and auth'd `/historical/orders|positions|fills|cutoff`)

Auth'd trading/portfolio (the Phase C/D leg — **nothing like this exists in the sidecar today**):
- `GET /portfolio/balance`, `/positions`, `/fills`, `/settlements`, `/portfolio/summary/total_resting_order_value`
- Orders: `POST /portfolio/events/orders` (place), `DELETE` + `/amend` + `/decrease` on `/portfolio/events/orders/{id}`, batched place `/portfolio/events/orders/batched`, batched cancel, `GET /portfolio/orders` + `/{order_id}`, queue positions (`/queue_position(s)`)
- Order groups: `/portfolio/order_groups` create/list/get + `/limit`, `/reset`, `/trigger` (Kalshi's rolling-15s contract-rate-limit group with auto-cancel — the bracket/velocity primitive)
- Subaccounts: balances, transfers, netting; `/account/limits`; `/api_keys` + `/generate` (programmatic key creation)
- Communications (RFQ): `/communications/rfqs` + `/{id}`, `/communications/quotes` — recently realigned to the live spec (2026-06-20 filter removals) per CHANGELOG

Order semantics wrapped (`portfolio.py` place_order L88+, enums L63-123): limit orders, TIF GTC/IOC/FOK, `post_only`, `reduce_only`, `expiration_ts`, `cancel_order_on_pause`, self-trade-prevention (cancel-resting / cancel-incoming), `client_order_id` idempotency, fractional `count_fp`, subaccounts, order-group linkage. **Canonical direction is Kalshi's single YES-denominated book**: `book_side` bid=long yes / ask=long no, price always the YES leg; legacy `action/side` mapped with 1−p conversion — and the library's docs/tests hammer the footgun that legacy `side` means *different things on orders vs fills* (branch on `book_side`). This is exactly the class of domain trap that costs real money in an adapter port.

WebSocket feed (`pykalshi/feed.py` L497-505; `wss://external-api-ws.kalshi.com/trade-api/ws/v2`): public `ticker`, `trade`, `market_lifecycle_v2`, `orderbook_delta` (**docstring says requires auth — verify at build time**), private `fill`, `market_positions` (real-time P&L), `order_group_updates`. Typed messages (BaseModels), background-thread reconnect with resubscribe, heartbeat/`last_message_at`/`reconnect_count` metrics — watchdog-ready design. `OrderbookManager` (`orderbook.py`) applies snapshot+delta to a local book.

Finance math: **no strategy/P&L math engine** — but models carry the execution-accounting fields (fees: `taker_fees_dollars`, `maker_fees_dollars`, `average_fee_paid_dollars`, `fee_cost`; `spread`/`spread_bps`/`mid` computed in Decimal on fixed-point dollar strings, models.py L547-568; net P&L property on positions = revenue − cost basis − fees). It is a *data-contract* donor for the paper-fill/P&L layer, not a math donor.

## Fit table vs roadmap gaps

Roadmap context: TR-16 (Done 2026-09-03) left the sidecar's Kalshi lane **keyless and read-only**: Polymarket-question → Kalshi-event resolution via bounded `/events` walk, top-of-book `/markets/{ticker}/orderbook` fetch (Kalshi public book = one level/side; BUY=1−no_bid, SELL=yes_bid), 429 backoff ×1-2, fail-loud → book at PM reference with execution note. **Kalshi trading = Phase C/D** (Phase C Backlog: design Sep 15–30, build early Oct) and needs the auth'd surface. Kelly window Sep 8–Oct 8 = nothing ships.

| Component | Fit | Roadmap slot | Notes |
|---|---|---|---|
| Auth'd REST trading surface (place/cancel/amend/decrease/batch, queue pos, balances/fills/positions/settlements, v2 ack semantics, client_order_id idempotency) | ✅ concept donor — port endpoint semantics + wire bodies to Rust trading adapter | Phase C/D trading leg (build early Oct+) | The single highest-value transfer; thin HTTP wrapper in Rust is low-effort **iff** the semantics are copied correctly — this is where that knowledge lives |
| Kalshi error-code taxonomy → typed failures + retry-on-429 policy | ✅ adopt (port) | Phase C/D | Straight copy: `_handle_response` map + backoff rule mirrors the sidecar's fail-loud doctrine |
| Direction semantics (book_side vs outcome_side vs legacy; fills ≠ orders) | ✅ adopt (port as enums + tests) | Phase C/D | Highest footgun density; port their tests too |
| WS private channels (fill, market_positions w/ P&L, order_group_updates) + reconnect/resubscribe + local book | ⚪ concept-only (port design; tokio-tungstenite already a sidecar dep) | Phase C/D execution monitor | Real-time execution leg for paper-fill realism (Phase D2 fill-model input) |
| Order groups (rate-limit group, reset/trigger) | ⚪ concept-only | Phase C/D only if strategy needs velocity/bracket control | Niche; skip unless needed |
| Market-data breadth gap vs keyless adapter (candles, /markets/trades tape, forecast percentile_history, exchange/status+schedule, batch orderbooks) | ⚪ queue | Data-1 / research scripts | Keyless adapter reads only top-of-book at paper time; pykalshi (with a read key) fills candle/tape/status gaps in research scripts — but creds = trading-adjacent, so pre-C/D use stays in scripts/venv-calib research lane |
| pandas/Jupyter/repr/web dashboard, sync-from-async codegen | ❌ not portable | — | Python-only ergonomics |

**Keyless adapter gaps pykalshi would cover (when creds exist):** everything under `/portfolio/*` and `/portfolio/orders*`, order lifecycle + batching, queue position (fill-probability signal), settlements reconciliation, account limits, subaccounts, RFQ/comms, historical orders/positions/fills for P&L backfill, private WS channels — plus market-data breadth (candles, multi-market tape, exchange status/schedule, forecast percentiles) that the sidecar never polls. The adapter's *current* gap is narrower than that list implies: for paper-only Phase B it needs only executable quotes, which TR-16 already provides fail-loud. The gap only becomes real when Phase C/D turns the Kalshi leg live.

## Integration proposal (Phase C/D, post-Oct-8)

1. **Do now (freeze-compliant):** file this audit; when Phase C design opens (Sep 15–30) cite `pykalshi/_sync/portfolio.py` + `_base.py` + `enums.py` + `feed.py` as the semantic spec for the Rust trading adapter. Optionally pin a known commit SHA in the design doc so the donor is immutable.
2. **At Phase C/D build:** port, in order — (a) v2 order wire contract + ack-status handling + `client_order_id` dedupe; (b) error-code taxonomy + retry/backoff; (c) direction enums with the fills-vs-orders caveat and mirrored tests; (d) WS private-channel consumer w/ reconnect (reuse sidecar's existing tungstenite stack). **Effort: ~1–2 dev-days including tests** for a thin typed wrapper (no math, no state machine beyond order lifecycle). **Risk: low-medium** — semantics are the value and they're already debugged here; residual risk is spec drift since 2026-07-29 (Kalshi has moved filters/params before — see CHANGELOG), so validate payloads against the live OpenAPI spec at build time.
3. **Flag-revertible:** yes — the trading adapter ships behind the existing venue/paper posture; nothing in this audit implies capital deployment. Any pre-C/D research use (candles/tape pulls) lives in the Python research lane, keyed read-only, and is trivially removable.
4. **Verification path:** this repo's own integration tests are demo-credential-gated and CI-ran; the honest dry-run for the Rust port is Kalshi **demo** (external-api.demo.kalshi.co) before mainnet keys.

## NOT-portable list

- The runtime itself (Python/httpx/pydantic/websockets) — stack is TS/Rust; pykalshi is a **spec/coverage donor, not a dependency**.
- pandas/DataFrame/Jupyter rich-display/web-dashboard extras.
- Sync-from-async code generation (only matters if the donor were kept in Python).
- `OrderbookManager` delta-application code (concept ports; tokio + tungstenite is the sidecar's home for it).
- No keyless mode — cannot replace the sidecar's keyless market-data adapter as-is (constructor hard-requires creds).

## Honest caveats

- **Young, single-maintainer, unofficial.** Created 2026-02-01; v2.0.0 with real breaking-change discipline, but bus-factor 1 and no Kalshi affiliation.
- **Not full-spec coverage.** README concedes the official auto-generated SDK has "full API coverage"; pykalshi is a curated subset (e.g. it chased RFQ/quote spec drift in Unreleased changes rather than being generated). Port semantics against the live spec, not against this repo alone.
- **No live-trade verification in unit tests** — 527 tests are mock-based; the real-fill path is only covered by demo-credential integration tests.
- **WS `orderbook_delta` now documented "requires auth"** in this repo — if true, it changes the keyless real-time-depth roadmap (currently REST top-of-book poll). Verify against Kalshi before designing the WS leg.
- Deliberately not compared against the official `kalshi-python` SDK in depth; if Phase C/D wants an auto-generated full-spec base instead of a curated one, that is a separate (cheap) audit.

## Verdict

**QUEUE** — not adopt-now, not skip. Tied to roadmap order and the Sep 8–Oct 8 freeze: the stack's Kalshi lane is paper-only and already fail-loud at the executable quote it needs, so pykalshi buys nothing that ships before Oct 8. Its value is (a) the **semantic spec donor for the Phase C/D Rust trading adapter** — auth'd order lifecycle, error taxonomy, direction footguns, WS private channels — which is exactly the untested, high-footgun part of the future leg, and (b) a cheap read-only data source for research scripts once a key exists. MIT makes the port clean. Pin the SHA in the Phase C design doc (Sep 15–30), port at Phase C/D build (~1–2 dev-days, flag-revertible, demo-first verification), and re-verify payloads against the live OpenAPI spec at build time.
