# Pre-registration — weather nowcast-vs-price calibration (NYC, both venues)

**Frozen 2026-10-12, in-thread, BEFORE the first sample row existed.** This file is the gate: it is
committed before `scripts/weather-nowcast-sampler.py` writes anything, so the test cannot be bent
after seeing the data. Approved by Xman in-thread ("B, then card and schedule C and D").

**Instrument:** `scripts/weather-nowcast-sampler.py` (hourly, keyless, read-only) →
`data/weather-nowcast-samples.jsonl`. **Read:** `scripts/weather-nowcast-read.py`.
**Measurement only:** no orders, no keys, no rule/size/gate change, no live lane. Kalshi stays paper
regardless — we hold no key.

---

## Universe (fixed at freeze)

- **City: NYC only.** Both venues, reported separately and **never pooled**.
- **Kalshi** `KXHIGHNY` cycles (`KXHIGHNY-<yymon><dd>`) that are listed/open at sample time.
- **Polymarket** `highest-temperature-in-nyc-on-<month>-<day>-<year>` events, same cycles.
- **Oracle product, pinned by the feasibility read** (`drafts/weather-data-feasibility-2026-10-12.md`):
  Polymarket = max of **routine hourly METAR @ KLGA**; Kalshi = **CLINYC / Central Park via The
  Weather Company** (proxied by GHCN-Daily `USW00094728` TMAX, tenths °C → °F, nearest int).
  **Day-of "max so far" is computed per venue on THAT VENUE'S OWN station's hourly METAR series**
  (Polymarket: KLGA; Kalshi: Central Park / station id `NYC`) — amended 2026-10-12 before any
  in-window sample, see the amendment note at the bottom. Each venue's own oracle is used for
  settlement.
- **Size:** every price recorded with its executable size. The gate is evaluated at **S ≥ 50
  contracts** per leg; a leg thinner than S is reported, never silently upgraded.
- **Fees (pinned; a change voids the sample):** Kalshi taker `0.07 · P · (1−P)`, maker `0`
  (pinned law from the BTC pair card). Polymarket: read the market's own `feeType` / `feeSchedule`
  fields per sample — these weather markets publish **`feeType: weather_fees`, `rate 0.05`,
  `exponent 1`, `takerOnly`, `rebateRate 0.25`** — so PM taker `= 0.05 · min(p, 1−p)`, maker 0.
  **Never** use `takerBaseFee` / `makerBaseFee` (a legacy constant 1000) or any base/1e4 derivation.

## Price primitives recorded (definitions the read depends on)

Binary mirror: `yes_ask = 1 − no_bid`, `no_ask = 1 − yes_bid`. Each row stores best `yes_bid`,
`yes_ask`, `no_bid`, `no_ask` **with the size resting at each level**, plus the full best-level set
of the sampled ladders, the venue's own mid, `max_so_far_F` **per station** (KLGA for Polymarket, Central Park for
Kalshi), the ET hour of the
sample, the ensemble bracket distribution, and the raw fee fields.

**"Dead" bracket at a sample:** `upper_bound < max_so_far_F` that day **measured on that venue's own
settlement station**. The daily maximum is monotone, so under the pinned oracle product `P(YES) = 0`
for that bracket — no model required.

## Q1 — is there *executable* residual mass in dead brackets?

Per dead bracket, per sample, the harvestable edge is the **best of the two mirror routes**, each net
of that venue's taker fee on the leg actually taken:

```
edge_buy_no  = (1 − no_ask) − fee_taker(no_ask)      # pay no_ask now, receive 1.00
edge_sell_yes= yes_bid − fee_taker(yes_bid)          # receive yes_bid now, pay 0 later
edge         = max(edge_buy_no, edge_sell_yes)       # only routes with size >= S qualify
```

Hour buckets: **16:00 ET and later** (the hour at which the day's high is already final in **91 %**
of days, 99 % within 1 °F, measured over 103 days) and separately **18:00 ET+** (100 %).

