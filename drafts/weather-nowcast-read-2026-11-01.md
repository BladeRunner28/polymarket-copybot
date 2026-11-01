# wx2 read — dead-bracket residual mass & ensemble-vs-market, NYC (2026-11-01)

**Instrument:** `scripts/weather-nowcast-sampler.py` (hourly, keyless, cron `0598c4000662`) →
`data/weather-nowcast-samples.jsonl`; applied by `scripts/weather-nowcast-read.py` (read-only).
**Gate:** `drafts/weather-nowcast-prereg-20261012.md` — frozen 2026-10-12 22:52 CDT, amended same
evening (per-venue station basis) **before** any in-window sample. Not edited for this read.
**Window:** 2026-10-12 → 2026-10-31, 463 sampler runs, 14 560 bracket rows, 926 context rows.

**Status: no live-path change.** No rule, size, risk gate, paper trade, PnL number or venue
keep/cancel moves off this read. Kalshi stays paper-only / keyless. `wx3` and `wx4` not started.

---

## Verdict

**Polymarket: VOID** — the prereg's own invalidation clause fired (fee-schedule change mid-sample,
§3). No verdict is reported for it.
**Kalshi: FAIL as printed by the tool**, which here means *the gate did not pass*, not *a measured
zero edge*: Q1 produced **zero** qualifying legs in either in-window bucket (§1).

Decision rule, quoted from the frozen gate:

> **PASS (one-sided, per venue)** iff, over **≥ 20 distinct settled days** with ≥ 3 qualifying
> samples in the bucket, the day-mean total edge per sample unit has a **day-clustered bootstrap
> 95 % CI lower bound > 0**. Both venues are reported; a pass on one says nothing about the other.

> **Floor: ≥ 20 distinct settled days per venue** with ≥ 3 samples in the relevant hour bucket.
> Below the floor the read prints **INSUFFICIENT SAMPLE** and makes **no claim**.

> **Voids the sample:** a change to the sampler's field semantics; an oracle-rule change by either
> venue (PM changed publisher between its 2025 and 2026 eras already); a fee-schedule change.

Both venues cleared the 20-day floor on the **calendar** basis (20/20 each). On the
**resolution-verified** basis both sit at **19**, `2026-10-12` unverified on both — printed as a
shadow only; the gate still uses the calendar basis (unchanged).

---

## 1. Q1 — executable residual mass in dead brackets, 16:00+ / 18:00+ ET

Edge per dead bracket = `max((1 − no_ask) − fee, yes_bid − fee)`, only legs with **size ≥ 50**.
A "dead" bracket is one where the day's max-so-far on **that venue's own settlement station**
already exceeds the bracket's upper bound, so `P(YES) = 0` by monotonicity.

| venue | bucket | dead-bracket obs | legs | days | mean edge | 95 % CI (day-clustered) |
|---|---|---|---|---|---|---|
| kalshi | 16:00+ | 145 | **0** | 0 | — | — |
| kalshi | 18:00+ | 111 | **0** | 0 | — | — |
| polymarket | 16:00+ | 859 | 4 | 2 | +0.0010 | [+0.0010, +0.0010] |
| polymarket | 18:00+ | 657 | 1 | 1 | +0.0010 | [nan, nan] |

**Kalshi — the harvestable side is simply not quoted in the window.** Across 20 settled days, 145
dead-bracket observations after 16:00 ET produced **zero** rows with a YES bid at *any* size, and
zero `no_ask` size. Every `yes_bid` Kalshi rested on a dead bracket in the whole sample sits at ET
< 15:00 (§4). This is the "no-op" close the prereg wrote down in advance:

> If, at 16:00-18:00 ET, the "certain" side of dead brackets is simply **not offered** on either
> venue … then Q1's honest close is "there is no residual mass to harvest" and NYC weather dies as
> a strategy.

