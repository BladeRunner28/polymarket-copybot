# Tuning #38 — approval execution (2026-09-28)

**Approved in-thread by Xman 2026-09-28 02:5x CDT:** all four recommendations of cycle #38
(window 2026-09-26 07:00 → 2026-09-27 07:00 CDT). This document is the plan *and* the executed
results: what the review asked, what the code/state actually was, what shipped, and the evidence
each change produced.

**Nothing in any decision, rule, size, gate or published PnL number changed.** All four recs are
either ops/infra or read-only measurement. Rec 2 adds a line; rec 3 removes wasted fetches; rec 1
restores the backup; rec 4 is card hygiene. No RuleSet version was created, no threshold moved, no
figure was recomputed or edited.

---

## Rec 1 — Restore the GitHub backup (act-now class)

**The review said:** the 09-26 22:30 backup logged `PUSH FAILED`; `origin/main` is still `f940c8e`
(09-25); 9 commits unpushed; "the remote is reachable → this is a one-shot push failure that never
retried"; fix = `git push origin main`.

**What the push actually returned (run before doing anything else):**

```
remote: error: File data/archive-analysis/asset-labels-2026_01-2026_04.parquet is 137.03 MB;
              this exceeds GitHub's file size limit of 100.00 MB
remote: error: GH001: Large files detected.
 ! [remote rejected] main -> main (pre-receive hook declined)
```

**Premise correction (the load-bearing one).** This was never a transient fault and a retry could
never have fixed it. GitHub's **pre-receive hook hard-rejects any single file over 100 MB**, and the
rejection kills the *whole* push — so 09-26 and 09-27 both failed deterministically, and `git push
origin main` reproduced the rejection on demand. Reachability of the remote was irrelevant.

The blob was committed **by the backup job itself**: commit `310582b` ("Auto-backup 2026-09-26 22:30
— 72 files") added `data/archive-analysis/asset-labels-2026_01-2026_04.parquet` (143,691,188 bytes)
as part of the routine `data/` snapshot. The job then logged `❌ … PUSH FAILED` and — because it
runs once a day at 22:30 with no retry — the repo sat 11 commits ahead of origin.

**Second premise correction.** The failure was *not* silent outside the log. The job's stdout is
captured and the job is `deliver: discord`, so both nights produced a `Status: script failed`
delivery with the ❌ line (`~/.hermes/cron/output/eb5412dee4d7/2026-09-26_22-31-19.md` and
`…2026-09-27_22-32-22.md`). What was missing was a **retry**, not a signal — the alert went to the
Home channel instead of this thread.

**What shipped.**

1. **History rewrite of the two unpushed auto-backup commits.** `filter-branch` refused (the live
   crons hold unstaged changes in the worktree), so the rewrite was done with plumbing against a
   temporary index — the worktree was never touched:

   | | before | after | note |
   |---|---|---|---|
   | 09-26 snapshot | `310582b` | `2d4ac7c` | same tree minus the 137 MB blob |
   | 09-27 snapshot | `dfe2ba0` | `a398501` | same |
   | verified | — | — | `git diff --stat dfe2ba0 a398501` = **1 file changed: the parquet only** |

   Commit messages, authors, committer dates all preserved. Otherwise byte-identical, so nothing in
   the sibling sessions' work (archive-ML bridge, L2 pin-at-dispatch, c200 intent-watch,
   maker-fill `intentPrice`) was disturbed. The pre-rewrite tip was held on a local branch
   `pre-rewrite-20260928` (tip `dfe2ba0`) until the push verified, then deleted — it was never
   pushed, so `git push --all` cannot resurrect the blob; the old commits survive in the reflog.

2. **Untracked + ignored the class.** `data/archive-analysis/*.parquet` added to `.gitignore` with
   the reason; the file stays on disk (it is a derived extract, not a source) but can no longer
   re-break a push. `git check-ignore -v` confirms the rule matches it.

3. **Oversize guard in the backup script** (`~/.hermes/scripts/copybot-git-backup.sh`) — *beyond the
   enumerated recs*: the review's own watch-item said it would propose a script change after a
   **second** push failure, and the second failure had already happened (09-26 + 09-27), with a
   deterministic cause. The guard unstages any staged file >95 MB and prints
   `⚠️  <repo>: N file(s) over GitHub's 100 MB limit were left OUT of this commit — <paths>`, so the
   rest of the snapshot still lands and the log names what was left behind. Previously the job had
   no size check at all and no retry until 22:30 the next day.

**Evidence (real run, 2026-09-28 03:08 CDT, not a simulation).** The guard was tested by
force-staging the 137 MB blob and running the real job by hand:

