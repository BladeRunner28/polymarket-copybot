**Kelly Window Report — 2026-11-16** (regime day 71 — FINAL READ)
Rules v73: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7524 | open $18 | net worth $7542 | realized $5642 | exposure 18/$3821 | drawdown 5.6% (realized basis, peak $7987 vs NW $7542)

**Last 24h:** 7 copies opened (3 main-lane, 4 lane) | $85 booked | realized $-17.99 on the 7 of them already settled
**Settled in the last 24h (any open date):** realized $-17.99 across 10 trades
[KELLY] decisions in log: 3338 (289 sized, 3049 skipped). Top skip reasons: no edge: q=0.411 ≤ price=0.435 (289); no edge: q=0.491 ≤ price=0.515 (187); no edge: q=0.501 ≤ price=0.525 (183)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 93 | $86 | $100 | $3085 (93 res) | $0 open |
| 0.20-0.40 | 121 | $22 | $100 | $41 (120 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 23 | $19 | $50 | $13 (23 res) | $0 open |
| >=0.80 | 16 | $94 | $100 | $116 (16 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1294 copies, realized $2252
**Target check (mid/high-band ≈0):** 39/253 ✗ ABOVE expected ≈0 — inspect


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 234 | $69 |
| 0.40-0.60 | 585 | $-355 |
| 0.60-0.80 | 233 | $-47 |
| >=0.80 | 161 | $2 |
Baseline total realized $134 on 1290 pre-Kelly copies | Kelly-window main-lane realized $3256 on 253 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $-530 on n=40 vs $2,500 → ✗ short $3030 · all-time in regime $3085 on n=93 · same 30d by OPEN date (cohort opened in-window, 40/40 settled): $-530 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 214/253 copies in <0.40 ✗ (mid/high 39) | mid-band ≈0 39/253 ✗ ABOVE expected ≈0 — inspect | drawdown 5.6% (realized basis) vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

## FINAL VERDICT (pre-registered §6, read 2026-11-16)

**Window status:** pre-registered window Sep 8 – Oct 8 (read Oct 8). This read lands 39 days past close (regime day 71) — a post-window read of the same cohort family, not an on-time read.

| check | §6 target | actual | result |
|---|---|---|---|
| concentration | book in <0.40 | 214/253 = 85% | ✓ direction |
| mid/high count | ≈0 | 39/253 | ✗ above |
| mid-band 0.40–0.60 | skip, ≈0 | 0 copies, $0 | starved, unproven |
| <0.20 realized (abs) | ≥$2,500/30d | −$530/30d; $3,085/71d (≈$1,300/30d) | ✗ |
| drawdown | ≤ 20% (realized basis) | 5.6% | ✓ |

**Band vs λ̂ (Sep-1 table):**
- **<0.20** — λ̂ −0.91, sign right all-time (+$3,085 on n=93) but the ABSOLUTE target fails on the 30-day reading: −$530 on n=40, short $3,030. The all-time positive and the trailing-negative disagree; that's a refit question, not a Kelly question.
- **0.20–0.40** — **UNRESOLVED through 2026-11-20.** +$41 at n=121; flipped sign vs λ̂ −0.21 at n=77 (noise-level). Not a loss, not evidence either way.
- **0.40–0.60** — zero copies. "≈0" is starvation by the zero-edge rule (3,049 skips), not demonstrated calibration.
- **0.60–0.80** — 23 copies, +$13 (flat) — aligned with λ̂, skip was right.
- **≥0.80** — 16 copies Kelly-sized, +$116 vs λ̂ +0.37 (skip). Mild misalignment at n=16; immaterial.

**Drawdown correction (instrument):** the 34.2% printed earlier today was the MTM watermark ($11,458, stale since the 11-10 ledger repair) divided into a realized-basis book. The live gate reads `realizedPeak` (rebased $7,987.32 on 11-15, Lane-A approved) → 5.6%, under the 20% cap, which is why 3 main-lane copies opened in the last 24h. Reporter is now basis-aware (scripts/kelly-window-report.ts), same precedence as score-trades.ts; no rule or gate change.

**Recommendation (rules untouched; needs approval):**
1. Keep `kellyEnabled=1` — the mechanism is doing its job: 3,049 skips, mid-band fully starved, long-shot is the only net-positive region in either cohort.
2. The binding fail is the ABSOLUTE long-shot target, not sizing discipline. If the target stays binding: drop `kellyFraction` 0.5→0.35 and `kellyMaxSizeUsd` 100→75 while 85% of the book sits in one band — cuts variance, keeps the skip logic.
3. Do NOT revert to `kellyEnabled=0`: legacy mid-band was −$355 at n=585, the band Kelly refuses to size.
4. Refit λ̂ before any fraction increase: ≥0.80 misaligns (+$116 vs skip) and the 0.20–0.40 sign flip still needs the 11-20 read.
