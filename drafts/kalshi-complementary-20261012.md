# Complementary Kalshi workstream — options A, B, C (executed 2026-10-12)

**Charter:** in-thread, 2026-10-12 16:47 CDT, Xman answered the Kalshi question with
*"Do a, b, and c"* — (a) start keyless tape capture + one pre-registered maker read,
(b) a Kalshi-native macro shadow lane, (c) a weather/oil cross-venue read. This document
is the executed record: what was built, what the first real reads returned, and the
pre-registered gate each study must clear. Nothing below changes a rule, a size, a gate
or a live position — **we hold no Kalshi API key, so every lane here is paper/shadow.**

Why the question was asked at all: `kalshi-venue-shadow` prices our C-200 copies on
Kalshi's book and finds **2 quotes on 791 in-window copies (0.3% cross-list)**, so the
Kalshi *copy* lane looks dead. It is dead — but that was measuring "Kalshi twins of our
book", which is not the same claim as "there is no strategy on Kalshi".

---

## 1. What shipped

| piece | file | state |
|---|---|---|
| Tape capture (option A) | `scripts/kalshi-tape-capture.py` + `~/.hermes/scripts/copybot-kalshi-tape.sh` | **live on cron, every 5 min** (job `60f844c59cfb`) |
| Family allowlist | `data/kalshi-tape-families.json` | seeded 2026-10-12 (10 families) |
| Tape artifacts | `data/kalshi-tape/{bars,coverage}.jsonl`, `prints-<date>.jsonl.gz`, `state.json` | writing |
| Macro shadow (option B) | `scripts/kalshi-macro-shadow.py` + `~/.hermes/scripts/copybot-kalshi-macro.sh` | **live on cron, hourly** (job `f57d30ef6dee`) |
| Macro artifacts | `data/kalshi-macro-{quotes,settled,news}.jsonl` | 336 quote rows, 1 news row |
| Cross-venue read (option C) | `scripts/kalshi-crossvenue-read.py` | executable; first read recorded below |

Both cron jobs are `no_agent` script jobs: **silent when healthy**, one line to this
thread only on a failed run, a cap hit, an incomplete window, or an artifact that went
stale. (Watchdog contract used by the rest of the copybot stack.)

### Why A had to start today, not later
Kalshi's public trade tape is keyless but **rolling**: on 2026-10-12 it reaches
2026-08-15 and nothing at 2026-07-25 (~8 weeks; it was ~10 weeks on 2026-09-25). Every
day not captured is microstructure history that cannot be recovered afterwards.

### The capture's own sampling rule (quote it beside any figure drawn from it)
The venue tape is a firehose: **188 prints/s venue-wide** measured on the first two
windows (52,000 prints scanned in 276 s of captured time). A continuous capture would be
~4 GB/day of transfer, so the job captures **complete, gap-free 4-minute windows every
5 minutes (~80% duty cycle)** and records the hole before every window in
`coverage.jsonl`. Coverage is **measured, never assumed**: never quote a bar total as
venue volume without its coverage row.

First captured window (17:1x CDT, real, not a dry run): **224 bars, 3,065 verbatim
prints (≥100 contracts), 7 families, `stop=window_complete`, no cap hit.** Over the two
windows so far: 3,500 verbatim prints carrying 1,123,208 contracts / $810,414 notional,
split `taker_side` 1,906 YES / 1,594 NO, and **168 prints ≥1,000 contracts = 4.8% of
prints carrying 32.4% of kept contracts** — the tail is where the size is.

---

## 2. Option A — the maker question, and what the first tape already says

**Fees decide the venue.** Kalshi's schedule (effective 2026-07-07): taker
`0.07·C·P·(1−P)`; **maker `0.0175·…` with a maker multiplier of 0 by default, i.e.
resting orders pay $0 on standard series.** Measured fee, per contract:

- P=0.25 → taker **$0.0131** (525 bps of price) · maker **$0**
- P=0.90 → taker $0.0063 (70 bps) · maker **$0**
- P=0.95 → taker $0.0033 (35 bps) · maker **$0**

On KXBTC15M the spread was 1¢ at 0.25/0.26 — **4% of price, against a 5.3% taker fee**.
Any taker strategy there is dead on arrival; a maker earns instead of pays. That is the
entire reason this is a *maker* study and not a direction study.

