# Class-swap measurement: the class basis is denser, better covered — and the same null

**Card** `wallet-category-fit-class-swap` (approved 2026-09-23, **measurement half**) · **status** measured;
no scoring change made · **date** 2026-09-23 · instruments `scripts/measure-category-fit-source.ts` (fetch) +
`scripts/measure-category-fit-basis.py` (measurement)

## The question the card set

Swap the category dimension of wallet scoring from the raw event-slug token onto the real class
(`marketCategoryClass` / `marketCategoryFine`). The token basis is known-defective (`highest` spans 14,879
marketIds; `bestCategory` literally reads `will`, `what`, `world`). The measurement half is: **does a class-based
category fit rank leg outcomes better than the token-based one, or is it the same null with prettier names?**

## Setup (and why a fetch was needed)

A wallet's per-category win rate is derived from its resolved activity sample at scan time and never stored, so
the comparison cannot be rebuilt from SQLite. The fetch runs **the same adapter call the scanner runs**
(`fetchWalletActivity(address, 30)`) for all **198** wallets that hold a settled leg, and records the bucket maps
for three keys from **one snapshot** — token (production today), coarse class, fine class — so the comparison
isolates the *basis*, not snapshot age.

- **198/198 wallets fetched, 0 failures.**
- **Token-mirror cross-check: 0 mismatches** against `scoreWallet`'s own `categoryStrengths` on all 198 wallets —
  the mirror is verified against production's computation, not assumed.
- Class source: `ObservedTrade.marketCategoryClass` where stamped (only rows written after the ingest change
  carry it — **36 rows**), else the validated Python classifier. On those 36 live rows: **36 agree / 0 disagree**.

## Result 1 — the class basis is what the card says it is (structure, 198 wallets)

| basis | buckets/wallet (median) | bucket size (median trades) | trades in buckets ≥2 | distinct best-bucket values | strongest-category bucket carries (median share of the wallet's sample) |
|---|---|---|---|---|---|
| token | 14 | 2.5 | 94.2% | 40 | 33.6% |
| coarse class | 3 | 33.0 | 99.8% | 7 | 72.6% |
| fine class | 8 | 7.5 | 99.1% | 19 | 45.5% |

The token map fragments a wallet's record into ~14 thin buckets; a "strongest category" claim there rests on a
third of the sample. The class map aggregates it. Also production-side, across **all 3,201 profiles**: 12 buckets
per wallet median (max 106), **41.1% of wallets hold at least one question-fragment token bucket**, **9.0% of
bucket trades sit in them**, and **9.3% of wallets' `bestCategory` is a fragment token** (`will`, `what`, …).

So the swap is structurally justified. That was never the open question.

## Result 2 — and it does not rank leg outcomes any better (the measurement)

Same legs, same estimator, same MDE machinery as the published score-information read; the wallet's bucket win
rate is the score, `won` is the label. A basis "clears" only if its AUC is further than the lane's MDE from 0.5
**and** its wallet-clustered CI excludes 0.5.

**C-200 — 1,962 legs / 102 wallets · win 49.5% · MDE ±0.026**

| basis | AUC | clustered 95% CI | clears | fit defined on |
|---|---|---|---|---|
| token (as stored, production) | 0.497 | [0.446, 0.554] | no | 74% |
| token (fresh fetch) | 0.509 | [0.454, 0.569] | no | 69% |
| **coarse class** (fresh) | 0.487 | [0.434, 0.542] | no | 87% |
| **fine class** (fresh) | 0.502 | [0.451, 0.553] | no | 84% |

**STANDARD — 8,694 legs / 184 wallets · win 63.8% · MDE ±0.013**

| basis | AUC | clustered 95% CI | clears | fit defined on |
|---|---|---|---|---|
| token (as stored, production) | 0.525 | [0.428, 0.643] | no | 84% |
| token (fresh fetch) | 0.529 | [0.433, 0.652] | no | 84% |
| **coarse class** (fresh) | 0.493 | [0.422, 0.564] | no | 91% |
| **fine class** (fresh) | 0.522 | [0.445, 0.613] | no | 90% |

**Not one basis clears, in either lane.** The class basis is *worse* than the token basis on C-200 coarse (0.487)
and on STANDARD coarse (0.493) — i.e. the more aggregate the bucket, the closer to a coin flip.

It is not a null because nothing moved: the swap **does** change the feature. On C-200 the class basis supplies a
fit where the token basis has none on **366** legs (and vice versa on 19); on STANDARD, **1,090** legs. The two
bases disagree by more than 10 win-rate points on **388** C-200 legs and **2,577** STANDARD legs.

**What that does inside the score** (`src/lib/scoring/trade.ts:119-123`):
`categoryFitScore = winRate × 130 − 15`, and an *undefined* fit scores the neutral **50**. So the swap converts
366 C-200 legs from "no category information → 50" into a live, confident-looking component value — while the
component ranks outcomes at chance. That is added variance in the copy score, not added signal.

## Verdict

- The card's premise holds: the class is the right *label* for a category dimension, and it is materially denser
  (3 buckets vs 14; 33 trades vs 2.5 per bucket; 87–91% coverage vs 69–84%).
- The card's implied benefit does **not** hold: a class-based `categoryFitScore` ranks leg outcomes at chance,
  in both lanes, with CIs that include 0.5 — the same null as the token basis, and marginally worse on the coarse
  axis. **Recommendation: do not swap the scoring dimension.** It moves a published score, so it would need a
  positive measurement to justify it; the measurement is negative.
- If the class is wanted at all, the defensible uses are diagnostic: keep the class beside the token for
  reporting/labels and for the analytics instruments (it is what made this measurement possible), and leave the
  live `categoryFitScore` on the token so **no published score moves**.
- A third option existed and was measured away: use the class only as a *fallback* when the token bucket is
  missing. It would fill 366 C-200 legs — with a chance-level number. Not recommended.
- Nothing here is a rule change, so nothing is parked behind the Oct 8 window: the card stays in **Backlog**
  with the measurement recorded, pending your call on whether to close it as "measured — not supported".

## Caveats

- The class basis here is the *bucket key*; the fine/coarse classes were stamped at ingest today, and legs were
  classified through the parity-checked classifier rather than a backfilled column (36 stored-class rows agreed
  36/36).
- AUC on leg outcome is not EV, and the wallet sample contains only wallets that already cleared every gate.
- **Correction carried from outside this card:** the published score-information CIs were computed with `NaN`
  placeholders left in the score array (NaN sorts to the top of the score axis and narrows the interval). Point
  estimates there were always computed on the defined subset, so no verdict flips; re-derived clean, the
  intervals widen — C-200 `categoryFit(token)` CI `[0.471, 0.536] → [0.446, 0.554]`, STANDARD `[0.454, 0.590] →
  [0.428, 0.643]`. This instrument bootstraps the defined subset with remapped wallet clusters.

## Reproduce

```
npx tsx scripts/measure-category-fit-source.ts      # fetch/cache 198 wallet samples -> data/category-fit-source.json
python3 scripts/measure-category-fit-basis.py       # -> data/category-fit-basis.json
```
