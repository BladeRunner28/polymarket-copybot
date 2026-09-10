# Repo Audit — ulab-uiuc/coinjure (adoption fit beyond the vendored matching module)

**Date:** 2026-09-09 · **Auditor:** subagent deep-audit (github-repo-audit procedure)
**Repo:** https://github.com/ulab-uiuc/coinjure · **License:** MIT (LICENSE file verified; © 2024 Haofei Yu; pyproject `license = "MIT"`)
**Stars/forks:** 35 / 4 · **HEAD:** 51bd34c 2026-04-07 (`feat(videos) #231`) · **pushed_at:** 2026-05-05 (~4 mo dormant — treat as frozen)
**Default branch:** main (only branch) · tags v0.1.0, v0.1.1 · version 0.1.1 (PyPI `coinjure`)
**Repo state:** ~22.8K LOC package (`coinjure/`, 113 py files repo-wide), 34 test files / 9,470 LOC, 423 `def test_*` counted statically. **Tests NOT executed here** (poetry deps pyarrow/httpx/openai/kalshi_python not installed) — verdicts on tests by inspection of assertion quality. No fabricated numbers below.

**Sibling-repo relationship:** this repo is the UIUC-lab "trading agent harness"; oracle3 (Yicheng Yang, same lab, Apache-2.0, audited 2026-09-07) *vendors a package literally named `coinjure`* but containing **only** `matching/` — a cross-platform matcher that this repo's current HEAD does **not** contain (see §3 — the audit's central correction).

---

## 1. What it is

Coinjure is an LLM-agent-driven **trading harness** for Polymarket + Kalshi: an OpenAI-Agents-SDK "agent" layer drives a deterministic core — `market discover` (rule-based relation discovery) → `engine backtest` (relation-level backtests on real orderbook-snapshot parquet) → `engine paper-run/live-run` (process-per-strategy engines with control server + killswitch) → Textual/TUI monitor. 8 relation types (`implication, exclusivity, complementary, same_event, correlated, structural, conditional, temporal`) map 1:1 to 7 builtin arb strategies (`implication_arb`, `group_arb`, `direct_arb`, `coint_spread`, `structural_arb`, `conditional_arb`, `lead_lag`). README claims "100+ backtest-positive strategies in an hour" and real live profit — treat as lab claims, no in-repo track record.

**Relationship to this stack:** the only previously-vendored coinjure asset (the `matching` module, verdict ADOPT at Phase C kickoff) is **not in this repo** — it lives in oracle3 (see §3). This audit therefore covers (a) the byte-identity/provenance question and (b) what *this* repo still transfers beyond it.

---

## 2. Verified machinery (from source, not README)

### 2a. Relation lifecycle + store — deterministic, simple
`coinjure/market/relations.py` (251 LOC): `MarketRelation` dataclass (relation_id, markets[], spread_type, confidence, hypothesis string, hedge_ratio = β from OLS p_A = α + β·p_B, lead_lag int, status, backtest_pnl/trades) + `RelationStore` JSON file store with **fcntl flock + tmp-file-write + atomic rename** (Windows no-op fallback). Lifecycle statuses: `active → backtest_passed | backtest_failed → deployed → retired` (set_backtest_result / mark_deployed / mark_retired). This is the *lab-simple* version; oracle3's `market/relations.py` (discovered→validated→deployed→retired + `ValidationResult` with violation_count/rate/mean_arb/current_arb + ADF/EG stats) is strictly richer and already the Phase C adoption reference. Incremental value here: the ~30-line **multi-process-safe atomic JSON journal** pattern (flock + rename) — a clean fit for a research-bot shadow journal that the Phase C oracle3 audit left open ("store as JSON/SQLite").

