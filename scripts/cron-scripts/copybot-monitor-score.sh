#!/bin/bash
# CopyBot: detect new trades from tracked wallets and score them.
set -euo pipefail
LOG=/Users/xsnyde2/polymarket-copybot/logs/cron/copybot-monitor-score.log
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "=== run $(date "+%Y-%m-%dT%H:%M:%S") ==="
LOCKDIR=/tmp/copybot-monitor-score.lock
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
# v37 (tuning review #10): trim API pacing 600→300ms — zero 429s all window,
# runs were duration-bound (~17 min effective cadence), halving per-call delay
# recovers ~40% of cadence.
# v41 (tuning review #12, approved): 4 clean 429 windows — trim 300→150ms.
# v44 (tuning review #13, approved): trim 150→100ms.
#
# tuning #32 rec 1 (user-approved 2026-09-21): ONE sweep per cycle. This script
# used to run monitor:trades TWICE, and the second call's `API_DELAY_MS=100` was
# inert — monitor-trades never reads API_DELAY_MS (only
# src/lib/dead-market-resolution.ts does), so both calls issued the same requests
# at the same pacing. The 24h lookback makes the second sweep pure duplicate load:
# it re-fetches the same window and every fill hits ObservedTrade's unique
# constraint. Cost: 10 data-api 429s across 7 of 109 runs, ending a 6-window clean
# streak. Deleting the sweep halves the monitor's request volume; a fill that
# lands mid-cycle is picked up by the next cycle's 24h window, so nothing is lost.
npm run --silent monitor:trades 2>&1 | tail -6
# v53 (tuning review #22 rec 2, approved 2026-09-11): full score:trades output —
# the old `tail -6` hid [RISK-GATE]/[KELLY]/[DRAWDOWN-SHADOW]/[SHADOW] lines,
# making those counters unprovable lower bounds.
API_DELAY_MS=100 npm run --silent score:trades 2>&1
# Dashboard PnL rollup (2026-09-13): incremental, index-backed refresh so the
# dashboard's in-progress hour is at most ~10 min stale (the hourly update-pnl
# job is the authoritative run). Deliberately NON-fatal — this script drives
# trading and a rollup hiccup must never mask or fail it.
npm run --silent rollup:pnl 2>&1 | tail -2 || echo "WARN: rollup:pnl failed (charts keep last good rollup; update-pnl retries hourly)"
