# Repo Audit — KaustubhPatange/polymarket-trade-engine ("Early Bird")

**Audited:** 2026-09-09 · **License:** MIT (verified verbatim, LICENSE file, Copyright (c) 2026 Kaustubh Patange) → **borrowable with attribution** (keep notice on copied files) · **API:** 316 stars, TypeScript, archived=false, pushed 2026-06-08, default branch master
**Clone:** /tmp/audit_triage/clones/KaustubhPatange_polymarket-trade-engine (not re-cloned)
**Verification run:** `bun test` → **140 pass / 2 fail of 142** (both failures are network-only: curl-TLS fetch test + live Binance WS stream, sandboxed env). Engine typechecks/runs clean under bun. ~11.2k lines TS.

---

## What it is

A **live, tested execution engine for Polymarket 5-min/15-min crypto up-down binaries** (BTC/ETH/XRP/SOL/DOGE/HYPE/BNB), written in TypeScript/Bun. NOT a thin CLOB wrapper and NOT an LLM/agent project. It is a genuinely engineered order-lifecycle state machine: market lifecycle orchestration (`INIT→RUNNING→STOPPING→DONE`), CLOB fill-settlement race handling over the user WebSocket channel, retry/recovery, emergency exits, resolution/redeem automation, crash recovery, a session-loss circuit breaker, and a surprisingly realistic simulation harness (deterministic orderbook fills, modeled on-chain balance delay, FOK semantics) with a 142-test suite driving it. Strategy layer is trivial (fixed 6-share buy&hold entries timed by RSI/ATR/gap heuristics on a 5-min window); **zero Kelly/edge/sizing math, zero calibration/evidence, zero arbitrage, zero cross-market logic** — confirmed by domain grep over engine/, tracker/, utils/.

**Domain:** BTC-updown momentum timing on hard 5-min windows. **Its value is execution correctness, not signal.**

---

## Verified machinery (from source, file paths relative to clone root)

1. **Two-phase MATCHED→MINED fill-settlement state machine — `engine/user-channel.ts` (the crown jewel).**
   - Taker orders **never receive an order `UPDATE MATCHED` event** on this CLOB — the trade event is the only fill signal (lines 52–55, 115–118). Maker fills handled as safety net.
   - Buffers `MINED` amounts and `MATCHED` trade IDs that arrive **before** `trackOrder()` (race between placement response and WS event) — lines 50–55, 158–186.
   - `untrackOrder()` preserves matched-but-not-mined orders so an in-flight settlement can still fire `onFilled` (lines 71–80) — cancels racing MATCHED never drop a trade.
   - `_trySettle` fires `onFilled(total)` only when `minedAmounts.size ≥ associatedTrades.size` — waits for ALL constituent trades of a multi-trade order (lines 190–198).
   - WS reconnect → one-shot **REST reconciliation** sweep via `getOrderById`, `actualShares > 0 ? actualShares : shares` gross fallback (lines 292–320).
   - Verified by tests: taker-only flow, MINED-before-MATCHED, buffered-before-trackOrder, multi-trade waits — all pass.
