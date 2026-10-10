# U2 promotion gate — does selecting on wallet skill beat price-only? (READ 2026-10-10)

**Verdict: NO — the wallet-quality selector is NOT promoted. Every reading of the gate fails, and the
wallet-level reading is negative with a confidence interval that excludes zero on the broader
population. The archive's VETO verdict stands, now with money-level evidence instead of an AUC.**

Card: `ml-u2-wallet-feature-priors` · gate text verbatim:
> "Promotion to a SELECTOR requires >=200 of our own forward legs in which top-tercile selection
> beats price-only with a market-clustered 95% CI excluding zero — otherwise the archive's answer
> stands."

## What existed before this read, and what was missing

`scripts/wallet-feature-priors.py` implements the card's *ranking* half: per-feature AUC against the
price baseline, per price quintile, per stratum. It has no **selection** arm, so the promotion gate
above had never actually been tested — an AUC below 0.5 is a strong hint, not the gate. It also reads
the 2026-09-13 canonical dataset, while the 2026-10-10 forward read was produced by a scratch run that
rebuilt the dataset to `data/decision-dataset-forward-20261010.csv`; the repo had no instrument that
ran the gate on either file.

Added: **`scripts/wallet-selection-test.py`** (read-only; writes only its own JSON). It answers the
gate question and nothing else.

## Method — and the design decisions the gate text did not pin

