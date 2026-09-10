# Audit: valory-xyz/trader — adoption fit into Xman's Polymarket/Kalshi stack

**Date:** 2026-09-09 · **Auditor:** repo-scout subagent · **Source:** GitHub API + shallow clone `/tmp/audit_triage/clones/valory-xyz_trader` (HEAD `d632189`, 2026-09-08)

## License verdict (FIRST)

**Apache-2.0** (GitHub API `spdx_id=Apache-2.0`, LICENSE present, per-file Apache headers).
→ Borrowable with attribution. No AGPL/no-license complications. 77 stars, active (last push 2026-09-08, ~1037 merged PRs), Python, not archived. This is Valory AG's flagship production prediction-market agent (their "Polystrat" Polymarket service + "Omenstrat" Omen service).

## What it is

Olas/Open-Autonomy agent (open-aea ABCI framework, Tendermint FSM consensus, Safe multisig settlement) running a single loop: **discover markets → sample → ask an external "AI Mech" (paid on-chain third-party LLM prediction agents) for p_yes/p_no/confidence/info_utility → size the bet via a downloaded IPFS "strategy" script → gate → execute FOK on Polymarket CLOB v2 / FPMM on Omen → redeem at resolution.** Heavyweight orchestration layer dominates the repo; the trading mechanics are a few small pure files.

## Verified machinery (formulas, file paths)

### 1. Execution-aware grid-Kelly sizer — THE core asset
`packages/valory/customs/kelly_criterion/kelly_criterion.py` (~505 lines, pure function `run(**kwargs) -> dict`, 60 tests in `test_kelly_criterion.py`). No framework imports; a standalone module. Fixed-size sibling: `packages/valory/customs/fixed_bet/fixed_bet.py`.

- **CLOB execution model** (`walk_book`): simulate taker market buy by walking ask levels sorted by price; `cost = Σ p·s` up to spend, `shares` accumulate, partial fill at `remaining/price`. VWAP = cost/shares.
- **Objective** (grid over spend b, default 500 points between min_bet and max_bet):
  `w_win = w_bet − cost + shares − fee`, `w_lose = w_bet − cost − fee`, maximize `G(b) = p·ln(w_win) + (1−p)·ln(w_lose)`; bet only if `G(b) > ln(w_bet)` (log-growth improvement > 0). Both YES/NO sides evaluated independently; argmax over g_improvement decides side.
- **Verified:** this is textbook expected-log-utility maximization for a binary wager paying 1:1 at resolution, with execution cost from real book depth and per-trade fee. With a flat book at price π and no fee it reduces to fractional Kelly `f* = (p−π)/(1−π)`, capped by max_bet — consistent with standard reference. Sanity: fee subtracted on both win and lose branches; floor balance removed from effective wealth first.
- **Gates baked in:** pre-filter `min_edge ≤ p − best_ask ≤ max_edge` (defaults 0.03 / 1.0); min_oracle_prob 0.5; empty/thin-book rejection; sub-floor fill-cost rejection; inverted-band rejection. Post-hoc edge recomputed vs **VWAP, not midpoint** (the executable-quote refinement this stack already treats as correct).
- **Caps/defaults:** max_bet 5 USDC (6-dp Polymarket) / 0.8 xDAI (18-dp Omen); n_bets=1; w_bet = min(n_bets·max_bet, bankroll − floor); fee_per_trade 0.01; bankroll floor. `expected_profit = p·shares − spend − fee` (linear EV reported alongside log objective).
- **FPMM branch** (Omen-only): `shares(b) = αb + x − xy/(y + αb)`, `α = 1 − fee` — **not validated against live Omen contract math; irrelevant (Omen not in stack). Do not copy this branch.**

### 2. Prediction-source accuracy ε-greedy loop (model/source selection)
`packages/valory/skills/decision_maker_abci/policy.py` — `EGreedyPolicy`:
- Per-source ledger `{requests, pending, accuracy}`; on **market resolution** (`polymarket_reedem.py:96`, `reedem.py:125`) the tool's pick is scored winning/losing and accuracy updated (correct/resolved).
- `weighted_accuracy = minmax01( accuracy + ((requests − pending)/n_requests)·0.1 )` — volume-regularized, small-sample-safe.
- Selection: ε-greedy over weighted accuracy; **quarantine** tool after `consecutive_failures_threshold` failures for `quarantine_duration`; policy serialized and persisted across runs. Verified against standard ε-greedy/UCB-ish bandit practice; scaling helper (`utils/scaling.py`) is a plain min-max linear scaler.

