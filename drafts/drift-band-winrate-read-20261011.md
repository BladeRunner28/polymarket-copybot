# Drift gate — band / win-rate attribution (read due at the 2026-10-08 window close)

**Card:** `drift-gate-band-winrate-shadow` · **Instrument:** `scripts/drift-band-winrate-read.py` (read-only, writes nothing)
**Run:** 2026-10-11, output kept at `data/drift-band-winrate-read-20261011.txt` · **Baseline of record:** `data/drift-shadow.jsonl` (27,020 candidate rows through 2026-10-11 09:23Z)
**This document proposes NO threshold.** The drift tolerance decision belongs to `drift-gate-counterfactual` / the recorded HOLD (`decay-bar-tripped-oct8-decision`). This supplies one dimension to it.

## Why

`maxPriceDrift` has been a FLAT 0.004 for every entry ≥ 0.20 since v60, and the drift gate is the #1 skip reason (28.9% of 7,556 skips in the window that was measured). An external review (`drafts/reddit-late-copy-20260928.md`) supplied a mechanism: copied-market drift is outcome-aligned, so a fixed copy delay is a tax on a high-win-rate book and a subsidy on a longshot-heavy one — tolerance should scale with **(1 − band win rate)**. Two unrelated mechanisms pointing at one field is an argument to measure it, not to move it.

## Method (and its anchors)

- **Duplicate accumulation removed:** 27,020 poll rows → **9,092 distinct signals**, key `(marketId, outcome, wallet)`, earliest poll wins — the shipped `dedupeSignals()` convention (`src/lib/shadow-drift.ts`). Poll-row basis mean **+$0.33** vs per-signal **+$0.88**: the poll-row average is the diluted one, which is why the read is on signals.
- **Anchor:** my poll-row recomputation reproduces the published summary exactly — candidates 27,020, marked 20,467, `avgPnlPerTradeExDust` $0.33, dustExcluded 1,775 — and the per-signal mean $0.88 matches `avgPnlPerTradeExDustPerSignal`. So this read is comparable to the lane's own numbers.
- **Population:** 9,092 distinct signals → **5,867 settled** (3,225 awaiting resolution) → **5,499 ex-dust** (entry ≥ $0.10; 368 dust rows excluded, per the tr29-rec1 floor).
- **As-of discipline:** a decision's band win rate uses only settled signals in that band with an **earlier** timestamp, needing ≥ 30 priors to be labeled (5,717 of 5,867 labeled; 150 too early). The whole-sample band win rate is printed separately and labelled look-ahead, so the arm this replaces is visible.

## Result 1 — the forgone value falls monotonically with ENTRY PRICE (per-signal, ex-dust)

- `0.00–0.20` (median entry 0.150): n=203 · **+$23.47** · clustered CI [+18.26, +28.62] · win 49% · 193 markets
- `0.20–0.40` (0.310): n=687 · **+$5.45** · [+4.05, +6.85] · win 46% · 611 markets
- `0.40–0.60` (0.505): n=1,166 · **+$0.50** · [−0.09, +1.14] · win 52% · 1,014 markets
- `0.60–0.80` (0.695): n=1,104 · **−$2.37** · [−2.90, −1.87] · win 53% · 931 markets
- `0.80–1.01` (0.967): n=2,339 · **−$0.69** · [−0.86, −0.53] · win 88% · 1,687 markets

Every band clears n ≥ 200 ex-dust settled signals, so the band dimension **is** derivable and does not close as "too thin". The damage sits in the low bands; above 0.60 the gate is blocking candidates that would have lost money.

## Result 2 — the WIN-RATE axis does not separate, and is confounded with time

Pooled quintiles of the as-of band win rate (all bands):

- Q1 (wr 0.08–0.50): n=1,073 · **+$7.95** · [+6.55, +9.29]
- Q2 (0.50–0.56): n=1,073 · −$0.19 · [−0.84, +0.42]
- Q3 (0.56–0.91): n=1,073 · −$2.40 · [−2.89, −1.96]
- Q4 (0.91–0.94): n=1,073 · −$0.71 · [−0.94, −0.46]
- Q5 (0.94–0.95): n=1,075 · −$0.10 · [−0.30, +0.08]

**Not monotone** (rising: False, falling: False). Within bands the high-win-rate half is the *less negative* half in all five bands (e.g. `0.60–0.80` −$0.83 vs −$3.96; `0.80–1.01` −$0.14 vs −$1.25), which is the external claim's direction — **but the halves are not date-matched**: in four of five bands the LOW half sits 2026-09-19…09-22 and the HIGH half 2026-09-30…10-03, up to 12 days apart, and the only date-matched split (`0.80–1.01`, 09-19 vs 09-20) separates 0.88–0.94 from 0.94–0.95 — a 1 pp contrast. So the "as-of win rate" axis in this window is substantially a **time** axis, and the within-band gaps must not be read as win rate alone.

The decisive counter-example to a naive transfer: the **highest**-win-rate band (0.80–1.01, 88% wins) has **negative** forgone value (−$0.69). Win rate and price are confounded in our book — a high-priced token wins often and pays little — and on the price axis the effect runs opposite to the claim's prediction.

## Verdict

1. **The flat tolerance is mis-scaled along PRICE, not along band win rate.** Forgotten value concentrates at entries < 0.40 and turns negative above 0.60 — the band dimension points at `0.20–0.40`, and at nothing above it.
2. **The win-rate mechanism does not transfer cleanly.** Non-monotone pooled series, date-confounded within-band splits, and a high-win-rate band with negative forgone value. Reported as measured, not as a direction.
3. **This agrees with the recorded HOLD rather than challenging it.** The earlier relaxation read (`scripts/drift-relaxation-read.py`) found that widening 0.004 → 0.006/0.008 admits only ~19–21 legs across the whole window, with every clustered CI straddling zero — and now we know why the admitted slice is small even though 0.20–0.40 has the largest per-signal counterfactual: the population is blocked by a MEDIAN ~6¢ of drift, so a tolerance move reaches few of these rows. Nothing here is a reason to move a threshold; it is the dimension the decision records.
4. **If a tolerance change is ever brought forward, its pre-registration should be band-relative in PRICE** (e.g. "0.20–0.40 only, ≤ N legs/30d, CI excluding 0 at n ≥ 50"), never as a single flat number — the win-rate clause the external source suggested is not supported by our own counterfactual.

## Caveats that limit these numbers

- IN-SAMPLE counterfactual: the shadow prices rows the gates blocked; it is not a replay of a book that took them.
- The `0.00–0.20` mean is convexity-heavy (203 ex-dust rows of a longshot band, median entry 0.150) and that band already carries the longshot relaxation (`longshotDriftPct` 0.08 / cap 0.02), so it is not the slice a flat-tolerance change would reach.
- Ex-dust excludes 368 settled signals (6.3%) below $0.10 — stated, never silently dropped.
- Marked/awaiting split: 3,225 of 9,092 distinct signals are still unresolved; every settled figure here is on the 5,867 that are.

**Reproduce:** `python3 scripts/drift-band-winrate-read.py` (reads `data/drift-shadow.jsonl`; writes nothing).
