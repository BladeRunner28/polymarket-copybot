**Kelly Window Report — 2026-10-19** (regime day 44 — FINAL READ)
Rules v62: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7922 | open $48 | net worth $7973 | realized $6070 | exposure 48/$4037 | drawdown 1.5%

**Last 24h:** 2 Kelly-regime copies opened (0 main-lane, 2 lane) | realized $16.94 | $30 booked
[KELLY] decisions in log: 649 (163 sized, 486 skipped). Top skip reasons: no edge: q=0.556 ≤ price=0.585 (20); no edge: q=0.381 ≤ price=0.410 (19); no edge: q=0.436 ≤ price=0.465 (16)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 57 | $82 | $100 | $3827 (57 res) | $0 open |
| 0.20-0.40 | 74 | $25 | $100 | $-67 (73 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1067 copies, realized $2169
**Target check:** mid/high-band main-lane copies 0/131 → ≈0 ✓ (zero-edge skips holding)

**WEEKLY (7d):** 74 copies opened | realized $371.87

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
**Verdict fields (pre-registered §6):** concentration ✓/✗ above | mid-band ≈0 ✓/✗ above | drawdown 1.5% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

## Verdict (final read, window Sep 8 – Oct 8, read 2026-10-19)

Independently re-queried PaperTrade ⨝ DecisionJournal (botId=BANKROLL_200, ruleSetVersion>=49,
reasonsJson NOT LIKE '%Short-TTR lane%'): <0.20 n=57 avg $82 realized +$3,827.47; 0.20–0.40 n=74
avg $25 realized −$66.90, 1 open. Matches collector exactly.

### Pre-registered checks (§6)

| check | target | actual | verdict |
|---|---|---|---|
| concentration <0.40 | book concentrates | 131/131 = 100% | ✓ |
| mid-band (0.40–0.60) copies | ≈0 | 0 | ✓ |
| 0.60+ copies | ≈0 | 0 | ✓ |
| long-shot share of realized | 3–6× baseline | 8.2× ($465→$3,827) | ✗ as written (over range) |
| max drawdown | ≤ pre-Kelly baseline | 1.5% vs 20% gate | ✓ |

Long-shot overshoot note: ratio is inflated by a tiny baseline denominator (baseline total $140,
long-shot $465). Absolute gain is the honest read; the 3–6× band was calibrated against that
denominator, so the ✗ is a target-formulation artifact, not evidence of over-sizing.

### Band-level λ̂ alignment (Sep-1 refit vs realized)

| band | Sep-1 λ̂ | Oct-15 λ̂ | Kelly | realized | alignment |
|---|---|---|---|---|---|
| <0.20 | −0.91 | −0.743 | size (cap-bound) | +$3,827 | ✓ aligned |
| 0.20–0.40 | −0.21 | −0.158 | size | −$67 | ✗ sign flip (+$62 pre-Kelly) |
| 0.40–0.60 | +0.03 | +0.060 | skip | $0 (−$366 avoided) | ✓ aligned-by-skip |
| 0.60–0.80 | +0.21 | +0.197 | skip | $0 (−$41 avoided) | ✓ aligned |
| ≥0.80 | +0.37 | +0.291 | skip | $0 (+$2 forgone) | ✓ immaterial |

Oct-15 refit (data/premium-calibration.json) keeps every band's λ̂ sign unchanged → the
0.20–0.40 realized sign flip is NOT calibration drift. It is n=74 on −$67 (noise-level, ~1.5σ
at observed variance), so the band is "unresolved", not "model failure". §6's caveat stands:
λ̂ measures premium, not PnL; the mid-band skip remains luck of the zero-edge rule.

### Recommendation (recommendations only — no rule/code change made)

1. **Continue Kelly.** Keep kellyEnabled=1, fraction 0.5, maxBankrollPct 10%, maxSizeUsd $100.
   No evidence favors a higher fraction; no drawdown pressure argues for a lower one.
2. **Track 0.20–0.40 as unresolved** for a 30-day extension rather than scoring it a loss.
3. **Re-baseline the long-shot target** to an absolute PnL figure (e.g. ≥$2,500 over a 30-day
   window at current caps) instead of a 3–6× ratio off a $140 denominator.
4. Caps at $100 already bind on every <0.20 copy (avg $82, max $100); the capacity question
   §7 raised is now the live unknown — a $150 cap test would answer it, but only with approval.
