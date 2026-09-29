# External read: r/PredictionsMarkets "I copied 6,005 Polymarket whale bets late"

**Source** `reddit.com/r/PredictionsMarkets/comments/1ws4u6x` · posted 2026-09-28 04:21 UTC · 15 up / 6 comments
**Author** DubsWasASaint · links `rivo.markets/traders` (a paid-adjacent top-200 trader ranking product) — treat as content marketing with one 3-day window
**Status** analysis only, gates nothing · no rule touched

## What it claims

Every whale-sized BUY on the Polymarket tape 2026-08-23→25 (15,976 entries, deduped, $100 clip each),
copied at six delays (0s / 30s / 2m / 10m / 30m / 1h) and held to resolution, on the 6,005 entries whose
outcome traded after every delay:

- 0s **+7.6%**, 30s +7.6%, 2m +7.7%, **10m +7.7%**, 30m **+4.1%**, 1h **−2.5%**
- average entry price 61.2¢ at 0s → 62.1¢ at 10m → 66.5¢ at 1h
- drift is outcome-aligned: winners +13.7¢ / losers −10.9¢ at 1h (at 10m only +1.7 / −0.7)
- by band: 20–50¢ +13.3% · 50–80¢ +5.9% · 80–95¢ +5.0% · 95¢+ **−3.1%**
- by size: $10k–25k **−4.3%** · $100k+ **+16.7%** (n=53)
- 17 of 26 ranked traders profitable at their own price, 15 at 10m, 8 at 1h

## Key insight for us

Their headline — *speed below ~10 minutes is worth nothing* — is the one thing we already have.
Our whale webhook path is sub-second (`src/app/api/webhooks/whale-signal/route.ts`, Rust sidecar
`:3014`), so a 10-minute grace period is not an opportunity we are missing; it is a statement about
retail copiers. The load-bearing claims are the two the post did not set out to make:

1. **Delay cost is a function of win rate, not of time.** Winners get dearer (+13.7¢) and losers
   cheaper (−10.9¢), so at a 65.6% win rate delay is a tax; at a 20% win rate delay is a *subsidy*.
   Our book prices win rate explicitly (C-200 longshot <0.20 ×2.5, dead zone 0.20–0.60 ×0.125 at v60),
   but our staleness control is flat: `maxPriceDrift = 0.004` for everything ≥0.20. If their mechanism
   transfers, drift tolerance should scale with (1 − band win rate), which is the same direction our
   v57 longshot relaxation went — for an unrelated, percentage-of-price reason. Two independent
   mechanisms pointing at one rule field is worth a measurement.
2. **Lag persistence is a wallet-selection dimension we have never scored.** 9 of their 17
   profitable-at-entry traders are negative an hour late (ferrariChampions2026 +20.0% → −5.5%;
   SPCEXBUYER +19.1% → −27.1%), while Djdjdjekekek (+78.5% → +62.9%) and 0x4f2 (+16.1% → +68.7%)
   survive. Our scores are ROI / consistency / copyability — none of them is lag-robustness.

## Where it does *not* transfer (checked against our data)

- **Population overlap is close to zero.** Their smallest reported size bucket is **$10k+**. Our C-200
  funnel's average followed trade is **$608** (`scripts/apply-v45.ts` evidence line) — a ~20× gap. And at
  *our* scale the size relation runs the other way: v45 found copies following large wallets (avg $608)
  lost **−$0.26/t** while the +EV lane's small wallets ($40) ran −$0.03/t, which is why `whaleSizeUsd=500`
  exists. Their "$100k+ is the best bucket" is a claim about a cohort we do not trade.
- **58% of resolved entries are excluded from every headline.** An entry is scored only if its outcome
  kept trading past the 1-hour delay: 6,005 of 14,240 settled (and of 15,976 total). That drops exactly the
  markets that resolved or went quiet inside the hour — the fast, information-rich ones where a late copy
  would be worst. The exclusion is defensible as "un-fillable", but it filters *in favour* of the
  conclusion being advertised.
- **The "late price" is a tape proxy, not an executable price.** Average of the first buys by *anyone* on
  the same outcome within 5 minutes after the delay, fees not modelled. Our real cost includes the
  half-spread and — in the other direction — our sidecar books every BANKROLL_200 BUY 2¢ inside
  (`maker_improvement = 0.02`), i.e. our *booked* entry price does not move with delay at all. That
  convention means our realized PnL is structurally blind to late-entry cost; the drift gate is the only
  thing standing in for it.
- **No fees, no exits, hold-to-resolution.** Not comparable in magnitude to C-200 realized numbers, which
  carry exits, tier cuts and the 2¢ maker convention.
- **Their band table contradicts our own measured bands.** They like 20–50¢ (+13.3%); our v37/V45+
  measurements put the C-200 0.20–0.60 band in the dead zone (×0.125) and found sub-0.20 the only +EV
  bucket. Different cohort, different treatment — do not import the bands.

## The honest tension with our own live instrumentation

`data/drift-shadow-summary.json` is the counterfactual for the very gate this post argues against:
19,180 blocked candidates, 3,534 marked, **−$0.13/trade ex-dust** (dust-inclusive +$9.98, carried by two
$0.0005 entries) against a live book of ~+$0.94/trade. Its pre-registered decay bar **tripped** on
2026-09-28 (9 consecutive days ≤ $0.50, trailing-7d cohort −1.08), which per the 2026-09-20 pre-registration
means a `maxPriceDrift` / `longshotDriftPct` relaxation is brought forward.

This post is *not* the evidence for that relaxation. Their "10 minutes late costs nothing" is measured on
the **median** entry, whose price did not move at all (40.6% of entries within half a cent of the whale's
price at 30s); our gate only ever fires on the **drifted tail**. Their tables say nothing about whether the
drifted tail is profitable. Our own shadow does, and it says the tail is worth ≈ $0. The tension is real —
volume/capital-recycling value versus −$0.13/t dilution — but it has to be settled on our numbers and by
ruleSetVersion attribution, exactly as pre-registered, not by an external post.

## Recommendations (measurement only, none of this is approved)

1. **Band-relative staleness.** Test whether drift tolerance should scale with the band's realized win rate
   (the (1 − winRate) hypothesis above) rather than stay flat at 0.004 above 0.20. Instrument: extend the
   existing drift-shadow writer with the band's trailing win rate at decision time; read at the same
   Oct 8 window close the other pre-registered reads use. Cheap, reuses the file format already in place.
2. **Per-wallet lag persistence.** Compute each tracked wallet's counterfactual return at 0 / +10m / +30m /
   +1h from tape we already store (`ObservedTrade` has price + timestamp), then score persistence as a
   *candidate ranker* against leg outcome using the harness in
   `scripts/wallet-selection-score-information.py` — wallet-clustered bootstrap CI and the lane's MDE at
   A = 0.5. That harness already showed every current wallet score is a coin flip on C-200 (best 0.526,
   MDE ±0.026) while entry price clears at 0.653, so a new dimension needs the same bar, not a story.

Nothing else in the post is actionable for us: we are not latency-constrained, we do not trade their
sizes, and their bands and category split are their cohort's.

## Thread comments (all 6, for completeness)

The only substantive reply is the objection the post does not address: *"what I've seen when people try and
copy whales is that the whale just sweeps the entire order book so you can't copy"* (No-Brick-2854) — which
is our fill-model gap, not a latency gap. Two replies worry about crowding eating the 10-minute window.
