**Kelly Window Report — 2026-11-03** (regime day 58 — FINAL READ)
Rules v70: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $8160 | open $164 | net worth $8323 | realized $6424 | exposure 164/$4212 | drawdown 1.3%

**Last 24h:** 14 copies opened (7 main-lane, 7 lane) | $254 booked | realized $67.52 on the 5 of them already settled
**Settled in the last 24h (any open date):** realized $-80.30 across 8 trades
[KELLY] decisions in log: 2030 (210 sized, 1820 skipped). Top skip reasons: no edge: q=0.572 ≤ price=0.595 (132); no edge: q=0.481 ≤ price=0.505 (131); no edge: q=0.491 ≤ price=0.515 (115)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 69 | $85 | $100 | $4098 (68 res) | $100 open |
| 0.20-0.40 | 106 | $22 | $100 | $173 (105 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1122 copies, realized $2013
**Target check (mid/high-band ≈0):** 0/175 ✓ (zero-edge skips holding)

**WEEKLY (7d):** 50 copies opened | realized $585.97

**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $4271 on 175 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $1569 on n=22 vs $2,500 → ✗ short $931 · all-time in regime $4098 on n=69 · same 30d by OPEN date (cohort opened in-window, 20/21 settled): $876 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 175/175 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/175 ✓ (zero-edge skips holding) | drawdown 1.3% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

## Verdict vs pre-registered §6 (window Sep 8 – Oct 8; regime day 58, 26d past end)

| band | λ̂ | §6 expect | window | verdict |
|---|---|---|---|---|
| <0.20 | −0.91 | size, cap-bound | n=69, $4,098 | aligned ✓ |
| 0.20–0.40 | −0.21 | size | n=106, $173 | UNRESOLVED (to 2026-11-20) |
| 0.40–0.60 | +0.03 | skip | n=0 | aligned-by-skip ✓ |
| 0.60–0.80 | +0.21 | skip | n=0 | aligned ✓ |
| ≥0.80 | +0.37 | skip | n=0 | aligned ✓ |

Note: pre-Kelly reference PnL for <0.20 was +$93 and 0.20–0.40 +$62 (Sep-5 basis); the baseline table above is the wider all-resolved cut ($465 / $80). Both are historical references, not window-relative rates. Realized for <0.20 is at the v70 $100 cap (avg $85).

- Concentration 175/175 in <0.40 ✓ · mid-band+high ≈0 0/175 ✓ · drawdown 1.3% vs 20% gate ✓
- **Long-shot absolute target (re-baselined 2026-10-21, kelly rec 3): trailing 30d by settle $1,569 on n=22 vs $2,500 → ✗ short $931.** All-time regime $4,098 on n=69 over 58 days ≈ $2,120/30d pace. Target UNMET, not a win.
- 0.20–0.40 stays UNRESOLVED through 2026-11-20: it flipped sign against its λ̂ at n=77, which is noise-level; do not treat it as a loss or as evidence either way.
- Exposure $164/$4,212 (3.9%) — exposure cap not binding; no ⚠ flags this read.

**Recommendation (no rule changes made):** continue Kelly at kellyFraction 0.5 with v70 caps. The one pre-registered target that fails is the absolute long-shot PnL ($1,569 vs $2,500, n=22 settled in 30d — small sample) while regime pace is ≈$2,120/30d and every structural expectation holds. Hold the target as UNMET and re-measure at n≥40 settled in a 30d window; only then propose (lane A) a fraction/cap change (0.5→0.6 or maxSizeUsd) if the gap persists. Revert to kellyEnabled=0 is not indicated: concentration, skip behavior and drawdown all match §6.

