#!/bin/bash
# Kelly window report data collector (daily/weekly/final). Emits markdown to
# stdout for the cron agent; retries on sqlite lock (monitor-score writes).
cd /Users/xsnyde2/polymarket-copybot || exit 1
export DATABASE_URL="file:./dev.db"
for attempt in 1 2 3; do
  OUT=$(npx tsx scripts/kelly-window-report.ts auto 2>/tmp/kelly-report-err.log)
  RC=$?
  if [ $RC -eq 0 ] && [ -n "$OUT" ]; then
    echo "$OUT"
    exit 0
  fi
  echo "attempt $attempt failed (rc=$RC): $(head -c 300 /tmp/kelly-report-err.log)" >&2
  sleep 10
done
exit 1
