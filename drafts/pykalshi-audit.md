# pykalshi — adoption audit (arshka/pykalshi)

**Audited:** 2026-09-09 · **Clone:** /tmp/audit_triage/clones/arshka_pykalshi · **Verdict:** ✅ Borrow / ⚪ Queue (Phase C or live-execution trigger)
**License:** MIT (verified in LICENSE; Copyright (c) 2024 Arsh Koneru) — borrowable with attribution. Not AGPL, not NO-LICENSE.

---

## 1. What it is

Unofficial Python client for the Kalshi trade API v2 (`external-api.kalshi.com/trade-api/v2`, same host family as our TR-16 adapter). v2.0.0, PyPI `pykalshi`, Python ≥3.9 (repo pins 3.12), deps: httpx, pydantic≥2, cryptography, python-dotenv, websockets. Optional pandas + FastAPI/uvicorn extras.

GitHub: 123 stars, 23 forks, created 2026-02-01, pushed 2026-07-29, 1 open issue, active. Single maintainer (arshka). CI: unit tests on 3.9–3.13 + integration tests against the **demo** API when secrets exist (not forks).

Not a strategy repo — it is an **infrastructure client**. No Kelly/edge/arb math to verify; the audit targets are: endpoint surface, auth/signing correctness, retry/rate-limit behavior, direction-mapping semantics, and test quality.

## 2. Verified machinery (in source, line-checked)

