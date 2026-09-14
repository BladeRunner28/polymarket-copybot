# Scoring / Ranking Machinery Repos — Deep Audit (license-first, source-verified)

**Date:** 2026-09-13 · **Auditor:** subagent deep-audit (`github-repo-audit` procedure)
**Purpose:** Find scoring/ranking machinery in the wild that could **replace or repair** the CopyBot trade score, which has *no measured predictive power* on the stack's own 9,600 trades (all PnL bands negative; win/loss feature profiles identical).
**Method:** 55 GitHub search-API queries (30 repo + 25 repo + 9 code search) → **1,145 unique repos** (579 round-1 + 482 round-2 + 219 code-search hits, deduped) → 58 shortlist metadata fetches → **37 shallow-cloned and read line-by-line**. **Marketing READMEs were not trusted; every formula below is quoted from a file the clone contains.**

**Scope note (capability gap proved in OUR repo first, not assumed):** the adopting stack already ships `src/lib/scoring/trade.ts` (hand-weighted 6-part: walletQuality·0.30 + categoryWinRate + entryTiming·0.20 + spread·0.10 + liquidity·0.15 + thesis·0.10), `src/lib/insider.ts` (an *11-component* weighted wallet score that **already includes a Brier term** at 0.12 weight), and `scripts/pilot-score-separation.py` (grouped-CV pilot comparing the hand-weighted composite vs a price-only baseline vs a ridge-logistic refit, with out-of-fold excess-return-by-decile). So the real gaps are **not** "no score" or "no validation harness" — they are: **(1) no sample-size shrinkage / empirical-Bayes estimator, (2) no pool-wise rank normalisation, (3) no calibration-vs-baseline *skill* factor wired as a ranking input, (4) no explicit anti-gaming / coverage / one-hit gates, (5) no versioned-score A/B cutover rule.** This audit targets those five.

---

## 0. Verdict summary table

| # | Repo | License | Genuine scoring machinery in source? | Predictive power shown? | Fit |
|---|---|---|---|---|---|
| 1 | **nexiumito/polycopy** | MIT | **Yes — 7-factor wallet score (Brier-skill, Sortino/Calmar, HHI, zombies, discipline) + hard gates + pool rank-normalisation + versioned scoring + Brier/Spearman A/B cutover harness** | No shipped OOS numbers (harness needs labels) | ✅ **adopt concepts; vendor-able** |
| 2 | **seer-pm/demo** (`traderScore.ts`) | MIT | **Yes — production trader score: symmetric n/(n+K) shrinkage to neutral, Laplace hit-rate prior, hit-rate vs OWN break-even odds, PF prior, coverage gate, sufficient-statistics merge** | Calibrated bands claimed; no raw OOS study shipped | ✅ **adopt shrinkage + headline metrics** |
| 3 | **AntoineROYERB/polymarketpricer** | MIT | **Yes — edge-vs-resolution (FIFO buy→sell match), follow score: edge 0.30 + consistency 0.20 + specialization 0.20 + recency 0.15 + frequency 0.15; per-category variant; 3MB sample DB committed** | None demonstrated | ✅ adopt edge-vs-resolution + per-category structure |
| 4 | **pselamy/polymarket-insider-tracker** | MIT | **Yes — composite risk scorer, versioned+persisted config per record, multi-signal bonus, threshold *calibrated against cost-adjusted follower PnL*** | **Yes (negative finding):** threshold raised 0.60→0.80 because sub-0.85 signals were follower-PnL-negative after fees+slippage | ✅ **adopt replay-able versioned config + cost-adjusted threshold discipline** |
| 5 | **Gurdiel07/polymarket-bot** | MIT | **Yes — wallet scoreboard by mean signed drift @24h, min-sample gate, prune candidates, 7-day forward test (expected-vs-observed)** | None demonstrated (framework only) | ⚪ concept (scoreboard + forward-test loop) |
| 6 | **tmk11/PolymarketWalletScan** | NONE | **Yes — "skill vs luck": edge = mean(outcome − price), bootstrap CI, one-hit-wonder, HHI/Gini, win-rate-padding & metric-gaming flags** | None demonstrated | ⚪ concept-only (no license) |
| 7 | **DavidSMazur/gnosicular** (`informed_trader_index`) | NONE | **Yes — signed informedness = (0.70·edge + 0.30·(2·hit−1)) · n/(n+prior_strength); market index = size^0.5-weighted; half-Kelly sizing; tuned profiles** | None shipped (search scripts only) | ⚪ concept-only — **the closest math to the ask** |
| 8 | **JamesFletty/maths** | NONE | **Yes — explicit baseline suite (random/top-pnl/top-roi/most-active/category-specialist/no-signal), walk-forward split, latency-stress edge @0/30/120/600 s, leakage checks, promote gate** | Harness only | ⚪ concept-only — **best validation-harness template** |
| 9 | **childersjac-max/Line-Tracker-Model** (sports) | NONE | **Yes — prob_shrinkage_alpha·model + (1−α)·no-vig fair; CLV model; SHARP_MONEY signal class** | **Yes — own backtest (914 bets): SHARP_MONEY 17 bets, 47.1% hit, ROI −2.80%; CLV_MODEL +1.36%** | ⚪ concept — shrinkage blend + honest negative evidence |
| 10 | **mateogon/hermes-polymarket-clob2-agent** | NONE | **Yes — overfit_checks (small_sample/too_many_experiments/category_concentration/out_of_sample_degradation) + FOK copyability sim + cents-worse & latency gates** | Guardrails only | ⚪ concept-only (overfit overlay) |
| 11 | **jt8530-beep/weather** (`wallet_alpha_radar`) | NONE | **Yes — alpha-decay probe (post-trade book moves at T+delay), category profiler, hedge-ratio & high-entry gates** | Probes only, self-labeled "not a signal" | ⚪ concept (alpha-decay measurement) |
| 12 | **darrnhard/polymarket-smart-money** | NONE | Partial — lead/lag hierarchy measurement, burst windows, overlap-conviction tiers | **Yes (behavioural):** all 3 "top" wallets are bots; leader/laggard measured; "do not copy rn1" | ⚪ concept-only |
| 13 | **Cachaza/polymarket-scanner** | NONE | Yes — 4-component market score (price anomaly, holder concentration Δ, wallet quality, taker flow) + backtest module | None | ⚪ concept (component set) |
| 14 | **meta-xucong/POLY_SMARTMONEY** | NONE | Yes — config-weighted copy_score over rich copyability features (burstiness, interval_median, near_expiry_ratio, recent_surge, suspected_hft) | None | ⚪ concept (feature list only) |
| 15 | **tshore2004/polymarket-trader** | NONE | **Yes — `calibrate_weights.py`: logistic-regression + grid-search + bootstrap-CI weight optimiser, Brier before/after; Pinnacle/odds fair-value anchor** | Tool only | ⚪ concept — **the "repair the weights" recipe** |
| 16 | **samuraifrenchienft/Prediction-Agent** | NONE | Yes — XGBoost shadow scorer, Platt calibration (Brier<0.25 gate), phased rollout, smart-money consensus features | None (Phases gated on 400/800 labels) | ⚪ concept (calibration gate pattern) |
| 17 | **feecrookz-bit/basement-archive** | NONE | Yes — cadence classifier (bot/accumulator) pinning bot weight to 0.25 floor | **Yes (negative):** Solana PnL leaderboards are HFT bots; followers are exit liquidity | ⚪ concept (bot-mute gate) |
| 18 | **Ksmith18skc/SignalForge** | NONE | Yes — 5-part weighted score (wallet 35 / consensus 25 / liquidity 15 / timing 15 / inefficiency 10) | None | ❌ hand-weighted, **same failure mode as our score** |
| 19 | **seer-pm** (rest of repo) | MIT | n/a — AMM/PSM pricing, not wallet ranking | n/a | ❌ not-portable |
| 20 | **chainstacklabs/polymarket-alpha-bot** | Apache-2.0 | No wallet score — LLM cross-market arb-pair detector | None | ❌ not-portable (LLM layer; duplicates oracle3 coinjure) |
| 21 | **manifoldmarkets/market-maker** | MIT | No — EMA/EM-variance quoting bot | n/a | ❌ not-portable (not ranking) |
| 22 | **al1enjesus/polymarket-whales** | MIT | **No scoring** — $ threshold alert CLI (+ Telegram funnel) | n/a | ❌ hype/alert-only |
| 23 | **yorkeccak/Polyseer** | NONE | No scoring (LLM agent) | n/a | ❌ already audited (Aug-31) |
| 24 | **caiovicentino/polymarket-mcp-server** | MIT | No scoring; **2 of 45 tools are stubs** (already audited) | n/a | ❌ already audited |
| 25 | **YichengYang-Ethan/oracle3** | Apache-2.0 | Scoring **beyond WangMLE** = `ModelInformedSizer` (Kelly gates) only; no wallet/cluster ranking | Wang λ̂ MLE (paper N=13,274) | ✅ WangMLE already vendored; see §oracle3 |
| 26 | **evan-kolberg/prediction-market-backtesting** | NOASSERTION | Backtesting framework (NautilusTrader), not a scorer | n/a | ❌ read-only (no license grant) |
| 27 | **vobornij, Marzel7/flex, winder87, Timaroc13, dexoryn*, suislanchez, Abomination81/copybot, etc.** | mixed/NONE | No verifiable predictive scoring found | none | ❌ skip |