| Choice | Value used | Why |
|---|---|---|
| Population | forward C-200 legs, `opened_at >= 2026-09-26` | the card's own forward clock; 340 of the 365 legs the card counts survive the dataset's dedupe + field requirements (both >200) |
| Feature | `wallet_quality_score` | the "wallet quality" feature the ranking read prices |
| Selector | TOP TERCILE by that score | the gate's words |
| Tercile basis | **both** leg-level and wallet-level | the feature is a WALLET attribute; a leg-level cut on a wallet attribute is arbitrary, so the faithful reading (cut wallets, take their legs) is reported beside it |
| Metric | mean **net-of-fee PnL per leg** (`pnl_net_full`) | the card asks whether selection changes the money; per-leg dollars is the book's own unit |
| "price-only" arm | (i) copy-all, (ii) top-tercile **by entry price** | the gate says "beats price-only" without naming the comparator, so the gate requires BOTH |
| CI | **market-clustered** bootstrap: resample `market_id` with replacement, 1,000 reps, seed 20261010, percentile 2.5/97.5 on the difference in mean PnL/leg | the gate's words |
| Label basis | primary = realized-PnL-per-settled-leg (`pnl_net_full`) | a profitable-leg question, **not** "did the signal predict the market outcome"; the `y_win` base rate is printed beside every AUC for exactly that reason (this repo's measurement-target rule) |

## Results

**Forward C-200 (n=340 legs · 320 markets · 25 wallets · 2026-09-26 → 2026-10-09)**

| Arm | mean net PnL/leg |
|---|---|
| copy-all (price-only baseline population) | **$5.682** |
| top tercile, wallet quality (leg-level, n=161) | $4.527 |
| top tercile, wallet quality (**wallet-level**, 10 wallets, n=42) | **−$0.169** |
| bottom tercile, wallet quality | **$10.222** |
| top tercile by entry price | $0.076 |

| Gate arm | Δ $/leg | 95% CI (market-clustered) | P(Δ>0) |
|---|---|---|---|
| A leg-level top vs copy-all | −1.155 | [−7.022, +5.199] | 0.361 |
| A2 wallet-level top vs copy-all | −5.851 | [−13.201, +1.602] | 0.053 |
| B leg-level top vs top-price | +4.451 | [−1.845, +14.392] | 0.861 |
| B2 wallet-level top vs top-price | −0.245 | [−5.000, +6.173] | 0.421 |
| C leg-level top vs bottom | −5.695 | [−19.961, +8.691] | 0.221 |

**AUC on the same rows:** `wallet_quality` **0.4977** vs `entry_price` **0.6748** against `net>0`;
`y_win` base rate 0.4265.

**Robustness — the verdict does not depend on the population:**

- forward, ALL LANES (n=379): A −1.185 [−6.759, +4.668] · A2 **−6.657 [−13.666, −0.159]** (P(Δ>0)=0.023) · B +3.687 [−2.706, +12.344] · B2 −1.785 [−6.044, +2.593] → PROMOTE **false**
- full history C-200 (n=1,678, 2026-07-22 → 2026-10-09): A −1.016 [−4.581, +2.884] · A2 −0.929 [−4.571, +3.612] · B +2.433 [−0.771, +7.122] · B2 +2.521 [−0.718, +7.843] → PROMOTE **false**

`PROMOTE: false` on all three populations, under both tercile bases.

## Why it fails — the mechanism, in one table

The forward window's 25 wallets, by their own quality score:

| wallet | quality | legs | $/leg |
|---|---|---|---|
| 0x85f031d069 | 92.4 | 4 | +0.22 |
| 0x4dd24f21b6 | 90.8 | 6 | −0.61 |
| 0xc95ed399d2 | 89.3 | 10 | +1.06 |
| 0x80896d05a9 | 89.1 | 4 | **−10.03** |
| 0xfaebec08a9 | 86.6 | 5 | **−9.87** |
| 0xfb07f48542 | 85.6 | **55** | **+12.72** |
| 0x885ffdf360 | 85.0 | **135** | +0.85 |
| 0x524db83689 | 83.1 | 6 | **+70.74** |
| 0x7c63520c2c | 82.8 | 12 | +22.13 |
| 0x8b8b9c565c | **74.3** | 9 | **+38.56** |

Two facts kill the selector: the score is **compressed** (24 of 25 wallets sit in 82.6–92.4, so the
"tercile" is a knife-edge on 2–3 points of score), and the ordering carries the **wrong sign at the
money level** — the single lowest-scored wallet in the window (+$38.56/leg) and the mid-pack wallets
that carried the window's PnL (0xfb07f48542 +$12.72/leg over 55 legs; 0x524db83689 +$70.74/leg) all
sit OUTSIDE the top tercile, while three of the top ten wallets averaged −$10.03, −$9.87 and −$4.65.
The bottom tercile doing best ($10.222 vs copy-all $5.682) is the same fact seen from the other side.

## What this does NOT say

- **It is the acted book.** These are the legs the live policy already chose to trade, so this is
  "which of our own picks were good", never "which signals are good" — the same selection bias the
  ranking instrument documents. A negative selection result here is still decisive for the card's
  question (would filtering on this score have improved the book? — no), but it is not a statement
  about wallet skill in the wild.
- **25 wallets is a small selector universe** and 320 markets is a coarse clustering unit; the CIs are
  wide for that reason. The direction is consistent across three populations, which is the argument —
  not any single CI.
- **Settled legs only** (the dataset's population), labelled by realized PnL; the `y_win` arm is
  printed beside it but the gate is a money question.
- The metric is mean PnL/leg; a different objective (Sharpe, drawdown, tail) could rank arms
  differently, and the gate never named one. Nothing here is a license to change a rule: no rule,
  size, gate or published figure moved, and none is proposed.

## Reproduce

```bash
python3 scripts/wallet-selection-test.py            # forward C-200, all-lanes, full history
python3 scripts/wallet-selection-test.py --bot BANKROLL_200 --from 2026-09-26
cat data/wallet-selection-test-20261010.json        # cuts, arms, gate CIs, label bases
```

Next step, if wallet skill is ever revisited: it needs a feature that separates wallets on something
other than this score (the ranking read prices 14 candidates, all at or below chance on the acted
book), and the promotion gate above is the bar — a top-tercile selection whose market-clustered CI
excludes zero against price-only.
