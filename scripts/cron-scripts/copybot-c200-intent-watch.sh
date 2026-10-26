#!/usr/bin/env bash
# C-200 fill-intent watcher (c200-maker-fill-assumption instrument) + L2 coverage alarms: alerts when the
# gate clears (>=50 measured legs), when a leg is booked without an intent stamp, when a gap is not the
# modelled -$0.02, when an intent is dispatched but never booked, when the shadow revert switch is on,
# when a dispatch's market has no L2 book coverage around its own t0 (check 7, v62), or when the L2
# recorder is dead or its heartbeat is stale (check 8).
# Silent when healthy — empty stdout = the Hermes cron delivers nothing.
set -uo pipefail
cd /Users/xsnyde2/polymarket-copybot
exec python3 scripts/c200-intent-watch.py