---

## 1. Primary candidates (deep source verification)

### 1.1 nexiumito/polycopy — **MIT** — the single best architectural match

**What it is.** A solo-dev Polymarket copy-trading stack (Python, 281 code files, 56 k LOC) whose `discovery/` layer is a full wallet-scoring engine: `scoring/v1.py`, `scoring/v2/{aggregator,dtos,normalization,gates,pool_context,factors/*}.py`, a `metrics_collector_v2.py` that computes the 12 v2 metrics, and two backtest scripts. Docs (`docs/specs/M5-trader-scoring.md`, `docs/deepsearch/*`) show an explicit versioned spec process.

**License verdict.** MIT → borrowable with attribution. No AGPL/GPL anywhere in the scoring path. Deterministic pure functions, stdlib + pydantic + structlog; trivially portable to Node/TS or Python.

**Verified scoring machinery (from source).**
- **7 raw factors** (`factors/`):
  - `calibration` = **Brier-skill `1 − brier_wallet / brier_baseline_pool`**, wallet Brier = `mean((outcome − avg_price)²)` over resolved positions; baseline = pool-average wallet, fallback 0.25. Cites Gneiting-Raftery (<0.22 skill, <0.15 expert). (`factors/calibration.py`)
  - `risk_adjusted` = `median(Sortino, Calmar)` with a **minimum-variance floor `pstdev > 1e-3`, else 0.0** — explicitly to stop "scoring absence-of-evidence as evidence of skill". (`factors/risk_adjusted.py`)
  - `specialization` = **HHI over Gamma categories (sign flipped to *reward* concentration)**, citing Mitts & Ofir 2026 on Polymarket insider wallets. (`factors/specialization.py`)
  - `discipline` = `(1 − zombie_ratio) × (1 − min(1, sizing_cv))`; `consistency` = fraction of positive months; `timing_alpha` (later zeroed); `internal_pnl` = sigmoid of realised copy-PnL.
- **Aggregation** = fixed weights, explicitly **renormalised after dropping a dead factor**: `timing_alpha` went `0.20 → 0.0` with the stated justification (audit H-008, citing adaptive-lasso: *"uninformative factors with non-zero weight monotonically degrade out-of-sample estimation error"*). Weights are asserted to sum to 1.0 at import (`raise ImportError` otherwise). (`aggregator.py`)
- **Pool normalisation** = **rank transform `rank/N` with average-tie interpolation**, chosen over p5-p95 winsorisation because "winsor assumes symmetry + N≥20; our pool is right-skewed survivors, N=13". Explicitly fixes a "fixed-point trap" where a wallet was locked at 0.45 for 80 cycles. (`normalization.py`)
- **Hard gates (fail-fast, pre-scoring)** with per-gate audit rows: `cash_pnl_positive`, `trade_count_min` (50, or 20 cold-start), `days_active_min` (30/7), `zombie_ratio_max` (0.40), `not_blacklisted`, `not_wash_cluster`, `not_arbitrage_bot` (`net_exposure_ratio ≥ 0.10`). Every gate returns `observed_value`, `threshold`, `reason`. (`gates.py`)
- **Versioned scoring**: `SCORING_VERSION` is append-only; historical `trader_scores` rows are never rewritten. `metrics_collector_v2` computes `brier_90d` on resolved positions + `zombie_ratio`.
- **A/B cutover harness** (`scripts/backtest_scoring_v2.py`, offline fixtures): scores each labelled wallet with v1 and v2, reports **Brier aggregate over each version's top-10 promoted wallets**, **Spearman rank correlation** v1↔v2, and a machine verdict — **`brier_v2 < brier_v1 − 0.01` ⇒ go cutover, else stay v1`** (exit code 2 = not recommended).

