# Change 1 + change 2 — execution (2026-09-21)

**Approved 2026-09-21** ("I approve.") in reply to the 2026-09-20 18:00 C-200 daily
report. Applied 08:4x CDT. RuleSet **v59 → v60**; DecisionJournal gained two nullable
columns.

Two changes: **1** halve new size in the 0.60–0.80 premium band, **2** journal the real
gate inputs on every decision and price the `minConfidence` bar. Change 1's *named
mechanism* could not work — the recon below redirected it to the mechanism that can.

## A · Recon — why change 1 needed a different carrier

The rec proposed `premiumOverlayEnabled 0 → 1` (k=0.5) "scoped to 0.60–0.80". Three
measured facts killed that carrier:

1. **The overlay skips lane copies.** `score-trades.ts` applies the v38 premium resize
   only when `!kellySized && lane !== "short_ttr"` — and every copy in the target band
   is a short-TTR **lane** copy. 7d band flow: **87 opens, 84 of them at exactly $4.99**
   (= fixed lane size × the 0.5 band map), zero Kelly admits (Kelly refuses λ̂>0 bands).
   Flipping the flag would have changed **nothing** in the target band.
2. **The overlay cannot be band-scoped.** It is band-driven by construction: with
   k=0.5 the same flip would **boost the <0.20 band by 1.39×** (λ̂=−0.789) — the
   tail-variance increase the report's own analysis argues against ("prefer count over
   size there"; its top 5 tickets are +$2,229 of the band's +$1,782).
3. **The headline and the mechanism disagreed on magnitude.** k=0.5 gives
   `1 − 0.5×0.2142 = 0.893`, i.e. **−10.7%**, not the headline's −50%.

So the delta was implemented where it binds: a **band-scoped factor on the final size,
whatever lane booked it**, carrying the headline's magnitude.

## B · Change 1 — shipped (RuleSet v60)

`c200BandSizeFactor` **0.5**, `c200BandSizeFactorRange` **"0.6-0.8"** (lo inclusive,
hi exclusive). Applied after Kelly/lane sizing and **before** the v55/v58 concentration
gates, so those rails measure the size that actually books.

| | before | after |
|---|---|---|
| 0.60–0.80 avg clip | $4.90 | **$2.45** |
| 0.60–0.80 7d notional | $426.38 | **$213.19** (Δ −$213.19) |
| other bands | untouchable by construction | — |

Evidence for the change: band excess **−0.0995, z=−3.96, N=382**; cash **+$2.66 over
30d on $1,015 of flow** while absorbing a third of the day's new positions.

Artifacts: `src/lib/band-size.ts` (pure `parseBandRange` / `applyBandSizeFactor`),
`tests/band-size.test.ts` (8 cases incl. hi-exclusive boundary and revert-inertness),
`scripts/apply-v60-premium-band-half.ts` (prints the per-band consequence, `--dry-run`
writes nothing). Revert: factor `1` or range `""`.

## C · Change 2 — shipped (measurement, additive)

**The gap, precisely.** `confidence` is computed in `trade.ts` *before* the hard-skip
gate and drives the `minConfidence` bar — but three skip returns and the short-TTR copy
return hardcode `confidence: 0`, so **8,585 of 8,651 skip rows (99.2%) stored 0.0** and
the funnel's largest blocker could not be evaluated against outcomes at all.
(`copyScore` was already stored post-boost, rounded — so the real gaps were the raw
confidence and the unrounded decision score.)

Shipped:

- **Two nullable columns** `rawConfidence` + `adjustedCopyScore` on `DecisionJournal`,
  populated on every returned decision (all six `scoreTrade` paths). Applied as **raw
  DDL + `prisma generate` + an empty drift check** — never `db push` against the live
  DB — and the existing `confidence`/`copyScore` semantics are **unchanged**, so no
  consumer, ML feature or published figure moves.
- **`data/lowconf-shadow.jsonl`** — every decision the confidence gate rejected, with
  the price + band, the raw confidence it was rejected at, the bar in force, the score,
  TTR/spread/liquidity, and `confidenceOnly` (nothing else was blocking — the population
  a lower bar would actually admit). `scripts/mark-shadow-longshot.ts` (hourly) marks
  each to settlement and publishes `data/lowconf-shadow-summary.json` split by
  **confidence bucket** (0.60–0.70 / 0.50–0.60 / …), by **band**, and by the
  confidence-only slice.

No threshold moves: `minConfidence` stays 0.7 until the Oct 8 close, attributed by
`ruleSetVersion`.

## D · Verification

```
RuleSet v60 active — c200BandSizeFactor 0.5, range "0.6-0.8"; RuleChange
   changedBy=hermes-v60-premium-band-half-approved
apply-v60 --dry-run    → 7d band: 87 opens / $426.38 / avg $4.90 / realized −$3.84;
                         consequence avg $4.90 → $2.45, notional → $213.19
schema                 → ALTER TABLE ×2 (raw DDL), prisma generate, migrate diff =
                         "This is an empty migration." (no drift)
npx tsc --noEmit       → clean
npm test               → 221/221
marker (all 4 feeds)   → shadow-drift / shadow-wallet-cap / shadow-lowconf all report;
                         lowconf summary written
cron prompts           → daily report 5,075 → 6,621; tuning review 11,622 → 12,405
roadmap                → 200; 3 new cards (band-size, journaled inputs, lowconf lane)
```

**First production sample — the scoring cycle that started 08:55:18 CDT (after the
deploy):**

- **Change 2 columns are live**: of the rows written since the deploy, the 14 scored
  decisions carry `rawConfidence` + `adjustedCopyScore` (0.69 / 0.18 / 0.31 / 0.64 /
  0.11 …) while the legacy `confidence` column stays `0.0` — additive exactly as
  designed, no consumer semantics moved. (Rows written without them are v52 coalesce
  rows: a coalesced fill never went through `scoreTrade`, so there is nothing to
  record — null means "not scored", not "gate saw 0".)
- **The lowconf lane captured 12 rejects on the first cycle**, with the band-aware bar
  recorded per row (`minConfidence` 0.55 for a <0.20 long-shot vs 0.70 global) and the
  `confidenceOnly` flag. Both early samples are `confidenceOnly: false` — the rejects
  arrive stacked with other hard skips, which is a first (small-sample) hint that the
  bar is not the sole blocker for most of them; the summary's slice will answer it
  properly as settlements accumulate.
- **`[BAND-SIZE]` not yet fired**: that run booked 0 copies, so no C-200 size was
  computed. It fires on the first copy entering [0.6, 0.8) — ~12/day at the current
  rate — and the trigger condition to look for is `factor=0.5` with
  `size 4.99→2.50 (lane=short_ttr)`.

(tsx loads the source at process start, so a run already in flight keeps the old code —
a missing line in the 08:40 run is not a wiring failure.)

## E · Not done

- No `minConfidence` / `minCopyScore` change (measurement only, per the rec's own
  framing and the Oct 8 window).
- The overlay flag stays **0**: turning it on would boost the long-shot band, which is
  the one band the same report says to protect from size increases.
