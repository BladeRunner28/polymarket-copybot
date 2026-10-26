#!/bin/bash
# Daily capital report → Discord (no-agent cron job: stdout IS the message).
#
# Runs the /capital series report and prints the Discord digest. Everything
# except the digest goes to the log file (stdout must stay clean or the log
# lines land in Discord). Always prints — a flat day still reports.
#
#   digest       : the Discord message
#   --write (set below) also refreshes drafts/capital-deposits-<day>.md, which
#                 the dashboard serves at :3013/drafts/<slug>.
set -uo pipefail

PROJ=/Users/xsnyde2/polymarket-copybot
LOG=$PROJ/logs/cron/copybot-capital-report.log
mkdir -p "$(dirname "$LOG")"
echo "=== run $(date "+%Y-%m-%dT%H:%M:%S") ===" >>"$LOG"

LOCKDIR=/tmp/copybot-capital-report.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  if [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +30 2>/dev/null)" ]; then
    echo "breaking stale lock (>30 min)" >>"$LOG"
    rmdir "$LOCKDIR" 2>/dev/null
    mkdir "$LOCKDIR" 2>/dev/null || { echo "lock re-acquire failed — skip" >>"$LOG"; exit 0; }
  else
    echo "previous run still active — skipping" >>"$LOG"
    exit 0
  fi
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null' EXIT

cd "$PROJ" || { echo "project dir missing" >&2; exit 1; }
export DATABASE_URL="file:./dev.db"

# Retry: the monitor-score cron holds the SQLite write lock for ~15 min at a time.
for attempt in 1 2 3; do
  OUT=$(npx tsx scripts/capital-deposits-report.ts --write --discord 2>>"$LOG")
  RC=$?
  if [ $RC -eq 0 ] && [ -n "$OUT" ]; then
    echo "$OUT"
    echo "delivered $(printf '%s' "$OUT" | wc -l | tr -d ' ') lines" >>"$LOG"
    exit 0
  fi
  echo "attempt $attempt failed (rc=$RC)" >>"$LOG"
  sleep 10
done

echo "capital report FAILED after 3 attempts — see $LOG" >&2
exit 1
