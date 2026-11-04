**Kelly Window Report — 2026-11-04** (regime day 59 — FINAL READ)
Rules v71: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $8910 | open $499 | net worth $9421 | realized $7509 | exposure 499/$4760 | drawdown 0.2%

**Last 24h:** 24 copies opened (12 main-lane, 12 lane) | $758 booked | realized $1065.98 on the 12 of them already settled
**Settled in the last 24h (any open date):** realized $1084.60 across 17 trades
[KELLY] decisions in log: 2157 (223 sized, 1934 skipped). Top skip reasons: no edge: q=0.481 ≤ price=0.505 (133); no edge: q=0.572 ≤ price=0.595 (132); no edge: q=0.491 ≤ price=0.515 (123)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 75 | $85 | $100 | $5103 (71 res) | $350 open |
| 0.20-0.40 | 112 | $22 | $100 | $251 (109 res) | $54 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1134 copies, realized $2014
**Target check (mid/high-band ≈0):** 0/187 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $5354 on 187 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $2574 on n=25 vs $2,500 → ✓ +$74 · all-time in regime $5103 on n=75 · same 30d by OPEN date (cohort opened in-window, 23/27 settled): $1881 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 187/187 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/187 ✓ (zero-edge skips holding) | drawdown 0.2% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

## Verdict vs pre-registered §6 (window Sep 8 – Oct 8; day 27 past end, regime day 59)

| band | λ̂ | §6 expect | window | verdict |
|---|---|---|---|---|
| <0.20 | −0.91 | size, cap-bound | n=75, $5,103 | aligned ✓ |
| 0.20–0.40 | −0.21 | size | n=112, $251 | UNRESOLVED (to 2026-11-20) |
| 0.40–0.60 | +0.03 | skip | n=0 | aligned-by-skip ✓ |
| 0.60–0.80 | +0.21 | skip | n=0 | aligned ✓ |
| ≥0.80 | +0.37 | skip | n=0 | aligned ✓ |

Reading:
- **<0.20 aligned and now over the absolute target:** trailing-30d by settle $2,574 on n=25 ≥ $2,500 (✓ +$74); regime all-time $5,103 on n=75 over 59 days ≈ $2,595/30d pace, so the two measures agree for the first time. Sample is thin (25 settled) — margin is $74 on ~$2.5k, i.e. noise-width; treat as MET-BUT-THIN, not a confirmed pass.
- **0.20–0.40 UNRESOLVED through 2026-11-20:** $251 on n=112 (avg $22) is positive vs its −0.21 λ̂, but it flipped sign at n=77 earlier and n=112 is still noise-level. Not a loss, not evidence either way.
- **Mid-band and high bands:** zero copies, exactly as pre-registered. Skips come from the zero-edge rule, not from calibration sight (the §6 caveat stands).
- **Structural checks:** concentration 187/187 copies in <0.40 ✓ · mid/high 0/187 ✓ · drawdown 0.2% vs 20% gate ✓ · exposure $499/$4,760 (10.5% of cap, not binding).
- **Data note:** cash $8,910 + open $499 = $9,409 vs reported net worth $9,421 — $12 gap, consistent with open-notional rounding, no action.

**Recommendation (recommendations only; no rule or code changed):** continue Kelly at kellyFraction 0.5 with v71 caps (maxBankrollPct 10%, maxSizeUsd $100). All four structural expectations hold, no ⚠ drawdown or exposure flags, and the long-shot band is at pace rather than behind. Two conditions before any lane-A proposal: (a) re-measure the absolute target at n≥40 settled in 30d — the current $74 margin does not survive normal variance; (b) hold 0.20–0.40 open to 2026-11-20 as pre-committed. Revert to kellyEnabled=0 is not indicated. If the target is still marginal at n≥40, the first proposal to test is kellyFraction 0.5→0.55 on the <0.20 band only (cheapest lever on realized $ per settled copy), not a cap increase.

