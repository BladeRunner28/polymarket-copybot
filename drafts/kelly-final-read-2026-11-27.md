**Kelly Window Report — 2026-11-27** (regime day 83 — FINAL READ)
Rules v73: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $6511 | open $687 | net worth $7133 | realized $5299 | exposure 687/$3617 | drawdown 9.9% (realized basis, peak $7987 vs NW $7199)

**Last 24h:** 36 copies opened (11 main-lane, 25 lane) | $1096 booked | realized $-2.09 on the 11 of them already settled
**Settled in the last 24h (any open date):** realized $6.96 across 15 trades
[KELLY] decisions in log: 4285 (334 sized, 3951 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.481 ≤ price=0.505 (282); no edge: q=0.491 ≤ price=0.515 (239)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 110 | $88 | $100 | $2585 (106 res) | $400 open |
| 0.20-0.40 | 149 | $21 | $100 | $10 (148 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 23 | $19 | $50 | $13 (23 res) | $0 open |
| >=0.80 | 16 | $94 | $100 | $116 (16 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1535 copies, realized $2440
**Target check (mid/high-band ≈0):** 39/298 ✗ ABOVE expected ≈0 — inspect


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 234 | $69 |
| 0.40-0.60 | 585 | $-355 |
| 0.60-0.80 | 233 | $-47 |
| >=0.80 | 161 | $2 |
Baseline total realized $134 on 1290 pre-Kelly copies | Kelly-window main-lane realized $2725 on 298 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $-792 on n=44 vs $2,500 → ✗ short $3292 · all-time in regime $2585 on n=110 · same 30d by OPEN date (cohort opened in-window, 43/47 settled): $-731 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 259/298 copies in <0.40 ✗ (mid/high 39) | mid-band ≈0 39/298 ✗ ABOVE expected ≈0 — inspect | drawdown 9.9% (realized basis) vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

## Verdict (pre-registered §6, composed 2026-11-27)

| criterion | expectation | actual | verdict |
|---|---|---|---|
| concentration | book in <0.40 | 259/298 copies | ✓ met |
| mid/high activity | 0.40–0.60 skip → ≈0 | 0 in 0.40–0.60, 39 in 0.60+ | ✗ inspect (60.80 band 23, ≥0.80 16) |
| long-shot target | ≥$2,500 / 30d absolute | -$792 trailing 30d (n=44) | ✗ short $3,292 |
| band alignment | <0.20 +, 0.20–0.40 + | +$2,585 / +$10 | aligned in sign |
| drawdown | ≤ pre-Kelly baseline | 9.9% vs 20% gate | ✓ |

Per-copy economics: Kelly main-lane $2,725 / 298 = $9.14 per copy vs pre-Kelly
$134 / 1,290 = $0.10 per copy (raw totals, different periods — not a rate test).
**0.20–0.40 band: UNRESOLVED** through 2026-11-20 — it flipped sign against its
λ̂ at n=77, which is noise-level. Not a loss, not evidence either way.

**Recommendation (rules untouched — needs user approval):** continue Kelly with
kellyEnabled=1 and fraction 0.5 unchanged; do NOT revert (legacy sizing put 585
mid-band copies into a -$355 region). Propose one RuleSet change: a trailing-30d
guard on the <0.20 band so size above $25 requires non-negative 30d realized —
the target miss is a long-shot edge-decay problem, not a sizing-variable problem.
Re-read at the Dec 15 refit before touching caps.
