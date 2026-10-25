**Kelly Window Report — 2026-10-24** (regime day 49 — FINAL READ)
Rules v67: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7802 | open $86 | net worth $7888 | realized $5988 | exposure 86/$3994 | drawdown 2.6%

**Last 24h:** 6 copies opened (1 main-lane, 5 lane) | $122 booked | realized $-50.00 on the 1 of them already settled
**Settled in the last 24h (any open date):** realized $-29.79 across 2 trades
[KELLY] decisions in log: 1105 (170 sized, 935 skipped). Top skip reasons: no edge: q=0.392 ≤ price=0.415 (66); no edge: q=0.552 ≤ price=0.575 (60); no edge: q=0.572 ≤ price=0.595 (51)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 59 | $82 | $100 | $3677 (59 res) | $0 open |
| 0.20-0.40 | 79 | $24 | $100 | $-30 (78 res) | $9 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1089 copies, realized $2200
**Target check (mid/high-band ≈0):** 0/138 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $3648 on 138 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $2117 on n=23 vs $2,500 → ✗ short $383 · all-time in regime $3677 on n=59 · same 30d by OPEN date (cohort opened in-window, 18/18 settled): $693 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 138/138 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/138 ✓ (zero-edge skips holding) | drawdown 2.6% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
