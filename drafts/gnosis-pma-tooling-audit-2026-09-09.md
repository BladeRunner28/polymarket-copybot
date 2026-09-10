# Audit: gnosis/prediction-market-agent-tooling — adoption fit for Xman PM/Kalshi stack

**Date:** 2026-09-09 · **Auditor:** Hermes subagent (adoption-fit audit) · **Clone:** /tmp/audit_triage/clones/gnosis_prediction-market-agent-tooling @ 817117d9 (2026-04-22, v0.69.40, 118 .py files) · **Status:** recommendation only — no shipping before Oct 8 (Kelly measurement window open).

---

## 0. License verdict (FIRST)

**LGPL-3.0** — verified by reading the actual `LICENSE` file (full LGPLv3 text, no exceptions/dual-license header).

Per doctrine: **READ-ONLY concept donor**. Anything here is concept material only:
- NO wholesale copying of any file, function, or structure — LGPL-3.0 copyleft applies to derivative works even when dynamically linked; the Python-module boundary does not grant the MIT-style "small excerpt" latitude.
- Concepts, formulas (math is not copyrightable expression per se, and most derivations are standard/public), design patterns, and API-endpoint knowledge MAY be reimplemented from scratch with attribution in comments.
- Precedent: homerun AGPL audit → same posture.
- One nuance: `kelly_criterion.py`'s "full" variant is itself ported from **valory-xyz/trader (Apache-2.0)** with an Apache header retained at kelly_criterion.py L96–112 — but the gnosis file as a whole is LGPL-3.0, so treat the file, not the derivation, as the license boundary.

---

## 1. What it is

Gnosis' Python toolkit ("Tools to benchmark, deploy and monitor prediction market agents"). It is **agent ops tooling, not a trading/strategy product**: it wraps LLM-forecast agents (langchain/openai/pydantic-ai/langfuse, LLM "is this question predictable/invalid" filters, Perplexity + Tavily research wrappers, logprobs parsing) around market adapters for **Omen (primary), Polymarket, Manifold, Metaculus (API key), Seer**, plus a benchmark harness (agent p_yes vs market price), bet-sizing (Kelly family), execution (CoW AMM swaps on Omen; py-clob-client on Polymarket CLOB), **a Polymarket whale copy-trader**, Omen Reality-oracle accuracy checks, and GCP deployment/monitoring. Last commit Apr 2026; actively maintained by a real org (gnosis) as infrastructure for their own prediction agents.

Deterministic value for us is concentrated in a thin slice: Kelly/betting-strategy math, Polymarket tape/trader analytics + copy-loop state machine, fee modeling, and CLOB execution gotchas. Everything else is Omen-specific or LLM-layer (not-portable per doctrine).

**Reality check vs Xman's stack:** the v39 Bayesian log-odds evidence engine, Kelly sizing (Phase B, calibrated-input discipline), CLOB Rust sidecar, Kalshi adapter, and 692M-trade tape DB already cover the hard parts. This repo has **no evidence-aggregation math, no calibration machinery (Brier/CI), no arbitrage detection, no Kalshi, no sports data, no signal/feature engineering** — grep-verified across the package.

---

## 2. Verified machinery (from source, with file paths)

All paths relative to `prediction_market_agent_tooling/`. Math verified line-by-line against standard references; divergences flagged.

### 2.1 Kelly — simplified binary (`tools/betting_strategies/kelly_criterion.py` L32–80)
```
edge  = |p̂ − m| · c          # c = agent "confidence" in [0,1]
odds  = (1/m) − 1            # m = market prob of bet direction
f*    = edge / odds
bet   = min(f* · max_bet, max_bet)
```
- **NOT textbook Kelly.** Docstring cites Wikipedia's f* = p − q/b, but the code does not implement it: it implements a *confidence-scaled-edge × implied-odds* heuristic. Textbook Kelly here would be f* = p − (1−p)·m/(1−m). The coded form shrinks edge linearly with confidence and divides by decimal odds — different sensitivity, and it ignores that the bet moves the price (docstring admits this, cites PR #330 discussion).
- Confidence multiplies **edge**, not the probability estimate (in the categorical-full variant it instead blends p̂ toward m). No calibrated-probability input discipline exists anywhere in this repo — their `confidence` knob is exactly the kind of uncalibrated shrinkage the v39 doctrine rejects. This machinery is a **regression risk** if adopted naively, not an upgrade.

