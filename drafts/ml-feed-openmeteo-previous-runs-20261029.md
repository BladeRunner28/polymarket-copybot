# ML feed REC 1 — Open-Meteo previous-runs NWP as a weather feature — MEASURED, REFUTED as specified

**Status:** Lane A proposal. Nothing applied: no rule, size, gate, booking or threshold touched, no
`apply-v*.ts` run, no write to `prisma/dev.db`. The feed itself was only READ (keyless).
**Written:** 2026-10-29. Every number below came out of the run recorded in §7 today; none is carried
over from the roadmap note or from the upstream repo.
**Roadmap card:** `ml-feed-openmeteo-previous-runs` (tagged `awaiting-approval`).

---

## 0. Verdict first

**Do not add the as-issued NWP lead-0..2 daily extreme as a wx2 feature.** The card's own decision rule
is not met, and its refutation condition fires:

| gate (from the card) | measured | result |
|---|---|---|
| ship only if settlement-direction accuracy improves **≥5pp** over baseline | +0.39pp on the first half, +7.53pp on the second (lead 1); −0.89pp / +6.24pp (lead 2) | **fails half 1** |
| **≥20 settled days**, time-ordered OOS | 94 settled days × 4 settlement stations (376 station-days), 47/47 split | passes |
| **refuted if delta <2pp or sign flips across halves** | lead-2 delta flips sign (+/−) and lead-1 is +0.39pp (<2pp) on half 1 | **REFUTED** |

A narrower claim survives the measurement and is worth one cheap, pre-registered test (§6): the feed
adds direction accuracy **only in the morning window (≤ ~10:00 local), only on NYC stations**, and only
before the day's maximum has formed. That is a 2-hour slice of one city, not a lead-0..2 feature, and it
is not worth a live rule until it clears its own gate on the sampler's own data.

---

## 1. What the transferable asset actually is (probed live today, not assumed)

`https://previous-runs-api.open-meteo.com/v1/forecast` is keyless and returns the forecast **as issued**:

- `hourly=temperature_2m_previous_day1..7_<model>` = the value forecast N days earlier for that hour.
  This is genuinely leak-free; it is what makes a weather backtest honest.
- **`hourly=temperature_2m` (no suffix) is NOT a forecast for a past hour — it is the LATEST run.** For
  past timestamps that is an analysis that has assimilated the observations. Building "lead 0" out of it
  backtests a forecast that is 95.65% accurate on direction, i.e. it leaks the answer; measured here and
  then **discarded from the evidence**. Leak-free leads are `previous_day1..7` only.
- `daily=` variables are rejected for previous runs (`Invalid value: Cannot initialize
  ForecastVariableDaily from invalid String value temperature_2m_max_previous_day1`) — a daily extreme
  must be aggregated from the hourly series, which is what this measurement does.
- History available back to at least 2026-07-20 on `gfs_seamless`, `ecmwf_ifs025`, `icon_seamless`.

So the roadmap note's "leads 0-5 in one keyless call" is right about **leads ≥1**. The "lead 0 as of the
decision time" case cannot be backfilled; the only leak-free lead-0 evidence is the live sampler's own
captured `context.forecast_F` — that is Panel B.

---

## 2. Definitions (pinned before the numbers, so the draft cannot drift from the code)

- **Stations:** the four the wx1/wx2 cards pinned, never pooled across venues — PM NYC = KLGA,
  Kalshi NYC = Central Park (IEM `NYC`, proxy for CLINYC/TWC), PM DFW = KDAL, Kalshi DFW = DFW airport.
- **A** = the settled daily maximum °F from routine hourly METAR (IEM ASOS `report_type=3`) — the same
  product the sampler pins as the oracle basis. A day counts as settled only with ≥20 local hourly
  observations and coverage through 21:00 local.
- **Mh** = max observed temperature on that day strictly before the decision hour h.
- **LIVE thresholds** = integer °F thresholds `Mh+1 .. Mh+12`. A threshold ≤ Mh is already decided by
  monotonicity, and every predictor scores identically on it — including it would manufacture accuracy.
- **Direction accuracy** = share of (station, day, h, threshold) rows where `sign(pred − thr)` =
  `sign(A − thr)`.
