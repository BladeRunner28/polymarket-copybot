**Kelly Window Report — 2026-10-14** (regime day 39 — FINAL READ)
Rules v62: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7610 | open $105 | net worth $7710 | realized $5815 | exposure 105/$3905 | drawdown 4.8%

**Last 24h:** 9 Kelly-regime copies opened (2 main-lane, 7 lane) | realized $116.96 | $98 booked
[KELLY] decisions in log: 576 (154 sized, 422 skipped). Top skip reasons: no edge: q=0.556 ≤ price=0.585 (20); no edge: q=0.381 ≤ price=0.410 (19); no edge: q=0.436 ≤ price=0.465 (16)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 53 | $81 | $100 | $3615 (53 res) | $0 open |
| 0.20-0.40 | 69 | $25 | $100 | $27 (67 res) | $36 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1032 copies, realized $2032
**Target check:** mid/high-band main-lane copies 0/122 → ≈0 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 | Kelly-window main-lane realized $3642
Long-shot (<0.20) realized: baseline $465 → window $3615 (7.8x)
**Verdict fields (pre-registered §6):** concentration ✓/✗ above | mid-band ≈0 ✓/✗ above | drawdown 4.8% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

**FINAL VERDICT (§6 pre-registration, verified 2026-10-14)** — window closed Oct 8; this is the 6th
consecutive read, now post-window continuation rather than a new verdict.

Band λ̂ alignment (Sep-1 pre-registered → Sep-15 refit → Oct-1 refit → live log avg):

- <0.20: −0.910 → −0.789 → −0.779 → −0.815 (49 decisions) → **size** ✓ | realized +$3,615
- 0.20–0.40: −0.210 → −0.204 → −0.196 → −0.198 (106) → size ✓ | realized +$27 (n=69)
- 0.40–0.60: +0.030 → +0.034 → +0.074 → +0.064 (247) → **skip all** ✓ | 0 copies
- 0.60–0.80: +0.210 → +0.214 → +0.219 → +0.219 (89) → skip all ✓ | 0 copies
- ≥0.80: +0.370 → +0.291 → +0.291 → +0.327 (85) → skip all ✓ | 0 copies

The §6 caveat risk did NOT materialize: mid-band λ̂ stayed positive through both refits (Sep-15
+0.034, Oct-1 +0.074), so the zero-edge skip was calibration-consistent, not luck. Sign alignment
holds: the most-negative-λ̂ band is the only profitable band.

| verdict field | pre-registered | measured | result |
|---|---|---|---|
| concentration <0.40 | book in <0.40 | 122/122 copies | ✓ |
| mid-band + 0.60+ ≈0 | ~0 trades | 0/122 | ✓ |
| long-shot share 3–6× | vs baseline | 7.8× | above band (favorable) |
| drawdown vs baseline | ≤ 20% gate | 4.8% | ✓ |

Frozen close cohort (main-lane, opened ≤ Oct 8): <0.20 **+$3,737** (n=51, all resolved) ·
0.20–0.40 **−$38** (n=57) · **total +$3,698**. Rolling today (adds 2 long-shot + 12 mid-band
post-window copies, mid-band railed to $17.99): +$3,642 — i.e. **−$56 of post-window give-back**,
entirely long-shot (−$122) against +$65 mid-band recovery. Long-shot per-copy: baseline $6.04 →
window $68.21 (11.3×), inflated by the $20→$100 cap and fat-tailed.

**Recommendation (recommendations only — no change without explicit approval): KEEP Kelly**
(kellyEnabled=1, fraction 0.5, caps unchanged at v62), consistent with the 2026-10-13 in-thread
decision (cap trim to $60 declined; measured cost of that trim was −$1,485 with only +$19 mid-band
benefit). Sole live lever is the **Oct 15 λ̂ refit** (fires 06:00, card
`kelly-oct15-lambda-refit-capture`): does <0.20 λ̂ keep drifting toward 0 — already −0.910 → −0.779
= ~17% smaller modeled long-shot edge → ~17% smaller long-shot sizes — and does mid-band λ̂ stay
≥ 0. If the frozen cohort's long-shot per-copy edge decays further post-close, the lever is the
sizer (λ̂ / kellyFraction), not a cap trim. No ⚠ flags: drawdown 4.8% vs 20% gate, exposure
$105/$3,905 (2.7%) not binding; active RuleSet v62 verified (kellyEnabled=1, fraction 0.5,
maxSizeUsd 100, maxBankrollPct 0.10).
