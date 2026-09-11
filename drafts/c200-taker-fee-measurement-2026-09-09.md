# Paper-ledger taker-fee measurement (2026-09-09)

**Trigger:** poly-maker audit (`drafts/poly-maker-audit.md`) surfaced that Polymarket charges category-based taker fees and that our paper ledger books fills at observed prices with **no fee model at all** (the only `fee` hits in `src/` are the word "feed"). This quantifies the drag. **Measurement only — no lane, rule, size or PnL-code change.**

## Method

- **Formula (official):** `fee = C × feeRate × p × (1 − p)` — `docs.polymarket.com/trading/fees`. Makers pay 0; only takers pay. Category coefficients: politics/finance/tech/mentions **0.04**, sports/economics/culture/weather/other **0.05**, crypto **0.07**, geopolitics **0 (fee-free)**.
- **Independently cross-checked** against poly-maker's own live fill: a ~668-share 19¢ Politics close → formula predicts $4.11, exchange charged ~$4.1.
- **Legs modelled:** entry always (entering is a match); exit only for `status='closed'` (an early exit is a real sell → another match); `status='resolved'` settles at 0/1 with no trade → **no exit fee**. `shares = simulatedPositionSize / entryPrice`.
- **Kalshi:** same functional shape, `rate 0.07` per its published schedule — **flagged as requiring live confirmation**, n=92.
- **Category:** `MarketSnapshot.category` is NULL on all 8.7M rows, so category is inferred from the `marketId` slug by keyword (5,140 of 9,531 land in "other" → 0.05). A **flat-0.04 sensitivity** is reported so the result doesn't hinge on classification.
- **All-taker is the upper bound** (worst case). Entries/exits that were actually maker cost 0 — and on Politics would *earn* a 25% rebate. Reality sits between.
- Script: `/tmp/poly_fee_measure.py` (re-runnable; reads `prisma/dev.db` read-only).

## Results (9,531 realized trades)

| Bucket | n | Realized gross | Modelled fee | Fee / gross | Net | Flips |
|---|---|---|---|---|---|---|
| **ALL** | 9,531 | **+$5,397.60** | **$2,463.83** | **45.6%** | **+$2,933.77** | 238 |
| **BANKROLL_200 (C-200)** | 1,431 | **−$153.77** | **$327.10** | 212.7% | **−$480.87** | 63 |
| STANDARD | 8,100 | +$5,551.37 | $2,136.73 | 38.5% | +$3,414.64 | 175 |
| Polymarket only | 9,439 | +$5,435.79 | $2,429.72 | 44.7% | +$3,006.07 | 236 |
| Kalshi only | 92 | −$38.19 | $34.11 | 89.3% | −$72.30 | 2 |

Flat-0.04 sensitivity: ALL fee $1,978.11 → net $3,419.49; **C-200 fee $266.71 → net −$420.48**.

**Entry leg = 87% of all modelled fee** (C-200: 77%). The drag is overwhelmingly paid on **entry**.

## What this says

1. **The paper ledger flatters results by ~45%.** Gross +$5,397.60 becomes ~$2,934–$3,419 once taker fees are priced. Every downstream figure derived from the ledger — C-200 ladder progress, tuning-review inputs, category comparisons — inherits this optimism.
2. **C-200 is loss-making under every coefficient assumption.** Booked −$153.77; with fees −$420 to −$481. This is consistent with (and now mechanically explains part of) the earlier −$324/33-day attribution work. The failure isn't only category mix — the lane pays a fee on every entry that the ledger never charged.
3. **The entry is the problem, not the exit.** 87% of the fee sits at entry, i.e. we cross the spread to enter. Maker entry (resting, post-only) removes the entry fee entirely and, on Politics, converts it into a 25% rebate on taker fees paid by others — the exact discipline poly-maker enforces (`post_only = true`, and rewards only score for resting orders within the band).
4. **Sensitivity is small; the conclusion is not.** Whether "other" is 0.04 or 0.05 moves the total by ~$0.5k but leaves C-200 negative in both.
5. **238 trades (63 in C-200) flip from winners to losers** once fees are applied — the sign-flip rate is the sharpest way to state the fidelity gap.

## Caveats

- All-taker is an upper bound; if part of our fills are maker, the true fee is lower. We do not currently record maker/taker on paper fills — **that's the missing field** (the audit's markout/fill-probability point, and Phase D2's "realistic fills" scope).
- Category inference is keyword-based on slugs, not Polymarket's own tag.
- Kalshi's 0.07 coefficient and the "no fee on settlement" assumption for `resolved` trades are both modelled, not confirmed against a live fill.
- Fees are charged in USDC at match time, independent of outcome — they are a guaranteed drag, not a PnL-contingent one.

## Recommended follow-up (needs approval; post-Oct-8)

- Wire the fee model into the paper accounting as a **shadow column** first (booked PnL untouched; fee-adjusted PnL emitted alongside), so tuning reviews can see both. Behind a rules flag, revertible.
- Record **maker/taker** (or at minimum order type) on paper fills — without it, fee-adjusted PnL can't improve past the all-taker bound.
