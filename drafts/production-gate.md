# The copy-lane production gate (G1–G5) — and the current book scored against it

**Card:** `t_59b0ffce` · **branch:** `wt/production-gate` · **measurement + design document**

**Nothing applied.** No rule, no size, no gate, no booking changed. No write to `prisma/dev.db`
(every read is `file:…?mode=ro` + `PRAGMA query_only=1`), no `apply-v*.ts`, no cron, nothing merged,
nothing committed.

| artifact | absolute path |
|---|---|
| this draft | `…/polymarket-copybot/.worktrees/t_59b0ffce/drafts/production-gate.md` (served copy at `…/polymarket-copybot/drafts/production-gate.md`) |
| the scorer | `…/polymarket-copybot/.worktrees/t_59b0ffce/scripts/production-gate-read.py` |
| machine copy of the run | `…/polymarket-copybot/.worktrees/t_59b0ffce/drafts/production-gate-run-20261112.json` |

```
python3 scripts/production-gate-read.py --json drafts/production-gate-run-20261112.json
# run 2026-11-12T13:40:26-0600 · db prisma/dev.db 13.5 GB mode=ro · 12,825 settled legs
```

Every figure below is a line of that run. Section numbers in the margins (`[G1]`, `[G2]`, …) name the
block it came from. No number is quoted without its `n`, and booked is never pooled with fill-aware.

---

## 0. The one-paragraph version

The copy lane has a **progress** bar (the ladder phase gate) and no **readiness** bar. Those are
different questions, and the second one is why the production horizon keeps receding. This document
writes the readiness bar as five conditions that must all hold, and scores today's book against them.
The current book fails or has not yet established **four of five conditions in both lanes**. The only
condition that passes is the one that was already true on 2026-10-29 — drawdown — and even that has
narrowed (C-200 7.55% → 14.05% of peak). The two load-bearing failures are:

* **G2 edge** — remove each lane's ten best legs and the book **loses money on the fill-aware basis**:
  C-200 **−6.1%** of notional on 2,810 legs, STANDARD **−0.6%** deduped (`+6.5%` raw with a CI that
  straddles zero). In the trailing 30 settled days C-200's ex-top-10 fill-aware ROI is **−22.8%**
  (CI −31.4…−13.3). The edge is ten markets wide.
* **G3 capacity** — the pooled finished book earns **$10.45 per $1k-capital-day fill-aware** against
  the operator's **$142.86** floor: **13.7x short**. $500/day therefore needs **$47,853** of open
  capital (13.7x the $3,500 floor), and at the floor today's rate yields **$36.57/day = 7.3%** of the
  $500 target. This is the central fact about the lane and it is not an opportunity.

---

## 1. The gate

Five conditions, all required. A single FAIL or NOT-YET blocks funding; there is no weighting and no
scoring — a gate you can trade off is not a gate.

| # | condition | bar | measured on |
|---|---|---|---|
| **G1** | SAMPLE | ≥ 300 settled legs carrying a **fill-aware** verdict | `PaperTrade.fillStatus` ≠ NULL (filled/unfilled), settled only |
| **G2** | EDGE | **ex-top-10 ROI > 0** on the fill-aware basis | same population, ten largest legs dropped (PnL *and* notional) |
| **G3** | CAPACITY | ≥ **$142.86 per $1k-capital-day** ($500/day inside a $3,500 open-capital floor) | `Σ size × hold-days` on the finished book |
| **G4a** | DRAWDOWN | ≤ **20%** peak-to-trough on realized equity | running peak, principal base rule (below) |
| **G4b** | LIVE BRAKE | **25%** — recorded, **not implemented by this card** | — |
| **G5** | DURATION | **90 consecutive days** with no pre-registered refutation firing in that lane | `data/prereg-registry.jsonl` + `prereg-reads.jsonl` |

### G1 SAMPLE — the sample must be positions, not claims

A leg marked `fillStatus='unfilled'` is not a small loss, it is **not a position**: the resolver saw
the book and our level was never reachable. Since 2026-10-28 the live booking does exactly that
(`bookedPnl()` in `src/lib/paper.ts` returns `$0`). G1 asks for 300 settled legs whose PnL is a
verdict rather than an assumption.

What it cannot tell you: **coverage**. A lane can pass G1 while most of its book still books
`p(fill)=1`. The coverage line is printed beside the count for exactly that reason, and read strictly
as *settled positions* the bar is higher than the card states — both numbers appear in §2.

