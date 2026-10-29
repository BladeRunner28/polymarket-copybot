# STANDARD fill booth — first read (card t_7560e0d0)

Generated 2026-10-29T17:14:29.179Z by `scripts/standard-fill-stamp.ts`. **Measurement only** — nothing in
the trade path reads this, and no rule, size, gate or booked figure was changed.

## The question

STANDARD books `entryPrice = currentPrice` with p(fill) = 1 and no fill model at all. Profit-recs 2026-10-29 #1
priced a 1c better entry at **+$1,439.33** on 90 days' settled notional (5.0% of notional against a 90d realised
+8.1%): one cent is 62% of the lane's 90-day profit. This is the measurement that decides whether that cent exists.

## Headline

- **Book arm, widest window (30-60m):** n = **251** legs, mean **-0.37c** vs the booked price, median **+0.50c**, 10th–90th percentile [-1.50, +1.50]. The entry was attainable at the booked price or better on **29%** of legs and a cent or more WORSE on **27%**.
- **Versus the mid** (what the refutation is worded against): mean **-1.08c**, median **+0.00c**, within ±0.3c on 55% of 251 legs.
- **No waiting, no hindsight (first snapshot after the decision, n = 251):** mean **+1.03c**, median **+0.50c**, a cent or more worse on **38%**. This is the taker's number; every wider bucket buys its lower mean with hindsight.
- **The pre-registered gate is NOT MET:** 251 legs against the required 300.
- **Gate arithmetic:** 49 more stamped legs. At the measured rate (251 stamped over 59.2 days = 4.24/day) that is ~12 days of ordinary running — but the binding constraint is L2 COVERAGE, not time: 29% of in-scope STANDARD legs have a covered book window at all, because the recorder pins C-200 dispatches and STANDARD dispatches are not pinned.
- **Verdict:** NOT EVALUABLE: n=251 of the required 300 legs carry a stamp with a mid (book arm), so the ±0.3c test has no population to fire on. Nothing is refuted and nothing is confirmed.

## How to read the two arms (they do NOT agree, and must not be pooled)

The book arm asks *what ask could I have lifted*: at the first snapshot after the decision the best ask sat **above** the booked price (median +0.50c, a cent or more worse on 38% of legs). A taker pays the spread, and the wider buckets approach parity only by taking the window's best price with hindsight.

The tape arm asks *did anything trade at or below the booked price*: 82% of legs show a print at or below it inside an hour, median -1.50c, p10 -12.50c — but a min-print over an hour is the most optimistic statistic available, and its left tail is markets repricing (a print at 0.001 is not an entry a copier could size). The tape says the level existed somewhere in the hour; the book says you could not have lifted it at the decision. Only the book arm carries a mid, so only the book arm can answer the ±0.3c test.

## Distribution by decision-lag bucket (book arm)

```
[standard-fill-stamp] book: evidence on 251/880 legs (29%), 251 inside the 30-60m window, median cover lag 10.7s, 5 legs with an ambiguous outcome token
[standard-fill-stamp] bucket      n   mean   median      p10      p90   <=booked  >=+1c   |d|<=0.3c   (attainable - decision, cents)
[standard-fill-stamp] first*    251  +1.03c  +0.50c   +0.00c   +2.00c      11%    38%        7%
[standard-fill-stamp] 0-10s     125  +0.78c  +0.50c   +0.00c   +2.00c      10%    40%        6%
[standard-fill-stamp] 10-30s    151  +0.76c  +0.50c   +0.05c   +1.50c      10%    36%        7%
[standard-fill-stamp] 30-60s    158  +0.72c  +0.50c   +0.00c   +1.50c      10%    37%        7%
[standard-fill-stamp] 1-5m      199  +0.46c  +0.50c   -0.50c   +1.50c      17%    34%        8%
[standard-fill-stamp] 5-30m     250  -0.09c  +0.50c   -1.20c   +1.50c      26%    30%        9%
[standard-fill-stamp] 30-60m    251  -0.37c  +0.50c   -1.50c   +1.50c      29%    27%       10%
[standard-fill-stamp] widest 30-60m: n=251 mean -0.37c median +0.50c [-1.50c, +1.50c] · at-or-better 29% · a cent worse or more 27% · $4476.78 booked notional
[standard-fill-stamp] * first snapshot at/after the decision at whatever lag: no patience, no hindsight
[standard-fill-stamp] vs the CONTEMPORANEOUS MID (the refutation's basis, ±0.3c):
[standard-fill-stamp] first*    n=251 mean  +0.20c median  +0.00c · spread paid +0.82c · within ±0.3c  68%
[standard-fill-stamp] 0-10s     n=125 mean  -0.06c median  +0.00c · spread paid +0.84c · within ±0.3c  69%
[standard-fill-stamp] 10-30s    n=151 mean  -0.02c median  +0.00c · spread paid +0.78c · within ±0.3c  70%
[standard-fill-stamp] 30-60s    n=158 mean  -0.07c median  +0.00c · spread paid +0.79c · within ±0.3c  71%
[standard-fill-stamp] 1-5m      n=199 mean  -0.32c median  +0.00c · spread paid +0.78c · within ±0.3c  66%
[standard-fill-stamp] 5-30m     n=250 mean  -0.82c median  +0.00c · spread paid +0.73c · within ±0.3c  58%
[standard-fill-stamp] 30-60m    n=251 mean  -1.08c median  +0.00c · spread paid +0.72c · within ±0.3c  55%
[standard-fill-stamp] widest    n=251 mean  -1.08c median  +0.00c · spread paid +0.72c · within ±0.3c  55%
```

