# ML training — first fit, and the three leaks that had to die first

2026-10-19. Every number measured on this machine. Scripts: `scripts/build-ml-dataset.py`,
`scripts/ml-prepare.py`, `scripts/ml-train.py`, `scripts/ml-online.py`. Venv: `.venv-ml`.

---

## 0. Verdict in one paragraph

After removing three separate sources of fake skill, the honest result is **real but modest**:
a regularized logistic on the strictly *executable* feature set beats the strongest price-only
baseline by **+0.0292 AUC** (0.7367 vs 0.7077), CI **[0.0218, 0.0363]** excluding 0, with Brier
**0.2018 vs 0.2203**. LightGBM ties the logistic to four decimal places, so the booster earns
nothing and the interpretable model should be the primary. Online/streaming learning **hurts** as
a scorer and helps only as a calibrator (+0.0010 Brier). Nothing here is a PnL claim — AUC is not
edge, and the EV read is still owed.

## 1. Three leaks, in order of how much damage they did

**(a) The label was wrong for 25 % of rows.**
`ObservedTrade.outcome` is a *token name*, not a YES/NO flag: `NO` 60,915, `YES` 3,423, `UNDER`
1,931, `OVER` 1,588, `DOWN` 567, `UP` 543, then team names. The first version of the builder
treated everything that wasn't literally `"YES"` as the NO side, which **inverted OVER and UP**
and assigned a meaningless side to every team token. Fixed by deriving the side from prices (our
entry price sits nearer one of the two token prices), validated at **97.31 %** on the 63,120 rows
whose token name is unambiguous (YES 93.0 % near-yes, NO 97.5 % near-no, OVER 85.0 %, UNDER 85.1 %
near-no, UP 71.7 %, DOWN 70.2 % near-no).

**(b) 70.2 % of the test window was decisions in markets that had ALREADY resolved.**

| population | share of test labels | win rate |
|---|---|---|
| market already decidable at decision time | 32,425 (**70.2 %**) | **91.5 %** |
| market genuinely open at decision time | 13,776 | **60.0 %** |

Those rows are the machine-learning equivalent of betting a race after it finishes: the price at
decision time was already ~0.95 and the outcome matched it. Trained with them, the model reports
**AUC 0.949**; trained honestly, **0.737–0.768**. This was by far the largest source of fake skill
and it is invisible unless you compare the label's timestamp with the decision's.

**(c) `horizon_hours` is a future quantity.** It is `(first 0.90/0.10 crossing − decision time)`,
i.e. computed from a terminal event, and how fast a market reaches a terminal price correlates with
which way it went. Excluded from every arm; it remains a legitimate purge/reporting key.

Result of the guard: **20,788 of 63,168 labelled rows survive (32.9 %)** — 7,012 train / 13,776 test.

## 2. The bar, re-derived on the honest population

Two price-only frames, both logistic, same rows:

| frame | AUC | Brier |
|---|---|---|
| `logit(yes_price)` | **0.7077** | 0.2203 |
| `logit(side_price)` | 0.7075 | 0.2114 |

The bar is the **stronger** one (0.7077 / 0.2203) — letting the weaker frame be "the bar" would
manufacture an improvement out of a feature choice. Note what this lands on: almost exactly the
**original ML-1 gate bar of 0.729 / 0.212**, which was until now judged on a different population
and a different label. Two independent roads arriving at ~0.71–0.73 AUC is a real validation of
that bar, and it is the opposite of what I told you earlier today: on the *leak-free* population
the old bar was roughly right, and it was the 0.9224 I quoted off the contaminated one.

## 3. Results — three feature arms, all against the same bar

