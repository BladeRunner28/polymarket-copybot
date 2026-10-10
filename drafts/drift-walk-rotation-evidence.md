# t_81d0a4cb — drift-shadow marker: head-of-line blocking starves the decay bar's 7d cohort

Instrument fix, branch `wt/drift-walk-rotation` (worktree `.worktrees/t_81d0a4cb`), not merged.

## 1. Defect, reproduced

Unmodified code (`git show HEAD:scripts/mark-shadow-longshot.ts`), live log:

```
$ grep -o "shadow-drift: +[0-9]* marked this run (cap [0-9]*/run, backlog [0-9]*)" logs/cron/copybot-shadow-longshot.log | tail -5
shadow-drift: +0 marked this run (cap 300/run, backlog 6147)
shadow-drift: +0 marked this run (cap 300/run, backlog 6154)
shadow-drift: +0 marked this run (cap 300/run, backlog 6156)
shadow-drift: +0 marked this run (cap 300/run, backlog 6161)
shadow-drift: +0 marked this run (cap 300/run, backlog 6164)
```

Trailing consecutive `+0` runs: **14** (earlier streaks in the same log: 22 and 30). `4945 settled` is frozen across 15 consecutive lines.

The old walk selected the first 25 / first 300 keys of the pending map (candidate order). Reconstructed read-only from the same data:

```
pending keys in candidate order: 6147
OLD walk (head of the pending map, cap 25):  window 2026-09-17..2026-09-26
OLD walk (head of the pending map, cap 300): window 2026-09-17..2026-09-26
decided after 2026-10-01: 1127 of 6147 pending keys
```

The head is unresolvable at the venue:

```
$ curl -s -o /dev/null -w "%{http_code}\n" "https://gamma-api.polymarket.com/markets/slug/highest-temperature-in-hong-kong-on-september-18-2026-34c"
200
$ curl -s "https://gamma-api.polymarket.com/markets?slug=highest-temperature-in-hong-kong-on-september-18-2026-34c"
[]
```

## 2. Change

| file | what |
| --- | --- |
| `src/lib/shadow-attempts.ts` (new) | per-candidate attempt ledger + `selectPendingForRun` rotation |
| `scripts/mark-shadow-longshot.ts` | drift walk uses the rotation; stamps attempts; prints the attempted window + cohort reason |
| `tests/shadow-attempt-rotation.test.ts` (new) | 8 tests pinning the ordering, the retry window, coverage and persistence |
| `.gitignore` | `data/shadow-attempt-state.json` (churning runtime state, precedent `data/c200-intent-watch-state.json`) |

Ordering: never-attempted first (most recently **decided** first among themselves) → then least-recently-attempted → a row at/over 3 consecutive failures waits 24 h before re-entering. Ledger is `data/shadow-attempt-state.json`, written atomically, checkpointed every 50 attempts, pruned to pending keys. The other three feeds (lowconf / longshot / wallet-cap) keep their oldest-first `capPending` walk untouched.

New knob: `DRIFT_TEST_LIMIT` caps the drift walk alone (for bounded proof runs); `SHADOW_ATTEMPT_FAIL_LIMIT` / `SHADOW_ATTEMPT_RETRY_HOURS` default to 3 / 24.

## 3. Before / after marker lines (verbatim)

BEFORE (HEAD code, `MARK_LIMIT=25`, same starting data as the after run):

```
shadow-drift: +0 marked this run (cap 25/run, backlog 6147). Gate counterfactual: 26367 would-have entries, 4945 settled (3179 wins, 64.3%), $37159.54 @ $10/trade ($7.51/trade, $0.38/trade ex-dust [695 rows below $0.1]). Summary: .../data/drift-shadow-summary.json
```

AFTER (same cap, same starting data):

```
shadow-drift: +11 marked this run (cap 25/run via DRIFT_TEST_LIMIT, backlog 6147; walk 25/6147 eligible, decided 2026-10-09..2026-10-10, 25 never attempted before, 0 held by the 3-fail/24h retry; trailing-7d attempted 25, resolved 11). Gate counterfactual: 26367 would-have entries, 5028 settled (3206 wins, 63.8%), $36927.64 @ $10/trade ($7.34/trade, $0.32/trade ex-dust [695 rows below $0.1]). Summary: .../data/drift-shadow-summary.json
```

AFTER, production shape (`cap 300/run`, no test limit), two consecutive runs chained:

```
shadow-drift: +276 marked this run (cap 300/run, backlog 6083; walk 300/6083 eligible, decided 2026-10-06..2026-10-08, 300 never attempted before, 0 held by the 3-fail/24h retry; trailing-7d attempted 300, resolved 276).
shadow-drift: +295 marked this run (cap 300/run, backlog 5807; walk 300/5807 eligible, decided 2026-10-03..2026-10-06, 300 never attempted before, 0 held by the 3-fail/24h retry; trailing-7d attempted 300, resolved 295).
```

## 4. Evidence against the exit criteria

**1 — the walk touches candidates decided after 2026-10-01.** Every run prints the window of what it walked: `decided 2026-10-09..2026-10-10` (cap 25), `2026-10-06..2026-10-08`, `2026-10-03..2026-10-06` (cap 300). Reconstructed per run from the ledger stamp joined to the candidates' decision dates: every attempted key in the two bounded runs was decided after 2026-10-01 (25/25 and 25/25), and all 50 were inside the trailing-7d cut.

