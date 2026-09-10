# PolyWorld Audit — adoption fit (AmazingAng/PolyWorld)

**Date:** 2026-09-09 · **Auditor:** subagent (github-repo-audit workflow) · **Stack context:** TS dashboard + Rust CLOB sidecar, paper-only, v39 Bayesian evidence engine, Kelly SHIPPED Phase B (measurement window Sep 8–Oct 8: nothing ships, recommendations only, flag-revertible)

---

## License verdict (checked FIRST)

**MIT** — GitHub API `license.spdx_id = MIT`; LICENSE file present in clone, `MIT License / Copyright (c) 2025 0xAA`. package.json also `"license": "MIT"`. → **Borrowable with attribution** (keep copyright notice in any ported file header + credit line).

## What it is

A **Next.js 16 / React 19 / TypeScript dashboard** (not an agent framework — zero `agent`/`tool` references in `src/`) by 0xAA (AmazingAng, well-known CN web3 educator): real-time Polymarket markets plotted on a MapLibre world map, 19 draggable panels, SQLite local cache (better-sqlite3), 5 background sync loops, browser-wallet **live trading** via Polymarket CLOB (proxy-wallet + builder-signing-sdk), and Claude-API "AI insights." 182 stars, 36 forks, created 2026-03-04, **last push 2026-03-27 (~5.5 months stale)**, single-author, no releases, education-grade. Inspired by WorldMonitor.

**Architecture:** `Gamma API → fetchEventsFromAPI → processEvents → SQLite → /api/markets → UI polls`. Sync loops (src/instrumentation.ts): markets 30s, smart money 30s, news 5min, tweets 3min, resolutions 2min. LLM glue is confined to news/sentiment/geo/summary (CLAUDE.md self-reports ~$5/hr AI cost with batching + `ai_match_done` dedupe flags).

## Verified machinery (deterministic core, file paths)

Repo: `/tmp/audit_triage/clones/AmazingAng_PolyWorld` (scratch clone; source of truth is the audit notes below).

1. **Arbitrage detector — `src/lib/arbitrage.ts` (153 lines)** — the standout. `detectArbitrage(markets, feeRate=0.02)`:
   - Multi-outcome branch **gated on `negRisk` only** (mutually exclusive outcomes), skips events with inactive placeholder slots, ≤10 outcomes, avg outcome price ≥ 0.08, `sumProb ≥ 0.70` coverage guard.
   - Genuinely careful false-positive filters: threshold-style outcome names (`above|below|over|under|…` + `< > ≤ ≥` digit) and numeric-range brackets (`X%–Y%`) excluded — these don't sum-to-1.
   - `impliedEdge = |sumProb − 1.0| − feeRate × N_outcomes` (per-leg fee scaling), direction over/under, liquidity floor $1,000, top-20 sorted by implied edge.
   - Binary branch: YES+NO sum ≠ 1.0 → `deviation − feeRate`, same liquidity floor.
2. **Smart-money rule signals — `src/lib/smartSignals.ts` (238) + `src/lib/signalEngine.ts` (412)** — fully deterministic, zero LLM:
   - `whale_accumulation` (≥3 buys / ≥$5k same wallet, 6h), `smart_divergence` (price Δ>2% opposite net smart flow), `cluster_activity` (≥2 wallets same side, 2h), `momentum_shift` (3h net-flow flip vs prior 3h).
   - Engine adds `top_wallet_entry` (top-50-PnL wallet buy <1h; strong ≥$20k / moderate ≥$5k), `top_cluster` (≥3 distinct top-50 wallets <1h, hardcoded "strong"), `news_catalyst` (≥2 keyword overlap news↔smart-flow, 2h, net direction). Dedupe per (type, slug) keep-strongest; sort strength→recency.
