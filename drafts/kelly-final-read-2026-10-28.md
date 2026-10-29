**Kelly Window Report — 2026-10-28** (regime day 53 — FINAL READ)
Rules v69: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7219 | open $267 | net worth $7336 | realized $5586 | exposure 267/$3718 | drawdown 9.4%

**Last 24h:** 9 copies opened (5 main-lane, 4 lane) | $252 booked | realized $51.10 on the 3 of them already settled
**Settled in the last 24h (any open date):** realized $41.13 across 4 trades
[KELLY] decisions in log: 1490 (183 sized, 1307 skipped). Top skip reasons: no edge: q=0.572 ≤ price=0.595 (132); no edge: q=0.491 ≤ price=0.515 (114); no edge: q=0.481 ≤ price=0.505 (69)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 64 | $83 | $100 | $3378 (62 res) | $200 open |
| 0.20-0.40 | 87 | $23 | $100 | $34 (83 res) | $63 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1110 copies, realized $2034
**Target check (mid/high-band ≈0):** 0/151 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $3412 on 151 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $749 on n=17 vs $2,500 → ✗ short $1751 · all-time in regime $3378 on n=64 · same 30d by OPEN date (cohort opened in-window, 15/17 settled): $274 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 151/151 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/151 ✓ (zero-edge skips holding) | drawdown 9.4% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.
0.20-0.40 band: UNRESOLVED (not a loss) through 2026-11-20 — sign flipped vs λ̂ at n=77, noise-level; do not cite either way.

**Recommendation (user approval required — no rule/code changed):** continue Kelly at fraction 0.5 with caps unchanged. Only failing field is the absolute long-shot PnL target, and the cause is size, not sign (band avg $83 sits at the $100 cap). Proposal for RuleSet v70 trial: maxSizeUsd $100 → $150, staged, since 151/151 copies already sit in <0.20 and a cap raise concentrates risk. kellyEnabled=0 not indicated (no gate trip, band edge intact).
