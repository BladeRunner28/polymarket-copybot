# Profit review — 2026-10-22

**The book has one actionable defect left, and it is not the one I filed yesterday.**
Yesterday's #1 was "give STANDARD the stale exit, scoped 0.2–1.0, <0.20 exempt" — and it shipped with
a gate I never ran. I ran it today. The gate passes, but **at the wrong scope**: the stop earns its
money only at **≥0.60**, and at 0.20–0.40 it destroys $1,064 of measured value. The revised scope is
below. Everything else I was going to propose fails a test I can now run, and I am withdrawing it.

Reproduce: `python3 scripts/profit-band-report.py --v3` (§M–§S are new in this commit).
Cost basis on every ROI line: `simulatedPositionSize` = dollars at risk.

---

## 0. Two things about the measurement itself, because they change how to read everything else

**The book holds 2.7× more capital than the deduped view says.** 1,255 open STANDARD legs are only
466 distinct `(wallet, market, outcome)` bets — up to **64 separate fills in one market** (Barcelona
UCL, $640). I checked whether that is a re-fire bug: it is not. Those 64 legs carry **64 distinct
`observedTradeId`s** — the executor mirrors each whale fill separately. So:

- **per-bet statistics** must dedupe (duplicate rows are pseudo-replication) → 466 bets, $5,343
- **capital statistics** must not → 1,255 legs, **$13,422 deployed**, 1,058,013 capital-days

That resolves the basis fight I had with myself last run. The 1,033,886 figure in the measured
baseline was **not** a basis error; it was the capital basis, and it is the right one for capital
questions. My "does not reproduce" correction yesterday was half wrong: the number reproduced
(1,058,013 today), what was wrong was using it in a ratio against a deduped denominator. Both bases
are now printed side by side in §P.

**The snapshot series for open markets is 35 days stale.** Median time since the last
`MarketSnapshot` for an open leg is **836h**. So "hold to the latest mark" understates the hold arm:
at the DB's own `currentPrice` the open book is **+$1,881.86** unrealized; valued at latest snapshots
it is **+$813.09**. Every replay delta below is therefore reported against *both* hold arms, and the
one I have to survive is the pessimistic DB basis.

---

## 1. Where the money is, allocation vs edge (all-time, deduped, per lane)

`§M`, cost = dollars at risk, CI = market-clustered bootstrap.

**STANDARD — 89% of the book's capital, and it buys the worst bands at the same clip as the best**

- **<0.20** — 221 legs, $2,722, **+$1,463 (+53.8%)** CI [+0.6,+115.4] · 7.0% of notional
- **0.2–0.4** — 416 legs, $5,245, +$722 (+13.8%) CI [−2.0,+30.1] · 13.4%
- **0.4–0.6** — 1,180 legs, $15,497, **−$1,091 (−7.0%)** CI [−13.1,−0.5] · 39.7% ← v63 killed new entries
- **0.6–0.8** — 635 legs, $8,274, +$272 (+3.3%) CI [−2.5,+8.9] · 21.2%
- **0.80–0.95** — 402 legs, $4,395, **−$130 (−3.0%)** CI [−8.3,+2.1] · 11.3%
- **0.95–1.00** — 347 legs, $2,926, −$14 (−0.5%) · 7.5%

**C-200 — 43% of its notional in the only band that pays**

- **<0.20** — 215 legs, $6,577, **+$6,017 (+91.5%)** CI [+26.2,+169.5] · 42.8%
- 0.2–0.4 — 369, $3,958, +$496 (+12.5%) · 0.4–0.6 — 731, $2,409, −$6 · 0.6–0.8 — 399, $1,867, +$75
- 0.80–0.95 — 107, $564, +$17

All lanes realised: **+$7,822 on $54,433 (+14.4%)**.

## 2. Why sizing never sees any of this

`§N`, from `DecisionJournal.simulatedPositionSize` (what the **scorer** decided, before any clamp):

| lane | <0.20 | 0.2–0.4 | 0.4–0.6 | 0.6–0.8 | 0.80–0.95 | span |
|---|---|---|---|---|---|---|
| STANDARD | $18.00 | $18.00 | $18.00 | $18.00 | $18.00 | **1.0×** |
| C-200 | $12.36 | $12.15 | $10.00 | $10.00 | — | 1.8× |

STANDARD's pre-cap clip is **$18.00 in every band, min = max = 18.00, on 564 legs in 45 days**, while
confidence ranges 0.21–0.92 and the bands' realised ROI ranges −7.0% to +53.8%. The band factors in
`rules.ts:348` are pinned at `deadZoneSizeFactor: 1`, `longshotSizeFactor: 1` — v41 moved band sizing
into the C-200 mapping (`paper.ts mapBankroll200Size`) and neutralised STANDARD's copy so bands would
"apply exactly once". They apply zero times on the lane that holds the capital.

