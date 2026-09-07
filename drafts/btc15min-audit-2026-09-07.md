# Repo Audit: aulekator/Polymarket-BTC-15-Minute-Trading-Bot

**Audit date:** 2026-09-07 · **Auditor:** Medusa CopyBot stack (ML-2 / short-TTR lane lens)
**Repo:** https://github.com/aulekator/Polymarket-BTC-15-Minute-Trading-Bot · clone: /tmp/btc15min (shallow, depth 1)

---

## 0. License verdict (BEFORE code)

- **GitHub API `license`: null → NO-LICENSE / all-rights-reserved.** README line 5 shows an **MIT badge**, but **no LICENSE file exists in the repo** (badge is a link to opensource.org, not a grant). The repo's own licensing is self-contradictory.
- **Verdict: READ-ONLY audit. Copy NOTHING.** Everything below is concept extraction for reimplementation. No code, no docstrings, no formulas copied verbatim into the stack.

## 1. Metadata snapshot (GitHub API, 2026-09-07)

| Field | Value | Note |
|---|---|---|
| license | **null** | NO-LICENSE despite MIT badge |
| stars / forks | 583 / 172 | high for a 2-week-old-at-push repo |
| created / pushed | 2026-02-15 / **2026-02-28** | **~191 days dormant** |
| commits (total) | **4** | whole repo is 4 commits, one ~week of dev |
| LOC | 12,756 Python | incl. ~1.5k LOC of tests |
| topics | bot, btc, polymarket-arbitrage-trading-bot, python, trading | "arbitrage" topic ≠ any arb code (none found) |
| default_branch | main | |

**Hype signals:** README references files that don't exist (`run_bot.py`, `scripts/`, `.env.example`); quick-start still says `git clone https://github.com/yourusername/...` (unfinished template); Redis live/sim mode-switch commands self-labeled "**-- not stable yet**"; "~75% win rate in early runs" FAQ claim with **zero in-repo evidence** (no results JSON, no logs/, no backtest artifacts); committed `__pycache__` (cpython-3.14).

## 2. What it is

A NautilusTrader-based Python bot for Polymarket's `btc-updown-15m-<unix_timestamp>` markets (900s UTC-aligned binary markets). README sells a "7-phase architecture" (data_sources → ingestion → nautilus_core → strategy_brain → execution → monitoring → feedback) with "multi-signal intelligence", "professional risk management", "self-learning".

**Code reality: two parallel stacks.**
1. **Demo `core/` pipeline** — clean phase directories + per-phase `test_*.py` files. The flagship `BTCStrategy15Min` (demo strategy wiring spike+sentiment+divergence) is **imported nowhere except tests**. The custom `core/nautilus_core` wrapper, `core/ingestion`, and `execution/execution_engine.py` are **unexercised demo/scaffold layers** (execution_engine.py imports risk_engine; bot.py does not import execution_engine).
2. **`bot.py` `IntegratedBTCStrategy`** — the actual live bot. Imports NautilusTrader's **official** Polymarket adapter (not the custom core wrapper), constructs **all six** signal processors + fusion + risk/performance/learning singletons, but its final committed logic **overrides all signal directions with a price trend filter** (see §3). Fusion is demoted to "informational context". Auto-restarts itself every 90 minutes (`restart_after_minutes = 90`).

The commit history tells the story: "adjust on live signals and execution engine" — the author iterated live against real markets for ~1 week, left an honest audit trail of failures in code comments ("This is why we were losing at prices near $0.50"), then abandoned the repo.

## 3. Verified machinery (formulas straight from source)

