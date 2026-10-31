**Kelly Window Report — 2026-10-30** (regime day 55 — FINAL READ)
Rules v70: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $8300 | open $56 | net worth $8358 | realized $6456 | exposure 56/$4229 | drawdown 0.6%

**Last 24h:** 5 copies opened (5 main-lane, 0 lane) | $90 booked | realized $19.16 on the 4 of them already settled
**Settled in the last 24h (any open date):** realized $19.16 across 6 trades
[KELLY] decisions in log: 1758 (196 sized, 1562 skipped). Top skip reasons: no edge: q=0.572 ≤ price=0.595 (132); no edge: q=0.491 ≤ price=0.515 (115); no edge: q=0.541 ≤ price=0.565 (72)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 66 | $84 | $100 | $4245 (66 res) | $0 open |
| 0.20-0.40 | 96 | $23 | $100 | $36 (93 res) | $54 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1111 copies, realized $2034
**Target check (mid/high-band ≈0):** 0/162 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $4281 on 162 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $1717 on n=20 vs $2,500 → ✗ short $783 · all-time in regime $4245 on n=66 · same 30d by OPEN date (cohort opened in-window, 19/19 settled): $1142 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 162/162 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/162 ✓ (zero-edge skips holding) | drawdown 0.6% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
