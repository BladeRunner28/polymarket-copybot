# FlashAlpha-lab/awesome-options-analytics — Audit for Medusa CopyBot

**Status:** COMPLETE — 2026-09-01. Repo: github.com/FlashAlpha-lab/awesome-options-analytics.
**License:** ✅ **CC0 1.0** (public domain — the list itself is freely usable).
**Content:** curated link list, 154 entries / 18 sections, single README (~39KB). No code in this repo.

---

## 1. Verdict

**Low direct applicability — but 3 genuinely actionable items.** The domain
mismatch is fundamental: the list is about **listed equity options analytics**
(greeks, volatility surfaces, dealer gamma, multi-leg structures), and the
copybot trades **binary prediction-market contracts** (Polymarket/Kalshi) —
which have no greeks, no IV surface, no options inventory to dealer-hedge.
~12 of 18 sections don't transfer. The value is concentrated in the **Kelly
Criterion section** (feeds Phase B) and one **fill-simulator methodology**
(feeds Phase D2).

## 2. Meta-finding (trust weighting)

~**40% of entries are FlashAlpha's own products** (every section leads with a
flashalpha.com link carrying `utm_campaign` tracking — a marketing funnel
disguised as a curated list; the Contributing section even bans the
self-promotion the list itself practices). This doesn't invalidate the
non-FlashAlpha content, but it means: **treat the list as a sales page for a
paid API, harvest only the third-party items.** The three FlashAlpha repos
worth reading (below) are all **MIT**, so their code is usable regardless.

## 3. Relevance tiers

### HIGH — actionable now

| Item | What | Why it matters |
|---|---|---|
| **Thorp (2006), "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market"** (Cambridge, free chapter) | Definitive practical treatment of Kelly incl. fractional Kelly, drawdown control, binary bets | **Phase B ships Sep 15** — this is the canonical reference for the exact problem (binary contracts, edge, fractional sizing). Read before the refit. |
| **flashalpha-fill-simulator** (MIT, engine-agnostic, zero deps) | Limit-order fill simulator: post-and-wait limits, **stale-quote guards**, deterministic same-bar tiebreaks, patient-then-cross exit | **Phase D2 (Cox-PH paper fill model)** solves the same problem for prediction markets: P(fill) from book context. Steal the methodology, adapt to L2 book data. |
| **flashalpha-examples `06_kelly_sizing.py`** (MIT) | Runnable Kelly sizing integrating market data | Reference pattern for Phase B sizing implementation (alongside octagon-audit.md + oracle3). |

### MEDIUM — conceptual only

| Item | Concept that transfers | Caveat |
|---|---|---|
| **Expected-move / event decomposition** (earnings section) | Split market-implied move into "event jump vs baseline diffusion" — the analog of pre-event premium (election nights, Fed days) decaying into resolution | No tool transfers; the concept could inform a "pre-event premium decay" feature for event markets. |
| **Realized-vol estimators** (Garman-Klass, Parkinson, Yang-Zhang — pandas-ta/arch) | Robust volatility-of-price-drift measurement | Could sharpen the drift gates (drift-too-late skips are 34.5% of the skip mix). |
| **Uniform 0-100 decision envelope** (strategy signals) | Normalizing heterogeneous signals to one score scale with ranked structures | The copybot already does this (copyScore 0-100, calibrated delta). Confirms the pattern, adds nothing. |
| **Risk-adjusted screening formulas** (`harvest_score/(dealer_flow_risk+1)`) | Score-per-unit-risk ranking pattern | Already effectively done via copyScore/caps; a nice formula to reuse in the ML-1 feature set. |

### LOW / NONE — skip

- **Options pricing & greeks** (Black-Scholes, binomial, MC, QuantLib, py_vollib, LetsBeRational) — binary contracts need no greeks.
- **Volatility surfaces / SVI / SABR** — no surface to model on prediction markets.
- **GEX / dealer positioning / DEX/VEX/CHEX** — no market-maker options inventory to infer from; the microstructure is different (CLOB liquidity, not gamma hedging).
- **0DTE mechanics** — the short-TTR lane (2–72h) is the *analog*, but 0DTE dealer-hedging dynamics don't transfer.
- **Multi-leg structures / dispersion / macro VIX regime** — no multi-leg instruments; Kalshi/Polymarket have no VIX analog worth porting.
- **Data providers** (CBOE, OptionMetrics, ORATS, Polygon, Thetadata, IBKR…) — the system already ingests Polymarket/Kalshi public APIs; these are listed-equities feeds. Polygon is the only generic one, and there's no current need.
- **FlashAlpha paid API** (GEX/VRP/screener/signals, ~40 entries) — proprietary, equities-only, subscription; not a fit for a keyless Polymarket stack.

## 4. Recommendations

1. **Before Sep 15:** read Thorp (2006) Kelly chapter → add to Phase B card as a
   reference alongside octagon-audit.md and oracle3.
2. **Phase D2 (post-mid-Sep):** read flashalpha-fill-simulator (MIT) methodology
   → borrow stale-quote guards + deterministic tiebreak + patient-then-cross
   exit for the Cox-PH fill model over data/l2/ books.
3. **Phase ML-1 feature list:** add the risk-adjusted formula pattern
   (`score/(risk+1)`) and realized-vol estimators as candidate features.
4. **Skip the rest** — including the FlashAlpha API itself.

## 5. Files

- Repo: /tmp/awesome-options (README.md, CC0)
- This audit: `drafts/awesome-options-audit.md`
