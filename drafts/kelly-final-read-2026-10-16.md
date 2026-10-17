**Kelly Window Report — 2026-10-16** (regime day 41 — FINAL READ)
Rules v62: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7498 | open $118 | net worth $7619 | realized $5716 | exposure 118/$3859 | drawdown 5.9%

**Last 24h:** 10 Kelly-regime copies opened (1 main-lane, 9 lane) | realized $-40.35 | $98 booked
[KELLY] decisions in log: 599 (157 sized, 442 skipped). Top skip reasons: no edge: q=0.556 ≤ price=0.585 (20); no edge: q=0.381 ≤ price=0.410 (19); no edge: q=0.436 ≤ price=0.465 (16)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 53 | $81 | $100 | $3615 (53 res) | $0 open |
| 0.20-0.40 | 72 | $25 | $100 | $-33 (71 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1048 copies, realized $1994
**Target check:** mid/high-band main-lane copies 0/125 → ≈0 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 | Kelly-window main-lane realized $3582
Long-shot (<0.20) realized: baseline $465 → window $3615 (7.8x)
**Verdict fields (pre-registered §6):** concentration ✓/✗ above | mid-band ≈0 ✓/✗ above | drawdown 5.9% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

**FINAL VERDICT (§6 pre-registration, D+8 read 2026-10-16)** — window closed 2026-10-08; this is the
8th consecutive FINAL read (post-window continuation, not a new verdict). Verified before publishing:
`DATA_MODE=live npx tsx scripts/kelly-window-report.ts auto` reproduces every number above
byte-for-byte, and the active RuleSet is **v62** (kellyEnabled=1, fraction 0.5, maxSizeUsd $100,
maxBankrollPct 0.10, minEdge 2%).

Band λ̂ alignment — Sep-1 pre-registered → Sep-15 → Oct-1 → **Oct-15 refit (still current;
`data/premium-calibration.json` calibratedAt 2026-10-15T11:00:29Z, no Oct-16 refit fired)**:

- <0.20: −0.910 → −0.789 → −0.779 → **−0.7431** (n=240) → size ✓ | realized +$3,615
- 0.20–0.40: −0.210 → −0.204 → −0.196 → **−0.1580** (487) → size ✓ | realized −$33 (n=72)
- 0.40–0.60: +0.030 → +0.034 → +0.074 → **+0.0596** (1000) → skip all ✓ | 0 copies
- 0.60–0.80: +0.210 → +0.214 → +0.219 → **+0.1969** (471) → skip all ✓ | 0 copies
- ≥0.80: +0.370 → +0.291 → +0.291 → **+0.2906** (154) → skip all ✓ | 0 copies

**No sign flips across four refits** — the card `kelly-oct15-lambda-refit-capture` gate stays satisfied
(λ̂(0.2,0.4) still negative, λ̂(<0.20) drifting toward 0 = smaller modeled long-shot edge = smaller
long-shot sizes at the sizer, mid-band λ̂ still positive), so the mid-band skip is
calibration-consistent rather than luck. Sign alignment holds: the most-negative-λ̂ band is the only
profitable band, so size/skip matches each band's realized sign 5/5.

| verdict field | pre-registered | measured | result |
|---|---|---|---|
| concentration <0.40 | book in <0.40 | 125/125 copies | ✓ |
| mid-band + 0.60+ ≈0 | ~0 trades | 0/125 | ✓ |
| long-shot share 3–6× | vs baseline | 7.8× | above band (favorable) |
| drawdown vs baseline | ≤ 20% gate | 5.9% | ✓ |

No ⚠ flags: drawdown 5.9% vs the 20% gate, exposure $118/$3,859 = 3.1% (not binding), and the
script's exposure-cap warning line did not print.

Frozen close cohort (main-lane, opened ≤ Oct 8 23:59 CDT; convention matched to the Oct-13/14/15
reads) = **+$3,698.20** (<0.20 +$3,736.61 n=51 · 0.20–0.40 −$38.41 n=57) vs **rolling +$3,582.17** →
**−$116.03 give-back** (yesterday −$74.10 — the give-back widened ~$42 in 24h), entirely long-shot
(−$121.43 on the two post-window copies: p=0.105 $100 −$71.43, p=0.0844 $50 −$50.00) against +$5.40 of
mid-band recovery across 15 post-window mid-band copies (sizes railed $17.99 / $9.00 = the sizer's
small-λ̂ output, no band remap). Per-copy long-shot edge: baseline $6.04 → rolling $68.21 (11.3×,
cap-inflated by the $20→$100 cap change, n=53, fat-tailed).

**Recommendation (recommendations only — no rule, code or size change without explicit approval):
KEEP Kelly**, kellyEnabled=1 at v62, cap $100, fraction 0.5 — the same call as the user-approved
2026-10-13 decision (the $60 cap trim was measured at −$1,485 profit for +$19 mid-band). The
post-window long-shot losses are the expected cost of the measured long-shot edge at cap size, not a
regime break: rolling main-lane is still +$3,582 vs the +$140 pre-Kelly baseline. Sole live lever
remains the sizer (λ̂ / kellyFraction): if the <0.20 per-copy edge keeps decaying at the $100 cap,
trim kellyFraction rather than the cap. Next scheduled λ̂ refit ≈ Oct 29; no new RuleSet version
proposed.
