# Repo Audit — YichengYang-Ethan/oracle3 (adoption fit for Medusa CopyBot)

**Date:** 2026-09-07 · **Auditor:** subagent deep-audit (github-repo-audit procedure)
**Repo:** https://github.com/YichengYang-Ethan/oracle3 · **License:** Apache-2.0 (borrowable w/ attribution)
**Stars/forks:** 253 / 33 · **pushed_at:** 2026-05-08T07:48Z (~122 d dormant — matches scout) · **default_branch:** main · **version:** 1.1.2 (commit 86c2518)
**Topics:** prediction-market, wang-transform, hierarchical-mle, kelly-criterion, arbitrage, kalshi, polymarket, dflow, jito-bundles
**Repo state:** 37.5K LOC Python (201 files), 45 test files, 642 `def test_*` counted statically (README claims 633 collected); in-repo paper source (`paper.md`/`paper.tex` = Yang 2026 UIUC working paper the math is built on). **Tests NOT executed here** — deps (solana/solders/kalshi-python/openai…) not installed; verdicts on tests are by inspection of assertion quality, not a run. No fabricated numbers below.

---

## 1. What it is

A research-flavored prediction-market trading engine by Yicheng Yang (UIUC): Wang-Transform pricing (`p_mkt = Φ(Φ⁻¹(p*) + λ)`) with an MLE-calibrated risk-premium model (pooled + hierarchical covariates + 3 SE estimators), a three-tier Kelly sizer, an **8-family constraint-arb taxonomy** (same_event / cross_platform / implication / exclusivity / conditional / structural / cointegration / complement) with validation stats, a **staged cross-platform market-matching library (`coinjure`)**, paper/live traders for Polymarket/Kalshi/Solana-DFlow, an LLM agent layer, and a full CLI/dashboard. The deterministic core is the pricing + relations + matching stack; the LLM/agent layer and Solana execution infra are NOT portable (duplicate or venue-bound — see §6).

**Relationship to this stack:** oracle3's `WangMLE` is **already vendored** at `scripts/vendor/oracle3/wang_mle.py` (Apache-2.0, with LICENSE) for the C-200 biweekly band-λ̂ refit (`scripts/calibrate-premium.py`), and Phase B (Kelly) explicitly ports `ModelInformedSizer` semantics. This audit covers what ELSE transfers and whether the vendored module needs an upgrade.

**Vendored-module verdict: `diff` shows the vendored `wang_mle.py` is BYTE-IDENTICAL to upstream `oracle3/pricing/wang_mle.py` (21,768 B both, current as of v1.1.2 / 2026-05-07).** No upgrade required. Re-check only if upstream ever pushes again (repo has been dormant 122 d — treat as frozen; vendoring was the right call).

## 2. Verified machinery (from source, not README)

### 2a. Wang pricing core — VERIFIED (consistent with Yang 2026; already in use)
- `p_mkt = Φ(Φ⁻¹(p*) + λ)`; λ>0 ⇒ systematic overpricing. `distortion.py` implements probit (Wang 2000), dual-power (Denneberg), proportional-hazard (Wang 1995) families with scipy-free A&S/Beasley-Springer-Moro CDF/PPF (≤1e-7 abs err — fine for signals, not for p-values).
- `wang_mle.py`: probit-offset MLE (`Pr(y=1|p_i) = Φ(z_i − X_i·β)`, z_i = Φ⁻¹(p_i)) — computationally a probit with known offset; analytic gradients; Fisher + Huber-White sandwich + clustered SEs; LR/AIC/BIC/pseudo-R² diagnostics; chunked (30K) BLAS ops; priors Polymarket 0.166 / Kalshi 0.187 / pooled 0.183. This is the vendored module; API surface matches how `calibrate-premium.py` calls it (`fit(prices, outcomes, initial_beta)`, `se_robust[0]`).
- `fair_value.py`: **hierarchical λ_i = 0.2590 − 0.0716·ln(1+V) + 0.1431·ln(1+D) − 0.4772·|p−0.5| + 0.1273·Spread** (paper Table 3, N=13,274) and **time-varying λ(τ) = 0.2531 − 0.1555·τ + 0.0744·τ² + covariates** (Table 5, N=111,889), τ = fraction of lifetime elapsed. Volume tiers <500 / 500–2K / 2K–10K / >10K; **>10K ⇒ λ≈0 (premium competed away)**. `mispricing_signal = (actual_premium − expected_premium)/|expected_premium|` isolates model-implied premium — nice decomposition, beats raw Δ.
- `calibrator.py`: `OnlineCalibrator` = per-category **EWMA (α=0.05)** on resolved contracts (outcome-smoothed to 0.999/0.001) + **hierarchical shrinkage** `λ̂_cat = w·λ̂_raw + (1−w)·λ̂_global`, `w = n/(n+κ)`, κ=20; batch MLE results override EWMA; confidence = logistic(t-stat − 2) or n-factor.

