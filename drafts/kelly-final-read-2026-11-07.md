**Kelly Window Report — 2026-11-07** (regime day 62 — FINAL READ)
Rules v71: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $9671 | open $388 | net worth $10077 | realized $8160 | exposure 388/$5089 | drawdown 0.8%

**Last 24h:** 16 copies opened (5 main-lane, 11 lane) | $423 booked | realized $-60.03 on the 2 of them already settled
**Settled in the last 24h (any open date):** realized $-88.07 across 6 trades
[KELLY] decisions in log: 2697 (246 sized, 2451 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (247); no edge: q=0.491 ≤ price=0.515 (146); no edge: q=0.481 ≤ price=0.505 (136)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 86 | $84 | $100 | $5562 (83 res) | $200 open |
| 0.20-0.40 | 124 | $22 | $100 | $376 (121 res) | $54 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1175 copies, realized $2081
**Target check (mid/high-band ≈0):** 0/210 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $5938 on 210 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $1898 on n=34 vs $2,500 → ✗ short $602 · all-time in regime $5562 on n=86 · same 30d by OPEN date (cohort opened in-window, 33/36 settled): $1780 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 210/210 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/210 ✓ (zero-edge skips holding) | drawdown 0.8% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

**VERDICT (§6, pre-registered)**
- Concentration <0.40: PASS — 210/210, mid/high band exactly 0.
- Mid-band ≈0: PASS — 0/210 (zero-edge rule, not calibration sight).
- Drawdown: PASS — 0.8% vs 20% gate; no ⚠ flags, exposure $388/$5,089 not binding.
- LONG-SHOT ABSOLUTE PnL ≥ $2,500/30d: MISS — $1,898 on n=34 (30d by settle date), short $602 (76%). All-time in regime $5,562 on n=86.
- 0.20–0.40 band: UNRESOLVED through 2026-11-20 — sign flip at n=77 is noise-level; not a loss, not evidence either way.
- Baseline context: pre-Kelly $140/1,290 copies vs Kelly-window $5,938/210 — raw totals, not a like-for-like rate.

**RECOMMENDATION (approval required, no rule change made):** continue Kelly — selection hypothesis held; the target miss is a size constraint, not a signal failure (long-shot band cap-bound at $84 avg vs $100 max). Proposal: RuleSet bump kellyMaxSizeUsd $100 → $140 for a 30d read on Dec 7, 0.20–0.40 frozen until Nov 20. Revert not recommended.