### G2 EDGE — the one condition a lucky market cannot pass

`ex-top-10 ROI` drops the ten largest legs (PnL **and** notional) and recomputes the return on what is
left. If a book only clears zero because of ten markets, it is not an edge; it is a tail with a
bookkeeping habit.

Measured on **both** bases and never pooled:

* **fill-aware** — `unfilled` legs contribute $0 PnL and $0 notional (the position we would own);
* **booked** — `p(fill)=1`, every dispatched leg a position (the number that overstates).

Verdict rule (recorded, so a later read cannot choose it): **PASS** needs ex-top-10 fill-aware ROI > 0
on **both** the raw and the deduped arm *and* the raw market-clustered CI lower bound > 0; **FAIL**
needs both arms ≤ 0; anything else is **NOT-YET**. NOT-YET blocks funding exactly like FAIL.

### G3 CAPACITY — so the arithmetic is confronted, not discovered after funding

Operator's setting: *"capacity floor: $3,500 open capital at the $500/day target"*, which resolves to

```
required capacity  = ($500 / $3,500) × 1000 = $142.86 per $1k-capital-day
```

`$500/day` is rung 2 of the `$250 → $5,000/day` ladder, so this is the **current** rung, not the
terminal one. Capacity is `PnL / Σ(size × hold_days) × 1000`: profit per dollar of open capital per
day. Two things must be said in the same breath:

* the full-book rate **and** the **ex-top-10** rate. A lane whose capacity disappears once its ten
  best legs are removed has no capacity; it has a lottery ticket that already paid;
* the **open capital the target implies** — both rungs — against the open notional actually deployed,
  because a "capacity floor" that is *below* today's deployment requires the book to **deploy less
  while earning more per dollar-day**.

### G4a DRAWDOWN — 20% evidence bound, chosen before the fact

Operator: *"20% evidence, 25% live brake"*. G4a is the **evidence** bound. On the realized equity
curve — `equity = principal + cumulative settled realized PnL` — measured against the **running peak**,
never against starting capital and never against the final peak. **Base rule:** a drawdown only counts
once equity ≥ that lane's principal; an early dip on a $1,900 book is not a 20%-of-peak fall.

### G4b LIVE BRAKE — 25%, recorded only

Arming a brake changes what the bot does. This card records the number and the five things that would
have to be built — it does **not** implement them, and does not pick the stop semantic:

1. a persisted **high-water mark per lane** (the `BotBankroll`/watermark mismatch on C-200 is what an
   unpersisted peak looks like);
2. a check that runs **before admitting a new leg**, not only at EOD — an EOD-only brake is a report,
   not a brake;
3. a **stop semantic**: refuse new admissions, or close open legs? They are very different; the
   operator has not chosen;
4. the **same principal base rule as G4a** — measured below: without it C-200 reads **27.29%** today,
   so a 25% brake applied to the unbased curve would have fired on a book that was never 25% down;
5. an explicit **reset / re-arm** procedure — a brake nobody can re-arm is a permanent shutdown.

### G5 DURATION — 90 consecutive clean days

Counting starts at the last pre-registered refutation that fired **in that lane**. Two consequences
worth stating up front: a lane with **no** lane-scoped pre-registered gate can never start its clock,
and a refutation that fires on day 89 resets it. The measurement is the registry, not memory.

---

## 2. The score

### 2.1 Verdict matrix — 2026-11-12, 12,825 settled legs

| lane | G1 sample | G2 edge | G3 capacity | G4a drawdown | G5 duration |
|---|---|---|---|---|---|
| **BANKROLL_200** | **PASS\*** | **FAIL** | **NOT-YET** | **PASS** | **NOT-YET** |
| **STANDARD** | **NOT-YET** | **NOT-YET** | **NOT-YET** | **PASS** | **NOT-YET** |

\* G1 passes on **fill verdicts** (575 ≥ 300) but the count of settled **positions** is **192 / 300** —
if G1 is read as positions it is NOT-YET. Both readings are printed in §2.2.

**Neither lane is fundable.** Two lanes, two different reasons: C-200 has a sample and no edge;
STANDARD has neither a sample nor a measured edge.

### 2.2 G1 — sample and coverage

**BANKROLL_200** `[G1]` — 2,820 settled legs raw / 2,144 deduped:

