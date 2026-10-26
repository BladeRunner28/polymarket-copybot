#!/bin/bash
# CopyBot: Kalshi MACRO shadow lane (workstream "complementary Kalshi", option B).
#
# WHAT IT IS: a read-only, forward-only measurement instrument. Each run snapshots
# Kalshi's macro families (CPI / Fed / U3 / GDP / NBER recession / payrolls) and
# records a settlement row the first time a held market resolves, so the lane can be
# scored as a CALIBRATION curve (implied at H hours to close vs realized). Nothing
# here trades, sizes or touches the Polymarket book, and Kalshi publishes no wallet
# attribution at all, so this can never become a copy lane.
#
# WHY HOURLY: the pre-registered read (in scripts/kalshi-macro-shadow.py, written
# before the data existed) needs, per settled market, one quote at >=24h to close and
# one at <=6h to close. Hourly runs give sub-hour resolution on the short bucket; the
# sample accrues over weeks because these families are event-driven.
#
# OBSERVABILITY CONTRACT (matches the other copybot watchdogs)
# -----------------------------------------------------------
# Silent when healthy; prints ONE line (delivered, deliver=origin) only when the run
# failed or appended no quote rows. Freshness is a property of the ARTIFACT: this
# wrapper also checks the newest quote row's age, so a script that "succeeds" while
# writing nothing cannot look healthy.
set -uo pipefail

REPO=/Users/xsnyde2/polymarket-copybot
LOG="$REPO/logs/cron/copybot-kalshi-macro.log"
QUOTES="$REPO/data/kalshi-macro-quotes.jsonl"
mkdir -p "$(dirname "$LOG")"

stamp=$(date "+%Y-%m-%dT%H:%M:%S%z")

LOCKDIR=/tmp/copybot-kalshi-macro.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  if [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +30 2>/dev/null)" ]; then
    rmdir "$LOCKDIR" 2>/dev/null || true
    mkdir "$LOCKDIR" 2>/dev/null || { echo "kalshi-macro: lock held — skipping tick ($stamp)"; exit 0; }
  else
    echo "kalshi-macro: previous run still active — skipping tick ($stamp)" >>"$LOG"
    exit 0
  fi
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

cd "$REPO" || exit 1
echo "=== run $stamp ===" >>"$LOG"

OUT=$(python3 scripts/kalshi-macro-shadow.py 2>&1)
RC=$?
echo "$OUT" >>"$LOG"

if [ $RC -ne 0 ]; then
  echo "🔴 kalshi-macro FAILED (rc=$RC) at $stamp — last lines: $(echo "$OUT" | tail -2 | tr '\n' ' ')"
  exit 0
fi

# artifact freshness, not job status: the newest quote row must be from THIS run
python3 - "$QUOTES" "$stamp" <<'PY'
import json, sys, time
from datetime import datetime, timezone
path, stamp = sys.argv[1], sys.argv[2]
try:
    with open(path) as fh:
        fh.seek(max(0, fh.seek(0, 2) - 4000))
        last = [l for l in fh.read().splitlines() if l.strip()][-1]
    row = json.loads(last)
    ts = datetime.fromisoformat(row["ts"]).timestamp()
    age_min = (time.time() - ts) / 60.0
except Exception as exc:
    print("🟠 kalshi-macro: no readable quote row (%s) at %s" % (exc, stamp))
    sys.exit(0)
if age_min > 15:
    print("🟠 kalshi-macro: newest quote row is %.0f min old at %s — the lane wrote nothing this tick"
          % (age_min, stamp))
PY
exit 0
