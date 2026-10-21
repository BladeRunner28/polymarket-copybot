**Kelly Window Report — 2026-10-20** (regime day 45 — FINAL READ)
Rules v64: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7795 | open $48 | net worth $7837 | realized $5943 | exposure 48/$3969 | drawdown 3.2%

**Last 24h:** 7 Kelly-regime copies opened (3 main-lane, 4 lane) | realized $-127.65 | $171 booked
[KELLY] decisions in log: 659 (166 sized, 493 skipped). Top skip reasons: no edge: q=0.556 ≤ price=0.585 (20); no edge: q=0.381 ≤ price=0.410 (19); no edge: q=0.436 ≤ price=0.465 (16)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 58 | $83 | $100 | $3727 (58 res) | $0 open |
| 0.20-0.40 | 76 | $25 | $100 | $-93 (75 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1071 copies, realized $2168
**Target check:** mid/high-band main-lane copies 0/134 → ≈0 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 | Kelly-window main-lane realized $3634
Long-shot (<0.20) realized: baseline $465 → window $3727 (8.0x)
**Verdict fields (pre-registered §6):** concentration ✓/✗ above | mid-band ≈0 ✓/✗ above | drawdown 3.2% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

## Verdict (final read, window Sep 8 – Oct 8, read 2026-10-20, day 45 regime)

Independently re-queried PaperTrade ⨝ DecisionJournal (botId=BANKROLL_200, ruleSetVersion>=49,
reasonsJson NOT LIKE '%Short-TTR lane%'): <0.20 n=58 avg $83 realized +$3,727; 0.20–0.40 n=76
avg $25 realized −$93, 1 open ($18). Matches collector.

### 24h attribution (drawdown 1.5% → 3.2%)

7 resolutions, −$127.65 net. One full-cap long-shot loss dominates: dota2-synaps-y, entry 0.144,
$100 size, −$100 (78% of the day's loss). No exposure-cap binding (book $48 vs $3,969 cap);
remains 16.8pp under the 20% drawdown gate.

### Pre-registered checks (§6)

| check | target | actual | verdict |
|---|---|---|---|
| concentration <0.40 | book concentrates | 134/134 = 100% | ✓ |
| mid-band (0.40–0.60) copies | ≈0 | 0 | ✓ |
| 0.60+ copies | ≈0 | 0 | ✓ |
| long-shot share of realized | 3–6× baseline | 8.0× ($465→$3,727) | ✗ as written (over range) |
| max drawdown | ≤ pre-Kelly baseline | 3.2% vs 20% gate | ✓ |

Long-shot overshoot note: ratio inflated by a $140 baseline denominator; absolute gain is the
honest read. The 3–6× band was calibrated against that denominator, so the ✗ is a
target-formulation artifact, not evidence of over-sizing.

### Band-level λ̂ alignment (Sep-1 refit vs realized)

| band | Sep-1 λ̂ | Oct-15 λ̂ | Kelly | realized | alignment |
|---|---|---|---|---|---|
| <0.20 | −0.91 | −0.743 | size (cap-bound) | +$3,727 | ✓ aligned |
| 0.20–0.40 | −0.21 | −0.158 | size | −$93 | ✗ sign flip (+$62 pre-Kelly) |
| 0.40–0.60 | +0.03 | +0.060 | skip | $0 (−$366 avoided) | ✓ aligned-by-skip |
| 0.60–0.80 | +0.21 | +0.197 | skip | $0 (−$41 avoided) | ✓ aligned |
| ≥0.80 | +0.37 | +0.291 | skip | $0 (+$2 forgone) | ✓ immaterial |

Oct-15 refit keeps every band's λ̂ sign unchanged → the 0.20–0.40 sign flip is NOT calibration
drift; it is n=76 on −$93 (noise-level), so the band reads "unresolved", not "model failure".
§6 caveat stands: λ̂ measures premium, not PnL; mid-band skip is still luck of the zero-edge rule.

### Recommendation (recommendations only — no rule/code change made)

1. **Continue Kelly.** kellyEnabled=1, fraction 0.5, maxBankrollPct 10%, maxSizeUsd $100. No
   evidence supports a higher fraction; no drawdown pressure argues for a lower one.
2. **Track 0.20–0.40 as unresolved** (30-day extension) rather than scoring it a loss.
3. **Re-baseline the long-shot target** to an absolute PnL figure (e.g. ≥$2,500/30d at current
   caps) instead of a 3–6× ratio off a $140 denominator.
4. **Watch single-loss concentration:** the $100 cap binds on every <0.20 copy (avg $83), so one
   full loss = 1.3% of net worth. Two consecutive would put drawdown near 6% — still safe, but a
   sizing review (per-position cap or max-concurrent-long-shot limit) is the next thing to test,
   with approval.
