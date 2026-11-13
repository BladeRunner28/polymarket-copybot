# v66: retire the STANDARD calendar stale exit — the branch is deleted, and the number the card was approved on was the DEMO book

**Status: PROPOSAL ONLY — one code deletion staged on a branch, nothing applied.**

| | |
|---|---|
| active RuleSet | **v72** — `standardStaleExitHours = 0`, `standardStaleExitBandMin = 0.60`, `standardMaxOpenPositions = 1,300` |
| `prisma/dev.db` | opened **read-only** for every query in this document (no write of any kind) |
| `scripts/apply-v*.ts` | **not run** |
| code | deletion committed on `wt/v66-retire-calendar-trigger` as **5297d03**, **not merged to main** (`git merge-tree main … ` = clean) |
| approval | `apr-v66-retire-calendar-trigger`, decided 2026-11-12 16:45:05Z, Lane A, "APPROVED by the operator (clicked link, no expiry)" |
| measured | 2026-11-12 10:45–11:05 CST |

Card: `v66-retire-calendar-trigger` · supersedes `v66-cap-pressure-gate` (never built) · supersedes the
2026-10-29 read of this same card (that read recommended keeping the branch; this one deletes it, on the
operator's approval, and carries both corrections forward)

Open this on the dashboard: **http://localhost:3013/drafts/v66-retire-calendar-trigger-20261112**

---

## 0. What the operator has to run (3 commands)

```bash
cd ~/polymarket-copybot
git merge wt/v66-retire-calendar-trigger          # verified conflict-free against main (merged tree 36a06da)
npx tsc -p tsconfig.json --noEmit && npx vitest run tests/standard-stale-exit.test.ts
npx vitest run                                    # full suite — the branch base is 132 commits behind main, so this is the first honest full run
```

Nothing else. **No RuleSet change, no `apply-v*`, no DB write is part of this change** — the rail was
already disarmed on 2026-10-29 by RuleSet v70 (`standardStaleExitHours 168 -> 0`, audit row `changedBy =
hermes-v70-retire-standard-calendar-stale-exit`). The merge is a code deletion that makes that retirement
permanent. Revert: `git revert 5297d03`.

---

## The key insight

**The card's decision rule is met with room to spare — and the scope number the approval rests on
("12 open STANDARD legs / $112.60") was measured on the DEMO book, not the live one.**

The live book has had **zero** in-scope legs since at least v70's activation on 2026-10-29 14:02:54 UTC,
and it has **zero** today. The only rows that satisfy the predicate are 11 DEMO legs / $103.60, which
production never loads (`scripts/update-pnl.ts:73`: `adapter.isDemo ? {status:"open"} : {status:"open",
isDemo:false}`). Reconstructed as-of the activation timestamp from `closedAt`/`resolvedAt`, the live
in-scope population was **0 then too** — nothing has closed out of scope since, because nothing was ever
in it.

So the rail's live firing history is exactly one event, ever: the **2026-10-24 backlog sweep**. It has
never had an organic live leg to fire on, and it has been inert by config for 14 days. Deleting the branch
does not change a single booked number today; it removes the only way the rail could come back — one
RuleSet field write — on a trigger whose premise (cap pressure) has never existed.

---

## 1. Live state the decision is made against

Every figure read read-only from `prisma/dev.db` at 2026-11-12 ~10:50 CST.

| quantity | measured |
|---|---|
| active RuleSet | **v72**, created 2026-11-11 18:41:05 UTC |
| the rail | `standardStaleExitHours = 0` (since **v70**, 2026-10-29 14:02:54 UTC), band floor 0.60 |
| open STANDARD, live book | **391 legs / $4,317.52**, ages 33h – 2,877h |
| **in scope today** (entry ≥ 0.60 AND age ≥ 168h) | **0 legs / $0.00** |
| same predicate, DEMO book | 11 legs / $103.60 (the only rows that match) |
| same predicate, as-of v70 activation | **0 live** · 11 demo / $103.60 |
| leg cap | 1,300 → headroom **909 (69.9%)** |
| `[STANDARD] open-position cap` blocks | **0 ever**, any window |
| trailing flow (30d) | 213 opens vs 389 resolutions = **−5.87 legs/day net** |
| trailing 14d | 124 opens · 204 resolutions · **0 early closes** |

Open book by entry band (live): `<0.20` 243 · `0.20–0.40` 56 · `0.40–0.60` 85 · `0.60–0.80` **7** ·
`0.80+` 0. The 7 high-band legs are 3–4 days old; none is anywhere near 168h.

---

## 2. The card's decision rule, both conjuncts, re-measured today

> **DECISION RULE:** delete the branch when the predicate has fired zero times on organic flow in the
> prior 14 days AND the open in-scope population is < 20 legs.

**Conjunct 1 — zero firings on organic flow in 14 days: MET, and it is stronger than "14 days".**

| firing | legs | notional | booked | when |
|---|---:|---:|---:|---|
| the 2026-10-24 backlog sweep | 701 | $7,321.20 | −$350.52 (−4.79%) | 07:06:33 → 07:08:13 UTC, one run, 698 distinct timestamps |
| anything after it | **0** | $0 | $0 | — |

- All **701** legs of the sweep were in band (entry ≥ 0.60) *and* aged (≥ 168h) — i.e. the sweep is exactly
  the predicate firing on a 100-day backlog, not on flow.
- STANDARD early closes **ever**: 7,369; the **last one is 2026-10-24 07:08:13**. In the last 14 days
  STANDARD has taken **no early close of any kind** (0 `closed`, 204 `resolved`).
- Of the 1,608 closes ever that satisfy the predicate on their own timestamps, **907 landed 2026-07-22 →
  2026-09-25 — before v66 existed (2026-10-23)** — and are the dead-slug 404 expiry path wearing the same
  shape. Only the 701 are the rail.

**Conjunct 2 — open in-scope population < 20 legs: MET at 0, but the card's "12 / $112.60" is wrong.**

Two independent reads (2026-10-29 22:16 and today) find **zero live legs** in scope. The number in the card
— and in `scripts/apply-v70.ts`'s own header, "12 open legs / $112.60 were in scope at activation" —
reproduces **only** when the `isDemo` filter is dropped:

```
live  (isDemo=0):  0 legs /  $0.00
demo  (isDemo=1): 11 legs / $103.60      <- 12 legs / $112.60 on 2026-10-29 (one ~$9 demo leg has since left the book)
```

`apply-v70.ts` itself never computed the scope (it prints open legs + headroom and does filter
`isDemo:false`), so the figure entered the card from a review query that did not filter. **Consequence:**
the rail's scope was already empty on the day it was retired, and the "there are 12 legs in scope today"
line in the approved proposal describes the demo book. Correcting it makes the retire case stronger, not
weaker: there is nothing left for the rail to do, and nothing to wait for.

---

## 3. The zero is falsifiable — proven before trusting it

The refutation this card pre-registers ("`[STANDARD] open-position cap` ≥ 20 blocks") is only worth
anything if that counter can move. It can. `DecisionJournal.risksJson`, last 30 days (**40,369 rows,
newest today**):

| channel | rows |
|---|---:|
| band skip | 3,615 |
| v45 blacklist category | 3,369 |
| kelly no-edge | 2,622 |
| hour blackout | 772 |
| market-slug cap | 268 |
| **open-position cap (any lane)** | **0** |

0 rows matching `open-position cap` in **any** window ever. The channel is demonstrably live, so this is a
real zero: on the evidence available, the 1,300-leg cap is not a constraint on this system and the calendar
rail was protecting a resource that has never been scarce (909 legs of headroom while the book shrinks).

---

## 4. What the rail is worth, measured today — and a correction to the approval text

The approved proposal says "no value at any horizon". **That sentence does not reproduce at the rail's own
horizon, and should not be carried forward as fact.** Today's re-run of the committed replay
(`python3 scripts/standard-168h-replay.py`, read-only, all 10,381 priceable STANDARD legs, `PnlSnapshot`
marks — label-correct):

| cohort | legs | capital-days | booked PnL | Δ 168h vs hold | market-clustered CI |
|---|---:|---:|---:|---:|---|
| whole book | 10,381 | 1,698,993 → 369,232 (−78.3%) | +9,288 → +8,526 | **−$762.62** | [−5,682, +3,628] |
| **the rail's own scope, entry ≥ 0.60** | 4,448 | 897,021 → 185,081 (−79.4%) | −199 → −136 | **+$62.90** | [−1,105, +1,608] |
| fired and already settled | 518 (149 mkt) | — | +1,435.73 vs +821.96 | **−$613.77** | [−4,326, +2,276] |

At the rail's scope, on **settlement truth** (`S.4`, `resolved` legs only): 170 legs / $2,036 notional →
hold **+$65**, 168h exit **+$29**, **alpha −$36 (−1.8% of notional)**, ex-worst/best market **−$61**.

The price-source check that makes those numbers safe to use (`S.8`/`S.9`, completed in the same run): 436
legs are priced by both instruments, median |`PnlSnapshot` − `MarketSnapshot`| = **$0.286**, and **no band
flips sign** when the positional marks are swapped in — at the rail's scope 0.60–0.80 the 168h delta reads
**−$36** (label-correct) vs **−$26** (positional) on 35 legs. The sign here is not an artefact of the price
basis.

Horizon sweep at the rail's scope (`S.6`, Δ ≥0.60): 24h **+$117** · 72h **+$371** · **168h +$63** ·
336h **+$219** · 720h **+$224** · 1440h **−$30**. Every horizon the rail could fire on is
indistinguishable from zero at its scope; the destructive horizons (+2.5h **−$10.2k**, +24h **−$7.7k** on the
whole book, the numbers the card quotes) are exits the rail does **not** take, because it is band-scoped.

The 2026-10-29 read of this card measured the same thing on the mark basis and got a *positive* 168h point
estimate, **+$1,062 on 315 settled STANDARD legs / 69 markets, CI [−$937, +$2,982], ex-top-10 +$411** — not
reproduced today because that read was not band-scoped and used `MarketSnapshot` (positional marks), while
this one is scoped and uses `PnlSnapshot`. Both agree on the decision-relevant fact: **at the rail's own
scope and horizon, the value is ~zero with a CI spanning ±$1–3k.**

**So the retirement stands on the premise test, not on value destruction:** a calendar trigger cannot be
answering cap pressure that has never existed, and its scope is empty. That is the same basis
`apply-v70.ts` recorded on 2026-10-29, and it is the honest one.

---

## 5. The change

**`scripts/update-pnl.ts`** — delete the branch (was lines 274–297; the card's 270–292 has drifted):

```diff
-        } else if (t.botId === "STANDARD") {
-          … 24 lines of v66 comment + age computation …
-          const ageHours = (Date.now() - t.openedAt.getTime()) / 3_600_000;
-          if (standardStaleExitFires(ageHours, t.entryPrice, rules)) {
-            const why = `stale ${…}h >= ${…}h scoped stop (entry ${…} >= ${…}) -- v66`;
-            await withDbRetry(() => closePaperTrade(t.id, price, why), `recycle ${t.id}`);
-            recycled++;
-          }
-        }
+        }
+        // RETIRED 2026-11-12 … 34-line tombstone: what stood here, why it fired once,
+        // why deletion (not disarming), what is kept (the predicate), the re-arm trigger,
+        // and the pointer to this document.
```

and drop `standardStaleExitFires` from the `../src/lib/paper` import (no other use in the file).
`standardStaleExitFires()` itself **stays** in `src/lib/paper.ts` and stays unit-tested — the card asks for
that explicitly, and the re-arm path reuses it.

**`scripts/apply-v70.ts`** — two comment/log lines that would otherwise become false instructions after the
merge ("revert is one field"): now say the field alone restores nothing, and point at this document. No
behaviour in that script changes.

### Verification (all run on the branch)

| check | result |
|---|---|
| `tsc -p tsconfig.json --noEmit` | **clean** (exit 0) |
| `vitest run tests/standard-stale-exit.test.ts` | **13/13 passed** — predicate still exported and covered |
| production call sites of `standardStaleExitFires` | **0 calls** (`src/` + `scripts/`); only the definition, a comment and two strings in `apply-v70.ts` |
| live-ruleset probe (real loader → field → predicate) | v72: `hours=0`; `fires=false` at age 10,000h/entry 0.95, 1,000,000h/0.99, 1,000,000h/0.60 |
| merge into current main | `git merge-tree main wt/v66-retire-calendar-trigger` → **clean**, merged tree `36a06da` |
| the merged tree's `update-pnl.ts` | main's `priceForOutcome` fix (fbf9073) intact · no `else if (t.botId === "STANDARD")` code line (the one match is the tombstone comment) · predicate import gone |
| full suite on the branch | **10 failures in 2 files** (`engine`, `fill-intent`) — these are a stale-base artefact: the branch base `aeebfc7` is **132 commits behind main**, and those two files import `src/lib/{paper,rules,benchmarks,rule-updater}`, not either script this commit touches. Both files pass **32/32 on main today**. Not claimed green here; re-run the suite after the merge. |

That probe is the before/after proof that this is behaviour-neutral **today**: the branch was already
unreachable, because the live ruleset fails the predicate's own guard at every boundary I tested.

---

## 6. What moves, and what does not

| figure | before merge | after merge |
|---|---|---|
| booked PnL, leg counts, exits, marks | — | **unchanged** (predicate false on the live ruleset) |
| predicate evaluations per hourly run | ~391 no-op `Date.now()` calls | 0 |
| ways to re-arm the calendar rail | one RuleSet field write | code revert + merge |
| production callers of `standardStaleExitFires` | 1 (inert) | 0 (tests only) |
| any report / dashboard / ladder number | — | **unchanged** |

Three judgment calls, each overridable in one line:

1. **Branch commit instead of a doc-only proposal** — so the operator's step is one `git merge`. *Override:
   don't merge; nothing else in the repo changes and the rail stays inert by field, exactly as today.*
2. **34-line tombstone comment at the deletion site** — the reason travels with the code, so the next reader
   cannot re-propose a calendar exit from scratch. *Override: strip to one line; costs no behaviour.*
3. **Keep the predicate + its 13 tests** (`standardStaleExitFires`) rather than delete them with the branch —
   the pre-registered re-arm reuses it. *Override: delete both; then the re-arm needs the predicate rewritten.*

---

## 7. Refutation — what brings the rail back, and how

- **Re-arm** if `[STANDARD] open-position cap` blocks **≥ 20 copies in any 30-day window** (counter proven
  live in §3; 0 today, 0 ever). It returns as a **cap-pressure gate** — fires when the cap refuses a copy,
  never on a calendar — and it must be **re-measured at 168h before it fires**, because that is the one
  horizon whose sign is not against it (§4).
- **This document's §4 reading is wrong** if, at the 2026-11-28 re-read, the in-scope settled population has
  grown past ~600 legs / $7.5k of notional and the alpha is negative with a CI excluding zero at the rail's
  own horizon. Then "the rail is worth nothing at its scope" becomes "the rail costs something at its
  scope", and the anti-rail case is stronger than stated here.
- **Nothing reopens this on capital-days alone.** 399,879 open STANDARD capital-days (23.5% of the lane's
  all-time 1,698,993) is instrument term — median time-to-resolution 4d on settled legs, open book median
  age 104d, 2.3% of legs / 1.9% of notional implied overdue — not stranded capital.

---

## 8. Lane A compliance — what this run did not do

- No `scripts/apply-v*.ts` executed. No RuleSet row written; active ruleset is still **v72**, unmodified.
- **No write of any kind to `prisma/dev.db`** — every query opened read-only (`file:prisma/dev.db`, and the
  replay/analysis scripts use `mode=ro`).
- **No merge to main.** The deletion lives in commit `5297d03` on `wt/v66-retire-calendar-trigger`, and that
  branch's pre-existing uncommitted work (`data/roadmap.json` note edits, the 2026-10-29 draft) was left
  untouched. Main was at `df49185` when this was written and moved only by sibling sessions.
- Nothing that changes what the bot decides or how much it risks was applied; the one code change is
  behaviour-neutral against the live ruleset, which §5's probe demonstrates.

## 9. Reproduce

```bash
cd ~/polymarket-copybot
python3 scripts/standard-168h-replay.py                      # read-only, S.1-S.7 quoted here
sqlite3 -header -column "prisma/dev.db" "SELECT COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) ntl
  FROM PaperTrade WHERE botId='STANDARD' AND isDemo=0 AND status='open'
    AND entryPrice>=0.60 AND (strftime('%s','now')*1000-openedAt)>=168*3600000;"     -- 0 | (null)
sqlite3 -header -column "prisma/dev.db" "SELECT SUM(risksJson LIKE '%open-position cap%') cap_blocks,
  COUNT(*) rows FROM DecisionJournal WHERE createdAt >= (strftime('%s','now')-30*86400)*1000;" -- 0 | 40369
git -C .worktrees/t_757759ca show --stat 5297d03
```

Note on instrumentation: the replay ran to completion (`EXIT=0`, `S.1–S.9`), 2026-11-12 10:52–11:02 CST. Earlier
drafts left `S.8`/`S.9` unquoted because they are network-bound; this run finished them, and they are quoted in
§4.
