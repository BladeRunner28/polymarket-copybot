# The rung must print four bases and credit only the one we can prove

**LANE A — PROPOSAL ONLY. Nothing applied: no `apply-v*`, no prisma write, no RuleSet change, no
merge. The card this answers is `ladder-credit-confirmed-filled`.**

Read at **2026-11-16 10:57 CST** (regime = `journal.ruleSetVersion >= 68`, cost =
`PaperTrade.simulatedPositionSize` = dollars at risk, settle clock = `COALESCE(closedAt, resolvedAt)`).

Re-read / verify every number in this doc with:

```
python3 scripts/ladder-credit-basis-audit.py          # this proposal's instrument (new, §L0-L9)
python3 scripts/profit-supply-ladder.py --regime 68   # the review's instrument (§S5/S6)
```

Both open `prisma/dev.db` `mode=ro`. The booth file is read, never written.

---

## 1. The four bases, re-measured — the card's read reproduces to the cent

| basis | legs | cost | PnL | ROI | $/day |
|---|---|---|---|---|---|
| booked rows (`realizedPnl` column) | 422 | $9,158.8 | +$442.0 | +4.8% | +$22.4 |
| positions only (minus `fillStatus='unfilled'`) | 231 | $4,405.5 | +$71.1 | +1.6% | +$3.6 |
| unadjudicated (`fillStatus IS NULL`) | 141 | $2,281.1 | +$490.9 | +21.5% | +$24.9 |
| **confirmed filled** | **90** | **$2,124.4** | **−$419.7** | **−19.8%** | **−$21.3** |

The 07:53 review read 421 / $9,141 / +$406.3, 230 / $4,387 / +$35.5, 141 / +$490.9, 89 / −$455.4.
Every delta is **one leg**: `cmwj3n6mh003hb5uryqkskl7r`, C-200, `dota2-frogli-konca-2026-11-16`
FROGLINGS @0.335, $17.99, settled **08:34:59** today, **filled, +$35.65**. It moved the filled
class from −21.6% to −19.8% and the positions-only rate from $1.8/day to $3.6/day.

That is the first thing to internalise: at 89-90 legs, **one settlement moves the published ROI by
almost two points.** Any claim in this document that rests on the filled class's magnitude is
therefore not a measurement — see §5.

Per lane, which is where the structure is:

| basis | lane | legs | cost | PnL | ROI |
|---|---|---|---|---|---|
| booked | C-200 | 299 | $7,654.6 | +$52.2 | +0.7% |
| booked | STANDARD | 123 | $1,504.2 | +$389.7 | +25.9% |
| positions only | C-200 | 108 | $2,901.3 | −$318.6 | −11.0% |
| positions only | STANDARD | 123 | $1,504.2 | +$389.7 | +25.9% |
| unadjudicated | C-200 | 18 | $776.9 | +$101.1 | +13.0% |
| unadjudicated | STANDARD | 123 | $1,504.2 | +$389.7 | +25.9% |
| confirmed filled | C-200 | 90 | $2,124.4 | −$419.7 | −19.8% |
| confirmed filled | STANDARD | 0 | — | — | — |

**"Positions only" is not a second basis — it is the unadjudicated basis plus whatever has been
adjudicated.** 79.4% of the +$490.9 ($389.7) sits in the lane that has never been stamped.

Rolling windows (settle clock, both lanes) — and the reason the regime figure is not a rate:

| basis | last 7d | last 14d | regime (19.7d) |
|---|---|---|---|
| booked rows | +$412.4 (143 legs) | +$421.6 (353) | +$442.0 (422) |
| positions only | +$243.4 (70) | −$25.3 (182) | +$71.1 (231) |
| unadjudicated | +$16.3 (25) | +$208.1 (101) | +$490.9 (141) |
| confirmed filled | **+$227.1 (45, +21.8%)** | −$233.5 (81, −12.8%) | −$419.7 (90, −19.8%) |