**Predictive-power evidence.** **None shipped.** The harness requires operator-supplied `assets/scoring_v2_labels.csv` (`smart_money` / `random`) + fixtures; no results file is committed. The *individual* factors have cited literature (Brier, Sortino, Mitts-Ofir HHI), but the composite's OOS power is unproven in-repo. Treat the factors as hypotheses with a ready-made test rig, not as validated signal.

**Fit table.**
| Component | Verdict | Effort / risk |
|---|---|---|
| Brier-skill calibration factor (vs pool baseline) as a *ranking* input | ✅ **adopt** — the stack has a `brier` term in `insider.ts` but **not** a pool-baseline skill ratio; deterministic, ~40 LOC TS | ~0.5 d, LOW, flag-revertible |
| Rank-transform pool normalisation of sub-scores | ✅ **adopt** — replaces raw-linear inputs; ~30 LOC; directly addresses "bands all negative" (rank gives monotone spread) | ~0.5 d, LOW |
| Hard-gate suite with persisted `observed/threshold/reason` | ✅ **adopt** — mirrors existing `hardSkips` in `trade.ts`; add audit columns so a rejection is replayable | ~0.5 d, LOW |
| **Versioned scoring + Brier/Spearman cutover rule** | ✅ **adopt** — this is the missing decision rule for any score change; ~1 d (harness) | ~1 d, LOW |
| Minimum-variance floor on any Sharpe/Sortino component | ✅ adopt (guards zombie/whale-holder wallets) | small |
| `zombie_ratio`, `sizing_cv` discipline factor | ⚪ concept — needs a position-age/initial-value model in our data | medium |
| The fixed hand-weights themselves | ⚪ concept — evidence-based but still hand-set; feed `tshore`'s optimiser instead (§1.15) | — |

---

### 1.2 seer-pm/demo — `web/netlify/functions/utils/traderScore.ts` — **MIT** — the shrinkage the stack lacks

**What it is.** A deployed prediction-market app (Seer, Gnosis lineage); the one file that matters is a **production trader score** with an unusually rigorous design doc in the file header.

**License verdict.** MIT → borrowable. The math is ~200 lines of pure TS — **directly portable, not even a reimplementation.**

**Verified scoring machinery (from source).**
- 5 components, weights `returns 25 · profitFactor 30 · hitRate 15 · lossBurn 15 · breadth 15`.
- **`hitRate` scored against the wallet's OWN break-even odds, not a fixed band** (`HIT_EDGE_FLOOR −0.10`, `HIT_EDGE_CEIL 0.15`). Stated rationale: *"A prediction market pays out inversely to the price paid, so 'won 30% of markets' is excellent at 4:1 average odds and ruinous at 1:2. The fixed 35% floor this replaced assumed even money and zeroed every long-shot strategy by construction — a real wallet with a 4.94 profit factor scored 0 on it."*
- **`SAMPLE_SHRINK_K = 10, NEUTRAL_SCORE = 50`** — *"The weighted mean keeps `n/(n+K)` of its distance from neutral, so n=3 keeps 23% and n=98 keeps 91%. Symmetrically: too little evidence reads undecided, in both directions, rather than excellent."* → this is exactly the empirical-Bayes shrinkage that is missing from our hand-weighted score, and it kills the "3-market wallet tops the board" failure.
- **Laplace prior on hit rate** `HIT_PRIOR_P=0.5, HIT_PRIOR_N=5` ("stops 1-for-1 reading 1.0"); **symmetric prior on profit factor** `PF_PRIOR_FRACTION=0.02` of gross flow (the header documents fixing a prior that was "a sample-size penalty in disguise" costing a real 4.94-PF wallet ~8 points).
- **Coverage honesty gate**: `MAX_UNSCORED_PNL_FRACTION = 0.25` → when the scored markets don't explain the wallet's P/L, the score is **`null` with `reason:"coverage"`** ("A dash is the honest answer; the alternative is a confident number about markets we cannot see").
- **Sufficient-statistics design** (`scoredMarketCount, winningMarketCount, grossProfit, grossLoss, bestMarketPnl, scoredCapital, pnlUsd`) so rows merge with `+` / `Math.max` along executor/owner/chain axes — the score is derived once from merged totals, and a `method` field lets a future daily-series implementation coexist.
- `market`-scoring dust gate `MARKET_SCORE_DUST_USD = 1`, eligibility gates `MIN_SCORED_MARKETS 3`, `MIN_CAPITAL_USD 100` → **`null` before it is ever a misleading low number.**

**Predictive-power evidence.** The header says bands are "calibrated against a reference" and cites live-board fixes; **no OOS study is committed.** Its tier thresholds (Elite ≥85 …) are presentational. So: high design discipline, **no demonstrated predictive power**.

**Fit table.** All ✅ adopt, all near-portable:
| Component | Verdict | Effort / risk |
|---|---|---|
| **Symmetric shrinkage `score = 50 + (raw−50)·n/(n+K)`** on our composite | ✅ **adopt (highest-value single change)** — 5 LOC; makes low-sample wallets read *undecided*, not *excellent*; flag-revertible | ~2 h, LOW |
| **Hit-rate measured vs wallet's own break-even odds** (replace `categoryWinRate` raw) | ✅ adopt — ~20 LOC, deterministic | ~2 h, LOW |
| Laplace / flow-scaled priors on hit-rate & profit-factor | ✅ adopt | small |
| Coverage gate (`null` when unscored P/L fraction > 0.25) | ✅ adopt — honesty gate; our DB can compute it | small |
| Sufficient-statistics + `method` field | ⚪ concept (our SQLite schema differs) | medium |

---

### 1.3 pselamy/polymarket-insider-tracker — **MIT** — the calibration-discipline winner

**What it is.** Python insider/anomaly detector for Polymarket: detectors `fresh_wallet`, `size_anomaly`, `niche_market`, `sniper` → a composite `RiskScorer` with weighted aggregation, dedup window, and an alert threshold.

**License verdict.** MIT → borrowable. 119 code files, real tests (`tests/integration/test_end_to_end.py` etc.).

