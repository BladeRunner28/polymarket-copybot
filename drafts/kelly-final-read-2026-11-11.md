**Kelly Window Report — 2026-11-11** (regime day 66 — FINAL READ)
Rules v71: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $9738 | open $1146 | net worth $10916 | realized $8984 | exposure 1146/$5508 | drawdown 4.7%

**Last 24h:** 39 copies opened (14 main-lane, 25 lane) | $1050 booked | realized $-45.34 on the 11 of them already settled
**Settled in the last 24h (any open date):** realized $-184.38 across 33 trades
[KELLY] decisions in log: 3247 (282 sized, 2965 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.501 ≤ price=0.525 (180); no edge: q=0.481 ≤ price=0.505 (175)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 108 | $87 | $100 | $6430 (99 res) | $850 open |
| 0.20-0.40 | 138 | $21 | $100 | $360 (134 res) | $72 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1258 copies, realized $2053
**Target check (mid/high-band ≈0):** 0/246 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $6790 on 246 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $2815 on n=46 vs $2,500 → ✓ +$315 · all-time in regime $6430 on n=108 · same 30d by OPEN date (cohort opened in-window, 46/55 settled): $2815 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 246/246 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/246 ✓ (zero-edge skips holding) | drawdown 4.7% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

**VERDICT (§6, pre-registered) — 2026-11-11** (window Sep 8–Oct 8 closed 34d ago; post-window tracking)

| band | λ̂ (Sep-1) | intent | Kelly realized |
|---|---|---|---|
| <0.20 | −0.91 | size (cap-bound) | +$6430 / n=108 ✓ aligned |
| 0.20-0.40 | −0.21 | size | +$360 / n=138 — UNRESOLVED |
| 0.40-0.60 | +0.03 | skip | $0 / 0 ✓ skip held |
| 0.60-0.80 | +0.21 | skip | $0 / 0 ✓ |
| >=0.80 | +0.37 | skip | $0 / 0 ✓ |

- Concentration <0.40: **PASS** — 246/246 copies; mid/high bands exactly 0.
- Mid-band ≈0: **PASS** — 0/246 (zero-edge rule, not calibration sight).
- Drawdown: **PASS** — 4.7% vs 20% gate. Exposure $1,146/$5,508 (20.8%), not binding.
- LONG-SHOT ABSOLUTE ≥ $2,500/30d (re-baselined 2026-10-21, kelly rec 3): **PASS but thin** — $2,815 on n=46 by settle date, +$315 (13% above line). All-time in regime $6,430 / n=108. Same 30d by open date is a different cohort, not the rate.
- 0.20–0.40: **UNRESOLVED through 2026-11-20** — flipped sign against its λ̂ at n=77, noise-level; not a loss, not evidence either way.
- Lane (Kelly-exempt): 1,258 copies, realized $2,053.
- Baseline context: pre-Kelly $140 / 1,290 copies vs Kelly-window $6,790 / 246 — raw totals, different periods, not a like-for-like rate.

Day was negative: realized −$185 across 33 settlements (24h), net worth $11,146 → $10,916. Drawdown moved 0.0% → 4.7%, still far inside the gate; long-shot 30d cushion narrowed $402 → $315.

**RECOMMENDATION (approval required; no rule or code change made):** continue Kelly at v71 (fraction 0.5, 10% cap, $100 max). Do not raise caps — the 30d target is met by only ~13% and one bad settle day erased a quarter of the cushion. $100→$140 sizing stays parked; 0.20–0.40 stays frozen to Nov 20; revert (kellyEnabled→0) not recommended — <0.20 remains the whole book and the only proven edge.

