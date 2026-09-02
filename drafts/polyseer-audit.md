# Polyseer Audit — Bayesian Evidence Aggregation for the Sentiment Layer

**Status:** COMPLETE — 2026-08-31. Repo: github.com/yorkeccak/Polyseer ("Polymarket alpha at the speed of now").
**Audited:** the forecasting core (`src/lib/forecasting/*`), the analyst agent (`src/lib/agents/analyst.ts`), and the pipeline architecture. Cloned to /tmp/polyseer.

---

## 1. What Polyseer actually is

A Next.js app that takes a Polymarket/Kalshi URL and produces a structured research report: multi-agent research (researcher/orchestrator/analyst/reporter agents over the **Valyu research API + OpenAI gpt-4o/gpt-5**), evidence quality scoring, and **mathematical probability aggregation**. Self-hostable with SQLite.

**The valuable part is NOT the LLM pipeline** (opaque, gpt-5-dependent, duplicates what the copybot's research bot already does) — it's the **pure forecasting core** (`src/lib/forecasting/`, ~150 lines, zero dependencies):

## 2. The aggregation machinery (verified formulas)

**Evidence → log-likelihood ratio** (`evidence.ts`):
```
logLR = polarity × typeCap × (0.45·verifiability + 0.25·corroboration + 0.15·consistency + 0.15·recency)
typeCap: A=1.0, B=0.6, C=0.3, D=0.2   (evidence-tier caps)
corroboration: r = 1 − e^(−k₀·k)       (independent corroborations → 0..1)
recency: 1/(1 + days/120)               (120-day half-life)
```

**Aggregation** (`aggregator.ts`) — logit-space Bayesian updating with correlation correction:
```
l = logit(p₀)                            # prior (default from market or 0.5)
per cluster (grouped by originId):       # correlated sources share a cluster
  ρ = 0.6 if m>1 else 0                  # default intra-cluster correlation
  mEff = m / (1 + (m−1)·ρ)               # effective independent count
  contribution = mEff × trimmedMean₍₂₀%₎(logLRs)
  l += contribution
pNeutral = sigmoid(l)                    # evidence-only posterior
pAware   = sigmoid(logit(pNeutral) + 0.1·logit(pMarket))   # market blended LAST
```
Influence: leave-one-out ΔP per evidence item. This is the standard **correlation-aware log-odds aggregation** from the forecasting literature (Karger et al. effective counts; Metaculus-style weighting) — the formulas themselves are public methodology, **not** novel proprietary code.

## 3. Audit findings

| Aspect | Verdict |
|---|---|
| Aggregation math | ✅ Sound, clean, dependency-free, unit-testable — logit-space LLR accumulation with ρ-corrected effective counts and trimmed means |
| Market firewall | ✅ Market price blended last at 10% weight — prevents the estimate from just echoing the market (circularity guard) |
| Quality rubric | ✅ Ready-made: tier caps + verifiability/corroboration/consistency/recency weights — maps 1:1 onto RegulatorySignal's confidence field |
| LLM agent layer | ❌ Not portable: OpenAI models (stack is DeepSeek), Valyu API dependency, per-query cost, opaque |
| **License** | ❌ **NO LICENSE FILE** — all-rights-reserved. Do NOT copy code; reimplement the formulas (~80 lines of standard math) |
| Recency/nice-authority/pathway hints | ⚪ Heuristic multipliers on the core; ideas worth borrowing conceptually, not verbatim |

## 4. Why this matters for C-200 (the fit)

The research bot's RegulatorySignal currently feeds the scorer as a **crude ±25/±10/−20 copyScore boost, clamped at 79 since v34** (because it was unvalidated). Polyseer's core is the principled replacement — the missing "sentiment → calibrated probability" bridge:

- **Signals → Evidence**: polarity = sentimentScore, tier = source type, verifiability = confidence, corroborations = distinct independent signals in the category/window, recency = processedAt.
- **Aggregate → posterior**: p₀ = market price; aggregate the category's recent signals → pNeutral → **delta = posterior − market** = a *calibrated sentiment edge* in probability points, instead of a fixed score boost.
- **Correlation correction solves the double-counting problem** their boost has always had: a bill + its news coverage + a Quiver insider trade all reflect the SAME event — naive boosts stack them; ρ=0.6 cluster correction doesn't.
- **Firewall preserved**: the sentiment delta is computed against the market (the delta IS the signal), so a neutral signal produces zero edge — no more "0.0 FR notices masking" hacks.

## 5. Integration proposal — Phase A2 (evidence aggregation for sentiment)

1. Reimplement `forecasting/` in TS (`src/lib/forecasting/`): logit/sigmoid, effectiveCount, trimmedMean, evidenceLogLR, aggregateNeutral (~80 lines, standard math, methodology-attributed).
2. Map RegulatorySignal → Evidence in a small adapter; per research category, aggregate the last 7d of opinionated signals.
3. In `score-trades.ts`: replace the Phase-8 ±boost with `delta = pNeutral − pMarket` → convert to a scoring adjustment (e.g., copyScore += delta·scale, or fold into the premium overlay as a second calibrated input). The v34 clamp can then be relaxed or kept as a safety bound — the calibration comes from the math.
4. Measurement-first: log `[SENTIMENT] prior=… posterior=… delta=…` per boosted decision; compare outcomes vs the old boost regime over 2 weeks (aligns with the biweekly calibration cadence).

**Effort:** ~half day + 2-week observation. **Risk:** low (paper-only, additive, revertible by ruleset flag).

---

## 6. Metaforecast review (2026-08-31) — no dependency

Checked before Phase A2 implementation per user request: **Metaforecast (QURI) was
discontinued on 2026-07-09** — the website and public GraphQL API are gone; only an
archived DB (available from QURI on request) and MIT-licensed source remain (Squiggle
monorepo, `apps/metaforecast`). It was a search/aggregator over 18 platforms with
per-platform **subjective** ★ quality ratings (`calculateStars()`), daily fetches, and
Elasticsearch — **no calibrated cross-platform posterior** and no log-odds aggregation
machinery. Verdict: no live data source to integrate (a Polymarket-vs-consensus
divergence feed would need direct Kalshi/Manifold/Metaculus APIs — separate phase), and
no methodology that improves on the Polyseer core above. Phase A2 proceeds unchanged.

