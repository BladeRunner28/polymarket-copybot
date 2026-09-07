# digital-oracle — Adoption Audit (2026-09-07)

**Repo:** komako-workshop/digital-oracle · https://github.com/komako-workshop/digital-oracle
**Audit lens:** Medusa CopyBot paper stack (~/polymarket-copybot) — v39 Bayesian log-odds evidence aggregation w/ market firewall; C-200 compounding; Phase-B half-Kelly; Kelly window Sep 8–Oct 8 → **nothing ships before Oct 8**.
**Auditor note:** findings below come from reading the cloned source at `/tmp/digital-oracle` (commit `a63e4c1`, Jul 27 2026) and running its test suite locally (246/246 pass, fixture replay, no network). Not from the README.

---

## 1. What it is

An "AI agent skill" (Claude Code / Cursor / Codex / OpenClaw) that answers macro/probability questions (housing, gold, BTC, geopolitics, recession, "is X overpriced") by fetching **trading data** from ~16 keyless public endpoints and having the **LLM synthesize** a structured multi-signal probability report.

Architecture is two layers, cleanly separated:

1. **Deterministic Python library** (`digital_oracle/`, ~2,700 LOC + tests): typed providers that fetch + normalize market data into frozen dataclasses, plus infra (threaded `gather`, TTL cache, proxy pool, HTTP retry, record/replay snapshot HTTP for offline tests).
2. **Prompt layer** (`SKILL.md`, 352 lines): methodology, signal menus per question type, and the **entire aggregation "math"** — which is heuristic prose, not code.

**Critical structural finding:** there is **no aggregation, scoring, weighting, or calibration code anywhere in the repo.** Greps for `kelly|edge|risk`, `calibrat`, `weight|score|aggregat|bayes|log.odds|posterior` return nothing but the CNN Fear&Greed composite score and yfinance max-pain weighting. The "cross-validate 13 sources into one calibrated answer" claim is executed by the LLM following SKILL.md Step 5 instructions ("Don't vote by majority… weight judgment… time alignment"), producing the probability table in the report template. There is no numeric fusion step; no per-source reliability weights; no backtest or calibration loop.

---

## 2. Verified machinery (from source)

### 2a. Probability normalization per source (the real deterministic core)

| Provider | Probability source (verified in code) | Keyless? |
|---|---|---|
| Polymarket (`polymarket.py`) | Gamma `/events` `outcomePrices` parsed as decimal 0–1 → `OutcomeQuote.probability`; `yes_probability` helper; `midpoint` = (bestBid+bestAsk)/2 | ✅ gamma-api + clob public |
| Kalshi (`kalshi.py`) | `yes_probability` = mid(yes_bid, yes_ask), fallback `last_price`; `_cent_probability` divides cents by 100; orderbook derives implied yes_ask = 1−no_bid, yes_bid = 1−no_ask | ✅ api.elections.kalshi.com trade-api v2 public market data |
| CME FedWatch (`cme_fedwatch.py`) | Parses `fed-funds-target.json`, `prob/100` per target range | ⚠️ **403-blocked** — repo's own SKILL.md says unusable from every host tested; dead path |
| Options (yfinance provider) | **Black–Scholes Greeks, pure stdlib `math.erf` — verified correct:** `d1 = (ln(S/K) + (r+σ²/2)T)/(σ√T)`, `d2 = d1 − σ√T`; call Δ = N(d1), put Δ = N(d1)−1, Γ = φ(d1)/(Sσ√T), Vega per 1pp (÷100), θ per calendar day (÷365). | Requires `pip install yfinance` (external dep) |
| Treasury (`treasury.py`) | Yield curves (nominal + real), `.yield_for(tenor)`, `.spread(long, short)` (e.g. 10Y−2Y), breakevens via fiscaldata + home.treasury CSV | ✅ |
| CFTC COT (`cftc.py`) | Socrata `publicreporting.cftc.gov/72hh-3qpy` — commercial/spec positioning per commodity | ✅ |
| EDGAR (`edgar.py`) | `company_tickers.json` CIK map + `/submissions` + Form-4 insider transactions; full-text via `efts.sec.gov` | ✅ (UA contact email required — SEC fair access, not a key; `EDGAR_USER_EMAIL`) |
| Deribit (`deribit.py`) | Futures term structure w/ `basis_vs_perpetual` + `annualized_basis_vs_perpetual`; option chain w/ ATM strike; books | ✅ public API |
| CoinGecko | spot prices, mcap, dominance | ✅ free tier, ~10–30 req/min |
| Fear&Greed (`fear_greed.py`) | CNN dataviz endpoint → single 0–100 score + rating bands | ✅ |
| BIS | policy rates, credit-to-GDP **gap** (deviation from trend, not level) | ✅ stats.bis.org |
| World Bank | GDP/indicators (1–2 yr lag documented) | ✅ |
| Eastmoney | CN A-share quotes / order-size fund flow (institutional vs retail) / sector rotation / OHLCV; Tencent fallback for history | ✅ |
| Stooq / Yahoo prices | CSV / yfinance price history | ✅ / yfinance dep |
| Web search (`web.py`) | DuckDuckGo HTML scrape + page fetch (VIX, MOVE, CDS, HY OAS etc. are only reachable this way) | ✅ no key, fragile |

