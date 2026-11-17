**Kelly Window Report — 2026-11-17** (regime day 72 — FINAL READ)
Rules v73: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7348 | open $48 | net worth $7379 | realized $5496 | exposure 48/$3739 | drawdown 7.4% (realized basis, peak $7987 vs NW $7396)

**Last 24h:** 15 copies opened (7 main-lane, 8 lane) | $293 booked | realized $-146.28 on the 12 of them already settled
**Settled in the last 24h (any open date):** realized $-146.28 across 12 trades
[KELLY] decisions in log: 3443 (296 sized, 3147 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.491 ≤ price=0.515 (188); no edge: q=0.501 ≤ price=0.525 (183)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 94 | $86 | $100 | $2985 (94 res) | $0 open |
| 0.20-0.40 | 127 | $22 | $100 | $5 (126 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 23 | $19 | $50 | $13 (23 res) | $0 open |
| >=0.80 | 16 | $94 | $100 | $116 (16 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1302 copies, realized $2242
**Target check (mid/high-band ≈0):** 39/260 ✗ ABOVE expected ≈0 — inspect

**WEEKLY (7d):** 97 copies opened | realized $170.94

**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 234 | $69 |
| 0.40-0.60 | 585 | $-355 |
| 0.60-0.80 | 233 | $-47 |
| >=0.80 | 161 | $2 |
Baseline total realized $134 on 1290 pre-Kelly copies | Kelly-window main-lane realized $3120 on 260 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $-330 on n=38 vs $2,500 → ✗ short $2830 · all-time in regime $2985 on n=94 · same 30d by OPEN date (cohort opened in-window, 38/38 settled): $-330 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 221/260 copies in <0.40 ✗ (mid/high 39) | mid-band ≈0 39/260 ✗ ABOVE expected ≈0 — inspect | drawdown 7.4% (realized basis) vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

## FINAL VERDICT (pre-registered §6, read 2026-11-17)

**Window status:** pre-registered Sep 8 – Oct 8 (read Oct 8). This read lands 40 days past close (regime day 72) — post-window read of the same cohort family, not an on-time read.

| check | §6 target | actual | result |
|---|---|---|---|
| concentration | book in <0.40 | 221/260 = 85% | ✓ direction |
| mid/high count | ≈0 | 39/260 | ✗ above |
| mid-band 0.40–0.60 | skip, ≈0 | 0 copies, $0 | starved, unproven |
| <0.20 realized (abs) | ≥$2,500/30d | −$330/30d; $2,985/72d (≈$1,244/30d) | ✗ |
| drawdown | ≤20% (realized basis) | 7.4% | ✓ |

**Band vs λ̂ (Sep-1 table):**
- **<0.20** — λ̂ −0.91; sign right all-time (+$2,985 on n=94), absolute target fails on trailing 30d (−$330, n=38, short $2,830). All-time positive vs trailing-negative disagreement is a λ̂ refit question.
- **0.20–0.40** — **UNRESOLVED through 2026-11-20.** +$5 at n=127; flipped sign vs λ̂ −0.21 at n=77 (noise-level). Not a loss, not evidence.
- **0.40–0.60** — zero copies; "≈0" is starvation by the zero-edge rule, not demonstrated calibration.
- **0.60–0.80** — +$13 on 23, aligned with λ̂; skip was right.
- **≥0.80** — +$116 on 16 vs λ̂ +0.37; mild misalignment, immaterial at n=16.

**24h drift vs 11-16 read:** NW $7,542→$7,379; main-lane realized $3,256→$3,120; DD 5.6%→7.4%; trailing-30d long-shot −$530→−$330 (cohort n 40→38). Runner note: drawdown line cites NW $7,396 vs state line $7,379 — $17 basis gap in the drawdown probe, cosmetic, gate unaffected.

**Recommendation (rules untouched; needs approval):**
1. Keep `kellyEnabled=1` — skip logic is working (3,147 skips, mid-band starved); long-shot remains the only net-positive region.
2. Binding fail is the ABSOLUTE long-shot target, not sizing discipline. If it stays binding: `kellyFraction` 0.5→0.35 and `kellyMaxSizeUsd` 100→75 (variance cut with 85% of book in one band).
3. Do NOT revert to `kellyEnabled=0` — legacy mid-band −$355 at n=585, the band Kelly refuses to size.
4. Refit λ̂ before any fraction increase; hold the 0.20–0.40 call until 2026-11-20.
