#!/bin/bash
# CopyBot: refresh paper-trade PnL and resolve finished markets.
set -euo pipefail
LOG=/Users/xsnyde2/polymarket-copybot/logs/cron/copybot-update-pnl.log
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "=== run $(date "+%Y-%m-%dT%H:%M:%S") ==="
LOCKDIR=/tmp/copybot-update-pnl.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  if [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +45 2>/dev/null)" ]; then
    echo "breaking stale lock (>45 min) and continuing"; rmdir "$LOCKDIR" 2>/dev/null; mkdir "$LOCKDIR" 2>/dev/null || { echo "lock re-acquired by another run — skipping"; exit 0; }
  else
    echo "previous run still active — skipping (lockfile-skip)"; exit 0
  fi
fi
trap "rmdir \"$LOCKDIR\"" EXIT
cd /Users/xsnyde2/polymarket-copybot
unset DATABASE_URL
set -a; source .env; set +a
# 2026-11-15 self-audit — this step used to be `npm run --silent paper:update-pnl 2>&1 |
# tail -6`, and that tail is why 21 hours of failure left no evidence. `tail` flushes only
# at EOF, so when the harness killed the run at its 3600 s ceiling every line the step had
# printed died with the pipe. copybot-update-pnl.log shows it exactly:
#   === run 2026-11-13T10:35:44 ===
#   === run 2026-11-13T12:36:44 ===
#   breaking stale lock (>45 min) and continuing
# nine times over, with not one line of the step that hung — PnlSnapshot has no rows at
# all between 11-13 09:34 and 11-14 06:45.
#
# Now the step (a) streams unbuffered into the tee'd log, so a kill leaves what it was
# doing, and (b) is bounded at 300 s (observed runtime 10-15 s, 20x headroom). The bound
# kills the whole process group (scripts/run-bounded.py — no `timeout(1)` on this host),
# so a hung fetch cannot hold the lock to the harness ceiling and then be "broken" as
# stale by the next hour's run.
BOUNDED="python3 /Users/xsnyde2/polymarket-copybot/scripts/run-bounded.py"
set +e
$BOUNDED --timeout 300 --label "paper:update-pnl" -- npm run --silent paper:update-pnl 2>&1
RC=$?
set -e
if [ "$RC" -ne 0 ]; then
  if [ "$RC" -eq 124 ]; then
    echo "❌ paper:update-pnl BOUNDED OUT at 300s — see the partial output above for the step it died in"
  else
    echo "❌ paper:update-pnl exited $RC"
  fi
  exit "$RC"
fi
# Dashboard PnL rollup (2026-09-13): refresh the hourly PnlHourlyRollup
# pre-aggregate AFTER snapshots land, so /, /performance and /analytics read
# ~2.5k rollup rows instead of scanning all 2M PnlSnapshot rows per page view.
# Fatal on failure: a broken rollup silently freezes the dashboard charts, and
# this job is the authoritative refresh (the monitor-score job also refreshes
# it non-fatally every 10 min for the in-progress hour). The script reconciles
# SUM(rollup) against SUM(PnlSnapshot) and self-heals with a full rebuild.
$BOUNDED --timeout 300 --label "rollup:pnl" -- npm run --silent rollup:pnl 2>&1