| arm | n | stamped (filled+unfilled) | % legs | % notional | filled | unfilled | NULL |
|---|---|---|---|---|---|---|---|
| lifetime | 2,820 | **575** | 20.4% | 27.5% | 192 | 383 | 2,245 |
| trailing 30d | 405 | 292 | **72.1%** | **62.7%** | 88 | 204 | 113 |
| lifetime deduped | 2,144 | 569 | 26.5% | 32.9% | 190 | 379 | 1,575 |

The lifetime stamp rate is low for a structural reason: the resolver needs an L2 book window, and the
book only exists from 2026-09-26, so the older 2,245 NULL legs are **unstampable**, not "unfilled". The
forward population is the 30d arm, where coverage is **72.1% of legs / 62.7% of notional**.

Fill-aware booking, ledgered (`booked − fill-aware`):
**+$1,001.10** removed over 383 unfilled legs, of which **$172.44** is already zeroed in the stored
column (post-flip stamps) and **$828.66** is *still carried* there on pre-flip stamps. That residual is
why the stored `BotBankroll` identity (principal $1,900 + realized $5,638.38 = **$7,538.38**) sits
between the booked reconstruction (**$7,710.82**) and the fill-aware one (**$6,709.72**). The card's
inherited "61% of booked C-200 PnL sat on legs that never filled" is the **2026-10-26 snapshot**, when
the book was $1,313.66; today the same ratio is **17.2%** ($1,001.10 of $5,810.82) because the book
grew and the flip went live.

**STANDARD** `[G1]` — 10,005 settled legs raw / 3,712 deduped:

| arm | n | stamped | % legs | % notional |
|---|---|---|---|---|
| lifetime | 10,005 | **0** | 0.0% | 0.0% |
| trailing 30d | 1,090 | **0** | 0.0% | 0.0% |
| lifetime deduped | 3,712 | **0** | 0.0% | 0.0% |

Zero. The fill booth has stamped legs into an artifact (`data/standard-fill-stamp-20261029.jsonl`:
880 legs in scope, **251** with book evidence, **74** reachable at the booked price = 29.5%) but **no
STANDARD leg in `PaperTrade` carries a stamp** (0 of 10,005), so every STANDARD leg still books
`p(fill)=1`. G1 is not "nearly there" on this lane; on the DB basis it is at zero, and the booth's own
best population (251) is itself below 300.

### 2.3 G2 — edge on both bases

**BANKROLL_200** `[G2]`

| arm | basis | n | notional | PnL | ROI | ex-top-10 n | ex-top-10 PnL | ex-top-10 ROI | CI |
|---|---|---|---|---|---|---|---|---|---|
| lifetime raw | booked | 2,820 | $28,185.09 | +$5,810.82 | +20.6% | 2,810 | −$1,087.03 | −4.0% | −15.0…+12.0% |
| lifetime raw | **fill-aware** | 2,820 | $28,185.09 | +$4,809.72 | +17.1% | 2,810 | **−$1,678.21** | **−6.1%** | −16.5…+7.2% |
| lifetime deduped | fill-aware | 2,144 | $23,290.27 | +$5,313.82 | +22.8% | 2,134 | −$1,174.11 | −5.2% | −14.2…+9.1% |
| trailing 30d | booked | 405 | $9,209.57 | +$153.80 | +1.7% | 395 | −$2,636.44 | −30.2% | −41.9…−14.4% |
| trailing 30d | **fill-aware** | 405 | $9,209.57 | −$107.80 | −1.2% | 395 | **−$2,016.87** | **−22.8%** | −31.4…−13.3% |

The **top-10 contribution** is **+$6,487.93 across ten different markets** (booked: +$6,897.85), best
leg +$1,513.33 in `will-alibaba-have-the-…`. Ten markets carry the entire lane: remove them and the
fill-aware book is −$1,678.21. The 30d arm is worse on every column and its CI **excludes zero** — the
direction of travel is negative, not flat.

Where the ex-top-10 fill-aware book earns and loses (entry-price bands, n and notional per row):

| band | n | notional | PnL | ROI |
|---|---|---|---|---|
| 0.00–0.10 | 158 | $5,963.25 | **−$1,689.80** | **−28.3%** |
| 0.10–0.20 | 172 | $4,698.39 | −$85.36 | −1.8% |
| 0.20–0.40 | 652 | $6,650.68 | +$289.40 | +4.4% |
| 0.40–0.60 | 1,055 | $4,361.11 | −$280.75 | −6.4% |
| 0.60–0.80 | 595 | $3,432.53 | −$8.87 | −0.3% |
| 0.80–1.01 | 178 | $2,327.40 | +$97.17 | +4.2% |

