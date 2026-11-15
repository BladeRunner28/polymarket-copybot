**Kelly Window Report — 2026-11-15** (regime day 70 — FINAL READ)
Rules v73: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7242 | open $318 | net worth $7563 | realized $5660 | exposure 318/$3832 | drawdown 34.0%
⚠ **drawdown 34.0% EXCEEDS the 20% gate** — new copies should be journaled watchlist; confirm the gate is tripping

**Last 24h:** 0 copies opened (0 main-lane, 0 lane) | $0 booked | realized $0.00 on the 0 of them already settled
**Settled in the last 24h (any open date):** realized $-11.05 across 2 trades
[KELLY] decisions in log: 3318 (286 sized, 3032 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.501 ≤ price=0.525 (183); no edge: q=0.481 ≤ price=0.505 (178)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 93 | $86 | $100 | $3085 (90 res) | $300 open |
| 0.20-0.40 | 118 | $22 | $100 | $59 (117 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 23 | $19 | $50 | $13 (23 res) | $0 open |
| >=0.80 | 16 | $94 | $100 | $116 (16 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1290 copies, realized $2252
**Target check (mid/high-band ≈0):** 39/250 ✗ ABOVE expected ≈0 — inspect


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 234 | $69 |
| 0.40-0.60 | 585 | $-355 |
| 0.60-0.80 | 233 | $-47 |
| >=0.80 | 161 | $2 |
Baseline total realized $134 on 1290 pre-Kelly copies | Kelly-window main-lane realized $3274 on 250 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $-530 on n=37 vs $2,500 → ✗ short $3030 · all-time in regime $3085 on n=93 · same 30d by OPEN date (cohort opened in-window, 37/40 settled): $-530 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 211/250 copies in <0.40 ✗ (mid/high 39) | mid-band ≈0 39/250 ✗ ABOVE expected ≈0 — inspect | drawdown 34.0% vs 20% gate ✗
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