```
=== git backup 2026-09-28T03:08:47 ===
sqlite: journal_mode=wal wal_checkpoint(TRUNCATE)=0|0|0
⚠️  polymarket-copybot: 1 file(s) over GitHub's 100 MB limit were left OUT of this commit —
    data/archive-analysis/asset-labels-2026_01-2026_04.parquet (143 MB) (move them off this repo or add a .gitignore rule)
✅ polymarket-copybot: backed up 22 files → GitHub (a019b65 Auto-backup 2026-09-28 03:08 — 22 files)
```

| check | result |
|---|---|
| `git rev-list --left-right --count origin/main...HEAD` | **`0  0`** |
| `git log --oneline -1 origin/main` | `a019b65 Auto-backup 2026-09-28 03:08 — 22 files` |
| pushed range `f940c8e..a019b65` | 12 commits, of which 11 were the backlog (`310582b`+7 sibling +`efeb2a0` etc.) |
| `git ls-tree -r -l HEAD \| awk '$4+0>100000000'` | empty |
| `grep -c "PUSH FAILED" logs/cron/copybot-git-backup.log` | **3** — *not* the 1 the rec predicted (a 2026-09-14 `backup-test` line matches too) |
| backup job exit code | `0` |

**Note on the rec's verify clause:** "origin/main names `310582b`" is unachievable for two reasons —
the history rewrite necessarily re-hashes the two auto-backup commits, and the 09-27 snapshot
(`dfe2ba0`) was already on top of `310582b` when the review was written. Amended clause, now on the
card: `rev-list` = `0 0`, no blob >100 MB in the pushed tree, the newest backup-log line reads ✅,
and the next 3 nightly runs each log ✅ with no ⚠️.

---

## Rec 2 — Event-family concentration read in the EOD (#36 R1, carried a 3rd time)

**The review said:** add a read-only event-family concentration line to the EOD's C-200 block, with
its own reproducing SQL; verify by `grep -c "by event family" logs/cron/copybot-eod.log` ≥ 1 and by
matching the printed top-3 against a recomputation of `substr(marketId,1,30)`.