### 2b. Kelly / edge sizer — VERIFIED against standard binary Kelly
`trading/sizing.py` `ModelInformedSizer` (Phase B already ports this):
- YES (underpriced): `kelly = (p* − p_m − 2·fee)/ (1 − p_m)` ✓ standard (Thorp 2006 form).
- NO (overpriced): `kelly = (p_m − p* − 2·fee)/ p_m` ✓ (derived; correct NO-side dual).
- Gates: volume-tier skip (very-high ⇒ λ≈0), confidence floor 0.15, min net edge 0.005, `max_kelly` default 0.15, capital × kelly, min/max dollar bounds, win-rate empirical cap.
- **Formula wart (minor, safe direction):** the empirical-win-rate blend `wr·(1/p_m − 1) − (1−wr)` is the Kelly *numerator* (b·p−q), missing the ÷b — overstates true Kelly when p_m<0.5. Since it enters via `min(kelly_raw, max(empirical,0))` it can only *loosen* the cap, never oversize vs the model Kelly. Document, don't fix. Fee treated as probability-points (2×0.5%) — fine at ~$1 notional, but Kalshi per-contract fees want venue-accurate handling (the stack already does this).

### 2c. Constraint-arb family — the Phase C payload
- **`coinjure/matching` (1,559 LOC — the standout):** staged 5-factor same-event matcher for Polymarket↔Kalshi: category buckets (0.10) · date proximity (0.20; 1.0 within 7 d, linear decay to 0 at 30 d) · **template structural match (0.30)** — regex templates with semantic fields (`election_state_race` → party+state+race_type; `crypto_price_threshold` → coin+price+threshold+direction) that inherently reject WIN-vs-TIE and "by X"-vs-"by Y" false matches · text similarity (0.30, min 0.45) · **resolution compatibility (0.10)** — end-date delta >7 d warning + official-source check (AP/Reuters/ESPN…). Confidence: HIGH if template matched, else ≥3 passing stages ⇒ HIGH, ≥2 ⇒ MEDIUM. `_compute_spread()` yields the YES-price gap. **Self-contained:** stdlib-only modules; the single `oracle3.ticker` import lives in a convenience adapter in `__init__.py` → clean to vendor wholesale.
- `cross_market_arbitrage_strategy.py` (v2, 820 LOC): order-book-aware (best bid/ask, last-price fallback); `gross = bid_B − ask_A`; `net = gross − 2·0.5%`; entry ≥3¢ net (default), exit on collapse <0.5¢, max hold 3,600 s, cooldown 60 s; state machine flat → long_a_short_b (buy YES A @ask + buy NO B @1−bid_B) → flat; logs per-leg success, explicitly warns "PARTIAL: leg1 filled but leg2 failed — position may be unhedged" (no auto-unwind). NO leg priced off the YES-bid mirror — an approximation (real Polymarket NO book can differ).
- `exclusivity_arb_strategy.py`: A+B≤1 → buy both NO; min violation 2¢. `implication_arb_strategy.py`: A⇒B ⇒ p_A≤p_B; sell A / buy B; min 1¢. `event_sum_arb_strategy.py`: ΣYES=1 within event; Σ<1 → buy all YES, Σ>1 → buy all NO; min 2¢. `structural_arb_strategy.py`: residual vs linear relation (slope/intercept), min 2¢, hysteresis exit.
- `market/relations.py`: 8-type taxonomy + **lifecycle discovered → validated → deployed → retired/invalidated** with `ValidationResult` (violation_count / violation_rate / mean_arb / current_arb, ADF, Engle-Granger, half-life, hedge ratio, lead-lag). `market/validation.py`: `_check_constraint`, `validate_relation`, plus `cross_platform_premium_test` and `favorite_longshot_test` — calibration-quality harnesses in the same spirit as this stack's λ̂ z-scores.