**Polymarket — 4 legs, and the edge is one tick of nothing.** All four in-window legs (2026-10-23
×2, 2026-10-28 ×2) are `yes_bid = 0.001` against `no_ask = 0.999`, i.e. a book summing to exactly
1.000, with 90–385 contracts showing. Net of fee (zero-fee era, §3) the edge is exactly 0.0010 —
which is why the bootstrap CI is degenerate at [+0.0010, +0.0010]: it is the tick, not a spread.
At the 50-contract floor that is **$0.05 per leg, $0.20 across all 20 days** (≈ $0.01/day).

---

## 2. Q2 — pre-14:00 market-implied vs 31-member-ensemble-implied, paired by day

Δ = market − ensemble. **Δ < 0 ⇒ the market is better than the ensemble.** Log-loss and Brier of
the realized bracket.

| venue | bundles / days | log-loss Δ | 95 % CI | Brier Δ | 95 % CI |
|---|---|---|---|---|---|
| kalshi | 235 / 19 | **−2.602** | [−4.812, −0.838] | **−0.431** | [−0.704, −0.184] |
| polymarket | 236 / 19 | **−0.715** | [−1.691, −0.109] | **−0.272** | [−0.506, −0.079] |

Both venues' CIs exclude zero, in the same direction: **the market beats the 31-member GFS
ensemble**. The tool still prints **INSUFFICIENT SAMPLE**, because it scored **19** days and the
frozen floor is 20 — so no claim is made here, per the gate. The sign and rough size are worth
recording: nothing in this sample suggests the ensemble adds information that the pre-14:00 price
lacks.

---

## 3. Why the Polymarket side is VOID (prereg invalidation clause)

Polymarket's own `feeSchedule` changed **inside the sample window**, at the market level:

- samples through 2026-10-19: `feeType: weather_fees`, `rate 0.05`, `rebateRate 0.25`
- from **2026-10-20T18:56Z**: `feeType: zero_fees`, `rate 0`, `rebateRate 0` — and **44 markets
  flip mid-life** (e.g. every `highest-temperature-in-nyc-on-october-20-2026-*` bracket carried
  0.05 until 10-20T18:56Z and 0 after), so this is a venue-side change, not a listing attribute
- the 2026-11-01/11-02 listings are back on `weather_fees` / 0.05 again

That is a fee-schedule change mid-sample, which the frozen gate names as a void condition. Reported,
not smoothed over.

**What the void does and does not touch.** All four in-window PM Q1 legs fall *after* the change
(10-23, 10-28), so they were already priced at fee = 0 and the arithmetic is internally consistent;
Q2 uses no fee at all. At these prices the fee is $0.00005/contract on a 0.001 leg — immaterial to
the numbers. So the void is **procedural, not substantive**: it removes the right to *claim*, which
is exactly what the gate is for.

**Field semantics and oracle basis: checked, unchanged.** Bracket/context key sets are identical
before and after the two mid-window sampler commits (`a28ccb2` 10-26 city table, `1d4cb58` 10-27
coverage alerting); `dead_basis_station` is `CentralPark/NYC` for Kalshi and `KLGA` for Polymarket
on 100 % of rows, both eras; Kalshi's fee dict (`taker 0.07*P*(1-P)`, `maker 0`) is a single value
across all 4 374 rows; ensemble member count is 31 on 100 % of context rows.

**Dead-flag truth check (my own, outside the read):** every row flagged `dead` was compared against
the venue's own settled outcome — **Kalshi 217/217 and Polymarket 1 576/1 576 (11 not yet settled)
settled away from the flagged bracket; zero rows we call dead settled YES.** The dead determination
is sound on settled data.

---

## 4. Out-of-window observation (NOT part of the gate — no claim, no sizing)

The gate only looks after 16:00 ET. For the **"X° or below"** side that window is unnecessarily
late: monotonicity kills such a bracket the moment the day's max exceeds X, at *any* hour. Looking
there (still keyless, still the same instrument):

- **Kalshi**, dead `X° or below` brackets at ET < 16:00 with a YES bid at ≥ 50 contracts:
  **13 sample rows over 3 distinct day-brackets** (2026-10-15 `63° or below`, 2026-10-17
  `61° or below`, 2026-10-27 `59° or below`), YES bids **0.02–0.15**, sizes 51–595.
  Mean edge **+0.0569/contract** (median +0.0373, max +0.1411), all `sell_yes`.
  Capacity at the observed top-of-book ≈ **$70 gross over 20 days** (~$3.5/day, on 3 of 20 days),
  before fills, latency and depth decay.
