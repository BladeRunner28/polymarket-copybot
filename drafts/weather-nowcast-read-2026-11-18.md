# wx2 read — dead-bracket residual mass & ensemble-vs-market, NYC (2026-11-18)

**Instrument:** `scripts/weather-nowcast-sampler.py` (hourly, keyless, cron `0598c4000662`) →
`data/weather-nowcast-samples.jsonl`; applied by `scripts/weather-nowcast-read.py` (read-only).
**Gate:** `drafts/weather-nowcast-prereg-20261012.md` — frozen 2026-10-12 22:52 CDT. Not edited,
not re-frozen, not reinterpreted for this read.
**Window:** 2026-10-12 → 2026-11-17 · 861 sampler runs · 26 700 bracket rows · 1 722 context rows.
**Supersedes:** `drafts/weather-nowcast-read-2026-11-01.md` (20 settled days). Same gate, 37 days now.

**Status: no live-path change.** No rule, size, risk gate, paper trade, PnL number or venue
keep/cancel moves off this read. Kalshi stays paper-only / keyless. `wx3` and `wx4` not started.

---

## Verdict

| venue | verdict | basis |
|---|---|---|
| **kalshi** | **FAIL** (gate not passed) | floor cleared 37/20; Q1 has **zero** qualifying legs in both in-window buckets |
| **polymarket** | **VOID** | its own `feeSchedule` changed **twice** inside the sample window (prereg void condition) |

Decision rule, quoted from the frozen gate:

> **PASS (one-sided, per venue)** iff, over **≥ 20 distinct settled days** with ≥ 3 qualifying
> samples in the bucket, the day-mean total edge per sample unit has a **day-clustered bootstrap
> 95 % CI lower bound > 0**. Both venues are reported; a pass on one says nothing about the other.

> **Floor: ≥ 20 distinct settled days per venue** with ≥ 3 samples in the relevant hour bucket.
> Below the floor the read prints **INSUFFICIENT SAMPLE** and makes **no claim**.

> **Voids the sample:** a change to the sampler's field semantics; an oracle-rule change by either
> venue (PM changed publisher between its 2025 and 2026 eras already); a fee-schedule change.

**Read `kalshi FAIL` as "the gate did not pass", not as "a measured zero edge."** Every Q1 component
is `INSUFFICIENT SAMPLE`; the per-venue label is the read-script's own wrinkle, unchanged mid-sample.

---

## 1. Q1 — executable residual mass in dead brackets, 16:00+ / 18:00+ ET

Edge per dead bracket = `max((1 − no_ask) − fee, yes_bid − fee)`, only legs with **size ≥ 50**.
A "dead" bracket is one whose upper bound the day's max-so-far on **that venue's own settlement
station** already exceeds, so `P(YES) = 0` by monotonicity.

| venue | bucket | dead-bracket obs | legs | days | mean edge | 95 % CI (day-clustered) |
|---|---|---|---|---|---|---|
| kalshi | 16:00+ | 266 | **0** | 0 | — | — |
| kalshi | 18:00+ | 201 | **0** | 0 | — | — |
| polymarket | 16:00+ | — | 4 | 2 | +0.0010 | [+0.0010, +0.0010] |
| polymarket | 18:00+ | — | 1 | 1 | +0.0010 | [nan, nan] |

Routes taken: polymarket `sell_yes` ×5, `buy_no` ×0. kalshi: no route, because no leg.

**Kalshi — still the pre-written no-op close.** 467 dead-bracket observations after 16:00 ET across
37 settled days produced **zero** rows with a YES bid at ≥ 50 contracts. The whole-sample diagnostic
sharpens it: of 420 `dead` rows, the YES bid is quoted on **37** rows with median size **40**
(min 1, max 595) and `no_ask` size is **0** on every one — i.e. the certain side exists, but as a
token quote, not as executable size. This is what the prereg wrote down in advance:

> If, at 16:00-18:00 ET, the "certain" side of dead brackets is simply **not offered** on either
> venue … then Q1's honest close is "there is no residual mass to harvest" and NYC weather dies as
> a strategy.

