#!/bin/bash
# BotBankroll size-column DRIFT CHECK — monthly (kanban t_a25f8a45, Lane B instrument repair).
#
# WHY THIS EXISTS
# `BotBankroll.minPositionSize` / `maxPositionSize` are DISPLAY-ONLY (nothing enforces them), so a stale
# row is not a safety hole — it is a MISREADING hazard: it reads like a rail, and scripts/profit-velocity.py
# prints it straight out as `clip $min-$max` in the published daily read. The ML_LANE row advertised
# $0.10 / $100 against an effective $0.25 / $20 from 2026-10-20; it was FOUND on 2026-10-29 and was still
# drifting 22 days later because `scripts/verify-botbankroll-limits.ts` had no caller except a package.json
# script no cron ran. A drift detector that only runs when a human remembers is the same defect class as
# the field it guards, so it now runs on a schedule.
#
# WHAT IT CHECKS
# The table against `effectiveSizeLimits()` in src/lib/safety.ts — the single definition of what each lane
# can actually be given (BOT_LIMITS fallback to STANDARD, plus the Kelly ceiling for KELLY_BOTS only).
#
# CONTRACT (matches the other copybot watchdogs)
#   ok      -> one line to the log, exit 0 (cron job is deliver: local, so a healthy month is silent)
#   drift   -> the verifier's own table is logged, ONE line per drifting value goes to stdout, exit 1;
#              the cron job's failure_deliver: origin turns that into a page.
# The verifier's exit code is the verdict — this wrapper never re-derives the arithmetic.
set -uo pipefail

REPO=/Users/xsnyde2/polymarket-copybot
LOG="$REPO/logs/cron/copybot-verify-bankroll-limits.log"
mkdir -p "$(dirname "$LOG")"

cd "$REPO" || exit 1
stamp=$(date "+%Y-%m-%dT%H:%M:%S%z")

LOCKDIR=/tmp/copybot-verify-bankroll-limits.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  if [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +30 2>/dev/null)" ]; then
    echo "breaking stale lock (>30 min) and continuing" >>"$LOG"
    rmdir "$LOCKDIR" 2>/dev/null
    mkdir "$LOCKDIR" 2>/dev/null || exit 0
  else
    echo "previous run still active — skipping ($stamp)" >>"$LOG"
    exit 0
  fi
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

echo "=== run $stamp ===" >>"$LOG"
OUT=$(npm run --silent verify:bankroll-limits 2>&1)
RC=$?
echo "$OUT" >>"$LOG"

if [ $RC -eq 0 ]; then
  echo "bankroll-limits ok: $(echo "$OUT" | grep -c '   ok$') value(s) match the enforced ceilings" >>"$LOG"
  exit 0
fi

# Drift (or the verifier itself broke). Page with the rows that drifted, one per line.
echo "🔴 bankroll-limits DRIFT at $stamp — BotBankroll size columns no longer match src/lib/safety.ts:"
echo "$OUT" | grep -E 'DRIFT|FAIL|FAILED' || echo "$OUT" | tail -5
echo "   These columns are DISPLAY-ONLY but profit-velocity.py publishes them as 'clip \$min-\$max'."
echo "   Fix with: npx tsx scripts/apply-ml-lane.ts --apply (ML_LANE only) or the row's own writer;"
echo "   never edit kellyMaxSizeUsd/BOT_LIMITS to match a stale row. Full output: logs/cron/copybot-verify-bankroll-limits.log"
exit "$RC"