**Verified claim check:** "13 of 15 providers zero API keys, zero deps" ≈ true — no `Authorization`/`api_key`/`Bearer` anywhere in providers; EDGAR's UA-email is a fair-access courtesy not a key. Two providers need the `yfinance` pip dep.

### 2b. Normalization conventions

- Coercion layer `_coerce.py`: `_coerce_float`/`_coerce_int` reject bool/NaN/inf/empty → `None`. Typed frozen dataclasses everywhere; `raw` payload preserved on entities for debugging.
- **No sanity/arbitrage layer:** e.g. a Polymarket market's YES+NO `outcomePrices` are not checked to sum ≈ 1; Kalshi yes vs no quotes are not cross-checked for consistency; no liquidity/volume filter *in code* (the "$100K volume discount" rule exists only as SKILL.md prose).
- Event selection helpers: `PolymarketEvent.primary_market()` ranks live>volume24h>volume>liquidity; `KalshiEvent.most_active_market()` by vol24h/vol/OI. These are the closest thing to "signal quality weighting" in the repo — heuristic ranking, not math.

### 2c. Infra (well-built, stdlib-only)

- `concurrent.gather()` — ThreadPoolExecutor fan-out with per-task exception capture and partial-failure semantics (`result.get_or(key, None)`).
- `cache.TTLCache` — thread-safe, per-entry TTL, factory runs outside lock, max 512 entries.
- `http.UrllibJsonClient` — urllib-only, 3 retries, timeout 20 s, optional `ProxyPool` egress rotation for IP-throttled hosts (Eastmoney).
- `snapshots.py` — `RecordingHttpClient`/`ReplayHttpClient`: record live API responses to disk, replay in tests. This is why 246 tests run in 0.22 s offline. **Genuinely nice pattern.**
- `scripts/regression_runner.py` — manual live-workflow smoke tests (not CI; repo has **no CI, no pyproject/setup, no packaging** — plain importable dir).

### 2d. Aggregation — the answer to the audit question

**digital-oracle has no numeric aggregation to compare against v39.** Its "single calibrated answer" is SKILL.md Step-5 heuristics: four analysis dimensions (signal interpretation, cross-validation, time alignment, weight judgment), an explicit "don't vote by majority" rule, and a hard report template (layered signal tables → contradiction analysis → probability scenario table → conclusion w/ sub-conclusions + risk factors).

**vs. the adopting stack's v39** (`src/lib/forecasting/index.ts`, verified): v39 is real quantitative aggregation — per-evidence `logLR = polarity × typeCap × (0.45·verif + 0.25·corrob + 0.15·consist + 0.15·recency)`, corroboration `1−e^(−k₀k)`, recency `1/(1+d/120)`, cluster correlation ρ=0.6 with effective-count shrinkage `mEff = m/(1+(m−1)ρ)`, logit-space update on the market-price prior, trimmed-mean(20%) per cluster, and the market firewall `pAware = sigmoid(logit(pNeutral) + 0.1·logit(pMarket))`.

