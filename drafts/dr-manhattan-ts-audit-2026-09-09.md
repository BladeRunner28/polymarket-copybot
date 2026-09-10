# Audit: gtg7784/dr-manhattan-ts (2026-09-09)

**Repo:** github.com/gtg7784/dr-manhattan-ts · npm `@alango/dr-manhattan`
**License:** MIT (LICENSE file, "Copyright (c) 2025 Taegeon Go (Alan)") → borrowable w/ attribution.
**Metadata (API):** 56★ / 8 forks / 13 open issues · TypeScript · created **2025-12-24** · main HEAD `f250ab0` **2026-05-27** · pushed_at 2026-09-07 = dependabot/renovate branch churn only (main untouched ~3.5 months). npm: 10 releases 0.1.0→**1.0.0**, last publish 2026-05-27. NOT 48h old — scout premise correction.

---

## What it is

**CCXT-style unified exchange-connectivity library** for prediction markets — a TypeScript port of guzus/dr-manhattan (Python, 199★, **NO-LICENSE**) that normalizes REST + WS read/write across 5 venues: Polymarket (REST+WS, Polygon), Limitless (REST+WS, Base), Kalshi (REST), Opinion (REST, BNB), Predict.fun (REST, BNB). Published, CI'd (lint/typecheck/vitest/build on Node 20/22), biome + renovate hygiene. It is NOT an alpha/strategy engine and does not claim to be — the README is sober (no hype numbers, no referral/affiliate/discord/telegram markers anywhere; token-less, no CA).

## Verified machinery (formulas + file paths)

The library core is honest plumbing; the "intelligence" helpers are **naive to the point of being placeholders**:

- `MarketUtils.spread` (src/types/market.ts:54–60): `|1 − (pY + pN)|` — despite the name it is the **YES+NO complement-gap / sum≠1 invariant**, not bid-ask spread. This is the *concept* behind Phase C's cross-market arb check. Verified in source.
- `OrderbookUtils` (src/types/orderbook.ts:23–88): standard mid `(bestBid+bestAsk)/2`, spread `ask−bid`, sorts bids desc / asks asc in `fromRestResponse`. Correct, boring.
- `Exchange.calculateImpliedProbability` (src/core/exchange.ts:188–190): `clamp(price,0,1)` — **identity**, not a model. `calculateExpectedValue` (:192–200): `p·1 − p ≡ 0` — zero by construction (EV of paying `price` for a coin priced `price`); circular, always ≤ 0, tested as such (tests/polymarket.mock.test.ts:205–221). `getOptimalOrderSize` (:202–205): `min(maxPos, 0.1×liquidity)` — heuristic cap, **NOT Kelly**. `findTradeableMarket` (:159–182): picks a *random* suitable market. `StrategyConfig.spreadBps` (src/core/strategy.ts:15) declared, never used.
- Examples: spread-strategy.ts = market-maker skeleton around mid w/ inventory skew (bid = mid−halfSpread−skew); spike-strategy.ts = EMA-deviation dip-buy w/ cooldown (emaAlpha = 2/(period+1)); weather-bot-strategy.ts = optional **OpenRouter LLM** market classification (default `anthropic/claude-3-haiku`). Educational demos, unvalidated.
- Gap: WS clients (src/exchanges/polymarket/polymarket-ws.ts, limitless/limitless-ws.ts 512 LOC) deliver per-update callbacks; **no L2 delta-merge/rebuild logic exists anywhere** in src (grep rebuild|delta|merge over orderbook.ts + core/websocket.ts: zero hits) — book state is snapshot-only (`fromRestResponse`), consumers must merge deltas themselves.
- Math audit result: **no Kelly, no Bayesian aggregation, no statistical/ML model, no scoring in src**. Nothing to re-derive beyond the two correct-but-trivial formulas above.

## Fit table