**The cheap hypothesis is already dead, and now reproducibly so.** `scripts/kalshi-btc15m-calibration.py`
(`python3 scripts/kalshi-btc15m-calibration.py`) reads every settled market in the
rolling window — **6,438 markets, 2026-08-06 → 2026-10-12** (the count grows as markets settle; 6,439 a few minutes later, same read) — and compares the last
printed price to the realized outcome: implied <0.02 → **n=3,211, realized YES 0.0000**
(implied mean 0.0010); implied >0.98 → **n=3,222, realized YES 1.0000** (implied 0.9990).
**99.9% of the sample sits in those two tails**, so 15-minute crypto is a
race-to-the-finish whose edge question lives *inside* the window, never at settlement —
and the earlier hand-probe figure (3,200 markets) is superseded by this script's output.

**Fill estimator, corrected on first contact.** A print occurs at the *resting* order's
price, so a resting bid at `x` fills only on a print **at `x` with the taker selling** —
not, as a first pass assumed, on any print below `x` (that proxy over-counted wildly:
"bid 0.90" looked like 390 fills, the correct count is 2). Measured on 4.6 minutes of
KXBTC15M tape: bidirectional fills are *sparse* — 7 fills / 1,268 contracts at 0.25,
0 at 0.50, 1 at 0.80, 2 at 0.90, 15 at 0.95 — i.e. **the observable fill flow sits in
the tails**, exactly where the calibration read says the price is already right.

### Pre-registered read (written now, before the sample exists — do not move it)

Run once **≥30 captured hours** of tape exist (≈1 week of the 80% duty cycle):

1. **Universe:** allowlisted families with ≥500 captured bars; report per family, no
   pooling across families.
2. **Fill rule:** resting order at price `x`; a fill requires a print at `x` with
   `taker_side` opposing us. Because queue position and unfilled remainder are
   unobservable from a keyless tape, apply a pre-registered haircut — credit
   `min(1, our_size / print_size)` of each qualifying print, and report the unfiltered
   count beside it so the haircut's effect is visible.
3. **Fees:** maker $0 (standard series). Taker fee applies to the exit assumption; state
   which exit is used.
4. **Adverse selection is the whole test:** mark every simulated fill to the market's
   settlement (Kalshi `/markets/{ticker}`), and report fill-time-to-settlement PnL **net
   of the mark-out**, not just fill quality. A strategy that fills only when the market
   is about to move against it will show positive "fill count" and negative PnL.
5. **Gate:** promote to a paper-execution lane **only if** the net-of-adverse-selection
   maker EV is positive with a 95% CI excluding zero at the pre-registered sample size.
   **A negative or marginal result closes the lane** and is recorded as such (that is the
   expected outcome: our moat is wallet-copy + measurement, not microstructure).

**Not claimed:** no edge exists on Kalshi; no lane is profitable; the tail-heavy fill
flow above is not evidence either way — it is the sample-size problem made visible.

---

## 3. Option B — Kalshi-native macro shadow lane

A read-only, forward-only instrument: snapshots the macro families Kalshi actually runs
(CPI / Fed / U3 / GDP / NBER recession / payrolls) and records a settlement row the first
time a held market resolves, so the lane scores as a **calibration curve** — what the
venue's implied probability said at H hours to close vs what happened. It cannot become a
copy lane: Kalshi publishes no wallet attribution at all, keyless or otherwise.

First real run (2026-10-12 17:0x CDT): **6 families, 336 quote rows**; open markets
KXCPI 44 (OI 914k), **KXFED 200 (median spread 0.40)**, KXGDP 36, KXPAYROLLS 26, KXU3 28,
KXRECSSNBER 2 (OI 1.31M).

**Pre-registered read (already in the script header):** at **n ≥ 20 settled markets per
family**, each with a quote at ≥24h to close and one at ≤6h, report implied-vs-realized
by horizon bucket; the lane "prices the venue" only if the 24h bucket's
|realized − implied| clears its binomial 95% CI. Until then every figure is
**descriptive** and no rule may move off it. Sample accrues over weeks: these families
are event-driven.

**Data-quality finding on the GDELT context column (measured, then corrected).** The
per-run news counts were a naive substring match on headlines and were wrong in two
distinct ways, both measured on the 26,334-story capture:

