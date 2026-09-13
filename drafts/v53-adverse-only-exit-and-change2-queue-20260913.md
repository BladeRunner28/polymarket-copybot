# v53 — C-200 Change 1 (adverse-only stale exit) shipped · Change 2 queued to Oct 8

**Date:** 2026-09-13 · **Approver:** user, in the C-200 daily-report thread ("I approve" + option picks)
**RuleSet:** v52 → **v53** (`changedBy = hermes-v53-tr21-change1-approved`, RuleChange audit row written)
**Status:** Change 1 APPLIED · Change 2 QUEUED (not applied) · one reconciliation finding (see §4)

---

## 1. What shipped (Change 1)

The tier-1 stale exit is now **adverse-only**.

| | before (v29–v52) | after (v53) |
|---|---|---|
| cut trigger at ≥ `staleExitHours` (24h) | `winMove < +5%` ("flat is bad") | `winMove ≤ −15%` (adverse only) |
| flat / slightly-up position at 24h | closed at last price | runs on to max-age |
| 168h hard max-age | unchanged | unchanged (still unconditional) |

New ruleset fields (defaults preserve legacy, so a revert is one field):

- `staleExitAdverseOnly` — 0 = legacy "flat is bad" cut, 1 = adverse-only. **v53 sets 1.**
- `staleExitAdverseMove` — adverse threshold, negative fraction. **v53 sets −0.15.**

Code: `src/lib/paper.ts` (`winMovePct`, `staleExitDecision` — pure, unit-tested), `scripts/update-pnl.ts`
(uses them; per-trade reason string says `v53 adverse-only exit`), `scripts/apply-v53.ts`.

**Revert:** `apply-v54` setting `staleExitAdverseOnly: 0` — the legacy branch is kept byte-identical
in `update-pnl.ts` and pinned by tests (`tests/stale-exit.test.ts`, "legacy branch stays revert-identical").

## 2. Evidence (the numbers the decision rested on)

Raw-row basis (what the 2026-09-13 report quoted): 24–72h exits were 1,069 rows, −$1,215.72 on
$7,152 staked (−17.0% ROI, 44% win) — the entire Polymarket hole; every other hold window positive.

Decision-level basis (deduped, §4): 24–72h = **511 decisions, −$406.10 on $3,308** — still the only
materially negative bucket; `resolved` +$184.62, 72–168h +$104.73, >168h +$360.41.

Direction survives dedupe; **magnitude does not** (roughly ⅓ of the headline). The change was applied
on the direction, which both samples agree on.

## 3. Blast radius at apply (measured, not assumed)

- 58 open C-200 rows, $1,073.65 staked, 0 of which age ≥168h.
- Rows the v53 rule would close on the next hourly run: **0**. Rows the *old* rule would have closed
  that v53 spares: **0**. Of the 30 rows ≥24h, 29 were already ≥+5%.
- So v53 is forward-looking: today's book is cut identically either way; the rule bites on the next
  cohort of flat-at-24h positions.
- Production run exercised end-to-end after the change: `PnL update complete: 1747 updated, 0 resolved,
  0 expired, 0 recycled, 1747/1749 covered (100%)` in 122s — no crash, new predicate evaluated on the
  whole open book. `npx tsc --noEmit` clean; full suite 138/138 green.

## 4. Reconciliation finding — duplicate rows inflate every z-stat

`PaperTrade` carries legacy duplicate accumulation rows (pre-guard multi-entry, same market+outcome).
All-time C-200 finished Polymarket-only: **raw N=1,473 vs decision-level N=785** (688 duplicate rows).

Duplicates are pseudo-replication: one bet counted N times. Effects:

| stat (all-time, PM-only) | raw | deduped |
|---|---|---|
| 08:00 ET | z=−2.69 (−$76.60) | **z=−1.77** (−$12.37) |
| 20:00 ET | z=−2.82 (−$80.43) | **z=−1.35** (−$26.25) |
| band 0.60–0.80 | z=−3.21 (−$66.30) | **z=−2.16** (−$18.72) — survives |
| band 0.40–0.60 | z=−2.26 (−$315.11) | **z=−2.87** (−$133.61) — strengthens |
| band 0.20–0.40 | z=+2.62 but −$214.45 | z=+2.12, **+$132.69** — contradiction was an artifact |
| all-time realized | −$137.06 | **+$243.66** |

Tooling: `scripts/analyze-calibration.py --dedupe` (opt-in; default unchanged so mid-window
comparisons stay stable, writes `…-deduped.json`). `scripts/analyze-change2-gates.py` always dedupes.
Roadmap card `calibration-dedupe-decision` holds the open question (make deduped the published default?).

## 5. Change 2 — approved in principle, queued to the Oct 8 window close

Not applied. Two corrections to the report's framing, both from the pre-apply recon:

- **20:00 ET is already blacked out** (`src/lib/hour-policy.ts`, `C200_BLACKOUT_HOURS_ET = {20}`, v41/v48).
  In-window 20:00 volume is 0 by construction, so "blocklist 08 + 20" reduces to **adding 08:00 ET only**.
- **08:00 ET loses significance at decision level** (z −2.69 → −1.77; in-window N=8, below the N≥20 bar).
  The **0.60–0.80 band is the gate that survives** (all-time z −2.16, in-window z −2.23, N=67, −$20.83)
  and now trips the pre-registered trigger.

Pre-registered trigger (in-window sample only, deduped): `|z| ≥ 2.0` AND realized PnL < 0 AND N ≥ 20.
Read at the Oct 8 close with `python3 scripts/analyze-change2-gates.py`
→ `data/change2-gates-since-2026-09-06.json`. All-time stats are context, never the trigger.

Implementation sketch (at apply, not now): hour gate = add `8` to `C200_BLACKOUT_HOURS_ET` (+ test
update); band gate = per-leg cap in `score-trades.ts` behind a new ruleset field (v47/v44 pattern),
**never** via the symmetric `maxEntryPrice` (it would kill the <0.15 long-shot edge).

## 6. Window caveat (explicit override)

The pre-registered Kelly window runs Sep 8 – Oct 8. v53 landed **mid-window** on explicit user
approval, so the Oct 8 read is "Kelly + v53 adverse-only exit", not a pure Kelly read.
Change-level attribution must come from windowed runs (`analyze-calibration.py --since <date>`), not
from the Oct 8 total. Change 2 and the dead-zone stop stay queued for exactly this reason.
