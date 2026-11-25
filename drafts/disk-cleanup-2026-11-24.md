# Disk cleanup — executed 2026-11-24

Host was at **21 GB free of 460 GB (96% used)**. Tier 1 executed and verified:
**139 GB free (67% used)** — **+118 GB reclaimed**, nothing in the trading system touched.

```
before   460Gi  398Gi used   21Gi free   96%
after    460Gi  280Gi used  139Gi free   67%
```

## What was freed

| item | how | reclaimed |
|---|---|---|
| Atomic Chat local models | **moved** to `/Volumes/Storage/cold/atomic-chat/models` + symlink back | 79 GB |
| DB snapshots | Oct 10 copy deleted; Nov 15 rollback copy **moved** to `/Volumes/Storage/db-snapshots/` | 21.5 GB |
| Package-manager caches | deleted (`uv`, huggingface, puppeteer, pnpm, Homebrew, pip, electron) | 7.9 GB |
| `.hermes` debris | two `state.db.pre-update-emergency-*.bak` + both pre-update zips | 4.2 GB |
| `~/Downloads` installers | 13 DMGs/PKGs whose apps are already in `/Applications` | 3.2 GB |
| `DarkChampion` ollama model | `ollama rm` — 5 months stale, unreferenced in repo/`.env`/config | 10 GB |

Two things were **moved, not deleted**, so they remain available:
- Atomic Chat's 79 GB of GGUFs — symlink verified readable, so the app still finds them.
- The Nov 15 pre-repair DB snapshot (13 GB) — still the one rollback copy of record.

## Deliberately left alone

- `Library/Caches/ms-playwright` (1.0 GB) — the headless-browser path the audit tooling uses.
- `.hermes/installs/` — live agent environment.
- `~/Downloads/VSCode-darwin-universal.dmg` — VS Code is not in `/Applications`, so that installer is not redundant yet.
- `/Applications/Ollama-0.33.1.app.bak` (599 MB) — stale app backup, operator's call.

## Verified after the deletions

- monitor/scoring cron cycles completing normally (`Scoring complete … rollup-pnl incremental`).
- L2 recorder still writing.
- Dashboard `:3013` returns 200.
- Symlinked model path resolves and a GGUF is readable through it.

## What is still on the table (tier 2 — needs approval, scripted)

**1. Agent worktrees — ~50–66 GB.** 65 worktrees under `.worktrees/`, 61 whose HEAD is already an
ancestor of `main`. **Do not bulk `rm`:** there are 110 uncommitted non-data files across them and
several hold work that is *not* in main (e.g. `wt/phil-counterfactual-ledger-primitive` carries
`src/lib/counterfactual-ledger.ts` + tests; `wt/polyterm-p1-provenance-persistence` carries
`provenance-log.ts`). Procedure: commit WIP to its branch → `git worktree remove` → `git worktree
prune`. Cheaper partial win with no loss: delete only the **clean** checked-out `data/` copies inside
each worktree (restorable with `git checkout -- data`).

**2. `dev.db` retention — 13 GB → ~1.5 GB.** `MarketSnapshot` holds 15.93 M rows with **99.8% older
than 30 days** (35,825 rows in the last 30); `ObservedTrade` 7.78 M rows, 49% recent. `freelist_count
= 0`, so VACUUM reclaims nothing until rows are deleted. Sequence: delete → `VACUUM` → `PRAGMA
wal_checkpoint(TRUNCATE)`, outside cron hours, with headroom (now available).

**3. `data/l2` retention — 28 GB / 58,568 files.** Recording since 2026-09-03 with **no prune job
anywhere in cron or scripts**. Right home is `/Volumes/Storage` (281 GB free) with a dated prune.

**4. `.git` — 3.6 GB, 80 MB/day.** Over the 2048 MB ceiling by 1.7 GB, driven by the nightly backup
committing whatever changed under `data/` (jev-shadow 540 MB/7d, drift 193 MB, lowconf 165 MB).
`git gc --prune=now` first (no rewrite); a history rewrite is a separate decision with its own blast
radius. Three files are already permanently excluded as over GitHub's 100 MB limit
(`wallet-sells` 539 MB, `c200-printthrough` 242 MB, `kalshi-macro-quotes` 117 MB) — they belong on
cold storage with symlinks.

