# ccxt/ccxt — audit (2026-09-08)

**Verdict: ✅ ADOPTABLE library — MIT, real, extremely active (pushed 2026-09-08).** Not for churning existing lanes — for two specific future gaps: multi-venue arb data (Phase C) and feature-lane price/funding feeds.

## What it is
- Unified trading API across 100+ crypto exchanges **and now prediction markets** — JS/TS/Python/C#/PHP/Go/Java/**Rust**.
- Metadata: MIT, 43.9k★ / 8.8k forks, created 2017, actively maintained (open issues 845 at 44k★ = healthy triage), monorepo multi-language.
- **Venue coverage (verified via ccxt.com, 2026): Polymarket, Kalshi, Hyperliquid, Limitless, Myriad** + full crypto roster. This is the only mainstream library that unifies the two venues this project actually trades (Polymarket + Kalshi).

## Domain relevance (the gate that killed OpenBB)
This time the gate PASSES — prediction markets are a first-class ccxt surface, not an afterthought. The ecosystem confirms the direction: pmxt ("CCXT for prediction markets") and dr-manhattan-rust (CCXT-style **Rust** API for Polymarket/Kalshi/Limitless/Opinion/Predict.fun) are both chasing the same niche.

## Fit vs roadmap
| Component | Fit | Verdict |
|---|---|---|
| Multi-venue PM quotes (Polymarket+Kalshi+Hyperliquid) via one API | Phase C arb build — cross-venue arb detection needs exactly this breadth | ✅ adopt as the Phase C data backbone (when that card fires, post-Oct-8 gate) |
| Perp funding / OHLCV / spot across crypto venues | Feature lane (macro/finance wires; crypto-perp-funding-style signals); price-derived = prior/features under the market-firewall doctrine, NOT evidence | ✅ adopt for feature feeds |
| Rust bindings | polyhydra-whale-signal sidecar is Rust — ccxt Rust or dr-manhattan-rust could serve sidecar data fetches | ⚪ concept — evaluate when the sidecar grows a new data need |
| Replacing existing Polymarket CLOB / data-api / Kalshi keyless read lanes | Bespoke, tested, doctrine-encoded (firewall, tiers, fail-loud TR-16) | ❌ do NOT churn — abstraction adds a layer, zero edge |

## Honest caveats
- Unified-API cost: ccxt's Polymarket orders abstract the EIP-712 signing; fine for new code, but it hides exactly the mechanics your sidecar currently owns and debugs. Use it for *data breadth*, not for replacing owned execution paths.
- Library weight: multi-language monorepo; pin the version; the Python/TS surface is the stable core.
- Venue-specific gaps still exist under the hood (e.g., Polymarket's event/condition model vs ccxt's market/symbol model needs mapping — verify the market-symbol layer for the arb card before committing).
- pmxt / dr-manhattan-rust are younger/smaller — not adoption candidates today; ccxt is the durable one.

## Action
- **Queue**: no work now (Kelly window open — measurement only until Oct 8).
- **Revisit triggers**: (1) Phase C arb card fires → build the multi-venue quote layer on ccxt (Python or TS) rather than bespoke per-venue fetchers; (2) a perp-funding / cross-venue feature card lands → ccxt funding+OHLCV is a half-day integration behind the research-signal webhook; (3) sidecar data-breadth need → evaluate ccxt Rust or dr-manhattan-rust (verify license + maturity first).
