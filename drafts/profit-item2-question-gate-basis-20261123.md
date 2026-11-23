# Item 2's question-class gate — pre-register the tolerance, the population and the write-off scope

**Card:** `profit-item2-question-gate-basis` (approval `apr-profit-item2-question-gate-basis`,
approved 2026-11-23T13:22:25Z) · **Lane A — PROPOSAL ONLY, nothing applied** ·
**Read:** 2026-11-23T13:02:42Z (stamp `standard-fill-stamp.jsonl ranAt=2026-11-23T13:02:42.334Z`) ·
**Instrument:** `scripts/profit-question-fill-read.py` (extended this run; artifact
`data/profit-question-fill-read.json`)

**Revision 2 (2026-11-23, after review).** §2, §3, §4 and §8 prose corrected against the
instrument's own output: the "mid is never a grid price" claim, the crosstab's status as an
invariant rather than evidence, the 0.05–0.20 price band, the 543-leg denominator, the flow share,
the book-stamp count, and the "same span" framing. No published count, ROI, CI or arm percentage
changed; two read-only cells did — the §2 mid-match tolerance (≤0.01c → ≤0.05c) and the readiness
horizon (27 → ~23 months) — and no line of the §6 rule text changed.

**Revision 3 (2026-11-23, after review).** §8's flow sentence now names a basis per figure instead
of welding a STANDARD leg share to a both-lane dollar share, and §2's arm-B row / §3 state the
sub-tick remainder range the instrument actually produces: **0.05–0.90c** over the 40 off-grid legs,
with **10 of the 40 above 0.50c**. The grid construction bounds the remainder at 0.95c, not 0.50c;
capping arm B at 0.50c still yields 46/89, so again no published count, ROI, CI or arm percentage
moved and the §6 rule text is untouched.

**Revision 4 (2026-11-23, after review).** §8's flow trend now reads the series as it prints instead
of inverting it — the class fell from the backfilled September epoch and then rose **8 → 30** while
the lane was flat (**146 → 143**) — and the "coverage can only improve forward" line is replaced by
the actual arithmetic (33 un-stamped legs, all September; ≥90% needs ~23 months of new legs). F4 and
§7 now carry the recommended bar's horizon, the fact that it clears on essentially the same date as
the ≥300 bar it replaces, and the card's own **~2h stamp extension** as the path that actually
un-parks item 2; F4 is now justified on the coverage principle rather than on timing. No published
count, ROI, CI or arm percentage changed and no line of the §6 rule text changed.

## Key insight

The tolerance is not a rounding knob — it names an **execution model**, and only the arm that grants
a *full tick of price improvement* flips the verdict. On the booked-mid basis the gate reads **36.0%**;
on the venue's own tick grid it reads **51.7%**; only a flat **+1c of slack** reaches **80.9%** — the
29.2pp between the last two is pure slack, not grid alignment. Both non-arbitrary bases **FAIL** the
60% conjunct on today's n. That does not make the choice idle: under §6 the published state stays
**NOT DECIDABLE** until the coverage bar clears (73% < 90%), and on the day it clears the
pre-registered tolerance is what decides PASS versus FAIL. Pre-registering it now is the point —
after the bar clears, the reading that gets picked will be the one that was written down first.

Two population facts matter more than the tolerance and must ride in the same pre-registration:

1. **The instrument judges the lane that owns 2.1% of the class's post-corpus profit.** Post-corpus
   question PnL is **+$4,635.83**, of which **BANKROLL_200 carries $4,539.09 on 650 legs** and
   STANDARD **$96.74 on 425 legs**. The fill stamp is STANDARD-only, so item 2's verdict is being
   computed on the small half of the class.
2. **The "$6,200" is 25% pre-corpus and is not what the gate measures.** All-time both lanes is
   **+$6,180.86** (n=2,939); post-corpus both lanes is **+$4,635.83**; the STANDARD post-corpus
   class the stamp can see is **+$96.74**. A write-off sized on the all-time balance would be an
   accounting entry against July–August flow, decided by a September–November fill read.

