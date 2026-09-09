# HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits — audit (2026-09-08)

**Verdict: ✅-adjacent as MIT *reference* for a future live-execution layer — not an adoption now.** The copy-trading core + execution engine are real; the other nine strategies are 12–70 LOC scaffolds; ingestion architecture has a modern-Polymarket mismatch.

## What it is
- MIT (clean), Rust, 3,404 LOC, created 2025-09, pushed 2026-09-07, 434★/127 forks, single-maintainer. 10 strategy modules on one shared engine (CLOB client, EIP-712 order executor, risk guard, position monitor/store, market cache, on-chain ingestion).
- **Honest parts of the README:** dry-run is the default (`enable_trading: false` / `mock_trading`), self-custody keys local, "per-venue repos hold venue metadata, not a working bot" (Kalshi/Limitless = not built), copy trading is the only production-ready strategy.
- **Soft smell:** the most recent commit *deleted the per-item status column* from all three READMEs — exactly the column that would have shown 9 of 10 strategies as scaffolds. And a "PnL Profit — live at pnlpro.fit" badge is unverifiable external marketing.

## Verified machinery
- **Execution core is genuinely real** (the useful 55% of the code): `clob.rs` (489 LOC) — "CLOB v2 client — EIP-712 order signing + L2 HMAC auth + POST /order"; `order_executor.rs` (310) — signed CTF orders, FAK/GTD, dry-run paths; `risk_guard.rs` (186) — circuit breaker + depth check; exposure caps per category/tag via `position_store`; TP/SL background monitor exits via FAK against midprice. This is the hard part of Polymarket live trading and it's implemented properly.
- **Copy-trading flow** (184 LOC, the one real strategy): configured `wallets_to_track` (no auto-discovery magic) → Polygon WS `eth_subscribe` OrderFilled logs filtered by maker → allow/block-list eligibility → strategy sizing → caps → risk → signed execution → TP/SL.
- **⚠ Ingestion architecture mismatch:** fills are sourced from **on-chain OrderFilled logs** on the CTF Exchange contracts. Modern Polymarket matching is off-chain on the CLOB — on-chain OrderFilled only sees a subset/legacy flow. Their own config carries `data_api_base` + `clob_wss_url` but the copy path doesn't use the data-api orderfilled stream. **This repo's copy signals will miss most live whale fills** — the user's sidecar (polyhydra-whale-signal, data-api orderfilled) is the correct modern source. Verify-before-trust item, not a blocker for the executor parts.
- **Strategy status reality:** whale_signal 16 LOC, cross_market_arb 14, resolution_sniper 13, market_maker 12, spread_farming/sports_execution/orderbook_imbalance similar — stubs. Only copy_trading + directional_arb (69) have bodies.

## Fit vs roadmap
| Component | Assessment | Verdict |
|---|---|---|
| Rust EIP-712 CTF order signing + L2 HMAC + FAK/GTD executor + risk guard | The future live-execution layer once C-200 proves out (production-capital unlock, precommit card). MIT reference to borrow structure from — the user's sidecar is currently signal-only (:3014). | ✅ reference (post-Kelly, when live capital gates) |
| TP/SL position monitor (midprice-poll → FAK exit) | Their paper engine has exit logic (PaperTrade closed/resolved) — compare only. | ⚪ concept |
| Copy-trading pipeline shape (tracked-wallet list → eligibility → sizing → caps) | Mirrors their approved-wallet copy flow; their wallet *selection* (polyhydra scoring, C-200) stays theirs. | ⚪ concept |
| On-chain OrderFilled ingestion | Misses off-chain CLOB fills — their data-api orderfilled sidecar is strictly better. | ❌ |
| 9 scaffold strategies (resolution_sniper, market_maker, cross_market_arb…) | Resolution-sniper (95¢→$1 hold) contradicts their own favorite-band ≈0-trades finding; cross-market arb = Phase C already designed (oracle3 matcher ahead of this). | ❌ |
| ratatui TUI / external pnlpro.fit | Local TUI duplicates their dashboard; external PnL claim unverifiable. | ❌ |

## Action
- **Do not run live; do not port strategies.** Value = the **execution-engine reference** (clob/order_executor/risk_guard ~1k LOC, MIT) for when production capital unlocks post-Kelly.
- Revisit trigger: C-200 production-proof clears the precommit gate → build live execution informed by this repo's signing/auth/risk structure (flag-revertible, dry-run-first exactly as they do).
