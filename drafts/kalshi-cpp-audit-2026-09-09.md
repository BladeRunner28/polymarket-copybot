# kalshi-cpp — Adoption Audit (2026-09-09)

**Repo:** Reddimus/kalshi-cpp · **License:** MIT ✅ · **Verdict:** ADOPT (spec/protocol donor; queue Rust adapter work to Phase C/D)

---

## 1. License verdict — FIRST ✅

- **MIT** (verified two ways): on-disk `LICENSE` (MIT, © 2026 Kevin Martinez Lopez) + GitHub API `license.spdx_id = "MIT"`.
- **Verdict: borrowable with attribution.** MIT permits copying logic, schemas, and comments into the Rust adapter. No AGPL/no-license constraints. Attribution: keep the copyright notice in any derived spec/source files.

## 2. What it is

C++23 SDK for Kalshi's **Predictions** API (external-api.kalshi.com/trade-api/v2): typed REST client (~75 public methods), WebSocket streaming client, RSA-PSS request signing, fixed-point string money handling, `std::expected<T, Error>` (exception-free) error model. CMake/FetchContent library, ~7,950 LOC core (`include/kalshi/api.hpp` 1,454 lines of typed models/params; `src/api/client.cpp` 4,109 lines of request/response contracts). Cloned at `/tmp/audit_triage/clones/Reddimus_kalshi-cpp` (shallow, commit `0351c66`, 2026-09-04).

Metadata: 83 stars, 1 fork, **0 open issues**, created 2026-01-11, pushed 2026-09-04. Margin/Perps API explicitly out of scope (separate host/auth/risk semantics — correct call).

## 3. Verified quality signals — unusually high for 83 stars

| Signal | Evidence |
|---|---|
| CI | 6 jobs: Linux + macOS + Windows build/test, ASan/UBSan sanitizer run, clang-tidy, markdownlint, consumer-smoke (FetchContent + install/find_package paths). Warnings-as-errors on Linux. |
| Tests | **222 test cases / 13 files** incl. **36 operation-contract tests** through an injected `HttpTransport` (no live creds, offline), signer tests (RSA keys generated at runtime — no private-key fixtures), WS parser/lifecycle tests, response-parser tests, fixed-point edge tests. |
| Fixture provenance | `tests/fixtures/PROVENANCE.md`: synthetic bodies shaped from Predictions OpenAPI 3.29.0, SHA-256 pinned (`75d99f25…`), deliberately includes fractional prices/orders that legacy integer fields can't represent — verifies parsing never rounds/saturates. |
| Contract provenance | `docs/research.md` pins OpenAPI 3.29.0 / AsyncAPI 2.0.0 / Perps digests (fetched 2026-09-03) + refresh procedure (`curl openapi.yaml` → sha256 → diff routes). `docs/api-coverage.md` = exact supported/deferred matrix. |
| Activity | SemVer + Keep-a-Changelog, 26 changelog sections; v0.5.0→0.5.1→0.5.2 released within 48h (2026-09-03/04). Recent fixes: WS URL validation, signing query-string exclusion, thread-safety of WS handle teardown, moved-from sentinel safety. Hardening cadence is real. |
| Fail-loud posture | Typed `ErrorCode` taxonomy (NetworkError, AuthenticationError, InvalidRequest, RateLimited, ServerError, ParseError, SigningError, InvalidKey); deprecated/removed legacy methods **fail before transport** with `InvalidRequest` instead of calling stale routes — same doctrine as TR-16. |

## 4. Verified endpoint coverage (typed, per `api.hpp` + `docs/api-coverage.md`)

**Market data (REST):** exchange status, schedule, announcements; user-data timestamp; **account API limits + endpoint costs** (rate-limit introspection — see §6); markets list/get; **orderbook single + batch**; market candlesticks; trades; events/series + metadata; multivariate collections read; incentive programs.