**Verified scoring machinery (from source, `detector/scorer.py`).**
- Weights `fresh_wallet 0.40 · size_anomaly 0.35 · niche_market 0.25`; multi-signal bonuses `1.2` (2 signals) / `1.3` (3+); scores quantised to `NUMERIC(4,3)` so a **stored record replays its exact decision** even after weights change.
- **Versioned + self-describing records**: every assessment stores `scoring_algorithm_version` and the exact active `scoring_config`; changing a default, a bonus, or a combination rule *requires* bumping the version. Deprecated weights API still records per-assessment so old rows stay replayable.
- **Threshold calibrated against cost-adjusted follower PnL** — quoted verbatim from the file: *"The threshold lifted from 0.6 to 0.80 after the first cost-adjusted backtest showed everything below 0.85 was follower-PnL negative under realistic taker fees + half-cent slippage. 0.80 keeps a small margin below 0.85+ so we don't drop borderline-high signals on a hard cliff."*

**Predictive-power evidence.** **Yes — a genuine (negative) finding**: the repo documents its own cost-adjusted backtest and raises the threshold accordingly. This is the strongest evidence tier in the whole audit for *how to calibrate a gate to net-of-cost follower PnL* — the exact discipline our stack's "score has no predictive power" problem calls for. (Absolute numbers aren't published; only the direction + the 0.85 crossover.)

**Fit table.**
| Component | Verdict | Effort / risk |
|---|---|---|
| **Cost-adjusted threshold calibration** (find the score cut where net-of-fees follower PnL turns positive; set the gate with a margin below the cliff) | ✅ **adopt** — this *is* the repair for a non-predictive score: it converts the score into a conservative admission gate | ~1–2 d analysis, LOW risk (read-only until a flag flips) |
| Versioned + persisted `scoring_config` per decision | ✅ adopt — enables true replay/rollback of score changes | ~0.5 d |
| Multi-signal bonus / dedup window semantics | ⚪ concept (sidecar already has a gate suite — verify before copying) | — |
| Anomaly detectors themselves | ❌ not-portable — duplicates our existing wallet layer + `insider.ts` | — |

---

### 1.4 AntoineROYERB/polymarketpricer ("Edge Terminal") — **MIT** — edge-vs-resolution done cleanly

**What it is.** FastAPI + Next.js + Mage-AI Polymarket smart-money tracker: "ranks wallets by measured predictive skill, tracks niches, streams alerts, paper-trades the copy." **A 3 MB sampled production DB is committed** (200 wallets, 24k trades, 1.3k markets, derived analytics tables), so the scoring is inspectable offline.

**License verdict.** MIT → borrowable. Score logic is pure pandas/Decimal (ETL) + one async service.

**Verified scoring machinery (from source).**
- **Edge vs resolution** (`transformers/compute_trade_edge.py`): FIFO-match each BUY to the next SELL, else to the **resolution price** (`1.0` winner / `0.0` loser); `edge = (edge_price − entry_price)/entry_price`; per-wallet `avg_edge`, `median_edge`, `edge_consistency = positives/n`, `edge_volatility`, and `edge_score = (avg_edge − min_edge)/edge_range` (pool min-max normalisation).
- **Follow score** (`services/follow_scoring.py` + `scoring_constants.py`): `0.30·edge + 0.20·consistency + 0.20·specialization + 0.15·recency + 0.15·frequency`; per-category variant `0.25 edge + 0.25 roi_pct + 0.20 win_rate + 0.15 specialist_bonus + 0.10 volume_pct + 0.05 recency`; **recency decay `e^(−days/90)`**; **frequency sigmoid** (slope 0.1, midpoint 10 trades/month); specialist bonus 1.0 vs 0.5; thresholds `FOLLOW ≥0.70 / WATCH ≥0.35`.
- Migrations show the score evolving (`017_add_edge_scoring`, `010_add_wallet_tier`, `013_fix_min_score_default`).

**Predictive-power evidence.** **None demonstrated** — no OOS/backtest result committed. It is a hand-weighted composite (same family as ours), but its `edge = beating the resolution price` is the cleanest label and it already ships per-category scores.

**Fit table.** Sourcing `edge vs resolution` into our `walletQuality` sub-score ✅ adopt (~0.5 d); symmetric edge_score min-max normalisation ⚪ concept (rank transform is more robust — prefer §1.1); follow-score weights ⚪ concept (do not copy weights, feed the optimiser in §1.15); the committed sample DB ⚪ useful as a *fixture* for a cross-repo score sanity check, not for predictive evidence.

---

### 1.5 JamesFletty/maths — **NONE (all rights reserved)** — the best validation-harness template

**What it is.** A small Python `polymarket_bot` (2.6 k LOC) whose `wallets/validation/` package is a complete **wallet-signal validation harness** — small but the most methodologically pointed code in the audit.

**License verdict.** **No LICENSE file → all-rights-reserved. Read-only: copy NOTHING; reimplement concepts.** (Precedent: the Polyseer audit flagged exactly this.)

**Verified machinery (from source).**
- `validation/baselines.py`: explicit **baseline suite** — `random_wallet` (seeded), `top_raw_pnl`, `top_roi`, `most_active`, `category_specialist`, plus zero-value `market_prior_only`, `momentum`, `no_wallet_signal`. (This is the "is the score better than doing nothing / better than the leaderboard?" test our stack needs.)
- `validation/metrics.py`: **latency stress** — mean edge in **bps** at latency `0s/30s/120s/600s` vs a forward 30-min price, then `edge_after_spread`, `edge_after_slippage`, `edge_after_crowding` (subtracts 2/2/1 bps). Plus `precision_positive`, `false_positive_rate`, `drawdown_contrib`, `unavailable_row_rate`.
- `validation/leakage.py`: raises on `future_trades_in_score` and `realized_before_resolution` — **explicit look-ahead leakage checks** (directly relevant: is our score contaminated, or our labels?).
- `validation/harness.py`: `walk_forward_split`, baseline comparison, `promote_policy(metrics, leakage_ok, min_samples, …)` → `{mode, reasons}` — a **promotion gate**, i.e. "may this score go live?".
- `wallets/scoring.py`: `score = (liq_adj_return·100 + ambiguity_adj_return·100 + sharpe_like·10) · min(1, resolved/25)`; `confidence = 0.2 + 0.8·sample_factor` — a *crude* first-order shrink, superseded by §1.2's `n/(n+K)`.
- **Wart worth noting:** `baselines._ret()` has an operator-precedence bug (`a or b if c else d`) that can silently change the baseline return — evidence the repo is early-stage, not battle-tested.

**Predictive-power evidence.** Harness only — **no results committed**. Its value is the *method*: baselines + walk-forward + latency stress + leakage check + promotion gate.