### 2.2 Kelly — full binary, AMM pool-impact-aware (`kelly_criterion.py` L83–173)
- Closed-form quadratic solution for the bet that maximizes expected log wealth **including the bet's own effect on an FPMM (constant-product AMM) pool**, given YES/NO pool balances x,y, proportional fee f = 1−fee_rate. Imported from valory-xyz/trader (Apache-2.0 derivation credited; guard `y += 1e-10` when x==y).
- **Only valid where the venue price is set by a constant-product pool (Omen). Polymarket is an order-book CLOB** — pool balances are not the executable liquidity surface. Concept (impact-aware sizing, cap so you don't move the price against yourself) transfers; the closed form does not. Impact-aware sizing on CLOB needs order-book-depth integration.

### 2.3 Kelly — categorical simplified + full (`kelly_criterion.py` L176–419)
- Simplified: per-outcome `edge/odds` with optional shorting as negative sizes; winner-take-all or proportional split of max_bet; clips to ±max_bet (L209–244).
- Full: **SLSQP joint optimization over all outcomes maximizing expected log utility** `Σ p̂ᵢ·ln(1+profitᵢ)` with constraints Σ|bet| ≤ max_bet and no-guaranteed-loss (payout ≥ cost per outcome) (L363–389). Solid engineering details: early-exit all-zero when |p̂−m| < 1e-3 (L278), SLSQP warm-start from the simplified solution (L311), best-so-far tracking because SLSQP can terminate worse than an earlier iterate (L328–399), profit floor clip at −0.99 for log stability (L346), and winner-take-all enforced post-hoc by argmax (L401–410) because a hard constraint breaks the solver.
- Value for Xman: **concept-only**. Stack is binary CLOB markets; categorical/neg-risk multi-outcome betting is not a roadmap item. The SLSQP + best-iterate-tracking pattern is worth remembering IF categorical Kelly is ever needed.

### 2.4 Polymarket copy-trader (`markets/polymarket/copy_trading.py`, 461 lines — most roadmap-relevant file)
- `PolymarketCopyTrader` (L97): polls `data-api.polymarket.com/trades?user=` for a target whale, dedupes by `transactionHash` against a persisted JSON state file (`CopyTraderState`: replicated tx hashes + last poll ts, L62–82), replicates each trade:
  - BUY → USD = size×price×copy_ratio; skip if < min_trade_size; dry-run mode; balance check; place via CLOB (L185–241).
  - SELL → scaled token count, capped at our held balance, skip if no position (L243–295).
  - Skip taxonomy with reasons (market untradeable/closed, lookup failed, insufficient balance, dry_run) — every outcome returns a `ReplicatedTradeResult`, nothing silently drops (L134–152).
- `discover_top_traders` (L345): active high-volume gamma events → `trades?market=` per market → resolutions from Polymarket subgraph → per-trader **PnL/ROI/win-rate reconstructed from the public tape** (L400–444), sortable by volume/PnL/ROI/win-rate, min-trade-count filter.
- Verdict below: the **tape-reconstruction PnL approach** (works for ANY address, keyless, independent of leaderboard API) and the **dedupe-state + scaled-replication loop** are the two transferable concepts for C-200 shadow validation. Implementation is Python; ours would be Rust/TS.

### 2.5 Trade PnL reconstruction math (`markets/polymarket/data_models.py` L289–304)
```
BUY : win → size·(1−p)     lose → −size·p
SELL: win → −size·(1−p)    lose → +size·p
```
Standard and correct for the data-api trade convention. **Caveat: `to_polymarket_bet()` hardcodes `fee_rate_bps=0` (L373) and `get_profit` excludes trading fees** — a real (small) upward bias if used to rank traders on high-frequency books. Our whale analytics must keep modeling fees.

### 2.6 CLOB execution gotchas (`markets/polymarket/clob_manager.py`)
- **FOK market orders can return `success=True` for killed orders** — "The CLOB returns success=True even for killed FOK orders, so we must verify the transaction hash exists on Polygon" (L126–147): verify tx receipt on-chain, retry `OrderNotFoundError` with backoff. Operational nugget worth confirming our Rust sidecar already handles (if not: cheap hardening).
- Min BUY order 1 USDC enforced (L97); per-token fee rate via `get_fee_rate_bps` CLOB endpoint (L69–83); allowance approvals needed on CTF_EXCHANGE + NEG_RISK_EXCHANGE + NEG_RISK_ADAPTER (L159–193).
- **Market probability = CLOB `last-trade-price` only** (`get_last_trade_p_yes` L797) — no book mid, no VWAP, no staleness guard. Inferior to what the sidecar/v39 already consume. Do not regress.

### 2.7 Fee model (`markets/market_fees.py`, 72 lines)
- Generic fee struct: bet-proportional + absolute + **price-dependent taker fee in Polymarket's actual form** `fee = collateral × fee_rate × (1−p)` for buys (L58–72). Compact, verified against Polymarket's published fee shape. Concept: re-check our Kelly/ROI math carries taker fee this way (likely already does post-Phase B).

### 2.8 Metaculus crowd prior extraction (`markets/metaculus/data_models.py` L83–101)
- `p_yes` read from Metaculus **recency-weighted** aggregation `latest.forecast_values[1]` (index 1 = Yes, empirically determined; default 0.5 when unanswered). No aggregation math in-repo — consumes Metaculus' precomputed aggregate. Metaculus questions API requires an API token (`metaculus/api.py` L16). If ever wanted as an *independent, non-price* signal source (per doctrine: price-derived = prior, NOT evidence — a Metaculus crowd forecast is not price-derived), this extraction rule is the only nugget; 0.5-default-for-new-questions is a silent-prior trap to avoid. Not a roadmap item today.

### 2.9 Everything else checked and rejected (verified in source)
- `tools/omen/reality_accuracy.py` — Omen Reality.eth oracle-participant answer accuracy. Venue-specific, not portable.
- `deploy/betting_strategy.py` L499–556 — price-impact cap via `minimize_scalar` over FPMM impact deviation: **Omen AMM-only** (pool balances), not CLOB depth.
- FPMM probability / buy-token formulas (`markets/agent_market.py` L370, `markets/omen/omen.py` L1427) — standard Gnosis constant-product math, Omen execution only.
- Polymarket API surface (`markets/polymarket/api.py`): gamma events pagination, data-api trades (user/market), positions (`sortBy=CASHPNL` etc.), condition→slug→event chain, CLOB last-trade-price. **Keyless.** One genuinely useful fact: **data-api `/trades` offset is capped at 3000** (L206–208) — tape backfills of high-volume whales must window by time, not offset. (We likely know this from the tape DB work; flagging as verified.)
- Benchmark harness (`benchmark/benchmark.py`): agent-vs-market MSE, % within range, confidence-vs-error correlation, precision/recall — LLM-agent eval methodology, references **market price as the evaluation truth** (L205–222), i.e. it scores calibration-to-crowd, not accuracy. Not portable; no proper-scoring/Brier calibration of resolved outcomes anywhere in repo.
- Research/evidence wrappers: Perplexity, Tavily, "relevant news analysis", logprobs parser, LLM predictability/invalidity filters (`tools/is_predictable.py`, `tools/is_invalid.py` — pure LLM prompt tools). LLM layer → not-portable (doctrine: DeepSeek/local; and these add nothing to the shipped research bots).
- No arbitrage code anywhere (grep), no Kalshi anywhere (grep), no cross-market matching, no sports.

---

## 3. Fit table vs roadmap gaps

| Repo component | Xman roadmap gap | Verdict | Notes |
|---|---|---|---|
| Whale tape PnL/ROI/win-rate reconstruction from public trades (copy_trading.py L345–461, data_models.py L289) | C-200 copybot — whale wallet tracking & validation ladder ($500→$5k/day) | **concept-only** | Keyless; independent of leaderboard API; validates ANY address against the tape. LGPL → reimplement (Rust/TS against existing tape DB — likely simpler since 692M trades are local). Caveat: their PnL excludes fees; we must include them. |
| Copy-loop state machine: tx-hash dedupe + scaled replication + dry-run + skip-reason taxonomy (copy_trading.py L97–343) | C-200 replication ladder | **concept-only** | Pattern reference for flag-revertible shadow lanes: state file → poll → dedupe → scale → skip-or-execute. We already have whale tracking; the *replication* half is the new bit. |
| CLOB FOK fill-verification gotcha (clob_manager.py L126–147) | Execution hardening (sidecar) | **concept-only / adopt-as-fix** | Verify-on-chain-because-CLOB-lies-about-FOK. If sidecar lacks it, 1–2 dev-day hardening item; not a new feature. |
| Fee model incl. price-dependent taker fee (market_fees.py) | Phase B Kelly input discipline (shipped) | **concept-only** | Only as a check that our net-edge math uses the taker-fee form `fee = collateral×fee_rate×(1−p)`. |
| Categorical Kelly (simplified/full, SLSQP log-utility) (kelly_criterion.py L176–419) | none (binary-only stack) | **not-portable** | No categorical roadmap item. Pattern (warm-start + best-iterate tracking) noted for the future only. |
| Full binary Kelly, pool-impact closed form (kelly_criterion.py L83–173) | Kelly already shipped Phase B | **not-portable** | AMM-pool model ≠ CLOB book. Impact-aware sizing would need book-depth integration — a different derivation. |
| Simplified binary Kelly (L32–80) | Kelly already shipped Phase B | **not-portable** | Non-textbook heuristic; no calibrated-probability discipline; regression vs v39 doctrine. |
| Market prob = last-trade-price (polymarket.py L797) | v39 price engine | **not-portable** | Inferior estimator; do not regress. |
| Metaculus wrapper (api.py/data_models.py) | research-bot data feeds | **not-portable** | Auth-gated, LLM-forecaster ecosystem; only the p_yes-extraction rule is transferable if a crowd-prior lane is ever wanted (non-price source, so eligible as evidence per doctrine — but Metaculus API token + maintenance for marginal value). |
| Benchmark harness, LLM filters, Perplexity/Tavily/news, langfuse, logprobs, Omen Reality accuracy, CoW/FPMM execution, GCP deploy | none | **not-portable** | Omen-specific or LLM layer. |
| Arbitrage / Kalshi / sports / staged-market matching / relations lifecycle | Phase C PM↔Kalshi arb, Data-1 sports | **not-portable** | **Repo contains none of this** (grep-verified). Zero contribution to Phase C or Data-1. |
| Evidence aggregation / calibration math | v39 evidence engine, ML-2 feature registry | **not-portable** | **Repo contains none.** Nothing new vs v39 + research bots. |

**Bottom line:** the repo is ~90% not-portable (Omen + LLM layers), ~10% concept-only, 0% adopt-verbatim. The only genuine concept value sits in the copy-trading file, aimed at C-200 — and even there it is an alternative validation path for machinery the stack partially has.

---

## 4. Integration proposal (all post-Oct-8, recommendations only, flag-revertible)

**Proposal A (the only one worth scoping): C-200 shadow-lane — tape-reconstructed whale PnL validation.**
- What: a shadow lane that recomputes candidate whales' PnL/ROI/win-rate from the local 692M-trade tape joined to resolutions (fees included), as an independent cross-check of leaderboard/analytics-derived whale scores before a whale enters the copy ladder. Reimplement the concept from copy_trading.py L345–461 + data_models.py L289 in the existing stack language (Rust sidecar or TS); flag `shadow_whale_pnl_recon` on/off; output goes to the existing shadow/webhook channel, never to sizing.
- Effort: **3–5 dev-days** (join trade tape → resolutions; fee-aware PnL; win-rate/ROI; per-whale lag/window config). Risk: **low** — read-only over local data. Revert: flag off; no state mutation.
- Note: for live (non-tape) whales, data-api `/trades` pagination must window by time (offset cap 3000, verified L206) — the gnosis code just warns and stops; ours must not.
- Optionally fold in the **replication-loop state-machine pattern** (dedupe-by-hash + scale + dry-run + skip reasons) when the copy ladder itself is built — again reimplemented, 2–3 additional dev-days at that time, not now.

**Proposal B (hardening check, 1–2 dev-days, possibly already done): confirm the Rust sidecar verifies FOK fills on-chain** (tx receipt status, retry on missing tx) since the CLOB reports success for killed FOK orders (clob_manager.py L126–147). If already handled, close as no-op.

**Proposal C (audit check, ≤1 dev-day): confirm net-edge/ROI math charges Polymarket's price-dependent taker fee** as `collateral × fee_rate × (1−p)` (market_fees.py L58). If the fee form is wrong in any sim path, fix it; else no-op.

Nothing here touches Phase C, Data-1, ML-2, or Phase D2 — the repo has no material for those lanes.

---

## 5. NOT-portable list

1. **Everything under the LLM/agent layer** (langchain/openai/pydantic-ai/langfuse; `tools/is_predictable.py`, `tools/is_invalid.py`, `tools/rephrase.py`, logprobs parser; Perplexity/Tavily/news research wrappers; benchmark harness + PredictionsCache). OpenAI/langchain-centric → excluded by doctrine (DeepSeek/local models) and by redundancy with the shipped research bots.
2. **All Omen/Reality.eth/CoW/FPMM machinery** (omen subgraph/contracts, Reality oracle accuracy, FPMM probabilities, AMM buy-token math, AMM price-impact sizing, CoW order execution). Venue doesn't exist in the stack.
3. **Pool-impact Kelly (full binary + categorical-full SLSQP)** — FPMM assumption invalid on CLOB; categorical irrelevant to a binary stack.
4. **Simplified Kelly heuristic** — non-textbook, confidence-shrinkage semantics conflict with calibrated-probability doctrine; a downgrade of shipped Phase B sizing.
5. **Metaculus/Manifold/Seer adapters** — out-of-scope venues; auth-gated.
6. **GCP deploy/kubernetes/streamlit monitoring, cron-validator, safe/transaction-cache infrastructure** — different infra philosophy (shadow lanes + webhooks, not GCP agent fleets).
7. **lgpl-3.0 license itself** — nothing from this repo enters our tree; reimplement concepts only.

---

## 6. Honest caveats + verdict

Caveats:
- **License posture is the ceiling:** even the small, elegant bits (fee model, dedupe state machine) cannot be copied — every adoption here is reimplementation from a spec, which raises cost and lowers fidelity vs an MIT repo.
- **Kelly file docstrings overstate:** simplified Kelly cites Wikipedia but implements a different (heuristic) formula; the full variant is AMM-only. Anyone lifting "their Kelly" without reading source would ship a sizing regression. Verified against source, not README.
- **Their tape PnL excludes fees** (fee_rate_bps hardcoded 0) — if we reimplement the reconstruction concept we must include fees or whale ranks drift on high-frequency books.
- **Last-trade-price as p_yes** is their only Polymarket probability estimator — naive; the stack's book-derived prices are strictly better.
- **No arbitrage/Kalshi/sports/evidence/calibration code exists in this repo** despite it being a "prediction-market agent" toolkit — its deterministic core is *position-sizing + tape analytics*, not discovery/aggregation. Any expectation of Phase C / Data-1 / ML-2 material would be wrong.
- Repo is Omen-first with Polymarket as a secondary adapter; maturity signals (on-chain FOK verification, skip-reason taxonomy) are real but confined to that adapter. Numbers cited above (3–5 dev-days etc.) are estimates from this audit's reading of scope, not measured effort.

**Verdict: SKIP (with one queued concept extraction for C-200).** Nothing is adopt-verbatim (LGPL-3.0); nothing addresses Phase C, Data-1, ML-2, or Phase D2; Kelly, evidence, and execution machinery already shipped in the stack are equal-or-superior. The single worthwhile action, queued behind the Oct-8 freeze and gated on roadmap order (C-200 slot), is Proposal A: reimplement the **whale PnL/ROI/win-rate reconstruction-from-tape** concept (copy_trading.py L345–461 + data_models.py L289–304, fee-corrected, joined to the local 692M-trade DB) as a flag-revertible shadow validation lane for whale selection — 3–5 dev-days, low risk, no pre-Oct-8 shipping. Proposals B and C are ≤2 dev-day verification/hardening checks against code the stack already owns. Recommendation: do not schedule any work against this repo; record the two concept specs (tape-PnL recon, replication state machine) in the C-200 planning notes and close the audit.