### 3. Rebet / position-management guard
`packages/valory/skills/market_manager_abci/bets.py:417-452` (`rebet_allowed`):
- Same-side add only if model win-prob (`max(p_yes, p_no)`) is **non-decreasing** AND position liquidity non-decreasing.
- Side-flip only if more confident AND new side's potential net profit ≥ previous.
→ Anti-chasing / anti-avalanche / anti-flip-flop guard on a live position.

### 4. LLM request-context envelope (Polymarket data handling for a predictor)
`bets.py:462-508` `to_request_context`: `{market_id, type, market_prob (=current YES price), market_liquidity_usd, market_close_at, amm_fee, market_spread, description (resolution rules, capped 5000 chars), neg_risk, poly_tags}` — the exact context envelope a research LLM needs to produce p_yes. Note their design: **price is fed INTO the LLM prompt and the bet is LLM-p vs market-price edge** — opposite of this stack's v39 doctrine (price-derived = prior, not evidence).

### 5. Execution gates + market-ingestion filters
- Spread gate (`decision_maker_abci/behaviours/decision_receive.py:534-566`): skip if `best_ask − best_bid ∉ [polymarket_spread_min, polymarket_spread_max]`; **crossed book (spread < 0) always rejected**; missing book bypasses gate (logged when band non-default). Default band [0,1] = pass-through.
- Ingestion filter chain (`market_manager_abci/behaviours/polymarket_fetch_market.py`, 1k+ lines): closed_flag, zero_liquidity, parse_error, null_or_mismatch, past_opening_margin, extreme_outcome_price, cross_category_dedup, keyword_category (currently disabled — logs only). Category-bucketed fetch with per-reason drop counts.
- Sampling/priority (`decision_maker_abci/behaviours/sampling.py`): deterministic sort — highest liquidity first, then earliest closing time; processable-bet classification over queue status; no stochastic selection.
- Sell path (`decision_receive.py:626`): exit if model flips side or confidence < `min_confidence_for_selling` (=0.5, hardcoded models.py:565) — **code comment: "Selling flow is currently not supported in production"** → their PnL model is hold-to-resolution/redeem, no live exit machinery.

## Fit table vs roadmap gaps

| # | Component | Verdict | Roadmap fit | Notes |
|---|---|---|---|---|
| 1 | Execution-aware grid-Kelly sizer (`kelly_criterion.py`, pure fn + 60 tests) | ✅ **adopt** (port to TS) | **Post-Oct-8** sizing-v2 candidate (Phase B successor; v40/Homerun risk-gate family) | Edge vs asks/VWAP, fees, floor, caps, min/max-edge band. Grid-Kelly is agnostic to the p source — feed the **v39 calibrated posterior**, never raw LLM p_yes |
| 2 | Source-accuracy ε-greedy + quarantine (`policy.py`) | ✅ **adopt as concept** (reimplement in TS) | **ML-2** dual-track lane selection; C-200 trader-quality scoring | Resolution-scored, volume-regularized, failure-quarantined source selection; the empirical half of "which lane to trust" |
| 3 | Rebet/position guard (`bets.py rebet_allowed`) | ✅ **adopt as concept** | Sizing-service risk guard, post-freeze | Confidence-monotonic adds; flips demand better EV |
| 4 | LLM request-context envelope schema (`to_request_context`) | ✅ **adopt (schema)** | DeepSeek research-bot prompt contract — immediate, no-ship | Right field shape; do NOT copy their "price inside prompt" stance (v39: price-derived = prior) |
| 5 | Spread gate + crossed-book rejection | ⚪ concept-only | Phase C arb / Kalshi adapter order gates | Logic trivial; band defaults = pass-through |
| 6 | Ingestion filter taxonomy (closed/zero-liq/extreme-price/dedup/… ) | ⚪ concept-only | Data-1 sports-lane ingestion hygiene | Polymarket-API-specific code; taxonomy of failure modes is the value |
| 7 | Fixed-bet strategy (`fixed_bet.py`) | ⚪ concept-only | — | Superseded by shipped Kelly (Phase B) |
| 8 | ABCI FSMs, Tendermint consensus, Safe settlement, staking_abci, chatui_abci, Omen graph tooling, polymarket_client connection, withdraw/sweep/top-up chains | ❌ not-portable | — | Framework boilerplate / chain ops / venue code |