**Polymarket — the same 5 legs, one tick of nothing.** All five are `yes_bid = 0.001` against
`no_ask = 0.999` (a book summing to exactly 1.000) in the zero-fee era; the CI is degenerate at
[+0.0010, +0.0010] because it is the tick, not a spread. At the 50-contract floor that is
**$0.25 gross across 37 days** (≈ $0.007/day). PM's all-day diagnostic shows 3 032 dead rows, YES
bid quoted on 39 (median size 452, max 6 371) — but those quotes sit **before** the 16:00 bucket or
below the size floor once the fee era is accounted for.

---

## 2. Q2 — pre-14:00 market-implied vs 31-member-ensemble-implied, paired by day

Δ = market − ensemble. **Δ < 0 ⇒ the market is better than the ensemble.** Log-loss and Brier of
the realized bracket, day-clustered bootstrap CI.

| venue | bundles / days | log-loss Δ | 95 % CI | Brier Δ | 95 % CI |
|---|---|---|---|---|---|
| kalshi | 441 / 35 | **−2.8236** | [−4.3664, −1.4894] | **−0.4866** | [−0.6793, −0.3182] |
| polymarket | 446 / 36 | **−2.1563** | [−3.5524, −0.9232] | **−0.4803** | [−0.6582, −0.3076] |

**Both CIs exclude zero, in the same direction, and both venues are now past the 20-day floor**
(Kalshi 35 days, PM 36). The market beats the 31-member GFS ensemble on both. The PM arm sits inside
a VOID venue (§3), so only the Kalshi arm is a claim; but the two agree in sign and magnitude, which
is the useful part: **nothing here suggests the ensemble adds information the pre-14:00 price lacks.**

Floor shadow (printed, not used by the gate — the gate stays on the calendar basis):
kalshi calendar 37 / resolution-verified 35 (`2026-10-12`, `2026-11-13` unverified);
polymarket 37 / 36 (`2026-10-12` unverified). Both still ≥ 20 either way.

---

## 3. Why Polymarket is VOID — and why that is procedural, not substantive

Polymarket's own `feeSchedule` changed **twice inside** the sample window, at the market level:

- `2026-10-13 → 2026-10-20T18:56Z`: `rate 0.05`, `rebateRate 0.25`, `takerOnly true`
- `2026-10-20T18:56Z → 2026-11-01T04:22Z`: `rate 0`, `rebateRate 0` — 5 940 rows over 14 distinct
  cycle days, and **44 markets flip mid-life** (the same bracket is quoted at 0.05 before the switch
  and 0 after), so this is a venue-side change, not a listing attribute
- `2026-11-01T04:22Z → 2026-11-18` (newest row): `rate 0.05` again — 12 606 rows over 29 days carry
  0.05 across the two eras

A fee-schedule change mid-sample is a void condition named by the frozen gate. Reported, not
smoothed. The arithmetic is unaffected where it matters — all 5 PM Q1 legs fall in the zero-fee
window and are fee-insensitive at 0.001, and Q2 uses no fee — so the void is **procedural**: it
removes the right to claim, which is the whole point of pre-registering.

**Forward boundary (new, flagging it now):** the venue reprices weather taker fees **0.05 → 0.01 at
2026-11-20 23:59 UTC** (repo fee work, commit `b684e30` / `drafts/profit-research-20261118.md`). Any
sample collected after that instant is a **third** fee regime, so a future read that pools across it
is void by the same clause. The current era closes in two days.

---

## 4. Instrument repair made for this run (disclosed, semantics-neutral)

The gate fired `STALE:reader-error:unrunnable` because the gate gives the reader **600 s** and the
reader had grown past it: `kalshi_outcome()` / `pm_outcome()` were re-fetched **per sample bundle**
with no cache (441 + 446 bundles × a 1.2 MB settled-market pull / a gamma event pull), so runtime
scaled with the sample. Measured on today's file: **unmodified reader ≈ 11 min (exit 0, gate would
have timed out)**.

