**Kelly Window Report — 2026-11-06** (regime day 61 — FINAL READ)
Rules v71: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $9924 | open $224 | net worth $10133 | realized $8248 | exposure 224/$5116 | drawdown 0.1%

**Last 24h:** 16 copies opened (5 main-lane, 11 lane) | $307 booked | realized $120.48 on the 8 of them already settled
**Settled in the last 24h (any open date):** realized $641.92 across 19 trades
[KELLY] decisions in log: 2503 (241 sized, 2262 skipped). Top skip reasons: no edge: q=0.491 ≤ price=0.515 (145); no edge: q=0.481 ≤ price=0.505 (136); no edge: q=0.572 ≤ price=0.595 (132)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 82 | $84 | $100 | $5683 (81 res) | $100 open |
| 0.20-0.40 | 123 | $22 | $100 | $336 (120 res) | $54 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1164 copies, realized $2088
**Target check (mid/high-band ≈0):** 0/205 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $6019 on 205 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $2579 on n=34 vs $2,500 → ✓ +$79 · all-time in regime $5683 on n=82 · same 30d by OPEN date (cohort opened in-window, 31/32 settled): $1901 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 205/205 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/205 ✓ (zero-edge skips holding) | drawdown 0.1% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
