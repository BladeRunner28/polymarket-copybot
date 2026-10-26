#!/bin/bash
# CopyBot: weather nowcast-vs-price sampler (roadmap card wx2 — approved in-thread 2026-10-12 "B").
#
# WHAT IT IS: a read-only, keyless, forward-only measurement instrument. Each run records the price
# primitives of EVERY bracket of the current NYC daily-high cycles on BOTH venues (Kalshi KXHIGHNY
# and Polymarket highest-temperature-in-nyc-*), plus the physical state of each venue's own
# settlement station (hourly METAR) and the 31-member ensemble, into
#   data/weather-nowcast-samples.jsonl
# NOTHING here trades, sizes or touches the Polymarket book, and we hold no Kalshi key, so the
# Kalshi side can only ever be paper. The gate it feeds is FROZEN in
# drafts/weather-nowcast-prereg-20261012.md — do not move it after the data exists.
#
# WHY HOURLY: the gate needs >= 3 qualifying samples per hour bucket (16:00+ ET and 18:00+ ET) per
# venue per day, and the pre-14:00 distribution read needs morning samples. Hourly gives 8 in the
# 16:00+ bucket; the sample then accrues over >= 20 distinct settled days (weeks, not days).
#
# OBSERVABILITY CONTRACT (matches the other copybot watchdogs)
# -----------------------------------------------------------
# Silent when healthy; prints ONE line (delivered, deliver=origin) only when the run failed or wrote
# nothing. Freshness is a property of the ARTIFACT, not the job: the newest sample row must be from
# THIS tick, so a script that "succeeds" while writing nothing cannot look healthy.
set -uo pipefail

REPO=/Users/xsnyde2/polymarket-copybot
LOG="$REPO/logs/cron/copybot-weather-nowcast.log"
SAMPLES="$REPO/data/weather-nowcast-samples.jsonl"
mkdir -p "$(dirname "$LOG")"

stamp=$(date "+%Y-%m-%dT%H:%M:%S%z")

LOCKDIR=/tmp/copybot-weather-nowcast.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  if [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +30 2>/dev/null)" ]; then
    rmdir "$LOCKDIR" 2>/dev/null || true
    mkdir "$LOCKDIR" 2>/dev/null || { echo "weather-nowcast: lock held — skipping tick ($stamp)"; exit 0; }
  else
    echo "weather-nowcast: previous run still active — skipping tick ($stamp)" >>"$LOG"
    exit 0
  fi
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

cd "$REPO" || exit 1
echo "=== run $stamp ===" >>"$LOG"

OUT=$(python3 scripts/weather-nowcast-sampler.py 2>&1)
RC=$?
echo "$OUT" >>"$LOG"

if [ $RC -ne 0 ]; then
  echo "🔴 weather-nowcast FAILED (rc=$RC) at $stamp — last lines: $(echo "$OUT" | tail -2 | tr '\n' ' ')"
  exit 0
fi

# non-empty stdout means the sampler itself raised its hand (e.g. no brackets captured)
if [ -n "$OUT" ]; then
  echo "$OUT" | tail -1
fi

# artifact freshness: the newest sample row must have been written by THIS run
python3 - "$SAMPLES" "$stamp" <<'PY'
import json, sys, time
from datetime import datetime, timezone
path, stamp = sys.argv[1], sys.argv[2]
try:
    with open(path) as fh:
        fh.seek(max(0, fh.seek(0, 2) - 8000))
        last = [l for l in fh.read().splitlines() if l.strip()][-1]
    row = json.loads(last)
    ts = datetime.fromisoformat(row["ts"]).timestamp()
    age_min = (time.time() - ts) / 60.0
except Exception as exc:
    print("🟠 weather-nowcast: no readable sample row (%s) at %s" % (exc, stamp))
    sys.exit(0)
if age_min > 75:
    print("🟠 weather-nowcast: newest sample row is %.0f min old at %s — the lane wrote nothing this tick"
          % (age_min, stamp))
PY
exit 0