2. **Placement retry with balance-error share-resize — `engine/market-lifecycle.ts` `_placeWithRetry` (lines 641–836).** Regex-parses the CLOB insufficient-balance error `balance:\s*(\d+).*?order amount:\s*(\d+)` and shrinks `shares = actualBalance / 1e6` (lines 730–739) to keep trading through Polymarket's on-chain balance-lag. Buys retry 30× @ 500 ms (`BUY_MAX_RETRIES`/`BUY_RETRY_DELAY_MS`, lines 485–489); sells retry until slot end. Pre-flight tracker gating (`canPlaceBuy`/`canPlaceSell`, lines 682–689) avoids burning network calls on known-invalid orders.
3. **Expiry/cancel race discipline — same file.** `_checkExpiries` defers expiry for orders that have MATCHED but await MINED (450–464); reads partial fill via `getMatchedSoFar` BEFORE cancelling (455–459); `_cancelOrders` filters out `isMatched` ids so cancels can't unlock a wallet that a pending settlement will still debit (495–500). Tested: "lifecycle-initiated cancel does not call onFailed", "emergency sells fill despite 4s MINED delay".
4. **Emergency-sell loop — lines 545–594.** Cancel-and-replace: re-place GTC sell with **2 s expiry at the fresh best bid**, loop until filled or slot end — time-boxed exit that tracks the market price on every retry. Directly reusable as a time-boxed-exit primitive.
5. **FOK fee model — lines 780–789.** `fee = grossShares × feeRate × price × (1 − price)`; net shares = `gross − fee/price`. Matches the binary-market (1−p)·p fee-basis convention; applied only to FOK (taker) orders, `feeRateBps` read live from the orderbook WS `last_trade_price` channel. ⚠ Verify basis against the live CLOB fee endpoint before reuse.
6. **Reservation wallet ledger — `engine/wallet-tracker.ts`.** Shadow balance = real − Σ reserved buy costs; `availableShares = held − reserved-for-sells`. Handles the partial-fill-after-cancel branch (reservation already unlocked → deduct actual cost, lines 66–84). Prevents double-spend and phantom sells without awaiting CLOB settlement.
7. **Crash recovery — `engine/state.ts` + `engine/recovery.ts` + `engine/early-bird.ts`.** Atomic snapshot (tmp+rename) every 5 s of pending orders/orderHistory per market; on boot, REST status-check each pending order (`getOrderById`), filled→history, live→drain, cancel stale buys (strategy callbacks unrecoverable), resume only sell-drain in STOPPING. Sim balance replay from orderHistory. Session-loss breaker: `MAX_SESSION_LOSS` (default $3) hard-shutdown, persisted across restarts (early-bird.ts 62, 144–152, 261–265).
8. **Sim harness realism — `engine/client.ts` `EarlyBirdSimClient` (lines 136–322).** Modeled on-chain balance delay (`SIM_BALANCE_DELAY_MS` default 4000) before sells allowed after a buy fill; FOK = fill-now-or-kill exactly like the CLOB; fill requires counterparty liquidity `> shares × price × 2` (lines 110–128); `SimUserChannel` synthesizes MATCHED/MINED/CANCELLATION events so the settlement machine is exercised offline. Realistic-paper-trading architecture worth copying.
9. **Lifecycle state machine + ctx API — `engine/market-lifecycle.ts` + `engine/strategy/types.ts`.** Strategy = function over a context with fire-and-forget `postOrders` (never await placement; react via onFilled/onExpired/onFailed), `hold()` refcount keeps RUNNING alive for event-driven strategies, `blockBuys/blockSells`, `emergencySells`, cleanup-fn on destroy (useEffect-style). PnL computed on resolution with $1/share winner payout, auto-redeem via CTF `redeemPositions` relay tx (946–1001, 922–932).
10. **Orderbook tracker — `tracker/orderbook.ts` + `utils/price-level-map.ts`.** Red-black-tree price levels (O(log n) set/delete, incremental `totalLiquidity`), book-snapshot + `price_change` delta handling, book-walk buy-cost calculator walking asks (lines 165–192).
11. **Notable ops note:** code comment at `tracker/api-queue.ts:75–93` — Polymarket crypto-price API now requires TLSv1.3 mlkem768x25519 (curl ≥ 8.19); they keep a `useCurl` toggle because Bun/Node BoringSSL hits ECONNRESET. Relevant if the stack ever polls that endpoint.

**Test evidence:** `bun test` → 140 pass / 2 fail (network-only), 298 expect() calls, 15 files. Coverage includes the full fill-settlement race matrix, lifecycle PnL paths (positive/negative/resolution), emergency sells, FOK fee deduction, wallet-insufficient retries, hold semantics, cleanup-once semantics.

---

## Fit table vs roadmap gaps

| Component (repo) | Roadmap hook | Verdict | Notes |
|---|---|---|---|
| Two-phase MATCHED→MINED settlement + race buffers + reconnect reconcile (`user-channel.ts`) | Shipped TS/Rust CLOB exec layer | ⚪ **concept-only → verify-gap** | Strongest item. If the shipped sidecar lacks any of: taker-no-UPDATE-MATCHED handling, matched-not-mined cancel guard, MINED-before-trackOrder buffering — port the pattern (not wholesale code; Rust rewrite). Pattern diff first. |
| Balance-error regex + share-resize retry (`market-lifecycle.ts:730–739`) | Exec-layer hardening | ⚪ **concept-only** | Concrete, tested trick for pUSD/USDC on-chain balance-lag. Port if sidecar retry is naive. |
| Time-boxed emergency-exit loop (cancel→re-place at fresh best bid, 2 s GTC) | **Phase C arb fills**, Phase D2 Cox-PH exits | ⚪ **concept-only** | Exit discipline primitive; arb matching sits on this. Capture as design pattern. |
| Reservation wallet ledger (partial-fill-after-cancel branch) | Rust sidecar accounting | ⚪ **concept-only → verify-gap** | Check sidecar ledger covers the double-count hazards (matched-not-mined cancel vs onFilled). |
| Crash recovery: 5 s atomic snapshot + boot REST reconcile + drain mode | Exec-layer ops | ⚪ **concept-only → verify-gap** | Design checklist; most stacks hand-wave this. |
| Realistic sim harness (balance delay, FOK kill, liquidity-gated fills) | Paper-only posture | ⚪ **concept-only** | Xman is paper-first; this is the reference model for honest sim fills. |
| Session-loss circuit breaker (persisted) | Risk ops | ⚪ concept-only | Note for Kelly-window recs; not new (Xman risk engine covers), but cheap idea. |
| FOK fee formula (1−p)·p basis | CLOB fee handling | ⚪ concept-only | Verify basis vs live fee endpoint first. |
| Strategy layer (RSI/ATR/realized-vol gap-timing, fixed 6-share sizing) | Data-1 / ML-2 / sizing | ❌ **not portable** | Crypto 5-min momentum domain; arbitrary fixed sizing, no calibration. |
| Ticker multi-exchange divergence (Binance/Coinbase/OKX/Bybit) | — | ❌ not portable | Crypto-asset specific; Xman has its own price lanes. |
| Slot/slug anchor math (`utils/slot.ts`) | — | ❌ not portable | Polymarket updown slug format specific. |
| pUSD wrap/unwrap + relayer redeem flows (`engine/client.ts:548–636`) | — | ❌ not portable | Chain-ops plumbing already implied in shipped stack. |
| React run-analysis dashboard (`analysis/`) | Shipped TS dashboard | ❌ not portable | Duplicates shipped dashboard. |
| CLOB client wrapper (clob-client-v2 signing, `signatureType: 1` Magic creds) | Rust sidecar CLOB layer | ❌ not portable | Standard SDK wrapper; nothing new. |

