# RuleSet v37 — 2026-08-30 Reports: Quality Gates + Kalshi Gate + Entry-Band Sizing

**Status:** ✅ IMPLEMENTED & ACTIVATED 2026-08-30 23:58 CT (RuleSet v37, 13 proposals, audit row `hermes-v37-reports-0830`; 56/56 tests green, tsc clean). Rollback = deactivate v37 / reactivate v36.
**Source:** Tuning review #10 (07:15) + C-200 daily report (18:09), both 2026-08-30.

---

## The 13 changes (apply-v37.ts)

| Field | v36 → v37 | Source |
|---|---|---|
| `minCopyScore` | 70 → **80** | daily D2 (avg executed conf 0.59/score 75.4 filtered nothing; 80+ = best 30d bucket +$0.57/trade) |
| `minConfidence` (NEW) | **0.70** | daily D2 — hard skip; short-TTR lane exempt |
| `kalshiMinCopyScore` (NEW) | **80** | daily D1 — Kalshi gate |
| `kalshiMinConfidence` (NEW) | **0.75** | daily D1 — Kalshi gate |
| `kalshiCircuitBreakerPnl` (NEW) | **−50** | daily D1 — pause Kalshi when realized < −$50 (TRIPPED at −$100.28 → Polymarket-only) |
| `deadZoneMinPrice` / `MaxPrice` / `SizeFactor` (NEW) | **0.2 / 0.6 / 0.5** | daily D2 — halve size in the −$227 entry band |
| `longshotMaxPrice` / `SizeFactor` (NEW) | **0.20 / 1.5** | daily D2 — <$0.20 only +EV bucket (+$185.75); set to 0.20 not 0.40 because the report's own data puts 0.20–0.40 inside the losing middle |
| `maxOpenPositions` | 150 → **225** | review R1 (range 225–250; daily D3 asked 200 — 225 satisfies both) |
| `staleExitHours` | 48 → **24** | daily D3 — slot-starved book needs faster turnover |
| `maxCopiesPerWalletPerDay` | 25 → **40** | review R5 (304 downgrades ≈ 87% of executed copies) |

Note: `maxPriceDrift 0.006→0.0045` was already applied by the auto-tuner at EOD (v36); v37 layers on top.

## Behavior verified live (v37 ruleset)

- Mid-confidence signal (~77, conf 0.59) → **skip** ("confidence 0.59 < min 0.7").
- ≥80 clean entry in the 0.2–0.6 dead zone → paper_copy, **size $9** (18 × 0.5).
- Long-shot entry < $0.20 → paper_copy, **size $20** (18 × 1.5, clamped).
- Regulatory-boosted signal → clamp at 79 → **watchlist** (79 < minCopyScore 80): unvalidated boosts can no longer manufacture copies at all — the strongest form of the v34 clamp; lane-eligible boosted signals can still copy via the short-TTR lane (floor 35, fixed $10).
- **Kalshi circuit breaker TRIPPED** (realized −$100.28 < −$50) → all routing stays Polymarket until the leg recovers above −$50.
- Ledger gap $0.00.

## Conflict resolution (reports disagreed)

- Tuning review #10 said "hold v35, don't tighten until v32/v35 resolve" — the daily report (later, with fresh realized data) explicitly overrode with tightening recs. Implemented the daily report; the tuner's relax floor was raised to `max(highScoreCapMin, sweetSpotMinScore, 55)` so a hot streak can't erode the 80 bar (rule-updater.ts, engine test updated).
- Cap numbers: review 225–250 vs daily 200 → **225** (satisfies both).
- Review R2 ("recycle only fires at EOD") was a misread — the hourly update-pnl runs the sweep (5 recycled observed in one run); 24h stale exit makes it fire more often.
- API pacing: `API_DELAY_MS` 600→300 in copybot-monitor-score.sh (review R3; zero 429s this window).

## Rollback

Deactivate v37 / reactivate v36 (one transaction, audit trail). New fields are additive; rulesets lacking them fall back to DEFAULT_RULES values.

## Expected effect

Main-lane copies: only ≥80 AND ≥0.70 confidence, halved in the 0.2–0.6 band, boosted below $0.20 — 40–60% fewer trades per the report, targeting positive expectancy instead of −$0.18/trade. Kalshi leg paused. Open-cap headroom 225 with 24h turnover.
