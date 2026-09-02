# OctagonAI/kalshi-trading-bot-cli — Audit for C-200 (Phase B input)

**Status:** COMPLETE — 2026-08-31. Repo: github.com/OctagonAI/kalshi-trading-bot-cli (379★, 104 forks, pushed 2026-08-22).
**License:** ✅ **MIT** (Copyright 2026 Octagon AI, Inc.) — safe to borrow with attribution.
**Cloned to:** /tmp/kalshi-trading-bot (~37k LOC TypeScript, Bun runtime).

---

## 1. What it is

An AI-native CLI trading bot for Kalshi: LLM "deep research" (LangChain over
Anthropic/Gemini/Ollama/OpenAI + Tavily search) produces independent probability
estimates per market, an **EdgeComputer** derives edge vs the live order book, a
**Kelly sizer** sizes positions, and a **5-gate risk engine** gates execution.
SQLite state + full audit trail.

**The LLM layer is NOT portable** (LangChain, OpenAI-centric, duplicates the copybot's
research bot + local-LLM sentiment). The value is the **execution math** — clean,
MIT, TypeScript, ~600 lines across three files. All formulas verified below.

## 2. Transferable component A — executable-quote Kelly sizing (`src/risk/kelly.ts`)

Standard binary-outcome Kelly, refined to price against the executable quote:

```
YES:  f* = executableEdge / (1 − pricingProb)
NO:   f* = |executableEdge| / pricingProb
executableEdge = (modelProb − marketProb) − (ask − marketProb)   # edge vs the ASK, not midpoint
pricingProb    = ask (YES) or 1 − noAsk (NO); falls back to midpoint
```

Verified: this is the classic f = (q−p)/(1−p) with q−p recomputed against the price
you'd actually pay. **The executable-quote refinement is the single most valuable
idea here** — edge vs midpoint overstates edge by half the spread; on a 2¢ spread
that's 1¢ of phantom edge per trade, which compounds into the exact "premium drag"
your v41 band sizing fights.

Pipeline of a size decision (in order):
1. **Min-edge threshold** (default 5%) — don't size inside model error.
2. **Extreme-probability guard** (p ≤ 0 or p ≥ 1 → skip).
3. **Half-Kelly default** (`multiplier 0.5`), **maxPositionPct 10%** of bankroll.
4. **Liquidity haircut**: spread > 5¢ OR 24h volume < threshold → scale fraction
   by haircut (liquidityAdjusted flag).
5. **Bankroll = cash − open exposure** (live from portfolio; availableBankroll).
6. Contract rounding to tick size; every skip writes a `skippedReason`.

## 3. Transferable component B — edge computation (`src/scan/edge-computer.ts`)

- `edge = modelProb − marketProb` — the same delta your Bayesian aggregation emits.
- **Confidence tiering by |edge|**: ≥0.10 very_high, ≥0.05 high, ≥0.02 moderate,
  else low — a simple, defensible mapping you can reuse for evidence tiering.
- **Cache-vs-refresh policy** (`shouldRefresh(ticker, marketProb, closeTime)`):
  reuse the model's cached probability unless price moved or close is near —
  saves LLM calls on quiet markets. Directly applicable to the research bot's
  6-hourly cadence (skip re-scoring items whose market hasn't moved).
- Every edge snapshot persisted with drivers/catalysts/sources → audit trail
  (matches your DecisionJournal measurement-first pattern).

## 4. Transferable component C — 5-gate risk engine (`src/risk/gate.ts` + `correlation.ts`)

All checks must pass; defaults: spread ≤ 5¢, volume ≥ 500/24h, **≤ 3 open positions
per event category**, ≤ 10 total positions, drawdown ≤ 20%, ≤ 10% bankroll per
position. The interesting additions vs your current stack:

- **Per-category concentration limit** — you cap totals (maxOpen 225, walletCap 40)
  but nothing bounds how many positions share ONE market category. A correlated
  bundle (all politics, all crypto) is the real risk; this is a cheap SQL join.
- **Drawdown gate** (≤20%) as a hard pre-execution check — your circuit breaker
  (v40) trips on rate/volume; a portfolio-drawdown gate is a different tripwire.
- Explicit `reason` strings per failed gate → audit + Discord-able.

## 5. Fit for C-200

| Piece | Maps to | Verdict |
|---|---|---|
| Executable-quote Kelly | **Phase B — Kelly sizing replaces band sizing** (Scheduled) | ✅ Direct reference implementation; adopt the ask-adjusted edge + haircut + bankroll-constrained sizing |
| Edge confidence tiering | Phase A2 evidence aggregation / delta → score | ✅ Reuse the 0.10/0.05/0.02 tiers for evidence strength |
| Cache-vs-refresh | Research bot 6-hourly cron | ✅ Cheap operational win: skip re-scoring unmoved markets |
| Per-category concentration | Risk layer (gaps in caps 40/225) | ✅ New capability worth adding to the ruleset |
| Drawdown gate | Risk layer (complements v40 circuit breaker) | ✅ New capability |
| LLM research pipeline | Research bot / local LLM | ❌ Not portable — duplicates existing stack |
| CLI/agent/WhatsApp/backtest UI | — | ❌ Irrelevant |

## 6. Integration proposal — Phase B (when it starts)

1. Port `kellySize()` to the scoring path (`src/lib/`): inputs `edge` (from the
   evidence aggregation delta or premium overlay), `marketProb` + **bestAsk** from
   MarketSnapshot (already recorded every cycle!), `bankroll` from
   query_bankroll.js. Half-Kelly, 10% cap, liquidity haircut from spread/volume
   columns already in MarketSnapshot.
2. Log `[KELLY] edge=… executableEdge=… fraction=… skippedReason=…` per decision —
   the measurement-first comparison vs the current band sizing (same pattern as
   the sentiment A/B and astro shadow).
3. Add two risk gates to the ruleset (flag-gated): per-category concentration
   (max N per category from MarketSnapshot.category) and portfolio drawdown gate
   (from BotBankroll/query_bankroll).
4. Research bot: adopt the cache-vs-refresh rule (skip re-scoring when
   |ΔmarketProb| < threshold and not near close).

**Effort:** ~1 day for Kelly + gates (math is ~200 lines, MIT). **Risk:** low —
paper-only, additive, flag-revertible, and Phase B is already Scheduled.

## 7. Honest caveats

- Octagon's "modelProb" comes from their opaque LLM research pipeline; the Kelly
  math assumes a **calibrated** probability. Your pipeline has calibration
  machinery (Wang premium calibration, v41 band analysis) — feed the *calibrated*
  edge in, not the raw delta.
- Kelly assumes binary independent outcomes; short-TTR markets with correlated
  resolutions (same event, multiple markets) need the correlation/category gate
  to stay honest — which is why gate C matters as much as the formula.
- Their defaults (5¢ spread, 500 vol, 10% max position) are Kalshi-flavored;
  Polymarket's deeper books justify different numbers — recalibrate, don't copy.

## 8. Files

- `src/risk/kelly.ts` (230 lines) — the sizer (MIT)
- `src/scan/edge-computer.ts` (164 lines) — edge + confidence tiers
- `src/risk/gate.ts`, `src/risk/correlation.ts` — the 5-gate engine
- This audit: `drafts/octagon-audit.md`
