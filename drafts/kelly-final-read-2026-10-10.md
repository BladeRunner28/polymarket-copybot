**Kelly Window Report — 2026-10-10** (regime day 35 — FINAL READ)
Rules v61: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7440 | open $172 | net worth $7774 | realized $5713 | exposure 172/$3937 | drawdown 3.7%

**Last 24h:** 28 Kelly-regime copies opened (1 main-lane, 27 lane) | realized $-131.57 | $199 booked
[KELLY] decisions in log: 544 (144 sized, 400 skipped). Top skip reasons: no edge: q=0.556 ≤ price=0.585 (20); no edge: q=0.381 ≤ price=0.410 (18); no edge: q=0.436 ≤ price=0.465 (16)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 52 | $81 | $100 | $3737 (51 res) | $100 open |
| 0.20-0.40 | 60 | $27 | $100 | $-8 (60 res) | $0 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 997 copies, realized $1843
**Target check:** mid/high-band main-lane copies 0/112 → ≈0 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 | Kelly-window main-lane realized $3729
Long-shot (<0.20) realized: baseline $465 → window $3737 (8.0x)
**Verdict fields (pre-registered §6):** concentration ✓/✗ above | mid-band ≈0 ✓/✗ above | drawdown 3.7% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

**§6 PRE-REGISTERED VERDICT (hermes, 2026-10-10)**

Sep-1 λ̂ table (design §6) vs realized band PnL, and λ̂ sign re-check against the
latest refit (`data/premium-calibration.json`, calibratedAt 2026-10-01):

| band | λ̂ Sep-1 | λ̂ Oct-1 | window realized | baseline realized | verdict |
|---|---|---|---|---|---|
| <0.20 | −0.91 | −0.78 | $3737 | $465 | aligned (size) |
| 0.20–0.40 | −0.21 | −0.20 | −$8 | $80 | aligned sign; band flat/neg this window |
| 0.40–0.60 | +0.03 | +0.07 | $0 (0 copies) | −$366 | aligned-by-skip; no sign flip |
| 0.60–0.80 | +0.21 | +0.22 | $0 (0 copies) | −$41 | aligned (skip) |
| ≥0.80 | +0.37 | +0.29 | $0 (0 copies) | $2 | mild misalignment, immaterial |

1. **Concentration <0.40 → ✓** (112/112 main-lane copies; mid/high bands 0/112).
2. **Mid-band ≈0 → ✓** (0 copies admitted — zero-edge skip rule holding).
3. **Long-shot share of realized → 100% of window main-lane PnL; $3737 vs $465
   baseline = 8.0×** (pre-registered band was 3–6× → over the top of band, i.e.
   more concentrated than expected, not fewer).
4. **Drawdown → 3.7% vs 20% gate ✓** (no ⚠ flag raised; exposure $172/$3937 =
   4.4% of cap, not binding).
5. **λ̂ alignment caveat → satisfied:** no band changed sign between the Sep-1
   pre-registered table and the Oct-1 refit; the mid-band skip is still
   justified by λ̂>0, not merely by the zero-edge rule.
6. Note: live rule v61 has `kellyMaxSizeUsd=$100` (design §5 default was $60);
   the sized 0.20–0.40 band realized −$8 vs +$80 baseline (n=60, small) — a
   candidate re-check for the next window.

**Recommendation (recommendations only):** CONTINUE Kelly (keep kellyEnabled=1).
Primary targets met; long-shot edge survived at $100/copy (design capacity
question answered affirmatively). Two proposals for the user to approve or
reject: (a) revert `kellyMaxSizeUsd` 100→60 (design value) for the next window
to bound the sized-band variance; (b) keep the short-TTR lane Kelly-exempt and
review after the next 30-day window. No rule or code change made.
