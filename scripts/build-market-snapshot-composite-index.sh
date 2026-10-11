#!/bin/bash
# Stage the composite index build in a QUIET window: wait for the monitor-score run
# (which writes continuously for ~10 min) to release its lock, then build + measure.
set -uo pipefail
cd /Users/xsnyde2/polymarket-copybot
LOCK=/tmp/copybot-monitor-score.lock

echo "=== waiting for a quiet window (monitor-score lock: $LOCK) ==="
for i in $(seq 1 36); do
  if [ ! -d "$LOCK" ] && ! pgrep -f "scripts/score-trades.ts" >/dev/null && ! pgrep -f "scripts/monitor-trades.ts" >/dev/null; then
    echo "quiet at $(date +%H:%M:%S) after $((i*15))s of polling"
    break
  fi
  sleep 15
done
if [ -d "$LOCK" ]; then echo "STILL LOCKED at $(date +%H:%M:%S) — aborting, no DDL run"; exit 3; fi

echo "=== plan BEFORE ==="
sqlite3 prisma/dev.db "EXPLAIN QUERY PLAN SELECT marketId, MAX(collectedAt) AS c, timeToResolution, question, isDemo FROM MarketSnapshot WHERE marketId IN ('x','y') GROUP BY marketId;"

echo "=== building MarketSnapshot_marketId_collectedAt_idx $(date +%H:%M:%S) ==="
/usr/bin/time -p sqlite3 prisma/dev.db ".timeout 120000" "CREATE INDEX IF NOT EXISTS MarketSnapshot_marketId_collectedAt_idx ON MarketSnapshot(marketId, collectedAt);" 2>&1 | tail -4

echo "=== plan AFTER ==="
sqlite3 prisma/dev.db "EXPLAIN QUERY PLAN SELECT marketId, MAX(collectedAt) AS c, timeToResolution, question, isDemo FROM MarketSnapshot WHERE marketId IN ('x','y') GROUP BY marketId;"

echo "=== index sizes ==="
sqlite3 prisma/dev.db "SELECT name, SUM(pgsize)/1048576 AS mb FROM dbstat WHERE name LIKE 'MarketSnapshot%' GROUP BY name;"

echo "=== integrity of the new index vs a sample of markets (should return 0 rows) ==="
sqlite3 prisma/dev.db "SELECT COUNT(*) AS mismatches FROM (SELECT marketId, MAX(collectedAt) mx FROM MarketSnapshot GROUP BY marketId LIMIT 200) a WHERE NOT EXISTS (SELECT 1 FROM MarketSnapshot s WHERE s.marketId=a.marketId AND s.collectedAt=a.mx);"
echo "done $(date +%H:%M:%S)"