| Component | Verdict | Effort | Risk | Note |
|---|---|---|---|---|
| `\|1−(pY+pN)\|` complement-gap check (MarketUtils.spread) | ⚪ concept-only | ~0 (3 LOC) | LOW | Already the Phase C invariant; fold into Sep 15–30 design if the PMA tape doesn't already surface it. |
| Unified 5-venue REST/WS facade + normalized types | ⚪ concept-only | — | — | PM+Kalshi breadth **duplicates ccxt** already queued for Phase C; roadmap gate: do NOT churn bespoke CLOB / data-api / Kalshi read lanes. |
| Limitless (Base DEX) + Opinion/Predict.fun (BNB) connectors — the venues ccxt does NOT cover | ⚪ concept-only (queue) | ~½–1d read+spike | LOW | Only genuinely additive surface; maps to no approved card today. Revisit only if Phase C arb or Data-1 extends to chain venues. |
| Kalshi REST connector (kalshi.ts:340–558) | ⚪ concept-only | — | — | Duplicates existing bespoke Kalshi lane; API-normalization quirks worth a skim, nothing to copy. |
| Polymarket CLOB connector (createOrder/cancel/trades/price-history) | ⚪ concept-only | — | — | Duplicates bespoke CLOB lane; thin wrapper over `@polymarket/clob-client` anyway. |
| WS orderbook clients | ❌ not-portable as code | — | — | No delta-merge; stack already has own L2 recorder (data/l2/). |
| EV / implied-prob / order-size / find-market helpers | ❌ not-portable | — | — | Identity/zero-by-construction/heuristic; cautionary example of what NOT to ship. |
| Strategy scaffold + 3 example strategies | ❌ not-portable | — | — | Unvalidated demos; paper stack has its own v39 Bayesian engine + Kelly. |
| Repo hygiene (CI matrix, mocks, releases) | ⚪ concept-only | — | — | Signals genuine engineering intent; process norm, not code. |

## Integration proposal

**Do not add as a dependency.** If Phase C arb (design Sep 15–30, build early Oct) wants chain-venue quote breadth beyond ccxt's PM/Kalshi coverage, *read* the Limitless connector (limitless/index.ts 947 LOC + limitless-ws.ts 512 LOC) as the reference for a Base-chain L2 read lane — a paper spike, flag-revertible by construction (reference-only, no dep, no lane churn). Effort ~½–1 day, LOW risk. Nothing ships before the Kelly window closes Oct 8 regardless (precommit-mid-oct-kelly-gate); a read-only design-window spike is compatible with the freeze.

## NOT-portable list

- **All LLM/agent code** (weather-bot OpenRouter classification) — user runs DeepSeek/local; consistent with precedent.
- **Any alpha/edge claims** — none exist in source; do not let the "dr-manhattan" name or 56★ imply strategy value.
- **Strategy implementations** (spread MM, spike dip-buy) — naive, unvalidated, redundant with the v39 engine.
- **TS code → Rust sidecar** — cross-language; concepts only (types/ordering conventions are unremarkable).
- **Anything from parent guzus/dr-manhattan (Python)** — that repo is **NO-LICENSE** (all-rights-reserved); only the TS repo's MIT applies. The TS port is independently written, but API/design lineage is a caveat: MIT on the TS code, do not back-port Python files.

## Honest caveats + verdict

1. **Scout premise was wrong on freshness:** created 2025-12-24 (~8.5 mo old); 56★ is a modest organic rate, not fast-starred; last real commit + npm publish **2026-05-27** (3.5 mo idle); 2026-09-07 push = dependency bot branches. Not a 48h-old hype repo, but also not an actively maintained one.
2. Repo IS what it claims to be (CCXT-style multi-venue API) — no repo-name-vs-content mismatch, no referral farm, CI green by design. The "smart" helpers are scaffold-flavored, and the WS layer lacks managed book rebuild.
3. v1.0.0 published then silence + 13 open issues = immature maintenance posture for a live trading dependency.

**Verdict: QUEUE** (reference-only, not a dependency). No code transfers pre-Oct-8 freeze; ccxt already owns the PM/Kalshi quote-breadth slot in Phase C; dr-manhattan-ts's only unique value — Limitless/Opinion/Predict.fun read lanes — maps to no approved card. Pick it up during the Phase C design window (Sep 15–30) if Base/BNB venue breadth enters scope; effort ~½–1d spike, LOW risk, flag-revertible. Otherwise skip.
