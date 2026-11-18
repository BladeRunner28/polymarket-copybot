**Kelly Window Report — 2026-11-18** (regime day 73 — FINAL READ)
Rules v73: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7038 | open $110 | net worth $7043 | realized $5248 | exposure 110/$3572 | drawdown 10.5% (realized basis, peak $7987 vs NW $7148)

**Last 24h:** 17 copies opened (5 main-lane, 12 lane) | $468 booked | realized $-217.86 on the 15 of them already settled
**Settled in the last 24h (any open date):** realized $-247.77 across 19 trades
[KELLY] decisions in log: 3569 (301 sized, 3268 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.491 ≤ price=0.515 (188); no edge: q=0.501 ≤ price=0.525 (183)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 97 | $87 | $100 | $2785 (96 res) | $100 open |
| 0.20-0.40 | 129 | $22 | $100 | $5 (129 res) | $0 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 23 | $19 | $50 | $13 (23 res) | $0 open |
| >=0.80 | 16 | $94 | $100 | $116 (16 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1314 copies, realized $2194
**Target check (mid/high-band ≈0):** 39/265 ✗ ABOVE expected ≈0 — inspect


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 234 | $69 |
| 0.40-0.60 | 585 | $-355 |
| 0.60-0.80 | 233 | $-47 |
| >=0.80 | 161 | $2 |
Baseline total realized $134 on 1290 pre-Kelly copies | Kelly-window main-lane realized $2920 on 265 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $-1042 on n=39 vs $2,500 → ✗ short $3542 · all-time in regime $2785 on n=97 · same 30d by OPEN date (cohort opened in-window, 39/40 settled): $-1042 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 226/265 copies in <0.40 ✗ (mid/high 39) | mid-band ≈0 39/265 ✗ ABOVE expected ≈0 — inspect | drawdown 10.5% (realized basis) vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
