**Kelly Window Report — 2026-11-14** (regime day 69 — FINAL READ)
Rules v73: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7193 | open $378 | net worth $7580 | realized $5671 | exposure 378/$3840 | drawdown 33.8%
⚠ **drawdown 33.8% EXCEEDS the 20% gate** — new copies should be journaled watchlist; confirm the gate is tripping

**Last 24h:** 0 copies opened (0 main-lane, 0 lane) | $0 booked | realized $0.00 on the 0 of them already settled
**Settled in the last 24h (any open date):** realized $-2.71 across 1 trades
[KELLY] decisions in log: 3318 (286 sized, 3032 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.501 ≤ price=0.525 (183); no edge: q=0.481 ≤ price=0.505 (178)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 93 | $86 | $100 | $3096 (89 res) | $350 open |
| 0.20-0.40 | 118 | $22 | $100 | $59 (117 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 23 | $19 | $50 | $13 (23 res) | $0 open |
| >=0.80 | 16 | $94 | $100 | $116 (16 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1290 copies, realized $2252
**Target check (mid/high-band ≈0):** 39/250 ✗ ABOVE expected ≈0 — inspect


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 234 | $69 |
| 0.40-0.60 | 585 | $-355 |
| 0.60-0.80 | 233 | $-47 |
| >=0.80 | 161 | $2 |
Baseline total realized $134 on 1290 pre-Kelly copies | Kelly-window main-lane realized $3285 on 250 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $-519 on n=36 vs $2,500 → ✗ short $3019 · all-time in regime $3096 on n=93 · same 30d by OPEN date (cohort opened in-window, 36/40 settled): $-519 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 211/250 copies in <0.40 ✗ (mid/high 39) | mid-band ≈0 39/250 ✗ ABOVE expected ≈0 — inspect | drawdown 33.8% vs 20% gate ✗
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

## FINAL VERDICT (pre-registered §6, read 2026-11-13)

**Window status:** pre-registered window was Sep 8 – Oct 8 (reads Oct 8). This read lands 36 days after the window closed (regime day 69), so it is a post-window read of the same cohort family, not an on-time read.

| check | target (§6) | actual | result |
|---|---|---|---|
| concentration | book in <0.40 | 211/250 = 84% | ✓ direction |
| mid/high count | ≈0 | 39/250 | ✗ above |
| mid-band 0.40–0.60 | skip, ≈0 | 0 copies, $0 | starved, unproven |
| <0.20 realized (abs) | ≥$2,500/30d | −$519/30d; $3,096/69d (≈$1,346/30d) | ✗ |
| drawdown | ≤ pre-Kelly baseline (20% gate) | 33.8% | ✗ |

**Band vs λ̂ (Sep-1 table):**
- <0.20 — λ̂ −0.91, signed right (+$3,096 over regime) but the absolute target is not met on any 30-day reading; trailing 30d by settle date is −$519 on n=36.
- 0.20–0.40 — **UNRESOLVED through 2026-11-20.** +$59 at n=118; flipped sign vs λ̂ −0.21 at n=77, noise-level. Not a loss, not evidence either way.
- 0.40–0.60 — zero copies. The "≈0" is starvation by the zero-edge rule, not demonstrated calibration.
- 0.60–0.80 — 23 copies, +$13 (flat, aligned).
- ≥0.80 — 16 copies Kelly-sized, +$116. λ̂ said skip; realized says otherwise at n=16 — immaterial, but note Kelly overrode the skip here.

**Recommendation (rules untouched; needs approval):**
1. Ops: confirm the 20% drawdown gate is actually tripping and journaling watchlist instead of sizing — 33.8% breach is the one hard fail.
2. Primary lean: keep `kellyEnabled=1` — the skip logic is doing the job it was built for (mid-band starvation, 3,032 skips), and the long-shot band is the only net-positive region in either cohort.
3. Option set if the target is the binding constraint: (a) hold fraction 0.5 and let the 11-20 read decide; (b) drop `kellyFraction` to 0.35 with `kellyMaxSizeUsd` 100 → 75 to cut long-shot variance while the drawdown gate is open; (c) revert `kellyEnabled=0` — not supported by this read, since legacy mid-band was −$355 at n=585.
4. λ̂ refit: the ≥0.80 misalignment (λ̂ +0.37 vs +$116 realized) and the 0.20–0.40 sign flip both say refit before any fraction increase.