The C-200 factors that do the work: `c200LongshotBandFactor 3.5`, `c200DeadZoneBandFactor 0.125`,
`c200BandSizeFactor 0.5` @ 0.6–0.8. **That is a well-built map, and it is on the wrong lane.**

## 3. …and why I am not proposing to port it

`§O` frozen-leg shadow — hold the legs fixed, scale each stake by the map, PnL is linear in stake:

- **C-200 map, raw** — PnL +$4,477 (STANDARD), **ex-top-10 delta +$93**
- **C-200 map, notional-neutral** — delta +$6,681, **ex-top-10 delta −$77**
- **dead-zone skip only** — delta +$1,091, **ex-top-10 delta +$1,091** ← already live as v63

The headline gain is one leg. The only component that survives removing the 10 biggest winners is the
dead-zone skip, and it already shipped. `§Q` says the same thing band by band:

- **<0.20 STANDARD**: +53.8% → **−11.3% ex-top-10** (the top 10 legs are 120% of the band's profit)
- **<0.20 C-200**: +91.5% → **−8.5% ex-top-10** (top 10 = 108%)
- 0.2–0.4 STANDARD: +13.8% → **+5.2%** (survives) · 0.6–0.8: +3.3% → **+1.9%** (survives)
- 0.80–0.95 STANDARD: −3.0% → −4.1% (persistently negative, tail-independent)

So the cheap band is a **10-leg outcome in both lanes**. Its calibration edge (+11.3pp, stable across
both sample halves — yesterday's number, still the most reproducible statistic in the book) says the
*per-bet mean* is positive. It does not say the *dollars* are projectable, and at a `(1−p)/p` payoff
they cannot be: one win at p=0.10 returns 9 stakes. **Up-weighting it multiplies a distribution, not
an edge.** Yesterday I recommended neither; today I can show why that was right, and it is a firmer
no than yesterday's.

## 4. The rate that decides whether any of this matters

`§S`:

- last 14d — $244/day staked, **+$9.42/day** realised → 531× short of $5,000/day
- last 30d — $247/day, +$63.25/day → **79×**
- last 60d — $687/day, +$83.95/day → 60×
- last 90d — $909/day, +$73.22/day → 68×
- last 126d — $987/day, +$123.37/day → 41×

The ladder is a **41–79× size problem**, not a threshold problem. No band reallocation I can measure
moves a 41× gap: the entire dead-zone skip — the best-measured rule change in the book — was worth
$1,091 all-time. That is 18 days of the gap. This is the part of the report I would rather not write,
but the arithmetic is in the committed script.

---

# RECOMMENDATIONS

## #1 — Scope the stale exit to **entry ≥ 0.60**, and exempt everything below 0.40 — LANE A, proposed

**Hypothesis.** A 168h hard-age stop applied only to positions entered at ≥0.60 improves realised PnL
*and* releases the stranded capital block, while the same stop applied below 0.40 destroys value
because a `(1−p)/p` payoff cannot be time-stopped.

**Measurement.** `scripts/profit-band-report.py --v3 §P` — 1,255 open STANDARD legs, counterfactual
exit at the first recorded mark at or after entry+168h (median realised exit age 227h), compared to
holding at (a) the market's latest snapshot and (b) the DB's `currentPrice`. This is the gate the
2026-10-21 draft set and never ran.

| basis | scope | n | notional | stop − hold@snap | stop − hold@DB |
|---|---|---|---|---|---|
| deduped | ≥0.60 | 330 | $3,619 | **+$85** | −$7 |
| all legs | ≥0.60 | 701 | $7,321 | **+$548** | **+$326** |
| deduped | 0.40–1.00 | 376 | $4,240 | +$80 | −$48 |
| all legs | 0.40–1.00 | 853 | $9,151 | +$460 | **−$136** |
| all legs | <0.40 (exempt) | 402 | $4,271 | **−$1,341** | — |

Capital-days at ≥0.60 (all legs): **591,843 → 113,106 (−81%)**; whole book 1,058,013 → 189,745.

**Why ≥0.60 and not 0.40.** 0.40–1.00 flips sign with the mark basis (+$460 stale, −$136 fresh) — it
is not a scope I can defend. ≥0.60 is positive on **every** basis. The loss at <0.40 is not noise:
0.20–0.40 holds +$1,148 to settlement against +$85 stopped, **−$1,064** on 135 legs. And 0.6–0.8
alone carries +$490 of the +$548 (hold −$503 → stop −$13, **29.3% of notional**).

**Decision rule.** Adopt when the ≥0.60 scope is (i) positive on the pessimistic DB-mark basis and
(ii) releases ≥50% of capital-days. Today: +$326 and −81%. **Met.** Exit cost is not a threat —
breakeven haircut on stopped proceeds is **7.5% of proceeds** (all legs) / 2.3% (deduped), against a
0.6–0.8 half-spread of ~1–2% of price.

**Refutation.** (a) If the first 20 organic stopped legs realise worse than hold by >1.0% of notional,
the marks lied and the rule reverts. (b) If a re-run at 60 days shows the 0.20–0.40 exemption
advantage falling below $200 (from $1,064), the exemption was luck and the band should be in scope.
(c) If 0.6–0.8's hold-to-settlement return turns positive on ≥150 new settled legs, the stop is
selling recoveries.

**Effect.** +$326 to +$548 one-off on the existing book; recurring ~4.5% of notional on new ≥0.6 flow;
stranded capital-days −81%. It does **not** create trades — the freed $7,321 has no queue (admissions
run 4–7/day), so treat the capital number as hygiene, not as redeployable alpha.
**Cost: 2–3h.**

## #2 — Do **not** raise the cheap-band size factor; re-baseline its evidence to calibration — LANE A, proposed (nominal change)

**Hypothesis.** The <0.20 band's realised dollar ROI is not projectable, because it is entirely its
top 10 legs, so no size increase above the current 3.5× is supported by any statistic that survives
the tail test.

**Measurement.** `§Q` (tail ladder) + `§O` (ex-top-10 shadow). <0.20 ex-top-10 is **−11.3%**
(STANDARD) and **−8.5%** (C-200); the top 10 legs are 120% and 108% of each band's realised profit.
At the same time `§A` calibration (unchanged, still reproducible) shows +11.3pp of edge in both sample
halves. Both are true; the mean is real, the dollars are a draw.

**Decision rule.** Raise the factor only when **≥150 forward cheap legs** show calibration edge
**≥ +8pp** *and* ex-top-10 dollar ROI **> 0**. Neither is met today (0 forward legs at current size
under v65; ex-top-10 negative).

**Refutation.** If forward calibration lands within ±3pp of price on ≥150 legs, the band is fairly
priced after all and the historical +11.3pp was the winner's curse from screening 226 wallets — in
that case cut the factor, do not raise it.

**Effect.** $0 today, and it is the guard on the most expensive available mistake: 3.5× on a band
whose realised profit is 10 legs.
**Cost: 1h** (instrument only; the decision is a re-read at 150 legs).

## #3 — Nothing else. Three measured dead ends, named.

- **Port the C-200 band map to STANDARD** — refuted by §O: notional-neutral ex-top-10 **−$77**.
- **Cap legs per market on STANDARD** (it has no v55-style ceiling; C-200 does) — refuted by §R: deep
  accumulation is the *profitable* part on STANDARD (copy #10+: +31.1% on $23,739, 77% of book PnL)
  and the *losing* part on C-200 (copy #4–9: −25.6%). The lanes disagree in sign, so any cap is a
  lane-specific bet, not a repair.
- **Cut 0.80–0.95 entries** — the band is −3.0% on 402 STANDARD legs but the CI is [−8.3,+2.1]. It
  fails the significance bar, and the 168h stop in #1 already handles the exit side of exactly this
  block (+$63). Not proposing it on a CI that includes zero.

**IF YOU WEREN'T HERE:** I'd write the ≥0.60 scope into the exit rule myself and leave every other
threshold alone — including the cheap band's size. The stop is the only change in this book that is
positive on both mark bases and both statistical bases, and the reason to do it is not the $326:
it is that **353 open legs, $3,142, sit at a mark of 0.996 with about $28 of upside left** — that is
not a position, it is an accounting residue that makes every capital number in every other report
wrong.

---

## Cost of being wrong, stated

#1 is the third scoping of the same rule in four days (0.2–1.0 → 0.4–1.0 → 0.6–1.0). Each narrowing
came from a measurement, but three scopes in four days is itself evidence that the exit rule is being
tuned against a book it did not create: the ≥0.6 block is **legacy stock** — `maxEntryPrice` is 0.85
on STANDARD and 0.80 on C-200, so 0.95–1.00 can never recur, and 0.80–0.85 is ~1 entry per 15 days.
Once the stock is cleared, #1 stops mattering, which is fine — it is a stock fix, not a flow fix.

## Contradictions I am not resolving silently

1. **0.2–0.4 exit direction.** Yesterday: cuts beat settlement by **$258** in 0.20–0.40 (41 priced
   C-200 tickets, `analyze-band-exit-exemption.ts`). Today: a 168h stop on STANDARD's open 0.20–0.40
   loses **$1,064** vs holding. Different population (C-200 cut tickets vs STANDARD open stock) and
   different counterfactual (settlement vs +168h mark), so they need not agree — but they point
   opposite ways, and the exemption in #1 rests on today's number. Flagging rather than choosing.
2. **Capital-days.** My 10-21 correction stands only halfway: 383,239 deduped reproduces, and
   1,058,013 on the capital basis is also right and arguably more meaningful. The error was the ratio,
   not the level.
3. **Lane B confirmed, not just claimed:** 0 entries in 0.4–0.6 since v63 shipped (2026-10-20 16:00,
   ~41h of organic flow), across both lanes. Yesterday's watch item closes green.
