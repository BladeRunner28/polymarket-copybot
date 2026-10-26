# Weather city expansion — prep for Set 1 (NYC, DFW) and Set 2 (8 cities)

**Status:** prep only. Nothing sampled for any new city. No rule, gate or lane touched.
**Written:** 2026-10-26. Every venue/ticker/station line below was probed live today, not assumed.
**Governing pattern:** `drafts/weather-nowcast-prereg-20261012.md` (frozen, amended same evening) —
Set 1 cities replicate it verbatim; nothing in it is re-litigated here.

---

## 0. The one fact that makes this "a card, not an afternoon"

**The two venues settle the SAME city on DIFFERENT stations, measuring DIFFERENT products.** NYC is the
proof and it was measured before any in-window sample:

- **Polymarket** settles NYC on **KLGA** (LaGuardia), from **routine hourly METAR** (`report_type=3` on
  IEM ASOS).
- **Kalshi** settles NYC on **CLINYC** (Central Park), from **The Weather Company**'s daily summary.

The two disagreed live: `KXHIGHNY-26OCT12 B69.5` bid 0.99 while the LGA series read max-so-far 71. Same
city, same day, different answer. That is why the frozen prereg says **both venues are reported
separately and never pooled**, and why every new city needs **two** oracle identifications, not one.

---

## 1. The pattern each new city must replicate

Copied from the frozen prereg, in the order it must be built:

1. **Series + cycle format** — e.g. `KXHIGHNY-<yymon><dd>`, taken from cycles listed/open at sample time.
2. **Per-venue settlement station** — the `max_so_far_F` basis is computed **on that venue's own station**.
3. **Per-venue oracle product** — hourly METAR vs a daily summary are different quantities; a "wrong
   product" mismatch invalidates a sample exactly like a wrong station.
4. **Sample** = the venue's own mid per bracket + `max_so_far_F` for that station.
5. **Dead bracket** = `upper_bound < max_so_far_F` on that venue's station (the daily max is monotone, so
   under a pinned oracle `P(YES) = 0`). Live check: whether the "certain" side is simply **not offered**.
6. **Net edge per leg** using **that venue's** taker fee on the leg actually taken.
7. **Hour buckets**, with `16:00 ET and later` primary — the hour at which the day's high is already
   final in **91 %** of cases.
8. **PASS (one-sided, per venue)** iff over **≥ 20 distinct settled days** with **≥ 3 qualifying samples**
   in the bucket, the day-mean total edge per sample unit has a **day-clustered bootstrap 95 % CI lower
   bound > 0**.
9. **Q2** — at every sample with ET hour < 14:00, log-loss and Brier of the realised bracket against the
   ensemble-placed distribution, paired by (day, venue, hour-bucket).
10. **Floor / drops** — below 20 settled days the read prints **INSUFFICIENT SAMPLE** and makes no claim;
    a sample drops if it lacks `max_so_far_F` or a complete ladder; **> 2 % of a day's samples dropped
    invalidates that day**.
11. **Invalidations** — publisher change (PM changed publisher between its 2025 and 2026 eras already),
    station change, fee-schedule change.

---

## 2. SET 1 — NYC (existing) + Dallas/Fort Worth (new)

### NYC — already running, do not restart it

`KXHIGHNY` / station `CLINYC` (Kalshi) vs `KLGA` (PM). Card `wx2-nowcast-vs-price-calibration`.
**Status today: 14 calendar-settled days of a 20-day floor, resolution-verified 13**
(2026-10-26 read, `VERDICT=INSUFFICIENT SAMPLE 14/20`). The floor is the constraint and it is a
forward-days constraint: **no dataset shortens it.**

### DFW — the new city, fully resolved except one field

| field | value | source |
|---|---|---|
| Kalshi series | **`KXHIGHTDAL`** — "Dallas Maximum Temperature" | live series list, 15,396 entries |
| Kalshi station | **`CLIDFW`** | the venue's own `rules_primary` on a settled market |
| Kalshi oracle | **The Weather Company**, °F (settled example `expiration_value` 82.00) | same |
| Kalshi bracket form | `>86°` style strike ladders | same |
| PM family | **`highest-temperature-in-dallas-on-<month>-<day>-<year>`** (open today) | gamma, live |
| PM settlement station | **`KDAL` — Dallas LOVE FIELD** (not KDFW) | the PM event's own `description`, read 2026-10-26 |
| PM oracle product | **hourly routine METAR temperature remark**, tenths of a degree **Celsius**, SPECI lines excluded | same |
| PM slug trap | 2025-era slugs were **year-less**; key on `event.endDate`, never the URL | `weather-oracle-reconcile.py` header |