**Fit table.** All ⚪ concept (no license):
| Component | Effort / risk |
|---|---|
| Baseline suite (random / top-pnl / top-roi / most-active / category-specialist / no-signal) around `pilot-score-separation.py` | ~0.5 d, LOW — **highest-value addition to our existing pilot** |
| Latency-stress edge (0/30/120/600 s) after spread+slippage+crowding | ~0.5 d, LOW — quantifies copy-trade decay |
| Leakage checks (future trades in score; realised before resolution) | ~2 h — **verify our labels before trusting any "no predictive power" verdict** (cf. `drafts/resolution-label-bug-plan.md`) |
| Promotion gate `{mode, reasons}` | ~0.5 d |

---

### 1.6 DavidSMazur/gnosicular — `informed_trader_index` — **NONE** — the math closest to the ask

**What it is.** A prediction-market agent repo (417 files, 143 k LOC, Jupyter+Python). The relevant module is `agents/rome_agent/informed_trader_index/strategy.py`: an **informed-trader index** strategy with parameter-search scripts.

**License verdict.** **No LICENSE → read-only; reimplement the math only.** Pure-Python, no exotic deps for the scoring path — the formula is a direct reimplementation target.

**Verified machinery (from source) — this is the empirical-Bayes estimator the stack is missing:**
- **Per-trader signed informedness with shrinkage:**
  `raw = 0.70·mean_edge + 0.30·(2·hit_rate − 1)`; **`score = raw · n_trades/(n_trades + prior_strength)`**, clipped to [−1, 1]. Default `prior_strength = 5.0`; tuned profiles `1.565` (stress_hardened) and `3.433` (leaderboard).
- **Learning weight** on each settled trade = `sqrt(collateral)` ("conservative size weighting to avoid whales dominating"), and `mean_edge` is that weighted mean.
- **Market index** over current trades: `w = |score| · conviction · size_weight`, with `conviction = clamp(1−entry_p or entry_p, floor, 1)` and `size_weight = sqrt(collateral)`; `signal = Σ(direction·score·conviction·size)/Σw`; **`p_yes_index = 0.5 + 0.5·signal`**; `confidence = clamp(weight_mass/(weight_mass+6), 0.05, 0.98)`.
- **Abstention filters** (the value *is* that it refuses to trade): `min_market_trades`, `min_weight_mass`, `min_scored_traders`, `min_settled_markets_to_trade`, `conviction_floor`, `min_edge_to_trade`.
- **Half-Kelly sizing** matched to binary shares (`(q−p)/(1−p)` YES, `(p−q)/p` NO).

**Predictive-power evidence.** **None shipped.** The repo contains parameter-**search** scripts (`scripts/search_profitable_strategy.py`, `continue_informed_search.py`) and tuned profiles — a tuned-but-unreported result, i.e. possibly overfit. Per the audit rule ("backfilled-track-record suspicion"), do **not** treat the tuned profiles as validated.

**Fit table.** ✅ **adopt the shrinkage estimator** `raw·n/(n+prior)` as a *drop-in replacement* for the raw `categoryWinRate` / wallet-quality inputs (~30 LOC, deterministic, ~2 h — this is the single most on-point transferable component from the whole audit); ⚪ concept: the size^0.5 weighting, conviction weighting, and the abstention-filter set (align with our existing hardSkips); half-Kelly already covered by Phase B.

---

### 1.7 tmk11/PolymarketWalletScan — **NONE** — best "skill vs luck" discriminator + anti-gaming

**What it is.** A standalone wallet analyzer (12 files) whose `skill_score.py` + `analyzer.py` answer *"is this wallet skilled or lucky?"* with a transparent 0–100 score and a per-component breakdown.

**License verdict.** **No LICENSE → read-only; reimplement concepts.** stdlib-only ("uses only the Python standard library") → very portable.

