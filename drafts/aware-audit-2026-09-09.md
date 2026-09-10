# AWARE (ent0n29/aware) — Adoption Audit — 2026-09-09

Audited for fit into Xman's Polymarket/Kalshi stack (TS/Rust, paper-only, v39 Bayesian evidence engine, Kelly Phase B SHIPPED, PMA tape, local-LLM sentiment bot). Kelly measurement window Sep 8–Oct 8: **nothing ships, recommendations only, flag-revertible**.

Source: shallow clone at `/tmp/audit_triage/clones/ent0n29_aware` (HEAD `cf5e1d6`, 2026-02-21). Refs below are repo-relative.

---

## 1. What it actually is

**License: MIT** (verified `LICENSE`, "Copyright (c) 2024-2026 AWARE"; GitHub API spdx_id=MIT). Borrowable with attribution. ✅

"**AWARE Fund — Smart Money Index for Prediction Markets**" (GitHub description; README line 1: *"Don't bet on outcomes. Bet on the best traders being right."*). 56 stars, Python+Java+TS, 284 code files, created 2026-01-05, **last pushed 2026-02-21 — dormant ~6.5 months**.

Despite the fund-y name, the repo is a **three-project mashup** on one `polybot` execution base (`com.polybot.hft.*` Java packages):

1. **Polybot base**: Java microservices (executor/strategy/ingestor/analytics) + ClickHouse — a real Polymarket maker/HFT scaffold (e.g., `GabagoolDirectionalEngine.java` complete-set edge engine with hysteresis; complete-set arb concepts).
2. **Gabagool22 reverse-engineering research** (`research/`): offline analysis + a bot clone of one specific Polymarket BTC-up/down maker ("gabagool22"), incl. fill-model calibration (`calibrate_maker_fill_model.py`), replication scoring vs trade prints (`replication_score_orders.py`). *Separate embedded project — not the README product.*
3. **AWARE product layer** (`aware-fund/services/analytics/` + FastAPI + Next.js): the README headline — Smart Money Scores on top traders, PSI index family, fund-mirroring engine (Java), insider alerts, NAV/deposit product pages (fund never launched; README: smart-contract custody "still pending").

**Farm-tell assessment**: NOT a name-vs-content farm — the machinery is real and internally consistent (orchestration in `run_all.py`, ClickHouse DDL cascade, Java services with unit tests). BUT the analytics layer has classic **scaffold-as-pipeline** patches (see Caveats): hardcoded placeholders in `strategy_dna.py`, no ML checkpoints anywhere, bootstrap-relaxed index criteria, and the repo's flagship "ML ensemble" has no trained artifacts.

---

## 2. Verified machinery (formulas + file paths)

Deterministic core located in `aware-fund/services/analytics/` (Python). Line-by-line verification vs standard references:

### 2.1 Smart Money Score rubric — `scoring_job.py`
`SmartMoneyScorer.calculate_score` (L55-113): weighted rubric, score = 0–100 int:
- **profitability 40%** (`_score_profitability` L115-146): percentile of total P&L vs scored peers (capped 95) when peer set >10; else absolute $ P&L tiers.
- **risk_adjusted 30%** (`_score_risk_management` L148-176): points for *small* avg trade size (≤$100 → +20 … >$1000 → +5) + market diversity (+10..30).
- **consistency 20%** (`_score_consistency` L178-217): trades/day + buy/sell balance + days-active.
- **track record 10%** (`_score_track_record` L219-268): days-active + volume + market diversity.

Tiers: BRONZE <40 / SILVER 40-59 / GOLD 60-79 / DIAMOND ≥80 (L337-346).

**Verification notes (math/design)**: formula is a transparent heuristic — deterministic, bounded, no hidden math errors. Two design flaws worth flagging:
- The "risk_adjusted" label overstates: no volatility/Sharpe input — it rewards *small size* (which is anti-correlated with the big wallets a mirror sleeve usually wants) and *diversity*.
- **Feature double-counting across weighted components**: `days_active` scores in both consistency (≤35) and track-record (≤35); `unique_markets` scores in both risk (≤30) and track-record (≤30). Activity/diversity is effectively counted 2-3× inside a rubric whose weights pretend the components are orthogonal.

