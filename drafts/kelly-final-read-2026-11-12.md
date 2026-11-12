**Kelly Window Report — 2026-11-12** (regime day 67 — FINAL READ)
Rules v72: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $6458 | open $1034 | net worth $7537 | realized $5592 | exposure 1034/$3819 | drawdown 34.2%
⚠ **drawdown 34.2% EXCEEDS the 20% gate** — new copies should be journaled watchlist; confirm the gate is tripping

**Last 24h:** 36 copies opened (4 main-lane, 32 lane) | $632 booked | realized $532.90 on the 10 of them already settled
**Settled in the last 24h (any open date):** realized $451.52 across 32 trades
[KELLY] decisions in log: 3318 (286 sized, 3032 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.501 ≤ price=0.525 (183); no edge: q=0.481 ≤ price=0.505 (178)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 93 | $86 | $100 | $3230 (86 res) | $650 open |
| 0.20-0.40 | 118 | $22 | $100 | $59 (117 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 23 | $19 | $50 | $13 (23 res) | $0 open |
| >=0.80 | 16 | $94 | $100 | $116 (16 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1290 copies, realized $2039
**Target check (mid/high-band ≈0):** 39/250 ✗ ABOVE expected ≈0 — inspect


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 234 | $69 |
| 0.40-0.60 | 585 | $-355 |
| 0.60-0.80 | 233 | $-47 |
| >=0.80 | 161 | $2 |
Baseline total realized $134 on 1290 pre-Kelly copies | Kelly-window main-lane realized $3419 on 250 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $-385 on n=33 vs $2,500 → ✗ short $2885 · all-time in regime $3230 on n=93 · same 30d by OPEN date (cohort opened in-window, 33/40 settled): $-385 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 211/250 copies in <0.40 ✗ (mid/high 39) | mid-band ≈0 39/250 ✗ ABOVE expected ≈0 — inspect | drawdown 34.2% vs 20% gate ✗
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

**VERDICT (§6, pre-registered) — 2026-11-12** (window Sep 8–Oct 8 closed 34d ago; post-window tracking)

| band | λ̂ (Sep-1) | realized | verdict |
|---|---|---|---|
| <0.20 | −0.91 | +$3,230 (n=93) | aligned ✓ |
| 0.20-0.40 | −0.21 | +$59 (n=118) | UNRESOLVED → 2026-11-20 |
| 0.40-0.60 | +0.03 | $0 (n=0) | skip held ✓ |
| 0.60-0.80 | +0.21 | +$13 (n=23) | immaterial |
| ≥0.80 | +0.37 | +$116 (n=16) | immaterial |

- **Concentration:** 211/250 copies landed in <0.40 ✓ on substance (the zero-tolerance check prints ✗ because 39 are mid/high). Those 39 are repair artifacts, not new mid-band bets: of the 50 C-200 rows in the approved 233-row price-side repair, 47 moved UP (29 → 0.60–0.80, 17 → ≥0.80, 1 → 0.60–0.80). Decision-time behaviour remained concentrated.
- **Long-shot ABSOLUTE target (re-baselined 2026-10-21):** trailing 30d by settle −$385 on n=33 vs +$2,500 → **FAIL, short $2,885.**
- **⚠ This reverses yesterday's PASS (+$2,815).** The 18 C-200 rows recorded at <0.20 that were actually ≥0.80 carried $3,965 → $121 realized after correction. The long-shot edge measured through 2026-11-11 was largely a mispriced ledger, not an edge.
- **Drawdown vs 20% gate:** ✗ but the breach is accounting, not trading. The approved price-side repair (commit d974287, 12:39 CST today) cut BANKROLL_200 realized $8,913 → $5,070; the $11,458 peak ratcheted on the pre-repair book and was NOT reset (a reset is a deliberate act). The gate is firing in today's scorer (`[RISK-GATE] drawdown gate [realized] 32.3% > 20%`), yet 9 fills still booked after the repair (1 main-lane $100, 8 lane) — confirm the gate covers the fill path, not only scored decisions.
- **0.20-0.40:** UNRESOLVED through 2026-11-20 (flipped sign against λ̂ at n=77; noise-level). Not a loss, not evidence either way.

**Recommendation (no rules or code changed):**
1. Hold kellyEnabled=1, fraction 0.5, caps — no increase. The band that justified cap-bound sizing just lost $3,200 of realized to a ledger correction.
2. Decide the peak: re-seed to post-repair equity with a note (recommended), or accept the gate freezing C-200 entries. This is Lane A — one deliberate act, user-approved, not mine to take.
3. Re-read <0.20 on post-repair-only settlements at n≥30 before any revert or size increase; do not revert Kelly on ~1 day of clean data.
