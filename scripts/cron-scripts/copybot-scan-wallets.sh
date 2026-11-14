#!/bin/bash
# CopyBot: rotate through the wallet backlog, profiling + scoring 25 wallets.
set -euo pipefail
LOG=/Users/xsnyde2/polymarket-copybot/logs/cron/copybot-scan-wallets.log
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "=== run $(date "+%Y-%m-%dT%H:%M:%S") ==="
LOCKDIR=/tmp/copybot-scan-wallets.lock
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
# `tail -8` (was -6): 2026-11-14 self-audit. The [SCAN BUDGET] line and the
# [SCAN PARTIAL] line can now both appear on a truncated run, and with up to 25
# censored [DEPTH] lines above them a -6 window could drop the budget line — the one
# line that says why the batch stopped. Everything the old window kept is still kept.
WALLET_SCAN_LIMIT=25 API_DELAY_MS=200 npm run --silent scan:wallets 2>&1 | tail -8