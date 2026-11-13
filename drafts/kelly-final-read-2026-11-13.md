**Kelly Window Report — 2026-11-13** (regime day 68 — FINAL READ)
Rules v72: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7186 | open $388 | net worth $7580 | realized $5674 | exposure 388/$3840 | drawdown 33.9%
⚠ **drawdown 33.9% EXCEEDS the 20% gate** — new copies should be journaled watchlist; confirm the gate is tripping

**Last 24h:** 0 copies opened (0 main-lane, 0 lane) | $0 booked | realized $0.00 on the 0 of them already settled
**Settled in the last 24h (any open date):** realized $81.83 across 31 trades
[KELLY] decisions in log: 3318 (286 sized, 3032 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.501 ≤ price=0.525 (183); no edge: q=0.481 ≤ price=0.505 (178)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 93 | $86 | $100 | $3096 (89 res) | $350 open |
| 0.20-0.40 | 118 | $22 | $100 | $59 (117 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 23 | $19 | $50 | $13 (23 res) | $0 open |
| >=0.80 | 16 | $94 | $100 | $116 (16 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1290 copies, realized $2254
**Target check (mid/high-band ≈0):** 39/250 ✗ ABOVE expected ≈0 — inspect


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 234 | $69 |
| 0.40-0.60 | 585 | $-355 |
| 0.60-0.80 | 233 | $-47 |
| >=0.80 | 161 | $2 |
Baseline total realized $134 on 1290 pre-Kelly copies | Kelly-window main-lane realized $3285 on 250 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $-519 on n=36 vs $2,500 → ✗ short $3019 · all-time in regime $3096 on n=93 · same 30d by OPEN date (cohort opened in-window, 36/40 settled): $-519 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 211/250 copies in <0.40 ✗ (mid/high 39) | mid-band ≈0 39/250 ✗ ABOVE expected ≈0 — inspect | drawdown 33.9% vs 20% gate ✗
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