One band — sub-$0.10, 158 legs, **21.7%** of the ex-top-10 notional — is **−$1,689.80**, i.e. slightly
more than the whole ex-top-10 loss. Remove that band alone and the remaining book is **+$11.59**. That
is not an edge: it is the loss being concentrated in one place.

**STANDARD** `[G2]`

| arm | basis | n | notional | PnL | ROI | ex-top-10 n | ex-top-10 PnL | ex-top-10 ROI | CI |
|---|---|---|---|---|---|---|---|---|---|
| lifetime raw | booked = fill-aware | 10,005 | $115,160.58 | +$9,288.13 | +8.1% | 9,995 | +$7,448.33 | **+6.5%** | −3.5…+17.3% |
| lifetime deduped | booked = fill-aware | 3,712 | $44,952.58 | +$1,512.81 | +3.4% | 3,702 | **−$260.03** | **−0.6%** | −4.7…+3.9% |
| trailing 30d | booked = fill-aware | 1,090 | $12,421.38 | −$206.68 | −1.7% | 1,080 | −$1,016.74 | **−8.3%** | −22.9…+7.3% |

Booked equals fill-aware here **only because the lane has no fill verdicts** (G1) — that is the
measurement, not a coincidence. The raw point estimate is positive (+6.5%) with a CI that straddles
zero; dedupe flips the sign (−0.6%); the trailing 30 days are −8.3%. **The sign is not established**,
and today's STANDARD book cannot be said to have a positive ex-top-10 edge.

The one independent fill-aware read on this lane comes from the booth's own evidence (251 book-stamped
legs, 2026-10-29 snapshot, reachability at the booked price): **+$626.23 on $4,476.78 = +14.0%**, and
**ex-top-10 −$197.11 on 241 legs = −4.6%**. Same shape as C-200 — a tail, not an edge — on a small,
stale sample, and reachability is an *upper* bound (no queue position, no size).

### 2.4 G3 — capacity

**Per lane, finished book, raw** `[G3]`:

| lane | basis | capital-days | settled legs | PnL | $ / $1k-capital-day | ex-top-10 $ / $1k-cap-day |
|---|---|---|---|---|---|---|
| BANKROLL_200 | booked | 49,052 | 2,820 | +$5,810.82 | **$118.46** | −$22.16 |
| BANKROLL_200 | fill-aware | 49,052 | 2,820 | +$4,809.72 | **$98.05** | **−$34.21** |
| STANDARD | booked = fill-aware | 1,300,188 | 10,005 | +$9,288.13 | **$7.14** | +$5.73 |

**Pooled** (the basis the inherited $11.14 used — both lanes, one capital pool):

| basis | capital-days | settled legs | PnL | $ / $1k-capital-day | required | gap |
|---|---|---|---|---|---|---|
| booked | 1,349,239 | 12,825 | +$15,098.95 | **$11.19** | $142.86 | **12.8x** |
| fill-aware | 1,349,239 | 12,825 | +$14,097.85 | **$10.45** | $142.86 | **13.7x** |

The booked pooled arm reproduces the inherited figure to **$0.05** ($11.19 vs $11.14) and the gap to
one decimal (12.8x), which confirms the convention the operator's amendment was written against. The
honest figure is the fill-aware one: **$10.45 = 13.7x**.

Consequences, printed rather than buried:

* **$500/day at today's fill-aware rate needs $47,853 of open capital** — 13.7x the $3,500 floor;
* **at the $3,500 floor today's rate yields $36.57/day = 7.3%** of the $500 target;
* **$5,000/day (terminal rung) needs $478,527** of open capital = **101x** today's **$4,735.24** open
  notional (booked arm: $446,799 = 94x);
* the **$3,500 floor is below the $4,735.24 actually deployed** (STANDARD $4,317.52 across 391 legs +
  C-200 $417.72 across 10). G3 as set requires the book to **deploy less while earning 13.7x more per
  dollar-day**. Those two requirements point in opposite directions and no sizing change reconciles
  them; only a change in what is traded (turnover and edge) can.