Fix, applied this run: `import functools` + `@functools.lru_cache(maxsize=None)` on the two outcome
lookups — **3 lines, `/Users/xsnyde2/polymarket-copybot/scripts/weather-nowcast-read.py`**. No
scoring, floor, bucket, fee or verdict logic touched.

Verified, not assumed:
- same input, both versions run to exit 0 → **stdout byte-identical**; JSON identical except
  `generated_at` (10:50:54 vs 10:58:19 — the two runs, not a values difference);
- reader now **66 s**; the gate itself now runs end-to-end in **79 s and prints `MET`** (was STALE).
- sampler untouched: cron `0598c4000662` active, hourly, last run 08:51 CST ok, newest sample row
  14:50:31Z — so the staleness was never the sampler.

---

## 5. Census and drop rule

- 861 sampler runs → 26 700 bracket rows, 1 722 context rows.
- **Kalshi:** 38 days observed, **37 settled**; samples per ET bucket `<14:00` 2 778 · `14–16` 426 ·
  `16:00+` 414 · `18:00+` 1 290.
- **Polymarket:** 38 days observed, **37 settled**; `<14:00` 5 005 · `14–16` 770 · `16:00+` 737 ·
  `18:00+` 2 299.
- **Days excluded by the >2 % drop rule: none** (`excluded_days: []`). No `dropped` entries and no
  instrument errors on any coverage row in the window.
- Field semantics and oracle basis re-checked at this read: `dead_basis_station` is KLGA
  (Polymarket) and CentralPark/NYC (Kalshi) on every in-window row; Kalshi's fee is the pinned law
  `0.07·P·(1−P)` (its rows carry no `feeSchedule`, by design). **The only semantic change in the
  window is the PM fee schedule (§3), which is exactly the void.**

---

## 6. Caveats that limit these numbers

1. **The PM void (§3)** — no Polymarket claim is available from this sample, including the Q2 arm
   that now clears the floor.
2. **Q1's Kalshi zero is a liquidity-location fact, not an efficiency measurement.** It says nothing
   about sizes below 50 contracts, and nothing about brackets that are dead for reasons other than
   the max-so-far monotonicity rule.
3. **The dead flag uses the hourly METAR max-so-far, while settlement uses the venue's own product**
   (PM: NOAA hourly KLGA Temp column; Kalshi: TWC Central Park daily summary). That gap is why Kalshi
   dead brackets can carry 1–15 ¢ bids at all; the flag was truth-checked against settled outcomes at
   the 11-01 read (217/217 Kalshi, 1 576/1 576 PM settled away, zero settled YES) and **not re-run
   for this read**.
4. **Q2's log-loss is tail-driven.** One realized bracket priced near the 1e-6 clip moves a day's mean
   by whole nats; the Brier deltas (same sign, much tamer) are the metric to trust. Log-loss is
   direction only.
5. **Sizes are top-of-book only**, sampled hourly at varying minutes — a resting bid seen at 17:10
   may not survive to 17:15.
6. **Kalshi is paper-only permanently here** (no key, no wallet attribution), so nothing on that venue
   can ever be more than shadow.
7. **37 days is a thin floor, not a regime.** Both venues' histories are shallow and perishable, and
   the PM fee era turns over on 2026-11-20 (§3).

---

## 7. What was NOT changed

- `drafts/weather-nowcast-prereg-20261012.md` — **not edited, not re-frozen, not reinterpreted.**
- `scripts/weather-nowcast-sampler.py` — untouched.
- No rule, threshold, sizing, exposure cap or risk gate. No `src/lib/safety.ts` change; paper-only.
- No paper trade, no realized PnL, no dashboard number, no published figure.
- Kalshi left paper-only and keyless — no key requested, none used.
- `wx3-weather-breadth-expansion` **not started** (its entry condition is a signed, CI-backed edge;
  none exists — the honest result is the opposite). `wx4-weather-live-lane` **not started** (needs a
  wx2 PASS plus a separate approval with a before/after).
- The sampler was not re-registered, restarted or rescheduled.

**What WAS changed:** `scripts/weather-nowcast-read.py`, 3 lines (§4) — a memo cache, verified
output-identical on the same input.