## 1. What item 2's rule says, and what it leaves unstated

> "If ≥60% of the question-market legs tape out as filled at non-negative ROI, the profit is real;
> otherwise it is written off permanently."

Unstated: (a) the **price tolerance** that makes "filled" testable; (b) the **population** (which
lanes, which era, settled or not); (c) the **coverage bar** under which a point estimate may be
turned into a permanent write-off. Today (a) is what decides FAIL vs PASS the moment (c) clears,
(b) decides whether the gate is looking at the profit at all, and (c) decides whether the answer
arrives this quarter or in two years.

## 2. Mechanism — the booked level is a MID, and a mid is not a tradable price

`PaperTrade.entryPrice` is "the quote STANDARD read at scoring time and booked"
(`scripts/standard-fill-stamp.ts`, `basis.decisionPrice`); `src/lib/paper.ts:53-55` derives shares
from it. The stamp's per-bucket record carries both the **best ask** and the **mid**. Measured on the
89 settled, stamped question legs:

| fact | value |
|---|---|
| booked price equals the mid of the min-ask bucket (≤0.05c) | 32/89 (36.0%) |
| that mid sits exactly on the 1c grid | 37/89 (42%) overall; 20 of the 32 mid-booked legs |
| min ask − mid, same bucket | median **+1.00c**, range 0.00–4.95c (ask ≥ mid holds with 0 violations across all 1,848 stamped bucket pairs) |
| booked level off the 1c grid (sub-tick remainder > 0) | 40/89 (45%); 49/89 sit on the grid |
| crosstab `booked==mid` × `reachable at tol 0` | (mid, reached) **0** · (mid, not) 32 · (off-mid, reached) 32 · (off-mid, not) 25 |

**The zero in that crosstab is an arithmetic invariant, not a finding.** In every bucket the ask is
≥ the mid (0 violations in 1,848 stamped bucket pairs), and the stamp pairs the *minimum* ask with
the mid **of the bucket it occurred in** — so `booked − mid ≥ ask − mid` holds by construction on
every leg. A leg booked at its mid can therefore pass tol 0 only if ask == mid (a locked book), and
measured that way **0 of 32** mid-booked legs pass. That invariant is still what carries the
argument, because it means tol 0 is not testing fillability on mid-booked legs at all — it rejects
them by construction. The rejection is also *not* an off-grid artifact: 37 of the 89 legs carry the
min-ask bucket's mid exactly on the 1c grid (a 2c spread puts it there: 0.09/0.11 → 0.10), including
20 of the 32 mid-booked legs. On the other side, all 32 tol-0 passes are off-mid legs — 32 of the
57, or 56% — and **10 of them printed with the min ask exactly at the booked price** (a genuine
touch at our level, not a later dip). Across the 32 passes the booked level sits a median **+1.50c**
above the mid and the deepest dip through the booking is 6.5c. tol 0 therefore measures *the booked
level plus how far the market later traded through it*, on a population from which mid-booked legs
are mechanically excluded; it is a booking-and-path statistic, not a conservative fill test.

The bar is 89 legs, n small enough that every arm's ROI interval spans zero:

| arm | tolerance rule | reachable | reachable-cohort ROI | 95% CI (mkt-clustered) | ex-top-3 |
|---|---|---|---|---|---|
| **A** tol 0 (maker at the booked mid) | 0.00 | **32/89 = 36.0%** | +74.7% | [−21.5, +212.2] | −$76.24 |
| **B** tick-aligned reachability | leg's sub-tick remainder to the next 1c (0 for the 49 on-grid legs; 0.05–0.90c observed on the other 40) | **46/89 = 51.7%** | +63.4% | [−14.4, +166.0] | −$52.75 |
| **C** flat +1c | +0.01 | **72/89 = 80.9%** | +27.1% | [−32.0, +103.3] | −$217.75 |
| **C'** C re-priced at the ask | +0.01, PnL at the min ask | 80.9% | +33.4% | [−30.1, +117.4] | −$197.12 |
| **B'** B re-priced at the ask | sub-tick, PnL at the min ask | 51.7% | +74.5% | [−11.9, +193.0] | −$22.54 |
| **B''** B priced at the tick-implied ask | sub-tick, PnL at `booked + sub-tick` | 51.7% | **+62.1%** | [−14.6, +163.9] | −$59.67 |