- All three brackets **settled NO** (checked against Kalshi's own settled markets), so the bids were
  stale, not information.
- Why they might legitimately exist: the residual 3–14¢ is plausibly priced **product risk** — the
  dead flag uses the hourly METAR max-so-far, while Kalshi settles on TWC's Central Park daily
  summary, the exact gap the prereg's amendment had to fix for the mirror side. n = 3 days cannot
  distinguish "free money" from "the market knows the product better than our proxy".
- **Polymarket**, same out-of-window shape: 18 rows / 5 days, but all at the **0.1¢ tick** (max
  0.5¢) → no mass, consistent with §1.

---

## 5. Census and drop rule

- 463 sampler runs → 14 560 bracket rows, 926 context rows, both venues.
- **Kalshi:** 21 days observed, **20 settled**; samples per ET bucket `<14:00` 1 470 · `14–16` 228 ·
  `16:00+` 216 · `18:00+` 702.
- **Polymarket:** 21 days observed, **20 settled**; `<14:00` 2 706 · `14–16` 418 · `16:00+` 396 ·
  `18:00+` 1 287.
- **Days excluded by the >2 % drop rule: none.** No `dropped` entries and no instrument errors
  logged on any coverage row in the window; the sampler log shows clean runs through
  2026-11-01T08:35 CST (newest sample row 2026-11-01T14:35Z, hourly cadence intact).

---

## 6. Caveats that limit these numbers

1. **The PM void (§3)** is the headline limit: no Polymarket claim is available from this sample.
2. **Q2 is one day short of the floor** (19 scored vs 20 required) and `2026-10-12` is unverified on
   both venues. Read it as a directionally consistent signal, not a result.
3. **Q2's log-loss is tail-driven.** A single realized bracket priced at ~1e-2 (clipped at 1e-6)
   moves a day's mean by whole nats; the Kalshi −2.60 nats is that. The Brier delta (same sign, much
   tamer) is the metric to trust; log-loss here is direction only.
4. **Q1's Kalshi zero is a liquidity-location fact, not an efficiency measurement.** "No YES bid at
   ≥ 50 on a dead bracket after 16:00" says nothing about whether a *smaller* size clears, or about
   brackets that are dead for other reasons.
5. **Sizes are top-of-book only**, sampled hourly at varying minutes — a resting bid observed at
   17:10 may not survive to 17:15.
6. **The out-of-window numbers (§4) are pre-registration-free** and are reported as observation
   only: 3 day-brackets, unmodeled fee/latency/fill, and a plausible product-risk explanation that
   the sample cannot exclude.
7. **Verdict-label wrinkle (flagged, not fixed):** the read prints per-venue `FAIL` when the floor
   clears and the route is not structurally `absent`, even though every component is
   `INSUFFICIENT SAMPLE`. With Kalshi at zero legs, `FAIL` must be read as "gate not passed". The
   script was not changed — editing it now would touch a frozen-gate consumer mid-sample.

---

## 7. What was NOT changed

- `drafts/weather-nowcast-prereg-20261012.md` — **not edited, not re-frozen, not reinterpreted.**
- `scripts/weather-nowcast-read.py` and `scripts/weather-nowcast-sampler.py` — untouched (including
  the verdict-label wrinkle above, and the fee field, which is read from the row and never
  hard-coded).
- No rule, threshold, sizing, exposure cap or risk gate. No `src/lib/safety.ts` change; paper-only.
- No paper trade, no PnL, no dashboard number, no published figure.
- Kalshi left paper-only and keyless — no key requested, none used.
- `wx3-weather-breadth-expansion` **not started** (its entry condition is a signed, CI-backed edge;
  none exists). `wx4-weather-live-lane` **not started** (needs a wx2 PASS plus a separate approval
  with a before/after).
- The sampler was not re-registered, restarted or rescheduled.