Per-lane, the split is the story: C-200 holds capital **1.74 leg-days per dollar** deployed
(49,052 capital-days / $28,185.09) against STANDARD's **11.29** (1,300,188 / $115,160.58) — **6.5x**
faster turnover — and earns **13.7x** more per capital-day ($98.05 vs $7.14). But **its capacity is
entirely tail-carried**: with its ten best legs removed it is **−$34.21 per $1k-capital-day**. A lane
cannot be funded on capacity that only exists inside its top ten legs.

### 2.5 G4a — drawdown

**Daily** end-of-day realized equity curve, principal base rule `[G4a]`:

| lane | principal | equity (fill-aware) | marks | max DD | peak → trough | no base rule | now off peak |
|---|---|---|---|---|---|---|---|
| BANKROLL_200 | $1,900.00 | $6,709.72 | 100 | **14.05%** (−$994.10) | 2026-10-18 → 2026-11-10 | 27.29% | 5.27% (−$373.60) |
| STANDARD | $11,092.91 | $20,381.04 | 119 | **17.34%** (−$3,816.13) | 2026-07-20 → 2026-09-10 | 17.34% | 7.92% (−$1,753.10) |

Leg-level marks (sensitivity): C-200 14.20%, STANDARD 18.17%. Both PASS the 20% bound.

Three things the numbers say that a PASS hides:

1. **C-200's drawdown has more than doubled** since the operator's 2026-10-29 read (7.55% → 14.05%),
   and it is the *recent* fall (10-18 → 11-10), not a young-book artifact.
2. **The base rule carries C-200**: 27.29% unbased vs 14.05% based. A 25% brake applied to the unbased
   curve would have fired on this book. G4b must inherit the rule or it will trip spuriously (open
   question 4 in §1).
3. **STANDARD's 17.34% is the tight one** — 2.66pp of margin — and its worst fall is 12 months old
   (Jul–Sep), i.e. the bound is being held by an old recovery, while the lane currently sits 7.92% off
   its peak and 30-day PnL is **−$206.68**.

### 2.6 G5 — duration

**BANKROLL_200** `[G5]` — 2 lane-scoped pre-registered gates + 1 all-lane:

| gate | scope | frozen | state | fired | detail |
|---|---|---|---|---|---|
| `entry-floor-a` | lane | 2026-10-17 | FROZEN | no | never fired (n=31 frozen across 19 reads) |
| `c200-ladder-window-1025` | lane | 2026-10-24 | **REFUTED** | **yes** | 2026-11-09; value **$597.46** on n=53 vs threshold $1,750 |
| `price-side-inversion` | all-lane | 2026-11-08 | UNGRADEABLE | no | never fired |

Last lane-scoped refutation fired **2026-11-09** → **3 of 90 days**. Earliest possible pass
**2027-02-07** if nothing else fires. What fired: the C-200 ladder advance gate for the pinned
2026-10-25…10-31 window — the seven settled days summed **$597.46** against the $1,750 the $250/day
rung required.

**STANDARD** — **0** lane-scoped gates, 1 all-lane (`price-side-inversion`, never fired). No
pre-registered refutation has ever been registered for this lane, so **the 90-day clock cannot start**.
"0 days" is the honest reading, not "90 days so far".

---

## 3. What would have to change for a pass — countable

Each item is a number and the measurement that produces it. None of them says "improve the model".

### BANKROLL_200

| # | gate | now | pass needs | measurement |
|---|---|---|---|---|
| 1 | G1 | 192 settled **positions** (575 verdicts) | **300 positions** | count of settled legs with `fillStatus='filled'`; cadence **4.0 filled/day** over 48 days → +108 legs ≈ **27 days, ~2026-12-09** |
| 2 | G2 | ex-top-10 fill-aware **−6.1%** (−$1,678.21 on $27,433.35) | **> 0**, both raw and deduped arms, CI lower bound > 0 | same run, `G2 lifetime raw fillaware`. Mechanism with a number: the sub-0.10 band alone is **−$1,689.80 (−28.3%)** on 158 legs / $5,963.25; ending that band's loss at $0 makes the rest of the book **+$11.59** — i.e. it clears zero by $11.59, which is not yet evidence of anything |
| 3 | G2 (current regime) | trailing-30d ex-top-10 fill-aware **−22.8%** (CI −31.4…−13.3) on 395 legs | **> 0** on the same 30d arm | `G2 30d raw fillaware`; a cumulative-lifetime read alone would hide this |
| 4 | G3 | **$98.05** / $1k-capital-day; ex-top-10 **−$34.21** | **≥ $142.86** and ex-top-10 > 0 | same run, `G3 fillaware`: at constant PnL, capital-days must fall **49,052 → ≤ 33,660 (−31.4%)**; at constant capital-days, PnL must rise **+$2,199 (+45.7%)**; ex-top-10 capacity needs the full **+$1,678.21** |
| 5 | G4a | **14.05%** | stay **≤ 20%** | daily curve; **5.95pp** of room, and no-rule reads 27.29% — the surface is thinner than the verdict suggests |
| 6 | G5 | **3 / 90 days** | 90 consecutive clean days | `data/prereg-reads.jsonl` for lane-scoped gates; no lane-scoped refutation may fire before **2027-02-07** |

