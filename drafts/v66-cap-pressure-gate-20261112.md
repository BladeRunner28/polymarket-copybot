# v66: fire the STANDARD stale exit on cap pressure, not on the calendar

**Status: PROPOSAL ONLY — nothing applied.** RuleSet is still **v72** (`standardStaleExitHours = 0`, band
`0.60`, leg cap `1,300`). No `apply-v*` was run, `prisma/dev.db` was opened read-only throughout, and no
branch was merged. The code and the apply script live on `wt/v66-cap-pressure-gate` (committed there, **not
merged**); the operator's apply step is one command, at the end of this document.

Card: `v66-cap-pressure-gate` · approval `apr-v66-cap-pressure-gate` (2026-11-12 16:10 UTC) · measured
2026-11-12 16:21 UTC.

**Instruments (both committed with this write-up):**

```
python3 scripts/v66-gate-backtest.py --days 90     # day-by-day gate replay, 90d
DATA_MODE=live python3 scripts/profit-exits.py --no-fetch   # §AO: what the sweep bought and paid
../../node_modules/.bin/vitest run tests/standard-stale-exit-pressure.test.ts
```

---

## 0. The operator's decision, in one line

**Arm the rail on the cap's own block counter, scoped to entry ≥ 0.80 — not the card's headroom test, and
not the 0.60 band.** It changes nothing today (0 cap blocks ever, 0 legs in scope), and it is the only
version whose measured cost per leg fired is below the value of the slot it frees.

---

## The key insight

**The trigger question is settled; the economics are not — and the card's fix only settles the first one.**

1. **A calendar cannot answer cap pressure, and neither does "headroom < 15%".** Measured over 90 days the
   headroom conjunct was true on **71 of 90** days and removed **1** of the 35 net-growth days. Against a
   1,300-leg cap that only governed STANDARD from 2026-10-20, it is a test the lane passes while sitting
   nowhere near the cap. The honest pressure signal is the cap **refusing a copy** — and that counter reads
   **0 on all 371,428 `DecisionJournal` rows ever written**.
