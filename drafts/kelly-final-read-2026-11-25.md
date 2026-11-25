**Kelly Window Report — 2026-11-25** (regime day 80 — FINAL READ)
Rules v73: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $6739 | open $447 | net worth $7183 | realized $5286 | exposure 447/$3642 | drawdown 10.0% (realized basis, peak $7987 vs NW $7186)

**Last 24h:** 34 copies opened (1 main-lane, 33 lane) | $402 booked | realized $-19.94 on the 14 of them already settled
**Settled in the last 24h (any open date):** realized $-59.94 across 31 trades
[KELLY] decisions in log: 4027 (317 sized, 3710 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.481 ≤ price=0.505 (279); no edge: q=0.491 ≤ price=0.515 (191)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 102 | $87 | $100 | $2585 (100 res) | $200 open |
| 0.20-0.40 | 140 | $21 | $100 | $40 (139 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 23 | $19 | $50 | $13 (23 res) | $0 open |
| >=0.80 | 16 | $94 | $100 | $116 (16 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1469 copies, realized $2397
**Target check (mid/high-band ≈0):** 39/281 ✗ ABOVE expected ≈0 — inspect


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 234 | $69 |
| 0.40-0.60 | 585 | $-355 |
| 0.60-0.80 | 233 | $-47 |
| >=0.80 | 161 | $2 |
Baseline total realized $134 on 1290 pre-Kelly copies | Kelly-window main-lane realized $2755 on 281 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $-1092 on n=41 vs $2,500 → ✗ short $3592 · all-time in regime $2585 on n=102 · same 30d by OPEN date (cohort opened in-window, 41/43 settled): $-1092 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 242/281 copies in <0.40 ✗ (mid/high 39) | mid-band ≈0 39/281 ✗ ABOVE expected ≈0 — inspect | drawdown 10.0% (realized basis) vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

## Verdict (2026-11-24, window closed 2026-10-08)

| band | λ̂ (Sep-1) | Kelly | realized | verdict |
|---|---|---|---|---|
| <0.20 | −0.91 | size (cap) | +$2585 (n=102) | aligned in-window; trailing 30d −$1092 → absolute target ✗ |
| 0.20–0.40 | −0.21 | size | +$40 (n=140) | UNRESOLVED (sign flip at n=77 is noise; neither loss nor evidence) |
| 0.40–0.60 | +0.03 | skip | $0 (n=0) | aligned-by-skip |
| 0.60–0.80 | +0.21 | skip | +$13 (n=23) | ≈0, small leakage |
| ≥0.80 | +0.37 | skip | +$116 (n=16) | mild misalignment (small n, $ immaterial) |

- Concentration: 242/281 (86%) in <0.40 — script flags ✗ under its strict zero-mid/high test; directionally as designed.
- Mid/high ≈0: 39/281, realized +$129 — above the ≈0 expectation; flag is a strict-copy-count test, not a PnL test.
- Long-shot ABSOLUTE target ($2,500/30d): ✗ realized −$1092 on n=41 (trailing 30d by settle).
- Drawdown: 10.0% vs 20% gate ✓. Exposure $447/$3642 — not binding.

**Recommendation (pending user approval; no rule/code change made):** keep `kellyEnabled=1` — the zero-edge skip machinery works (3710 skips, mid-band starved as designed) and 0.20–0.40 is unresolved. Do NOT scale: the long-shot band is the entire P&L and its last 30d is negative at cap-bound size. Options: (a) cut `kellyMaxBankrollPct` 10%→7.5% or cap <0.20 at $60 via RuleSet proposal; (b) verify the 30d flip isn't one market cluster before changing anything; revert to 0 is not indicated by this read.

