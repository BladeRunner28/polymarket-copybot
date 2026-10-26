#!/bin/bash
# CopyBot caffeinate watchdog (tuning review #9, rec 1): ensure the Mac never
# idle-sleeps during trading windows. If a caffeinate is already running (the
# launchd agent com.xsnyde2.copybot-caffeinate OR a previous fallback), stay
# silent (no-op for the Hermes cron). Otherwise prefer the launchd agent via
# kickstart; if it isn't loaded, spawn a detached caffeinate so the assertion
# survives this script's exit.
set -uo pipefail

if pgrep -x caffeinate >/dev/null 2>&1; then
  exit 0
fi

launchctl kickstart -k "gui/$(id -u)/com.xsnyde2.copybot-caffeinate" 2>/dev/null
sleep 2
if pgrep -x caffeinate >/dev/null 2>&1; then
  echo "caffeinate launched via launchd agent."
  exit 0
fi

nohup /usr/bin/caffeinate -imsu >/dev/null 2>&1 &
sleep 1
if pgrep -x caffeinate >/dev/null 2>&1; then
  echo "caffeinate fallback started (launchd agent not loaded — run: launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.xsnyde2.copybot-caffeinate.plist)"
else
  echo "ERROR: could not start caffeinate."
  exit 1
fi
