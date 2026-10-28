**Kelly Window Report — 2026-10-27** (regime day 52 — FINAL READ)
Rules v68: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7399 | open $46 | net worth $7440 | realized $5545 | exposure 46/$3770 | drawdown 8.1%

**Last 24h:** 6 copies opened (5 main-lane, 1 lane) | $182 booked | realized $-76.09 on the 3 of them already settled
**Settled in the last 24h (any open date):** realized $-294.23 across 11 trades
[KELLY] decisions in log: 1331 (178 sized, 1153 skipped). Top skip reasons: no edge: q=0.572 ≤ price=0.595 (132); no edge: q=0.491 ≤ price=0.515 (71); no edge: q=0.392 ≤ price=0.415 (66)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 62 | $83 | $100 | $3378 (62 res) | $0 open |
| 0.20-0.40 | 84 | $24 | $100 | $-17 (82 res) | $36 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1106 copies, realized $2044
**Target check (mid/high-band ≈0):** 0/146 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $3360 on 146 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $2267 on n=20 vs $2,500 → ✗ short $233 · all-time in regime $3378 on n=62 · same 30d by OPEN date (cohort opened in-window, 17/17 settled): $749 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 146/146 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/146 ✓ (zero-edge skips holding) | drawdown 8.1% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
