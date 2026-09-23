# Wallet category concentration vs our copy P&L — measured, null (2026-09-23)

**Card:** `polycopy-concentration-feature-test`. **Status: closed on a NULL.** No scoring input, no
filter, no catalog rule — and on this evidence concentration must not become one.

**What shipped:** `scripts/wallet-concentration-test.py` — read-only, one command re-runs everything
below, stdlib-only Python 3, writes nothing. Nothing was gated and no rule changed.

---

## 1. The claim being tested

Polycopy's Q1 2026 report (marketing-grade, no dataset — a hypothesis) claims category concentration is
the strongest predictor of trader performance: wallets with **80%+ of volume in one category averaged a
58.2% win rate vs 51.1% for 4+ categories** (+7.1pp), and NBA Over/Under specialists beat the category
average by 18pp. We store `bestCategory` and `categoryFitScore` but have **never measured concentration
itself**, and the C-200 category blacklist (lol/cs2) is a hard filter rather than a graded feature. So:
does a source wallet's concentration predict how *our* copy of it does?

## 2. How concentration is measured here (and why two windows)

**The stored category field is unusable.** `ObservedTrade.marketCategory` is a bare slug token —
`highest` (71k rows), `fifwc`, `which`, `what`, `elon` — not a category. This measurement therefore
classifies each market itself: exact slug **series** tokens first (lol, cs2, dota2, mlb, epl, fifwc,
atp/wta, ufc, btc, …), then ordered question-text rules (crypto, weather, econ, politics, culture,
tech). Coverage is printed before any result so the residual is auditable: the largest fine categories
by observed volume are football-intl 22.7%, **other 10.9%**, esports-lol 10.2%, baseball-mlb 9.9%,
esports-cs2 9.8%, esports-dota 9.0%, tennis 7.0%, politics-elections 3.6%.

**The classifier is validated against polycopy's own taxonomy.** Their `categoryStrengthsJson` (a
per-wallet `{category: {trades, winRate, pnl}}` map from their leaderboard scan — a different data
source from our observed trades) yields an independent top-category share; over **353 wallets** the two
measures agree at **pearson +0.548 / spearman +0.547**. So this is not a classifier artifact.

**Two windows, because the full-history one is confounded.** Concentration over a wallet's whole
observed history is driven by *how many of its trades we saw*: more trades → more categories touched →
lower top share (measured spearman **−0.721** C-200 / **−0.566** STANDARD). The primary measure is
therefore the same statistic over the wallet's **most recent 20 observed trades** (equal-n), where that
confound drops to **−0.103 / −0.120**. Both are reported; the full-history one is kept as the
"specialist = thin record" illustration.

## 3. Population

| | C-200 | STANDARD |
|---|---|---|
| settled legs with a concentration feature | 1,958 from **99 wallets** | 8,669 from **176 wallets** |
| cost / realized / edge | $14,824.27 / +$2,426.13 / +16.4% | $99,426.80 / +$8,833.69 / +8.9% |
| legs per wallet (median) | 7 | 15 |

Sample: 353 of 410 observed wallets have ≥10 observed trades (a 0/1 concentration from 2 trades is noise
not strategy); 3,201 wallet profiles exist in total. Legs are the settled book (`status closed|resolved`,
`isDemo=0`, `closedAt ?? resolvedAt`), split by lane. C-200's edge % carries the sidecar's 2¢ maker-fill
assumption (see `polycopy-edge-cost-pair`) — it inflates both sides equally, so it does not affect any
contrast below.

## 4. Results

### 4.1 Deciles — non-monotone in both lanes and both windows

C-200, last-20-trade window (wallet-level feature → leg-level outcome):

