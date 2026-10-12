**Kelly Window Report — 2026-10-11** (regime day 36 — FINAL READ)
Rules v61: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7659 | open $4 | net worth $7665 | realized $5763 | exposure 4/$3882 | drawdown 5.3%

**Last 24h:** 5 Kelly-regime copies opened (1 main-lane, 4 lane) | realized $50.74 | $64 booked
[KELLY] decisions in log: 550 (145 sized, 405 skipped). Top skip reasons: no edge: q=0.556 ≤ price=0.585 (20); no edge: q=0.381 ≤ price=0.410 (18); no edge: q=0.436 ≤ price=0.465 (16)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 53 | $81 | $100 | $3615 (53 res) | $0 open |
| 0.20-0.40 | 60 | $27 | $100 | $-8 (60 res) | $0 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1001 copies, realized $2015
**Target check:** mid/high-band main-lane copies 0/113 → ≈0 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 | Kelly-window main-lane realized $3608
Long-shot (<0.20) realized: baseline $465 → window $3615 (7.8x)
**Verdict fields (pre-registered §6):** concentration ✓/✗ above | mid-band ≈0 ✓/✗ above | drawdown 5.3% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

**§6 PRE-REGISTERED VERDICT (hermes, 2026-10-11, post-close read, +3d)**

Window Sep 8 – Oct 8; formal gate already closed 2026-10-09 (tuning review #50 rec 1,
approved). This read is post-close confirmation, not a new gate. Sep-1 λ̂ (design §6)
vs the live refit (`data/premium-calibration.json`, calibratedAt 2026-10-01;
Sep-15 values per the 2026-10-09 capture) vs realized band PnL:

| band | λ̂ Sep-1 | λ̂ Oct-1 | window realized | baseline |
|---|---|---|---|---|
| <0.20 | −0.91 | −0.78 | +$3,615 | $465 |
| 0.20–0.40 | −0.21 | −0.20 | −$8 | $80 |
| 0.40–0.60 | +0.03 | +0.07 | $0 (0 copies) | −$366 |
| 0.60–0.80 | +0.21 | +0.22 | $0 (0 copies) | −$41 |
| ≥0.80 | +0.37 | +0.29 | $0 (0 copies) | $2 |

Sep-15 refit λ̂ (captured 2026-10-09): <0.20 −0.789 · 0.20–0.40 −0.2042 · 0.40–0.60
+0.0341 · 0.60–0.80 +0.2142 · ≥0.80 +0.2906.

1. **Concentration <0.40 → ✓** (113/113 main-lane copies; mid/high bands 0/113).
2. **Mid-band ≈0 → ✓** (0 copies admitted; zero-edge skip held the whole window).
3. **Long-shot <0.20 realized $465 (baseline) → $3,615 = 7.8×** vs the pre-registered
   3–6× band → above the top of band (favorable, i.e. more concentrated than expected).
4. **Drawdown 5.3% vs 20% gate ✓** (no ⚠; exposure $4/$3,882 → not binding).
5. **λ̂ alignment caveat → satisfied:** no band flipped sign across the Sep-1 → Sep-15 →
   Oct-1 refits (mid-band λ̂ moved +0.034 → +0.074, still positive), so the 0.40–0.60
   skip is calibration-justified, not merely the zero-edge rule firing by luck.
6. **Trend/monitoring:** window main-lane realized slipped $3,737 → $3,615 (−$122) over
   the last 24h on long-shot resolutions; DD rose 3.7% → 5.3% (still 3.8× inside gate).
   0.20–0.40 band closed at −$8 over n=60 vs +$80 baseline (n=236) — carry-forward
   re-check, not a Kelly failure (the band is rail-capped, not Kelly-sized).

Baseline total realized $140 vs window main-lane $3,608.

**Recommendation (recommendations only — no rule or code change made):** CONTINUE Kelly
(kellyEnabled=1, kellyFraction=0.5). Proposals for user approval: (a) revert
`kellyMaxSizeUsd` 100→60 (design §5 default) to bound sized-band variance in the next
window; (b) re-check the 0.20–0.40 band next window; (c) keep the short-TTR lane
Kelly-exempt.
