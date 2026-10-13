**Kelly Window Report — 2026-10-12** (regime day 37 — FINAL READ)
Rules v62: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7558 | open $40 | net worth $7602 | realized $5698 | exposure 40/$3851 | drawdown 6.1%

**Last 24h:** 10 Kelly-regime copies opened (4 main-lane, 6 lane) | realized $-64.94 | $107 booked
[KELLY] decisions in log: 558 (149 sized, 409 skipped). Top skip reasons: no edge: q=0.556 ≤ price=0.585 (20); no edge: q=0.381 ≤ price=0.410 (19); no edge: q=0.436 ≤ price=0.465 (16)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 53 | $81 | $100 | $3615 (53 res) | $0 open |
| 0.20-0.40 | 64 | $26 | $100 | $-62 (63 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1007 copies, realized $2004
**Target check:** mid/high-band main-lane copies 0/117 → ≈0 ✓ (zero-edge skips holding)

**WEEKLY (7d):** 143 copies opened | realized $837.97

**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 | Kelly-window main-lane realized $3554
Long-shot (<0.20) realized: baseline $465 → window $3615 (7.8x)
**Verdict fields (pre-registered §6):** concentration ✓/✗ above | mid-band ≈0 ✓/✗ above | drawdown 6.1% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