Basis for every row: cost = `simulatedPositionSize` (**dollars at risk**), `realizedPnl` on
`status IN ('closed','resolved')` (TR-15 OR), `isDemo=0`, dedupe first leg per
`bot|wallet|market|outcome`, entry vintage, market-clustered bootstrap 2000 draws. Reachability =
min best-ask across the stamp's lag buckets ≤ the tested level — an **upper bound on fill** (no queue
position, no size). Re-pricing formula (constant dollars at risk, same per-share price path, fewer
shares): `pnl_f = pnl·booked/f − cost·(f−booked)/f`.

The full class (no reachability filter) is **89 legs, $1,569.78 at risk, +$286.56 (+18.3%), CI
[−32.3, +78.4], win 42.7%, ex-top-3 −$276.46**. The positive headline is three legs.

## 3. Why +1c is excluded as a governing basis

49 of the 89 legs are booked on the grid already (tick remainder 0). A flat +1c hands those legs a
**whole cent of price improvement** with no booking-derived justification — 1.9% of the booked price
at the median leg, and only on the **23 legs booked at ≤0.20** is a cent 5% or more of the price
(the 89 booked prices run **0.051–0.839, median 0.515, p75 0.669**; **66/89 sit outside 0.05–0.20**)
— whereas the 40 off-grid legs need only their own sub-tick remainder (**0.05–0.90c observed**, 10 of
the 40 above 0.50c; the grid construction bounds it at 0.95c) to become
tradable. The tick-aligned arm grants each leg exactly the gap its own booking implies and no more:
**51.7%**. The flat arm grants everyone a full
tick: **80.9%**. That 29.2pp gap is the difference between "the booked price, instantiated on the
venue's grid" and "one tick better than the booked price", and it is the entire distance between
FAIL and PASS.

Second reason: reachability is already an upper bound on fill. Adding slack to an upper bound does
not make it conservative — it makes it a weaker upper bound. A gate that decides a **permanent**
write-off may not be loosened by a parameter that was never argued for on its own terms.