- **RSA-PSS auth** (`pykalshi/_base.py`): `message = f"{ts_ms}{method}{full_path}"`, PSS/SHA256, salt=PSS.DIGEST_LENGTH, headers `KALSHI-ACCESS-KEY/-SIGNATURE/-TIMESTAMP`. Path prefix is the API base path (`/trade-api/v2`), query stripped before signing — correct per Kalshi spec.
- **Retry/backoff** (`_compute_backoff`): honors `Retry-After`, else `min(2^attempt × 0.5, 30)`; retryable statuses `{429,500,502,503,504}`. Rate-limiter reads `X-RateLimit-Remaining/-Reset` headers when configured.
- **Typed error taxonomy** (`exceptions.py`): `AuthenticationError` (401/403), `ResourceNotFoundError` (404), `InsufficientFundsError`, `OrderRejectedError` keyed on Kalshi error codes (`order_rejected`, `market_closed`, `market_settled`, `invalid_price`, `self_trade`, `post_only_rejected`), generic `KalshiAPIError`. Wire error code/message are attached to every exception.
- **Direction semantics** (the subtle part, and where this library is *better* than the official SDK's docs): canonical field is `book_side` (bid = long YES, ask = long NO) on a single YES-denominated book; `price_dollars` is always the YES-leg price. Library docstrings explicitly warn that legacy `(action, side)` means different things on orders vs fills, and the fill-mapping validator deliberately ignores `action` on sell rows (`models.py` fill validator + `test_direction.py`). Ask at 0.17 ≡ buy NO at 0.83 with no manual 1−p conversion. This is exactly the class of bug that ate our phantom 0.52/0.58 stubs (TR-16) — they've encoded the same lesson.
- **Order surface**: limit orders via `POST /portfolio/events/orders` (V2 create-order) with client_order_id idempotency, TIF (GTC/IOC/FOK), post_only, reduce_only, expiration_ts, self-trade prevention, subaccount (0–63), `cancel_order_on_pause`; amend/decrease/cancel; batch place/cancel; queue-position queries; `wait_until_terminal()` on the Order object. Order **groups** (Kalshi's rolling-15s contracts-matched rate-limit groups with auto-cancel, trigger/reset) are wrapped. Client-side price validation against `price_ranges` / `price_level_structure` when a `Market` object (not bare ticker) is passed.
- **REST breadth** (verified endpoint list, sync+async parity via codegen): account limits, api_keys (incl. programmatic `generate`), balance, fills, orders (all verbs + queue positions), positions, settlements, subaccounts (balances/transfers/netting), order groups, **historical** positions/orders/fills/markets/trades/cutoff, markets (+multi orderbooks, multi trades, candlesticks batch), events (+multivariate, +`forecast/percentile_history`), series, MVE collections, exchange status/schedule/user_data_timestamp, communications (RFQs/quotes).
- **WebSocket** (`feed.py`/`afeed.py`, sync + async): public channels ticker/orderbook_delta (snapshot+delta)/trade/market_lifecycle_v2; **private channels fill, user_orders, market_positions, order_group_updates**; local `OrderbookManager` state machine; channel-name remapping (`user_order`→`user_orders`) so `feed.on()` fires.
- **Changelog honesty is a quality signal**: recent entries remove a *silent no-op* field (`buy_max_cost_dollars` — server ignored it, orders went out uncapped), fix a batch-cancel receipt bug that reported canceled orders as `resting`, and realign RFQ/quote filters to the live API (removed filters now raise `TypeError` instead of silently returning unfiltered data). This is a library that has been burned by Kalshi's API drift and fixed it.
- **Test suite: verified locally.** `uv run --extra dev pytest tests/ --ignore=tests/integration` → **527 passed in ~7s** (mocked httpx/crypto; no network). 17 unit files incl. direction-mapping, workflow, codegen parity (sync generated from async via `scripts/generate_sync.py`), rate limiter. Integration suite requires demo creds and is CI-gated.

## 3. Fit table vs roadmap

| Component | Maps to | Verdict |
|---|---|---|
| Auth'd REST: orders/fills/positions/settlements/subaccounts + private WS channels | Phase C live leg (cross-venue arb execution), any future live Kalshi trading | ✅ Adopt when a Kalshi execution need exists (post-go-live or live Phase C) — nothing else in the stack has this surface |
| Market-data breadth: series/events/markets enumeration, candles, trades batch, exchange schedule/status | Phase C scanner + liquidity gates (design Sep 15–30) | ⚪ Borrow as reference for TS/Rust port, or run as Python probe with demo creds — see §4 friction |
| RSA-PSS signing, retry/backoff, error-code taxonomy | TR-16 adapter hardening (Rust sidecar) | ⚪ Already implemented in Rust; pykalshi = cross-check reference only |
| Order group semantics, queue positions, order amend/decrease | Future maker-flow tooling | ⚪ Concept (Kalshi venue semantics, not transferable code) |
| pandas/Jupyter rich display, web dashboard, communications RFQ module | Copybot stack (TS dashboard already exists) | ❌ Not portable / not needed |

## 4. Integration proposal

**The single biggest friction point: pykalshi is auth-first.** `_BaseKalshiClient.__init__` raises `ValueError` if no API key + private key file exist — there is no keyless mode. Our current Kalshi read path (TR-16 Rust adapter) is deliberately keyless, and wallet-parity review confirmed we hold no Kalshi credentials story. So pykalshi is **not** a drop-in for the existing depth fetch; it becomes usable the day a Kalshi account key exists (or self-serve **demo** creds, which unlock the full market-data + demo-trading surface).

Recommended sequencing:

1. **Now → nothing to merge.** TR-16 is done, Phase C design doesn't start until Sep 15, C-200 lane is Polymarket-only. No card is blocked by this repo. Queue it.
2. **Phase C design window (Sep 15–30)** — two cheap options:
   - *Borrow-only:* mine its endpoint/param map and direction semantics as the spec for a Kalshi scanner module (enumeration, candles, trades) in TS/Rust. MIT, ~half-day effort reading source, no runtime added.
   - *Python probe service:* stand up demo Kalshi creds (self-serve, ~minutes), run pykalshi in the existing `venv-calib` python environment for the arb design trials (live candles/trades/orderbooks + public WS). Effort ~1 day. Flag-revertible: it is a research probe, not on the trade path.
3. **Live Kalshi execution (later trigger, not before)** — adopt pykalshi as the execution client for whatever Python/TS process crosses venues, or port its V2 create-order body + book_side mapping to the Rust sidecar. Pin a release (changelog "Unreleased" has breaking changes — don't float on main). Risk: introduces a second runtime language on the execution path; keep it behind the same flag/approval discipline as every lane.

## 5. NOT-portable list

- The whole SDK into the Rust sidecar (it is Python; the sidecar's fetch is 40 lines and works).
- Keyless market data — architecturally absent; do not plan around it.
- pandas/dataframe extras and web dashboard — duplicates stack capabilities.
- Communications (RFQ/quotes) module — Kalshi RFQ flow has no copybot use case.
- The 527-test harness pattern is worth *copying as a convention* (mock-based, direction-focused) but not the code.

## 6. Honest caveats

- **Young + single-maintainer:** created 2026-02-01, v2.0.0, one author. Quality is unusually high for the age (changelog + tests show production use), but pin versions and don't vendor it into a critical path without a fork/fallback plan.
- **No keyless mode** (see §4) — the #1 reason it is not adopted today.
- **Kalshi API drift is the real risk, and it's mutual:** Kalshi deprecated/moved endpoints mid-2026 (our TR-16 dead host; their removed `side`/`creator_user_id` filters). Any adoption inherits that drift; pykalshi's active cadence mitigates but does not remove it.
- **WS auth:** private channels require the signed handshake — fine with creds, another reason keyless parity is out of reach (consistent with the parked Phase Kalshi-1 finding).
- No strategy math to validate (client library); the only derived formulas checked — backoff `min(2^a×0.5, 30)`, `spread_bps` from mid — are correct and standard.

## 7. Bottom line

MIT, verified 527/527 tests, production-grade Kalshi client with the *correct* direction semantics and an honest changelog. Nothing in it unblocks a current card (TR-16 already covers keyless depth; wallet parity is a data wall no client fixes). **Queue for the Phase C design window (Sep 15–30):** use it as the endpoint/direction spec for the arb scanner, optionally as a demo-creds Python probe; promote to execution-client adoption only when a live Kalshi leg is actually approved. Do not merge into the sidecar today.