**Conclusion: v39 strictly dominates digital-oracle's aggregation design in every dimension** — it is numeric, correlation-aware, prior-anchored with a firewall, and already calibrated for sentiment. DO adds **zero aggregation technology** beyond what exists. What DO does add is a **breadth of keyless market/positioning fetchers** and the "price-only evidence, ≥3 independent dimensions, time-stratify, liquidity-discount" *doctrine* — the doctrine is a concept, not code.

---

## 3. Fit table vs roadmap gaps

Roadmap context verified from the adopting repo: research bot ingests Quiver/Congress/GovInfo/GDELT; adapters are Polymarket-only (`src/lib/adapters/`); Kalshi appears only as bespoke rules/scripts (reprice-kalshi-92, whale-review drafts), **no general Kalshi read adapter**; no CFTC/Deribit/CoinGecko/F&G/Treasury-curve/EDGAR anywhere in `src/lib`.

| Component | Verdict | Roadmap gap it fills | Effort | Risk |
|---|---|---|---|---|
| **CFTC COT provider** (`cftc.py`, ~143 LOC, weekly keyless positioning) | **ADOPT (queue)** | Only genuinely new *non-price* evidence class in DO. Positioning divergence maps naturally to v39 evidence polarity (spec net Δ vs price Δ). Research bot currently has zero positioning input. | Port ~0.5 day + evidence adapter + tests | Low. Weekly cadence, C-tier typeCap, flag-revertible behind research-signal webhook. Does not touch market-prior doctrine (positioning ≠ price). |
| **Record/replay snapshot test harness** (`snapshots.py`) | **ADOPT (queue)** | Research bot has no offline-test pattern for fetchers; this enables CI-safe fetcher tests like DO's 246. | ~1 day to retrofit on one fetcher | Low |
| **EDGAR Form-4 provider** (`edgar.py`) | **Concept-only** | Insider cadence is a real non-price signal — but Quiver (already ingested) likely covers insider trades; check overlap before building. UA-email requirement is trivial. | — | Duplication risk |
| **Kalshi read provider** (`kalshi.py`) | **Concept-only / conditional** | General keyless Kalshi market feed (KXFED rate path, SPX ranges) as *alternative-venue prior cross-check*. But v39's firewall doctrine treats market price as prior, not evidence — adding Kalshi prices as evidence violates it; adding as a second prior needs a doctrine decision. Stack already has bespoke Kalshi touchpoints. | 1 day if approved | Medium (doctrine conflict, not code) |
| **Treasury curve / BIS credit-gap / World Bank / Deribit basis / CoinGecko / Fear&Greed** | **Concept-only** | All price- or long-horizon-derived → redundant with market-prior under v39 doctrine. Only plausible use is a *regime gate* (e.g. de-risk copy size when 10Y−2Y inverts or BTC basis flips negative) — a sizing-layer feature, not evidence. Real product decision, not a port. | — | Doctrine |
| **BS greeks module** (`black_scholes_greeks`, stdlib erf) | **Concept-only** | Correct, tidy, tiny (~50 LOC) — but copy bot trades no options. Steal the formula file only if a deltas-as-probability need ever appears. | 0 | ~0 |
| **`gather` / TTL cache / proxy pool / typed-normalization pattern** | **Concept-only** | Stack already has its own equivalents (research bot fetchers, TS side). Patterns worth reading; code is Python, stack is TS — no direct port. | — | — |
| **SKILL.md methodology + report template** | **Concept-only** | "≥3 independent dimensions," "time-stratify signals," "liquidity <$100K discount," "don't vote by majority" — good doctrine, already ≈ the research bot's philosophy; v39 supersedes the weighting half. | — | — |
| **LLM agent layer** (question decomposition → signal routing → prose synthesis) | **NOT-portable** | Duplicates the user's research bot + qwen2.5:7b shadow A/B. Confirmed non-portable as predicted. | — | — |
| **CME FedWatch provider** | **NOT-portable** | Dead (403 from all hosts — repo self-documents). Kalshi KXFED is the replacement. | — | — |
| **Eastmoney provider** (CN A-share) | **NOT-portable** | Out of venue scope for a Polymarket copy stack. | — | — |
| **yfinance-based providers** (Yahoo/YFinance options) | **NOT-portable** | External dep + options chains irrelevant to copy scoring. | — | — |
| **DDG web-search scrape** (`web.py`) | **NOT-portable** | Fragile HTML scraping; research bot already has structured ingestion (GDELT/Quiver) for the same gap-filling role. | — | — |