### 2.2 Sharpe — `sharpe_calculator.py` (L91-191)
`sharpe = (mean_daily_pnl / σ_daily_pnl) × √365` on realized daily P&L (`aware_position_pnl` grouped by `toDate(resolved_at)`), ClickHouse `stddevPop`. Capped at 10.0; confidence = `min(days/30, 1)`; tier thresholds 0.5/1.0/1.5/2.0 with confidence gates.

**Verified**: annualization factor and formula standard. Caveats: $ P&L (not return %) — fine for per-trader consistency ranking, not capital-relative performance; "max drawdown" is a fake proxy (`abs(min(worst_day,0)/mean_daily)`, L171-176); "sigmoid-like" comment (L168) is actually a linear ramp (numerically consistent with cited points, but mislabeled).

### 2.3 Edge-decay statistics — `edge_decay.py` (L35-233) ✅ the strongest math in the repo
- **Two-proportion z-test** (L35-64): pooled `p_pool=(p1·n1+p2·n2)/(n1+n2)`, `se=√(p_pool(1−p_pool)(1/n1+1/n2))`, `z=(p1−p2)/se`. **CORRECT** vs standard reference.
- **Welch's t** (L67-99): `(mean1−mean2)/√(s1²/n1+s2²/n2)`. **CORRECT**.
- **z→p** (L102-145): Abramowitz–Stegun 7.1.26 erf approx, constants a1..a5, p=0.3275911. **CORRECT**.
- **Welch–Satterthwaite df** (L177-201): standard formula. **CORRECT**.
- **BUG — `t_to_pvalue` small-df (L148-174)**: for df ≤ 30 it computes `z = t·√(df/(df−2))`, *inflating* t → *smaller* p. Wrong direction: small-df t-distributions have fatter tails → p should be **larger** than the normal approximation, not smaller. Anti-conservative bias on small samples (exactly where decay detection matters). Fix: proper t CDF or conservative normal-with-fatter-tail bound.
- **Misnomer — `bootstrap_confidence_interval` (L204-233)**: not bootstrap at all; normal-theory with `se = |diff|/√n` (no variance estimate). Self-aware comment admits it. Name it "normal approx CI" or implement real resampling.

Decay scan (`EdgeDecayDetector.check_trader` L343ff) compares historical vs recent windows on Sharpe, win rate, returns, consistency → `DecaySignal`/alerts. **Wiring**: feeds alert records + notifications (run_all sequence), *not* auto-rebalancing — same recommendations-only philosophy as Xman's freeze.

### 2.4 PSI index construction — `psi_index.py`
`INDEX_CONFIGS` (L137-273): PSI-10/25/ALL/CRYPTO/POLITICS/SPORTS/NEWS/ALPHA with per-index configs. **The design gem**: `NON_REPLICABLE_STRATEGIES = [ARBITRAGEUR, MARKET_MAKER, SCALPER]` (L42-48) excluded from mirrorable indices, with the stated reason *"copying them late loses money"* (5s+ delay). Eligibility floors (score/trades/days/volume/Sharpe), weighting methods (equal/score/Sharpe/volume), concentration caps (`max_weight_per_trader` 0.15-0.20, `max_strategy_concentration` 0.30-0.40), rebalance cadence. Build path: eligible-traders SQL → strategy/category filters → top-N → weights → `PSIIndex` (L323-370).

**Caveat**: all configs are "bootstrap-relaxed" (min_trades=5, days_active=1, volume=$500, min_sharpe=0.0) — the index family never ran with meaningful criteria (no 90-day data existed by last push).

### 2.5 Consensus — `consensus.py` (L378-415)
Heuristic smart-money agreement: confidence = 0.30·log-scaled trader count (`log(n+1)/log(21)`) + 0.40·volume share + 0.30·mean Smart Money Score of majority. Strength tiers by agreement %. **Not** Bayesian evidence combination — orthogonal, additive heuristic.

