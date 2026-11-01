#!/bin/bash
# Daily git backup: commit + push any changes in the repos listed below.
# Started as copybot-only (hence the filename and job name); now covers every repo in REPOS.
# Silent when nothing changed (watchdog pattern); prints a summary when a backup happened so the
# no_agent cron delivers it to Discord. Exit 1 if any push failed.
set -uo pipefail

REPOS=(
  /Users/xsnyde2/polymarket-copybot
  /Users/xsnyde2/Projects/XrealBeam
)

LOG=/Users/xsnyde2/polymarket-copybot/logs/cron/copybot-git-backup.log
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "=== git backup $(date "+%Y-%m-%dT%H:%M:%S") ==="

# --- SQLite WAL checkpoint (tuning #35 Rec 1, applied 2026-09-24) --------------
# The copybot DB now runs journal_mode=wal. A daily checkpoint(TRUNCATE) folds the WAL
# back into the main DB file and shrinks the -wal to zero, so tonight's snapshot of the
# DB is one consistent file and the WAL cannot grow unbounded overnight. Prints
# "busy|log|checkpointed" pages; busy > 0 means a long-lived reader pinned pages and
# the next checkpoint picks them up. Never fails the backup.
COPYBOT_DB=/Users/xsnyde2/polymarket-copybot/prisma/dev.db
if [ -f "$COPYBOT_DB" ] && command -v sqlite3 >/dev/null 2>&1; then
  ck=$(sqlite3 -cmd ".timeout 15000" "$COPYBOT_DB" "PRAGMA wal_checkpoint(TRUNCATE);" 2>&1)
  mode=$(sqlite3 -cmd ".timeout 15000" "$COPYBOT_DB" "PRAGMA journal_mode;" 2>&1)
  echo "sqlite: journal_mode=${mode} wal_checkpoint(TRUNCATE)=${ck:-<no output>}"
fi

changed=0
failed=0

for repo in "${REPOS[@]}"; do
  name=$(basename "$repo")
  if [ ! -d "$repo/.git" ]; then
    echo "⚠️  ${name}: no git repository at ${repo} — skipped"
    continue
  fi
  cd "$repo" || continue

  # nothing staged/untracked/modified -> stay silent for this repo
  if [ -z "$(git status --porcelain)" ]; then
    continue
  fi

  git add -A

  # Oversize guard (tuning review #38 rec 1 follow-up, 2026-09-28): GitHub rejects
  # any single file over 100 MB at the pre-receive hook, and the rejection kills the
  # WHOLE push. The 09-26 and 09-27 backups failed exactly this way — the job itself
  # committed a 137 MB archive parquet — and the only retry is the next 22:30 run,
  # so the failure cost two days of backup. Unstage anything that big and SAY SO:
  # the rest of the snapshot still lands and the log names what was left behind.
  oversized=()
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    [ -f "$f" ] || continue
    sz=$(stat -f%z "$f" 2>/dev/null || echo 0)
    if [ "$sz" -gt 95000000 ]; then
      git reset -q HEAD -- "$f" 2>/dev/null || git rm -q --cached --ignore-unmatch -- "$f" 2>/dev/null
      oversized+=("$f ($(( sz / 1000000 )) MB)")
    fi
  done < <(git diff --cached --name-only)
  if [ "${#oversized[@]}" -gt 0 ]; then
    echo "⚠️  ${name}: ${#oversized[@]} file(s) over GitHub's 100 MB limit were left OUT of this commit — ${oversized[*]} (move them off this repo or add a .gitignore rule)"
  fi

  n_files=$(git diff --cached --name-only | wc -l | tr -d ' ')
  if [ "$n_files" -eq 0 ]; then
    continue
  fi

  git commit -m "Auto-backup $(date '+%Y-%m-%d %H:%M') — ${n_files} files" >/dev/null 2>&1
  branch=$(git branch --show-current)

  if git push origin "$branch" >/dev/null 2>&1; then
    summary=$(git show --stat --format="%h %s" HEAD | head -1)
    echo "✅ ${name}: backed up ${n_files} files → GitHub (${summary})"
    changed=$((changed + 1))
  else
    echo "❌ ${name}: commit made locally but PUSH FAILED — run: cd ${repo} && git push origin ${branch}"
    failed=$((failed + 1))
  fi
done


# --- Repo growth budget (kalshi-tape-repo-size-policy, Lane B, 2026-10-31) ----
# The tape is TRACKED on the user explicit override, so growth cannot be solved by
# untracking it here (that decision is parked on git-backup-large-artifact-policy).
# What this adds is a measured ceiling: scripts/repo-growth-budget.ts prints one line
# when growth is OUTSIDE policy and nothing when it is inside, so the nightly backup is
# where "tracked is quietly becoming a multi-GB repo" surfaces. Alarm only: it never
# prunes, untracks or gc-s, and it cannot fail the backup. An unreadable check is NOT
# reported as clean — rc 0 with no output is the only silent, healthy case.
growth_out=$(cd /Users/xsnyde2/polymarket-copybot && npx tsx scripts/repo-growth-budget.ts --days 7 --quiet 2>&1)
growth_rc=$?
if [ "$growth_rc" -eq 0 ]; then
  [ -n "$growth_out" ] && echo "$growth_out"
elif [ "$growth_rc" -eq 1 ]; then
  if [ -n "$growth_out" ]; then
    echo "$growth_out"
  else
    echo "⚠️  repo growth: check exited 1 with no output — the budget instrument is broken, not clean"
  fi
else
  echo "⚠️  repo growth: check FAILED rc=${growth_rc} — ${growth_out:-no output} (growth is UNMEASURED tonight; do not read that as inside policy)"
fi

[ "$failed" -eq 0 ] || exit 1