### 2b. Intra-event discovery rules — deterministic regex core + 1 LLM call
`coinjure/market/auto_discover.py` (475 LOC) — deterministic detectors, verified:
- `parse_deadline(question)`: regex family — `_RE_MONTH_DAY_YEAR` ("December 31, 2025"), `_RE_MONTH_DAY`, `_RE_IN_YEAR` (`in|by end of <year>?`), `_RE_BEFORE_YEAR` → **date-nesting implication** detection `detect_date_nesting` (same event, earlier deadline A ⇒ later deadline B; confidence 0.95).
- `detect_exclusivity`: winner-take-all events — ≥80% of active markets match `_RE_WINNER = will\s+.+\s+(win|qualify|be\s+the)` → one group relation, confidence 0.99.
- `detect_complementary`: exhaustive events — mid-price sum within tolerance 0.15 ⇒ sum ∈ [0.85, 1.15] (confidence 0.95); exhaustive-ness optionally *verified by an LLM call* (`_llm_verify_exhaustive`, prompt heuristic).
- Discovery is intra-event only (deadline nesting / outcome groups); **cross-venue same-event pairing is NOT in this repo** — oracle3's matcher fills exactly that gap.

### 2c. Builtin arb strategies — formulas verified (all Decimal arithmetic)
- **`direct_arb_strategy.py`** (663 LOC) — same_event cross-platform pair (poly_market_id + poly_token_id + kalshi_ticker), the *consumer* of matched pairs: `gross = |yes_poly − yes_kalshi|`; `net = gross − 2×0.005` (flat per-side fee); entry `net ≥ min_edge` (default 0.02), exit `held_net < close_edge` (0.01 default), cooldown; NO legs priced at the **1 − YES mirror** on the expensive venue (approximation — same caveat as oracle3's arb legs). Verified.
- **`group_arb_strategy.py`** (635 LOC) — exclusivity/complementary group constraint. Verified math: `edge_buy_yes = 1 − Σask_YES − fee·n` (complementary only), `edge_buy_no = Σask_YES − 1 − fee·n`; **exclusivity hard-disables BUY_YES (`edge = −1`)** because "no outcome wins" loses all YES legs while BUY_NO still profits (all settle NO ⇒ payout N ≥ cost) — sound; fees `_FEE_PER_SIDE = 0.005` taker / `_FEE_PER_SIDE_MAKER = 0` (Kalshi maker); maker mode uses bid sums; stop-loss `max_loss`, exit `close_edge`. Test `tests/test_group_arb_strategy.py` encodes exact hand-computed cases (e.g. `edge_buy_yes = 1 − 0.50 − 0.005·5 = 0.475`; exclusivity sum>1 → BUY_NO only).
- **`implication_arb_strategy.py`** (190) — violation = p_A − p_B > min_edge (0.01) ⇒ buy NO A + YES B; exit when restored. **`structural_arb_strategy.py`** (262) — p_A = slope·p_B + intercept; trade residual beyond min_edge (±0.02), exit at 0.5×. **`conditional_arb_strategy.py`** (271) — Bayes-consistency bands: p(A) ≥ cond_lower·p(B) and p(A) ≤ cond_upper·p(B) + (1 − p(B)); trade band violations. Verified as stated.
- **`coint_spread_strategy.py`** (303) — **misnamed**: no cointegration/stationarity test anywhere in the repo (verified: zero ADF/Engle-Granger/half-life-of-spread code; `allocator.py`'s half-life is a different, portfolio-decay formula). Actual algorithm = rolling z-score mean reversion on `spread = p_A − β·p_B` (warmup 200, entry ±2σ, exit 0.5σ) — a plain Bollinger-style spread trade. **`lead_lag_strategy.py`** (317) — leader mean-move threshold (0.03) → trade follower, exit on catchup_ratio ≥ 0.5 or max_hold 100 updates.
- **`trading/sizing.py`** (215) — `compute_trade_size`: `available·effective_kelly·min(edge/edge_cap,1)` clamped [min,max]. `_dynamic_kelly`: models the position as a $1-payout asset bought at price (1−edge) → net odds b = edge/(1−edge), Kelly f = (b·w − (1−w))/b, then `min(f, static_fraction=0.1)` — internally coherent (riskless-arb framing w = 1 ⇒ f = 1, capped by static fraction); the stack's Phase B Kelly (Thorp-form, oracle3-derived) already supersedes it; nothing new to take.
- **`trading/allocator.py`** (157) — verified: strategy-allocation time decay `w = exp(−0.693·age_days/half_life_days)` (= 2^(−age/half-life), half-life default 30 d) — small concept for research-bot strategy portfolio weighting.
- **`trading/risk.py`** (440) — `StandardRiskManager`: dollar-limit gates only (max single trade / per-ticker position / total exposure / drawdown 20% / daily loss / max positions). No math of interest; concept-level matches stack's own risk layering.

### 2d. Backtest/validation harness — genuinely useful patterns
- `coinjure/engine/backtester.py` (484): `run_backtest_relation(relation, …)` — builds event stream from **real Polymarket orderbook-snapshot parquet** (`data/backtest/parquet.py`: pmxt snapshots, columns `timestamp_received, market_id, update_type(price_change|book_snapshot), data(JSON)`), optional **train/test split** (two engines), `slippage_bps`, `commission_rate`, min/max fill-rate; **pass criterion `passed = pnl > 0`** → promotes relation in lifecycle. Default zero slippage (honest default with opt-in spread). This relation→backtest→promote loop is exactly the Phase C validation-journal skeleton.
- `coinjure/engine/performance.py` (431): win_rate, max_drawdown (+duration), sharpe, sortino, profit_factor, equity curve — standard analytics, no exotic math.
- **P0 guards worth stealing**: `tests/test_engine_p0.py` asserts the engine **auto-degrades to read-only on error storms and on portfolio-health breach** — same flag-revertible philosophy as the stack's Kelly-window rules; implementation in `engine/engine.py`/`control.py`.
- Tests overall (423 static): strongest are exact-arithmetic strategy tests (`test_group_arb_strategy.py`), relation-store CRUD (`test_relations.py`), order-result contract, LLM-sizing fallback tests. **Port-ready pattern: invariant-arithmetic tests for Phase C arb families.**

### 2e. LLM-adjacent layers — deterministic core with prompt-heuristic overlay
`strategy/agent.py` (OpenAI Agents SDK tool strategies), `trading/llm_allocator.py` (493), `trading/llm_sizing.py` (344): the *only* non-deterministic parts. Architecture is sound: deterministic quant sizing is the **anchor** (`quant_size` fed to the prompt), LLM output is JSON-parsed with Decimal coercion + validation (`_to_decimal`), failures fall back to the deterministic path, and async LLM results are **cached + rate-limited + pending-tracked** so strategies never block on the model. The stack's DeepSeek research bot already plays this role; **not portable, but the "deterministic anchor + optional LLM overlay + cache" pattern is the right separation** (concept).

### 2f. Data providers / market-data models
`data/live/polymarket.py` (1,282 LOC; Gamma + CLOB REST/polling, token_id/no_token_id normalization), `data/live/kalshi.py` (601 LOC; public `api.elections.kalshi.com/trade-api/v2` **keyless** endpoints + RSA-signed auth for trading when KALSHI_API_KEY_ID/PRIVATE_KEY_PATH set), `data/manager.py`/`source.py` (polling `DataSource` abstraction with composite merge), `data/order_book.py` (level lists), `data/news.py` (crawler). The stack already has its own Polymarket CLOB + keyless Kalshi adapters (Rust sidecar + TS dashboard) — these add no stack value beyond being a code reference for Kalshi RSA signing and pmxt-snapshot replay. **not-portable / low-value reference.**

---

## 3. Byte-identity verdict on the "vendored" matching module — ⚠️ material correction

**Finding: ulab-uiuc/coinjure never shipped the staged matcher, at HEAD or anywhere in history.** Evidence, all from the full (unshallowed) git history of the clone:

1. **No `matching/` package ever existed here.** `git log --all --diff-filter=D/A` and whole-history name scans over 122 commits + tags v0.1.0/v0.1.1: zero hits for any `matching/` path. Current HEAD tree has no matcher; oracle3's 9-module `coinjure/matching/` package (1,559 LOC) has no counterpart to diff against.
2. **The only upstream matching code ever was (a) `coinjure/market/matching.py` — 73 LOC fuzzy `match_markets()` (stopword-normalize + `SequenceMatcher ≥ 0.60`), added 2026-03-07 (bb32a53), deleted 2026-03-08 (df7220c, "delete useless files"); and (b) `examples/strategies/cross_platform_arb_strategy.py` — 429 LOC (MarketMatcher/CompositeTrader/CrossPlatformArbStrategy/MatchedMarket), added same day, deleted 2026-03-08 (194b972).** Both predate oracle3 v1.1.2 (2026-05-07) and were removed during this repo's pivot to the LLM harness — the matcher lived in upstream for **< 1 day**.
3. **Lineage, not byte-identity:** oracle3's `examples/strategies/cross_platform_arb_strategy.py` is a direct descendant of the deleted upstream file (shared class/function identifiers — `MarketMatcher, CompositeTrader, CrossPlatformArbStrategy, MatchedMarket, _normalize` + identical stopword set — `diff` = 113 lines, mostly import rewrites to `oracle3.*`). But oracle3's `coinjure/matching/` **package** (stages `_category/_date/_template/_text/_resolution/_pipeline/_types/_cache`, plus `_fetchers.py`) is oracle3's own from-scratch **staged** redesign (weights 0.10/0.20/0.30/0.30/0.10 = 1.00; template stage with hard-reject field mismatch −1.0; 3-way max text similarity ≥ 0.45) — it supersedes the deleted fuzzy matcher and is byte-unrelated to any file ever in upstream history.
4. **Vendored-copy health:** the vendored stage modules are clean — zero `oracle3.*` or `coinjure` imports inside `matching/*.py` (stdlib + httpx in `_fetchers.py` only); the single oracle3 coupling is the lazy `match_result_to_matched_market` adapter in `matching/__init__.py`. Verified stage math matches the oracle3 audit: date (1.0 within 7 d, linear decay to 0 at 30 d, 0.5 neutral), template (election_state_race party+state+race_type; crypto_price_threshold coin+price+threshold — both orderings; same-template-different-fields = −1.0 hard reject), resolution (official-source whitelist + end-date Δ>7 d warning), text floor 0.45.

**Verdict: byte-identity vs "upstream" = NOT APPLICABLE — there is no upstream to drift from, and therefore no upstream upgrade is pending or possible.** The repo that would be the upstream *deleted* the matcher six months ago and is dormant (~4 mo). The practical consequences:
- **Source of truth for Phase C adoption = oracle3 HEAD 86c2518 (Apache-2.0), exactly as the oracle3 audit planned.** Nothing should be pulled from ulab-uiuc/coinjure for the matcher.
- **Attribution nuance:** the vendored matcher's lineage traces to coinjure MIT code deleted 2026-03-08; oracle3 reworked it under Apache-2.0. Both licenses are permissive and compatible; when vendoring from oracle3 keep the Apache-2.0 notice and add a one-line MIT-origin note (coinjure, Haofei Yu / UIUC ulab) for cleanliness. No legal blocker.
- Re-check trigger: only if ulab-uiuc/coinjure ever publishes a matcher again (it shows no sign of doing so; frozen upstream).

---

## 4. Fit table vs roadmap gaps

| coinjure component (verified path) | Roadmap gap | Verdict | Effort / risk |
|---|---|---|---|
| **Staged matcher** — NOT in this repo; lives in oracle3 (`oracle3/coinjure/matching/`, 1,559 LOC) | Phase C PM↔Kalshi same-event matching | ✅ **ADOPT from oracle3** at Phase C build kickoff (as prior audit; source-of-truth correction above) | ~0.5–1 d incl. adapter + held-out gate; LOW; flag-revertible (detection/shadow lane) |
| `market/relations.py` atomic JSON journal (flock + tmp + rename, ~30 LOC pattern) + lifecycle statuses | Phase C shadow journal storage ("detection + shadow first") | ✅ adopt pattern (0.25 d) — multi-process-safe journaling for the research bot; reuse oracle3's richer lifecycle states, not coinjure's | LOW |
| `market/auto_discover.py` deterministic detectors: `parse_deadline` regexes, date-nesting implication (conf 0.95), winner-take-all exclusivity (≥80% `will X win`, conf 0.99), complementarity sum ∈ [0.85,1.15] (conf 0.95) | Phase C relation discovery *within* events/series (matcher covers cross-venue only) | ⚪ concept-only — port detector *logic* as a small module in the research bot; Kalshi series outcomes make group detection near-free; drop the LLM exhaustive-verifier call | 0.5 d; LOW |
| Group-arb invariant arithmetic: `edge_buy_yes = 1−Σask−fee·n`, `edge_buy_no = Σask−1−fee·n`, exclusivity BUY_YES disable, maker=0 fee split; `test_group_arb_strategy.py` exact-arithmetic tests | Phase C exclusivity/event-sum families (design notes 1b/1c) | ⚪ concept-only — reference formulas + **port the exact-arithmetic test style** as the Phase C invariant test harness | 0.25–0.5 d; LOW |
| Implication / structural / conditional formulas (A≤B, p_A=slope·p_B+c, Bayes bands) | Phase C implication + structural families | ⚪ concept-only (already specified in design notes; oracle3 versions equivalent) | — |
| `engine/backtester.py` relation→train/test→`passed = pnl>0`→promote + pmxt orderbook-parquet replay (`data/backtest/parquet.py`) | Phase C validation journal + λ̂ refit reporting cadence | ⚪ concept — adopt the *lifecycle-promotion gate shape* (pnl>0 + train/test split) for shadow journals; stack's own backtest infra stays | 0.25 d; LOW |
| `engine` P0 guards: auto-degrade to read-only on error storm / portfolio-health breach | flag-revertible integration culture; research-bot crash safety | ⚪ concept (0.25 d) — mirror as a watchdog in the research bot if absent | LOW |
| `_dynamic_kelly` / risk managers / direct_arb / lead_lag / coint z-score | Phase B sizing (shipped), Phase D2 fills | ❌ skip — superseded by shipped Phase B Kelly; coint/lead-lag are weaker than the stack's v39 Bayesian engine | — |
| `trading/allocator.py` half-life decay w = 2^(−age/half-life) | research-bot strategy weighting | ⚪ concept-only, tiny (10 lines) — only if research bot wants recency-weighted strategy mix | trivial; LOW |
| Data providers (`data/live/*`, news crawler), `hub/`, `engine/` process-per-strategy, CLI/TUI, storage, demo/e2e | — | ❌ not-portable (see §6) | — |
| LLM overlay pattern (deterministic anchor + cached/rate-limited async LLM refinement + Decimal-validated JSON) | research-bot LLM use | ⚪ concept — already the stack's DeepSeek-bot pattern; confirms the architecture | — |

---

## 5. Integration proposal (all post-Oct-8 / Phase C build; Kelly window untouched)

1. **Matcher (0.5–1 d, LOW):** vendor from **oracle3** `coinjure/matching/*.py` → `scripts/vendor/oracle3/coinjure/matching/` (Apache-2.0 notice + MIT-origin line), keep `_fetchers.py` out, write the Gamma↔Kalshi `NormalizedMarket` adapter; gate on held-out known-same-event pairs (per oracle3 audit §4.1). No change vs prior plan — this audit only corrects the provenance record.
2. **Shadow journal (0.25–0.5 d, LOW):** borrow the flock+atomic-rename JSON store pattern for the research bot's Phase C journal; lifecycle states from oracle3's relations model.
3. **Discovery helpers (0.5 d, LOW):** port `parse_deadline` + winner-take-all/exhaustive detectors for intra-event grouping on Kalshi series and PM events — feeds the shadow lane with relation candidates before the matcher cross-checks venues.
4. **Invariant test harness (0.25–0.5 d, LOW):** replicate `test_group_arb_strategy.py`'s exact-arithmetic style for exclusivity/event-sum/implication in the Phase C test suite.
5. **P0 watchdog (0.25 d, LOW):** error-storm → read-only degrade guard for the research bot, if not already present.
6. **Skip:** everything in §6. Effort if all adopted: ~1.5–2.5 d, all Phase C-build or research-bot scope, all flag-revertible (detection/shadow first), nothing pre-Oct-8.

---

## 6. NOT-portable list

- **Engine/process architecture** (`engine/engine.py` 702, `multi_strategy_engine.py` 1,112, `runner.py`, `control.py` socket control server, `registry.py`, hub pub/sub, demo_hub) — the stack's TS dashboard + Rust sidecar + research-bot split doesn't match; orchestration semantics only.
- **Live/paper traders & venue clients** (`engine/trader/*`, `data/live/polymarket.py`, `data/live/kalshi.py` RSA client, `trading/trader.py`, `position.py`, `types.py`) — the stack has its own paper fills (Phase D2 Cox-PH plan is ahead of anything here) and keyless Kalshi adapter; Kalshi RSA signing is a reference at most.
- **LLM agent layer** (`strategy/agent.py` OpenAI Agents SDK, `cli`, `.claude/skills/*`, `strategy/loader.py`) — duplicates the stack's DeepSeek research bot + local-LLM lanes.
- **Backtest harness code itself** (`engine/backtester.py`, parquet replay) — stack has its own; only the promotion-gate *pattern* transfers.
- **News crawler** (`data/news.py`), **CLI/TUI monitors** (`cli/*` textual_monitor), **demo/e2e/scripts** (`hub/demo_hub.py`, `examples/*`, `scripts/record_demo.sh`), and `data/kalshi-live/fomc_arb.py` (contains hard-coded `os.chdir('/Users/ethanyang/prediction-market-cli')` — research-scaffold proof; never runnable off the author's machine).
- **CointSpread/LeadLag strategies** — mislabeled/weak heuristics; the stack's Bayesian log-odds engine supersedes.

---

## 7. Honest caveats + verdict

- **Caveats:** (a) dormant upstream (HEAD 2026-04-07, pushed 2026-05-05) — treat as frozen; nothing to track for upgrades, including the matcher, which this repo doesn't contain; (b) 423 test fns counted statically, **suite not run here** (poetry deps not installed) — assertion quality inspected and genuinely good (exact-arithmetic cases, exclusivity edge cases, P0 guards), but "live-validated, real profit" is a README claim with no in-repo track record; (c) **"cointegration" is a misnomer** — no stationarity test exists; it's a rolling z-score spread trade; don't import that terminology into Phase C docs; (d) group/direct arb use the 1−YES NO-mirror and flat 0.5% taker fee (maker=0 known) — fine as *reference math*; Phase C must use venue fee schedules and real Kalshi NO books; (e) intra-event discovery tolerances (0.15 sum band, 0.80 winner regex, 0.95 confidences) are unvalidated lab defaults — recalibrate on own resolved data before trusting counts; (f) conditional-arb Bayes bands assume independence-free bounds — check against the stack's v39 engine semantics before any port; (g) oracle3-audit note stands: this repo's matcher descendant lives under oracle3's Apache-2.0, so Phase C vendor copies carry Apache-2.0 + MIT-origin attribution (both permissive — no blocker).
- **Verdict: QUEUE → ADOPT (unchanged, with a provenance correction).** The Phase C matcher payload is adopted from **oracle3** (source of truth), not from this repo — verified this repo never shipped it and its only upstream matcher was deleted 2026-03-08; no upgrade path exists to track. From *this* repo, the incremental transfers are small and cheap: the atomic-JSON journal pattern (0.25 d), deterministic intra-event discovery detectors (0.5 d), exact-arithmetic invariant tests (0.25–0.5 d), P0 read-only watchdog concept (0.25 d) — all Phase C-build or research-bot scope, all flag-revertible, all post-Oct-8 per the standing Kelly-window freeze. Everything else (harness, traders, LLM agent layer, data providers, coint/lead-lag heuristics) is concept-only or not-portable. Net: **one repo to vendor from (oracle3), a handful of small pattern borrows here, zero pre-Oct-8 action.**