| decile | share range | wallets | legs | realized | mean leg | median leg | win | edge % |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.24–0.45 | 9 | 180 | −$24.28 | −$0.13 | +$0.11 | 56% | −1.6 |
| 2 | 0.47–0.55 | 9 | 67 | +$72.34 | +$1.08 | +$0.05 | 54% | +18.2 |
| 3 | 0.55–0.62 | 9 | 156 | +$85.83 | +$0.55 | +$1.03 | 56% | +10.4 |
| 4 | 0.63–0.69 | 9 | 479 | +$787.01 | +$1.64 | −$0.20 | 47% | +18.4 |
| 5 | 0.69–0.74 | 9 | 187 | −$112.27 | −$0.60 | $0.00 | 50% | −7.3 |
| 6 | 0.78–0.85 | 9 | 72 | −$84.90 | −$1.18 | −$4.58 | 39% | −20.6 |
| 7 | 0.85–0.94 | 9 | 131 | +$142.11 | +$1.08 | +$1.20 | 52% | +19.0 |
| 8 | 0.94–1.00 | 9 | 162 | +$726.28 | +$4.48 | +$0.37 | 61% | +71.9 |
| 9 | 1.00 | 9 | 354 | +$1,242.07 | +$3.51 | −$0.48 | 44% | +44.1 |
| 10 | 1.00 | 18 | 170 | −$408.06 | −$2.40 | −$1.25 | 46% | −31.3 |

**No dose-response** (mean-leg PnL is not monotone). The full-history window is equally non-monotone
(+93.4% edge in D2, −25.0% in D5, +64.0% in D7, −35.9% in D8), and STANDARD shows the same pattern on
both windows (last-20: −11.9% in D2, +31.4% in D6, −17.2% in D7, +22.3% in D8). Note the top deciles
collapse to share = 1.00 (a wallet that only ever traded one category), so deciles 9–10 are split by
tie-break order, not by real distance.

### 4.2 The vendor's own ≥80% split — the answer depends on which window you pick

| lane | window | specialist ≥80% | generalist <80% | clustered p (mean / median) |
|---|---|---|---|---|
| C-200 | last 20 trades | 51 wallets, 849 legs, mean +$1.98, edge **+27.8%** | 48 wallets, 1,109 legs, mean +$0.67, edge +8.5% | **0.535 / 0.791** |
| C-200 | full history | 25 wallets, 222 legs, mean −$0.01, edge **−0.1%** | 74 wallets, 1,736 legs, mean +$1.40, edge +17.9% | **0.603 / 0.782** |
| STANDARD | last 20 trades | 104 wallets, 4,595 legs, mean +$1.40, edge **+12.1%** | 72 wallets, 4,074 legs, mean +$0.58, edge +5.2% | **0.493 / 0.377** |
| STANDARD | full history | 67 wallets, 1,899 legs, mean +$0.78, edge **+6.6%** | 109 wallets, 6,770 legs, mean +$1.09, edge +9.5% | **0.819 / 0.704** |

Two things kill the claim: the **sign flips** between the two windows on both lanes (C-200: +27.8% →
−0.1%; STANDARD: +12.1% → +6.6%), and the **win-leg shares are identical** to within a point
(C-200 48.5% vs 50.4%; STANDARD 64.0% vs 63.5%) while the edges differ — i.e. the edge gap lives
entirely in the tails, not in hit rate. Wallet-clustered CIs on the mean leg all span zero
(C-200 specialist [−$1.86, +$4.65], generalist [−$0.73, +$1.59]).

**Estimator note (applied, not just caveated):** the two-group tests permute the **group label at the
wallet level** — the pooled wallets are re-split on every draw. The first version of this instrument
shuffled legs instead, which treats 1,400 legs as 1,400 independent draws and returned **p = 0.006 /
0.000 for the STANDARD contrast above**; that p dies (0.493 / 0.377) once legs are clustered inside
their wallet. This is the single most important methodological point in this write-up: the leg-level
form manufactures significance for a feature that has none.

### 4.3 Price control — no band carries a consistent effect

Specialist vs generalist *inside* each entry-price quintile (clustered p):

| lane | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|---|---|---|---|---|
| C-200 diff | +$7.48 (p=0.447) | −$2.97 (**p=0.026**) | −$0.64 (p=0.544) | +$0.65 (p=0.452) | −$0.01 (p=0.984) |
| STANDARD diff | −$0.90 (p=0.815) | −$2.92 (p=0.148) | +$6.79 (p=0.101) | +$0.10 (p=0.896) | −$0.89 (p=0.371) |