### STANDARD

| # | gate | now | pass needs | measurement |
|---|---|---|---|---|
| 7 | G1 | **0** DB stamps (booth: 251 book-stamped, 74 reachable) | **300** stamped settled legs **in the DB** | (a) a writer that merges booth stamps into `PaperTrade.fillStatus` — today the chain does not; (b) then +49 stamped legs beyond the booth's 251, at its own 28.5% coverage of in-scope legs (251/880) → **~172 new in-scope settled legs** |
| 8 | G2 | deduped ex-top-10 **−0.6%** (−$260.03 on $44,811.38); raw **+6.5%** with CI **−3.5%** | both arms > 0 **and** raw CI lower bound > 0 | `G2 lifetime deduped fillaware` + CI; the deduped gap is small (+0.58pp) but the CI requirement is the binding one: the lower bound must move **−3.5% → > 0**, and the 30d arm (**−8.3%**, CI −22.9…+7.3) must stop pointing the other way |
| 9 | G3 | **$7.14** / $1k-capital-day | **≥ $142.86** | at constant PnL, capital-days must fall **1,300,188 → ≤ 65,009 (20.0x faster turnover)**; at constant capital-days, PnL must rise **$9,288 → ≥ $185,763**. The lane's long-dated instruments are the mechanism (median time-to-resolution ~115 days, measured elsewhere), so this is an instrument-selection question, not a sizing one |
| 10 | G4a | **17.34%** | stay **≤ 20%** | daily curve; **2.66pp** of room, worst fall 2026-07-20 → 09-10, currently 7.92% off peak |
| 11 | G5 | **0** lane-scoped gates → clock cannot start | ≥ 1 pre-registered, lane-scoped gate **plus** 90 clean days | `data/prereg-registry.jsonl`: a STANDARD-scoped row must exist and be graded forward before a single day counts |

### Both lanes / gate-level

| # | item | now | pass needs | measurement |
|---|---|---|---|---|
| 12 | G3 reconciled against the live target | **$10.45** pooled fill-aware (13.7x short) | ≥ $142.86 | `LANE-POOLED CAPACITY`; booked arm reproduces the inherited $11.14 at $11.19 |
| 13 | G4b brake | recorded, **not armed** | five build items in §1 + its own approved card | not measurable today; nothing here implements it |
| 14 | the "one tail" problem, stated as one number | C-200 top-10 = **+$6,487.93 across 10 markets**; STANDARD top-10 = **+$1,839.80 across 9 markets** | neither lane's ex-top-N ROI may depend on that concentration | `G2 … top-10` lines; the gate is only passed when the answer survives the removal |

---

## 4. Reality checks (read these before quoting anything above)

1. **Reachability is not a fill.** `fillStatus='filled'` means the book showed our level reachable
   inside the coverage window — no queue position, no size. The fill-aware arm is an **upper bound**
   on what the lanes would own, so every fill-aware ROI here is optimistic, not conservative.
2. **The lifetime fill-aware arm is 27.5% of C-200 notional** (30d: 62.7%). The other 72.5% books
   `p(fill)=1` because the resolver structurally cannot judge legs opened before the L2 corpus. The
   forward-looking read is the 30d column; the lifetime column is what the published book contains.
3. **The booked reconstruction is verified, not assumed**: `size × (currentPrice/entryPrice − 1)`
   reproduces the stored `realizedPnl` on **12,442 / 12,442** settled legs the flip did not zero
   (0 mismatches). Only the `unfilled` legs diverge, by construction.
4. **Raw vs deduped.** RAW (all settled legs) is the published book and the right basis for capital
   productivity — every leg consumed capital and produced PnL. DEDUPED (first leg per
   bot|wallet|market|outcome) is the statistical arm that kills duplicate-accumulation
   pseudo-replication: it removes 63% of STANDARD's settled legs and 84% of its PnL. Both are printed
   everywhere; **a claim that only survives on one arm is not a claim.**
