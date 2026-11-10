**Kelly Window Report — 2026-11-10** (regime day 65 — FINAL READ)
Rules v71: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $10065 | open $1003 | net worth $11146 | realized $9169 | exposure 1003/$5623 | drawdown 0.0%

**Last 24h:** 24 copies opened (6 main-lane, 18 lane) | $640 booked | realized $18.49 on the 2 of them already settled
**Settled in the last 24h (any open date):** realized $103.11 across 18 trades
[KELLY] decisions in log: 3124 (268 sized, 2856 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.501 ≤ price=0.525 (179); no edge: q=0.481 ≤ price=0.505 (167)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 101 | $86 | $100 | $6638 (93 res) | $750 open |
| 0.20-0.40 | 131 | $21 | $100 | $353 (128 res) | $54 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1233 copies, realized $2037
**Target check (mid/high-band ≈0):** 0/232 ✓ (zero-edge skips holding)

**WEEKLY (7d):** 168 copies opened | realized $2744.59

**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $6991 on 232 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $2902 on n=42 vs $2,500 → ✓ +$402 · all-time in regime $6638 on n=101 · same 30d by OPEN date (cohort opened in-window, 41/49 settled): $2973 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 232/232 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/232 ✓ (zero-edge skips holding) | drawdown 0.0% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

**VERDICT (§6, pre-registered) — 2026-11-10**
- Concentration <0.40: PASS — 232/232 copies, mid/high bands exactly 0.
- Mid-band ≈0: PASS — 0/232 (zero-edge rule, not calibration sight).
- Drawdown: PASS — 0.0% vs 20% gate; no ⚠ flags; exposure $1,003/$5,623 (17.8%) not binding.
- LONG-SHOT ABSOLUTE PnL ≥ $2,500/30d: **PASS** — $2,902 on n=42 (30d by settle date), +$402. All-time in regime $6,638 on n=101. Note: this metric read MISS ($1,898) on 2026-11-07 and passed +$1,004 in two days — met, but only ~16% above the line.
- 0.20–0.40 band: UNRESOLVED through 2026-11-20 — sign flip at n=77+ is noise-level; not a loss, not evidence either way.
- Lane (Kelly-exempt): 1,233 copies, realized $2,037.
- Baseline context: pre-Kelly $140/1,290 copies vs Kelly-window $6,991/232 — raw totals, not a like-for-like rate.

**RECOMMENDATION (approval required, no rule change made):** continue Kelly at v71 settings (fraction 0.5, 10% cap, $100 max). Target is now met, so no cap increase is proposed; the prior $100→$140 sizing idea stays parked unless the 30d long-shot rate dips back under $2,500. 0.20–0.40 stays frozen until Nov 20. Revert (kellyEnabled→0) not recommended.