**RESOLVED 2026-10-26: Polymarket settles Dallas on `KDAL` — Love Field — not KDFW.** The doc warned that
assuming KDFW "would repeat the exact class of error the prereg was amended to prevent," and that is
precisely what would have happened: the obvious guess is wrong. DFW is now fully identified on both venues
and has **no blocking field**.

Note how completely the two venues differ on one city — this is the strongest argument for the
never-pool rule anywhere in the doc:

| | station | product | units | oracle |
|---|---|---|---|---|
| Polymarket | **KDAL** (Love Field) | hourly routine METAR remark, SPECI excluded | tenths of °C | METAR |
| Kalshi | **CLIDFW** | daily summary | °F | The Weather Company |

Two airports, two products, two unit systems, two publishers — for the same city and the same day.
A sample that mixed them would be measuring nothing.

Also on Kalshi for Dallas (not Set 1, recorded so nobody re-discovers it): **`KXLOWTDAL`** — a *low*-temp
Dallas series. Low-temp is a separate family and a separate prereg, not a variation of this one.

### Set 1 code work (must be ONE parameterized path, not ten copies)

`scripts/weather-nowcast-sampler.py` currently hardcodes `SERIES = "KXHIGHNY"` and `LGA = "KLGA"`.
Adding DFW by editing those constants would fork the instrument and every later city would diverge.
The work is to lift them into a city table:

```
CITY = {
  "NYC": {"kalshi_series": "KXHIGHNY", "kalshi_station": "CLINYC", "iem_station": "KLGA",
          "pm_slug_prefix": "highest-temperature-in-nyc"},
  "DFW": {"kalshi_series": "KXHIGHTDAL", "kalshi_station": "CLIDFW", "iem_station": "<TBD>",
          "pm_slug_prefix": "highest-temperature-in-dallas"},
}
```

**Note the trap in that table:** Kalshi's basis is a *TWC daily summary at CLINYC*, not an IEM METAR
series — so `iem_station` is the **Polymarket** station and `kalshi_station` names the venue's own
oracle. Conflating them is how a sample silently measures the wrong station. For Kalshi the sampler must
read the venue's `expiration_value` / TWC product, not IEM.

### Definition of "the pattern is established" (the gate to Set 2)

All three, or Set 2 does not start:

1. DFW has completed **at least one full in-window sample cycle** (a cycle day's brackets sampled and
   scored), with the per-venue station split honoured.
2. `scripts/weather-oracle-reconcile.py` reproduces **both** venues' oracle for **5 consecutive days**
   with **zero** wrong-product / wrong-station mismatches on DFW.
3. The sampler runs DFW and NYC through **one parameterized code path** — verified by diffing that the NYC
   output is byte-identical to the pre-change run. If NYC moved, the refactor broke the established city
   and Set 2 inherits the break.

---

## 3. SET 2 — measured availability, today

Probed live 2026-10-26. This is the honest reason the set splits the way it does:

| city | Kalshi | Polymarket | shape |
|---|---|---|---|
| Los Angeles | `KXHIGHLAX` / `CLILAX`, settled ✓ | open ✓ | **two-venue** |
| Seattle | `KXHIGHTSEA` / `CLISEA`, settled ✓ | open ✓ | **two-venue** |
| Tokyo | `KXHIGHTRJTT` / station `RJTT` (Haneda) — series exists, **0 open / 0 settled** | open ✓ | PM-only |
| London | `KXHIGHTEGLL` / `EGLL` (Heathrow) — **0 open / 0 settled** | open ✓ | PM-only |
| Paris | `KXHIGHTLFPG` / `LFPG` (CDG) — **0 open / 0 settled** | open ✓ | PM-only |
| Munich | **no temperature series** (0 hits for 'munich'/'munchen' across 15,396 series; the 19 'germany' hits are macro/sports — GDP, CPI, GfK, BBL spread) | open ✓ | PM-only |
| Berlin | `KXHIGHTEDDB` / `EDDB` (Brandenburg) — **0 open / 0 settled** | **not open today** | **nothing tradeable today** |
| Rome | **no temperature series** (11 'rome' hits are all substring false positives — Chrome acquisition, Jerome Powell, Romeo streams — plus Italy macro/Serie A; none are weather) | **not open today** | **nothing tradeable today** |

