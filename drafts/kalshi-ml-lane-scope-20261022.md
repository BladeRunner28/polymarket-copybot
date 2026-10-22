# Kalshi ML lane — scope

**Date:** 2026-10-22 · **Status:** SCOPE (no code written) · **Author:** Hermes

## Correction of record

Repeated briefs described Kalshi as absent from the ML lane and left it there. The accurate statement
is narrower and I had it as the wrong one for weeks:

- **False:** "there is no Kalshi lane to wait for." There are **six scheduled Kalshi jobs** and ~195 MB
  of venue data accruing daily.
- **True:** **no `ml-*` script reads any Kalshi source.** The ML lane is Polymarket-only because nobody
  pointed it at Kalshi, not because Kalshi cannot support one.
- **Also true, and not a blocker:** Kalshi publishes no wallet attribution, so a *copy* lane there is
  impossible. An ML lane is market-only by construction — it never needed wallets. Treating "no wallets"
  as "no Kalshi" was a category error.

## What already exists and is running

Six cron jobs, all `last_status=ok`:

- `copybot-kalshi-shadow` — every 15 m · `copybot-kalshi-shadow-report` — 18:30 daily
- `copybot-kalshi-venue-shadow` — every 15 m · `copybot-kalshi-tape` — every 15 m
- `copybot-kalshi-macro` — every 60 m · `copybot-kalshi-pm-pair` — every 15 m

Data on disk:

- **`data/kalshi-tape/` — 195 MB, 245 files**, `bars-YYYY-MM-DD.jsonl.gz` daily since **2026-10-12**,
  plus `bars.jsonl` (30,816 rows) and `coverage.jsonl` (859 rows). Family allowlist in
  `kalshi-tape-families.json`, seeded 2026-10-12.
- **`kalshi-macro-quotes.jsonl` — 75,278 quotes / 336 markets / 9.7 days** (10-12 22:08 → 10-22 14:59).
  Families: KXFED 46,400 · KXGDP 8,352 · KXCPI 7,534 · KXU3 6,496 · KXPAYROLLS 6,032 · KXRECSSNBER 464.
  Median **232 quotes per market**.
- **`kalshi-macro-settled.jsonl` — 14 settled**, and critically it carries **venue truth**:
  `result` (yes/no), `expiration_value`, first/last quote mid, `hours_to_close`. This is the label
  source Polymarket's observe lane lacks.
- **`kalshi-venue-shadow.jsonl` — 1,281 paired rows, 721 resolved.** Market mix: other 591, sports 312,
  weather 294, politics 53, macro 29, crypto 2.
- **`kalshi-pm-btc-pair-*.jsonl`** — ~4 MB/day since 10-13, with `fee_model` and `venue_skew_ms` columns.
- **`PaperTrade` where `venue='Kalshi'`: 92 legs, realized +$27.82** (Polymarket: 12,676 legs, +$15,516.69).
- RuleSet already carries `kalshiMinCopyScore 80`, `kalshiMinConfidence 0.75`, `kalshiCircuitBreakerPnl -50`.

## Unresolved finding that must be settled first

In `kalshi-venue-shadow.jsonl`, across **721 resolved pairs**: **Kalshi PnL sums to $0.00** while the
Polymarket side sums to **$3,216.44**. Raw agreement between `kalshiResolved` and `won` is 335/721
(46.5 %).

I am **not** calling either of these a defect yet — `kalshiResolved` and `won` may encode different
things (whether the venue resolved vs whether our side won), which would make my agreement arithmetic
meaningless, and the $0.00 may be by design if that arm books quotes rather than positions. But a paired
venue arm that produces zero PnL over 721 resolutions is exactly the shape of a silent instrument, and
nothing downstream should be built until one of those two readings is confirmed. **Step 0 of any build.**

## Three candidate lanes

### K1 — Kalshi-only market model
Same design as the Polymarket market-only lane, on the tape. **Blocked on calendar, not code:** the tape
is 10 days old; the Polymarket model was fit on 99,561 rows across 29,686 markets. A Kalshi-only model
needs ~90 days of tape to be comparable, i.e. **not before 2027-01**, and Kalshi's macro families are
event-driven (few markets, sparse resolutions), so effective density is worse than raw days suggest.
**Effort:** ~2 dev-days of code, then wait. **Verdict: do not build now.**

### K2 — Cross-venue mispricing (Polymarket vs Kalshi, same event) ← recommended
This is the only lane where Kalshi adds **information** rather than another book to lose on: a second
price for the same outcome. Polymarket cannot supply that from inside Polymarket, and no amount of
Polymarket history produces it. The infrastructure is already collecting (`pm-pair` every 15 m,
`venue-shadow` every 15 m); what is missing is the candidate export and an honest fee model per venue.
**Effort:** ~3.5 dev-days — candidate export 1 d, feature build 1 d, walk-forward eval 1 d, read page 0.5 d.

### K3 — Macro calibration (already running, not ML)
`kalshi-macro-shadow.py` has its own pre-registered read written before the data existed: *n ≥ 20 settled
markets per family*, each with a quote at ≥ 24 h and another at ≤ 6 h to close, report implied-vs-realized
by horizon bucket. It is at **14 settled of 20** in aggregate. No build needed — it is a wait, and it
tests venue quality rather than generating a trading edge.

## Recommendation

**K2.** It uses data already on disk, needs no calendar wait, and answers a question the Polymarket lane
structurally cannot: *is the same event priced differently on two venues, by more than both venues'
fees?* K1 is a duplicate of a lane that already returned a negative on richer data, gated behind three
months of collection.

## Pre-registration for K2 (written before measuring)

**Hypothesis.** The same outcome shows a persistent executable cross-venue spread that exceeds
round-trip fees on both venues, and is not explained by timestamp skew between the venues.

**Measurement.** Join paired observations; compute executable edge per pair at matched timestamps using
each venue's own fee model (Kalshi's is **not** Polymarket's — it must be read from the venue, not
assumed); report median/quartile edge net of fees, the share of pairs clearing fees, concentration
ex-top-10, and the sensitivity to `venue_skew_ms`.

**Decision rule (all needed to continue).** Median executable edge exceeds round-trip fees, **and**
≥ 30 % of paired observations clear fees, **and** the edge survives ex-top-10 concentration, **and**
edge does not vanish when pairs with `venue_skew_ms` above its median are excluded.

**Refutation.** Kalshi adds no independent edge and the lane closes if **any** of: median edge is inside
the fee band; < 30 % of pairs clear fees; edge is carried by fewer than 10 pairs; the skew control kills
it; or Step 0 shows the paired arm has been booking nothing at all, which would mean the 721 "resolved"
pairs never measured what they appear to.

## What I need from you

1. **Approve K2 scoping→build**, or say K1 (and accept a 2027-01 start).
2. **Step 0 first:** authorise me to resolve the $0.00 Kalshi PnL and the 46.5 % agreement — read-only,
   ~1 h, and it may reclassify the whole cross-venue premise.
3. Confirm the fee model assumption should be verified against Kalshi's published schedule rather than
   reused from the Polymarket adapter (I believe they differ; I have not verified it here).
