# Repo Audit: skharchikov/polymarket-bot — Adoption Fit into Xman's Polymarket/Kalshi Stack

**Audited:** 2026-09-09 · **HEAD:** `f6ebb59` "release: v0.6.41" · **Repo:** https://github.com/skharchikov/polymarket-bot
**Clone:** /tmp/audit_triage/clones/skharchikov_polymarket-bot · **Language:** Rust (workspace: `trading-bot`, `copy-trading-bot`, `common`) · **Stars:** 32 · **Created:** 2026-03-08 · **Last push:** 2026-09-06 · **Active**

---

## 1. License verdict — NO-LICENSE (read-only concept donor)

- GitHub API: `license: None` (verified via API call).
- No `LICENSE`/`COPYING` file anywhere in tree (verified: `find . -iname "*license*"` → empty).
- ⇒ All rights reserved. Per user doctrine (precedent: BTC-15min audit): **READ-ONLY concept donor — copy NOTHING.** Math verified in source may be reimplemented from the standard references it instantiates. Everything below is concept-only at best.

## 2. What it is

Autonomous news-driven Polymarket bot in Rust. Pipeline (verified in README + source):

```
Gamma API markets → news crawler → candidates
  ├─ XGBoost ensemble (pure-Rust JSON tree inference, or Python sidecar: XGB+LightGBM+HistGBM+ET+RF+meta-learner) → price-anchored posterior
  └─ Multi-agent LLM consensus (roles: skeptic / catalyst / base_rate) → each emits a LIKELIHOOD RATIO + confidence (not a probability)
        → Bayesian update: market price as prior odds × Π LR^conf
        → histogram calibration on resolved estimates (inert — see §3.4)
        → edge gate (prob-diff) → fractional Kelly (0.15/0.25/0.50 per strategy) × terminal-risk scale → bet
```

Plus: copy-trading bot, Postgres (migrations/), Telegram ops, ADR docs, backtester w/ Sharpe/Brier/max-DD, Brier-score prediction logging. README keywords "Kelly" **and** "calibration" both verified in source. Currency EUR, live trading enabled — this is a real deployed bot with a track record quoted in code comments (e.g. XGB YES-side: "30% WR, −€745 in production" → `block_yes_side` default true).

## 3. Verified machinery — EXACT formulas from source

### 3.1 Kelly sizing — `common/src/pricing/kelly.rs` (textbook, nothing new)
```rust
let b = (1.0 - market_price) / market_price;   // net odds per unit staked on YES
let q = 1.0 - prob;
let f = (b * prob - q) / b;                     // kelly_fraction, floored at 0.0
pub fn fractional_kelly(prob, market_price, fraction) = kelly_fraction(...) * fraction
```
- This is exactly the standard binary-bet Kelly `f* = p − q/b = (bp − q)/b` with net odds `b = (1−price)/price`. Correct against the reference; unit tests confirm no-edge → 0 (0.60/0.60), positive edge → >0.
- Fractional multipliers: aggressive 0.50, balanced 0.25, conservative 0.15 (`trading-bot/src/config.rs:229-239`), applied per strategy profile (`trading-bot/src/strategy.rs:100-104`).
- **No novelty vs shipped Phase B Kelly** — same formula family, same fractional discipline. Log-optimality assumptions are the standard ones (single binary bet, no correlation across bets; they do add an LLM correlation check at the portfolio level, ADR 007).

