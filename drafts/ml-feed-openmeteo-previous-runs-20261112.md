# ML feed REC 1 re-read — Open-Meteo previous-runs, extended to 108 settled days (2026-11-12)

**Status:** Lane A proposal. **Nothing applied.** No rule, size, gate, booking, threshold or roadmap
gate touched; no `scripts/apply-v*.ts` run; no write to `prisma/dev.db`; nothing merged. The feed was
only READ (keyless). The card's apply step remains the operator's.
**Card:** `t_4605f399` / approvals `apr-ml-feed-openmeteo-previous-runs`, re-approved 2026-11-12T16:45Z.
**Prior proposal:** `drafts/ml-feed-openmeteo-previous-runs-20261029.md` — 94 settled days,
**REFUTED as specified**. This document does not re-derive that; it extends the window by 14 settled
days and answers the two questions the 10-29 draft explicitly left open.
**Every number below came out of the two runs recorded in §9 today.** None is carried over.

---

## 0. Verdict first

**Do not add the as-issued NWP lead-0..2 daily extreme as a wx2 feature. The card's decision rule fails
again on the extended window, and the two open questions both close against the feature.**

| question | measured today | result |
|---|---|---|
| card gate: ≥5pp on ≥20 settled days, time-ordered OOS, refuted if <2pp or sign flip | lead-1 **+1.25pp / +7.80pp** across halves; lead-2 **−0.12 / +6.74** (108 settled days) | **REFUTED** (both triggers)
| prior draft's Option B slice (NYC, ≤10:00, live brackets, day-clustered CI) | PM NYC **+7.54pp** [+3.13,+10.32], 28 city-days; Kalshi NYC **+1.08pp** [−4.93,+6.41] | PM clears it, Kalshi does not
| same slice vs the **venue's own ladder** | market **92.61%** vs best forecast rule **86.53%** → **−6.08pp** [−9.7,−2.6] | **no edge over the price**
| next-day cycle vs climatology (the draft's stated revival condition) | **+17.42pp** on 101 days, sign holds in both halves | **condition MET**
| next-day cycle vs the **venue's own ladder** | market **92.34%** vs forecast **86.18%** → **−6.16pp** [−8.4,−3.6] | **no edge over the price**
| contested brackets only (mid 0.20–0.80, where direction has information) | market **67.19%** vs forecast **49.10%** → **−18.09pp** [−27.8,−7.0] | the gap is widest where it would have to pay

**One sentence:** the feed is a real, leak-free forecast substrate that beats a thermometer and loses
to the book — and on a trading lane only the second comparison decides.

---

## 1. What was measured, on what

- **Window:** fetch 2026-07-25 → 2026-11-11; **108 settled days** after the wx2 settle filter
  (≥20 local hourly METAR obs per day, coverage through 21:00 local), last settled day **2026-11-09**.
  The 10-29 read had 94 days ending 2026-10-26 — 14 new days, including a full month of
  sampler history the earlier read did not have.
- **Stations, never pooled across venues** (pinned by wx1/wx2): PM NYC = KLGA, Kalshi NYC = Central
  Park (`NYC`), PM DFW = KDAL, Kalshi DFW = DFW airport. Settled maximum from routine hourly METAR
  (IEM ASOS `report_type=3`) — the oracle product the wx2 sampler pins.
- **Leak rule, unchanged and re-checked:** the only leak-free leads are
  `temperature_2m_previous_day1..7_<model>`; the unsuffixed `temperature_2m` is the latest run and is
  an *analysis* for past hours. Spec check today on PM NYC: MAE vs the settled max is **1.95 °F** for
  `previous_day1` and **1.22 °F** for the latest run — the second number is the leak, and it is
  excluded from every table here.
- **Models:** `gfs_seamless`, `ecmwf_ifs025`, `icon_seamless` (median of the three); bias is a
  **causal trailing-14-day** mean error per station × lead, so no scored day ever sees its own outcome.
- **Data used for the price side:** the wx2 sampler's own rows
  (`data/weather-nowcast-samples{,-dfw}.jsonl`) — 20,595 priced bracket rows with a settled label,
  11,282 of them same-day cycles. Its captured `forecast_F` is the live Open-Meteo forecast **as of the
  sample** (leak-free by construction for a same-day decision, and not backfillable — which is exactly
  why the sampler exists).

---

## 2. Panel A — the card's own test, 108 settled days × 4 stations

Direction accuracy on **live** thresholds (max-so-far+1 … +12), causal 14-day fit, against the baseline
that matters (**obs + station diurnal curve**, i.e. no forecast input at all):

| half | hour | persist | clim (baseline) | lead-1 | Δ1 | lead-2 | Δ2 |
|---|---|---|---|---|---|---|---|
| H1 | ALL | 58.25 | **90.70** | 91.95 | **+1.25** | 90.58 | −0.12 |
| H1 | 06 | 18.98 | 84.99 | 91.23 | +6.24 | 89.43 | +4.43 |
| H1 | 09 | 21.72 | 86.65 | 90.84 | +4.19 | 88.84 | +2.19 |
| H1 | 12 | 58.87 | 88.27 | 87.78 | −0.50 | 85.38 | −2.89 |
| H1 | 15 | 91.78 | 93.71 | 91.35 | −2.36 | 90.96 | −2.75 |
| H1 | 18 | 99.88 | 99.88 | 98.55 | −1.34 | 98.31 | −1.57 |
| H2 | ALL | 64.36 | 86.13 | 93.94 | **+7.80** | 92.88 | **+6.74** |
| H2 | 06 | 28.32 | 74.58 | 93.90 | +19.33 | 92.09 | +17.52 |
| H2 | 09 | 31.44 | 75.00 | 93.17 | +18.17 | 91.59 | +16.59 |
| H2 | 12 | 66.94 | 85.38 | 90.16 | +4.78 | 87.77 | +2.39 |
| H2 | 15 | 95.22 | 95.83 | 93.29 | −2.55 | 93.67 | −2.16 |
| H2 | 18 | 99.88 | 99.88 | 99.15 | −0.73 | 99.27 | −0.62 |

n = 12,960 threshold rows per half; 2,160 (station, day, hour) rows; 432 station-days.

**Both of the card's refutation triggers fire**, exactly as on 10-29: lead-1 improves the baseline by
**+1.25pp** in the first half (<2pp) and lead-2 **flips sign across hours within a half** (−2.89 at
noon, +16.59 at 09:00). The half-to-half instability is the finding, not noise to be averaged away:
the morning effect is large where the observation anchor is uninformative and negative from noon on,
when the day's peak is already in the thermometer.

---

## 3. Panel B — the real ladders, extended: 88 city-days, 12,168 live brackets

16,161 priced bracket rows joined to their settled label, 12,168 still undecided at sample time by
monotonicity (the wx2 prereg rule), 88 station-days:

| predictor | live bracket direction |
|---|---|
| `persist(Mh)` — obs anchor only | **86.42%** (n=12,168) |
| `max(Mh, ensemble mean)` | 86.90% |
| `forecast_F`, raw | 83.25% |
| `max(Mh, F)`, raw | 84.18% |
| `forecast_F`, causal-debiased | 84.94% |
| `max(Mh, F)`, causal-debiased | **87.80%** |

By sample-hour band (`max(Mh, F_deb)` − `persist`):

| band | n | persist | forecast rule | Δ |
|---|---|---|---|---|
| 00–08 | 4,275 | 80.21 | 85.96 | **+5.75pp** |
| 08–12 | 2,447 | 79.73 | 86.23 | **+6.50pp** |
| 12–16 | 1,947 | 84.80 | 86.75 | +1.95pp |
| 16–24 | 3,499 | 99.60 | 91.74 | **−7.86pp** |

Recorded mean(F − A): pm_nyc +0.12, kalshi_nyc **+1.85**, pm_dfw +0.23, kalshi_dfw +0.50 °F — the
Kalshi NYC grid cell is not the station, which is why any adoption needs the rolling per-station bias
this measurement uses and why a frozen constant does not transfer.

**Shape, unchanged from 10-29 and now firmer:** +1.4pp pooled, +5.8/+6.5pp before noon, **−7.9pp after
16:00**. "Add NWP as a wx2 feature" is ill-posed as written — the only defensible form is a pre-noon
prior, and even that has to beat something better than a thermometer (§5).

---

## 4. The prior draft's Option B gate, executed (new this read)

The 10-29 draft said its narrow re-scope "cannot pass on the 16 NYC settled days available today — it
needs the sample to run into December". It has now run to 2026-11-09. Executing exactly that shape —
NYC stations, sample hour ≤10:00, live brackets, forecast = captured-as-of debiased on a trailing
14-day window, anchor = max-so-far:

| station | city-days | n | persist | forecast rule | Δ | day-clustered 95% CI | H1 | H2 |
|---|---|---|---|---|---|---|---|---|
| **pm_nyc** | 28 | 2,202 | 82.38 | **89.92** | **+7.54pp** | **[+3.13, +10.32]** | +6.48 | +8.56 |
| kalshi_nyc | 28 | 1,383 | 80.04 | 81.13 | +1.08pp | [−4.93, +6.41] | −0.59 | +2.70 |

**Polymarket NYC clears the letter of the gate**: ≥5pp, CI lower bound above +2pp, ≥20 settled
city-days, same sign in both halves. Kalshi NYC fails it (point estimate under 2pp, CI straddles zero,
H1 negative). Per station, all hours, the effect is concentrated where it was measured:
pm_nyc **+2.20pp** all-hours [−2.84,+4.61] vs **+7.54pp** ≤10:00 [+3.13,+10.32], and **−9.85pp** at
16:00+ [−16.19,−5.92]; kalshi_nyc **−2.61pp** all-hours, **+1.08pp** ≤10:00, **−8.22pp** at 16:00+.

That is a real, stable, sign-consistent result — against `persist(Mh)`, which before 10:00 is a
thermometer reading of the coldest hour of the day. §5 is the comparison that decides whether it is
worth anything.

---

## 5. The comparator that matters — the venue's own ladder (new this read)

Same rows, same runs, same debias; every priced bracket is a YES/NO call for all four predictors
(`mkt` = the bracket's mid > 0.5). This is symmetric — each predictor is scored on the same brackets —
and it is the only baseline that can generate a trade.

**Same-day morning (≤10:00), live brackets — 3,585 rows, 28 distinct days:**

| scope | market | forecast | max(Mh,F_deb) | persist | Δ vs market |
|---|---|---|---|---|---|
| ALL | **92.61%** | 85.44% | 86.53% | 81.48% | **−6.08pp** [−9.7,−2.6] |
| pm_nyc | **95.37%** | 89.10% | 89.92% | 82.38% | −5.45pp [−8.7,−2.1] |
| kalshi_nyc | **88.21%** | 79.61% | 81.13% | 80.04% | −7.09pp [−13.4,−0.7] |

**Contested brackets only (mid 0.20–0.80 — where the venue is genuinely unsure), same slice:**

| scope | rows | market | forecast | max(Mh,F_deb) | persist | Δ vs market |
|---|---|---|---|---|---|---|
| ALL | 754 | **67.77%** | 49.87% | 50.53% | 53.58% | **−17.24pp** [−33.3,−5.9] |
| pm_nyc | 348 | **70.69%** | 52.59% | 52.59% | 45.98% | −18.10pp [−42.9,−3.5] |
| kalshi_nyc | 406 | **65.27%** | 47.54% | 48.77% | 60.10% | −16.50pp [−35.0,+3.3] |

**Reading:** the +7.54pp in §4 is a gain over an obs-only anchor, and it does not survive contact with
the price. On the very same ladders the market's own direction calls are ~6pp better on all brackets
and **17–18pp better on the only brackets where a direction call has information**. The feature
improves the bot's *estimate of the weather* and not its *view of the market* — and wx2 is priced
against the market, not against a thermometer.

---

## 6. Next-day cycle — the prior draft's revival condition, met on the letter, wrong in substance

The 10-29 draft named its own revival path: *"if a next-day-cycle sample (where no observation anchor
exists) shows ≥5pp over the diurnal-only rule on ≥20 settled days, the card is revived for that use
case."* Both halves were measured.

**(a) vs climatology — 404 station-days, 101 days, time-ordered split 2026-09-20:**

| scope | n | clim | lead-1 | Δ1 | lead-2 | Δ2 |
|---|---|---|---|---|---|---|
| ALL | 5,252 | 73.71 | **91.13** | **+17.42** | 89.22 | +15.52 |
| H1 | 2,600 | 80.50 | 89.62 | +9.12 | 87.08 | +6.58 |
| H2 | 2,652 | 67.04 | 92.61 | +25.57 | 91.33 | +24.28 |
| pm_nyc | 1,313 | 69.69 | 92.46 | **+22.77** | — | — |
| kalshi_nyc | 1,313 | 71.29 | 90.63 | +19.35 | — | — |

Substrate MAE on the daily max: lead-1 **1.60 °F**, lead-2 **2.01 °F**, climatology **4.22 °F**.
Sign holds in both halves, n is four times the floor. **The revival condition is met.**

**(b) vs the venue's own ladder on the same next-day cycles — 9,313 priced bracket rows, 28 days:**

| scope | market | forecast | Δ vs market | contested (0.20–0.80) | market | forecast | Δ |
|---|---|---|---|---|---|---|---|
| ALL | **92.34%** | 86.18% | **−6.16pp** [−8.4,−3.6] | 1,990 | **67.19%** | 49.10% | **−18.09pp** [−27.8,−7.0] |
| pm_nyc | **94.33%** | 88.30% | −6.03pp [−8.2,−3.9] | 1,284 | **69.63%** | 48.21% | −21.42pp [−33.7,−10.2] |
| kalshi_nyc | **86.16%** | 79.58% | −6.59pp [−12.1,+0.0] | 706 | **62.75%** | 50.71% | −12.04pp [−27.3,+4.1] |

**So the revival condition was written against the wrong baseline.** Climatology is not the
competition; on a trading lane the competition is the price, and the market already prices the
forecast (and better models than ours — NBM/GFS-MOS, high-res local grids) into a ladder that beats
our point forecast by 6pp, and by 18pp where the ladder is actually uncertain. "Beats a thermometer"
and "beats a climatology" are both true and both irrelevant.

---

## 7. Reality checks (what these numbers do and do not say)

1. **Direction accuracy is not PnL.** No price, size, fill, fee or exit is modelled anywhere here. A
   predictor can be more directionally right and still lose money; it cannot be less right and win
   through information alone. This read only removes candidates.
2. **The market comparison is the strong one, and its metric is coarse.** A bracket's YES/NO call from
   `mid > 0.5` throws away the price level; the contested-band table (0.20–0.80) is the part that is
   hard to dismiss, and its pooled CI excludes zero on both cycles. It is still not a fee-adjusted
   edge — wx2's frozen gate is the only thing that can put weather into sizing, and it is untouched.
3. **DFW is thin and half-blind.** The DFW city table entered the sampler 2026-10-26, so price-side
   DFW has ~14 days; the Kalshi NYC CI at 0.20–0.80 straddles zero. Nothing in this document rests on
   DFW.
4. **Lead 0 cannot be backfilled.** Same-day "as-of" evidence exists only where the sampler captured a
   live forecast (§4, §5). Any future backtest that builds lead 0 from the previous-runs API's
   unsuffixed variable is measuring the analysis (1.22 °F MAE, 95.65% direction accuracy in the
   earlier read) and will look spectacular and be worthless.
5. **Bias transfer is the fragile component.** Cross-half transfer of a frozen bias flipped sign in the
   earlier read; a rolling 14-day per-station bias is what every table here uses, and it is also why
   kalshi_nyc carries +1.85 °F of recorded error — the grid cell is not Central Park.
6. **Polymarket's fee-era void from wx2 still applies to any *price* claim** from this sampler. Nothing
   here makes a price claim; direction accuracy is fee-insensitive. It does not lift that void.
7. **This card's own gate is about a feature, not a trade.** Even a pass in §4 would not justify a
   rule; it would justify a shadow test with its own before/after — which is §8 Option B, and which
   §5 argues against starting.

---

## 8. What the operator decides

**Option A (recommended) — close `ml-feed-openmeteo-previous-runs` as REFUTED, for the second time,
on the extended window.** No feature, no code path, no rule. Keep the API in the feed catalogue: it is
the correct leak-free substrate, it is already paid for (free), and it is the right input for any
future **city breadth** work (wx3) where the venue ladder is thinner than NYC's. Nothing to apply —
the operator's step is bookkeeping: mark the card refuted and replace the revival condition.

Suggested roadmap note replacing the 10-29 result text:

> RE-READ 2026-11-12 on 108 settled days × 4 stations (was 94) + 12,168 live bracket rows (88
> city-days) + 20,595 priced rows: REFUTED again, both triggers (lead-1 +1.25/+7.80pp across halves,
> lead-2 −0.12/+6.74). The 10-29 draft's Option B slice now has enough days to run: PM NYC ≤10:00
> clears it (+7.54pp over persist(Mh), CI [+3.13,+10.32], 28 city-days; Kalshi NYC +1.08 fails), and
> the next-day revival condition is met vs climatology (+17.42pp, 101 days) — but on the venues' own
> ladders the market beats the forecast by 6.16pp on next-day cycles and 6.08pp in the same-day
> morning, widening to 18.09 / 17.24pp on contested brackets (mid 0.20–0.80). The feed beats a
> thermometer and loses to the book. Revival condition rewritten to a price-based comparator.

**Option B — authorise only the narrow morning shadow (still shadow-only, not recommended).** If he
wants the pm_nyc morning result carried forward despite §5, the gate must be rewritten against the
price, because the old wording ("beats persist(Mh)") has already passed and means nothing:

> shadow only; NYC/PM only; same-day, sample hour ≤10:00; **must beat the venue's own ladder** on
> contested brackets (mid 0.20–0.80) by ≥5pp over ≥20 settled city-days with a day-clustered 95% CI
> lower bound > 0, and must not move the 16:00+ band by more than ±1pp; refuted if the point delta is
> <2pp or the two day-halves disagree in sign. **As of today it fails this gate by −17.24pp**, so
> authorising it means authorising a test we expect to fail — its only value is a written null.

**Option C — retire the feed from the ML feature lane entirely, keep the fetcher.** Same as A but also
delete the "pending" status from the ML feed catalogue so the next scout run does not re-propose it.
The API stays in `scripts/ml-openmeteo-previous-runs-measure.py` for city work and for the
next-day-cycle substrate if wx3 ever starts.

**What I would not do:** adopt the lead-0..2 daily extreme as a wx2 feature; adopt the
"morning-only, NYC-only" variant on the strength of §4 alone; or re-open this card a third time without
a price-based gate.

---

## 9. Reproduce

```bash
# 1) keyless fetch (4 stations x 2 requests) + the card's own Panel A / Panel B read
python3 scripts/ml-openmeteo-previous-runs-measure.py --fetch \
    --cache ~/.hermes/cache/scratch/rec1-20261112 --start 2026-07-25 --end 2026-11-11

# 2) the four tests added by this read (T1 gate shape, T2 by-station, T3 next-day vs climatology,
#    T4/T4c/T5/T5c vs the venue's own ladders)
python3 scripts/ml-openmeteo-previous-runs-reread.py --cache ~/.hermes/cache/scratch/rec1-20261112
```

- New this read: `scripts/ml-openmeteo-previous-runs-reread.py` (read-only, writes stdout only).
  Unchanged: `scripts/ml-openmeteo-previous-runs-measure.py` (the fetcher + the card's own scoring).
- Run logs from today: `~/.hermes/cache/scratch/rec1-panelA-20261112.txt`,
  `~/.hermes/cache/scratch/rec1-reread-20261112.txt`.
- Sources, all keyless: `previous-runs-api.open-meteo.com/v1/forecast`,
  `mesonet.agron.iastate.edu/cgi-bin/request/asos.py?report_type=3`, and the sampler's own
  `data/weather-nowcast-samples{,-dfw}.jsonl`.

**What was NOT changed:** no `apply-v*.ts`; no `prisma/dev.db` write; no rule/size/exposure/risk gate;
no paper trade, PnL or dashboard number; `wx2`'s frozen pre-registration untouched; `wx3`/`wx4` not
started; the sampler, the read script and the roadmap card are untouched by this run. The only writes
this card produced are this draft and one read-only analysis script.

---

*Method note, stated because the earlier read was explicit about it: the two comparisons that decide
this card are (i) the card's own gate (Panel A, unchanged metric) and (ii) forecast-vs-ladder on the
same runs (T4/T5). Everything else here is supporting detail. If only one number survives, it is
−17.24pp: on the brackets where the venue is unsure, the venue is right 67.77% of the time and the
forecast 49.87%.*
