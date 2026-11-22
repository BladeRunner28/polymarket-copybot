**Kelly Window Report — 2026-11-22** (regime day 77 — FINAL READ)
Rules v73: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $6692 | open $428 | net worth $7095 | realized $5220 | exposure 428/$3598 | drawdown 10.9% (realized basis, peak $7987 vs NW $7120)

**Last 24h:** 47 copies opened (6 main-lane, 41 lane) | $797 booked | realized $-76.82 on the 25 of them already settled
**Settled in the last 24h (any open date):** realized $-31.95 across 49 trades
[KELLY] decisions in log: 3849 (310 sized, 3539 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.481 ≤ price=0.505 (273); no edge: q=0.491 ≤ price=0.515 (188)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 100 | $87 | $100 | $2585 (98 res) | $200 open |
| 0.20-0.40 | 135 | $21 | $100 | $40 (132 res) | $54 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 23 | $19 | $50 | $13 (23 res) | $0 open |
| >=0.80 | 16 | $94 | $100 | $116 (16 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1395 copies, realized $2331
**Target check (mid/high-band ≈0):** 39/274 ✗ ABOVE expected ≈0 — inspect


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 234 | $69 |
| 0.40-0.60 | 585 | $-355 |
| 0.60-0.80 | 233 | $-47 |
| >=0.80 | 161 | $2 |
Baseline total realized $134 on 1290 pre-Kelly copies | Kelly-window main-lane realized $2755 on 274 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $-1142 on n=40 vs $2,500 → ✗ short $3642 · all-time in regime $2585 on n=100 · same 30d by OPEN date (cohort opened in-window, 40/42 settled): $-1142 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 235/274 copies in <0.40 ✗ (mid/high 39) | mid-band ≈0 39/274 ✗ ABOVE expected ≈0 — inspect | drawdown 10.9% (realized basis) vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
