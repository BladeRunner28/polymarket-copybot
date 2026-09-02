# Homerun Audit — braedonsaunders/homerun

**Status:** COMPLETE — 2026-08-31. Repo: github.com/braedonsaunders/homerun (**AGPL-3.0**, 176★, actively maintained — updated 2026-08-26). Cloned to /tmp/homerun.
**What it is:** a full-stack "operating system for prediction market alpha" — Python/FastAPI backend + React/TS frontend + Postgres/Redis/Docker. 35 strategy files, 16 background workers, L2-book-replay backtester with a Cox-PH fill model, whale copy trading + confluence + 27-point insider detection, LLM judging layer, real-time dashboard. Everything DB-managed with hot reload.

**License note (AGPL-3.0):** copyleft — fine for CopyBot's private, local, paper-only use, and reading code as reference is unrestricted. But any code *copied* in must be attributed, and if CopyBot were ever offered as a networked service it would force AGPL. **Verdict: read and reimplement concepts; don't vendor code.**

---

## 1. What's worth taking (ranked)

### 🎯 High value — reimplementable ideas

1. **Insider/anomaly detection scoring for wallets (`insider_detector.py`, 699 lines).** An 11-component weighted score (win-rate 0.10, timing-alpha 0.16, ROI 0.08, Brier 0.12, entry-vs-resolution edge 0.10, concentration 0.07, **pre-news timing 0.12**, market-selection edge 0.08, drawdown behavior 0.05, cluster correlation 0.08, funding-overlap proxy 0.04) with FLAGGED ≥0.72 / WATCH ≥0.60 thresholds. The **pre-news-timing component connects directly to CopyBot's research bot** — a wallet that consistently trades *before* RegulatorySignals break is exactly the signal source worth copying. CopyBot's `walletGlobalScore` is win/ROI/consistency/copyability only; this adds a timing/Brier/behavior dimension. Reimplementable on existing tables (ObservedTrade, RegulatorySignal, DecisionJournal).

2. **Cox-PH fill-probability model (`fill_simulator/cox_trainer.py`, 760 lines).** P(fill within Δt) from own order history; covariates: queue depth, spread, trade intensity, **time-to-resolution** (+ TTR buckets <30s/<60s/<300s — captures the Polymarket phenomenon that 60–90% of taker flow on 15-min crypto binaries hits in the last minutes), side imbalance, vol, measured latency. KM fallback <100 events, C-index ≥0.55 gate, held-out 7-day validation, promote-only-if-better. CopyBot's paper fills are currently *assumed at current price* — a fill model would make paper realistic. **Prerequisite: persist L2 book context + order statuses** (see infra item). The TTR insight also independently validates CopyBot's short-TTR lane thesis.

3. **Trader Confluence (`traders_confluence.py`, 873 lines).** Aggregated multi-wallet signal scoring — formalizes CopyBot's swarm detection (currently count ≥3 in 1h) into a scored confluence with leader weights.

4. **Whale copy config surface (`traders_copy_trade.py`, 1015 lines).** Configurable delay, proportional sizing, max-copy-drawdown / daily-loss / source-exposure caps, **leader weights**, edge scoring from |entry − edge_midpoint|·multiplier, inventory requirements for sells. Several of these map onto CopyBot's ruleset cleanly (leader weighting, entry-edge scoring, exposure caps).

5. **Risk gates + token circuit breaker.** Gross exposure caps, daily loss limits, liquidity-depth checks, per-token flash-crash cooldown. CopyBot has open-position caps + the Kalshi breaker; the per-token circuit breaker is a small additive.

6. **Multi-leg execution (`multi-leg` in the README + cross_platform/negrisk/ctf_basic_arb strategies).** Parallel PM+Kalshi legs with hedging — **this is the reference design for Phase C.** The `cross_platform.py`, `negrisk.py` (YES+NO<1), and `combinatorial.py` strategies are worth reading during the Phase C design window (read-only, AGPL).

### ⚪ Medium value

7. **L2 book replay + trade-vs-cancel decomposition.** The backtester's foundation: persist Polymarket WS book deltas (25 levels × 0.5s) + split depth disappearance into fills vs cancels. Would enable realistic backtests of the copy logic AND verify whether observed whale trades actually filled at the recorded price. Requires starting L2 persistence now (storage cost moderate) to accumulate history.
8. **Semantic news→market matching** (sentence transformers + FAISS) — would upgrade CopyBot's keyword-regex category mapping (researchCategoryFor), but heavy.
9. **LLM opportunity judging** (profit viability / resolution safety / execution feasibility) — a review layer for the scorer; CopyBot's tuning-review cron does a lighter version.
10. **Tiered market scanner (HOT/WARM/COLD)** — triage concept for the dashboard.

### ❌ Not useful

- The platform itself (Postgres+Redis+16 workers+Docker+React) — adopting it replaces CopyBot's stack instead of enhancing it; CopyBot's Next.js dashboard + sqlite + cron is already serving.
- Crypto-HF (5m/15m binaries), weather, sports, settlement-lag strategies — outside CopyBot's market focus.
- AGPL code vendoring — avoid (license contamination for a system the user may extend/distribute later).

## 2. Recommendation

1. **Now (cheap):** token circuit breaker + copy-config surface ideas (leader weights, entry-edge scoring) → tuning-review proposals.
2. **Phase C design window (Sep 15–30):** read `cross_platform.py` / `negrisk.py` / `ctf_basic_arb.py` as reference for the arb invariants (read-only).
3. **Next phase candidate (Phase D):** insider/anomaly wallet scoring — 11-component reimplementation on existing tables; pre-news-timing wires into RegulatorySignal. Medium effort, directly improves copy selection.
4. **Infra decision:** start persisting L2 book snapshots + fill context now so a Cox-PH fill model becomes possible later (and paper fills stop being assumed-at-price). Storage cost check first.

---

## 3. Implementation status (2026-08-31, all four items shipped as v40)

| Item | Status | Where |
|---|---|---|
| Insider/anomaly wallet scoring | ✅ Live | `src/lib/insider.ts` (11 weighted components, pre-news timing via RegulatorySignal) + `scripts/score-insiders.ts` → `WalletInsiderScore` table; runs nightly in the EOD job, Discord alert on flagged/watch |
| Risk gates + per-token circuit breaker | ✅ Live | `rules.ts` v40 fields (dailyLossLimitUsd −150, maxGrossExposureUsd 250, breaker 15%/5m/30m cooldown) + `score-trades.ts` gates (journaled watchlist, `[RISK-GATE]` log) + `TokenCircuitTrip` table |
| L2 book snapshot recorder | ✅ Live | `scripts/record-l2.ts` — per-market WS connections (one subscription each), 5s top-25 snapshots + trade prints → `data/l2/<assetId>.jsonl`; supervised by cron `copybot-l2-watchdog` (every 15m) |
| Phase C design notes | ✅ Written | `drafts/phase-c-design-notes.md` (invariant families + safeguards from homerun's strategies, read-only) |

**L2 recorder pitfalls learned (2026-08-31):** the CLOB WS (a) rejects a SECOND subscription per connection ("INVALID OPERATION"), (b) silently returns `[]` for malformed token ids — gamma's `clobTokenIds` is a JSON-array-string on many markets, `.split(',')` breaks it, (c) ignores malformed subscription shapes (timeouts), (d) needs a PING keepalive to avoid silent idle drops. Neg-risk tokens subscribe fine via `assets_ids` once ids are parsed correctly. ~312KB in the first minutes for 25 markets — expect ~10–30MB/day (well within budget).
