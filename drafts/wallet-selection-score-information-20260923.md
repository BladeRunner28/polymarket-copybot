# How much do our wallet-selection scores know about leg outcome? (C-200: nothing)

**Card** `wallet-selection-score-information` (approved 2026-09-23) · measurement only, gates nothing
**Instrument** `python3 scripts/wallet-selection-score-information.py` → `data/wallet-selection-score-information.json`

## Method

Every stored selection score, per lane, against **leg won** on settled non-demo legs, with:
a **wallet-clustered** percentile bootstrap CI (2,000 draws resampling wallets — legs inside a wallet are not
independent draws), the lane's **Hanley-McNeil MDE at A = 0.5**, each score re-measured **within entry-price
quintiles**, and **entry price as the bar**. A score "clears" only if its AUC is further than the MDE from 0.5
**and** its clustered CI excludes 0.5.

## C-200 — 1,962 legs / 102 wallets · MDE ±0.026 · win legs 49.5%

| score (as stored) | AUC | 95% CI (wallet-clustered) | within price quintiles |
|---|---|---|---|
| globalScore | 0.497 | 0.457–0.563 | 0.492 |
| roi30d | 0.496 | 0.460–0.540 | 0.532 |
| consistencyScore | 0.494 | 0.452–0.549 | 0.478 |
| copyabilityScore | 0.493 | 0.436–0.552 | 0.505 |
| winRate30d | 0.480 | 0.437–0.533 | 0.451 |
| resolvedTradeCount30d | 0.526 | 0.486–0.565 | 0.553 |
| tradeCount30d | 0.519 | 0.468–0.566 | 0.565 |
| categoryFit (token) | 0.497 | 0.471–0.536 | 0.492 |
| **entryPrice** | **0.653** | **0.610–0.698** | 0.572 |

**Not one wallet-selection score clears its MDE on C-200.** The only ranker that clears is the market's own
price — and inside price quintiles it still reads 0.572.

## STANDARD — 8,694 legs / 184 wallets · MDE ±0.013 · win legs 63.8%

| score (as stored) | AUC | 95% CI | within price quintiles |
|---|---|---|---|
| globalScore | 0.496 | 0.404–0.594 | 0.502 |
| roi30d | 0.427 | 0.353–0.511 | 0.521 |
| consistencyScore | 0.432 | 0.342–0.544 | 0.526 |
| winRate30d | 0.462 | 0.377–0.573 | 0.506 |
| copyabilityScore | 0.590 | 0.484–0.654 | 0.480 |
| tradeCount30d | 0.581 | 0.489–0.647 | 0.519 |
| **averageLiquidity** | **0.602** | **0.513–0.658** | 0.491 |
| **averageSpread** | **0.603** | **0.505–0.658** | 0.474 |
| categoryFit (token) | 0.525 | 0.454–0.590 | 0.555 |
| **entryPrice** | **0.758** | **0.699–0.790** | 0.514 |

## Reads

1. **The wallet-quality dimension carries no leg-outcome information in either lane.** `globalScore` is 0.496/0.497,
   `roi30d` 0.427–0.496, `consistencyScore` 0.432–0.494, `winRate30d` 0.462–0.480. The scores we select wallets with
   do not rank their copies' outcomes.
2. **The two STANDARD features that clear the bar are not wallet-skill features.** `averageLiquidity` 0.602 and
   `averageSpread` 0.603 are **market-quality proxies**, and both **collapse inside entry-price quintiles**
   (0.491 / 0.474) — i.e. they are largely re-expressing price, which is already the strongest ranker. `copyabilityScore`
   (0.590) and `tradeCount30d` (0.581) sit above chance but their clustered CIs include 0.5 → not cleared.
3. **The category dimension in its current form is a coin flip** (`categoryFit (token)` 0.497 C-200 / 0.525 STANDARD),
   which is the quantitative case for the `observed-trade-category-field` fix. A class-based category fit is now
   buildable from the next scan and is carded with its own gate.
4. **Price does the work**: C-200 q1 (price 0.03–0.29) is 337 legs at 32.9% win but **+$2,729 realized** — the long-shot
   band carries the lane, consistent with v54. STANDARD q2 (0.44–0.79) is 4,632 legs / +$5,663.
5. **AUC is not EV** and the sample only contains wallets that already cleared every gate, so this says nothing about
   the gates' own value — it says the *ranking* inside the admitted set is uninformative. Legs also mix natural
   resolutions (481 resolved C-200) with early exits (1,481 closed), and the exit rule is not outcome-neutral.