---

## 4. Integration proposal (queue, post-Oct-8)

**Phase 1 — CFTC COT as C-tier evidence (the one real adopt):**
1. Vendor `cftc.py` + `_coerce.py` + a trimmed `http.py` into the research bot as `src/.../macrotape/cot.ts`-equivalent — but note DO is Python and the research bot is Python (`scripts/*.py`), so **direct Python import is feasible**: copy modules under a `third_party/digital_oracle/` dir with LICENSE attribution (MIT), or reimplement (~143 LOC).
2. Map weekly COT rows → v39 `EvidenceItem`: cluster=`cftc`, polarity from spec-net Δ vs price Δ sign agreement, typeCap=C (0.3) or B if validated, verifiability high (primary regulator data), corroboration 0 until a second positioning source exists.
3. Ship behind the existing research-signal webhook flag. Weekly cadence → trivial load.
4. Validate over 2–4 weeks against v39 outcome logs (calibration scripts already exist) before promoting tier.

**Revert:** delete the evidence category + flag — no sizing-path changes, cannot hurt the C-200 or the Kelly window.

**Phase 2 (optional, needs a doctrine decision):** regime-gate inputs (Treasury 10Y−2Y, BTC basis) as a *sizing* context flag in the Rust sidecar or TS scorer — explicitly NOT v39 evidence. This is the only framing under which DO's macro breadth is usable without breaking the market firewall.

**Effort total:** Phase 1 ≈ 1–2 days all-in; Phase 2 ≈ 2–3 days incl. backtest. **Risk:** low (Phase 1), medium-doctrine (Phase 2). Nothing here touches Oct-8 Kelly shipping.

---

## 5. NOT-portable list

- LLM agent layer + SKILL.md workflow (duplicates research bot; the repo's actual product is the prompt).
- CME FedWatch provider (403-blocked, dead).
- Eastmoney CN providers + `to_secid` (wrong venue scope).
- Yahoo/YFinance providers (external pip dep; options chains unused by a copy bot).
- DDG HTML web-search scrape (fragile; redundant ingestion path).
- "13-source calibrated single answer" framing itself — no calibration machinery exists to port.
- Any expectation of aggregation math: **there is none in code**; synthesis is prompt-grade.

---

## 6. Honest caveats + verdict

**Caveats:**
- The marquee capability (multi-source calibrated probability synthesis) is **not implemented in code** — it is an LLM following a well-written prompt. Any adoption must treat this repo as a *data-fetch library + doctrine doc*, never as a forecasting engine.
- No calibration, no backtest, no per-source reliability weighting, no no-arb sanity checks on outcome prices; liquidity filters exist only as prose.
- Young repo (created Mar 2026, pushed Jul 26 2026 = 43 d ago), 810★/164 forks, **no CI, no packaging**, manual regression script. Provider URLs hardcoded; several upstreams (CME) already broken.
- `outcomePrices`-as-probability and Kalshi mid-as-probability are thin conventions (no decay/smoothing, no volume weighting) — fine for read-only context, useless as an edge source.
- Running the repo's suite locally: 246/246 pass in 0.22 s against recorded fixtures (no network) — parsers are solid against the *recorded* world, unproven against the live one (regression_runner is manual).

**Verdict: QUEUE (not adopt-now, not skip).**
- Against roadmap order: nothing before Oct 8 (Kelly window) — correctly, since nothing here is urgent or sizing-critical.
- Post-Oct-8, the single worthwhile adopt is **CFTC COT as a C-tier positioning evidence source** (+ the snapshot-record/replay test pattern), ~1–2 days, flag-revertible, adding the first non-price, non-text evidence class to v39 (which today is regulatory/news text + market prior).
- Kalshi/Treasury/BIS/Deribit breadth: only via an explicit *regime-gate* doctrine decision (sizing context, not evidence) — queue behind that decision.
- Everything else: concept-only or not-portable. The stack's v39 aggregation already exceeds DO's design; this audit found **no aggregation technology gap** that DO fills.