**Verified machinery (from source).**
- Component weights: `significance 25 · edge 20 · consistency 15 · breadth 15 · concentration 15 · risk 10` (renormalised when a component is unavailable).
- **`edge_per_share = mean(outcome − entry_price)`** (share-weighted variant) — the file states: *"did the wallet buy outcomes that were underpriced relative to how they actually resolved? This is the cleanest skill signal in a prediction market, because beating the price is what an edge **is**."*
- **Bootstrap CI on per-market ROI** (2,000 resamples, fixed seed 1_234_567) → `significant = ci_low > 0`; plus `t_stat`.
- **One-hit-wonder / tail-risk control**: `top1_contribution` & `top3_contribution` of net PnL, `roi_ex_top1/top3`, **HHI and Gini** of profits, `largest_loss_to_median_win`.
- **Metric-gaming flags** (the part nobody else ships): `win_rate_padding_suspected` (many tiny "wins" that don't cover losses, via `low_value_win_max_pnl/roi`, `meaningful_market_win_rate`, `win_rate_quality_gap`), `small_bet_roi_padding_suspected`, `correlated_cluster_suspected`, `tail_risk_suspected`, `unrealized_pnl_dominance_suspected`, `reward_dependency_suspected`, `recent_performance_divergence_suspected` — each with a `*_skill_score_cap` (e.g. `metric_gaming_skill_score_cap 65`, `recent_copy_risk_high_skill_score_cap 55`).
- **Verdict taxonomy**: `skilled / lucky_or_one_hit_wonder / inconclusive / unprofitable / insufficient_data`, with hard gates (`total_markets ≥ 30`, `roi_ex_top1 > 0`, `meaningful_win_rate > 0.50`, `top1_contribution < 0.40`), and `effective_bets` = independent decisions grouped by event.

**Predictive-power evidence.** **None demonstrated** (no backtest results in-repo). It is a *diagnostic classifier*, not a proven predictor — but its anti-gaming flags are exactly the sanity layer a score needs before it can be trusted at all.

**Fit table.** ⚪ concept-only (no license): **`edge = mean(outcome − price)`** → adopt same as §1.6 (overlaps §1.3); **bootstrap-CI significance component** ~0.5 d; **one-hit-wonder / concentration-excl + gaming flags** ~1 d — high value, directly attacks "our score ranks lucky wallets"; `effective_bets` (event-grouped) ⚪ concept.

---

### 1.8 childersjac-max/Line-Tracker-Model (sports) — **NONE** — shrinkage blend + honest negative evidence

**What it is.** A sports line-movement model with a **committed backtest output** (`pipeline_output/backtest_metrics.json`) and `models/scorer.py`.

**License verdict.** **No LICENSE → read-only, concepts only.**

**Verified machinery (from source).**
- **Probability shrinkage**: `sized_prob = α·model_prob + (1−α)·fair_prob`, with `fair_prob` = **no-vig fair probability**, `PROB_SHRINKAGE_ALPHA = 0.5` (`configs/config.py`, `models/scorer.py`). Shrinks the model toward the de-vigged market — a clean, portable blend.
- Signals: `CLV_MODEL` (closing-line-value model) and **`SHARP_MONEY`**; OddsJam pre-computed arb feed as an extra feature.

**Predictive-power evidence — the rare honest one.** `backtest_metrics.json` (verbatim): `n_bets 914, hit_rate 0.444, roi_pct 1.298, sharpe 0.154, profit_factor 1.023, max_drawdown_pct −46.4`; **by signal: `SHARP_MONEY`: 17 bets, hit 0.471, ROI −2.80% (negative); `CLV_MODEL`: 897 bets, ROI +1.36%**; by market: spreads +10.8%, totals −5.3%, h2h −0.87%. So their **"sharp money" signal was negative in their own backtest** while a CLV model barely cleared fees, and Sharpe 0.15 with −46% drawdown is a fragile edge. Cite this as the domain's realistic base rate.

**Fit table.** ⚪ concept: **`sized_prob = α·model + (1−α)·de-vigged fair`** shrinkage (~20 LOC, deterministic) → a good way to shrink copy-signal probabilities toward market; the CLV/SHARP_MONEY signal taxonomy as a *labelling* scheme; the negative SHARP_MONEY result as the prior for any "sharp money" claim in our stack.

---

### 1.9 Also-deep-read (secondary)

- **mateogon/hermes-polymarket-clob2-agent** (NONE). `learning/overfit.py` `overfit_warnings(OverfitInputs)` emits `small_sample`, `too_many_experiments`, `category_concentration`, `out_of_sample_degradation` — a self-guard against exactly the "tuned on noise" failure; `signals/wallet_flow_signal.py` does **copyability with an order-book FOK fill sim**, a `cents-worse` gate (`max_entry_worse_cents`), a staleness gate, and maps `wallet_score → model_probability = clamp(0.5 + score·0.10, 0.52, 0.65)`. ⚪ concept: the **overfit overlay** (~0.5 d) + the **copyability/fill gate** (microstructure-informed, complements the Rust sidecar). No license.
- **Gurdiel07/polymarket-bot** (MIT). `analytics/wallet_scoreboard.py` ranks wallets by **mean signed drift at 24 h** on their own emitted signals with `min_samples 5` and proposes **prune candidates** (10+ samples, win-rate < 30%, mean drift ≤ 0); `analytics/forward_test.py` runs a **7-day forward test persisted as expected-backtest vs observed-forward** (`backtest_win_rate/total_pnl/profit_factor/sharpe/max_dd` vs realised). ✅ concept-adopt: the **expected-vs-observed forward-test loop** (~1 d) is a strong fit for the stack's shadow-first culture. Their `signal_scoring.py` (`|delta|·wallet_mult·conviction·market_quality`) is heuristic and **not** better than ours.
- **jt8530-beep/weather** → `wallet_alpha_radar/` (NONE). `wallet_alpha_decay_probe.py` joins captured wallet trades to stored order-book snapshots and measures whether price moved in the wallet's favour at **T+delay** — a direct alpha-decay / latency-stress measurement; `wallet_score.py` is a rule-points score with `high_entry_90_ratio`, `hedge_ratio_approx`, `REJECT_*` gates. Files literally self-label *"This is not a copy-trading signal"* and *"not a profitability proof."* ⚪ concept-adopt: **the alpha-decay probe + hedge-ratio gate** (hedged wallets aren't directional alpha).
- **Cachaza/polymarket-scanner** (NONE). `app/scoring.py` scores *markets* (not wallets) as `price_anomaly (6h ≥0.10) + holder_concentration Δ (top-5 seen-share +0.10) + wallet_quality (max(politics,overall)) + trade_flow (buy skew, fresh taker count, strong-wallet count)`, thresholds 8.0/5.5. `app/backtest.py` has a forward-return harness with `latent_strong_wallet_entry` signals and 6/24/72 h horizons. ⚪ concept: **holder-concentration-delta and fresh-taker-flow** features (microstructure-informed) — not present in our 6 sub-scores.
- **meta-xucong/POLY_SMARTMONEY** (NONE). `screen_users.py`: `copy_score = Σ config_weight·clamp(feature)` over a **rich copyability feature set** — `burstiness`, `minute_burst_ratio`, `interval_median_minutes`, `trades_per_day`, `near_expiry_ratio`, `recent_pnl_share`, `recent_surge_ratio`, `suspected_hft`, `ulcer_index`, `max_drawdown`, plus `copy_style` ∈ {成交爆发 / 时效强 / 可复制}. ⚪ concept: **burstiness + near-expiry + HFT-suspicion features** (bot/cadence detection — again absent from our score). No OOS evidence.
- **tshore2004/polymarket-trader** (NONE) → `calibrate_weights.py`: **the recipe to repair the weights** — loads resolved picks, fits **L2 logistic regression** (coef·std = relative predictive power) with **5-fold stratified CV ROC-AUC**, a **grid search** maximising ROI under weight constraints, **bootstrap CIs** ("tells you which factors are reliably non-zero"), and **Brier before/after**; `--apply` writes new weights. `core/fair_value.py` prioritises **Pinnacle (sharp book) → The Odds API → order-book depth**. ⚪ **concept-adopt (high value): turn our hand-weights into learned weights, and keep the bootstrap CI so we know which sub-scores are actually non-zero before trusting the composite.** ~1 d (we already have `venv-calib` + numpy/scipy).
- **samuraifrenchienft/Prediction-Agent** (NONE). XGBoost shadow scorer with conservative hyperparams + **temporal CV only**, and a **Platt-scaling `ConfidenceCalibrator`** (pure-Python gradient descent, `Brier < 0.25` activation gate, 150-sample minimum, monthly retrain) — a clean concrete pattern for "calibrate any RAW confidence-derived probability." ⚪ concept; their smart-money trader features are explicitly acknowledged as *proxies* ("we don't have real-time per-market position data… this is a lightweight heuristic").
- **feecrookz-bit/basement-archive** (NONE). `app/wallet_quality.py`: cadence classifier (`trades_per_day`, `median_gap_min`) → `bot` wallets get weight pinned to the **0.25 floor** so their buys "can never clear MIN_SIGNAL_SCORE alone". Repo's research note: leaderboard-topping wallets are HFT bots a follower cannot shadow → "Copy them and you are pure exit liquidity." ⚪ concept-adopt: **bot-mute floor** (~0.5 d) + treat fast-cadence wallets as un-copyable.
- **darrnhard/polymarket-smart-money** (NONE). Behavioural study of 3 top wallets: all three are **bots** (99.99% BUY-only, sub-cent sizes, 66–75% activity in 60–90 s bursts); measured **lead/lag**: `sovereign` leads 68–82% of shared markets, `rn1` lags 400+ min → **"do not copy rn1"**; overlap tiers (7,645 all-three markets = highest conviction). **`plan/performance-metrics.md` documents a blocker that matches ours**: WIN/LOSS classification from activity data is unreliable (~99% OPEN) because REDEEM events are missing — they need Gamma resolution data. ⚪ concept: **lead/lag + burst-window + overlap-conviction measurements** and the resolution-data caveat. **No license.**
- **Ksmith18skc/SignalForge** (NONE). 5-part weighted score (wallet 35 / consensus 25 / liquidity 15 / timing 15 / inefficiency 10) — schematic but structurally identical to ours; **not a repair, a mirror.** ❌.

