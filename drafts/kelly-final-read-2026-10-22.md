**Kelly Window Report — 2026-10-22** (regime day 47 — FINAL READ)
Rules v65: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7867 | open $63 | net worth $7922 | realized $6030 | exposure 63/$4011 | drawdown 2.2%

**Last 24h:** 9 copies opened (2 main-lane, 7 lane) | $111 booked | realized $82.49 on the 3 of them already settled
**Settled in the last 24h (any open date):** realized $52.34 across 8 trades
[KELLY] decisions in log: 844 (168 sized, 676 skipped). Top skip reasons: no edge: q=0.521 ≤ price=0.545 (45); no edge: q=0.481 ≤ price=0.505 (41); no edge: q=0.511 ≤ price=0.535 (28)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 58 | $83 | $100 | $3727 (58 res) | $0 open |
| 0.20-0.40 | 78 | $24 | $100 | $-76 (77 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1081 copies, realized $2238
**Target check (mid/high-band ≈0):** 0/136 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $3651 on 136 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $2875 on n=24 vs $2,500 → ✓ +$375 · all-time in regime $3727 on n=58 · same 30d by OPEN date (cohort opened in-window, 19/19 settled): $624 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 136/136 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/136 ✓ (zero-edge skips holding) | drawdown 2.2% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
