# Audit: TopTrenDev/polymarket-kalshi-arbitrage-bot

**Date:** 2026-09-09 · **Language:** Rust (3,549 LOC, 17 source files) · **Stars/forks:** 45/11 · **Created:** 2025-12-29 · **Pushed:** 2026-06-15 · **Clone:** /tmp/audit_triage/clones/TopTrenDev_polymarket-kalshi-arbitrage-bot

## 0. License verdict (FIRST)

**NO-LICENSE.** GitHub API returns `license: null`; no LICENSE/COPYING file in the tree (verified). Per user doctrine: all-rights-reserved → **READ-ONLY concept donor, copy NOTHING**. Any component below is concept-only; all math must be reimplemented from the formulas documented here. Not a farm-pattern repo — the README is honestly WIP ("not production-ready", "educational/research", no fake backtest/PnL claims), but the code quality bar for adoption is moot anyway: nothing is copyable.

## 1. What it is

A Rust dual-strategy prediction-market bot, real engineering in the PM↔Kalshi space (directly relevant to Phase C constraint-arb):
1. **Cross-platform arb** (PM ↔ Kalshi): fuzzy-title-matches "same event" on Kalshi/Polymarket **15-minute crypto up/down markets** (`KXBTC15M` family), scans only markets resolving in **10–30 minutes** (bot.rs:48-59, main.rs:120), buys opposite sides of the pair.
2. **"Gabagool"** (PM-only): same-venue YES/NO pair completion — buy the deficit side of an existing two-sided position while *average* pair cost < $1, "locking" profit on resolution.

Detection is genuine (real identity math), but the execution/fill/fee/accounting layers have verified flaws that make the claimed locked/riskless edge phantom in practice (see §3, §6).

## 2. Verified machinery (exact formulas, file:line)

### 2a. Cross-platform pairs arb — arbitrage_detector.rs:48-87
Two mirrored decompositions of the **binary identity: exactly one of (YES, NO) pays $1**:

- Strategy 1 (buy Kalshi YES + PM NO): `cost₁ = K.yes + PM.no`; `profit₁ = 1.0 − cost₁`
- Strategy 2 (buy Kalshi NO + PM YES): `cost₂ = K.no + PM.yes`; `profit₂ = 1.0 − cost₂`
- Gate: `profit > total_fees + min_profit_threshold`, with `Fees { polymarket: 0.01, kalshi: 0.01 }` (flat, per-opportunity, default; arbitrage_detector.rs:26-33) and threshold 0.02 (main.rs:98) → **requires computed cost < 0.96**.
- `roi_percent = (profit − fees) / cost × 100`.

The identity itself is correct — this IS the right family of model for cross-venue same-payout arb. But see §3: the Kalshi leg is priced at *last*, not *ask*, fees are flat not per-contract, and no executable-quote gate exists.

