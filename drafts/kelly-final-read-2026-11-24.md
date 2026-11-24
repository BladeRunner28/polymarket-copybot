**Kelly Window Report — 2026-11-24** (regime day 79 — FINAL READ)
Rules v73: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $6833 | open $413 | net worth $7244 | realized $5346 | exposure 413/$3672 | drawdown 9.3% (realized basis, peak $7987 vs NW $7246)

**Last 24h:** 20 copies opened (3 main-lane, 17 lane) | $333 booked | realized $0.00 on the 2 of them already settled
**Settled in the last 24h (any open date):** realized $3.46 across 13 trades
[KELLY] decisions in log: 3949 (316 sized, 3633 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.481 ≤ price=0.505 (278); no edge: q=0.491 ≤ price=0.515 (191)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 102 | $87 | $100 | $2585 (100 res) | $200 open |
| 0.20-0.40 | 139 | $21 | $100 | $40 (137 res) | $36 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 23 | $19 | $50 | $13 (23 res) | $0 open |
| >=0.80 | 16 | $94 | $100 | $116 (16 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1436 copies, realized $2457
**Target check (mid/high-band ≈0):** 39/280 ✗ ABOVE expected ≈0 — inspect

**WEEKLY (7d):** 154 copies opened | realized $-149.74

**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 234 | $69 |
| 0.40-0.60 | 585 | $-355 |
| 0.60-0.80 | 233 | $-47 |
| >=0.80 | 161 | $2 |
Baseline total realized $134 on 1290 pre-Kelly copies | Kelly-window main-lane realized $2755 on 280 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $-1092 on n=41 vs $2,500 → ✗ short $3592 · all-time in regime $2585 on n=102 · same 30d by OPEN date (cohort opened in-window, 41/43 settled): $-1092 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 241/280 copies in <0.40 ✗ (mid/high 39) | mid-band ≈0 39/280 ✗ ABOVE expected ≈0 — inspect | drawdown 9.3% (realized basis) vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

## FINAL VERDICT (pre-registered §6, read 2026-11-24)

**Window status:** pre-registered Sep 8 – Oct 8 (read Oct 8). This read lands 47 days past close (regime day 79) — post-window read of the same cohort family, not an on-time read.

| check | §6 target | actual | result |
|---|---|---|---|
| concentration | book in <0.40 | 241/280 = 86% | ✓ direction |
| mid/high count | ≈0 | 39/280 | ✗ above |
| mid-band 0.40–0.60 | skip, ≈0 | 0 copies, $0 | starved, unproven |
| <0.20 realized (abs) | ≥$2,500/30d | −$1,092/30d (n=41); $2,585/79d all-time | ✗ short $3,592 |
| drawdown | ≤20% (realized basis) | 9.3% | ✓ |

Note: the script's concentration field prints ✗ whenever mid/high > 0; the 86% share itself meets the direction. The failing leg is the mid/high COUNT (39), not the concentration share.

**Band vs λ̂ (Sep-1 pre-registered table; current refit 2026-11-15 in brackets):**
- **<0.20** — λ̂ −0.91 [now −0.53], sign right all-time (+$2,585 on n=102) but the ABSOLUTE target fails: trailing 30d −$1,092 on n=41, short $3,592. The Nov-15 refit halved the band's edge, and long-shot sizes now print $87 avg (below the $100 cap), consistent with that. All-time positive vs trailing-negative is a λ̂/regime question, not a sizing bug.
- **0.20–0.40** — **UNRESOLVED through 2026-11-20.** +$40 at n=139 (137 resolved); flipped sign vs λ̂ −0.21 at n=77 (noise-level). Not a loss, not evidence either way.
- **0.40–0.60** — zero copies. "≈0" is starvation by the zero-edge rule (3,633 skips), not demonstrated calibration.
- **0.60–0.80** — 23 copies, +$13 (flat) — aligned with λ̂, skip was right.
- **≥0.80** — 16 copies Kelly-sized (avg $94), +$116 vs λ̂ +0.37 (skip) — mild misalignment at n=16; immaterial. The 39 mid/high copies are a frozen block: unchanged across the last 8 daily reads (no new mid/high sizing since 2026-11-16). Current mid/high λ̂ is positive in every band ([+0.06, +0.34, +0.41]), so skipping stays justified.

**Weekly:** 154 copies opened, realized −$149.74 — sign flip vs +$170.94 last week (97 copies) and far below the +$2,744.59 7d read on 2026-11-10. NW $7,542 (11-16) → $7,244 today, −$298.

**Recommendation (rules untouched; needs approval):**
1. Keep `kellyEnabled=1` — skip logic is still working (3,633 skips, mid-band fully starved); long-shot remains the only net-positive region.
2. Do NOT revert to `kellyEnabled=0` — legacy mid-band was −$355 at n=585, the band Kelly refuses to size.
3. Binding fail is the ABSOLUTE long-shot target, now coinciding with the Nov-15 refit shrinking the <0.20 edge. Re-queue the variance cut: `kellyFraction` 0.5→0.35 and `kellyMaxSizeUsd` 100→75 while 86% of the book sits in one band (this proposal was never approved; rules still v73 fraction 0.5 / $100).
4. Refit/λ̂ drift check on the <0.20 band before any fraction increase; hold the 0.20–0.40 call — the 11-20 read does not settle it at n=139.

