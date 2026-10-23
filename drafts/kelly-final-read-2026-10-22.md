**Kelly Window Report — 2026-10-22** (regime day 47 — FINAL READ)
Rules v65: kellyEnabled=1 fraction=0.5 maxBankrollPct=10% maxSizeUsd=$100 minBet=$2 minEdge=2%

**State:** cash $7852 | open $68 | net worth $7934 | realized $6020 | exposure 68/$4017 | drawdown 2.0%

**Last 24h:** 8 copies opened (1 main-lane, 7 lane) | $78 booked | realized $-9.97 on the 1 of them already settled
**Settled in the last 24h (any open date):** realized $89.30 across 5 trades
[KELLY] decisions in log: 912 (168 sized, 744 skipped). Top skip reasons: no edge: q=0.392 ≤ price=0.415 (49); no edge: q=0.521 ≤ price=0.545 (45); no edge: q=0.572 ≤ price=0.595 (43)

**Window (since v49, main-lane Kelly):**
| band | n | avg size | max | realized | open |
|---|---|---|---|---|---|
| <0.20 | 58 | $83 | $100 | $3727 (58 res) | $0 open |
| 0.20-0.40 | 78 | $24 | $100 | $-76 (77 res) | $18 open |
| 0.40-0.60 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| 0.60-0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |
| >=0.80 | 0 | $0 | $0 | $0 (0 res) | $0 open |

**Lane (short-TTR, Kelly-exempt):** 1083 copies, realized $2228
**Target check (mid/high-band ≈0):** 0/136 ✓ (zero-edge skips holding)


**FINAL — pre-Kelly baseline (all resolved, journal v<49):**
| band | n | realized |
|---|---|---|
| <0.20 | 77 | $465 |
| 0.20-0.40 | 236 | $80 |
| 0.40-0.60 | 585 | $-366 |
| 0.60-0.80 | 231 | $-41 |
| >=0.80 | 161 | $2 |
Baseline total realized $140 on 1290 pre-Kelly copies | Kelly-window main-lane realized $3651 on 136 copies — raw totals, different periods and sample sizes (not a like-for-like rate)
<0.20 long-shot vs the ABSOLUTE target (re-baselined 2026-10-21, kelly rec 3), trailing 30d by SETTLE date: realized $2167 on n=22 vs $2,500 → ✗ short $333 · all-time in regime $3727 on n=58 · same 30d by OPEN date (cohort opened in-window, 19/19 settled): $624 — different cohort, NOT the 30-day PnL rate
**Verdict fields (pre-registered §6):** concentration 136/136 copies in <0.40 ✓ (mid/high 0) | mid-band ≈0 0/136 ✓ (zero-edge skips holding) | drawdown 2.0% vs 20% gate ✓
CAVEAT (design §6): λ̂ is a premium measure, not PnL — check band λ̂ vs realized alignment at the Sep 15 refit; mid-band skip is by zero-edge rule, not calibration sight.

---

**Verdict vs §6 pre-registered table (sign alignment vs Sep-1 λ̂):**
| band | λ̂ | realized | read |
|---|---|---|---|
| <0.20 | −0.91 | +$3,727 | aligned (cap-bound sizing) |
| 0.20–0.40 | −0.21 | −$76 | sign-aligned, UNRESOLVED → 2026-11-20 |
| 0.40+ | ≥+0.03 | $0 (0 copies) | aligned by skip |

**Targets:** long-shot ABSOLUTE ≥$2,500/30d → $2,167 on n=22 (trailing 30d, settle date) ✗ short $333 (87%).
Structural: concentration <0.40 ✓ · mid-band ≈0 ✓ · drawdown 2.0% vs 20% ✓ · exposure 68/$4,017 not binding.
0.20–0.40 band is UNRESOLVED (not a loss, not evidence) through 2026-11-20 — n=77 sign flip is noise-level.

**Recommendation (proposal only, no rule change made):**
1. Continue Kelly (kellyEnabled=1, v65 unchanged) — do not revert: structural gates all pass.
2. Hypothesis for the $333 shortfall: long-shot is cap-bound (avg $83, max $100 = cap), so size cap — not edge — may bind. Option: 30d A/B raising maxSizeUsd $100→$150 (or maxBankrollPct 10→15%), accepting higher variance.
3. Alternative: hold v65 flat to 2026-11-20 so 0.20–0.40 resolves, then re-read both bands together.