3. **Gamma ingestion + taxonomy — `src/lib/polymarket.ts` (231) + `src/lib/categories.ts` (248)** — paginated `order=volume24hr` fetch (batch 100, concurrency 5), `processEvents` → mapped/unmapped split, negRisk persisted; `detectCategory` = tag regex rules (TAG_RULES) + keyword fallback; sub-emoji detection.
4. **Data API client — `src/lib/smartMoney.ts` (444)** — `https://data-api.polymarket.com` (leaderboard / whale trades / wallet data; 30s sync loop in `smartMoneySync.ts`). Unofficial-endpoint semantics — verify upstream before reuse.
5. **Scoring math — `src/lib/impact.ts` (95)** — `computeImpactScores`: log1p(volume/liquidity/|change|/comments) → percentile ranks → weighted composite + age decay, clamped 0–100. `src/lib/anomaly.ts` (96): z-score > 2 on snapshot price-change distribution + volume spike. `src/lib/indicators.ts` (128): snapshot mean/variance, 6h smart-flow ratio, 5-min cache. `src/lib/flowAnalysis.ts` (93): per-category net flow + hourly trend from SQLite.
6. **Price-underlier parsing — `src/lib/priceMonitor.ts` (287)** — `parseThresholdFromTitle` regexes ("above/below/under $X", threshold-outcome labels), Binance/Yahoo price fetch w/ 30s cache, candle direction vs daily open. Deterministic crypto-underlier monitor for threshold markets.
7. **Event-structure parsing — `src/lib/marketLabels.ts` (94)** — `extractLabels`: common prefix/suffix diffing + entity regex over negRisk question lists → per-outcome candidate labels. Deterministic.
8. **CLOB trading layer — `src/lib/polymarketCLOB.ts` (184), `tradeAuth.ts` (135), `tradeSession.ts` (87), `marketOrder.ts`, `tradeAmounts.ts`, `openOrders.ts`** — derived-L2 API-key flow (`/auth/api-key`, `/auth/derive-api-key` w/ stub signer + L1 headers), proxy-address authenticated client, order routes w/ 15s timeout + 4s settle poll @ 500ms, book-walk execution price + `tick×5`/1% buffer, precision-safe raw-amount math, EIP-712 trade sessions (30min idle / 8h abs TTL).
9. **Resolution monitor — `src/lib/resolutionSync.ts` (460) + `resolutionSources.ts` (167)** — typed targets (`known_feed` / `price_feed` binance|yahoo|cme / `sports_feed` / `unmonitorable`), URL→symbol parsers (Binance `BTC_USDT`, Chainlink streams, Yahoo quotes, CME map), org-name text matching → early-resolution inference for closing out pre-resolution.
10. **Infra — `db.ts` (idempotent ALTER-migrate), `retry.ts`, `circuitBreaker.ts`, `apiCache.ts`** — standard patterns.

Tests exist for categories/keywords/marketOrder/retry/smartMoney/tradeAmounts (`src/__tests__/*.test.ts`, vitest) — **no arbitrage or signal-engine test** (untested-in-repo caveat).

## Fit table

| Component | Verdict | Rationale / roadmap mapping |
|---|---|---|
| `arbitrage.ts` detector (negRisk multi-outcome + binary YES+NO sum≠1) | ✅ **ADOPT** (queue → Phase C) | Deterministic, MIT, read-only. Overlaps Phase C invariant family ("YES+NO sum ≠ 1 → trade the violation") — supplies the Polymarket-internal screen + battle-tested false-positive filters for the Phase C cross-venue detector. Map: `phase-c` backlog card (design Sep 15–30, build early Oct). |
| Smart-money rule signals (smartSignals + signalEngine thresholds) | ⚪ concept-only | Deterministic but Data-API-coupled and demo-tuned (no backtest in repo). Thresholds (top-50 cluster, ≥3 buys/$5k accumulation, 2% divergence) are cheap, portable ideas for a smart-flow context lane — research bot's lane, post-window. Not code to lift. |
| Gamma ingestion pattern (`polymarket.ts`) | ⚪ concept-only | PMA tape already covers Gamma. `mapped/unmapped` + negRisk persistence is a decent schema idea only. |
| Category taxonomy + marketLabels + threshold parsers | ⚪ concept-only | `detectCategory`/`extractLabels` regex machinery is deterministic and could sharpen market-taxonomy/slug work; `parseThresholdFromTitle` useful for crypto-underlier threshold markets. No card today. |
| impact/anomaly/indicators/flowAnalysis scoring math | ⚪ concept-only | Percentile-rank composite, z>2 anomaly, flow ratios are textbook; DB/dashboard-coupled; v39 engine owns the stack's math. |
| CLOB layer (polymarketCLOB, tradeAuth, marketOrder, tradeAmounts) | ❌ not-portable (reference only) | Rust sidecar owns CLOB execution; browser proxy-wallet EIP-712 model ≠ sidecar key model. Worth reading for API-key-derivation + settle-poll timeouts only. |
| Resolution monitor (resolutionSync/resolutionSources) | ⚪ concept-only | Exit-timing idea (close pre-resolution on org/price feeds); Kalshi-reprice context exists; no card. |
| News/Tweets/AI: `ai.ts`, `aiGeo.ts`, sentiment/summarize/news/tweets routes, newsSync/tweetsSync AI matching | ❌ not-portable | Claude-API LLM glue, ~$5/hr, duplicates research bot + local-LLM sentiment lane (doctrine: LLM layers not portable). |
| World map, 19 panels, dnd layout, all `components/`, `hooks/`, `stores/`, `i18n/`, geo/topojson, HLS streams | ❌ not-portable | Dashboard UI; stack's TS dashboard exists; bespoke panel system not worth porting. |

