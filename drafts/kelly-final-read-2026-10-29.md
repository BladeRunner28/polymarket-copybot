**Kelly Window Report — 2026-10-29** (regime day 54 — FINAL READ)
Rules v70: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $8270 | open $66 | net worth $8338 | realized $6437 | exposure 66/$4219 | drawdown 0.8%

**Last 24h:** 7 copies opened (6 main-lane, 1 lane) | $273 booked | realized $1030.29 on the 4 of them already settled
**Settled in the last 24h (any open date):** realized $850.68 across 10 trades
[KELLY] decisions in log: 1559 (189 sized, 1370 skipped). Top skip reasons: no edge: q=0.572 ≤ price=0.595 (132); no edge: q=0.491 ≤ price=0.515 (115); no edge: q=0.481 ≤ price=0.505 (69)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 66 | $84 | $100 | $4245 (66 res) | $0 open |
| 0.20-0.40 | 91 | $23 | $100 | $17 (88 res) | $54 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1111 copies, realized $2034
**Target check (mid/high-band ≈0):** 0/157 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $4262 on 157 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $1717 on n=20 vs $2,500 → ✗ short $783 · all-time in regime $4245 on n=66 · same 30d by OPEN date (cohort opened in-window, 19/19 settled): $1142 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 157/157 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/157 ✓ (zero-edge skips holding) | drawdown 0.8% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
