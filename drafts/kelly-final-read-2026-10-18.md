**Kelly Window Report — 2026-10-18** (regime day 43 — FINAL READ)
Rules v62: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7915 | open $38 | net worth $7970 | realized $6053 | exposure 38/$4035 | drawdown 1.6%

**Last 24h:** 9 Kelly-regime copies opened (1 main-lane, 8 lane) | realized $445.07 | $182 booked
[KELLY] decisions in log: 647 (163 sized, 484 skipped). Top skip reasons: no edge: q=0.556 ≤ price=0.585 (20); no edge: q=0.381 ≤ price=0.410 (19); no edge: q=0.436 ≤ price=0.465 (16)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 57 | $82 | $100 | $3827 (57 res) | $0 open |
| 0.20-0.40 | 74 | $25 | $100 | $-67 (73 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1065 copies, realized $2152
**Target check:** mid/high-band main-lane copies 0/131 → ≈0 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 | Kelly-window main-lane realized $3761
Long-shot (<0.20) realized: baseline $465 → window $3827 (8.2x)
**Verdict fields (pre-registered §6):** concentration ✓/✗ above | mid-band ≈0 ✓/✗ above | drawdown 1.6% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

## Composed verdict — 2026-10-18 (regime day 43; pre-registered window ended Oct 8, this is a +10d re-read)

| check | pre-registered | actual | verdict |
|---|---|---|---|
| concentration | book in <0.40 | 131/131 copies (100%) | ✓ |
| mid/high band | ≈0 copies | 0 copies | ✓ |
| long-shot share | 3–6× baseline | 8.2× ($465→$3,827) | above band, favorable |
| drawdown | ≤20% gate | 1.6% | ✓ |

- Main-lane realized $3,761 on 131 copies (baseline $140 = 26.9×). Long-shot band = 101.8% of main-lane PnL; the 0.20–0.40 band is net negative.
- Per trade: <0.20 $67.14 vs baseline $6.04 (11.1×); 0.20–0.40 −$0.92 vs +$0.34 baseline — the one sign misalignment (λ̂ −0.21 predicted positive edge).
- Live λ̂ (2026-10-15 refit): −0.743 / −0.158 / +0.060 / +0.197 / +0.291. Mid-band still positive → 0-trade mid-band remains a zero-edge-rule artifact, not calibration sight. No new mid-band evidence.
- Capacity (§7 risk): edge held at $82 avg / $100 cap, so the predicted edge decay at larger size did not appear in-window.
- Caveats: +10d drift past window end; n=131 thin; size-cap-bound effect on a small sample.
- Recommendation (recs only, no change applied): **continue Kelly at fraction=0.5 / maxSizeUsd=$100**. If mid-band is to be tested, next probe is a shadow log of mid-band q-vs-p only (no sizing).