The filled class is **positive in the last 7 settled days** and negative over the regime. Both are
true; neither is a rate.

## 2. The number that actually moves is the rung's own window, and it barely moves

The advance gate is **C-200 only** (`query_bankroll.js:109-141`, `pnl += t.realizedPnl ?? 0`) and
sums the settled 7 days `T-3 .. T-9` local (`SETTLE_DAYS=3`, `GATE_WINDOW_DAYS=7`). On its own
population and clock (I reproduced the production report's window exactly — see the parity check):

| basis | legs | cost | PnL | ROI | gate sum | need (7×$250) | phase |
|---|---|---|---|---|---|---|---|
| booked rows (what prints today) | 163 | $3,898.8 | +$207.0 | +5.3% | **+$207.0** | $1,750 | Phase 1 |
| positions only | 62 | $1,502.4 | +$106.1 | +7.1% | +$106.1 | $1,750 | Phase 1 |
| unadjudicated | 5 | $278.0 | +$10.0 | +3.6% | +$10.0 | $1,750 | Phase 1 |
| confirmed filled | 57 | $1,224.5 | +$96.1 | +7.8% | **+$96.1** | $1,750 | Phase 1 |

Parity against the report's own as-recorded log (`data/phase-streak-log.jsonl`, local buckets, the
most recent write per day): 11-13 −$2.7 / −$2.7 · 11-12 $150.7 / $150.7 · 11-11 $513.4 / $513.4 ·
11-10 −$190.2 / −$190.2 · 11-09 −$47.9 / −$48.0 — **exact to the cent**, so the window and the local
day convention are the production ones.

**Read this honestly: for the rung, the basis change is worth −$110.9 on the gate sum (booked →
filled) and only −$10.0 (positions → filled).** No phase moves, today or near today; the gate is at
11.8% (booked) or 5.5% (filled) of the $1,750 it needs. The rung is **not** where the sign lives, and
a proposal that sells this as "the ladder was lying about +$20/day" has to be precise about whose
number it is: the +$22.4/day is the **book-wide** figure (§6), not the C-200 rung's.

## 3. The unadjudicated class is a coverage statement, not an unknown

141 legs, +$490.9. It is **two** populations with two different repairs:

**(a) C-200, 18 legs, +$101.1 — a link defect, fully recoverable.**
`SELECT ... FROM FillIntent WHERE paperTradeId IN (...)` matches **0 of 18**. Every one of the 18
has a `FillIntent` on the natural key `(decisionJournalId, marketId, lower(outcome), side)` — **18 of
18 tuple-recoverable** — and all 18 carry `fillBasis = NULL`, i.e. the resolver has **never attempted
them**. This is the same class the 2026-11-13 card found from the other side (unlinked intents), now
measured from the leg side. It is not "coverage we lack"; it is a write-path miss with a
deterministic key to recover from.

**(b) STANDARD, 123 legs, +$389.7 — no stamping path exists.** The booth
(`src/lib/standard-fill-stamp.ts`) is measurement-only and the resolver is scoped
`botId: "BANKROLL_200"`. Coverage by open vintage makes the asymmetry unmistakable:

| lane | open week | legs | stamped | coverage |
|---|---|---|---|---|
| C-200 | W41 … W47 | 593 | 575 | 90–100% every week |
| STANDARD | W41 … W47 | 225 | 0 | **0% every week** |

So: **C-200's credit basis can move today** (95%+ of new legs carry a verdict). **The combined book's
cannot** — and "unadjudicated" for STANDARD is not a coin flip we have not looked at. We have looked:
§4.

## 4. The booth has already run the card's refutation test on those exact legs

The card's refutation is *"a 150-leg forward sample of the unadjudicated class, adjudicated against
the venue tape, showing ≥60% actually filled."* The STANDARD booth already measures, per leg, the
lowest best-ask seen inside its lag window against `PaperTrade.entryPrice`. Joined by leg id to
**this card's 123 legs** (not a lane-wide rate — the same legs):