- **Substring, not word:** `cpi` counted Indian CPIM party stories; `fed` counted "fed
  scandals". Word-boundary matching moved KXFED **234 → 14** and KXCPI **28 → 24**.
- **Wrong corpus:** even after that fix, the capture is dominated by non-US outlets
  (economictimes/timesofindia/aninews/hindustantimes…), and **0 of the 24 surviving CPI
  matches are US-country stories**; the surviving KXFED "match" was a person named
  Denise Powell. The column now writes `us_country_counts` beside `counts` and stamps
  `match_rule`, so the row itself carries its own validity measure.

So the news column is **context only, not signal**, and the pre-registered read deliberately
ignores it. A real fix (targeted per-family GDELT queries with a pre-registered precision
check) is carded, not improvised here.

---

## 4. Option C — cross-venue read: same underlying, different contract

Same-underlying pairs: NYC daily-high temperature (Kalshi `KXHIGHNY` vs Polymarket
`highest-temperature-in-nyc-on-<month>-<day>-<year>`) and WTI crude (Kalshi `KXWTI` vs
Polymarket `wti-closes-above-on-…`).

**Result — the two venues do not list the same object, in either family:**

- **NYC temperature:** the ladders are **offset by one degree** (bucket grid Kalshi
  `68-69, 69-70, 70-71…` vs Polymarket's `<=68, 69-70, 70-71…`), so
  **exact-alignment rows = 0**: there is no contract pair that can support an execution
  claim at all. The exhaustiveness check (ladder mid sum, should be ≈1.00) reads kalshi
  0.985 (**5 one-sided bins excluded**) vs PM 1.007 — the exclusion is itself the
  liquidity story. The raw implied-vs-implied gap at x=70 is −0.512, and it is an
  **artifact of interpolating a uniform distribution inside a bucket** (Kalshi's
  dominant bin is 69-70 at 0.985 while PM's is 70-71 at 0.995 — the same weather, two
  grids). Reported as NOT a quote and NOT an edge.
- **WTI:** Polymarket thresholds are integers (85.0, 86.0, …); Kalshi strikes settle
  "above 84.99, 85.99, …" — **0 of 11 exact-strike matches.**

This is an independent corroboration of the existing card
`kalshi-lane-ontology-not-coverage` ("0% is a CONTRACT-ONTOLOGY problem, not matcher
coverage", measured 2026-09-18): the lanes fail on contract shape, not on matching
effort. A cross-venue arb claim needs exact-alignment rows, and there are none.

---

## 5. Reality checks

- **No Kalshi key.** Every lane above is paper/shadow. Nothing here can execute, and
  nothing here is pretending to be P&L.
- **Maker discipline is not our moat.** Our proven edge is wallet-copy + measurement.
  Market-making is a microstructure competition; the honest expectation for the
  pre-registered read is negative-to-marginal.
- **Complimentary is still real:** different signal (Kalshi's own flow, not wallets),
  different horizon (intraday vs multi-day), different capital (separate account), near
  zero correlation with the C-200 book.
- **The tape is the only irreversible asset here.** The capture is the piece with a
  deadline; the studies can be run any time after it has accumulated.
- **Fee arithmetic is the venue's own published schedule**, not an estimate.

## 6. Reproduce

```bash
cd ~/polymarket-copybot
python3 scripts/kalshi-tape-capture.py --window-minutes 4 --max-pages 200   # one capture window
tail -1 data/kalshi-tape/coverage.jsonl                                    # its measured coverage
python3 scripts/kalshi-macro-shadow.py                                     # one macro snapshot
python3 scripts/kalshi-crossvenue-read.py --city nyc --oil                 # the option-C read
python3 scripts/kalshi-crossvenue-read.py --city nyc --calibration         # settled-market calibration
```

## 7. Open items (carded, not silently decided)

- Maker read runs when the pre-registered sample exists (~1 week); gate as in §2.4.
- `kalshi-gdelt-context-v2` — replace the keyword column with targeted per-family GDELT
  queries + a measured precision check.
- Overlap with `bt-data-capture` (backtest data acquisition, Backlog): the Kalshi forward
  tape is now being captured for the allowlisted families — that card's Kalshi half has a
  running source; its PM-side pager and Parquet step remain open.
- Whale/wallet parity (`phase-kalshi1`) stays parked for cause: keyless Kalshi publishes
  no wallet data, ever.