### 2b. Price sourcing (the critical input) — clients.rs / polymarket_clob.rs
- **Kalshi leg: `last_price`, NOT ask.** KalshiClient::fetch_prices (clients.rs:629-685) calls `/events/{ticker}/markets` and takes `market["last_price"]/100` per outcome (subtitle "Yes"/"No"). `liquidity` = sum of market *volume* (not depth).
- **PM leg: best ask (correct).** PolymarketClient::fetch_prices → polymarket_clob::fetch_prices_for_tokens (polymarket_clob.rs:153-177): CLOB `/book` per token, `yes_ask = best_ask(yes_book)`, `no_ask = best_ask(no_book)` — comment: "yes/no store best ask — the price to buy each side on CLOB V2". Prices parsed as dollars-as-string, no /100 — correct for CLOB /book.
- **Asymmetry → phantom edge.** Real buy cost of the Kalshi leg is its *ask* ≥ last; the detector books it at last. Computed edge is overstated by up to (Kalshi ask − last) per contract, i.e. ~half the Kalshi spread or more, while the PM leg is honestly at ask. With a 60s price cache (clients.rs:75) plus 60s scan cadence, quotes can be ~2 min stale on 15m markets resolving within 30 min — a second phantom vector.
- A *separate* Kalshi quote path does the discipline right but is wired only to the monitor bin: get_market_prices / orderbook_to_best_ask (clients.rs:808-863) derives `yes_ask = (100 − best_no_bid_cents)/100`, `no_ask = (100 − best_yes_bid_cents)/100` from the orderbook — algebraically correct (and the exact concept Phase C's executable-quote rule needs). Not used by the arb loop.

### 2c. Gabagool (PM-only pair completion) — gabagool_detector.rs:26-98, gabagool_executor.rs
- Inputs: position (yes_qty, yes_cost, no_qty, no_cost), best asks. Target side = the side you hold fewer of (or the cheap side when balanced). Simulates buying **+1 share** at ask.
- `min_pairs = min(yes_qty, no_qty)`; `pair_cost_after = (new_yes_cost + new_no_cost) / new_min_pairs`; opportunity iff `pair_cost_after < 1.0`; `net_profit = 1.0 − pair_cost_after`; `roi = net_profit / pair_cost_after × 100`.
- Average-cost accounting is **arithmetically correct**: with ≥1 complete pair, the position pays min(yes,no)×$1 at resolution, so (Σcost)/pairs < 1 ⇒ locked profit (1 − avg)×pairs.
- **Executor breaks the model (verified):** main.rs:249 fires with fixed `trade_amount = 100.0`; executor buys `shares = amount / cheap_price` (gabagool_executor.rs:69) — at ask 0.45 that is **~222 shares of one side in one shot**, while the detector gated on a +1-share increment. First fire on any balanced event overshoots pair completion by ~221 shares → the excess is an **unhedged directional bet**, not locked profit. "Profit LOCKED" log lines (executor.rs:137-143, stats 166-173) only cover min(yes,no) pairs and ignore the naked excess.

### 2d. Execution / fill / settlement plumbing
- Kalshi order: `{event_ticker, side:"buy", outcome, count:(amount/price) as i64, price:(price×100) as i64}` (clients.rs:700-706); PM order: CLOB V2 limit buy `shares = amount_usd/max_price`, limit = the ask observed at scan (polymarket_clob.rs:258-309). Comment assumes immediate fill when ask ≤ max_price.
- **`cancel_order` is a no-op stub** (trade_executor.rs:204-221: logs "Cancelling…", calls nothing). **`get_order_status` hard-returns "filled"** (trade_executor.rs:223-235). The partial-fill / one-leg-fills path logs "may need to cancel PM/Kalshi trade" (trade_executor.rs:122-127) — and then cannot.
- One test in the whole repo (config.rs:84). No CI (.github absent). 1 shallow commit; no history signal.

## 3. Executable-quote & fee accounting (the discipline question)

- **Edge vs ASK, not midpoint/last:** violated on the Kalshi leg (§2b). Per-share overstatement = ask_K − last_K. On KXBTC15M with 1–3c spreads and their 4c gate (0.02 fees + 0.02 threshold), a computed 4c edge can be ≤ 0 real. This repo is a live case study for exactly the half-spread-kills-phantom-edge rule in Phase C's executable-quote discipline.
- **Fee dimensionality (verified wrong):** fees are flat $0.01 + $0.01 per *opportunity*, independent of size. Kalshi's real fee is **per-contract, proportional to expected earnings**: `0.07 × contracts × price × (1 − price)` at the top crypto tier (kalshi.com fee schedule; independent 2026 fee calculators agree). A $100 leg at 0.45 ≈ 222 contracts ⇒ Kalshi fee ≈ **0.07 × 222 × 0.45 × 0.55 ≈ $3.85** — ~200× the modeled $0.01, and the *same* order of magnitude as the whole modeled edge. Polymarket: 0 trading fee, so the PM side is fine. Net: cross-venue arb of these exact markets is likely structurally dead after real Kalshi fees — which is plausibly why the same author runs gabagool (PM-only, fee-free).
- **Fill model:** resting-limit semantics on the Kalshi leg (limit = last < ask ⇒ sits unfilled) + hard-coded "filled" status + no cancel ⇒ the bot can believe a fully-hedged arb exists while one leg never filled. Any real Phase C port must invert all three (post-only executable quotes, status polling, fill-contingent leg logic).

## 4. Fit table vs Phase C gaps

| Component | Verdict | Rationale / transfer |
|---|---|---|
| Pairs-arb identity decomposition (cost = Σ opposite-side quotes; profit = 1 − cost; gate; ROI) — arbitrage_detector.rs:48-87 | ⚪ **concept-only** | Correct model family for Phase C cross-venue same-payout arb. Reimplement in ~20 lines against executable quotes both sides; nothing copyable (NO-LICENSE). Math is elementary; the value is the discipline, which Xman's executable-quote rule already mandates. |
| 10–30 min-to-resolution window filter (bot.rs:48-59) on 15m crypto pairs | ⚪ **concept-only** | Real domain narrowing: near-resolution pairs converge; windowing is a sensible Phase C universe filter. One-line concept, re-derivable. |
| Gabagool avg-cost pair completion (`(Σcost)/min(qty) < 1 ⇒ locked`) | ⚪ **concept-only** | Sound accounting kernel for single-venue basket/pair completion — but ONLY with exact share sizing (buy deficit to equality), which their executor fails to do. Worth a concept note for Phase C family; reimplement with precise sizing + shadow-journal validation. |
| Kalshi ask-from-opposite-bid derivation `ask_yes = 1 − bid_no` (clients.rs:808-824) | ⚪ **concept-only** | Trivial identity, already implied by Xman quote discipline. Confirms author knew the right quote math — and didn't use it in the arb loop. |
| PM best-ask sourcing + CLOB /book parse (polymarket_clob.rs:153-177) | ❌ **not-portable** | Duplicates Xman's existing PM quote feed; CLOB V2 SDK plumbing is Rust-specific. |
| Cross-venue event matching (jaro-winkler + keyword/date/category/number weights 0.40/0.25/0.15/0.10/0.10, event_matcher.rs:151-211) | ❌ **not-portable** | Heuristic title matching with **no resolution-rule equivalence check** — the classic false-pair risk (two markets with same wording, different rules). Phase C matcher (oracle3/coinjure, ADOPTed) is strictly better; this is a cautionary contrast, not a donor. |
| Trade/fill/cancel/status layer (trade_executor.rs) | ❌ **not-portable** | Stubs + wrong fee/fill model; adopt as an **anti-pattern checklist** only. |
| Position tracker & settlement P&L (position_tracker.rs, settlement_checker.rs) | ❌ **not-portable** | Booking bugs: cross-venue legs store `cost = notional × price` while `amount` field holds shares (trade_executor.rs:83-97) ⇒ settled P&L = payout(shares) − notional×price, wrong by factor ~price; conventions inconsistent with gabagool executor's (cost = notional). Do NOT use as shadow-journal reference. |
| 15m-slot monitor logger + monitor bin (monitor_logger.rs, bin/monitor.rs) | ❌ **not-portable** | Thin logging scaffolding; Xman has the shadow journal. Bonus finding: get_market_prices tries `as_f64()` on `yes_ask` *before* the cents `/100` path (clients.rs:833-840) — as_f64 succeeds on integer-cent responses and treats them as dollars ⇒ latent 100× unit risk in the monitor quote path (internal unit inconsistency vs orderbook_to_best_ask and fetch_prices, both cents-based). |
| Kalshi RSA-PSS REST client, Polygon/on-chain helpers, config/env plumbing | ❌ **not-portable** | Stack-specific; Kalshi order payload shape (`event_ticker`+`outcome` vs documented per-market `ticker` orders) never validated end-to-end — README disclaims production readiness; treat payload as unverified. |

## 5. Integration proposal (if Phase C later wants this family)

- **Effort:** ~0.5–1 day total, reimplementation-only, since every transfer is elementary math plus a quote-source swap. No Rust, no external deps.
- **Risk:** low (concept-only), but flag-revertible by construction: Phase C already ships the matcher and executable-quote edge engine; a pairs-arb detector is a pure addition emitting shadow-journal signals — ship behind the same journal/flag path, no live orders pre-Oct-8 (Kelly measurement freeze: recommendations only).
- **Suggested shape (if ever prioritized):** detector = `1 − ask_pm − ask_k − fee_k(contracts, price) > 0` with both legs at executable asks, per-contract Kalshi fee model `0.07·c·p·(1−p)`-shaped, size = min(ask depth, deficit-to-equality), fill-contingent leg release, and the gabagool kernel sized exactly (buy deficit side only, never overshoot). Every one of those clauses is an inversion of a bug found here.
- **Net recommendation for now: queue — take the two concept notes (§4 rows 1–3) and the anti-pattern list; do not schedule any build.** Nothing here outranks the adopted oracle3/coinjure kickoff, and the cross-venue edge as *they* compute it is dead on arrival after real Kalshi fees — the transferable insight is mostly "what not to do", which the Phase C executable-quote spec already encodes.

## 6. Honest caveats

- No live-API verification was possible: Kalshi order-payload correctness, PM CLOB V2 auth flow, and real fill behavior are **unverified** (repo has no integration tests; single unit test; no CI).
- "Gabagool" is misnamed as hedged arb in practice: with $100 fixed-size orders vs 1-share detector increments, realized fills carry a large naked directional excess (§2c). Its *detector* accounting is right; its *executor* economics are not — likely why it never claims live results.
- The Kalshi `as_f64` cents/dollars branch (§4) is flagged as latent-risk, not asserted as a live bug — actual Kalshi response shape was not observed.
- No backtest, no paper-trade log, no PnL anywhere in the repo — claims are "strategy implemented," not "strategy profitable." Consistent with the honest-WIP README.

## 7. Verdict

**QUEUE — concept-only donor (NO-LICENSE), no code adoptable, no unique verified math worth porting.** Direct relevance to Phase C's space, but: (1) the cross-venue arb as implemented is phantom-edge by construction (Kalshi leg at last-price, flat-vs-per-contract fees ~200× understated, no cancel/fill truth), (2) the one sound kernel (gabagool pair-cost accounting) is betrayed by its own $100 overshoot executor, and (3) event matching is inferior to the already-ADOPTed oracle3/coinjure matcher. Harvest = two concept notes + an anti-pattern checklist for Phase C's executable-quote requirement; effort ~0; no build scheduled pre-Oct-8.
