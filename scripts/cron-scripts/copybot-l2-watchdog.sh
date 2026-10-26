#!/bin/bash
# CopyBot L2 order-book recorder watchdog (v40, Homerun audit): ensure
# scripts/record-l2.ts is running. If not, start it detached with tsx
# (nohup), logging to logs/record-l2.log. Silent when healthy.
set -uo pipefail

if pgrep -f "record-l2" >/dev/null 2>&1; then
  exit 0
fi

cd /Users/xsnyde2/polymarket-copybot
LOG=/Users/xsnyde2/polymarket-copybot/logs/record-l2.log
mkdir -p "$(dirname "$LOG")"
set -a; source .env; set +a
nohup npx tsx scripts/record-l2.ts >>"$LOG" 2>&1 &
sleep 3
if pgrep -f "record-l2" >/dev/null 2>&1; then
  echo "L2 recorder started (pid $(pgrep -f record-l2 | head -1))."
else
  echo "ERROR: L2 recorder failed to start — tail $LOG"
  exit 1
fi
