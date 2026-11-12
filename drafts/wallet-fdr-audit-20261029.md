# Wallet selection vs BH-FDR — is any tracked wallet distinguishable from the screen?

Card: `crowdintel-wallet-fdr-audit` (approved 2026-10-21, Lane B measurement). Instrument:
`scripts/wallet-fdr-audit.py`. Re-run: `python3 scripts/wallet-fdr-audit.py` (offline from cache);
`--fetch N` widens settlement truth keyless. Machine output: `data/wallet-fdr-audit.json`.

## The key insight

Zero of the 25 tracked wallets has an edge that survives the correction for the 1,136 wallets we
screen. The best single track wallet is at q = 0.101 — one thousandth of a point away from the bar
and, at n_eff 896 clusters, a coin-flip away from the 38 population wallets that clear it. **But the
tracked SET is not noise:** pooled across its 2,367 markets it beats its own entry bands by
+2.59pp (t +2.61, p = 0.0046), and it beats n_eff-matched non-tracked wallets by +4.44pp vs +0.19pp
(p = 0.030). The screen is picking something real and small; it cannot name which member of the set
is real. That distinction is what the decision rule had to resolve, and per the rule it resolves to
"propose", not "drop".

## Population and what binds it

| item | measured |
| --- | --- |
| first-print bets joined to venue settlement | 162,310 over 1,345 wallets |
| settled markets in truth cache | 8,619 of 299,502 conditionIds seen (2.88%) |
| truth cache growth this run | 4,005 → 9,851 markets (5,855 fetched, 145 failed) |
| wallets screened in WalletProfile | 3,748 (track 25, watch 3,495, ignore 228) |
| BH family actually tested | 1,136 wallets (n_eff ≥ 3 clusters, finite t) |

Bets are one per (wallet, conditionId, outcome) — first print only — priced at `detectedPrice`,
the same rule as profit-recs #3, because per-print weighting was shown on 10-27 to reverse the
sign. Edge is in probability points, so a $1 and a $10,000 wallet count the same.

Note on the old cache: the shared 4,005-market cache was built from markets the *paper book*
touched, and it read the 0.00-0.20 band at +9.76pp. On the expanded, wallet-driven sample that band
is **+2.39pp**. Any band thesis priced off the old cache has ~7pp of selection in it.

## Band baseline the excess is measured against (settle − price, whole population)

| band | n | mean edge | win rate |
| --- | --- | --- | --- |
| 0.00-0.20 | 18,977 | +2.39pp | 11.0% |
| 0.20-0.40 | 25,369 | +4.07pp | 34.7% |
| 0.40-0.60 | 50,456 | −0.29pp | 49.6% |
| 0.60-0.80 | 33,127 | −2.21pp | 66.7% |
| 0.80-1.00 | 34,381 | −2.09pp | 90.0% |

A wallet's excess is its edge minus the band mean of the same band, computed with that wallet left
out, so "it bought a well-priced band" earns nothing.

## BH-FDR across the screen (one-sided for skill, family = 1,136)

| bar | positive-excess wallets | share of tested |
| --- | --- | --- |
| q ≤ 0.05 | 22 | 1.9% |
| q ≤ 0.10 | 38 | 3.3% |
| q ≤ 0.20 | 48 | 4.2% |

A thin tail on a mostly-null population, which is what an efficient market plus a 1,136-way
multiple-testing correction should produce. Instrument check printed every run: q < p violations 0;
8 zero-variance cluster sets excluded as DEGENERATE rather than scored as p = 0 (that bug is what
the first draft of this instrument hit — it silently reported q = 0.0000 for hundreds of wallets).

## The current track set against the rule (q > 0.10 OR n_eff < 8 → flagged)

| outcome | wallets |
| --- | --- |
| q > 0.10 | 20 |
| n_eff < 8 (3, 7, 7 clusters) | 3 |
| no settled bet in truth cache | 2 |
| q ≤ 0.10 | **0** |
| **flagged share** | **25/25 = 100%** (bar: ≥ 30%) |

Closest to clearing, for the record: `0xf5a3504ad3` q 0.1009 (+4.54pp, n_eff 896);
`0x9c56304c88` q 0.1065 (+18.26pp, n_eff 55); `0x1f08255a13` q 0.1689 (+6.78pp, n_eff 319);
`0x6d98d93b9f` q 0.1719 (+13.24pp, n_eff 76). All four are the wrong side of a bar that a 1,136-way
correction sets, and three of the four are positive — the tracker is not picking losers, it is
picking people whose result cannot be separated from the population.

## One instrument with profit-recs #3 (the guard the card puts on this)

| reading | population | rho | n |
| --- | --- | --- | --- |
| **reproduction check** (same code, shared 4,005-market cache, raw edge) | prior instrument | **−0.100** | **27** |
| **THE number this card reports** (band-excess, expanded truth) | 9,851-market cache | **+0.084** | **45** |
| same population, raw edge (for the record, not a second verdict) | 9,851-market cache | +0.016 | 45 |

The first line reproduces the 10-29 review exactly (−0.100 on n=27), so the code is the same
instrument and the second line is that instrument on more truth, not a competing number. The
refutation branch needed rho ≥ +0.30 on ≥30 overlapping wallets; +0.084 on 45 is not it.

## Reality checks

- **Nobody is individually significant, yet the set is.** Pooled cohort: +2.59pp over bands, t +2.61,
  p = 0.0046 across 2,367 markets. If a hard q ≤ 0.10 gate were applied today, the track set would be
  **empty** — the gate is stricter than the evidence about the cohort, not stricter than the noise.
- **Truth coverage is 2.88% and not random.** Markets were fetched in order of how many distinct
  wallets printed them, so the sample over-represents popular markets; markets that never settled
  contribute nothing, which is a survivorship on market choice that no wallet-level correction
  reaches.
- **Clusters are markets, not events.** A 3-way event contributes 3 clusters; the coarser
  marketId grouping (`n_eff_event`, printed for every wallet) is never larger and often smaller.
- **Contamination from `label-integrity-wallet-win-filter`: none reaching this statistic.** That
  card's `won` label was measured on 10-29 to feed no scoring arm (scoreWallet takes its win-rate
  terms from `pnl > 0`), and this instrument reads neither `copyScore` nor `won` — it joins raw
  prints to the venue's settlement. The only channel would be the membership of the `track` set,
  which is the thing under test.

## Verdict (the card's rule, applied literally)

**PROPOSE a q-gated shadow ranking — Lane A, recommendation only, shadow-first.** 100% of tracked
wallets are flagged against a 30% bar, so the rule fires on the propose branch; the refutation branch
(rho ≥ +0.30) does not.

What that proposal should contain, given the two readings above (the operator decides, not this
card):

1. **Hard-gate arm:** rank by q, admit only q ≤ 0.10 with n_eff ≥ 8. Measured today this admits
   38 population wallets and **0** of the current 25, so it is a clean test of whether the screen's
   value is in its members or in its breadth.
2. **Shrunk-rank arm:** rank by band-excess shrunk toward the band prior by n_eff (empirical Bayes),
   which keeps the breadth that the pooled cohort read says is worth +2.59pp. Run both in shadow
   against the current track set, same window, same bands; the q-gate ships only if it beats
   keep-the-set on forward excess per market.
3. **Coverage gate:** no ranking decision on a wallet with n_eff < 8 — it cannot be evaluated at all.
   That is 3 of 25 track wallets today, plus 2 with no settled print.

No rule, size, gate, booking or threshold was changed by this card, and nothing was written to
`prisma/dev.db` (read-only connection). The only artifacts are this note, the instrument, the truth
cache and the JSON table.