## Second source: venue prints (tape arm)

Prints are trades that HAPPENED, not quotes we could have lifted, and they carry no mid — so this arm can extend
coverage and read price-vs-decision, and can never feed the ±0.3c-of-mid test.

```
[standard-fill-stamp] tape: evidence on 194/880 legs (22%), 194 inside the 30-60m window · prints cannot give a mid, so this arm never feeds the ±0.3c test
[standard-fill-stamp] bucket      n   mean   median      p10      p90   <=booked  >=+1c   |d|<=0.3c   (attainable - decision, cents)
[standard-fill-stamp] 0-10s      27  -0.32c  +0.50c   -1.50c   +0.50c      41%     4%        0%
[standard-fill-stamp] 10-30s     45  -0.90c  -0.32c   -2.50c   +0.50c      60%     2%       13%
[standard-fill-stamp] 30-60s     58  -0.77c  -0.05c   -2.50c   +0.50c      62%     3%       14%
[standard-fill-stamp] 1-5m      104  -1.06c  -0.50c   -3.00c   +0.50c      79%     8%       10%
[standard-fill-stamp] 5-30m     162  -1.78c  -0.50c   -5.00c   +1.00c      80%    13%        8%
[standard-fill-stamp] 30-60m    194  -3.48c  -1.50c  -12.50c   +1.00c      82%    11%        7%
[standard-fill-stamp] widest 30-60m: n=194 mean -3.48c median -1.50c [-12.50c, +1.00c] · at-or-better 82% · a cent worse or more 11% · $3492.00 booked notional
[standard-fill-stamp] * first snapshot at/after the decision at whatever lag: no patience, no hindsight
[standard-fill-stamp] REFUTATION (tape): NOT EVALUABLE: n=0 of the required 300 legs carry a stamp with a mid (tape arm), so the ±0.3c test has no population to fire on. Nothing is refuted and nothing is confirmed.
```

## Coverage, per source (never assumed complete)

```
{
  "standardLegsAll": 10272,
  "standardLegsInScope": 880,
  "scopeSinceMs": 1788180352649,
  "l2CorpusEpochMs": 1788180352649,
  "l2CorpusPresent": true,
  "marketsMissingAssetMap": 592,
  "bookFilePresent": 288,
  "bookStamped": 251,
  "tapeMarketsAttempted": 150,
  "tapeMarketsWithPrints": 150,
  "tapeMarketsInWindow": 109,
  "tapeStamped": 194,
  "tapeByMap": 0,
  "tapeByProximity": 194,
  "tapeTokenRejected": 2
}
```

## Shared resolver, mode `none` (level = the booked price)

Reachable **74/251** = 29%
· unresolved 629 (excluded from the rate, never counted as "did not fill").

## What this read does NOT establish

- The card's gate (**≥300 legs**) is **not met by the book arm**, and the tape arm cannot substitute: it has no mid,
  so the ±0.3c-of-mid test has no population to fire on. Nothing is refuted and nothing is confirmed.
- Attainment is reachability: a best ask at/below a price is a seller willing there, ignoring queue position and
  size. Min-ask over a window is an optimistic bound with hindsight; the 0-10s row is the no-patience read.
- Our L2 recorder covers the market universe plus C-200 pins. STANDARD dispatches are not pinned, so book coverage
  is incidental — that is why the book arm's n is what it is, and it is the binding constraint on the gate.

## Reproduce

```
npx tsx scripts/standard-fill-stamp.ts --book-only     # offline, book arm only
npx tsx scripts/standard-fill-stamp.ts                 # + bounded tape arm
```

Artifact: `data/standard-fill-stamp.jsonl` (append-only, one snapshot per run).
