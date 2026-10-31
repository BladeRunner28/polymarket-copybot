#!/bin/bash
# Cron shim: the canonical atlas-rebuild script lives in the BACKED-UP repo copy (git-backed daily 22:30).
exec bash /Users/xsnyde2/polymarket-copybot/scripts/gdelt-atlas-rebuild.sh "$@"
