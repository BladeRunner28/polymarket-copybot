# U2b — is there ANY wallet-side selector? (measured 2026-11-19)

**Answer: no.** Six wallet-side features, all computed causally from the wallet's own prior settled
book, fail the card's pre-registered promotion gate on the acted book.

## Why this was still worth running

The card named three candidates "not yet priced at leg grain" — wallet DEPTH, lag persistence,
per-band specialisation. All three had already been measured (wallet-depth-field-clamp /
-floor-reread / -ceiling-300-finding; wallet-lag-persistence-ranker, AUC 0.571 REFUTED 2026-11-03;
polycopy-concentration-feature-test). Citing them, not re-deriving them.

What had never been tested is the feature a live selector would actually consume: a wallet attribute
computed from legs that had already resolved **before** this leg opened. Every stored WalletProfile
score is an as-of-print snapshot that overwrites itself, so the earlier U2 read carried look-ahead.
This read removes it by construction (`terminalAt < openedAt`).

## Basis

- population: PaperTrade acted legs, isDemo=0, status closed/resolved, realizedPnl not null
- clock: openedAt UTC 2026-09-26 .. 2026-11-18 (the card's own forward clock)
- level: one leg; target: realizedPnl USD (money — no outcome label, so the EXIT-vs-SETTLEMENT split cannot bite)
- CI: 1,000-rep bootstrap clustered on marketId, seed 20260926 (0.96 markets/leg → cluster nearly degenerate, CIs near-iid)
- C-200: 857 legs / 821 markets / 50 wallets; 681 (79.5%) have a usable prior book (>=5 prior terminal legs)

## Result (C-200 forward)

Reference: copy-all on the covered subset +$0.886/leg; top-tercile entry price +$0.649/leg.

- depth — top tercile +$3.121/leg, CI [-0.970, +8.535]
- recent_mean_pnl — +$1.977/leg, CI [-2.388, +7.347]
- prior_win_rate — +$1.180/leg, CI [-3.372, +6.063]
- band_excess — -$1.307/leg, CI [-5.796, +2.983]
- prior_roi — -$2.033/leg, CI [-5.650, +1.183]
- prior_mean_pnl — -$1.697/leg, CI [-5.209, +1.311]

Multiplicity: 6 features x 4 contrasts; Bonferroni alpha 0.0083; BH q >= 0.134 everywhere — none significant.

**Concentration kills the one near-miss.** depth's 231-leg top tercile: median $0.00, 10% trimmed
mean -$1.132, ex-top-10 -$605.58; its wallet-level cut is +$0.379 [-1.853, +2.309]. prior_mean_pnl's
leg-level and wallet-level readings disagree in **sign** (-$1.697 vs +$2.011) — that is what a null
looks like. All-lanes arm (1,127 legs / 935 markets / 57 wallets, 901 covered) reproduces the null.
STANDARD is underpowered at 158 covered legs and is not read.

## The finding that outlives the card

The forward C-200 book's own headline is a top-10 artifact: sum **+$1,367.31** over 857 legs, but the
top 10 legs carry **+$3,818.87** → ex-top-10 **-$2,451.56**, median $0.00/leg, 10% trimmed mean
-$2.55, win rate 31.7%. Any selector judged against that mean is chasing ten legs.

## Status

Nothing tagged awaiting-approval; no rule, size, threshold, gate or admission input touched.
Re-open only when a named feature's top tercile holds >=200 covered legs **and** its lower CI bound
clears zero on both contrasts. Instrument: `npm run wallet:selector-search`
(scripts/u2b-selector-search.py, self-test = causality + shuffled-mutation arms).
