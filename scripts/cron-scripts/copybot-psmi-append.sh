#!/bin/bash
# CopyBot: append Polycopy's PSMI daily close to our local record.
#
# Approved 2026-09-23 (the "outstanding decision" from card
# polycopy-psmi-regime-measurement): the stored CSV data/polycopy-psmi-history.csv
# is the immovable record of what their API said on the day we read it. Existing
# rows are never rewritten; new dates are appended. No analysis, no LLM — this is
# a pure fetch so a future re-test can run on 2-3x the days.
#
# Their history endpoint keeps maxFreeDepthMonths=24, so the fetch is cheap and
# the cadence only decides how fast we notice a NEW day. Two ticks/day (09:20,
# 21:20) is idempotent: the second is a no-op unless the day's close landed.
set -uo pipefail
LOG=/Users/xsnyde2/polymarket-copybot/logs/cron/copybot-psmi-append.log
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "=== run $(date "+%Y-%m-%dT%H:%M:%S") ==="
LOCKDIR=/tmp/copybot-psmi-append.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  if [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +45 2>/dev/null)" ]; then
    echo "breaking stale lock (>45 min) and continuing"; rmdir "$LOCKDIR" 2>/dev/null; mkdir "$LOCKDIR" 2>/dev/null || { echo "lock re-acquired by another run — skipping"; exit 0; }
  else
    echo "previous run still active — skipping (lockfile-skip)"; exit 0
  fi
fi
trap "rmdir \"$LOCKDIR\"" EXIT
cd /Users/xsnyde2/polymarket-copybot || exit 1
python3 scripts/fetch-psmi-history.py 2>&1
rc=$?
echo "fetch-psmi-history exited $rc"
exit $rc