- **121 of 123 carry a book read.**
- **9 legs (7.4%) had a seller at or below the booked price** — these would book `filled`: $141.0 cost, **+$92.3**.
- **112 legs (92.6%) never saw the booked price offered** — under the convention in force for C-200
  (`fillBasis='book-window'`, *"book window showed it NOT reachable" → `unfilled`*) they book `unfilled`,
  i.e. **0**, removing **+$273.9** from the book.
- Lane-wide the booth reads 10.0% at-or-better on 380 legs, so the 7.4% here is not an outlier.

**The consequence for this proposal:** promoting the booth to a stamping write would not move
STANDARD from "unadjudicated" into the credit — it would move ~93% of those legs into `unfilled`, and
`src/lib/paper.ts::bookedPnl()` books a proven-unfilled leg at **0**. That is a bigger move than
"exclude the unadjudicated class", and it must be approved as its own change (FLAG 3).

The convention choice decides which arm applies, and it is not cosmetic:

- **book arm (taker at the booked price)** — ask must come to us; 7.4%. Consistent with C-200's resolver.
- **tape arm (resting maker at the booked price)** — a print at or below us; **no per-leg prints exist
  for these 123 legs** in the current artifact, so this arm is not computable today. If STANDARD is
  to be treated as a maker, the booth needs the tape side recorded per leg first.

## 5. What is NOT robust — and one claim in the card I have to walk back

The filled class at −$419.7 is **not** a demonstrated loss:

- ex-top-1 leg: **−$972.0** (the class's whole loss is one leg's winner; `atp-shevche-ruud-2026-11-11`);
- ex-top-3: −$1,072.0 · ex-top-5: −$1,149.6 (a *loss* grows when the winners are removed, consistently);
- market-clustered bootstrap, 3,000 resamples: PnL 95% CI **[−$1,387.7, +$1,078.0]**, ROI
  **[−60.7%, +51.2%]** — spans zero;
- last 7 settled days on the same basis: **+$227.1, +21.8%** (45 legs).

So the defensible claim is **not** "the book loses on the only proven basis". It is the accounting
identity, which needs no significance: **the book's positive number lives entirely inside a class no
fill model has examined, and 79.4% of that class belongs to a lane with a 0% stamping rate.** That
holds at every sample size.

**Retracted from the card's note: the decay story.** "Positions-only $7.1/day (11-15) → $1.8/day
(today)" is not a monotone convergence. Successive reads: $7.1 → $1.8 → **+$3.6** now; the difference
between the last two is one +$35.65 leg. The $/day denominator is also the regime span, which grows
every day, so two reads are not comparable even when the numerator does not move. The cohort table
replaces it:

| settle week | filled (n / PnL) | unadjudicated (n / PnL) | unfilled (n / PnL) | positions-only $/day |
|---|---|---|---|---|
| 10-27 | 9 / −$186.3 | 49 / +$274.6 | 30 / −$57.0 | +$12.6 |
| 11-03 | 49 / −$678.0 | 77 / +$189.7 | 110 / +$281.4 | −$70.1 |
| 11-10 | 32 / +$444.5 | 15 / +$26.6 | 51 / +$146.4 | +$81.9 |

And what the resolver has been adding lately (`fillResolvedAt`): last 7d 152 legs stamped → 59 filled
(−$160.8) + 93 unfilled (+$343.3). The mechanism is real (legs do move between classes) but the
direction is **not** one-way at this n.

## 6. Why the credit cannot simply be swapped: 94% of the lifetime book has no stamp

All-time (what the dashboard header and the EOD actually print):

