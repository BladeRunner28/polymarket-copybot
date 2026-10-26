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
npm run --silent paper:update-pnl 2>&1 | tail -6
# Dashboard PnL rollup (2026-09-13): refresh the hourly PnlHourlyRollup
# pre-aggregate AFTER snapshots land, so /, /performance and /analytics read
# ~2.5k rollup rows instead of scanning all 2M PnlSnapshot rows per page view.
# Fatal on failure: a broken rollup silently freezes the dashboard charts, and
# this job is the authoritative refresh (the monitor-score job also refreshes
# it non-fatally every 10 min for the in-progress hour). The script reconciles
# SUM(rollup) against SUM(PnlSnapshot) and self-heals with a full rebuild.
npm run --silent rollup:pnl 2>&1
