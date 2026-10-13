# Historical weather data for Polymarket & Kalshi — feasibility, measured (2026-10-12)

**Question (in-thread, 2026-10-12 21:4x CDT):** *"Can we pull historical weather data for use in
predictive use in Polymarket and Kalshi for weather bets?"*

**Status:** read-only reconnaissance + one read-only harness script. **Nothing changes in the live
path** — no rule, no size, no gate, no venue keep/cancel. We hold no Kalshi key; every lane
described here is measurement only and stays that way until approved.

---

## Verdict

**Yes — and stronger than "feasible": both venues' own settlement verdicts were reproduced from
free, keyless public data, exactly.**

| claim | measured | scope |
|---|---|---|
| Kalshi `KXHIGHNY` verdicts reproduced from GHCN-Daily Central Park | **396/396 brackets, 66/66 days** | 408 settled markets, 2026-08-05 → 09-30 |
| Polymarket "highest temp in NYC" verdicts reproduced from hourly METAR @ KLGA | **22/22 days** (11/11 in each slug era) | Oct 2025 + Oct 2026 |
| Same PM verdicts against the *wrong product* (GHCN daily, same station) | **4/9** (and **1/9** vs the other NYC station) | shows the trap below |
| Whole reconciliation runtime, keyless | **12 s** | `scripts/weather-oracle-reconcile.py` |

History depth is not the constraint: station data reaches **1869** (Central Park), archived *forecast
runs* reach **≥2022**, and both venues expose keyless price history. The constraint is on the
**venue** side (Kalshi lists `KXHIGHNY` only since Aug 2026 → 68 days of settled history; the public
trade tape rolls ~8 weeks), which is an argument for starting the clock now, not for waiting.

---

## 1. What the contracts actually settle on

| | Kalshi `KXHIGHNY` | Polymarket "highest temperature in NYC" |
|---|---|---|
| Station | **Central Park** (`CLINYC`) | **LaGuardia** (`KLGA`) |
| Publisher (today) | The Weather Company | NOAA — *"the highest reading under the `Temp` column"* |
| Publisher (2025 era) | — | Wunderground (KLGA history page) |
| Brackets | `T` = "88° or above" (floor 87), `less` = "71° or below" (cap 72), `B` = "74° to 75°" inclusive | 11 ranges: "63°F or below" … "80-81°F" … "86°F or above" |
| Cycle | opens ~10:00 ET **day before**, closes 05:00Z (01:00 ET) **day after** | lists ~2 days ahead; venue `endDate` = 08:00 ET on the target day, **but orders keep being accepted** — observed prints to 22:59 ET on the target day |
| Verdict granularity | whole °F bracket | whole °F bracket |

Kalshi's own rule text (fetched, not paraphrased):

> *"If the maximum temperature recorded at New York City (CLINYC) for Sep 19, 2026, is between
> 69-70° fahrenheit according to The Weather Company, then the market resolves to Yes."*

Polymarket's, current era:

> *"…the highest temperature recorded by NOAA at the LaGuardia Airport Station in degrees Fahrenheit
> on 5 Oct '26. The resolution source … will be information from NOAA, specifically the highest
> reading under the 'Temp' column …"*

**Two different NYC stations on two venues.** Never share an observation series across them (see trap 4).

---

## 2. Data inventory — all free, all keyless, all verified this session

| source | what it gives | depth | verified by |
|---|---|---|---|
| NCEI GHCN-Daily `USW00094728` (Central Park) | daily TMAX/TMIN, one 17 MB CSV | **1869-01-01 → 2026-10-09** (57,618 TMAX rows) | downloaded, parsed |
| NCEI GHCN-Daily `USW00014732` (LaGuardia) | daily TMAX/TMIN | 1939-10-07 → 2026-10-09 (31,780 rows) | downloaded, parsed |
| IEM ASOS archive (`asos.py`, `report_type=3`) | routine **hourly METAR** temp, whole °F | 379 days in one request; decades available | fetched LGA + NYC |
| Open-Meteo forecast API | day-0..3 daily max (GFS/ECMWF) | live | fetched (72.3 °F for 10-12 …) |
| Open-Meteo **ensemble** API | **31 GFS members** → a distribution, not a point | live | fetched (mean 74.3 °F day 0) |
| Open-Meteo **historical-forecast** API | **archived forecast runs** — "what was knowable then" | **≥2022 verified** | fetched 2022 + 2024 + 2026 windows |
| NWS `api.weather.gov` | gridpoint forecast (OKX 37,46), KLGA observations | live | fetched |
| Kalshi `trade-api/v2` (keyless) | settled markets + **hourly candlesticks** per market | 408 settled markets; ~40 candles per settled market | fetched |
| Polymarket Gamma + CLOB (keyless) | closed events, resolved brackets, **per-token price history** (1 h fidelity) | 68 points on a live market | fetched |
| our own `kalshi-tape-capture.py` | live Kalshi prints/bars — **`KXHIGHNY` is already in the allowlist** | 187 bars / 44 prints since 2026-10-12 | counted in `data/kalshi-tape/` |