**What this means for sequencing:**

- **Start with LA and Seattle.** They are the only two-venue cities, so they are the only ones that can
  reproduce the NYC design *including its cross-venue check*. They are also the cheapest test of whether
  the parameterized path generalises.
- **Tokyo / London / Paris / Munich are PM-only.** They can absolutely reach the 20-day floor (PM lists
  the family), but a PM-only read yields a **PM-only claim** with no cross-venue control — and the frozen
  prereg's whole discipline is that a pass on one venue says nothing about the other. Each should carry
  that limitation in its own prereg header, not inherit NYC's two-venue framing.
- **Berlin and Rome are deferred, not dropped.** Nothing is open today; a city with no live cycle cannot
  be sampled and pre-registering it now would register a population that does not exist. Re-probe when a
  cycle lists. Note Rome additionally has **no Kalshi series**, so it is PM-or-nothing permanently.

**Imprecision corrected 2026-10-26, worth recording because a later reader will grep for it:** the first
draft said Munich and Rome have "no Kalshi series at all." Precisely, they have **no temperature series** —
the series catalogue does return 11 substring hits for `rome` and 19 for `germany`, none of them weather.
Anyone re-checking with a naive grep will find those and conclude this document was wrong; it is the
matches that are wrong, not the absence. Match on the SERIES TITLE, never on the ticker substring.

**How to tell "nothing is listed" from "the call failed" — measured 2026-10-26, keep this.** A probe batch
run during this work returned **0 events for ALL TEN cities including NYC**, which cannot be true: NYC is
demonstrably open. The batch had failed (11 gamma calls in a tight loop) and a catch-all `except: print(0)`
rendered the failure as "nothing listed" — an empty sample read as a clean one. The discriminator is the RAW
BYTE COUNT, not the event count:

- **HTTP 200 + 3 bytes (`[]`)** -> genuinely no event: **Berlin, Rome** (re-confirmed twice).
- **HTTP 200 + ~87-91 KB** -> a real event payload: **NYC, Dallas, LA, Seattle, Tokyo, London, Paris, Munich**
  (1 event each, all re-confirmed).

Any re-probe of these cities must print the status code and byte size beside the count, because a zero from a
failed request and a zero from an empty listing look identical in the parsed form. Treat 0 bytes / non-200 /
parse error as **PROBE-FAILED**, never as absence.

**Deliberately not assumed:** that the international `KXHIGHT*` series will trade. Their existence in the
series catalogue with zero markets means the family is *defined* but not *listed*. A future listing is a
new fact to re-probe, not a plan to schedule.

---

## 4. Cost and reversal

- **DFW:** ~2-3 h, dominated by identifying Polymarket's settlement station and reconciling it. Data volume
  negligible (one cycle per day).
- **Each Set-2 two-venue city:** ~1-2 h once the parameterized path exists (station ID + reconcile).
- **Each Set-2 PM-only city:** ~1 h, and its prereg needs its own single-venue wording.
- **Reversal:** every sample is an append to its own file; the read is read-only. Deleting a city's samples
  and its config row removes the city with no effect on the others — **which is only true if the
  parameterized path exists.** Ten copy-pasted scripts have no clean reversal.

## 5. Refutation (when to stop rather than expand)

- If DFW's Polymarket station cannot be identified from the venue's own rules, **stop** — do not proxy it
  with KDFW. An unidentified oracle is not a sampling problem, it is a "the question is not answerable"
  result.
- If the reconcile harness shows a **station or product change** inside a city's window (NYC's PM
  publisher already changed once between eras), that city's samples invalidate per the frozen prereg
  rather than being stitched.
- If LA/Seattle fail to reproduce the NYC design on the parameterized path — i.e. the code needs
  city-specific branches — **stop at two cities.** The pattern did not generalise, and ten cities of
  bespoke instruments is the outcome this gate exists to prevent.
