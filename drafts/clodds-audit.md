# CloddsBot Audit — alsk1992/CloddsBot

**Date:** 2026-09-03 · **Auditor:** Hermes · **License:** MIT ✅ (borrowable w/ attribution)

## What it is

An open-source, self-hosted, **Claude-powered personal trading terminal** ("Claude + Odds"), built for the Colosseum Agent Hackathon (Solana) in 12 days, iterated since (Jan 26 → Sep 2026). npm `clodds` v1.9.0. Chat-first: talk to it via 21 messaging platforms, an LLM agent layer decides, a TypeScript executor + Solana/EVM SDK layer acts. Coverage claims: 10 prediction-market venues, 7 futures exchanges, Solana DEXs, EVM chains, Bittensor, token launches. 578 TS files (~12 MB), plus one small Rust crate (`fast-broadcast`, UDP gossip for their infra).

**Repo health:** 866★ / 170 forks, pushed 2026-09-01, 26 open issues, active V2 branch merges. README is hype-dense: token CA in the header (pump.fun `...pump`), "10.7k clones/14d" badge, "118+ trading strategies". Actual strategy *code* = 2 modules (crypto-hft, hft-divergence), ~3,910 LOC; the "119+ skills" = 121 bundled **prompt** directories (`src/skills/bundled`). Monetization signal: token launch. Treat README claims as marketing; the codebase is genuine but shallow-wide.

## Verified machinery (read in source)

1. **`src/utils/kelly.ts` — Kelly sizer (verified line-by-line ✅)**
   - Binary: `f* = (bp − q)/b`, `b = odds − 1` (lines 131–133) — standard Kelly, correct. Full/half/quarter Kelly, `min(f,1)` cap, half-Kelly recommended default, 25% bankroll cap on recommended size.
   - **Prediction-market wrapper (correct)**: YES side `odds = 1/price`, NO side via `noPrice = 1−price`, `odds = 1/noPrice`, winProb `1−p̂` (lines 193–228). Standard binary-PM adaptation, verified.
   - Multi-outcome (generalized Kelly, one-winner payout structure): `f_i = (p_i − π_i)/(1 − π_i)`, `π_i = 1/(1+payout)` (line 263) — algebraically equivalent to Kelly with net odds `payout`, correct.
   - **Limits**: confidence scaling is a naive `×confidence` multiplier; portfolio-Kelly correlation handling is ad-hoc (avg |ρ| → shrink ≤30%, no covariance matrix); EV reporting uses `edge × stake` (line 265), not true EV — cosmetic bug, sizing unaffected.
   - **Missing (the part that matters)**: no calibration layer and no executable-quote/spread refinement — Kelly here consumes a raw `estimatedProbability` at `marketPrice` treated as midpoint. This is precisely the phantom-edge trap the Octagon audit flagged and the user's calibrated band-sizer solved. Clodds' Kelly is fine math with no epistemic hygiene.

2. **`src/feeds/polymarket/whale-tracker.ts` — Polymarket whale feed (1,001 LOC)**
   - Mechanism: CLOB `/trades?market=&limit=100&cursor=` pagination + WebSocket order flow + position polls. Filters trades by `usdValue ≥ minTradeSize` (default **$10k**), tracks positions ≥ **$50k** default. Addresses harvested from maker/taker fields; `KNOWN_WHALES` seeded from env; category keyword tagging; per-whale closed-position win-rate/PnL tracking.
   - **Feed-only** (EventEmitter). No copy *execution*. Compare: user's copybot = automated wallet-first loop (leaderboard → positions → sidecar fills). Clodds' trade-flow-first approach is a complementary lens, not a substitute.

3. **`src/opportunity/risk.ts` — multi-leg arb risk modeler (600 LOC)**
   - Partial-fill math is textbook: `P(all legs fill) = Π p_i`; per-leg partial-fill risk `p_i · Π_{j≠i} p_j` terms; slippage averaged across legs; flat platform-risk factors (Drift=30 vs 10); `minLiquidityRatio = min(liquidity/size)`. Used in `opportunity/index.ts` only — LLM-facing, likely unexercised against live markets.

4. **`src/arbitrage/index.ts` — cross-venue arb service (737 LOC)**
   - Covers Polymarket/Kalshi/Manifold/Metaculus/PredictIt/Drift/Betfair; question-similarity matching (normalized word-set Jaccard). **Imported nowhere** — no code path constructs it. Actual arb surface = LLM agent tools `find_arbitrage` / `execute_arbitrage` in `agents/index.ts` ("YES+NO sum < 1 or cross-platform discrepancy" via LLM). Un-verified, unexercised scaffold.