## Integration proposal (effort / risk / flag-revertible)

1. **T1 — DeepSeek prompt-contract schema (immediate, ships nothing):** adopt the envelope fields (market_prob, liquidity_usd, close_at, spread, description≤5k) as the research-bot context contract, with price tagged prior-per-doctrine. Effort: trivial (schema doc). Risk: none. Not a ship — freeze-compliant.
2. **T2 — Exec-aware grid-Kelly port (post-Oct-8, paper):** TS port of `walk_book` + log-growth grid + edge band as sizing-v2, shadow-compared against shipped Phase-B Kelly on the same paper feed (Kelly measurement window runs to Oct 8 — **nothing ships; recommendation only**). Effort: ~0.5–1 day incl. porting semantics of their 60-test suite. Risk: low (sizing-only, no order path). Flag: `kelly_exec_aware_v2`, revertible.
3. **T3 — Source-accuracy ledger spec (ML-2 prep, post-freeze):** design doc for resolution-scored, volume-regularized ε-greedy selection with quarantine across DeepSeek / local-LLM / feature lanes. Effort: 1–2 days design. Risk: low.

**Overall verdict: queue — targeted concept harvest, timed after the Oct-8 Kelly gate** (feeds the pre-commit "concept menu" per `precommit-mid-oct-kelly-gate`). Not an audit-now build; not a skip.

## NOT-portable list

- **Entire open-aea / Open Autonomy layer** — ABCI skill FSMs, round/payload/state machinery, Tendermint block sync, IPFS content-addressed packages, Docker deployment, custom protocols (srr, mech). Duplicates this stack's research-bot orchestration; Python-framework-bound; by doctrine (LLM/agent-framework layers are not-portable; user builds deterministic cores).
- **Mech marketplace integration** — on-chain paid requests to third-party LLM prediction agents (agent-marketplace economics, not trading). Replaced by DeepSeek/local lanes. (Its accuracy-ledger *concept* transfers; its plumbing doesn't.)
- **Omen/Gnosis stack** — FPMM execution branch (math unverified, venue absent), realitio/conditional-tokens/omen subgraph queries, xDAI chain ops.
- **Olas staking/KPI machinery** (`staking_abci`, `check_stop_trading_abci`, `agent_performance_summary_abci`) — staking-rewards automation for the Olas protocol; not trading.
- **Polymarket Python CLOB connection** (orderbook/FOK/funding/deposit/withdraw/sweep chain) — execution already owned by the copybot stack + rust sidecar; Python not portable.
- **chatui_abci** — chat-driven strategy/config control; replaces this stack's config system without adding edge.

## Honest caveats + verdict

- **No published track record.** Repo is Valory's commercial flagship and highly active, but there are no verified PnL/ROI figures in-repo; their "benchmarking" is dataset-mocked, and agent performance summaries are internal. Do not credit them edge; the value is mechanism, not results.
- **Kelly composition differs.** They feed raw third-party-LLM p_yes straight into the sizer and bet on LLM-vs-price edge. Here the v39 posterior (calibrated, price-derived prior separate) must be the `p` input — grid-Kelly itself is agnostic and correct either way.
- **No live exit machinery** (sell flow disabled in production per their own comment; hold-to-resolution/redeem model) — nothing to borrow for active exits.
- **Single-venue:** Polymarket CLOB only (plus Omen FPMM); zero cross-venue arb machinery for Phase C. The spread/crossed-book gate concept is the only Phase-C-adjacent piece.
- **Signal-to-noise:** repo is enormous (whole Olas stack, 1037+ merged PRs); the entire transferable value sits in ~3 small pure files (kelly_criterion.py, policy.py, bets.py rebet_allowed) — do not let the framework's sophistication inflate the score.

**Verdict: queue** — license Apache-2.0 (borrowable); adopt #1 (exec-aware grid Kelly → TS port, post-Oct-8 sizing-v2 shadow) and #2 (accuracy ε-greedy → ML-2 concept) plus #4 (prompt envelope schema, immediate no-ship); everything else concept-only or not-portable. Recommendation-only until the Oct-8 Kelly gate; all integrations flag-revertible.
