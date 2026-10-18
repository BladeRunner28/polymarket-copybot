# Kelly Window — FINAL READ (pre-registered §6 verdict)

**Date:** 2026-10-17 · regime day 42 · window Sep 8 – Oct 8 (read 9d overdue)
**Rules v62:** kellyEnabled=1, fraction=0.5, maxBankrollPct=10%, maxSizeUsd=$100, minBet=$2, minEdge=2%

## State
cash $7,450 · open $58 · net worth $7,514 · realized $5,608 · exposure 58/$3,807 · drawdown 7.2%

## Window — main-lane Kelly (journal v≥49)
| band | n | avg size | realized |
|---|---|---|---|
| <0.20 | 56 | $82 | +$3,315 |
| 0.20–0.40 | 74 | $25 | −$67 |
| 0.40–0.60 | 0 | — | $0 |
| 0.60–0.80 | 0 | — | $0 |
| ≥0.80 | 0 | — | $0 |

Lane (short-TTR, Kelly-exempt): 1,057 copies, +$2,219.
Kelly decisions: 627 (162 sized / 465 skipped).

## Verdict vs design §6 pre-registration

| criterion | pre-registered | actual | verdict |
|---|---|---|---|
| Concentration <0.40 | book concentrates | 130/130 copies | ✓ |
| Mid/high band ≈0 | ≈0 trades | 0 copies (0/130) | ✓ |
| Long-shot share | 3–6× baseline | 7.1× | exceeds band |
| Drawdown | ≤ pre-Kelly baseline | 7.2% vs 20% gate | ✓ |

Baseline (pre-Kelly, all resolved): total +$140. Window main-lane: +$3,248 = 23.2×.

**λ̂ alignment check (caveat in §6):** Oct-15 refit λ̂ = −0.743 / −0.158 / +0.060 / +0.197 / +0.291
(top→bottom band). Signs unchanged vs Sep-1 (−0.91/−0.21/+0.03/+0.21/+0.37): mid-band λ̂ is
still **positive**, so the 0-trade mid-band result remains a product of the zero-edge rule,
**not** of calibration seeing the −EV region. No new evidence either way on mid-band.

## Honest caveats
1. Window table runs to today — includes ~9 days past the pre-registered Oct 8 end.
2. n=130 main-lane copies is thin; 0.20–0.40 is slightly negative (−$0.91/trade vs +$0.34 baseline).
3. 102% of main-lane PnL comes from one band (<0.20); avg size $82 is cap-bound, so the
   realized edge is a size effect on a small sample, not yet a durable rate.

## Recommendation (recommendations only)
**Continue Kelly at fraction=0.5 / maxSizeUsd=$100 — no RuleSet change proposed.**
Falsifiable target met (concentration + starvation held, DD 7.2%). The one unresolved
question is mid-band: 0 copies means no live test of the 0.40–0.60 region. Next probe, if
wanted, is a shadow log of mid-band q-vs-p only (no sizing) through the next refit cycle.