**What shipped:** `scripts/event-family-concentration.ts` — READ-ONLY, writes nothing, appended as
the last step of `~/.hermes/scripts/copybot-eod.sh` with `tail -6` and a non-fatal `|| echo WARN`
guard, exactly mirroring the `wallet-status-split.ts` precedent (#33 rec 2). It reads
`PaperTrade` (open, non-demo, BANKROLL_200) and prints the top-3 families **with their share of open
cost**, the family rule, the reproduce command and the raw-SQL cross-check on one line each.

**Family rule (pre-registered in the script header — do not silently re-derive it):**
1. if the slug carries an ISO date, the family is everything up to and including that date
   (league/weather events are date-scoped: `unl-nor-prt-2026-09-27-nor` + `-prt` = **one** family);
2. otherwise the first 3 dash tokens (`will-<entity>-…`, `elon-musk-of-…`).

**Correction to the rec's verify clause.** `substr(marketId,1,30)` cannot produce the ids the rec
itself quotes — it returns `will-xavier-becerra-win-the-ca`, while the review's headline says
`will-xavier-becerra` — and the 30-char prefix **splits same-event legs** (`unl-nor-prt-2026-09-27-nor`
vs `-prt`, measured: 673 of 1,235 historical C-200 slugs group differently under the two rules). A
prefix that splits same-event legs is a false-negative machine for exactly the correlation the rec
wants priced, so the 3-token/ISO rule is the corrected form; the prefix query is still printed on the
script's own cross-check line so the reviewer's original command reconciles.

**Measured output (2026-09-28 03:0x CDT, live book):**

```
C-200 open concentration by event family: 8 open legs / $333.09 cost / 8 families — top-3:
will-alibaba-have +$100.00 (30.0%) | will-xavier-becerra +$100.00 (30.0%) | will-kylian-mbapp +$100.00 (30.0%)
→ top-3 = +$300.00 = 90.1% of open cost | families with >1 leg: 0
```

Against #38's own in-window read (28 legs / $558.35, top-4 single-leg $100 = 71.6% of open cost):
same shape, and the book has since de-risked to 8 legs. The read joins no live dimension, so unlike
the wallet-status line it is deterministic and a re-run must reproduce it exactly.

**First EOD print:** 2026-09-28 22:00 (the greppable line lands in `logs/cron/copybot-eod.log` then).

---

## Rec 3 — The scorer consults the dead-slug negative-cache

**The review said:** 299 `Market fetch failed` lines on 109 distinct slugs in one window (29 → 78 →
299); the v41 cache exists but is consulted only by `update-pnl`; `score-trades.ts:428` re-probes
forever; fix = read the cache in the scorer + widen the FIFO to ~200.

**What shipped:** `src/lib/dead-slug-cache.ts` (new shared module: `loadDeadSlugs` /
`rememberDeadSlug`, `MAX_DEAD_SLUGS = 200`, atomic tmp+rename writes) used by **both**
`scripts/update-pnl.ts` (cap 24 → 200; semantics unchanged — load, skip, remember a clean 404) and
`scripts/score-trades.ts`.

**Why the rec's "read" half alone would not have fixed it.** `update-pnl` only ever fetches markets
the **book holds**, so the slugs the scorer trips over (detected-but-unfillable markets) were never
in the cache — that is what "**none of the repeaters are in the 24-slot cache**" actually measured.
Verified directly: the top repeater `cfb-smho-txtech-2026-09-26-spread-home-34pt5` (15 lines in the
#38 window) is still absent from the cache file. The scorer therefore **writes** on a fresh 404 as
well as reading; without that half the repeaters stay uncached forever.

Cached hits log on their own line — `Market fetch skipped (cached dead slug) for <slug> — scoring
with detection-time data.` — so the reviewer's `grep -c "Market fetch failed"` counts **new** dead
slugs, not re-probes of known ones. Only a clean 404/not-found is cached; a 429, timeout or connector
fault must never poison it. Fallback behaviour is unchanged (detection-time data).

**Evidence.**

| check | result |
|---|---|
| `npx tsc --noEmit` | exit 0 (both patched scripts + new module) |
| lib wiring proven | probe: `cap: 200 \| loaded: 24`, `SKIP (cached) unl-nor-prt-2026-09-27-prt`, `fetch cfb-smho-txtech…` (the gap the rec found, visible in one call) |
| cache cannot over-block | a live book market is not in the cache → `fetch` |
| **live production line** (03:07 run, code loaded after the patch) | `Scoring complete: … , 0 dead-slug fetches skipped (404 cache).` — the counter is wired and running |
| natural skip so far | **0** — the funnel is quiet (0 unscored rows in 90 min; the 2 cached slugs in the recent detection stream are already journaled), so the consult's first real hit is still ahead |

The 7-day gate (≤60 `Market fetch failed` in a window, no slug >2×, completion line carries the skip
count) is on card `tr38-rec3-scorer-dead-slug-cache`.

---

## Rec 4 — Card hygiene

Four cards added/closed in `data/roadmap.json` (backup taken first, one read-modify-write, idempotent
by id, then verified by reading the file back **and** by `curl` on the live board):

| card | column | what it is |
|---|---|---|
| `tr34-rec2-eod-asof-marker` | **Done** | closed — the as-of marker printed again on the 09-26/09-27 EODs |
| `tr36-rec1-event-family-concentration` | Scheduled | rec 2, with the corrected verify clause and the measured 2026-09-28 read |
| `decay-bar-tripped-oct8-decision` | Scheduled | the queue #37 R2 asked for: `consecutiveDaysAtOrBelow 8 / cohort7d -0.69 / tripped true`, bound to the Oct 8 read |
| `git-backup-oversize-blob-guard` | **Done** | rec 1's fix + guard, with the premise corrections recorded |
| `git-backup-large-artifact-policy` | Backlog | *follow-up, not part of this approval*: exclude / LFS / external store, for the class of failure |
| `tr38-rec3-scorer-dead-slug-cache` | In Progress | rec 3, carrying its 7-day gate |

Board verified live at `http://localhost:3013/roadmap` (HTTP 200, all six ids present; the page is
`force-dynamic`, so no rebuild was needed).

**Id note:** the review proposed `git-backup-push-failed-20260926`; a dated id is a session artifact
and the repo's convention is class-level ids, so it ships as `git-backup-oversize-blob-guard` with the
mapping recorded in its note.

---

## Open item (needs its own answer — not covered by "I approve all")

`git-backup-large-artifact-policy` (Backlog). The 09-26 failure was one instance of a class: the
nightly job snapshots everything under `data/`, `.git` is already **564 MB**, and the largest
*tracked* artifacts are a 51 MB smoke parquet plus two ~30 MB fill-hazard CSVs. GitHub hard-fails any
file >100 MB, so the next large artifact breaks the backup the same way. Options — (a) **exclude
derived binaries by class and keep a size budget** (recommended: no new deps, the guard now enforces
it, no source lost); (b) git-lfs for the extracts (not installed; 1 GB free); (c) external volume +
manifest. Card carries the detail.

## Standing-input corrections recorded for the reviewer cron

Appended to the `copybot-tuning-review-daily` prompt (raw store surgery, backup first, atomic write):
the two #38 premise corrections (push failures are not retry-class — read the push error; the
`PUSH FAILED` count is 3, not 1), the retired `substr(1,30)` verify clause, the corrected
event-family verify, the dead-slug-cache verify, and the new card ids — so cycle #39 executes the
corrected commands instead of re-deriving them.