## Integration proposal (the one adoption candidate)

**Port `detectArbitrage` semantics as a read-only Polymarket arb/YES+NO-invariant screen feeding Phase C.**

- **What:** New detector (TS in dashboard or Rust sidecar) scanning the PMA tape for (a) negRisk events with all-active multi-outcome `sumProb ≠ 1` and (b) binary YES+NO sum ≠ 1, applying PolyWorld's exclusions verbatim: negRisk-gate, inactive-slot skip, ≤10 outcomes, avg price ≥ 0.08, sumProb ≥ 0.70, threshold/range-name regex filters, per-leg fee scaling, liquidity floor.
- **Effort:** ~0.5 day incl. unit tests (logic is self-contained, 150 lines, no DB/UI deps — the one cleanly liftable module).
- **Risk:** LOW — pure read-only detection, no execution path, no sizing, no order code. Fits paper-only doctrine.
- **Flag-revertible:** YES — an on/off env flag on a detector that only emits recommendations; zero interaction with Kelly window lanes.
- **Timing:** **Do NOT ship before Oct 8** (Kelly measurement window freeze). Design notes now; code lands with Phase C (roadmap: build early Oct). The existing `phase-c` card already names this invariant family.
- **Attribution:** MIT requires preserving the copyright notice — header comment + credit in the ported module; note in `data/github-scout-latest.md`-style provenance if the stack tracks donors.

## NOT-portable list (explicit)

1. **All Claude/LLM glue** — `src/lib/ai.ts`, `aiGeo.ts`, `src/app/api/sentiment|summarize|news|tweets|overlay` routes, AI matching inside `newsSync.ts`/`tweetsSync.ts` (Claude API, $5/hr; duplicates local-LLM research lane).
2. **Entire UI layer** — `src/components/*` (60+ files), `src/hooks/*`, `src/stores/*`, `src/i18n/*`, world map + geo plumbing (`geo.ts`, `topojson.ts`, `geo-backfill.ts`, `countries.ts`), HLS/`youtube-live`.
3. **Browser-wallet trading execution model** — proxy-wallet approvals, `@polymarket/builder-signing-sdk`/builder-relayer signing, EIP-712 session store in localStorage — wrong execution model vs Rust sidecar keys.
4. **Sports/tweet/news content pipelines** — licensing + scope mismatch (GDELT + research bot already cover news).
5. **Data-API-dependent smart-wallet classification** — `isSmartWallet` semantics are upstream-heuristic, unverifiable from repo; don't inherit blind.

## Honest caveats

- **Arb math uses mid prices, not executable quotes.** `outcomePrices` deviation includes per-leg spread cost; PolyWorld's `impliedEdge` subtracts fees only. Per the Octagon lesson, a real arb must clear the **ask side** of each leg — treat PolyWorld output as *screening*, re-verify against order book before any (paper) execution. Port must add an executable-quote refinement, not copy the fee-only edge.
- **No arbitrage/signal unit tests in repo** (tests cover categories/keywords/marketOrder/retry/smartMoney/tradeAmounts only); single author, no releases, last push Mar 2026 — treat all thresholds as unvalidated demos, re-derive before trusting.
- **Data API endpoints are unofficial** — schema drift risk; validate against live responses during Phase C build.
- Repo is dashboard-shaped: the one clean lift is `arbitrage.ts`; everything else is idea-fodder, not code.

## Verdict

**QUEUE → adopt at Phase C (post-Oct-8).** MIT/borrowable verified. One genuinely transferable deterministic module (`arbitrage.ts` — negRisk sum≠1 + YES+NO invariant detection with unusually careful false-positive filtering) maps directly onto the Phase C arb card; ~0.5 day, LOW risk, flag-revertible, recommendation-only. Smart-money rule thresholds are concept-value for a post-window smart-flow lane. Everything LLM/UI/browser-wallet is not-portable per doctrine. Pre-Oct-8 Kelly freeze respected: nothing ships, design notes only. Not a skip — the arb module is the cleanest Polymarket-internal detector found so far and de-risks Phase C's Polymarket leg.