**Do not build a second instrument for Kalshi weather microstructure** — the existing tape already
carries the family; the weather lane should read the same artifact.

---

## 3. The reconciliation (the part that decides this)

### 3a. Kalshi `KXHIGHNY` vs GHCN-Daily Central Park — 396/396

Derive the observed whole °F from GHCN (`TMAX` tenths of °C → °F, **nearest integer**) and test it
against every settled bracket verdict:

| convention tried | day-level | verdict-level |
|---|---|---|
| **type-aware (T: ≥floor+1, less: ≤cap−1, B: inclusive)** | **66/66** | **396/396** |
| one uniform "inclusive" rule | 54/66 | 384/396 |
| uniform "cap-exclusive" rule | 49/66 | 379/396 |

Two days (of 68) have no GHCN observation yet — they are excluded, not counted as matches.

### 3b. Polymarket NYC vs hourly METAR @ KLGA — 22/22

| candidate oracle | 2026 era (11 days, current NOAA rule) | 2025 era (11 days, Wunderground rule) |
|---|---|---|
| **hourly METAR max, LaGuardia** | **11/11** | **11/11** |
| hourly METAR max, Central Park | 4/11 | 6/11 |
| GHCN **daily** TMAX, Central Park | 1/9 | 6/11 |
| GHCN **daily** TMAX, LaGuardia | 4/9 | 6/11 |

Day-by-day (2026 era), PM bracket vs the two readings — this is the whole finding in one column:

```
2026-10-01 PM=78-79°F  hourly_LGA=78  daily_CP=76
2026-10-02 PM=86-87°F  hourly_LGA=86  daily_CP=83
2026-10-03 PM=70-71°F  hourly_LGA=71  daily_CP=70
2026-10-04 PM=62-63°F  hourly_LGA=63  daily_CP=62
2026-10-05 PM=70-71°F  hourly_LGA=70  daily_CP=68
2026-10-06 PM=62-63°F  hourly_LGA=63  daily_CP=60
2026-10-07 PM=66-67°F  hourly_LGA=67  daily_CP=65
2026-10-08 PM=76-77°F  hourly_LGA=76  daily_CP=73
2026-10-09 PM=72-73°F  hourly_LGA=73  daily_CP=70
2026-10-10 PM=68-69°F  hourly_LGA=69  daily_CP=(no obs)
2026-10-11 PM=60-61°F  hourly_LGA=61  daily_CP=(no obs)
```

**Key insight: the oracle *product* matters more than the station.** Both the station (LaGuardia)
and the publisher (NOAA) in PM's rule were correct — but a daily-summary dataset at that station
scores **4/9**, while the hourly displayed readings score **11/11**. A generic "NYC temperature"
series would have been off by 2-3 °F on most days and looked like an unexplainable venue bug.

---

## 4. Traps (each one cost a measurement in this session)

1. **Polymarket reuses year-less slugs.** `highest-temperature-in-nyc-on-october-1` is the **2025**
   market (`event.endDate = 2025-10-01`); 2026 markets carry the year
   (`…-on-october-5-2026`). Key every join on `endDate`, never on the slug — a slug-keyed probe
   silently compares last year's verdicts to this year's weather (1/9 "matches").
2. **Station ≠ product** (above). And GHCN raw `TMAX` is **tenths of °C** — reading `206.0` as °F
   gave `0/66 days` before the unit fix; that number was wrong, not the venue.
