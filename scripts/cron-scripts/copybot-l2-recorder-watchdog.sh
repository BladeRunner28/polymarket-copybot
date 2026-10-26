#!/usr/bin/env bash
# L2 recorder watchdog — the in-Hermes equivalent of the LaunchAgent's KeepAlive.
#
# WHY THIS EXISTS: the recorder got started by hand once and nothing supervised it, so it died at ~03:19 on
# 2026-09-26 and L2 coverage stopped with no alarm. A KeepAlive LaunchAgent is written
# (~/Library/LaunchAgents/com.xsnyde2.copybot-l2-recorder.plist) but bootstrap/submit is BLOCKED inside a
# supervised Hermes gateway, so this script is what actually restarts the recorder in the meantime. If the
# agent ever gets bootstrapped by hand, this becomes a redundant second net (it no-ops while one is alive).
#
# Silent while the recorder is healthy — empty stdout means the cron delivers nothing. It speaks only when
# it restarted the recorder or when the recorder is alive but wedged.
set -uo pipefail
cd /Users/xsnyde2/polymarket-copybot

PATTERN='scripts/record-l2.ts'
STALE_LIMIT=600          # heartbeat is every 15s; 40 missed beats = the process is wedged, not busy
LOCK=/tmp/copybot-l2-recorder-watchdog.lock

if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
    rmdir "$LOCK" 2>/dev/null; mkdir "$LOCK" 2>/dev/null || exit 0
  else
    exit 0               # a previous run is still working — never start a second recorder
  fi
fi
trap 'rmdir "$LOCK"' EXIT

count() { pgrep -f "$PATTERN" 2>/dev/null | wc -l | tr -d ' '; }
heartbeat_age() { echo $(( $(date +%s) - $(stat -f %m logs/record-l2.log 2>/dev/null || echo 0) )); }

n=$(count)
if [ "$n" -ge 1 ]; then
  age=$(heartbeat_age)
  if [ "$age" -gt "$STALE_LIMIT" ]; then
    echo "🚨 **L2 recorder is wedged** — the process is alive but its heartbeat log has not been written for ${age}s (limit ${STALE_LIMIT}s; it beats every 15s). Killing and restarting it: sockets stopped delivering, so every pinned-market window in that gap is unmeasurable."
    pkill -f "$PATTERN" || true
    sleep 5
    python3 scripts/start-l2-recorder.py
    sleep 20
    if [ "$(count)" -ge 1 ]; then
      echo "  restart OK — $(tail -1 logs/record-l2.log)"
    else
      echo "  ⚠️ restart FAILED — last lines: $(tail -3 logs/record-l2.log | tr '\n' ' | ')"
    fi
  fi
  exit 0                 # healthy: say nothing
fi

echo "🚨 **L2 recorder was DOWN** — restarting it ($(date '+%H:%M:%S')). Book snapshots and the pinned-market quote tape had stopped, so any C-200 dispatch in the gap is unmeasurable."
python3 scripts/start-l2-recorder.py
sleep 20
if [ "$(count)" -ge 1 ]; then
  echo "  restart OK — $(tail -1 logs/record-l2.log)"
else
  echo "  ⚠️ restart FAILED — last lines: $(tail -3 logs/record-l2.log | tr '\n' ' | ')"
fi