| lane | basis | legs | cost | PnL | ROI |
|---|---|---|---|---|---|
| C-200 | booked rows | 2,839 | $28,723.6 | +$5,659.6 | +19.7% |
| C-200 | unadjudicated | 2,047 | $16,752.1 | +$3,789.2 | +22.6% |
| C-200 | confirmed filled | 266 | $3,788.8 | −$426.7 | −11.3% |
| STANDARD | booked rows | 10,011 | $115,223.6 | +$9,225.2 | +8.0% |
| STANDARD | confirmed filled | 0 | — | — | — |
| **ALL** | booked rows | 12,850 | $143,947.2 | **+$14,884.8** | +10.3% |
| **ALL** | confirmed filled | 266 | $3,788.8 | **−$426.7** | −11.3% |

Swapping the lifetime credit to confirmed-filled would publish **−$426.7 lifetime instead of
+$14,884.8** — 2.9% of the book. That is not a correction, it is a statement that 97% of the history
predates the instrument and can never be adjudicated. **The lifetime number must stay on its booked
basis with its coverage printed beside it; only the forward credit moves.**

The same column also arms a risk gate. `BotBankroll.realizedPnl` for C-200 is **+$5,659.6 — exactly
the booked-rows sum** (so the rollup carries the +$3,789.2 unadjudicated). With RuleSet v73
(`ddBasis='realized'`, `maxGrossExposureUsd=1000`), `effectiveExposureCap` = $1,000 + 50%×(NW −
principal) = **$3,829.8** today and **$1,935.2** if the unadjudicated PnL were excluded — a **−$1,894.6**
move in a risk number with **no** operational effect right now (C-200 open: 7 legs / $82.86).

## 7. Every surface that reads the column

| surface | where | what it does with the number | basis today |
|---|---|---|---|
| **rung / advance gate** | `query_bankroll.js:109-141` | settled 7d sum → phase advance, printed gate line | booked rows |
| dashboard ladder | `src/app/page.tsx:297-340`, `316-323` | T+0 7d sum → rung tick | booked rows |
| analytics ladder | `src/app/analytics/page.tsx:48-68`, `103-161` | same, second copy | booked rows |
| EOD report | `src/lib/report.ts:526-720` | per-lane realised, today's PnL, tail, wallet attribution | booked rows |
| performance page | `src/app/performance/page.tsx:41-63` | win rate + band/hour PnL | booked rows |
| capital / NW series | `src/lib/capital-data.ts:39-130` | equity curve, `/capital` page | booked rows |
| exposure cap arming | `src/lib/wallet-cap-arming.ts:198-215` (via rollup) | cap NW → `maxGrossExposureUsd` | booked rows |
| **auto-tuner wallet downgrade** | `src/lib/rule-updater.ts:226-240` | `sum(realizedPnl) < −$10` **and ≥3 legs → wallet `track`→`watch`** | booked rows |

The last row is not reporting. On the confirmed-filled basis **3 more wallets would be downgraded**
beyond positions-only (2 of them not blacklisted today: `0x26165d…` raw −$5.6 → filled −$55.2;
`0xda3407…` raw **+$51.4** → filled −$11.2). That changes who we copy and is therefore **not** part of
this apply (FLAG 4).

## 8. Proposal — three stages, five flags

**Stage 1 — PRINT (no figure moves, ~2h).** Every surface in §7 prints `filled / unadjudicated /
unfilled` counts beside its number, and the rung's gate line names its basis and its coverage
(`credit basis: confirmed-filled, 96% of new C-200 legs stamped, 0% of STANDARD`). No number changes
value; four lines are added. This is the card's own "print all four bases for one week" requirement,
and it is the only part that is safe to ship before the adjudication repairs.

