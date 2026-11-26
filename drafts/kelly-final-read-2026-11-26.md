**Kelly Window Report — 2026-11-26** (regime day 81 — FINAL READ)
Rules v73: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $6726 | open $380 | net worth $7107 | realized $5206 | exposure 380/$3603 | drawdown 11.0% (realized basis, peak $7987 vs NW $7106)

**Last 24h:** 32 copies opened (3 main-lane, 29 lane) | $475 booked | realized $-39.88 on the 10 of them already settled
**Settled in the last 24h (any open date):** realized $-79.63 across 32 trades
[KELLY] decisions in log: 4082 (320 sized, 3762 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.481 ≤ price=0.505 (280); no edge: q=0.491 ≤ price=0.515 (191)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 103 | $87 | $100 | $2585 (102 res) | $100 open |
| 0.20-0.40 | 142 | $21 | $100 | $40 (140 res) | $36 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 23 | $19 | $50 | $13 (23 res) | $0 open |
| >=0.80 | 16 | $94 | $100 | $116 (16 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1498 copies, realized $2318
**Target check (mid/high-band ≈0):** 39/284 ✗ ABOVE expected ≈0 — inspect


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 234 | $69 |
| 0.40-0.60 | 585 | $-355 |
| 0.60-0.80 | 233 | $-47 |
| >=0.80 | 161 | $2 |
Baseline total realized $134 on 1290 pre-Kelly copies | Kelly-window main-lane realized $2755 on 284 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $-1092 on n=43 vs $2,500 → ✗ short $3592 · all-time in regime $2585 on n=103 · same 30d by OPEN date (cohort opened in-window, 41/42 settled): $-892 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 245/284 copies in <0.40 ✗ (mid/high 39) | mid-band ≈0 39/284 ✗ ABOVE expected ≈0 — inspect | drawdown 11.0% (realized basis) vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
