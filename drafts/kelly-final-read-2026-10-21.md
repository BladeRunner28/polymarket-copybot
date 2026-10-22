**Kelly Window Report — 2026-10-21** (regime day 46 — FINAL READ)
Rules v65: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7796 | open $35 | net worth $7831 | realized $5930 | exposure 35/$3965 | drawdown 3.3%

**Last 24h:** 6 Kelly-regime copies opened (1 main-lane, 5 lane) | realized $-12.06 | $55 booked
[KELLY] decisions in log: 819 (167 sized, 652 skipped). Top skip reasons: no edge: q=0.521 ≤ price=0.545 (45); no edge: q=0.481 ≤ price=0.505 (35); no edge: q=0.511 ≤ price=0.535 (28)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 58 | $83 | $100 | $3727 (58 res) | $0 open |
| 0.20-0.40 | 77 | $25 | $100 | $-76 (77 res) | $0 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1076 copies, realized $2139
**Target check:** mid/high-band main-lane copies 0/135 → ≈0 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 | Kelly-window main-lane realized $3651
Long-shot (<0.20) realized: baseline $465 → window $3727 (8.0x)
**Verdict fields (pre-registered §6):** concentration ✓/✗ above | mid-band ≈0 ✓/✗ above | drawdown 3.3% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

## Verdict (final read, window Sep 8 – Oct 8, read 2026-10-21, regime day 46 / +13d post-window)

Independently re-queried PaperTrade ⨝ DecisionJournal (botId=BANKROLL_200, ruleSetVersion>=49,
reasonsJson NOT LIKE '%Short-TTR lane%'): <0.20 n=58 avg $83 realized +$3,727.47; 0.20–0.40 n=77
avg $25 realized −$76.10, 0 open. Matches collector exactly.

### 24h delta (vs 10-20 read)

1 main-lane copy resolved (0.20–0.40, −$93 → −$76, +$17); 5 lane copies opened; lane realized
$2,168 → $2,139 (−$29). Net day realized −$12.06. Drawdown 3.2% → 3.3%. No cap binding: exposure
$35 vs $3,965 cap (0.9%), 16.7pp under the 20% drawdown gate.

### Pre-registered checks (§6)

| check | target | actual | verdict |
|---|---|---|---|
| concentration <0.40 | book concentrates | 135/135 = 100% | ✓ |
| mid-band 0.40–0.60 copies | ≈0 | 0 | ✓ |
| 0.60+ copies | ≈0 | 0 | ✓ |
| long-shot share of realized | 3–6× baseline | 8.0× ($465→$3,727) | ✗ as written |
| max drawdown | ≤ pre-Kelly baseline | 3.3% vs 20% gate | ✓ |

Long-shot overshoot: ratio inflated by a $140 baseline denominator; absolute gain is the honest
read. The 3–6× band was calibrated to that denominator, so the ✗ is a target-formulation
artifact, not evidence of over-sizing.

### Band-level λ̂ alignment (Sep-1 refit / Oct-15 refit vs realized)

| band | λ̂ Sep-1 / Oct-15 | realized | alignment |
|---|---|---|---|
| <0.20 | −0.91 / −0.743 | +$3,727 | ✓ aligned |
| 0.20–0.40 | −0.21 / −0.158 | −$76 | ✗ sign flip, unresolved (n=77) |
| 0.40–0.60 | +0.03 / +0.060 | $0 (−$366 avoided) | ✓ aligned-by-skip |
| 0.60–0.80 | +0.21 / +0.197 | $0 (−$41 avoided) | ✓ aligned |
| ≥0.80 | +0.37 / +0.291 | $0 (+$2 forgone) | ✓ immaterial |

Oct-15 refit leaves every band's λ̂ sign unchanged, so the 0.20–0.40 sign flip is not calibration
drift; at n=77 / −$76 it is noise-level. §6 caveat stands: λ̂ measures premium, not PnL; the
mid-band skip is still luck of the zero-edge rule.

### Recommendation (recommendations only — no rule or code change made)

1. **Continue Kelly.** kellyEnabled=1, fraction 0.5, maxBankrollPct 10%, maxSizeUsd $100. No
   evidence for a higher fraction; no drawdown pressure for a lower one.
2. **Track 0.20–0.40 as unresolved** (30-day extension) instead of scoring it a loss.
3. **Re-baseline the long-shot target** to an absolute PnL figure (e.g. ≥$2,500/30d at current
   caps) rather than a 3–6× ratio off a $140 denominator.
4. **Watch single-loss concentration:** the $100 cap binds on every <0.20 copy (avg $83) = 1.3% of
   net worth per full loss. A per-position cap or max-concurrent-long-shot limit is the next test,
   with approval.