**2 — backlog/marked move and the attempted set rotates.** Backlog 6147 → 6124 → 6101 → 6083 → 5807 (each run removes the keys it resolved), `marked` 4945 → 5028 → 5073 → 5291 → 5409 → 7296 → 8796. Rotation, two independent ways:

* complete attempted sets of two consecutive runs (new `resolve` rows in the run's wall-clock window ∪ the run's own ledger stamp):

```
run 4 (stamp 2026-10-10T07:51:36.010Z): attempted 25 = 23 resolved + 2 still failing; window 2026-10-09..2026-10-09
run 5 (stamp 2026-10-10T07:52:33.858Z): attempted 25 = 18 resolved + 7 still failing; window 2026-10-08..2026-10-09
overlap between the two consecutive runs' attempted sets: 0 (disjoint — the sets rotate)
attempted keys decided after 2026-10-01: run4 25/25, run5 25/25
```

* the two consecutive cap-300 runs' still-failing sets: `2026-10-10T07:53:42.414Z: 24 rows` vs `2026-10-10T08:01:04.214Z: 5 rows`, overlap **0**. Run 4's rows also keep their original stamp through runs 5 and 6 (they are not re-attempted while never-attempted rows exist).

**3 — cohort7dMarked.** After the cap-300 run: `cohort7dMarked: 3582`, `avgPnlPerTradeExDustLast7dCohort: -0.15` (was 0 / null). The "explicit reason" branch also exists and was exercised on the first smoke run, when the two newest candidates had not settled yet:

```
shadow-drift: +0 marked this run (cap 2/run via DRIFT_TEST_LIMIT, backlog 6147; walk 2/6147 eligible, decided 2026-10-10..2026-10-10, 2 never attempted before, 0 held by the 3-fail/24h retry; trailing-7d attempted 2, resolved 0 — trailing-7d cohort still empty: 0/2 of the attempted candidates decided inside the window resolved at the venue (the rest are still open or archived)).
```

**4 — tsc / vitest / other markers.** `npx tsc --noEmit` clean; `npx vitest run` → 35 files, 391 tests passed (was 34/383). lowconf + wallet-cap lines are byte-identical between the before and after runs at the same cap and same starting data:

```
$ diff <(grep -E "^shadow-(lowconf|wallet-cap)" before-run.log) <(grep -E "^shadow-(lowconf|wallet-cap)" after-run1.log)
(no output)
```

## 5. Marks are real (spot check, read-only)

Five of the 276 rows the cap-300 run marked, re-read from the venue:

```
nfl-tb-dal-2026-10-09-rec-jake-ferguson-3pt5 | UNDER -> marked 1 (entry $0.46) | venue 200: Under @ 1 (closed=true)
nfl-tb-dal-2026-10-09-ryd-bucky-irving-49pt5 | UNDER -> marked 0 (entry $0.30) | venue 200: Over @ 1 (closed=true)
bra-pal-bah-2026-10-08-team-total-home-0pt5 | UNDER -> marked 0 (entry $0.895) | venue 200: Over @ 1 (closed=true)
nfl-tb-dal-2026-10-09-recyd-cade-otton-49pt5 | UNDER -> marked 1 (entry $0.135) | venue 200: Under @ 1 (closed=true)
nfl-tb-dal-2026-10-09-rec-ceedee-lamb-7pt5 | UNDER -> marked 1 (entry $0.19) | venue 200: Under @ 1 (closed=true)
```

## 6. Consequences the operator must know (nothing here re-tuned anything)

* **The drift counterfactual's published numbers move, and the series has a regime break.** Because marking was frozen for weeks and the fix marks the recent cohort first, the drift read now includes rows it never marked before: `marked` 4945 → 8796, win rate 64.3% → 56.2%, `avgPnlPerTradeExDust` $0.38 → $0.14. Any before/after comparison of the *cumulative* drift number across this fix is invalid; the day-level `drift-decay-series.jsonl` row for 2026-10-10 moved from `0.38` (pre-fix code) to `0.14` (post-fix), and 2026-10-10's last row is what the consecutive-days counter reads.
* **The pre-registered 2026-09-20 decay bar now has its cohort input.** `cohort7d: -0.15` (<= $0.50) → `cohortAtOrBelow: true`, while `consecutiveDaysAtOrBelow: 5` of the required 7. The bar is NOT tripped; if the next two days stay at/below the bar it will trip by its own pre-registered rule (which brings forward a maxPriceDrift/longshotDriftPct relaxation, attributed by ruleSetVersion). That decision is the operator's — this card did not touch thresholds or rules.
* The walk consumes the never-attempted front newest-first, so a full pass over the 6,147-key backlog takes ~24-30 h of hourly runs; after that the LRU cycle re-walks the whole set about once per cycle, which keeps the trailing-7d cohort refreshed. New candidates (~2k/day) always sort first, so fresh decisions are marked immediately.

## 7. How to reproduce

```bash
cd /Users/xsnyde2/polymarket-copybot/.worktrees/t_81d0a4cb      # node_modules is a symlink to the main checkout
DATA_MODE=live MARK_LIMIT=25 DRIFT_TEST_LIMIT=25 npx tsx scripts/mark-shadow-longshot.ts
DATA_MODE=live npx tsx scripts/mark-shadow-longshot.ts          # production cap 300
```

Runs write only this worktree's `data/*` copies (live cron artifacts in the main repo were never touched; the worktree's `data/` was snapshotted and restored afterwards, so the branch diff is code-only).
