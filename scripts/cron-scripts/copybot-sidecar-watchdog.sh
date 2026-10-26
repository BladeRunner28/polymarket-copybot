#!/bin/bash
# CopyBot watchdog: if the Rust execution sidecar (port 3014) is down, restart
# it via launchd and alert Discord. Healthy ticks print nothing (silent no-op
# for the Hermes cron), so this only makes noise when something is actually wrong.
# Also tracks restart frequency (tuning review #9): >=4 restarts in the last
# hour = crash-loop, escalated alert even when the individual restart succeeds.
set -uo pipefail

PORT=3014
LABEL="com.xsnyde2.copybot-rust-sidecar"
PROJECT=/Users/xsnyde2/polymarket-copybot
RESTART_LOG=/tmp/copybot-sidecar-restarts.log

if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
  exit 0  # healthy — stay silent
fi

cd "$PROJECT"
set -a; source .env 2>/dev/null; set +a

# Record this restart attempt (prune entries older than 1h first)
NOW=$(date +%s)
awk -v now="$NOW" '$1 > now - 3600' "$RESTART_LOG" 2>/dev/null > "$RESTART_LOG.tmp" 2>/dev/null || true
mv "$RESTART_LOG.tmp" "$RESTART_LOG" 2>/dev/null || true
echo "$NOW" >> "$RESTART_LOG"
RESTARTS_1H=$(wc -l < "$RESTART_LOG" 2>/dev/null | tr -d ' ')
RESTARTS_1H=${RESTARTS_1H:-0}

MSG="🚨 **CopyBot Alert: Rust Execution Sidecar DOWN** — port $PORT not listening at $(date '+%Y-%m-%d %H:%M:%S %Z'). C-200 (BANKROLL_200) cannot open trades while it is down. Attempting restart…"
if [ "$RESTARTS_1H" -ge 4 ]; then
  MSG="🔴 **CopyBot Alert: sidecar CRASH-LOOP** — ${RESTARTS_1H} restarts in the last hour (threshold 3). Port $PORT not listening at $(date '+%Y-%m-%d %H:%M:%S %Z'). Watchdog restarting again…
$MSG"
fi

# Restart via launchd (kickstart -k kills and restarts the job); if launchd
# control is unavailable (gateway sandbox / no agent installed), launch the
# binary directly so the sidecar comes back regardless.
launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null
sleep 5
if ! nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
  nohup "$PROJECT/rust-sidecar/target/debug/polyhydra-whale-signal" >> "$PROJECT/logs/rust-sidecar.log" 2>&1 &
  sleep 6
fi

if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
  MSG="$MSG
✅ Restart succeeded — sidecar is back up."
else
  MSG="$MSG
❌ Restart FAILED — inspect $PROJECT/logs/rust-sidecar.err.log manually."
fi

if [ -n "${DISCORD_WEBHOOK_URL:-}" ]; then
  PAYLOAD=$(python3 -c "import json,sys; print(json.dumps({'content': sys.argv[1][:1990]}))" "$MSG")
  curl -s -m 15 -H "content-type: application/json" -d "$PAYLOAD" "$DISCORD_WEBHOOK_URL" >/dev/null 2>&1
fi

echo "$MSG"
