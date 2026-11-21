**Kelly Window Report — 2026-11-21** (regime day 76 — FINAL READ)
Rules v73: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $6870 | open $282 | net worth $7172 | realized $5252 | exposure 282/$3636 | drawdown 10.5% (realized basis, peak $7987 vs NW $7152)

**Last 24h:** 31 copies opened (1 main-lane, 30 lane) | $367 booked | realized $148.10 on the 11 of them already settled
**Settled in the last 24h (any open date):** realized $128.10 across 14 trades
[KELLY] decisions in log: 3709 (304 sized, 3405 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.481 ≤ price=0.505 (266); no edge: q=0.491 ≤ price=0.515 (188)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 97 | $87 | $100 | $2685 (97 res) | $0 open |
| 0.20-0.40 | 132 | $22 | $100 | $40 (131 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 23 | $19 | $50 | $13 (23 res) | $0 open |
| >=0.80 | 16 | $94 | $100 | $116 (16 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1354 copies, realized $2263
**Target check (mid/high-band ≈0):** 39/268 ✗ ABOVE expected ≈0 — inspect


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 234 | $69 |
| 0.40-0.60 | 585 | $-355 |
| 0.60-0.80 | 233 | $-47 |
| >=0.80 | 161 | $2 |
Baseline total realized $134 on 1290 pre-Kelly copies | Kelly-window main-lane realized $2855 on 268 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $-1042 on n=39 vs $2,500 → ✗ short $3542 · all-time in regime $2685 on n=97 · same 30d by OPEN date (cohort opened in-window, 39/39 settled): $-1042 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 229/268 copies in <0.40 ✗ (mid/high 39) | mid-band ≈0 39/268 ✗ ABOVE expected ≈0 — inspect | drawdown 10.5% (realized basis) vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
