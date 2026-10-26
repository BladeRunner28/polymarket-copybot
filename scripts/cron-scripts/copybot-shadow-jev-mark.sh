#!/bin/bash
# CopyBot: Jev shadow lane — collect states for every scored leg in the window, mark pending
# candidates to settlement, publish data/jev-shadow-summary.json (Option B, approved
# 2026-10-06; freeze-allowed instrumentation — default-off, never touches live rules/positions).
#
# The lane is inert without JEV_SHADOW=1 + an OpenRouter key: with neither set this job only
# grows the replayable state corpus and marks resolutions, which is the real population the
# pre-registered bar will be read on. Set JEV_SHADOW/OPENROUTER_API_KEY in
# /Users/xsnyde2/polymarket-copybot/.env to make the model arm live (rows then carry a cost).
set -euo pipefail
LOG=/Users/xsnyde2/polymarket-copybot/logs/cron/copybot-shadow-jev.log
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "=== run $(date "+%Y-%m-%dT%H:%M:%S") ==="
LOCKDIR=/tmp/copybot-shadow-jev.lock
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
npx tsx scripts/mark-shadow-jev.ts --collect 2>&1 | tail -8