2. **Firing on pressure fixes WHEN, not WHETHER.** The rail's measured cost is the exit alpha it forfeits:
   **−$833.79 on 199 priced legs = −$4.19/leg** (±, CI −$12.70…+$0.33). A freed slot is worth **$1.02/leg**
   (lane's ex-top-1 settled rate — an *upper bound*, because the copy the cap refused is a marginal one).
   At the card's 0.60 band the trade is **4:1 against even when pressure is real**.
3. **The band is the lever, and it has never been measured separately.** Split by entry band the same
   cohort reads **0.60–0.80: −$826.75 on 76 legs (−$10.88/leg)** and **0.80–1.00: −$7.04 on 123 legs
   (−$0.06/leg)**. Narrowing the floor from 0.60 to 0.80 turns the trade from 4:1 against into ~1:17 for
   (+$0.96/leg point estimate). That is the whole proposal in one number.

---

## 1. Live state the decision is made against

| quantity | measured 2026-11-12 16:21 UTC |
|---|---|
| active RuleSet | **v72** (activated 2026-11-11 18:41:05 UTC) |
| the rail | `standardStaleExitHours = 0` — **retired by v70** (2026-10-29), band floor 0.60 |
| open STANDARD book | **391 legs / $4,317.52** — headroom **909 (69.9% of the 1,300 cap)** |
| open by entry band | <0.20: 243 · 0.20–0.40: 56 · 0.40–0.60: 85 · 0.60–0.80: **7** · 0.80–1.00: **0** |
| **rail scope today** (entry ≥ 0.60 AND age ≥ 168h) | **0 legs** — the 7 legs at 0.60–0.80 are all younger than 168h |
| cap-block counter | **0 rows** ever, any bot; 0 for `STANDARD: open-position cap` specifically |
| trailing flow | 7d **+7** (61 opens / 54 resolutions / 0 early closes) · 14d **−80** · 30d **−877** (213 / 389 / 701) |

The 30-day figure is contaminated by the v66 sweep itself (701 early closes on 2026-10-24). The clean
read is the sweep-excluded one from §AO.4: **−8.46 legs/day since the sweep**, and *without* the sweep the
book would be **893 legs today → 407 slots of headroom**.

---

## 2. What the rail actually bought and paid (re-measured today)

`scripts/profit-exits.py --no-fetch`, 2026-11-12. Coverage moved since the 2026-10-29 read (199 legs now vs
167 then, same cache), so the headline is re-quoted rather than carried:

| quantity | 2026-11-12 | 2026-10-29 |
|---|---|---|
| sweep cohort | 701 legs / $7,321.20 / **−$350.52** (−4.79%) | identical |
| exit alpha (settlement truth) | **−$833.79** (−39.81% of notional), CI [−$2,528, **+$67**] | −$831.70 on 167 legs |
| alpha per priced leg | **−$4.19** | −$4.98 |
| alpha ex-10-extreme markets | −$33.12 on 34 markets | −$0.39 on 11 markets |
| band 0.60–0.80 | 76 legs, **−$826.75** (−$10.88/leg), CI [−$2,460, +$43] | 64 legs, −$800.20 |
| band 0.80–1.00 | 123 legs, **−$7.04** (−$0.06/leg), CI [−$78, +$73] | 103 legs, −$31.50 |
| control (404 dead-slug expiry) | 6,503 exits, alpha **+$210.73**, mark error median **0.000** (p10 −1.1c / p90 +1.8c) | identical |
| a slot is worth | **$1.023/leg** ex-top-1 (n=420 resolved) · mean $1.692 · median $1.115 | $0.168/leg lifetime basis |
| clearance | 27.4% of the cohort would have freed itself within 7d, **80% within 90d** | identical |

Two facts do the work: the alpha is **four times the value of the slot it frees**, and **80% of the cohort
would have freed its own slot inside 90 days** without any rule.

---

## 3. The card's gate, replayed over 90 days

`scripts/v66-gate-backtest.py --days 90` (gate as specified: `headroom < 15%` AND `7d opens > 7d natural
resolutions`):

| quantity | measured |
|---|---|
| days measured | 90 |
| gate FIRE days | **34 (38%)**, all **2026-08-14 … 2026-09-20** |
| days `headroom < 15%` | **71 (79%)** |
| net-growth days | 35 → the headroom conjunct **removed 1**, i.e. did no work on the other 34 |
| days the full gate suppresses despite `headroom < 15%` | 37 |
| last 30 days | **0 fires / 30** (max open 1,269; min headroom 31) |
| first fire day 2026-08-14 | stock clearing would close **634 legs / $5,734.40 in one tick** (v66's real first tick: 701 / $7,321.20) |
| fire-day scope stock | 624–966 legs, median notional **$7,874.20** |
| counting every slot-freeing exit | 18 fires → **16 of the 34 vanish** |
| no-sweep counterfactual | 1,092 legs today → **headroom 208 = 16.0%**, i.e. the headroom test is now **false even without the sweep** |

---

## 4. The card's three ship conditions, assessed

| # | condition | verdict | evidence |
|---|---|---|---|
| 1 | unit-tested; refuses at `headroom ≥ 15%` or net growth ≤ 0 | **MET for the amended gate** (20 new tests, 997/997 suite green, `tsc` clean) | `tests/standard-stale-exit-pressure.test.ts` |
| 2 | 14-day shadow permits ≥ 1 fire in the growth regime and 0 in the current one | **MET by the headroom design only**: growth window **14/14**, current window **0/14**. The amended gate permits **0/90** — its trigger has never occurred, so a shadow cannot show it permitting | backtest §SHADOW |
| 3 | the leg cap blocks 0 copies on suppressed days | **MET**: 0 of 56 suppressed days carry a block; 0 blocks ever | `DecisionJournal` count = 0 |

Condition 2 is the finding, not a formality: the bar as written is satisfiable by the design the measurement
rejects, and *un*satisfiable by the design the measurement supports. Stating that plainly is the reason this
document is not a "bar met, ship it" write-up.

---

## 5. The gate that is actually built (three amendments, each measured)

| amendment | why | measured basis |
|---|---|---|
| **1. Trigger on the cap's block counter, not the headroom fraction** | the headroom conjunct removed 1 of 35 days and is false today even without the sweep | §3 |
| **2. Count every slot-freeing exit in the growth test** | 404 expiries and rule exits book `status='closed'` and free legs identically; counting resolutions only added 16 spurious fire days | §3 |
| **3. Rate-limit to 25 legs/day (UTC), budget consumed by all early closes** | an on/off switch on a per-leg age rule clears the backlog in one tick; a binding cap blocks only ~7.8 copies/day | §3, §AO.4 |

**And the scope (amendment 4, the one that decides the economics): band floor 0.60 → 0.80.** At 0.60 the
rail forfeits $4.19 of alpha per $1.02 slot; at 0.80 it forfeits $0.06. If the operator wants the card's
literal 0.60 scope, the code already supports it — the band is a rule field, and the apply script takes
`--band`.

Shape of the shipped code (all inert until a RuleSet change enables it):

| file | change |
|---|---|
| `src/lib/rules.ts` | 3 new fields, defaults `0 / 24 / 25` (`PressureOnly`, `PressureHours`, `MaxPerDay`) — a ruleset lacking them is byte-identical to pre-v73 |
| `src/lib/paper.ts` | `standardStaleExitPressureFires()` + `standardStaleExitAction()` — pure, beside the v66 helper, sharing no field with the C-200 rail |
| `src/lib/standard-exit-pressure.ts` | the four observed inputs, read **once per run** and only when `pressureOnly = 1` |
| `scripts/update-pnl.ts` | the STANDARD branch now asks `standardStaleExitAction(...)` and names the authority in the close reason (`v73 cap pressure …` vs `v66 calendar`) |
| `tests/standard-stale-exit-pressure.test.ts` | 20 tests: defaults, kill switch, each condition independently, strict rate boundary, scope unchanged |
| `scripts/apply-v73.ts` | dry-run by default; `--band=0.8` optional; `--apply` required to write |

Unit tests actually run (`vitest run`, 2026-11-12):

```
✓ tests/standard-stale-exit-pressure.test.ts (20 tests)
✓ tests/standard-stale-exit.test.ts (13 tests)
Test Files  93 passed (93)     Tests  997 passed (997)
tsc -p tsconfig.json --noEmit  → 0 errors
```

---

## 6. Before / after: every figure that moves on apply

| figure | before (v72) | after (armed, band 0.80) |
|---|---|---|
| `standardStaleExitHours` | 0 | 168 |
| `standardStaleExitPressureOnly` | 0 | 1 |
| `standardStaleExitBandMin` | 0.60 | **0.80** (only if `--band=0.8`) |
| legs closed on the first tick | 0 | **0** — 0 cap blocks, and 0 open legs at ≥0.80 aged ≥168h |
| book, PnL, marks, gates, sizing | — | **unchanged** |

This is the rare apply whose dry run and live run are identical: the rail is armed **shut**, and it can only
open on an event (`[STANDARD] open-position cap` refusing a copy) that has never occurred in 371,428 rows.

---

## 7. Options

| # | action | cost | buys | risks |
|---|---|---|---|---|
| **A (rec.)** | merge the branch, run `apply-v73.ts --band=0.8 --apply` | ~0 (5 min) | the calendar trigger becomes a mechanical response to the only event it exists for; measured cost $0.06/leg against a $1.02 slot | fires later at a rate the point estimate likes and the CI cannot exclude; band escalation 0.60→0.80 is a second rule change riding along |
| B | same, **without** `--band` (keep the card's 0.60 scope) | ~0 | exactly the approved card | point economics 4:1 against (−$4.19/leg vs $1.02); the only surviving argument is that the CI includes zero |
| C | do not arm; close the card as measured, keep the spec + tests on the branch | 0 | nothing | the next growth regime re-opens the same question with the same instrument |

**Override flags, if any of these are wrong:**

- `standardStaleExitBandMin 0.80` → `0.60` restores the card's population (cost: $4.19/leg vs $1.02/leg).
- `standardStaleExitMaxPerDay 25` → `10` (tighter drip) or `0` (unlimited — not recommended: 634-leg first tick).
- `standardStaleExitPressureHours 24` → `168` if "a block sometime this week" should be enough to authorise an exit.
- Kill switch, unchanged: `standardStaleExitHours 0`.

---

## 8. Revert and refutation

**Revert (one field):** `standardStaleExitHours → 0`. `standardStaleExitFires()` returns false on
`hours <= 0`, so the rail goes inert while the v73 fields stay on the record. The band may stay at 0.80 —
it is inert behind the kill switch.

**Refutation, pre-registered before the apply** (the card's own, kept binding, plus v66's):

1. `[STANDARD] open-position cap` blocks **≥ 20 copies on gate-suppressed days within 30 days** of
   activation → the trigger/window is wrong; revert and re-derive.
2. The first **20 organic stopped legs** realise worse than hold by **> 1.0% of notional** → the marks lied;
   revert (carried from v66: this is the falsifier that retired the calendar version).
3. A rate-limited first week's exit alpha on **≥ 150 priced legs across ≥ 40 markets** is negative → revert.

**Refutation of THIS recommendation** (what would make the doc wrong): the cap blocks a copy **while the
0.80+ scope is empty** for 30 days — that would mean the rail is aimed at a band that no longer exists, and
the right instrument is the admission funnel, not an exit.

---

## 9. Reality checks and limits

- **The alpha estimate is one market deep and its CI includes zero.** −$833.79 on 199 priced legs, of which
  the 5 most negative markets are −$887.52 and the 5 most positive +$86.85; ex-those-10 the alpha is −$33.12.
  The band split is the load-bearing evidence, not the pooled figure: 0.60–0.80 carries −$826.75 on 76 legs,
  and 0.80–1.00 is −$7.04 on 123.
- **Settlement coverage is 28.4%** (199 of 701 legs) in `--no-fetch` mode — 502 legs unsettled, 204 markets
  uncached. A fresh fetch would move the point estimate; run without `--no-fetch` before treating −$4.19/leg
  as final.
- **The slot price is an upper bound.** $1.023/leg is the lane's *average* settled rate; the copy the cap
  refused is drawn from the admission margin, which is the weaker tail. An armed rail is therefore
  optimistically priced in §0 point 3.
- **`headroom < 15%` before 2026-10-20 is hypothetical**: `standardMaxOpenPositions` only governed STANDARD
  from v64, and the reconstructed book runs to 1,695 legs in September. That is exactly why the headroom
  test passes on 79% of days — it is measuring a cap that was not attached to the lane.
- **No live shadow exists.** The 14-day window in §4 is a *replay* of stored marks and journal rows. A live
  write-only shadow would take 14 days to say nothing (the gate is shut on the block counter), so it was not
  built; the replay is the same computation on the same data.
- **Nothing was applied.** RuleSet v72 unchanged, no `apply-v*` executed, `prisma/dev.db` read-only, branch
  `wt/v66-cap-pressure-gate` unmerged.

---

## 10. The apply step (operator only)

```bash
cd ~/polymarket-copybot                          # MAIN checkout, not the worktree
git merge wt/v66-cap-pressure-gate               # only on the operator's word
DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v73.ts --band=0.8           # dry run
DATABASE_URL="file:./dev.db" npx tsx scripts/apply-v73.ts --band=0.8 --apply   # arm
```

**Run it from the main checkout, never from the worktree.** `DATABASE_URL="file:./dev.db"` resolves to
`prisma/dev.db`, and a worktree has no `prisma/dev.db` — Prisma would point at a database that does not
exist rather than failing in front of you.

Revert: `standardStaleExitHours → 0` (one field, next `apply-vNN` or the rules page).

---

## Appendix — raw output (2026-11-12 16:21 UTC)

```
live RuleSet v72: standardMaxOpenPositions=1300 standardStaleExitHours=0 standardStaleExitBandMin=0.6
rail is RETIRED (standardStaleExitHours = 0) — the gate below is the re-arm design, priced on an unshaped book.
STANDARD legs on record: 10396

cap-block journal rows: any bot 0 (first None last None) · STANDARD-only 0
v66 cohort closed 2026-10-24: 701 legs / $7,321.20 notional

scope days measured: 90   gate FIRE days: 34 (38%)   [all-exits variant: 18]
headroom < 15% days: 71 (79%)   of those, gate also needed net growth: 34
net-growth-only days: 35  -> the headroom test REMOVED 1 of them (and ADDED none it did not already have)
fire days: 2026-08-14 .. 2026-09-20
first fire day 2026-08-14: stock clearing would close 634 legs / $5,734.40 in one tick  (v66's actual first tick: 701 legs / $7,321.20)
fire days that vanish when early exits also count as slot-freeing: 16
fire-day scope stock: min 624 legs, max 966 legs, median $7,874.20
last 30 days: 0/30 fire, max open 1269, min headroom 31

v73  SHADOW WINDOWS
   growth regime 2026-08-21..2026-09-03 (14d)     permits 14/14 days · scope 10546 legs / $99,752
   current    2026-10-29..2026-11-11 (14d)        permits 0/14 days · scope 0 legs / $0
   amended gate (blocks24 > 0 AND opens7 > all exits): permits 0/90 days -- the cap has refused a copy on 0 of 90 days
   suppressed days on which the cap blocked any copy: 0 of 56
   days with headroom < 15% that the FULL gate still suppresses: 37

no-sweep counterfactual book today: 1092 legs -> headroom 208 (16.0% of cap)
```

```
AO.5  EXIT ALPHA ON THE DISPOSED COHORT -- marks vs settlement truth
   coverage: 199/701 legs settled (28.4% of legs)
   settled subset: 199 legs $2,094.60 cost
   stopped as executed : $ -440.12 (-21.01%)
   held to settlement  : $ +393.67 (+18.79%)
   EXIT ALPHA (stop - hold) = $-833.79 (-39.81% of notional)
   market-clustered 95% CI [$-2,527.67, $+66.58]  -> includes zero
   0.60-0.80     76      947  -47.07%  +40.21%   -826.75  -87.28%   CI [$-2,460, $+43]
   0.80-1.00    123      1,147   +0.50%   +1.12%     -7.04   -0.61%   CI [$-78, $+73]
   ex-those-10 markets: alpha $-33.12 on 34 markets

AO.4  THE COUNTERFACTUAL: what the 701 slots actually bought
   without the sweep the book would be 391 + 502 = 893 legs today, against a 1300 cap
   net book growth since the sweep (ex-disposal): -8.46 legs/day (555 -> 391 over 19.4 days)
   mean $+1.692 / median $+1.115 / EX-TOP-1 mean $+1.023 (n=420, resolved-only)
   a permanently-binding cap blocks ~7.8 copies/day, so its steady-state cost is $7.97/day ex-top-1
   the full 701-slot release, if every slot refilled and earned the ex-top-1 rate: $+717.03
   the 151 slots actually refilled so far: $+154.45
```