**Bottom line: no Kelly, no calibration, no arb, no cross-market, no ML, no whale/sports logic. Overlap with shipped stack is the whole execution plane — the repo's edge is the *depth of its execution edge-case handling*, which is exactly the category the audit brief said to check for. It is not "just another thin CLOB wrapper", but it is also not an engine to adopt wholesale.**

---

## Integration proposal

Respecting the **Sep 8 – Oct 8 Kelly measurement freeze (nothing ships, recommendations only, all integrations flag-revertible):**

1. **Now–Oct 8 (read-only, 1 dev-day):** Exec-layer **pattern diff** — run the shipped TS/Rust sidecar's order-lifecycle handling against the six ⚪ rows above. Deliverable: a gap checklist (no code changes). Zero risk, trivially flag-revertible (it ships nothing).
2. **Post-Oct 8, Phase C pre-work (2–4 dev-days, flag-revertible):** backfill the top verified gap in the Rust sidecar — expected candidates: taker-fill signaling or matched-not-mined cancel guard or balance-lag share-resize — as a new unit-tested module behind a feature flag, borrowing the repo's test scenario matrix (its 6 user-channel race tests are a ready-made spec). Attribution: MIT notice in header comment + doc.
3. **Roll into Phase C matching/execution hardening backlog:** emergency-exit loop and time-boxed GTC-replace semantics as the fill-exit primitive both arb legs will need.

**Risk:** low. MIT; pattern-level extraction; paper-only posture unchanged; no market-data dependency; no new runtime components. Repo is unmaintained-ish (last push Jun 2026) and live-money oriented — do NOT run as-is (its market domain + live posture conflict with Xman policy).

---

## NOT-portable list

- **Kelly/sizing/risk math — does not exist here.** No position-sizing code at all (strategy hardcodes 6 shares, `late-entry.ts:216`). No calibration, no evidence aggregation — strategy is a momentum heuristic, and repo README/docs never claim otherwise.
- **Strategy signals (RSI/ATR/gap/divergence on BTC)** — domain-specific to 5-min crypto updown; ATR impl is simplified (|Δclose| only, not true-range) — do not import as a reference ATR.
- **Ticker aggregation, slot anchor math, slug parsing** — polymarket-crypto specific.
- **Wallet/relay chain plumbing (pUSD wrap/unwrap, CTF redeem via builder-relayer)** — duplicates shipped chain ops.
- **React analysis dashboard** — duplicates shipped TS dashboard.
- **The whole-engine adoption** — would be a rewrite onto a different domain; shipped stack already covers transport.

---

## Honest caveats

- **Internal-gap uncertainty:** whether the shipped Rust/TS exec layer already covers items 1/3/5/6 could not be verified from here (audit of internal code out of scope) — hence "verify-gap" verdicts. If the sidecar already has all of them, the repo downgrades to *skip-with-concepts* (a checklist review still worth 1 hour).
- Fee formula and crypto-price TLS note flagged for live verification before any reuse.
- 2 test failures are environment-network-only; repo CI (`test.yml`) runs `bun test` only — no typecheck gate in CI; my scoped `tsc` run surfaced only a viem typing drift under non-repo flags, not logic errors.
- Stars (316) ≠ edge; the star count is mostly the story (MOTIVATION.md) + dashboard, not the machinery.

---

## Verdict: **QUEUE — concept extraction, not adoption.** ⚪

Tied to roadmap: it feeds **execution-layer hardening**, the correct slot being *pre-Phase-C* (Phase C arb matching and D2 exit logic inherit whatever fill/exit correctness the sidecar has). Do the 1-day read-only pattern diff now (free, freeze-compliant); schedule the 2–4 dev-day sidecar backfill after Oct 8 behind a flag. No roadmap card (Data-1, ML-2, C-200, Phase C logic itself) gets code from this repo — it contributes execution discipline underneath them. If the pattern diff finds zero gaps, verdict collapses to *skip-with-concepts* and nothing is lost.