**Portfolio (auth'd):** balance, positions, orders (list/get), fills, settlements, deposits, withdrawals, total resting order value.

**Order lifecycle (auth'd, V2 canonical):** create_order (V2 single-book w/ fixed-point `count_fp`/`price_dollars`, `book_side`, `time_in_force`, `self_trade_prevention_type`, `exchange_index` auto-route -1), cancel_order V1+V2, cancel_all, **batch create + batch cancel (V1 and V2)**, order groups (create/list/get/delete), queue positions (single + batch).

**Other auth'd:** subaccounts (create, balances, transfers, netting), **RFQ + quotes** (generic and RFQ-scoped), API keys (list/create/delete), milestones, structured targets.

**WebSocket:** `orderbook_delta` (current snapshot/delta exact fields), `trade` (canonical direction, `ts_ms`), **`fill` (canonical direction, shard, fee, position fields)** — directly relevant to future fill reconciliation; `market_lifecycle_v2` market messages. Commands: subscribe/unsubscribe/add/delete markets. Deferred channels documented explicitly: `ticker`, `user_orders`, `order_group_updates`, `market_positions`, multivariate lifecycle, communications, cfbenchmarks/pyth.

**Documented-deferred REST (~40 ops)** — the repo *tells you* what it doesn't type: series/event fee_changes, forecast_percentile_history, **order-group `trigger`/`limit`**, intra-exchange-instance transfers, **FCM orders/positions**, block-trade proposals, target_balance_allocation, api_usage upgrade/volume, live_data weather/game-stats/batch, historical/archive endpoints, multivariate collection POST.

## 5. Exchange-API quirks documented in code (the de-risking payload for the Rust adapter)

These are the transferable protocol facts, verified in source, that would otherwise cost live-testing time in Phase C/D:

1. **RSA-PSS auth string** (research.md + signer): sign `{millisecond timestamp}{UPPERCASE method}{full path}` with no separators; path starts `/trade-api/v2` (REST) or `/trade-api/ws/v2` (WS) and **excludes the query string**; send via `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-SIGNATURE`, `KALSHI-ACCESS-TIMESTAMP`. WS paths also signed without query params while query stays in the upgrade request (0.5.2 fix).
2. **V2 order semantics** (client.cpp): current API = one `bid`/`ask` book + fixed-point strings; SDK rejects ambiguous legacy integer bodies pre-transport (`discard_legacy_direction` flag to intentionally override legacy Yes/Buy direction); `exchange_index = -1` = ticker-based auto-routing vs explicit exchange shard; portfolio filters carry `exchange_index`.
3. **Fixed-point money discipline**: dollar/count values keep exact wire strings; conversion to legacy int fields only when exact and in-range, else `0` — never round/saturate.
4. **Rate-limit introspection exists server-side**: `/account/api_limits` (read/write buckets) and `/account/endpoint_costs` are typed — a keyless market-data adapter can fetch and budget against these.
5. **Version pinning discipline**: whole SDK revalidated against SHA-256-pinned OpenAPI/AsyncAPI; fixtures synthetic + pinned — an offline-contract-test pattern directly portable to Rust.

## 6. Fit table vs roadmap

| Component | Verdict | Map |
|---|---|---|
| Market-data REST path/param/schema inventory (markets, orderbook, trades, events, candlesticks) | ✅ **ADOPT (spec)** | Cross-check existing keyless adapter on :3014 against `api.hpp`/`client.cpp` now (hour-level, read-only) |
| Portfolio + order lifecycle contracts (V2 orders, batch, order groups, queue positions, fills, settlements) | ✅ **ADOPT (spec)** | Phase C/D Rust trading adapter — primary donor asset |
| RSA-PSS auth contract (signing-string construction, header names, WS path rule) | ✅ **ADOPT (spec)** | Phase C/D signer (Rust `ring`/`aws-lc-rs` RSA-PSS; concept transfers, code doesn't) |
| WS message schemas: `fill`, `trade`, `orderbook_delta`, `market_lifecycle_v2` field sets | ✅ **ADOPT (spec)** | Fill/trade schemas de-risk future fill reconciliation; orderbook_delta shapes current book handling |
| Contract-provenance discipline (SHA-pinned openapi.yaml, synthetic fixtures, injected-transport contract tests) | ✅ **ADOPT (concept)** | Vendor pinned `openapi.yaml` (SHA `75d99f25…`) into stack fixtures now; offline Rust contract tests |
| Typed error taxonomy + fail-before-transport for invalid ops | ⚪ **Concept only** | Mirrors TR-16 fail-loud; adopt as design principle, not code |
| Token-bucket rate limiter + exp-backoff retry helpers | ⚪ **Concept only** | **Not wired into the repo's own transport** (opt-in; used only in an example). Rust: `governor` crate; adapter must decide retry semantics explicitly (TR-16). Note the same gap in the C++ repo is a lesson, not a template |
| Fixed-point string money handling | ⚪ **Concept only** | Rust serde: keep strings → `rust_decimal` at the edge, never float |
| C++ source (libcurl/libwebsockets transport, Glaze JSON, headers, CMake) | ❌ **NOT portable** | C++ not in runtime stack; MIT permits logic copying but no shipping C++ |
| Deferred REST: block trades, FCM, order-group trigger/limit, historical/archive, target_balance, live_data extras | ❌ **NOT portable (absent)** | Must consult Kalshi OpenAPI directly if Phase C/D ambitions include these |
| Deferred WS channels: `user_orders`, `order_group_updates`, `ticker`, `market_positions` | ❌ **NOT portable (absent)** | Order-state sync strategy must come from AsyncAPI 2.0.0 directly |
| Repo dev tooling (clang-format/tidy configs, `cpp_auto_audit.py`, examples) | ❌ **NOT portable** | C++-specific |

## 7. Integration proposal (effort / risk / flag-revertible)

**Effort: LOW now, MEDIUM at Phase C/D.**
- **Now (recommended, fits Kelly freeze — nothing ships, docs only):** (a) diff the sidecar's keyless adapter paths/params against the repo's contract surface (hour-level); (b) vendor the SHA-pinned `openapi.yaml` 3.29.0 + note in stack docs; (c) write a 1-page `kalshi-api-spec.md` in the stack capturing §5 quirks (auth string, V2 order fields, exchange_index routing, rate-limit introspection endpoints).
- **Phase C/D:** build the Rust trading adapter with this repo as the reference contract donor — endpoints, V2 field semantics, WS fill/trade schemas, error mapping. Rust signing from the documented auth contract, verified against Kalshi docs, not by porting C++.
- **Risk: LOW.** Pure spec extraction — no runtime dependency, no C++ in the stack, no behavior change to :3014. **Flag-revertible:** every artifact is a doc/fixture addition; delete at any time with zero runtime impact.

## 8. NOT-portable list (explicit)

All C++ implementation: libcurl/libwebsockets transport and its threading model, Glaze JSON serialization, header-only model structs, CMake/Makefile packaging, clang tooling configs, the MSVC `DELETE`-macro `DEL` enumerator workaround (C++-specific hazard). The ~40 deferred REST ops and deferred WS channels listed in §4 are *absent from the repo* — not portable because they don't exist here; source of truth is Kalshi's OpenAPI/AsyncAPI. Rate limiter/retry code is C++ and, more importantly, **not wired into the transport** — only the concept transfers.

## 9. Honest caveats

- **Contract snapshot age:** everything pins Predictions OpenAPI 3.29.0 / AsyncAPI 2.0.0 as of **2026-09-03**. Kalshi's API moves; re-verify the live digest before Phase C/D coding (the repo itself documents the refresh procedure — reuse it).
- **Bus factor:** 83 stars, 1 fork, 0 issues, single maintainer (© Kevin Martinez Lopez), repo born Jan 2026. The 48h v0.5.0→0.5.2 burst shows active hardening, but don't treat the repo as a living dependency — treat it as a frozen spec snapshot with an expiration date.
- **No live integration tests** (by design — injected transport only): contract tests catch schema drift, not behavioral drift in Kalshi prod. Fine for a spec donor; the Rust adapter still needs its own paper-mode live checks in Phase C/D.
- **Fill streaming gap for order-state sync:** `fill` channel is covered, but `user_orders`/`order_group_updates` are deferred in this repo — if the stack wants order-state push rather than fill-then-poll reconciliation, consult AsyncAPI directly.
- **Rate limiting is your problem either way:** repo exposes introspection models but its own limiter is opt-in and its retry helpers aren't auto-applied. The Rust adapter must pick explicit budget + retry policy (fail-loud-compatible).

## 10. Verdict

**ADOPT as spec/protocol donor — queue integration work to Phase C/D (consistent with the pre-Oct-8 freeze: nothing ships, recommendations only).** License clean (MIT). Quality is the best-per-star signal seen in this audit batch: 222 offline tests, SHA-pinned contract provenance, cross-platform CI + sanitizers, fail-before-transport error doctrine matching TR-16. Do the three cheap doc/fixture actions now (adapter path diff, vendor pinned openapi.yaml, write the spec-quirk page); build the Rust trading adapter against this contract in Phase C/D.