- **Predictors:**
  - `persist` — pred = Mh (the day's max is what we have seen).
  - `clim` — pred = Mh + median(A − Mh | station, hour), i.e. the station's own diurnal curve. **This is
    the baseline that matters**: it is obs-only, has no forecast input, and is the strongest thing the
    lane can do today without any new feed. Persistence alone is a strawman (it says at 06:00 that the
    day's high is the 05:00 temperature) and beating it means nothing.
  - `nwp1` / `nwp2` — pred = max(Mh, as-issued remaining-day peak + bias), lead 1 and lead 2, bias =
    mean(A − fc) over a **causal trailing 14-day window** (only days strictly before the scored day), per
    station × lead. The forecast can never un-see an observation, hence the `max(Mh, ·)`.
- **Split:** day-ordered, 47 days fit / 47 days scored. Two implementations were run and both are
  reported: a stricter one that fits the *other* half's parameters, and the causal trailing-14-day one
  (the design a production version would use). Where they disagree, the causal one is quoted.

---

## 3. Panel A — 94 settled days, 4 settlement stations, as-issued leads 1 and 2

Direction accuracy on live thresholds, causal 14-day fit, `d = nwp − clim`:

| half | hour | persist | clim | nwp1 | d1 | nwp2 | d2 |
|---|---|---|---|---|---|---|---|
| H1 (07-25→09-16) | ALL | 58.17 | **90.90** | 91.29 | +0.39 | 90.01 | −0.89 |
| H1 | 06 | 18.57 | 85.28 | 90.44 | **+5.16** | 88.77 | +3.48 |
| H1 | 09 | 21.41 | 86.97 | 89.99 | +3.02 | 88.09 | +1.12 |
| H1 | 12 | 59.40 | 88.61 | 86.87 | −1.74 | 84.65 | −3.96 |
| H1 | 15 | 91.62 | 93.75 | 90.81 | −2.94 | 90.35 | −3.40 |
| H1 | 18 | 99.87 | 99.87 | 98.32 | −1.54 | 98.19 | −1.68 |
| H2 (09-17→10-26) | ALL | 62.28 | 86.79 | 94.32 | **+7.53** | 93.03 | **+6.24** |
| H2 | 06 | 26.51 | 76.33 | 94.28 | **+17.95** | 92.42 | +16.09 |
| H2 | 09 | 28.41 | 76.73 | 94.10 | **+17.38** | 92.33 | +15.60 |
| H2 | 12 | 62.54 | 85.95 | 90.74 | +4.79 | 87.94 | +1.99 |
| H2 | 15 | 94.06 | 95.08 | 93.22 | −1.86 | 93.31 | −1.77 |
| H2 | 18 | 99.87 | 99.87 | 99.25 | −0.62 | 99.16 | −0.71 |

Core decision window (hours 09/12/15), per station, `d` vs clim:

| scope | H1 nwp1 | H1 nwp2 | H2 nwp1 | H2 nwp2 |
|---|---|---|---|---|
| pm_nyc | +0.20 | −1.25 | **+11.64** | +10.17 |
| kalshi_nyc | +0.17 | −1.46 | **+8.39** | +8.33 |
| pm_dfw | −0.98 | −2.37 | +3.25 | +1.65 |
| kalshi_dfw | −1.61 | −3.24 | +3.78 | +0.95 |
| ALL | −0.55 | −2.08 | +6.77 | +5.27 |

Stricter cross-half transfer (parameters fitted on the other half): nwp1 −3.05pp / +5.43pp, nwp2
−5.63pp / +3.33pp — **both flip sign**. Substrate MAE for the lead-1 remaining-day peak: 2.04 °F (H1) and
1.01 °F (H2) vs the diurnal-climate rule's 1.21 °F / 1.94 °F. The feed's absolute skill is real; its
*incremental* value over a good obs-only rule is not stable.

**Reading:** the sign of the answer depends on the half. H2's +17pp at 06:00/09:00 is the honest size of
the effect where it exists — early morning, before the max has formed, the observation anchor is
uninformative and a 24-hour-old forecast is a large improvement over a monthly-mean diurnal curve. From
noon onward the as-issued forecast is *worse* than the obs-only rule in every half, every station: at
15:00 the day's peak is usually already in the thermometer, and a forecast that keeps adding +1-3 °F of
expected rise makes calls the monotone truth disagrees with.

---

## 4. Panel B — the real venue ladders (in situ, leak-free lead 0)

The sampler's own rows: every bracket it actually saw, at the hour it saw it, judged against the settled
station maximum; the forecast used is the sampler's captured `context.forecast_F` (fetched live at sample
time) with a causal debias. 5,451 bracket rows with a settled label, 4,023 of them still undecided at
sample time (monotonicity-live), 16 settled city-days (15 NYC + 1 DFW — DFW only entered the sampler on
2026-10-26, so it is one day, not 15).

| predictor | live bracket direction |
|---|---|
| `persist(Mh)` — obs anchor only | **86.38%** (n=4,023) |
| `max(Mh, ensemble mean)` | 86.53% |
| `event forecast_F`, causal-debiased | 82.00% |
| `max(Mh, F)` causal-debiased | 83.15% |
| `event forecast_F`, raw | 80.21% |
| `max(Mh, F)`, raw | 80.34% |

By sample-hour band (`max(Mh, F_debiased)` − `persist`):

| band | n | persist | max(Mh,F_deb) | delta |
|---|---|---|---|---|
| 00-08 | 1,338 | 80.87 | 84.01 | **+3.14pp** |
| 08-12 | 814 | 80.59 | 84.52 | **+3.93pp** |
| 12-16 | 654 | 81.65 | 82.26 | +0.61pp |
| 16-24 | 1,217 | 98.85 | 81.76 | **−17.09pp** |

Recorded forecast bias vs the settled maximum: Kalshi NYC **+2.27 °F**, PM DFW +1.20, Kalshi DFW +1.20,
PM NYC +0.08. On the real ladders the same shape as Panel A appears: help in the morning, active harm
after 16:00 — and nothing in the aggregate.

---

## 5. Reality checks (what these numbers do and do not claim)

1. **The +17pp morning number is not a 17pp business gain.** Threshold rows are not trades. The metric
   weights 12 live thresholds per decision equally; a real edge exists only where the venue prices the
   bracket wrong, which is the wx2 card's frozen gate, not this one. This card was scoped to the feed,
   and on the feed's own terms it fails its gate.
2. **The feature can only help where the max has not formed.** Both panels agree: ≥16:00 local, the obs
   anchor is 98.9% accurate on live brackets and any forecast that pushes the prediction above `Mh`
   loses. That is why "add NWP as a wx2 feature" is ill-posed: the useful form is a *pre-noon* prior, not
   a global feature.
3. **Bias transfer is the fragile part, not the data.** A single constant per station does not survive a
   season: cross-half transfer flips the sign of the delta (Panel A, stricter implementation), and the
   live sampler's forecast carries a +2.27 °F bias on the Kalshi NYC proxy because the grid cell is not
   the station. Any adoption needs a rolling, per-station, per-lead bias — which this measurement used,
   and which is exactly why the causal result is the one quoted.
4. **Next-day cycles are unmeasured here.** The sampler records no observation anchor for tomorrow's
   cycle, so Panel B could only judge same-day cycles. The place a forecast is *logically* indispensable
   is the next-day bracket, where `Mh = 0` and the diurnal rule is the only alternative — that question
   is open, and it is not evidence for the card as written.
5. **All four panels are measurement, not proof of tradable edge.** No price was used, no fill was
   modelled, no fee was applied. Settlement direction is necessary, not sufficient.

---

## 6. What I recommend the operator decide

**Option A (recommended) — close the card as REFUTED.** Do not add a lead-0..2 daily-extreme feature.
Keep the API in the feed catalogue (it is the correct leak-free substrate and will matter for next-day
cycles), but record that its incremental value over an obs+diurnal rule on same-day brackets is +0.39pp
in one half and −0.89 to +7.53pp in the other. No code change, no rule change.
**Refutation of this recommendation:** if a *next-day-cycle* sample (where no observation anchor exists)
shows ≥5pp over the diurnal-only rule on ≥20 settled days, the card is revived for that use case.

**Option B — authorise only the narrow re-scope, still shadow-only.** A single pre-registered test:
NYC stations only, local hours ≤ 10:00, same-day cycles, forecast = as-issued lead-1 debiased on a
trailing 14-day window, obs anchor = `Mh`. **Ship only if** direction accuracy on live brackets beats
`persist(Mh)` by **≥5pp** over **≥20 settled city-days** with a day-clustered bootstrap 95% CI lower
bound above +2pp; **refuted if** the point delta is **<2pp**, or the two day-halves disagree in sign, or
the 16:00+ band (where it should be inert) moves by more than ±1pp. This cannot pass on the 16 NYC
settled days available today — it needs the sample to run into December, so it costs a calendar month,
not a half-day.

Either way the feature stays out of the live lane: `wx2`'s frozen pre-registration is untouched by this
card and remains the only gate that can put weather into sizing.

---

## 7. Reproduction

- Fetcher: `scripts/ml-openmeteo-previous-runs-measure.py` (uncommitted, present in both the worktree
  and the live tree) — `python3 scripts/ml-openmeteo-previous-runs-measure.py --fetch` caches every HTTP
  response (2 requests per settlement station), then `--analyze` prints the tables in §3-§4 exactly as
  quoted. Keyless; writes only to its cache dir.
- Verified today: `python3 -m py_compile scripts/ml-openmeteo-previous-runs-measure.py` → OK;
  `npx tsc --noEmit` in the worktree → exit 0. No TypeScript, no rule and no DB row was touched by this
  card, so `vitest` was not run (nothing it covers changed).
- Window: 2026-07-25 → 2026-10-28 as-issued; 94 days pass the settled-day filter (2026-07-25 → 2026-10-26).
- Sources: Open-Meteo previous-runs (`gfs_seamless`, `ecmwf_ifs025`, `icon_seamless`), IEM ASOS
  `report_type=3`, and the sampler's own `data/weather-nowcast-samples{,-dfw}.jsonl` for Panel B.
- The contaminated lead-0 variant (`temperature_2m` = latest run) is retained in the script behind a
  `--show-leaky-lead0` flag with its 95.65% number, purely so the next reader cannot mistake it for
  evidence.