**Stage 2 — CREDIT (the rung and the EOD's forward window, ~2h).** The credited basis becomes
`confirmed filled`; `unadjudicated` is printed beside it and **never credited**; `unfilled` stays
excluded. Effect, measured: rung gate sum **+$207.0 → +$96.1** (phase unchanged, Phase 1 either way);
EOD regime line **+$22.4/day → −$21.3/day**; last-7d line **+$58.9 → +$32.4/day**. Ship only after
Stage 3(a), or C-200's credit silently drops 18 real legs to a link bug.

**Stage 3 — COVERAGE (separate Lane A applies, in this order).** (a) C-200 link repair: bounded retry
on the write path + a backfill restricted to `(decisionJournalId, marketId, outcome, side)` matches
(18/18 of the regime legs qualify; 2,047 historical legs are the population to size it against) —
then re-run the resolver and stamp. (b) STANDARD booth promoted to a stamping write on the **book
arm** (§4), which moves ~93% of the 123 unadjudicated legs to `unfilled` and removes ~+$273.9.

**Flags — each overridable, with the number that changes:**

- **FLAG 1 — credit basis.** Recommended: `confirmed filled`. Alternative `positions only` is
  refuted by §3/§4 (it is the unadjudicated basis plus what happens to be stamped). Status quo is
  what this card exists to end. *Changes: the rung's gate sum (−$110.9) and the EOD regime line
  (−$43.7/day).*
- **FLAG 2 — what a 0%-coverage lane contributes.** Recommended: print `not measurable` and credit
  nothing for it (STANDARD). Alternative: credit its booked number labelled `unadjudicated` — that is
  today's behaviour and it is what makes the ladder claim +$22/day. *Changes: $389.7 of regime PnL.*
- **FLAG 3 — STANDARD fill convention when the booth is promoted.** Recommended: book arm (taker at
  the booked price), consistent with C-200's resolver. Alternative: tape arm — requires recording
  per-leg prints first; not computable today. *Changes: 9 legs +$92.3 kept vs 112 legs +$273.9 removed.*
- **FLAG 4 — auto-tuner downgrade basis.** Recommended: **leave on `raw`** and card it separately
  (it changes who we copy). *Changes: 3 wallets, 2 of them live today.*
- **FLAG 5 — the lifetime number.** Recommended: **do not move it.** Keep `booked rows` with the
  coverage printed beside it; publishing −$426.7 lifetime is a coverage statement, not a PnL.
  *Changes: +$14,884.8 vs −$426.7 on every header/EOD total.*

Cost: Stage 1 **2h**, Stage 2 **2h**, Stage 3(a) **2h**, Stage 3(b) **4h**. No RuleSet value, no clip,
no gate threshold is touched by any of them.

## 9. Refutation — what would kill this proposal

Pre-registered, all re-read with the commands at the top:

1. **Forward adjudication of the unadjudicated class.** If a 150-leg forward sample of STANDARD legs,
   adjudicated on the book arm, shows **≥60% filled** (today: 7.4% on 121 of the card's own legs),
   the class is real positions and the exclusion is withdrawn.
2. **C-200 coverage collapse.** If coverage of legs opened in the last 14 days falls below **90%**
   (today: 95.4% C-200, 0.0% STANDARD, 71.9% combined), the filled-only credit is measuring a
   minority sample and Stage 2 does not ship.
3. **Cosmetic test for the rung.** If the filled and positions-only gate sums stay within **$10** of
   each other for 7 consecutive reads, Stage 2 is cosmetic for the rung (today: $96.1 vs $106.1 =
   $10.0, i.e. exactly at the bar) and the change should be shipped for the **EOD**, not for the rung,
   with that stated in the card.
4. **Magnitude claim.** If the filled class's bootstrap CI stops spanning zero on a forward sample
   ≥200 legs, its ROI may be quoted as a loss; until then it may not.

## 10. Lane discipline

Lane A, nothing applied: no RuleSet read or write, no `apply-v*`, no prisma write, DB opened
`mode=ro`, the booth artifact read-only, no merge. Instrument committed with this doc:
`scripts/ladder-credit-basis-audit.py` (§L0-L9 above; every table in this document comes from it, and
§L2b reproduces the production report's own day buckets to the cent). The card's instrument
`scripts/profit-supply-ladder.py` §S6 was re-run and agrees on all four bases.
