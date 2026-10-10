**Kelly Window Report — 2026-10-09** (regime day 34 — FINAL READ)
Rules v60: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7560 | open $184 | net worth $7857 | realized $5844 | exposure 184/$3979 | drawdown 2.5%

**Last 24h:** 20 Kelly-regime copies opened (4 main-lane, 16 lane) | realized $246.01 | $229 booked
[KELLY] decisions in log: 541 (143 sized, 398 skipped). Top skip reasons: no edge: q=0.556 ≤ price=0.585 (20); no edge: q=0.381 ≤ price=0.410 (18); no edge: q=0.436 ≤ price=0.465 (16)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 51 | $81 | $100 | $3782 (50 res) | $100 open |
| 0.20-0.40 | 60 | $27 | $100 | $-8 (60 res) | $0 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 970 copies, realized $1929
**Target check:** mid/high-band main-lane copies 0/111 → ≈0 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 | Kelly-window main-lane realized $3774
Long-shot (<0.20) realized: baseline $465 → window $3782 (8.1x)
**Verdict fields (pre-registered §6):** concentration ✓/✗ above | mid-band ≈0 ✓/✗ above | drawdown 2.5% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

**λ̂ alignment check (Sep-1 pre-registered → Sep-15 refit → Oct-1 live):**
| band | Sep-1 λ̂ | Oct-1 λ̂ | window realized |
|---|---|---|---|
| <0.20 | −0.91 | −0.779 | +$3782 |
| 0.20–0.40 | −0.21 | −0.196 | −$8 |
| 0.40–0.60 | +0.03 | +0.074 | $0 (skipped) |
| 0.60–0.80 | +0.21 | +0.219 | $0 (skipped) |
| ≥0.80 | +0.37 | +0.291 | $0 (skipped) |

Sep-15 refit values for reference: <0.20 −0.789 · 0.20–0.40 −0.2042 · 0.40–0.60 +0.0341 · 0.60–0.80 +0.2142 · ≥0.80 +0.2906.
Sign alignment holds: the most-negative-λ̂ band realized the only profit; the mid band's λ̂ moved further positive (Sep-15 +0.034 → Oct-1 +0.074), so the zero-edge skip stayed calibration-consistent through the close. The §6 caveat risk (mid-band λ̂ turning negative and Kelly resuming sizing) did not materialize.

**Verdict:** concentration <0.40 ✓ (111/111 copies; mid/high bands 0) · mid-band ≈0 ✓ (zero-edge skip held all window) · long-shot share $465→$3782 = 8.1× vs pre-registered 3–6× (exceeds, favorable) · drawdown 2.5% vs 20% gate ✓ · baseline total realized $140 vs window main-lane $3774.
**Note:** the 0.20–0.40 band recovered from −$427 (Sep 19, pre-rail) to −$8 final — that is the v57-B rail (cap on 0.20–0.60), not Kelly.
**Recommendation:** KEEP Kelly (kellyEnabled=1); hold kellyFraction=0.5. Edge is concentrated in <0.20 and is capacity-sensitive — the live question is long-shot sizing/fat-tail, with the Oct-8-approved mid-price gate covering the 0.20–0.60 slice. No rule/sizing change made; each lever needs explicit user approval.
