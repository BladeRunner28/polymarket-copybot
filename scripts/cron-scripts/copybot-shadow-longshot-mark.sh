#!/bin/bash
# CopyBot: resolve pending long-shot shadow-ladder candidates + publish the
# shadow-book summary (2026-09-11 C-200 daily report Change 1, approved;
# freeze-allowed instrumentation — never touches live rules/positions).
set -euo pipefail
LOG=/Users/xsnyde2/polymarket-copybot/logs/cron/copybot-shadow-longshot.log
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "=== run $(date "+%Y-%m-%dT%H:%M:%S") ==="
LOCKDIR=/tmp/copybot-shadow-longshot.lock
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
npm run --silent shadow:mark 2>&1 | tail -8