**PASS (one-sided, per venue)** iff, over **≥ 20 distinct settled days** with ≥ 3 qualifying samples
in the bucket, the day-mean total edge per sample unit has a **day-clustered bootstrap 95 % CI lower
bound > 0**. Both venues are reported; a pass on one says nothing about the other.

## Q2 — pre-14:00: is the bracket distribution flatter or sharper than the ensemble says?

At every sample with **ET hour < 14:00**, build two distributions over that day's bracket ladder:

1. **market-implied** — bracket mid prices, normalized to sum 1 (no-arbitrage projection);
2. **ensemble-implied** — the 31-member GFS ensemble's daily max per member, rounded to whole °F,
   placed in the venue's own bracket grid, normalized.

Primary metric: **log-loss and Brier of the realized bracket**, paired by (day, venue, hour-bucket).
**Reported as a signed mean difference** Δ = market − ensemble with a day-clustered CI; a claim
requires the CI to exclude 0. Δ > 0 ⇒ the market is *worse* than the ensemble (potential edge);
Δ < 0 ⇒ the market is *better* (the ensemble adds nothing). No direction is assumed at freeze.

## Sample floor, drop rules, invalidation

- **Floor: ≥ 20 distinct settled days per venue** with ≥ 3 samples in the relevant hour bucket.
  Below the floor the read prints **INSUFFICIENT SAMPLE** and makes **no claim**.
- A sample is **dropped** (and counted in the census) if it lacks a `max_so_far_F`, lacks a complete
  ladder for both venues, or has an instrument error. **If > 2 % of a day's samples drop, that day is
  excluded entirely** and the exclusion is printed.
- **Voids the sample:** a change to the sampler's field semantics; an oracle-rule change by either
  venue (PM changed publisher between its 2025 and 2026 eras already); a fee-schedule change.
- Nothing is built, sized or un-parked off this read. If it passes, the next step is a **separate**
  card with its own before/after — which is `wx4-weather-live-lane`, parked on this result.

## What would make this a no-op (stated up front)

If, at 16:00-18:00 ET, the "certain" side of dead brackets is simply **not offered** on either venue
(the books are one-sided, with the maker resting the *worthless* side), then Q1's honest close is
"there is no residual mass to harvest" and NYC weather dies as a strategy. First eyeball at freeze
time (2026-10-12 ~23:00 ET, not part of the sample): PM's dead brackets showed **YES asks at 0.001
with ~9 k size and no YES bids**, Kalshi's showed a **NO bid ladder up to 0.99 with an empty YES
ladder** — i.e. both venues rested the side *they* had the edge on. That is exactly the shape Q1
exists to measure over ≥20 days instead of one evening.

---

## Amendment note (2026-10-12 ~23:55 ET, still before any in-window sample)

**What changed:** the day-of "max so far" is now computed **per venue on that venue's own settlement
station** (Polymarket → KLGA hourly METAR; Kalshi → Central Park `NYC` hourly METAR, proxying the
CLINYC/TWC product). The first version used the KLGA series for both.

**Why:** the two venues settle on *different* NYC stations (this is the feasibility read's trap 4).
The very first instrument run caught it: at 23:52 ET on 2026-10-12 the KLGA series read max-so-far
**71 °F**, so the Kalshi bracket `69° to 70°` was flagged **dead** — while its own book carried a
**0.99 YES bid**, i.e. Kalshi's market believed (correctly, on Central Park's data) that the bracket
was still live. Under the v1 basis Q1 would have "measured" a ~0.99 edge on a bracket that could
still win: a fabricated result, not a finding.

**Also:** the single sample row written by the v1 basis (one run, taken at 23:52 ET after that day's
high was already final) was **deleted** rather than kept, so `data/weather-nowcast-samples.jsonl`
starts empty under the v2 semantics. Field-semantics changes void samples by this document's own
drop rule; there were no in-window samples to void.

**Unchanged:** Q1/Q2, the size floor (S ≥ 50), the fee laws, the hour buckets, the 20-day floor, the
drop rules, and the falsifiers.