## Root causes (not a list of deletions)

1. **No agent-worktree GC** — 66 GB of checkouts from completed task runs, 61 of them already merged.
2. **No retention policy on any append-only surface** — DB tables, `l2` recordings, shadow JSONLs all
   grow forever; nothing prunes them.
3. **The nightly git backup commits a growing `data/`** — so `data/` growth is charged twice (disk and
   object store), and three artifacts exceed the hosting limit and can never be backed up that way.


---

# Tier 2 — executed 2026-11-24 (same day, approved)

```
21 GB free (96% used)  ->  223 GB free (47% used)     +202 GB total
```

## Worktrees — 66 GB (archived, then removed)

65 agent worktrees under `.worktrees/`, 61 of them on branches already merged into `main`.
**Nothing uncommitted was discarded:** every worktree's WIP was archived first to
`/Volumes/Storage/cold/worktree-wip-20261124/` (65 dirs — `tracked.patch` per branch excluding
`data/`, `untracked.tar.gz`, `status.txt`, `MANIFEST.tsv`; spot-verified that the archive holds
`counterfactual-ledger.ts` + its tests and `provenance-log.ts`). Then `git worktree remove --force`
per worktree → `git worktree prune` → `.worktrees` deleted. **All 69 branches are preserved with
their commits**; repo went 123 GB → 60 GB.

**Near-miss, and the rule it produced:** removing the worktrees broke a live job. The deployed
`~/.hermes/scripts/copybot-kalshi-1c-queue.sh` falls back to
`.worktrees/t_0cb77acd/scripts/cron-scripts/copybot-kalshi-1c-queue.sh`, and the repo copy did not
exist — that script had never been committed, it lived only inside the worktree. Restored from the
archive, committed, and the capture verified running again (new `snaps-2026-11-25.jsonl.gz` +
`coverage.jsonl` at 18:40). **Next GC must grep every deployed wrapper and cron script for
`.worktrees/` references and materialise untracked-only files into the repo BEFORE removal.**

## l2 recordings — 20 GB moved off-volume

43,458 `data/l2` files and 924 `data/l2-events` files older than 30 days moved to
`/Volumes/Storage/cold/l2-cold/` with **symlinks left in place**, so every path-based reader keeps
working (verified by reading order-book JSON through a moved file's symlink). `data/` went 39 GB →
19 GB. Restore path: delete the symlinks, move the files back.

## `.git` — 3.6 GB → 2.0 GB

`git gc --prune=now`: 4,331 loose objects → 0, `size-pack` 2.03 GiB. **No history rewrite** — that
remains a separate decision with its own blast radius.

## Nightly backup fixed (the recurring INCOMPLETE warning)

`wallet-sells.jsonl` (539 MB), `c200-printthrough.jsonl` (242 MB) and `kalshi-macro-quotes.jsonl`
(117 MB) were tracked but permanently over GitHub's 100 MB hard limit, so every night the backup
carried nothing for them and logged `backup INCOMPLETE`. They are now `.gitignore`d and
`git rm --cached` (files stay on disk, unchanged, still growing). The warning should stop tonight.

## NOT done, and why — dev.db retention

The approved plan was "delete old `MarketSnapshot` rows, then VACUUM". Measuring first stopped it:

- `rawMarketJson` is `'{}'` on **100%** of rows, so blanking payloads reclaims nothing — row
  deletion is the only lever.
- `scripts/build-ml-dataset.py:122-131` builds the ML market universe from
  `SELECT DISTINCT marketId FROM MarketSnapshot` and labels each market with
  `resolved_at = MIN(collectedAt) WHERE yesPrice <= 0.10 OR >= 0.90`.
- Live counts: **54,451 markets total, 13,011 with a snapshot in the last 60 days** — a 60-day
  retention deletes **41,440 markets (76%)** from the training universe and shifts `resolved_at`
  forward for every market whose first extreme predates the cut.

That is a training-data change, not a cleanup. Carded as a decision
(`db-retention-policy`) with two options: prune only ACTIVE markets' intermediate snapshots
(preserves the universe), or accept the cut and re-baseline the ML reads. With 223 GB free there is
no urgency to choose badly.