### 2d. Execution / fill models
- `PaperTrader._simulate_execution`: sums book levels within limit, multiplies by a uniform random fill-rate haircut [min_fill_rate, max_fill_rate], fills **at the limit price**, partial fills possible, no resting-queue, no time-to-fill. This is a *cruder* fill model than this stack's current paper fills and far below the Phase D2 Cox-PH ambition — **not an adoption target**; treat as the floor, not the ceiling.
- Spread executor / atomic trader / Jito bundles / flash loans / Solana trader / blinks / on-chain signal source: venue-bound real-money infra + LLM agent layer — not portable (§6).

## 3. Fit table vs roadmap gaps

| oracle3 component (verified) | Roadmap gap | Verdict | Effort / risk |
|---|---|---|---|
| **`coinjure/matching` staged matcher** (category·date·template·text·resolution → confidence) | **Phase C** cross-venue PM↔Kalshi same-event matching (design notes §1a matching req; replaces fuzzy-only matching) | ✅ **ADOPT (vendor ~1.5K LOC, Apache-2.0)** at Phase C build kickoff (early Oct, post-Kelly-window) | ~0.5–1 d incl. adapter + pass against own PMA resolved-market pairs; LOW risk; flag-revertible (feeds detection/shadow lane only) |
| Constraint-arb formulas: exclusivity A+B≤1, implication A≤B, event-sum ΣYES=1, structural residual | Phase C invariant families 1b/1c (design notes already specify these; PMA backtest deliverable) | ⚪ concept-only — reference implementations; port the 5-line formulas + guards, not the oracle3 event/trader plumbing | small; the real work stays the PMA backtest (Sep 15–30 design window) |
| `relations.py` lifecycle (discovered→validated→deployed→retired) + `ValidationResult` (violation_rate/mean_arb/current_arb) | Phase C shadow journal ("detection + shadow first") | ✅ adopt pattern (0.5 d) — matches the stack's shadow-first culture; store as JSON/SQLite in research bot, don't port the file store | LOW |
| `validation.py` `favorite_longshot_test` / `cross_platform_premium_test` | λ̂ refit reporting (calibrate-premium Discord summary) + Phase C validation | ⚪ concept — add longshot-bias + venue-premium checks to the monthly refit output | ~0.25 d each; LOW |
| Time-varying λ(τ) (Table-5 τ² curve) + `premium_decay_strategy` (PremiumTracker; ride premium decay long-NO) | short-TTR sports/esports daily-PnL lane; ML-2 features | ⚪ concept-only — **recalibrate on own resolved trades**; their τ coefficients are 28-day general-market sample, CopyBot sports TTRs are hours; τ-aware band λ̂ is a genuine post-window research card (would touch C-200 sizing ⇒ measurement-only until window closes) | research 1–2 d; MEDIUM (model change — measurement-gated) |
| `OnlineCalibrator` EWMA (α=0.05) + hierarchical shrinkage (κ=20) between batch refits | λ̂ drift between the biweekly refits | ⚪ concept-only / queue — batch-per-band biweekly is already right cadence; EWMA adds regime-sensitivity for a copy lane. Only as post-Oct-8 research, shadow-compared vs batch refit | research; MEDIUM |
| `ModelInformedSizer` Kelly gates (volume-tier λ≈0 skip, confidence scaling) | Phase B (already shipped/landing v49/v50 via roadmap card) | ✅ already incorporated — nothing new to take; keep the ÷b wart note in mind if empirical blend is copied later | — |
| WangMLE SE/diagnostics (`se_robust`, z-stat, AIC/BIC) | calibrate-premium λ̂ z-scores | ✅ already in use (vendored file identical to upstream) — no upgrade | — |
| Test patterns: synthetic-data recovery tests (`test_wang_mle.py`) | calibrate-premium regression safety | ⚪ adopt pattern — add a synthetic-λ̂ recovery test around the vendored fit | 0.25 d |

## 4. Integration proposal (for AFTER Oct 8 — Kelly window untouched)

