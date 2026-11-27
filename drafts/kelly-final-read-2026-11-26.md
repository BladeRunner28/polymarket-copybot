**Kelly Window Report — 2026-11-26** (regime day 82 — FINAL READ)
Rules v73: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7132 | open $60 | net worth $7195 | realized $5292 | exposure 60/$3647 | drawdown 10.0% (realized basis, peak $7987 vs NW $7192)

**Last 24h:** 15 copies opened (3 main-lane, 12 lane) | $193 booked | realized $78.98 on the 11 of them already settled
**Settled in the last 24h (any open date):** realized $85.31 across 32 trades
[KELLY] decisions in log: 4181 (323 sized, 3858 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.481 ≤ price=0.505 (280); no edge: q=0.491 ≤ price=0.515 (239)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 103 | $87 | $100 | $2585 (103 res) | $0 open |
| 0.20-0.40 | 145 | $21 | $100 | $4 (145 res) | $0 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 23 | $19 | $50 | $13 (23 res) | $0 open |
| >=0.80 | 16 | $94 | $100 | $116 (16 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1510 copies, realized $2439
**Target check (mid/high-band ≈0):** 39/287 ✗ ABOVE expected ≈0 — inspect


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 234 | $69 |
| 0.40-0.60 | 585 | $-355 |
| 0.60-0.80 | 233 | $-47 |
| >=0.80 | 161 | $2 |
Baseline total realized $134 on 1290 pre-Kelly copies | Kelly-window main-lane realized $2719 on 287 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $-892 on n=42 vs $2,500 → ✗ short $3392 · all-time in regime $2585 on n=103 · same 30d by OPEN date (cohort opened in-window, 42/42 settled): $-892 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 248/287 copies in <0.40 ✗ (mid/high 39) | mid-band ≈0 39/287 ✗ ABOVE expected ≈0 — inspect | drawdown 10.0% (realized basis) vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
