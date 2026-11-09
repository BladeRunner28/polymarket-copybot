**Kelly Window Report — 2026-11-09** (regime day 64 — FINAL READ)
Rules v71: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $10205 | open $761 | net worth $11073 | realized $9065 | exposure 761/$5586 | drawdown 0.0%

**Last 24h:** 28 copies opened (11 main-lane, 17 lane) | $1063 booked | realized $530.14 on the 11 of them already settled
**Settled in the last 24h (any open date):** realized $430.09 across 33 trades
[KELLY] decisions in log: 3034 (262 sized, 2772 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (248); no edge: q=0.501 ≤ price=0.525 (177); no edge: q=0.481 ≤ price=0.505 (163)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 97 | $86 | $100 | $6638 (91 res) | $550 open |
| 0.20-0.40 | 129 | $22 | $100 | $340 (126 res) | $54 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1215 copies, realized $1947
**Target check (mid/high-band ≈0):** 0/226 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $6978 on 226 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $2857 on n=41 vs $2,500 → ✓ +$357 · all-time in regime $6638 on n=97 · same 30d by OPEN date (cohort opened in-window, 40/46 settled): $2902 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 226/226 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/226 ✓ (zero-edge skips holding) | drawdown 0.0% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
