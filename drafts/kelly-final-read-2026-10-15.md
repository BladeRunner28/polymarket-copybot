**Kelly Window Report — 2026-10-15** (regime day 40 — FINAL READ)
Rules v62: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7580 | open $76 | net worth $7655 | realized $5757 | exposure 76/$3877 | drawdown 5.5%

**Last 24h:** 9 Kelly-regime copies opened (2 main-lane, 7 lane) | realized $-58.14 | $93 booked
[KELLY] decisions in log: 588 (156 sized, 432 skipped). Top skip reasons: no edge: q=0.556 ≤ price=0.585 (20); no edge: q=0.381 ≤ price=0.410 (19); no edge: q=0.436 ≤ price=0.465 (16)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 53 | $81 | $100 | $3615 (53 res) | $0 open |
| 0.20-0.40 | 71 | $25 | $100 | $9 (68 res) | $54 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1039 copies, realized $1992
**Target check:** mid/high-band main-lane copies 0/124 → ≈0 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 | Kelly-window main-lane realized $3624
Long-shot (<0.20) realized: baseline $465 → window $3615 (7.8x)
**Verdict fields (pre-registered §6):** concentration ✓/✗ above | mid-band ≈0 ✓/✗ above | drawdown 5.5% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

**FINAL VERDICT (§6 pre-registration, D+7 read 2026-10-15)** — window closed 2026-10-08; this is the
7th consecutive FINAL read (post-window continuation, not a new verdict). Verified before publishing:
`npx tsx scripts/kelly-window-report.ts auto` reproduces every number above byte-for-byte, and the
active RuleSet is **v62** (kellyEnabled=1, fraction 0.5, maxSizeUsd $100, maxBankrollPct 0.10, minEdge 2%).

Band λ̂ alignment — Sep-1 pre-registered → Sep-15 → Oct-1 → **Oct-15 refit (fired 06:00 today,
`data/premium-calibration.json` calibratedAt 2026-10-15T11:00:29Z)**:

- <0.20: −0.910 → −0.789 → −0.779 → **−0.7431** (n=240) → size ✓ | realized +$3,615
- 0.20–0.40: −0.210 → −0.204 → −0.196 → **−0.1580** (487) → size ✓ | realized +$9 (n=71)
- 0.40–0.60: +0.030 → +0.034 → +0.074 → **+0.0596** (1000) → **skip all** ✓ | 0 copies
- 0.60–0.80: +0.210 → +0.214 → +0.219 → **+0.1969** (471) → skip all ✓ | 0 copies
- ≥0.80: +0.370 → +0.291 → +0.291 → **+0.2906** (154) → skip all ✓ | 0 copies

**No sign flips at the Oct-15 refit** — the card `kelly-oct15-lambda-refit-capture` gate is satisfied on
its own terms: λ̂(0.2,0.4) is still negative (no silent band skip), λ̂(<0.20) rose only −0.779 → −0.7431
(≈4.6% smaller modeled long-shot edge ⇒ ≈4.6% smaller long-shot sizes at the sizer — a sizer effect, not
a rule change), and mid-band λ̂ remains positive. The §6 caveat risk did NOT materialize across three
refits, so the mid-band skip is calibration-consistent rather than luck.

| verdict field | pre-registered | measured | result |
|---|---|---|---|
| concentration <0.40 | book in <0.40 | 124/124 copies | ✓ |
| mid-band + 0.60+ ≈0 | ~0 trades | 0/124 | ✓ |
| long-shot share 3–6× | vs baseline | 7.8× | above band (favorable) |
| drawdown vs baseline | ≤ 20% gate | 5.5% | ✓ |

Post-window give-back watch: **frozen close cohort** (main-lane, opened ≤ Oct 8 23:59 CDT; convention
matched to the Oct-13/14 reads) = **+$3,698.20** (<0.20 +$3,736.61 n=51 · 0.20–0.40 −$38.41 n=57) vs
**rolling +$3,624.10** → **−$74.10 give-back**, entirely long-shot (−$121.43) against +$47.33 of
mid-band recovery. Per-copy long-shot edge: baseline $6.04 → rolling $68.21 (11.3×, cap-inflated, n=53).
Post-Oct-1 calibration read (N=319, `scripts/analyze-calibration.py --since 2026-10-01`): entry
0.00–0.20 excess +0.1080 (z=+1.63, p=0.10) — the long-shot edge is positive but not yet significant on
post-window volume; 0.40–0.60 excess +0.0089 (z=0.22) i.e. ≈fair, consistent with the skip.

**Recommendation (recommendations only — no rule, code or size change without explicit approval):
KEEP Kelly**, kellyEnabled=1 at v62, cap $100, fraction 0.5 — the same call as the user-approved
2026-10-13 decision (cap trim to $60 declined; measured cost of that trim was −$1,485 profit for +$19
mid-band). No ⚠ flags: drawdown 5.5% vs 20% gate, exposure $76/$3,877 = 2.0% (not binding). Sole live
lever remains the sizer (λ̂ / kellyFraction): if the <0.20 per-copy edge decays further at the $100 cap,
trim kellyFraction rather than the cap. No new RuleSet version proposed.