1. **Vendor `coinjure/matching`** (post-Oct-8, Phase C build kickoff ~early Oct): copy `coinjure/matching/*.py` → `scripts/vendor/oracle3/coinjure/` (Apache-2.0 notice + LICENSE, mirroring the existing wang_mle vendor dir); write a thin adapter mapping Polymarket Gamma market + Kalshi event/ticker to `NormalizedMarket`; keep `_fetchers.py` out (their live fetchers are oracle3-coupled). Gate: run matcher over a held-out set of known-same-event PM/Kalshi pairs from the PMA dataset (both venues, resolved) — measure match precision vs the design notes' false-positive classes (WIN/TIE, multiway, "90-min vs advance", cumulative "by X" dates). This de-risks the Sep 15–30 design window's #1 matching deliverable.
2. **Phase C shadow lane** uses relations-lifecycle + ValidationResult-style stats for the journal; oracle3's exclusivity/implication/event-sum strategies stay as *reference* for the invariant math only — formulas already in the design notes.
3. **Skip** all execution/fill/live-trader adoption; keep the Phase D2 Cox-PH plan (oracle3's PaperTrader is strictly cruder).
4. **Research card (post-window, shadow-only):** τ-aware λ̂ and/or EWMA-vs-batch λ̂ comparison on the stack's own resolved-trade DB; oracle3's Table-5 coefficients are a prior, not a transplant.

Effort if all adopted: ~1.5–2.5 d spread across Phase C build + two research cards. Risk: LOW for (1) (pure matcher, shadow-fed), MEDIUM for (4) (sizing-adjacent — measurement-gated by the standing Oct-8 rule). Every item is flag-revertible (detection/shadow first, matching the A2/Phase-C precedent).

## 5. NOT-portable list

- **LLM/agent layer** (`oracle3/agent/*`, coordinator, research/agent CLIs, llm_news simulation) — duplicates the stack's DeepSeek research bot + local-LLM sentiment lanes.
- **Solana/DFlow execution** (`solana_trader`, `atomic_trader` flash loans, `jito_submitter`, blinks, `onchain_*`) — venue-bound real-money infra with no PM/Kalshi paper analog in the stack.
- **`PaperTrader` fill simulation** — cruder than the stack's existing fills; not an upgrade over the Phase D2 Cox-PH plan.
- **TickerGrouper fuzzy matching** (`SequenceMatcher ≥0.6` in cross_market_arbitrage_strategy) — superseded by coinjure's staged matcher; don't port both.
- **CLI / Textual dashboard / FastAPI server / demo flows / llm backtests** — stack has its own dashboard & orchestration.
- **Their trader/position/risk-manager interfaces** — the stack's Node scorer + Rust sidecar + research-bot split doesn't match; port semantics only (already the Phase B precedent).

## 6. Honest caveats + verdict

- **Caveats:** (a) dormant 122 d — frozen upstream, vendoring is correct and already done; (b) 642 test fns counted statically; suite **not run** in this environment (heavy poetry deps) — assertion quality inspected and good (synthetic-recovery, edge cases), but "633 tests pass" is the README's claim, unverified here; (c) all paper coefficients are general 28-day Polymarket samples — CopyBot's short-TTR sports lane must recalibrate, never reuse; (d) their arb legs assume NO ≈ 1−YES mirror and non-atomic two-leg fills with only a warning on partial fill — paper Phase C must require both-legs-recorded and model per-leg fill risk (design notes already flag this); (e) flat 0.5%-per-side fee as probability-point subtraction is an approximation — use venue fee schedules (stack already does); (f) no evidence of real-money track record in-repo (paper-trading engine by construction) — treat all edge-frequency claims as untested hypotheses until the stack's own PMA backtest confirms.
- **Verdict: QUEUE → ADOPT coinjure/matching at Phase C kickoff; nothing pre-Oct-8.** The single clean adoption is the staged matcher feeding Phase C's detection/shadow lane (low risk, ~1 d, flag-revertible). Everything else is concept-only (invariant math, relations lifecycle, τ-aware λ̂, EWMA-vs-batch research) or already incorporated (WangMLE identical, ModelInformedSizer = Phase B). Execution/fill models and the LLM layer: skip. This aligns with roadmap order — Phase C design Sep 15–30 uses the matcher evaluation results, build early Oct (post-window), and the research cards slot behind the Kelly measurement window per the standing no-ship rule.
