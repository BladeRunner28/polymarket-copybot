# oracle3 Technical Audit + Wang Transform Calibration on Copybot Data

**Status:** COMPLETE — 2026-08-31. Repo: github.com/YichengYang-Ethan/oracle3 (Apache-2.0, 251★, 633 tests, SSRN working paper: Yang 2026, "Pricing Prediction Markets: Risk Premiums, Incomplete Markets, and a Decomposition Framework").
**Tooling:** cloned to /tmp/oracle3; calibration ran against `prisma/dev.db` via oracle3's own `WangMLE` (numpy/scipy venv at /tmp/wangcal, script `/tmp/wangcal/calibrate.py`).

---

## 1. What oracle3 actually is (verified from source)

- **Pricing model:** `p_mkt = Φ(Φ⁻¹(p*) + λ)` — market price = physical probability distorted by a probit-space risk premium λ. Fair value = `Φ(Φ⁻¹(p_mkt) − λ)`.
- **Calibration:** `wang_mle.py` — pooled + hierarchical MLE (probit-offset regression), analytic gradients, robust/clustered SEs, LR tests, AIC/BIC. Handles 300K obs in ~2s. Paper coefficients: λ_Poly=0.166, λ_Kalshi=0.187, pooled 0.183; hierarchical λ_i = 0.259 − 0.072·ln(1+V) + 0.143·ln(1+D) − 0.477·|p−0.5| (+ spread, n.s.); time-varying λ(τ) with premium half-life at 33–77% of contract life.
- **Key insight (their Table 4):** very-high-volume markets (>$10K) have λ≈0 — premium competed away; the premium alpha lives in $500–$10K markets (λ 0.25–0.35).
- **Sizing (`trading/sizing.py`):** Kelly with model edge (YES: `(p*−p_mkt−fee)/(1−p_mkt)`; NO: `(p_mkt−p*−fee)/p_mkt`), capped at 0.15×capital, scaled by model confidence, volume-tier gated, optional empirical-win-rate blend.
- **Strategies:** 8 constraint-based arb (cross-market, exclusivity P(A)+P(B)≤1, implication, conditional), 2 model-driven, LLM-agent strategies; multi-venue (Kalshi/Polymarket/Solana).
- **License:** Apache-2.0 — reusable components, no restriction.

## 2. Calibration on copybot's own paper data (2026-08-31)

Model fit on finished trades (entry price, binary outcome). λ̂ > 0 = entries systematically OVERPRICED (premium drag); λ̂ < 0 = entries beat the market (info edge).

| Sample | N | λ̂ (SE) | z | Win% | Premium drag/contract |
|---|---|---|---|---|---|
| ALL / Polymarket | 8,315 | **−0.112** (0.016) | −6.8 | 63.6% | −0.034 |
| ALL / Kalshi | 73 | **+0.309** (0.156) | +2.0 | 34.2% | **+0.116** |
| STANDARD / Polymarket | 7,392 | −0.121 (0.018) | −6.9 | 64.9% | −0.036 |
| BANKROLL_200 / Polymarket | 923 | −0.051 (0.046) | −1.1 | 52.7% | −0.018 |
| C-200 entry <0.20 | 43 | **−1.204** (0.198) | **−6.1** | 51.2% | **−0.387** |
| C-200 entry 0.20–0.40 | 193 | −0.241 (0.091) | −2.6 | 39.4% | −0.088 |
| C-200 entry 0.40–0.60 | 441 | **−0.018** (0.060) | −0.3 | 50.1% | −0.007 |
| C-200 entry 0.60–0.80 | 152 | **+0.248** (0.104) | +2.4 | 59.9% | **+0.091** |
| C-200 entry 0.80–1.00 | 94 | **+0.355** (0.148) | +2.4 | 80.9% | **+0.079** |

## 3. What this means for C-200 (the strategy physics, in their own numbers)

1. **The copy edge is a long-shot phenomenon.** Entries <$0.20 carry λ̂=−1.20 (z=−6.1) — the copied whales' long-shot picks resolve *far* better than their prices imply. This is the model-level confirmation of the daily report's "+$185.75, only +EV bucket". The v37 ×1.5 long-shot boost is directionally right and likely **too small**.
2. **The 0.40–0.60 dead zone is exactly where λ≈0.** No premium drag, but also no measurable info edge (z=−0.31) — 441 trades of the bot's largest bucket with nothing behind it. The v37 ×0.5 halving is validated; the model says these entries are the least informative in the book.
3. **Mid-high entries pay premium even when they win.** 0.60–0.80 and 0.80–1.00 both have significantly positive λ̂ (+0.25/+0.35) — 59.9% and 80.9% win rates yet still negative EV from the premium paid. Confirms the report's late-stage buy finding and the maxEntryPrice gate.
4. **The Kalshi bleed is a risk-premium effect, not bad luck.** λ̂=+0.31, 34.2% win → overpriced entries on a venue where the copied whales carry no edge. The v37 circuit breaker (currently tripped) is exactly the right mechanism.
5. **Polymarket copying as a whole beats the market** (λ̂=−0.11, z=−6.8 across 8.3K trades) — the signal source is real; C-200 just dilutes it with fair-priced mid-band copies.

## 4. Integration proposal (3 phases, increasing effort)

**Phase A — premium-adjusted copy filter (recommended first; ~half day, zero risk):**
In `score-trades.ts`, after scoring, compute the entry's premium drag using a bucket λ̂ table calibrated from resolved paper trades (refit monthly via cron). Add the premium as a scoring input:
- λ̂ strongly negative (info edge, e.g. <0.20 entries): size boost (up from ×1.5).
- λ̂ ≈ 0 (dead zone): keep the halving; log as "no-edge entry".
- λ̂ ≥ 0.15 (premium drag): shrink size or add a `risk` tag ("entry embeds premium") — data-collecting first, gating later.
Requires nothing new from the API: entry price, category, venue, TTR, volume, spread are already in MarketState. The λ table lives in rules or a small JSON, versioned like the ruleset.

**Phase B — Kelly sizing replacing band sizing (medium):**
Port `ModelInformedSizer` semantics (Apache-2.0) into TS: edge = bucket-λ-adjusted premium, Kelly fraction capped at 0.15×bankroll, confidence-scaled. Replaces the heuristic band multipliers with edge-proportional sizing while keeping paper caps. Their empirical win-rate blend is directly available (they track win rate per bucket).

**Phase C — constraint-based cross-venue arb (the Kalshi redemption; larger):**
Port the exclusivity/cross-market/implication invariants: when the same event trades on Polymarket AND Kalshi (or YES+NO sum ≠ 1), trade the violation instead of directional routing. This converts the currently dead Kalshi leg into the market-neutral arb the original Phase-5 design intended.

## 5. Caveats

- Bucket λ̂ are in-sample (fit and evaluated on the same trades). The pattern is robust in sign (matches the paper's structural findings + the bot's PnL buckets), but Phase A should be instrumented as measurement before any hard gating.
- The paper's pooled λ (0.183) does NOT transfer directly to copy-trading entries (whale info shifts it negative) — always calibrate on the bot's own entries, not the paper's constants.
- Very-high-volume markets: λ≈0 means premium alpha unavailable there; for copies this is fine (whale info is the edge), but the model's confidence should be lower on mega-liquid markets.