Ten band tests, one at p = 0.026, sign inconsistent across bands, and that one is *negative* — exactly
the false-positive rate 10 tests produce at α = 0.05.

### 4.4 Rankers vs "leg won" — concentration carries no leg-level information

AUC 95% CI via Hanley–McNeil at A = 0.5; the sample's MDE is **±0.026 (C-200)** and **±0.013 (STANDARD)**.

| feature | C-200 AUC | STANDARD AUC |
|---|---|---|
| **conc fine, last-20 window** | **0.474 [0.448, 0.500]** | **0.482 [0.470, 0.495]** |
| conc fine, full history | 0.476 [0.450, 0.502] | 0.418 [0.405, 0.431] |
| conc coarse, last-20 window | 0.474 [0.448, 0.500] | 0.466 [0.454, 0.479] |
| generalist (1 − conc) | 0.526 [0.500, 0.552] | 0.518 [0.505, 0.530] |
| entryPrice (price baseline) | **0.653 [0.627, 0.678]** | **0.758 [0.745, 0.770]** |
| globalScore | 0.497 | 0.496 |
| roi30d | 0.496 | 0.426 |
| consistencyScore | 0.494 | 0.432 |
| copyabilityScore | 0.494 | **0.591 [0.578, 0.603]** |
| winRate30d (scan) | 0.480 | 0.462 |
| n observed trades (ours) | 0.504 | **0.631 [0.618, 0.643]** |

The concentration feature is **below** 0.50 on both lanes (mildly anti-predictive: more concentrated →
slightly *less* likely to win), and its best case — "prefer generalists" — is 0.526/0.518, both barely at
the edge of the MDE band. (AUC on "leg won" is not EV: the book profits at ~50% win rate because winners
and losers are not the same size. But it is the right first filter for a *ranker*, and it says
concentration is not one.)

## 5. Verdict

**Null.** Concentration — coarse or fine, by volume or by count, full-history or equal-n window, as
deciles or as the vendor's own ≥80% split — has **no measured relationship to our realized PnL, edge,
win rate or per-leg outcome**, and its most striking apparent effect (+27.8% edge for C-200 specialists)
reverses sign on a different window of the same data. None of this is a classifier artifact: the
classifier agrees with polycopy's own category map at r = +0.55 over 353 wallets.

**What this does not exclude:** the C-200 lane only supplies 99 wallets with ≥10 observed trades, so the
C-200 tests are low-powered (the AUC MDE there is ±0.026, but the ≥80% split rests on 51 vs 48 wallets);
the equal-n window averages over the last 20 trades regardless of when they happened; and our observed
history is our scanner's window (from 2026-07-13), not the wallet's full record. A moderate effect that
only shows up on wallets we have barely observed is not excluded — but nothing here justifies acting.

**What it does earn** (carded separately, none of it a rule):

1. **The transferable finding is about the scores, not the concentration.** At leg grain, on both lanes,
   the wallet scores we actually select on are ~coin flips (`globalScore` 0.497/0.496, `roi30d`
   0.496/0.426, `consistencyScore` 0.494/0.432), while the market's own **entry price** is 0.653/0.758.
   Two wallet-level features do clear their MDE: `copyabilityScore` (STANDARD 0.591) and our own
   observed-trade count (STANDARD 0.631). Whether our selection stack should say more about leg outcome
   than it does is a real question — it deserves its own measurement card, with the price baseline as
   the bar.
2. `ObservedTrade.marketCategory` is a slug token, not a category. Anything that wants a category
   dimension (their claim, our blacklist, category-fit scoring) should use a real classifier or fix the
   field at the write path.

## 6. Reproduce

```bash
python3 scripts/wallet-concentration-test.py      # the whole measurement above; writes nothing
```
stdlib-only Python 3, reads `prisma/dev.db` (read-only URI). Permutation draws are budgeted by pool
size (2,000–20,000, printed per section) and **permute wallet labels**, never legs; the bootstrap
resamples wallets; `prisma/dev.db` datetimes are Unix-ms. Deterministic (`random.seed(20260923)`).