---

## 2. Explicitly flagged: hype / scaffold / non-scoring

- **al1enjesus/polymarket-whales** (MIT, 63★) — a threshold-on-trade-size alert CLI; **zero scoring**, plus a Telegram-subscription funnel. Classic alert-repo; no machinery.
- **chainstacklabs/polymarket-alpha-bot** (Apache-2.0, 181★) — "alpha" here is **LLM-extracted cross-market arb pairs**, not wallet scoring; overlaps oracle3 `coinjure` (already audited). Not a score donor.
- **manifoldmarkets/market-maker** (MIT) — EMA/EM-variance quoting bot. Not ranking.
- **lbsm2017/polyMDash** (MIT, "conviction_scorer.py") — **weights sum to 1.60** (`0.50+0.30+0.30+0.30+0.20`) — a live arithmetic bug; do not adopt. Illustrates why "hand-weighted" needs an assertion that weights sum to 1.
- **winder87-stack/-polymarket-copy-bot, Timaroc13/polymarket-engine, dexoryn*/polymarket-copy-trading-bot, suislanchez/*-insider-detector, Abomination81/copybot, n9xdev/poly-alpha-lab, sueun-dev/polymarket-alpha-lab** — alert/skeleton/SQL-heavy repos (200 k LOC w/ no ratio that resolves to a predictive number); no verifiable scoring core.
- **kachence/prediction-almanac** (MIT) — a *catalogue* (`data/tools/*.yaml`) of prediction-market tools/datasets (`polymarket-orderbook-microstructure`, `prediction-market-calibration-decomposition`, `probalytics`, `overfitting-and-multiple-testing`, `brier-skill`…). Not code, but a useful **pointer list** for the calibration literature — worth keeping as a research index, not a dependency.
- **evan-kolberg/prediction-market-backtesting** (NOASSERTION, 1199★) — a NautilusTrader extension for PM backtests. Relevant as *infrastructure* for validating a score, but **NOASSERTION = no license grant → read-only**; and NautilusTrader/Python is not adoptable as a dependency for the Node/Rust core. Concept-only.

---

## 3. Repos the task named (prior audits — re-confirmed, no new work)

- **YichengYang-Ethan/oracle3 (Apache-2.0, vendored).** Scoring **beyond WangMLE** = `trading/sizing.py::ModelInformedSizer` only — a *trade* sizer (Kelly gates: volume-tier λ≈0 skip, confidence floor, min net edge, `max_kelly`), **not a wallet/trader ranking**. Its other "score-like" artifacts are `market/relations.py::ValidationResult` (violation_rate / mean_arb / ADF / Engle-Granger / half-life) and `market/validation.py::favorite_longshot_test` / `cross_platform_premium_test` — *market-quality* diagnostics, not wallet skill. **Verdict: no wallet-ranking machinery here; the vendored `wang_mle.py` is byte-identical to upstream (frozen 122 d) — nothing to take for this audit.** Its `OnlineCalibrator` (EWMA α=0.05 + hierarchical shrinkage `w = n/(n+κ)`, κ=20) is the one shrinkage idea present, but it shrinks a *λ̂ risk-premium*, not a wallet score — concept-adjacent to §1.2, not a substitute.
- **caiovicentino/polymarket-mcp-server (MIT, audited).** Confirmed: **2 of 10 analysis tools are stubs** (`get_price_history`, `get_market_holders` return hardcoded error dicts) out of 45 advertised tools → "45 tools" overstates working surface ~20%. **No scoring machinery at all.** Re-confirmed not-adopt.

---

## 4. Consolidated transferable components (ranked by value ÷ effort)

| # | Component (source) | License | Effort | Risk | Why it repairs the score |
|---|---|---|---|---|---|
| 1 | **Symmetric shrinkage `score = 50 + (raw−50)·n/(n+K)`** on the composite (seer-pm traderScore, MIT) | MIT | ~2 h | LOW | Directly attacks "hand-weighted score ranks lucky/low-sample wallets"; makes low evidence read *undecided*, not *good* |
| 2 | **Empirical-Bayes signed informedness** `(0.70·edge + 0.30·(2·hit−1))·n/(n+prior)` (gnosicular) | NONE | ~2 h | LOW | Replaces raw win-rate inputs with a shrunk, edge-anchored skill estimate |
| 3 | **Edge-anchored label `edge = mean(outcome − entry_price)`** (tmk11, NONE; also polymarketpricer `edge=(sell|resolution−entry)/entry`, MIT) | NONE / MIT | ~0.5 d | LOW | The correct target for "does the pick beat the price", independent of the PnL noise |
| 4 | **Baseline suite + walk-forward (grouped-CV) harness** around our existing `pilot-score-separation.py` (Fletty; polycopy) | NONE / MIT | ~0.5 d | LOW | Proves "better than random / top-PnL / no-signal" — the test that this stack's score currently fails |
| 5 | **Versioned scoring + Brier/Spearman cutover rule** (`brier_v2 < brier_v1 − 0.01` ⇒ adopt) (polycopy, MIT) | MIT | ~1 d | LOW | Turns "should we change the score?" into a machine-decidable rule |
| 6 | **Rank-transform pool normalisation** of sub-scores (polycopy, MIT) | MIT | ~0.5 d | LOW | Removes scale/outlier pathologies of raw linear inputs; monotone ranking |
| 7 | **Cost-adjusted threshold calibration** (gate at the score where net-of-fee follower PnL turns positive) (pselamy, MIT) | MIT | ~1–2 d | LOW | Converts a non-predictive score into a *conservative admission gate* — the honest use of a weak score |
| 8 | **Weight optimiser** (L2 logistic + CV-AUC + grid + bootstrap CI + Brier before/after) (tshore, NONE) | NONE | ~1 d | MED | Replaces hand-weights with learned ones and tells you which sub-scores are non-zero |
| 9 | **Anti-gaming / one-hit / concentration-excl gates** (tmk11 NONE; seer-pm coverage gate MIT) | mixed | ~1 d | LOW | Stops "lucky/padded wallets" and "score can't see the P/L" from ever reading high |
| 10 | **Copyability/latency gate** (FOK fill sim, cents-worse, staleness, burst/cadence bot-mute) (mateogon NONE; feecrookz NONE; jt8530 NONE) | NONE | ~0.5–1 d | LOW | Microstructure-informed: filters trades that cannot actually be copied at the price |
| 11 | **Forward-test loop: expected-backtest vs observed-forward** (Gurdiel07, MIT) | MIT | ~1 d | LOW | Catches the exact failure now visible (backtest ≫ live) with a persistent gap metric |
| 12 | **Brier-skill calibration factor vs pool baseline** (polycopy, MIT) | MIT | ~0.5 d | LOW | Adds a ranking input that is *definitionally* about being better-calibrated than the pool |

**Adopt-now shortlist (fastest, safest, flag-revertible, all LOW risk):** #1 shrinkage, #4 baseline suite on the existing pilot, #3 edge-anchored label, #6 rank-normalisation. All are measurement/scoring-only, hide behind a flag, and do not touch the live Kelly window.

---

## 5. Honest caveats + verdict

**Caveats.**
1. **Almost nothing in the wild demonstrates predictive power.** Of ~25 candidates with scoring code, **one** ships per-signal backtest numbers (childersjac: SHARP_MONEY **negative**), **one** documents a cost-adjusted calibration finding (pselamy: low scores follower-PnL-negative), and the rest ship *harnesses, specs, and tuned-but-unreported parameters*. Any transfer must be re-validated on our own labeled set (`training_data.csv` / `pilot-scoring-separation.py`).
2. **The domain's own "sharp money" evidence is negative or fragile.** childersjac's SHARP_MONEY class lost money; darrnhard found every top wallet is a bot and copying the laggard is a loss; feecrookz found leaderboards are HFT bots followers cannot shadow. **The prior for "copy the top wallets harder" being the fix is weak** — the fix is more likely in *labelling, shrinkage, gating and cost-adjusted thresholds* than in a cleverer whale score.
3. **Licenses limit what can be copied, not what can be learned.** Every genuinely interesting high-signal repo here except polycopy / seer-pm / polymarketpricer / pselamy / Gurdiel07 is **NO-LICENSE (all-rights-reserved)** → those must be **reimplemented from the formulas quoted above**, never copied. No AGPL service is needed by any component on the shortlist (homerun AGPL and OctoBot GPL were not candidates).
4. **Some "scores" are provably buggy** (polyMDash weights sum 1.60; Fletty's `_ret` precedence bug) — a reminder to assert `Σweights = 1` (as polycopy does at import) before trusting any composite.
5. **Our own measurement is not yet trustworthy enough to build on:** the resolution-label bug (`drafts/resolution-label-bug-plan.md`) and darrnhard's *identical* finding (REDEEM events missing → ~99% of markets read OPEN) mean the "no predictive power" result may be partly a **labeling** artefact. **Run the leakage + resolution audit (component #4/#7) BEFORE concluding the score is dead.**
6. Search coverage: 55 queries + 35 clones is broad but not exhaustive; long-tail repos (and the Chinese-language Polymarket ecosystem) are under-covered. GitHub repo-counts in this domain are inflated by AI-generated scaffold repos — the licence-first + source-verified filter above is deliberately blunt.

**Verdict.**
- **✅ ADOPT (concepts, deterministic, portable to Node/TS + Python):** shrinkage `n/(n+K)` (#1), empirical-Bayes informedness (#2), edge-anchored label (#3), baseline + walk-forward harness on the existing pilot (#4), versioned-score Brier/Spearman cutover (#5), rank-pool normalisation (#6), cost-adjusted threshold calibration (#7), anti-gaming/coverage gates (#9). Total ≈ **4–6 days**, all LOW risk, all flag-revertible, none touching the live Kelly window.
- **⚪ CONCEPT-ONLY (reimplement the math; do NOT copy code — no license):** gnosicular, tmk11, JamesFletty, jt8530, mateogon, darrnhard, Cachaza, meta-xucong, tshore, samuraifrenchienft, feecrookz, childersjac, Ksmith18skc.
- **❌ NOT-PORTABLE:** chainstacklabs (LLM arb layer, duplicates oracle3 `coinjure`); manifold market-maker (quoting, not ranking); al1enjesus/polymarket-whales and the alert-only clones (no scoring); Polyseer / polymarket-mcp-server (already audited; mcp-server has 2/45 stub tools); evan-kolberg backtesting (NOASSERTION + NautilusTrader dependency).
- **Two donor repos are worth vendoring (MIT, genuine deterministic cores):** **nexiumito/polycopy** (rank normalisation + gates + cutover harness) and **seer-pm/demo** (the `traderScore.ts` shrinkage/metrics file). Both are small, dependency-light, and directly attack the five proved gaps.
- **Roadmap coupling:** every item above is *measurement or scoring* and hides behind a ruleset flag, so it does not disturb the standing measurement window; sequence = **label/leakage audit → baseline+shrinkage+edge-label (all offline) → cutover-gated score change**. Nothing here is adopt-now for the live lane; the earn-its-place step is the same pilot that currently says the score does not work.

---

*Repos audited by shallow clone (read line-by-line): nexus polycopy, seer-pm/demo, polymarketpricer, pselamy-insider-tracker, Gurdiel07, tmk11, gnosicular, JamesFletty/maths, childersjac Line-Tracker, mateogon, jt8530 weather, darrnhard, Cachaza, meta-xucong, tshore, samuraifrenchienft, feecrookz, Ksmith18skc, chainstacklabs, manifold market-maker, al1enjesus, lbsm2017, winder87, NickNaskida, devfchen/joker, Timaroc13, Marzel7/flex, leoaguiarguedes, humanplane/terminal, 4Rbelaez, realfishsam, dexoryn. Metadata-only (license/size/stars) for the rest.*
*No fabricated numbers: every formula, threshold and backtest figure above was read from a cloned file; where a repo ships no results, this doc says "none demonstrated".*