3. **Kalshi strike semantics are type-aware.** `T`-tickers read `floor+1` ("floor 87 = 88 or
   above"), `less` reads `cap−1`, `B` is inclusive. A single uniform rule scores 384/396 and looks
   like bad data.
4. **Different station per venue.** Kalshi = Central Park (`CLINYC`/The Weather Company);
   PM = LaGuardia. On 2026-10-01 those differed by **2 °F** (Central Park 76 vs LGA 78) — enough to
   cross a bracket boundary.
5. **A venue `endDate` is not a trading cutoff.** PM's NYC market carries `endDate` 12:00Z (08:00 ET)
   on the target day yet reports `acceptingOrders: true` and traded to **22:59 ET** that evening.
   (This corrects an in-flight assumption that PM closes at 8am while Kalshi trades through.)
6. **The publisher changed, the station didn't.** PM's 2025 rule names Wunderground; 2026 names NOAA.
   An oracle validated in one era can silently fail in the next — reconcile **per era**.
7. **Venue history is thin and perishable; station/forecast history is deep.** Kalshi's first
   settled `KXHIGHNY` is 2026-08-05 (68 days); the public trade tape rolls ~8 weeks. Microstructure
   not captured now cannot be recovered later — the argument for wiring the instrument now.

---

## 5. What "predictive use" would actually rest on

### The signal side is free and forward-looking
- Forecast + **31-member ensemble** (a distribution) keyless; **archived forecast runs ≥2022** let us
  reconstruct *what was knowable at hour H on day D* for every past settlement — the backtest enabler.
- **Intraday certainty curve** (hourly METAR LGA, 103 days — Jul 1 → Oct 12 2026): the day's high is
  already final at **10:00 ET 8%**, **12:00 18%**, **14:00 57%**, **16:00 91%**, **18:00 100%**; and
  within 1 °F at 14:00 **80%**, 16:00 **99%**.

### The market side is not obviously asleep (and that is the honest result)
Median last-trade price of the **eventual winner**, on the event day, over the last 14 settled days:

| ET hour | 08:00 | 12:00 | 14:00 | 15:00 | 16:00 | 17:00 | 18:00+ |
|---|---|---|---|---|---|---|---|
| winner's median price | 0.51 | 0.60 | 0.76 | 0.81 | **0.93** | 0.98 | **0.99** |
| days winner ≥ 0.90 | 0/14 | 1/14 | 4/14 | 6/14 | 9/14 | 13/14 | 14/14 |

The coarse read is **efficiency, not lag**: at 16:00 ET the outcome is 91 % physically final and the
winner trades 0.93; at 18:00 both are 100 %/0.99. A naive "buy the determined bracket" has no room —
by the time it is determined, it is priced. Any edge therefore has to live in the **distribution**
(how the brackets' mass relates to the ensemble spread and to the max-so-far), which is a
measurement question, not an assumption. That is what option B below is for.

*(Efficiency check on volume: the winner's last trading hours carry 4-11 k contracts — these quotes
are real, not stale.)*

---

## 6. Options (recommendations-only — nothing here runs until you say so)

**A · Read-only harness — SHIPPED (no approval needed).**
`scripts/weather-oracle-reconcile.py` reproduces §3 keylessly in 12 s: Kalshi↔Central Park,
PM↔hourly KLGA, the wrong-product controls, forecast/ensemble/archive availability, venue
price-history probes. Nothing is wired to the live path; it writes nothing outside `/tmp`.

**B · RECOMMENDED — pre-registered "nowcast vs price" calibration study.** *(measurement only)*
Instrument reads the data we already have (Kalshi tape + candlesticks, PM prices-history, IEM METAR,
archived forecast runs) and tests two falsifiable questions:
1. At ET hours where the day's high is already final (16:00+, 91-100 %), does either venue leave
   **residual mass in physically dead brackets** (winning bracket bid < 1.00 with >0 edge after fees)?
2. Pre-14:00: is the bracket distribution **flatter or sharper than the ensemble spread** (i.e. is
   the ensemble's spread already priced, or systematically ignored)?
- Effort: ~1 day to instrument; ~3-4 weeks of forward samples (venue history is thin — Kalshi 68 days
  back, PM's current-rule era ~11 days). Risk: none (no orders, no keys).
- Gate: hypothesis + falsifier frozen **before** the first sample; verdict = "no claim" if the
  sample doesn't clear.

**C · Breadth expansion — after B, not before.** PM carries **96 distinct city/side daily-temp
families** (~224 open markets, **$1.58 M 24 h volume** across weather-tagged events) and Kalshi has
**422 series** in *Climate and Weather*. The harness generalizes, but each city needs its own station
product identified the way §3 did — that is where the work multiplies. Do not start it on faith.

**D · Live lane — explicitly not now.** No sizing, no venue decision, no order path until B (or a
sibling study) produces a signed edge that clears fees. Kalshi stays paper regardless: we hold no key.

**Overridable flags** (one line each — say the word and I change it):

- **City universe** = *NYC only*. → change: add cities to the study's universe list (B's scope grows).
- **PM era basis** = *2026 rule only (~11 days)*. → change: include the 2025 Wunderground era by
  handling the year-less slugs (more samples, oracle product must be re-validated for that era).
- **Venue scope** = *Kalshi + Polymarket*. → change: drop Kalshi to halve the instrument work, at the
  cost of the only venue where we can see through-the-day microstructure.

---

## 7. Reproduce

```bash
python3 scripts/weather-oracle-reconcile.py --json /tmp/weather-recon/rep.json   # 12 s, keyless
```

Keyless endpoints used (no auth anywhere): `ncei.noaa.gov/…/ghcn-daily/access/USW00094728.csv`,
`mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=LGA&report_type=3`,
`api.open-meteo.com/v1/forecast`, `ensemble-api.open-meteo.com/v1/ensemble`,
`historical-forecast-api.open-meteo.com/v1/forecast`,
`api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXHIGHNY&status=settled` and
`…/series/KXHIGHNY/markets/<ticker>/candlesticks`, `gamma-api.polymarket.com/events?slug=…`,
`clob.polymarket.com/prices-history?market=<tokenId>`.

*Caveats, stated so the numbers are not over-read:* Kalshi reconciliation is bracket-level (not
degree-level) over 66 days in Aug-Sep 2026; the PM result is 22 days in two 11-day October windows,
NYC only; the intraday certainty curve is 103 days at LGA; the winner-price path is n=14 settled days.
Wider claims need the samples option B collects.