### 2.6 Fund mirror engine — Java `strategy-service/.../fund/service/FundPositionMirror.java`
Trade-print mirroring: signal queued with **anti-front-running delay**, sized `fund_capital/trader_capital`, submitted via executor API with slippage protection, per-position P&L attribution. Unit tests present (`FundPositionMirrorTest`, `IndexWeightProviderTest`, etc.). Conceptually = Xman's PMA copy sleeve already in production.

### 2.7 What is NOT verified / not present
- **No ML artifacts**: `ml/checkpoints/` does not exist; committed `.pkl` files (`models/anomaly_detector.pkl`, `models/strategy_dna.pkl`) with no reproducible regeneration story visible in the clone; `run_all.py` ML path falls back to rules whenever the ensemble fails to load. The "ML ensemble scoring" headline is unbacked in-repo.
- `strategy_dna.py` **placeholder scaffold**: `avg_hold_hours: 24 # Would calculate`, `active_hours: [9,10,11,14,15,16] # Placeholder`, `win_streak_tendency: 0.5 # Placeholder` (L214-217); classifier comments admit proxies; clustering = group-by-holding-style (L393-427).

---

## 3. Fit table vs Xman stack

| Component | Verdict | Rationale |
|---|---|---|
| **Edge-decay flag layer** (pooled-z on win rate + Welch's t on windowed returns + sample-confidence gates; `edge_decay.py`) | ✅ **ADOPT (formula-level, reimplement in TS)** | Verified stats; directly serves flag-revertible regime: statistically-grounded "trader edge decaying → flag" monitor for mirrored wallets and Kelly measurement. MIT-ok w/ attribution. Fix small-df bug on port. |
| **Replicability taxonomy + PSI eligibility/constraint framework** (`psi_index.py` NON_REPLICABLE_STRATEGIES, floors, caps) | ⚪ **CONCEPT-ONLY** | Xman already mirrors; the portable idea is the *latency-strategy exclusion gate* + index-style constraints applied to the PMA mirror universe. Design reference, not code transfer. |
| **Smart Money Score rubric** (`scoring_job.py`) | ⚪ **CONCEPT-ONLY** | Deterministic & transparent, but overlaps Xman wallet-quality scoring and embeds double-counted features + size-averse "risk" proxy. Harvest the tiering idea, not the weights. |
| **Sharpe-on-realized-daily-P&L, √365, cap-10, sample-confidence** (`sharpe_calculator.py`) | ⚪ **CONCEPT-ONLY** | Standard math, likely already covered; the sample-confidence discounting is the only transferable nuance. |
| **Insider/early-signal heuristics** (new-account whales, volume spikes, smart-money divergence, coordinated entries — `insider_detector.py`) | ⚪ **CONCEPT-ONLY** | Tape-side early-warning layer Xman could cheaply reimplement over its own data; not validated by any backtest in-repo. |
| **Consensus strength** (`consensus.py`) | ⚪ **CONCEPT-ONLY** | Heuristic agreement vote; v39 Bayesian engine is strictly stronger. Could inform one evidence input ("smart-money vote") — minor. |
| **ML scoring ensemble + drift/retrain stack** | ❌ **NOT PORTABLE** | No trained artifacts; generic supervised pipeline duplicating Xman's local-LLM/evidence approach. |
| **Strategy DNA fingerprinting** (`strategy_dna.py`) | ❌ **NOT PORTABLE** | Placeholder scaffold; nothing real to port. |
| **Fund product layer** (NAV, deposits, web, API) | ❌ **NOT PORTABLE** | Paper-only mandate; custody/NAV product not in scope. |
| **Java services / ClickHouse DDL cascade** | ❌ **NOT PORTABLE** | Wrong runtime (TS/Rust); wholesale infra out of scope. |
| **Gabagool22 maker-clone research** (`research/`, `GabagoolDirectionalEngine.java`) | ❌ **NOT PORTABLE** | One-target reverse-engineering of a single BTC-up/down maker; a separate business from Xman; PMA tape already covers mirroring. |

---

## 4. Integration proposal (effort / risk / flag-revertible)

All subject to **pre-Oct-8 freeze: recommendations only, no ships, flag-revertible** (Kelly measurement window).

1. **Edge-decay flag monitor (TS port)** — implement pooled two-proportion z on rolling win-rate windows and Welch's t on windowed returns per mirrored wallet; emit recommendation-only decay flags alongside Kelly recommendations through Oct 8; ship after window close if it earns a roadmap card. Effort: ~1-2 days (stats are 3 functions; fix `t_to_pvalue` → proper t-CDF or raise flag threshold at small n; replace misnamed bootstrap with honest normal-approx CI). Risk: **low**; pure flag layer, zero order-path interaction. MIT attribution note in header.
2. **Replicability gate on PMA mirror universe** — classification buckets (latency-sensitive: arb/MM/scalper vs directional/event-driven) feeding existing mirror filters. Effort: small config + classifier if not present. Risk: low-medium (misclassification could exclude good wallets — flag-only first). 
3. *(Optional, post-freeze)* rubric-style quality score rework + tiering for wallet reports.

Verdict timing: anything adopted lands **after Oct 8**; between now and then only the decay-flag prototype as a **recommendation-only** research lane.

---

## 5. NOT-portable list (explicit)

- All Java microservices (`polybot-core`, executor/strategy/ingestor/analytics `-service`), Spring/ClickHouse coupling.
- ClickHouse schema cascade (`analytics-service/clickhouse/init/*.sql`) — concepts only.
- ML ensemble + drift/auto-retrain (`ml/training/*`, `ml/monitoring/*`) — no artifacts, duplicated capability.
- Strategy DNA classifier (`strategy_dna.py`) — placeholder scaffold.
- NAV/custody/invest product (deposits, withdrawals, fund tiers) + Next.js dashboard + FastAPI.
- Gabagool22 reverse-engineering corpus & clone — one-off, separate project.
- Notifications (Discord/Telegram/webhook) — Xman has own routing.

---

## 6. Honest caveats

1. **Dormant 6.5 months** (last push 2026-02-21), 56 stars, single-owner product, fund never publicly launched (custody pending per README). No live track record to validate the Smart-Money premise.
2. **"Operational" claim > evidence**: README claims scoring/index stack operational, but index criteria were bootstrap-relaxed to near-zero floors (min 5 trades / 1 day / $500 / Sharpe 0), and no ML ensemble artifacts exist — scoring is de facto the rule-based rubric.
3. **Scaffold patches inside otherwise-real code**: `strategy_dna.py` placeholders; fake drawdown proxy; mislabeled "bootstrap" CI; small-df t→p bug (wrong direction, anti-conservative).
4. **No backtests of the actual product premise** (does following top *replicable* traders win?) in-repo — only the gabagool single-target research, which is a different question.
5. **Rubric design flaws** (double-counted features; size-averse risk proxy) mean scores rank *consistent mid-size traders* above *large sophisticated whales* — wrong shape for a mirror sleeve without rework.
6. Repository is a private-dev dump of three projects; docs (VISION/ACTION_PLAN/DESIGN_DECISIONS/ML_AI_STRATEGY) overstate product completeness relative to code state.

---

## Verdict: **QUEUE (concept harvest) — not adopt-now**

MIT-clean and borrowable, but Xman already owns the mirror sleeve, and the repo's genuinely novel, *verified* deterministic asset is small: the edge-decay statistical layer (correct z/Welch machinery, port + fix), plus two design ideas (replicability gates, rubric tiering). Under the Sep 8–Oct 8 Kelly freeze nothing ships anyway, so the correct move is: implement the decay-flag monitor as a recommendation-only prototype (TS, ~1-2 days, low risk, flag-revertible), note it for post-freeze evaluation against the roadmap, and skip the Python/Java/ClickHouse stack, ML layer, and fund product entirely.