### 3.1 THE core finding — late-window trend-following, not signal-trading
The final bot does **not** trade on signal processors. Per `bot.py` (quote tick handler + `_make_trading_decision`):
- **Universe:** slugs `btc-updown-15m-{unix_900_boundary}`, generated for the prior interval through +24h; loaded via gamma markets with slug filter.
- **Trade timing:** fires once per 15-min sub-interval when `seconds_into_sub_interval ∈ [780, 840)` — **minutes 13–14 of each interval**, keyed to the market's own start timestamp (not wall clock).
- **Rationale (author's own words, bot.py ~710–727):** "At 13 minutes in, the UP/DOWN result is nearly decided. The price IS the trend… We're not predicting anymore, we're reading a nearly-resolved outcome." And the lesson: "At 30 seconds in, nobody knows which way BTC will move. The signals have no edge."
- **Trend gate replaces signals:** `price > 0.60 → buy YES; price < 0.40 → buy NO; 0.40–0.60 → SKIP` ("coin flip territory — this is where we were losing"). Trend confidence taken as `price` (or `1−price` for NO).
- **Size:** flat **$1.00** always. **Execution:** taker FAK/IOC **BUY-only** (there is no sell on Polymarket — you buy the YES or the NO token; "bearish" = buy NO). Liquidity floor: skip if ask (buy) or bid (sell) ≤ $0.02; FAK rejection ("no match") → reset timer, retry next tick.
- **Unverified economics:** buying YES at 0.71 with ~60s to resolution is only +EV if P(resolve YES | price 0.71 at T−60s) **exceeds the ask**. Price-as-probability ignores spread and favorite-longshot bias; no fees/gas in the model. The author's "price $0.71 → win rate ~71%" intuition is the classic naive proxy.

### 3.2 Signal processors (all six are constructed and run in bot.py, though gated downstream)
- **SpikeDetection** (weight 0.12): deviation `(p − MA20)/MA20` ≥ **0.05** → mean-reversion fade (up-spike → BEARISH), `conf = min(0.90, 0.50 + (|dev| − 0.05)·3.0)`, strength tiers at 5/8/12%. Velocity = 3-tick ROC ≥ **0.03** (only when |dev| < 3%) → momentum continuation, conf 0.57–0.65. Docstrings document re-scaling dollar-space thresholds (0.15 → 0.05) into probability space.
- **PriceDivergence** (weight 0.18) — two *contradictory* sub-signals: (a) **extreme fade:** p ≥ 0.68 with spot momentum ≤ +0.1% → BEARISH, `conf = min(0.80, 0.55 + extremeness·0.25)` where `extremeness = (p−0.68)/0.32`; symmetric below 0.32. (b) **momentum mispricing:** 0.35 ≤ p ≤ 0.65 and |spot_momentum| ≥ 0.3% (Coinbase vs latest-of-3 spot readings) → chase momentum, `conf = min(0.78, 0.55 + min(ms−1, 2)·0.08)`, `ms = |mom|/0.003`.
- **OrderBookImbalance** (weight 0.30, "best real-time signal"): `imb = (bid$ − ask$)/(bid$ + ask$)` over the YES CLOB book, ≥ **±0.30** → BULLISH/BEARISH; ignores books < $50 notional.
- **TickVelocity** (weight 0.25): 60s window ≥1.5% or 30s window ≥1.0% probability move.
- **DeribitPCR** (weight 0.10): OI-based put/call ratio ≤2 DTE, 5-min cache; PCR > 1.20 → contrarian BULLISH (fear), < 0.70 → contrarian BEARISH (greed).
- **SentimentAnalysis** (weight 0.05): Fear & Greed 0–25 contrarian bullish … 75–100 contrarian bearish.
- **Fusion** (`SignalFusionEngine`): `contribution = weight · conf · (strength/4)`; direction = larger side; `consensus_score = dominant_contrib/total_contrib · 100` — a **vote-concentration share, not a magnitude or a calibrated probability**; signals >5 min stale dropped; `is_actionable = score ≥ 60 ∧ conf ≥ 0.6`. bot.py lowers `min_score` to 40 and treats fusion as context, the trend gate as the real filter.
- Per-signal `score = (strength_weight·0.5 + confidence·0.5)·100` — uncalibrated blend.

### 3.3 Risk engine (`execution/risk_engine.py`) — decorative, no Kelly
- **No Kelly anywhere in the repo** (grep-verified). Fixed limits: $1/position, $10 total exposure, 5 positions, 15% drawdown, $5/day loss.
- `calculate_position_size`: `risk_amount = balance·2%`, `size = risk_amount · conf · (score/100)`, then **clamped to both ≥ $1.00 and ≤ $1.00** → always exactly $1. The "confidence-scaled sizing" is internally contradictory and never varies. bot.py says it outright: "Position size is always $1.00 — no variable sizing… The risk engine is still used to check that we don't already have too many open positions."
- SL 30% / TP 20% are defined on entry price but **never executed in the live path** (hold-to-resolution; no secondary exit), and in the sim they're moot (see 3.5).

### 3.4 Learning engine (`feedback/learning_engine.py`) — unexercised
Per-source (win rate, total P&L) → `performance_score = 0.6·win_rate + 0.4·min(1, |pnl|/100)` → exponential-ish weight lerp → normalize to Σ=1 with clamps 0.05–0.50. **Constructed in bot.py, never called** (no `optimize_weights()` call site). The "self-learning / automatically optimizes signal weights" README claim is dead code.

### 3.5 Paper-trading sim — **rigged-positive RNG, not a simulation**
`_record_paper_trade`: sim exit movement = `uniform(−0.02, +0.08)` for longs, `uniform(−0.08, +0.02)` for shorts → **80% positive mass by construction**; P&L computed as a *price-percentage move* on the token price (never resolves to 1.0, so binary payoffs are structurally excluded). **The FAQ's "~75% win rate in early runs" is an artifact of this biased RNG**, not a measured edge. Any "results" from this sim are meaningless.

## 4. Fit table vs roadmap gaps

Lens: ML-2 independent-entry ML lane (dual-track, features from 692M-trade tape) · short-TTR BTC lane (fast-resolving markets) · Phase Data-1 (external datasets) · Phase B (half-Kelly, Wang λ̂). Kelly window Sep 8–Oct 8 — nothing ships before Oct 8.

| # | Component (concept) | Verdict | Roadmap gap | Notes |
|---|---|---|---|---|
| 1 | **Late-window trend gate** — trade only minutes 13–14 of a 15-min binary interval, when `price>0.60→YES / <0.40→NO / 0.40–0.60 skip` | ⚪ **concept-only** | **short-TTR lane** (market-timing heuristic) | Highest-value takeaway. Directly testable against the 692M-trade tape: `P(resolve YES \| mid ≥ 0.60 at T−60..120s)` vs entry ask. Validates or kills the whole premise in ~1 dev-day, pre-commit. |
| 2 | **Deterministic slug universe** — `btc-updown-15m-{unix900}`, market-keyed sub-interval indexing, trade-once-per-(market,interval) key | ⚪ concept-only | short-TTR lane (market discovery/selection) | API-convention facts about Polymarket gamma markets, reimplementable independently. Confirms short-TTR market family exists and how to enumerate it. |
| 3 | **Probability-space threshold taxonomy** — MA-dev fade vs velocity continuation; extreme-fade bands 0.68/0.32; momentum-mispricing band 0.35–0.65; imbalance 0.30; no-trade zone 0.40–0.60 | ⚪ concept-only | **ML-2 feature registry** | Candidate features off the tape: distance-from-MA20, 3-tick ROC, book imbalance, spot-vs-poly momentum gap, F&G extremes. The fade-vs-chase *pairing* per regime is a genuinely useful feature-engineering idea. |
| 4 | **Weighted-vote fusion with staleness window** (≤5 min) + per-source weights | ⚪ concept-only | ML-2 ensembling | Vote-share consensus is uncalibrated (their flaw); ML-2 should learn per-signal weights from the tape, not the lerp. Structure is portable, numbers are not. |
| 5 | **Risk gate pattern** — per-position cap, max positions, daily loss, drawdown halt, liquidity floor | ❌ not portable | (already subsumed) | Medusa risk engine (Phase B half-Kelly + C-200) is strictly ahead. No Kelly/calibration in this repo to steal. |
| 6 | **Execution mechanics** (Nautilus Polymarket adapter, FAK/IOC taker buys, dummy-qty→$1-USD patch) | ❌ not portable | (Medusa Rust sidecar) | Only value: corroborates Polymarket gamma-market/adapter quirks (slug filter, gamma flag). Nothing for the sidecar. |
| 7 | **"Self-learning" weight optimizer** | ❌ not portable | (ML-2 supersedes) | Never invoked; would optimize over a rigged sim. Dead code — but honest precedent that per-source weight learning is a solved-shape problem. |
| 8 | **Paper sim + P&L model** | ❌ not portable | — | RNG-fabricated; binary payoff model wrong. Do not import even as reference. |
| 9 | Grafana dashboard / Redis mode-switch / 90-min restart | ❌ not portable | — | Ops patterns behind the Medusa dashboard + Node/TS ops; 90-min restart is a stability workaround, not a feature. |

## 5. Integration proposal (post-Oct-8, queue order)

**A. Tape test of the late-window trend premise (highest value, ~1 dev-day).** Query the 692M-trade tape: for `btc-updown-15m` family, conditional P(YES resolves 1 | mid ≥ 0.60 at T−60..120s) and the NO-side mirror, minus entry-ask. Outcome decides whether a short-TTR BTC rule lane is even worth papering. This is a *measurement*, flag-safe, no shipping.

**B. short-TTR BTC rule-beta lane spec (~2–4 dev-days, paper-only, flag-revertible).** If (A) clears the ask-cost hurdle: independent-entry rule lane on `btc-updown-15m` slug universe, entry only in T−120..−30s window, buy side indicated by trend gate, no-trade 0.40–0.60, flat sizing via Phase B half-Kelly on the *measured* λ̂-calibrated win prob (never the raw price). Effort: market-discovery module + paper lane in the existing Python research bot. Risk: **low if (A) passes, otherwise zero** — the entire edge thesis hinges on one conditional probability, which is exactly why we measure before building.

**C. ML-2 feature registry additions (~half dev-day).** Enter §3.2 thresholds/feature ideas (probability-space deviation, 3-tick ROC velocity, CLOB imbalance, spot-poly momentum gap, F&G band) as candidate ML-2 features to be evaluated off the tape alongside the existing backlog. Concept donor only — no numbers adopted as-is (all uncalibrated hand-tuned thresholds from a ~1-week live run).

## 6. NOT-portable list (license + substance)

- **All code and docstrings** — NO-LICENSE, all rights reserved. Read-only audit. (README's MIT badge is not a license.)
- Any **performance claim** ("~75% win rate") — rigged sim (§3.5), zero in-repo evidence.
- Risk sizing math, learning engine, fusion weights, signal thresholds as **numerical values**.
- Execution/adapter patches, Nautilus wiring, monitoring stack.
- Python 3.14 + NautilusTrader 1.222 dependency stack (stack already uses Node/TS + Rust + Python research bot).

## 7. Honest caveats + verdict

**Caveats:** (1) 4-commit, ~1-week-lived repo abandoned 191 days ago; README outruns the code (phantom files, unfinished template, MIT badge with no license file) — treat as a **concept donor with marketing overhead**, not a maintained project. (2) The demo 7-phase `core/` pipeline is largely unexercised scaffolding; the real bot is `bot.py` inline logic, itself full of contradictory leftovers (fade-the-extreme divergence processor vs chase-the-trend gate — the author kept both and let the trend gate win). (3) The core premise (late-favorite purchase at 60–120s to resolution) is **not validated anywhere** and ignores spread/favorite-longshot bias; the tape test in §5A is mandatory before any build. (4) No Kelly, no calibration, no backtest artifacts — nothing for Phase B. (5) All thresholds are hand-tuned from live pain ("FIXED: was 0.15…"), which makes them *hypotheses*, not parameters.

**Verdict: QUEUE — concept donor for the short-TTR lane + ML-2 feature registry, post-Oct-8.** Not adopt-now: nothing ships before the Oct 8 Kelly gate, and there is zero borrowable code under the license. Not skip: the late-window trend-persistence hypothesis and the deterministic 15-min slug universe are cheap, high-signal, and directly testable against the 692M-trade tape the stack already owns — the single best 1-dev-day measurement available to de-risk the short-TTR lane. Do the §5A tape test first; everything else in this repo is commentary.

*Nothing from this repo was copied. All concepts above are re-expressed in the stack's own terms.*