Note also that arm C keeps the maker's price while taking the taker's fill. Re-pricing the same legs
at the ask (C' / B'') is the internally consistent taker reading — it moves ROI by +6.3pp (C→C') and
+11.1pp (B→B') here only because the *minimum* ask over the window is often *below* the booking;
that is a best-of-window artifact, which is why B'' prices at the deterministic tick-implied ask
instead.

## 4. Population, coverage and flow

| population (STANDARD, settled, deduped, post-corpus) | legs | at risk | PnL | ROI |
|---|---|---|---|---|
| all post-corpus STANDARD legs | 2,472 | — | — | — |
| question legs (the class) | 425 (17.2% of the lane) | $7,618 | +$96.74 | +1.3% |
| question legs whose market is in the L2 asset map (**adjudicable**) | 122 | — | +$440.71 | — |
| question legs carrying a book stamp **and** settled (the gate's n) | **89 = 73.0% of adjudicable** | $1,569.78 | +$286.56 | +18.3% |

Coverage of the *adjudicable* universe is **73.0%** (89/122); the card's 16.4% used a different
denominator and reproduces in one query: **543** post-corpus STANDARD question legs, **all statuses,
no dedupe** (settled-only, no dedupe: 507; all-status deduped: 458; settled deduped: 425). Both
figures are true and they answer different questions, so the pre-registration has to say which one
governs where: the **coverage bar** is metered against the adjudicable universe, because a leg whose
market is not in the L2 map cannot be adjudicated either way; the **write-off**, if it ever happens,
lands on the whole class (425 settled / 543 all-status legs), so a verdict must print both — class
coverage beside adjudicable coverage. On the DB's deduped settled population the same 89 legs are
**20.9% of the class (89/425)** and **73.0% of the adjudicable universe (89/122)**.
Coverage of the whole lane's union is 404/1,036 = 39.0%.

Flow, by month opened (adjudicable universe / of which stamped): **2026-09: 106 / 73 · 2026-10: 7 / 7
· 2026-11: 9 / 9**. The class has produced **9 adjudicable legs in November**. At that rate the
card's **≥300-leg readiness bar is ~23 months away** (211 more legs at ~9/month); the recommended
≥90%-coverage bar lands on the same clock if only new legs move the number, and is cleared at once by
the stamp extension rather than by waiting (§8, F4).

Lane mix of the class's post-corpus profit: **BANKROLL_200 +$4,539.09 (n=650, $9,174 at risk)** vs
**STANDARD +$96.74 (n=425, $7,618)**. The stamp is STANDARD-only. The card's own cross-lane note —
C-200 question, fill-confirmed: 53 legs, −$757 (−49.8%) — is directionally the opposite of the booked
number, and it was produced on a different population (`fillStatus='filled'`, not reachability). Both
lanes must be in the same gate before "the profit is real" is answered.

## 5. Selection caveat that travels with every ROI in §2

Reachability is measured over the window that opens at the booking, so the reachable cohort is
selected on the subsequent price path: a leg is "reachable" when the market came back to (or through)
its entry. Split the 89 on that axis naively and you get a split on outcome direction, not on fill
quality:

- booked **at** the mid (n=32, the tol-0 rejection set): **−$260.02, −45.1%**, CI [−75.1, −12.7]
- booked **off** the mid, never reached (n=25): +$133.46, +30.3%, CI [−56.0, +158.4]
- **reached at tol 0** (n=32): +$413.12, +74.7%, CI [−21.5, +212.2]

Read correctly this says: under tol 0 the class's loss sits almost entirely in the 32 **mid-booked**
legs (−$260.02) — precisely the set the test excludes by construction — while the 25 legs that were
off-mid and never touched are mildly positive (+$133.46) and the 32 touched ones carry +$413.12. The
"unreachable" bucket is therefore not one population; it is the booking-convention set welded to a
genuinely untouched set. It does **not** say that a live taker earns +74.7% on the reachable subset,
and it does not license "pay up" as an entry rule — the split is on the price path, and the
one group whose interval excludes zero is the losing one. Any future re-read must print this caveat
beside the arm, or the reachable ROI will be quoted as an edge.

## 6. Recommendation — the pre-registered rule

Adopt the following as item 2's governing rule. **Nothing in it is applied today**; it becomes the
rule the operator cites when the verdict is finally taken.

> **Item 2, question class (pre-registered 2026-11-23).** Population: STANDARD ∪ BANKROLL_200,
> `isDemo=0`, `status IN ('closed','resolved')`, settled `realizedPnl` not null, deduped first leg
> per `bot|wallet|market|outcome`, market present in the L2 asset map, opened on/after the L2 corpus
> epoch. Level: the booked `entryPrice`; a leg is **reachable** iff the best ask within the stamp's
> lag window ≤ `entryPrice + sub-tick remainder(entryPrice)` — never a flat cent of slack. ROI on
> the reachable cohort is computed at the **tick-implied ask** (`entryPrice + sub-tick remainder`),
> not at the booked mid. **PASS** iff reachable ≥ 60% **and** reachable-cohort ROI ≥ 0. **Coverage
> bar:** a verdict may be published once the stamped settled population is ≥ 90% of the adjudicable
> universe (or ≥ 300 legs, whichever comes first). Until then the published state is
> **"NOT DECIDABLE — X% on n of N adjudicable legs"**, never FAIL and never PASS.

Measured under it today: **51.7% (46/89), 73.0% coverage → NOT DECIDABLE**, with the arm table in §2
reported beside it. Under the strict tol-0 reading the answer is 36.0% — same state, same bar.

### Flags — one line each, overridable independently

- **F1 · TOLERANCE BASIS — recommended: tick-aligned (B'').** Moves the headline 51.7% (vs 36.0% at
  tol 0, vs 80.9% at flat +1c). Revert: change the constant back to 0 in the rule text; no code
  carries it.
- **F2 · ROI LEVEL — recommended: tick-implied ask (B'' = +62.1%),** not the booked mid. Keeping the
  mid with a taker fill is the C arm's inconsistency. Revert: read ROI from the `arm B` row instead
  (+63.4%).
- **F3 · WRITE-OFF SCOPE — recommended: the post-corpus adjudicable class (+$96.74 STANDARD as it
  stands; the class number once both lanes are stamped),** not the all-time **+$6,180.86**. An
  all-time write-off cannot be adjudicated by a post-corpus fill read.
- **F4 · COVERAGE BAR — recommended: ≥90% of the adjudicable universe (89/122 today → 73%).** The
  bar should be coverage of the population the gate can actually adjudicate, not an absolute leg
  count: **≥300 is ~2.5× today's adjudicable universe**, so it is a different threshold in disguise,
  and it detaches from the population whenever the class grows or shrinks. The cost, stated honestly:
  the two bars clear on essentially the same date if nothing but new legs move the number — ≥90%
  needs **k ≈ 23.1 months** at November's 9 adjudicable legs/month (`(0.9·122−89)/(0.1·9)`) and ≥300
  needs `(300−89)/9 ≈ 23.4` — so the swap buys about a week on the clock, not two years. What it buys
  is the right remedy: the **33 un-stamped legs are all September**, and the card's own **~2h stamp
  extension** takes coverage from 89/122 to 122/122 and clears the recommended bar immediately, while
  no stamp extension can clear a 300-leg bar that needs 211 new legs. Concretely, F4 drops the
  "or ≥ 300 legs" disjunct from the §6 rule. Revert: keep 300 and accept
  that item 2 stays parked until ~2028-10 at November flow even after the stamp is extended.
- **F5 · LANE COVERAGE — recommended: block the class verdict until C-200 question legs carry a
  reachability stamp** (the booth exists: `scripts/c200-printthrough.py` + the union read in
  `scripts/c200-fill-aware-pnl.ts`). The STANDARD-only stamp sees 2.1% of the class's post-corpus
  profit.

## 7. Before / after — every figure that moves

| figure | before (unstated parameter) | after (rule pre-registered) |
|---|---|---|
| gate state, question class | "36.0% FAIL" **or** "80.9% PASS" depending on the reader's arm | **"NOT DECIDABLE — 51.7% (46/89), 73% coverage"** |
| tolerance in force | none | sub-tick remainder (≤1c, derived from the venue grid) |
| ROI basis of the reachable cohort | booked mid (inconsistent with a taker fill) | tick-implied ask |
| write-off candidate | $6,180.86 all-time, both lanes | post-corpus adjudicable class (+$96.74 STANDARD today) |
| readiness bar | 300 legs (~23 months out at November flow) | ≥90% of the adjudicable universe (73% today; also ~23 months by waiting, but immediate once the ~2h stamp extension runs) |
| class verdict may be published by | anyone who picks an arm | nobody, until F4/F5 clear |

No rule, size, gate, booked figure or DB row changes today. The diff above is what the *published
verdict* would read once the operator approves this text.

## 8. Reality checks the operator should see before approving

- The class's whole positive headline is **3 legs** (+$286.56 → ex-top-3 −$276.46). Nothing in §2 is
  robust to concentration.
- Every arm's ROI interval spans zero (best lower bound −11.9%). The gate's ROI conjunct passes on
  the point estimate only; "non-negative ROI" is not statistically established at n=89.
- The **adjudicable** flow is thin and lumpy: 106 mapped question legs in September (the L2 corpus
  epoch month, which carries backfill), **7** in October, **9** in November. The class as a whole is
  not small — November carries **110 question legs across both lanes** — and its post-corpus series
  should be read for what it prints, not as a decline: STANDARD question legs ran **505 → 8 → 30**
  (all statuses, undeduped) against STANDARD's own lane at **747 → 146 → 143**, i.e. 68% → 5.5% → 21%
  of the lane's legs. The 505 is the backfilled September epoch month; across the two organic months
  the class **rose 8 → 30 (+275%)** while the lane was flat (146 → 143, −2.1%) and the class's share
  of the lane **rose 5.5% → 21%**. From September the series falls (68% → 21%) only because that
  denominator carries the backfill; forward it is growing off a thin base. Either reading forbids
  citing recent flow as evidence that the class is dying. Measured per basis, November's question
  book is:
  - **STANDARD:** 30/143 = **21% of the lane's legs**; **9** settled question legs carry **$135 of
    STANDARD's $1,339 settled at risk = 10%**.
  - **Both lanes:** 110/575 = **19% of all legs**; **87** settled question legs carry **$2,443 of
    $10,628 settled at risk = 23%**.

  What is small is the *adjudicable* slice — 9 legs a month — which is why the coverage bar, not the
  tolerance, is what parks item 2.
- The adjudicable universe is capped by the L2 map, not by the book: **122 of 425** post-corpus
  question legs sit in the L2 asset map, and **89** of those 122 carry a book stamp and are settled
  (73.0%). New legs do stamp at 100% (Oct 7/7, Nov 9/9), but that does not close the gap on any
  useful horizon: the **33 un-stamped adjudicable legs are all September**, so coverage runs
  `(89 + 9k)/(122 + 9k)` and **90% needs k ≈ 23 months** at November's 9 adjudicable legs/month.
  Waiting is therefore not the path to the bar — extending the stamp over the remaining mapped
  question legs is (89/122 → 122/122; the card's own ~2h remedy, see F4).

## 9. Refutation — what would answer this in the other direction

1. If a ≥90%-coverage read (or 300 legs) on the pre-registered basis comes in **≥60% with ROI ≥ 0**,
   the profit is real and this proposal is answered the other way.
2. If it stays **<60%** at the bar, the class's *fillable* profit is negative and the write-off is
   earned — scoped per F3.
3. **Falsifies the basis itself:** if a per-leg, queue- and size-aware fill adjudication (not
   reachability) shows the booked level was transactable on legs where the ask never printed at or
   below it, then reachability is the wrong instrument and B'' must be replaced, not re-tuned.

## 10. Reproduce

```
python3 scripts/profit-question-fill-read.py          # prints all sections; writes data/profit-question-fill-read.json
```

Read-only: DB opened `mode=ro&immutable=1`, no RuleSet read or write, no prisma write, no code path
changed by this doc. The instrument gained three sections this run (class coverage, execution-model
arms, tol-0 split) and kept every previously published key.

## Provenance

- approvals id `apr-profit-item2-question-gate-basis`, lane **A**, decided 2026-11-23T13:22:25Z by
  the operator via the approvals inbox, no expiry.
- Source card `roadmap:profit-item2-question-gate-basis` (proposed 2026-11-21 by the daily
  profit-research job; `drafts/profit-research-20261121.md` §R1).
- Card-supplied figures not re-derived here: C-200 question fill-confirmed 53 legs / −$757 (−49.8%),
  from `scripts/profit-path-research.py`'s filled-class arm (2026-11-22 read; different population).