5. **Daily vs leg-level equity.** The daily curve is the risk-relevant one (arrival order inside a day
   is not a risk event). The leg-level arm is printed as a sensitivity and is always slightly worse
   (C-200 14.20%, STANDARD 18.17%).
6. **The inherited card figures are 14 days old and re-measured here, not repeated**: booked/fill-aware
   ex-top-10 −$956.97/−$435.97 was the 2026-10-26 snapshot of a $3,232.83 book; today the same two
   arms read −$1,087.03/−$1,678.21 on $28,185.09. The "30d books" in the card body (STANDARD −$359.72
   on $12,577) are the 2026-10-29 window; today's 30d is STANDARD −$206.68 on $12,421.38. The
   denominators reproduce to the dollar, which is how the convention was confirmed.
7. **Two bookkeeping residuals, both small and both flagged rather than smoothed**: (a) $828.66 of
   pre-flip `unfilled` PnL still sits in the stored `realizedPnl` column, so the `BotBankroll` identity
   for C-200 is neither arm; (b) STANDARD's stored `BotBankroll.realizedPnl` ($9,487.34) is **$199.13**
   above the sum of its leg PnL ($9,288.21) — unexplained, 0.7% of principal, no effect on any gate
   number here because the equity curve uses principal + leg PnL.
8. **Instrument defect found, not fixed** (Lane B candidate, out of scope for this card):
   `scripts/c200-fill-aware-pnl.ts` still computes its **booked** arm from
   `PaperTrade.realizedPnl`, which is now fill-aware for post-flip settlements. Its booked-vs-fill-aware
   comparison therefore silently understates the booked arm on new legs — this document does not use
   that script for the two-basis comparison, it reconstructs both arms per leg
   (`production-gate-read.py`, verified per §4.3). The printed `REPRODUCE_SQL` in that script is still
   correct as a population query.
9. **The STANDARD booth snapshot is 2026-10-29** (its later runs scoped to legs opened after
   2026-11-12T10:00Z and captured 0). The C-200 print-through snapshot is current (2026-11-12T11:23Z,
   802 intents, book-reach 16.6%), and its independent reach rate is a sanity check on the DB stamps.
10. **Verdicts are computed, not chosen**: the G2 rule and every threshold live at the top of
    `scripts/production-gate-read.py` as named constants (`G1_MIN_LEGS`, `G3_REQUIRED_PER_1K`,
    `G4A_BOUND`, …). Changing a bar means changing the constant, in a diff, visible.

---

## 5. Reproduce

```bash
cd ~/polymarket-copybot/.worktrees/t_59b0ffce
python3 scripts/production-gate-read.py                                   # tables + verdicts
python3 scripts/production-gate-read.py --json drafts/production-gate-run-20261112.json
```

Read-only by construction: `sqlite3` URI `mode=ro` + `PRAGMA query_only=1`, no Prisma client, no
RuleSet read for a decision, no writes anywhere. The script resolves the populated 13.5 GB
`prisma/dev.db` in the primary tree when run from a worktree (and prints which file it opened), and
resolves the cron-written artifacts (`data/prereg-*.jsonl`, `data/c200-printthrough.jsonl`,
`data/standard-fill-stamp-*.jsonl`) beside that DB rather than from the worktree's stale copies.

Derived figures in this document — differences, `x`-multiples, day counts, "what would have to
change" thresholds — are arithmetic on lines the run prints, and each one names its operands
(e.g. `$47,853 / $3,500 = 13.7x`; `192 filled / 4.0 per day = 48 days`). Nothing is carried over from
an earlier draft: the card's inherited figures are quoted only where they are explicitly being
compared against today's, with the date of the old measurement attached.

---

## 6. What this document does **not** do

* It does not arm G4b, and it does not choose the brake's stop semantic.
* It does not change a rule, a size, a band, a gate or a booking — including the sub-$0.10 band that
  the C-200 measurement points at. That is a Lane A question with its own card and its own
  before/after; nothing here recommends it.
* It does not rule on whether C-200's fill-aware basis or the booked basis should be the published
  headline. It states both, every time, with the flip ledger that reconciles them.
* It does not treat a PASS as progress. G4a was already passing on 2026-10-29 and is the only
  condition that was; its margin has narrowed.
