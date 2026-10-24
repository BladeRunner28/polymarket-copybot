**Kelly Window Report — 2026-10-23** (regime day 48 — FINAL READ)
Rules v65: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7894 | open $24 | net worth $7917 | realized $6018 | exposure 24/$4009 | drawdown 2.2%

**Last 24h:** 2 copies opened (1 main-lane, 1 lane) | $29 booked | realized $-20.00 on the 1 of them already settled
**Settled in the last 24h (any open date):** realized $-1.82 across 6 trades
[KELLY] decisions in log: 984 (169 sized, 815 skipped). Top skip reasons: no edge: q=0.392 ≤ price=0.415 (66); no edge: q=0.521 ≤ price=0.545 (45); no edge: q=0.572 ≤ price=0.595 (43)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 58 | $83 | $100 | $3727 (58 res) | $0 open |
| 0.20-0.40 | 79 | $24 | $100 | $-30 (78 res) | $9 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1084 copies, realized $2180
**Target check (mid/high-band ≈0):** 0/137 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $3698 on 137 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $2167 on n=22 vs $2,500 → ✗ short $333 · all-time in regime $3727 on n=58 · same 30d by OPEN date (cohort opened in-window, 19/19 settled): $624 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 137/137 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/137 ✓ (zero-edge skips holding) | drawdown 2.2% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

## FINAL VERDICT vs pre-registered §6 (2026-10-23)

| band | λ̂ (Sep-1) | §6 expectation | realized | verdict |
|---|---|---|---|---|
| <0.20 | −0.91 | size, cap-bound | $3,727 (n=58) | aligned ✓ |
| 0.20–0.40 | −0.21 | size | −$30 (n=78, 1 open $9) | sign flip at noise level → UNRESOLVED to 2026-11-20 |
| 0.40–0.60 | +0.03 | skip | 0 copies | aligned-by-skip ✓ |
| 0.60–0.80 | +0.21 | skip | 0 copies | aligned ✓ |
| ≥0.80 | +0.37 | skip | 0 copies | aligned ✓ |

- Concentration: 137/137 main-lane copies in <0.40 ✓
- Mid-band ≈0: 0/137 in 0.40–0.80 ✓ (zero-edge skips holding)
- LONG-SHOT ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3): $2,167 / 30d by settle date vs $2,500 → ✗ short $333 (87% of target). All-time in regime $3,727 on n=58. By-open-date cohort ($624, 19/19 settled) is a different cohort and is NOT the 30-day rate.
- Drawdown: 2.2% vs 20% gate ✓. Exposure $24/$4,009 — not binding.
- Retired: 3–6× pre-Kelly ratio target (false FAIL at 8.0× from the $140 baseline denominator). Do not cite.

**Recommendation (recommendations only — no rule or code change made):** continue Kelly at fraction 0.5 with current caps. The single miss is the long-shot absolute rate, and that band is cap-bound (avg $83 vs $100 cap), so capacity rather than edge is plausibly binding. Candidate test, not executed: kellyMaxSizeUsd $100→$150 as a 30-day A/B, gated on long-shot band λ̂ staying aligned at the next calibration refit. Hold 0.20–0.40 as UNRESOLVED and re-read 2026-11-20.

