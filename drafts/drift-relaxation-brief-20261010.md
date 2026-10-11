# Drift relaxation — pre-registered decision brief (2026-10-10)

**Status: recommendation only. Nothing has been changed** — no rule, no threshold, no
gate, no size. This brief exists so that the decision the 2026-09-20 decay bar authorizes
is ready the moment the bar trips. Card: `drift-gate-counterfactual` (+ the instrument
findings below, carded separately). Read-only instrument:
`python3 scripts/drift-relaxation-read.py` → `data/drift-relaxation-read.json`.

## 1. The rule, and where it stands

> Pre-registered 2026-09-20 (tuning #31 rec 2): a `maxPriceDrift` / `longshotDriftPct`
> relaxation is brought forward **only if** `avgPnlPerTradeExDust ≤ $0.50` on **7
> consecutive days** *and* the **trailing-7d cohort mean** is also ≤ $0.50 — attributed by
> `ruleSetVersion`, never as one total. Until it trips, the gate keeps its value.

Live state (`data/drift-shadow-summary.json`, 2026-10-10):

- `consecutiveDaysAtOrBelow` **6** of 7 · `cohort7d` **+$0.02** (3,868 poll rows) · `cohortAtOrBelow` true · `tripped` **false** · 22 days in the series
- The day series is a **daily sample of the CUMULATIVE ex-dust mean**, and its recent days were written while the marker was frozen (only the oldest cohort was markable — the head-of-line defect fixed on 10-10, card `t_81d0a4cb`).
- **On the current reads the bar trips on 2026-10-11** (the 7th consecutive day), which makes the relaxation decision due 2026-10-12. The trip is a *trigger to decide*, not a rule change: on this board's standing convention nothing is applied without your approval.

## 2. Key insight: the bar trips, but the population it would admit does not support a relaxation

The counterfactual looks good in aggregate and *is not actionable in the margin*:

1. **Anchored reproduction** — my re-read matches the published artifact to the cent
   (26,928 candidate rows, 13,881 marked, 7,260 wins, 52.3%, `+$6.13`/trade raw,
   **`+$0.29`/trade ex-dust**, 1,141 dust rows). So the rest of this read is on the same data.
2. **The published mean is a per-POLL number, not a per-opportunity number.** 26,928
   candidate rows are **9,075 distinct copy signals** (marketId + outcome + wallet) and
   **3,550 of those settled**, over **2,549 distinct markets**. One market
   (`lal-bet-get-2026-09-17-bet`) contributes **428 rows** on its own. The instrument counts
   a market that stays drifted once per poll.
3. **On a per-opportunity basis the gate looks like it is blocking edge**: first-observation
   ex-dust mean **`+$1.20`/trade** (n=3,404, market-clustered 95% CI **`[+$0.71, +$1.70]`**),
   `+$1.87` if booked at the lane's −2¢ maker fill. The incumbent C-200 book over the same
   window is **`+$1.27`** per $10 ex-dust (n=606) — i.e. the blocked set prices like what we
   already copy, not like something worse.
4. **But almost none of that population is copyable, and the copyable slice is where the
   drift tolerance stops mattering.** Only **244** of the 3,550 settled signals clear the
   non-drift gates (score ≥ 80.5 ≡ rawConfidence ≥ 0.7, spread ≤ 0.06, liquidity ≥ 750,
   TTR ≥ 2 h, price ≤ 0.95). The blocked population is blocked by *a lot* of drift, not a
   little: first-observation drift **p10 0.005 · p25 0.012 · median 0.060 · p90 0.495**.

Where the money is (settled drift-blocked signals, first observation, ex-dust, per $10):

- score 0–39: **+$1.24** (n=675)
- score 40–59: **+$1.43** (n=1,472)
- score 60–79: **+$0.65** (n=950)
- score 80–100: **+$1.72** (n=307)

The expectancy is spread across score bands, so it cannot be harvested by moving the drift
gate — the score/confidence gates stand between the counterfactual and any copy.

## 3. What each tolerance would actually admit (copyable population only)

Fill model: the signal is admitted at the **first poll whose drift is inside the tolerance**
(that is the price the gate would have paid), must clear the other gates at that row, dust
excluded, $10 clip. "Marginal" = newly admitted vs today's 0.004. CI = market-clustered
bootstrap (1,000 reps).

- today **0.004** → 1 admitted (−$10.00)
- **0.005** → 18 marginal, 13 markets, **+$1.87**/trade, CI **[−$7.62, +$12.50]**
- **0.006** → 19, 13, **+$5.82**, CI [−$7.30, +$22.99]
- **0.008** → 21, 15, **+$4.82**, CI [−$7.00, +$18.98]
- **0.010** → 23, 17, **+$2.56**, CI [−$7.28, +$12.77]
- **0.020** → 31, 23, **+$3.35**, CI [−$5.08, +$12.22]
- **0.050** → 39, 30, **+$2.01**, CI [−$4.40, +$10.06]
- longshot `pct` 0.08 → 0.12 (band < $0.20, cap 2¢) → **6** marginal, 4 markets, +$22.30, CI [−$10.00, +$58.38]

Two things to read off this: every interval straddles zero, and **the whole marginal set is
18–39 trades over 24 days** (≈1–2/day) even at a 5¢ tolerance — because the population is
blocked at 6¢+ drift, not just past the 0.4¢ line. The longshot variant is n=6.

## 4. Reality checks

- **Both bar conditions rest on the poll-row basis.** The cumulative day series samples
  `avgPnlPerTradeExDust` (poll rows) once a day; the trailing-7d cohort is the same basis.
  Re-cut per **distinct signal** on today's marks, the last 14 decision-days are *all* above
  the bar (`+$0.76 … +$6.46`) and the "consecutive days ≤ bar" streak is **0 of 7** — the
  published `6 of 7` is a property of the cumulative mean, not of recent vintages.
- **Instrument defect (independently carded):** the drift shadow records
  `result.confidence`, which is **0 by construction on every skip path**
  (`src/lib/scoring/trade.ts:46`) — all 3,550 settled rows carry `confidence: 0`, and unlike
  the lowconf lane it does **not** store `rawConfidence`. Every screen above therefore
  reconstructs rawConfidence from `copyScore` (`(score − 35)/65`, `watchlistScore` 35 for
  v43→v61) rather than reading it.
- **The short-TTR lane already admits 5¢ of drift** for TTR ≤ 72 h with score ≥ 35
  (`shortTtrMaxDrift` 0.05 since v28). Part of the "blocked" population is reachable today
  through that lane, so the true marginal effect of a flat-tolerance change is smaller than
  even the table above.
- **Basis asymmetry favours the counterfactual and is reported both ways.** The shadow books
  a $10 clip at the observed price with no fee; the live lane books at `intent − $0.02`. The
  maker-fill variant (`+$1.87` signals, `+$2.64` copyable) is the generous bound, the raw one
  (`+$1.20`, `+$1.93`) the conservative one — **the verdict is the same either way**.
- **Regime break.** The drift counterfactual's cumulative series changed basis on 2026-10-10
  (marked 4,945 → 13,881, ex-dust $0.38 → $0.29). Cross-fix comparisons of the cumulative
  number are invalid; the per-signal and per-day cuts here are computed on one (post-fix) basis.
- **This is not a demotion of the fix.** The fix did exactly what it promised: the trailing-7d
  cohort is populated for the first time (3,868 rows vs 0), which is the only reason this
  decision is readable at all.

## 5. Verdict and options

**Recommendation: (A) do not relax.** Record the bar's trip as a *measurement event* and keep
`maxPriceDrift` 0.004 / `longshotDriftPct` 0.08 unchanged.

- **(A) HOLD — recommended.** The pre-registered trigger fires on a basis that is not a
  per-opportunity number, and the actionable marginal set is 18–39 trades in 24 days with
  every interval straddling zero (longshot variant n=6). A rule change on that sample is
  indistinguishable from noise, and the gate's own per-signal expectancy is *not worse* than
  the incumbent's — which is an argument that the gate is mispriced, not that the fix is to
  widen it a little.
- **(B) Bounded experiment — only if you want forward evidence.** Set `maxPriceDrift` 0.006
  (the smallest change that adds a measurable set), pre-registering the re-read: the admitted-
  set ex-dust mean must beat the incumbent's same-window per-$10 ex-dust mean with a
  market-clustered CI excluding zero **and** ≥ 150 settled admitted legs before any further
  move. At the observed marginal rate (≈1/day at 0.006) that is ~5 months — state it up front
  or the bar will read "no result" forever.
- **(C) Abandon the flat gate (0.05) — rejected.** 39 marginal copyable legs in 24 days, mean
  +$2.01 ± $2.01/leg, and it imports the rest of an uncopyable population into the lane.
- **(D) Fix the instrument first, then re-read.** Cheapest honest path: store `rawConfidence`
  and `otherBlocks` on the drift shadow, dedupe the published mean to one row per signal, and
  let the post-fix marking accumulate ~2 weeks so the trailing cohort is a clean
  per-opportunity sample. That re-read is what a rule change should rest on.

## 6. What would change the answer

1. A per-opportunity (deduped) cohort read that puts the **copyable** subset's ex-dust mean
   below the incumbent's with a CI excluding zero.
2. A decision-level re-score of the archived drift-blocked candidates under each candidate
   tolerance with *all* gates applied in order (the shadow records gates, not the decision).
3. Two weeks of post-fix marking, which is the first time the trailing-7d cohort walks the
   whole population instead of a starved head.

**Reproduce:** `cd ~/polymarket-copybot && python3 scripts/drift-relaxation-read.py`
(read-only; writes only `data/drift-relaxation-read.json`).

## 7. Update 2026-10-11 — instrument v2 shipped, and the bar's own basis now disagrees with the honest one

Shipped (`drift-shadow-instrument-defects`, Medusa card `t_18dc9da3`): the feed records
`rawConfidence` + `otherBlocks` on every row, publishes a per-signal basis next to the
per-poll one (`data/drift-decay-series-per-signal.jsonl`, `decayBarPerSignal`), and the
daily report quotes both, labelled. Reads refreshed at 04:00 with marking still running:

- **poll-row (the pre-registered basis):** cumulative **+$0.37**/trade; trailing-7d cohort **−$0.00** (n=3,764 poll rows); bar **6 of 7** days
- **per-signal (one row per market|outcome|wallet):** cumulative **+$0.92** over 5,731 settled of 9,090 signals; trailing-7d cohort **+$3.11** (n=671, 589 markets, market-clustered CI **[+$1.69, +$4.53]**); bar **0 of 7**, `cohortAtOrBelow: false`
- **copyable subset on that basis** (score ≥ 80.5, spread ≤ 0.06, liquidity ≥ 750, TTR ≥ 2 h): 7d cohort **+$0.34** (n=94, 77 markets, clustered CI **[−$2.18, +$3.06]**) — below the incumbent (+$1.27 per $10) but the interval straddles zero
- **all settled signals, first observation:** **+$0.92** (n=5,371, CI **[+$0.58, +$1.30]**); copyable subset **+$1.02** (n=305, CI [−$0.80, +$2.83])

This sharpens §2 rather than reversing it: the trip is a property of the **poll-row** basis, and
on the honest basis the bar's *cohort* condition **fails outright** (+$3.11 vs a $0.50 bar). The
apparent edge is concentrated in rows no gate change can reach — the copyable slice is ≈ +$0.34/trade,
i.e. below what we already book. So **HOLD stands**, reopen condition (i) is **not** met (interval
straddles zero), and the question the data actually raises is not "widen the tolerance a little"
(the marginal sets stay 18–39 trades with intervals straddling zero) but **"does the flat 0.4¢ drift
gate earn its keep at all"** — a much larger question that needs its own pre-registration.

Open, one line each: (a) adopt the per-signal basis for the pre-registered bar itself, or keep
reading the series it was pre-registered against (`data/drift-shadow-summary.json` publishes both);
(b) the drift gate's existence as a gate rather than a score input.
