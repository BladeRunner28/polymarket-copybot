#!/usr/bin/env bash
# copybot-research-collect.sh — fact sheet for the CopyBot research agent (daily + weekly jobs).
# Wrapper exists for two reasons: the collector needs the repo as cwd (relative sqlite path),
# and the repo's .env is sourced the same way every other copybot wrapper does it.
#
# Exit codes are the collector's own (0 = wrote the fact sheet, 1 = hard failure) so the cron
# wrapper can never mask a dead source behind a keep-previous success.
set -uo pipefail
REPO="/Users/xsnyde2/polymarket-copybot"
cd "$REPO" || exit 1
if [ -f .env ]; then set -a; . ./.env; set +a; fi
unset DATABASE_URL 2>/dev/null || true
python3 scripts/research-collect.py "$@"