### 3.2 Sizing modifiers (strategy.rs, config.rs)
- **Terminal-risk time scale** (strategy.rs:112-116): bets ≤3d full size; else `scale = √(3 / days_to_expiry)` clamped to [0.2, 1.0]. Empirical motivation documented in code: ">7d bets have 19% WR (−€7.33/bet avg), 1-3d is the sweet spot."
- **Gates** (strategy.rs:83-107): `effective_edge = edge × confidence` must clear per-strategy min (0.05/0.06/0.08); min confidence 0.40/0.40/0.50; Kelly < 0.01 → reject. XGBoost-source signals get **half** the edge gate and 0.7× the confidence gate ("trust the model"). Plus `min_kelly_size` 0.02, `min_bet_price` (longshot filter), `block_yes_side` for XGB.
- **Edge definition** (bayesian.rs `compute_edge`): raw probability difference — YES: `posterior − yes_price`; NO: `(1−posterior) − (1−yes_price)`; bet the larger positive side. This is a **prob-diff edge, not odds-ratio edge** — a directional gate feeding Kelly, acceptable, but it overstates edge magnitude for deep-longshot/short-favorite regimes (Kelly's odds term carries the true economics).

### 3.3 Bayesian aggregation — `trading-bot/src/bayesian.rs` (the interesting concept)
- Agents emit **likelihood ratios, not probabilities**: `LR = P(news|YES) / P(news|NO)`, range clamped [0.1, 10].
- **Confidence dampening in log space**: `LR_dampened = LR^confidence` (conf 1.0 → full LR; conf 0.0 → LR=1, no update). Bayesian odds update:
  `posterior = odds_to_prob(prob_to_odds(price) × Π_i LR_i^conf_i)`
- **Consensus confidence**: geometric mean of agent confidences × agreement penalty `exp(−σ(log LRs))` (spread of agent LRs in log space decays confidence).
- Market price as prior anchors everything — LLM "probabilities" can only move the posterior by dampened, directionally-checked evidence. Legacy raw-probability LLM responses are converted to LRs relative to market price (`LR = odds(p̂)/odds(price)`, clamped).
- This is real, coherent math (multiplicative Bayes + log-space dampening) — the strongest transferable concept if any LLM-consensus channel ever feeds the stack. It is a *method for generating the calibrated-probability input*, not a replacement for the shipped calibration-band sizing.

### 3.4 Calibration — `trading-bot/src/calibration.rs` — REAL binning math, but the loop is DEAD at HEAD
- Load: `SELECT raw_probability, outcome FROM llm_estimates WHERE resolved = true AND agent_role = 'consensus' AND outcome IS NOT NULL` (calibration.rs:20-26).
- Curve: 10 bins of width 0.1; per-bin empirical outcome rate with **Laplace smoothing `(wins+1)/(total+2)`**; empty bins seeded with bin midpoint as prior; `correct(raw)`: maps to bin, **linear-interpolates toward the adjacent bin** by fractional offset (`lerp(bin_value, neighbor, |offset|/bin_width)`), output clamped [0.01, 0.99]; active only when `total_samples ≥ calibration_min_samples` (default **20**).
- Applied at `scanner/live.rs:765` to the Bayesian posterior (`calibrated_prob = calibration.correct(posterior)`) before edge/Kelly; summary text of per-bin actuals ("OVERCONFIDENT"/"UNDERCONFIDENT" labels) is also injected into the next LLM prompt (live.rs:657-659,677) — numeric correction + informational prompt loop.
- **Verified verdict on "real math vs prompt dressing":** the numeric correction is real histogram/reliability-diagram binning (cruder cousin of the stack's wang-calibration banding; Laplace prior at bin midpoint is the weak point). The prompt-injection summary is genuine-data dressing — informational, not a substitute for the numeric pass.
- **SMOKING GUN — dead loop:** the only INSERTs into `llm_estimates` write `agent_role` ∈ {`skeptic`, `catalyst`, `base_rate`} (per-agent rows, live.rs:736) and `bayesian` (consensus row, live.rs:776). **No code path ever writes `agent_role='consensus'`** (grep across all crates + migrations: the literal exists only in the calibration SELECT itself). ⇒ `total_samples` is permanently 0, `active` permanently false, correction silently returns raw values, and the prompt summary permanently reads "inactive (0 samples)". The calibration feature **cannot fire at HEAD v0.6.41** — looks like a role-string rename (to "bayesian") that never updated the loader. Even if wired, caveats: fit population = consensus posteriors that are price-anchored priors (partially calibrating the market price itself), and a 20-sample activation threshold for a 10-bin histogram is far too thin (most bins sit at midpoint prior).

### 3.5 Calibration/sizing data loop (housekeeping.rs)
Resolved bets → `resolve_estimates(market_id, yes_won)` marks `llm_estimates` + `prediction_log` resolved → per-cycle `reload_calibration()` rebuilds curve; XGB warm-start retrain trigger on resolution. The *loop design* (resolve → rebuild → feed forward) is the live-recalibration pattern; in this repo it is inert per §3.4.

## 4. Fit table (adopt | concept-only | not-portable)

| Component | Verdict | Rationale |
|---|---|---|
| Binary Kelly `f=(bp−q)/b`, b=(1−p)/p + fractional Kelly | **concept-only (duplicate)** | Textbook; identical family to shipped Phase B Kelly. Copy nothing. |
| Calibrated-probability input discipline (posterior → calibrate → size) | **concept-only (duplicate)** | Mirrors shipped v41 calibration-band sizing; this 10-bin Laplace+lerp variant is strictly cruder than wang-calibration banding and is dead code here anyway. |
| LLM-as-evidence aggregation: LR outputs, `LR^conf` dampening, price-as-prior odds update, disagreement-penalized consensus confidence | **concept-only (new-ish, queue)** | Genuinely different method of *producing* the calibrated input from LLM signals. Only worth a paper-only A/B if the stack ever feeds LLM/consensus probability signals; ~100-line pure-function reimplementation. |
| Live recalibration loop design (resolve→rebuild curve→inject summary into next eval) | **concept-only (broken here)** | The loop idea is the one thing arguably beyond shipped offline recalibration, but in-repo it never activates (§3.4) and prompt-injection of bin tables is unverified value. |
| Terminal-risk time scaling `√(3/d)` + longshot/expiry gates + XGB-role-based gate relaxation | **concept-only** | Cheap domain heuristics w/ their own loss stats; reimplement only if stack data shows the same >7d decay. |
| prob-diff edge (`p̂ − price`) side selection | **not-portable as-is** | Inferior to odds-ratio edge; stack should keep its own edge definition. |
| All Rust code, SQL migrations, docker-compose, XGB sidecar, copy-trading-bot, Gamma/news/Telegram integrations | **not-portable** | NO-LICENSE — cannot copy, adapt, or vend any of it. Concept only. |
| Backtest engine (Sharpe/Brier/max-DD), ADR documentation culture | **concept-only** | Evidence culture worth emulating (Brier vs market baseline, per-source stats), zero code value. |

## 5. Integration proposal

- **Ship: nothing.** Pre-Oct-8 freeze + Kelly measurement window (Sep 8–Oct 8, recommendations only) — no candidate here is missing from the shipped engine, so there is nothing to flag-revert.
- **Optional queue item (post-window, paper-only, flag-revertible):** if/when an LLM-consensus signal channel is added to the stack, reimplement §3.3's LR-framing + `LR^conf` dampening + disagreement-penalized confidence as a pure function module (≈0.5–1 day, no new deps, TS/Rust both trivial) and A/B it against shipped calibration-band sizing on the same resolved-estimate store. Expected value: **low** — shipped engine already enforces calibrated-probability input discipline; the LR framing is mostly a prompt-format change plus a dampening rule the stack likely already approximates.
- **Explicitly do NOT port:** their calibration loader (broken role filter — the bug is instructive: verify DB role strings against INSERT sites), Laplace-at-midpoint binning (wang banding is better), prob-diff edge.

## 6. NOT-portable list (license-blocked)

Every file in the repo: Rust sources (15,254 LOC), migrations, docker-compose, Python training scripts (`train_model.py`), analysis SQL. No portion may be copied, vendored, or translated line-for-line. Only mathematical formulas verified against standard references (§3.1 Kelly, §3.3 Bayes) are reimplementable, and they are already subsumed by the shipped engine.

## 7. Honest caveats + verdict

- **Caveats:** calibration "prize" is real math but **proven inert at HEAD** (role-string mismatch: loader wants `consensus`, writers emit `bayesian`/`skeptic`/`catalyst`/`base_rate`) — a cautionary finding, not a transfer; fit-set design would partially calibrate market price even if wired; 20-sample activation is too thin for 10 bins; prob-diff edge and Laplace-at-midpoint are inferior to stack equivalents; all Kelly/Bayes math is standard and already shipped in the same or better form.
- **Verdict: SKIP (pre-Oct-8), with the single LR-aggregation concept queued for a future LLM-signal channel.** No license, no new math, calibration loop broken, everything of value already subsumed by shipped Phase B + v41 banding. Do not schedule any work against this repo during the measurement window.

---

*Audit per user doctrine: NO-LICENSE ⇒ read-only concept donor. Math verified line-by-line against standard binary-bet Kelly reference (f* = p − q/b) and multiplicative Bayes. No numbers fabricated; all stats quoted from source comments/README.*