| arm | logistic AUC / Brier | LightGBM AUC / Brier | Δ AUC vs bar (clustered CI) |
|---|---|---|---|
| full | 0.7680 / 0.1902 | 0.7678 / 0.1912 | +0.0602 [0.0526, 0.0678] |
| executable (no `wallet_entry_price`) | 0.7673 / 0.1904 | 0.7609 / 0.1938 | +0.0533 [0.0459, 0.0600] |
| **executable-clean** (also no `price_drift`) | **0.7368 / 0.2008** | **0.7367 / 0.2018** | **+0.0292 [0.0218, 0.0363]** |

Why three arms: in the full arm **`wallet_entry_price` carries 63.6 % of the gain** (plus
`detected_price` 11.8 %, `price_drift` 2.7 %). That is the price the *wallet* paid — knowable at
decision time, but **not tradeable**: by the time we observe the trade the book has usually moved,
and `detected_price` is what we would actually pay. A model that leans on it answers "would this
have won at a price we could not get". The executable-clean arm is the only one that reflects a
real entry, and it is still **+0.0292 AUC** with the CI excluding zero.

**LightGBM ≈ logistic in all three arms.** The booster adds nothing the anchored logistic does not
already have, so the recommendation flips from the one I gave before training: ship the logistic as
the primary scorer (calibrated by construction, auditable, incrementally updatable) and keep
LightGBM as a cross-check that must keep agreeing.

## 4. Online learning — the honest result is a negative

Prequential (predict-then-learn, no row seen before it is predicted), on 13,776 settled decisions:

| online arm | prequential AUC | Brier | vs constant |
|---|---|---|---|
| Hoeffding Adaptive Tree (primed) | 0.6301 | 0.2828 | **skill −0.178** |
| online logistic (primed) | 0.6524 | 0.2713 | **skill −0.130** |
| **online calibrator on the frozen batch** | 0.7601 | **0.1928** | skill +0.197 |
| frozen batch, for reference | 0.7609 | 0.1938 | +0.197 |

- Standalone online models are **worse than predicting the base rate**. 7,012 priming rows is not
  enough to grow a tree, and the signal is a smooth price relationship that online trees model
  badly.
- Recalibrating the *batch* scorer online is the only version that does not lose: AUC unchanged
  (0.7601 vs 0.7609, as a monotone transform must), **Brier improves 0.0010**. Small, but it is
  free insurance against the base-rate drift we are actually exposed to.
- Two earlier calibrator runs looked catastrophic (AUC 0.66–0.68) purely because an unseeded
  online learner predicts ~0.5 for its first hundreds of rows — ties that collapse AUC. Seeding it
  at identity is what made the experiment meaningful; the first two numbers were the artifact, not
  the method.

**So: "learn live as it trades" is worth wiring, but as recalibration + drift monitoring on top of
a batch scorer, not as a self-learning predictor.** ADWIN fired on 2026-08-31 (after 3,327 rows)
and 2026-09-08 (after 6,847 rows) in the unseeded runs — real regime boundaries worth logging.

## 5. What this does NOT establish

- **AUC is not edge.** +0.029 AUC says the ranking improves; it does not say the bets make money
  after fees and at the prices we can actually get. The EV/PnL read is the next required step:
  for each trade, `p_model × 1 − entry_cost − fees`, and it must be positive on the executable
  arm, not the full one.
- **One holdout, one threshold.** 7,012 train rows across 11,777→ few thousand markets, 394 wallets.
  The +0.029 is within the range that a different boundary could move.
- **The 0.5 % label noise** from the derived resolution stands, and is larger than the effect being
  claimed for any single feature.
- **The declined arm is still partly unlabelled**: 21 % of decisions abstain (market still open at
  the last snapshot) and cannot train anything until they settle.

## 6. Reproduce

```
python3 scripts/build-ml-dataset.py --out data/ml        # 58 s
.venv-ml/bin/python scripts/ml-prepare.py                # 23 s
.venv-ml/bin/python scripts/ml-train.py --drop wallet_entry_price,price_drift   # 30 s
.venv-ml/bin/python scripts/ml-online.py --model calibrator                     # 3 s
```