5. **`src/security/` shield** — pre-trade tx validator: safe-program whitelist (includes Polymarket CTF Exchange `0x4d97…045`), amount thresholds, address checker, scam DB. Solana/EVM-DEX oriented. Relevant only to a live multi-chain agent; user is paper-only with a Rust sidecar gate layer already.

6. **`src/market-index/index.ts`** — gamma/Kalshi/Manifold/Metaculus semantic market search → SQLite + local embeddings (transformers.js). Ported from "pm-indexer".

## Fit table vs roadmap

| Component | Roadmap card | Verdict | Rationale |
|---|---|---|---|
| PM Kelly wrappers, 25%-cap + half-Kelly defaults | Phase B — Kelly sizing | ⚪ concept | Math verified but superseded: user's calibrated-probability pipeline + Octagon audit already define the sizing path. Clodds is a good **test-vector reference** for sizer sanity (caps, NO-side symmetry). |
| Multi-leg fill-risk formulas (Π p_i, partial-fill terms) | Phase C — cross-venue arb | ⚪ concept | The one genuinely useful extract: textbook partial-fill risk math to fold into Phase C design notes. 1-hour skim. |
| Venue map + price normalization + similarity matching | Phase C | ⚪ concept | Confirms venue roster for cross-venue (incl. Betfair/Smarkets/AgentBets); their matching is word-Jaccard, not constraint-based. |
| Polymarket whale tracker (thresholds, per-whale win-rate) | Phase D — insider gating / copy lane | ⚪ concept | Trade-flow-first lens; $10k/$50k default thresholds + category win-rate tracking are sanity references. Architecture is behind user's wallet-first loop. |
| Arb engine (`find_arbitrage` tools, arb service) | Phase C | ❌ not portable | LLM-orchestrated, unexercised, alert-shaped. User's constraint-based Phase C design is the deeper architecture. |
| Security shield (program whitelists) | — | ❌ | DEX/Solana-oriented; user's Rust sidecar gates + paper-only stance cover this axis. |
| Kelly portfolio/correlation sizer | Phase B | ❌ | Ad-hoc correlation shrink; user's portfolio risk should come from real covariance (C-200 capital work). |
| Market semantic index | Phase Data-1 | ❌ | Solves chat-retrieval, not a data-science gap. |

**NOT portable (whole categories):** the Claude agent core, webchat, 21 channel adapters, 121 skill prompts (incl. `copy-trading`, `ai-strategy`, `edge` — all prompt-layer), Solana copytrade/swarm-copytrade (Solana wallet following ≠ PM copy), crypto whale tracker, token-launch/DCA/limit-order stacks, x402/ledger payments, Bittensor, `rust/fast-broadcast`.

## Integration proposal

**Verdict: QUEUE — concept donor only, zero code adoption.** No component beats the current pipeline for its purpose; the repo's Polymarket depth is shallower than what the user already runs (copybot sidecar + v39 Bayesian scorer + calibration band-sizer). The single actionable extract is `opportunity/risk.ts` partial-fill math → Phase C design notes. Suggested trigger: when Phase C next opens, spend ≤1 h re-reading risk.ts fill-probability sections before finalizing the leg-risk model. Effort: ~0 days now. Flag-revertible: n/a (nothing merged). Do not add as a dependency — high churn, token-hype lifecycle risk.

## Honest caveats

- **README vs reality:** "118+ trading strategies" = 121 prompt dirs + ~3.9k LOC of strategy code in 2 modules; "autonomous risk management" = LLM agent + static shield; arb claims rest on unimported code.
- **Unexercised core:** `createArbitrageService` has zero importers; risk modeler is reachable from one LLM-facing index. Verified formulas ≠ verified live behavior.
- **Hackathon genesis + token promo** (CA in README header): typical viral-monetization lifecycle; treat ongoing maintenance as uncertain despite the Sep-01 push.
- Their own `AUDIT.md` (Feb 2026) is a fix-changelog, not an independent security audit; 25 test files incl. trading-safety guards — better than most, still thin for an "autonomous trading" claim.
- No calibration, no spread-aware pricing anywhere in the deterministic core — the exact gap the user's system already closed.
