#!/bin/bash
# CopyBot: weather nowcast-vs-price sampler (card wx2, approved in-thread 2026-10-12 "B";
# multi-city since card weather-city-dfw-set1, 2026-10-27).
#
# WHAT IT IS: a read-only, keyless, forward-only measurement instrument. Each run records the price
# primitives of EVERY bracket of the current daily-high cycles of EACH CITY on BOTH venues, plus the
# physical state of each venue's OWN settlement station (hourly METAR) and the 31-member ensemble:
#   nyc  Kalshi KXHIGHNY (CLINYC) + PM highest-temperature-in-nyc-*    (KLGA) -> data/weather-nowcast-samples.jsonl
#   dfw  Kalshi KXHIGHTDAL (CLIDFW) + PM highest-temperature-in-dallas-* (KDAL) -> data/weather-nowcast-samples-dfw.jsonl
# The city table lives in the sampler (CITIES) -- ONE parameterised path, never a copy per city; a city's
# identity is its own ARTIFACT FILE, so no row carries a city field.
# NOTHING here trades, sizes or touches the Polymarket book, and we hold no Kalshi key, so the
# Kalshi side can only ever be paper. The gate it feeds is FROZEN in
# drafts/weather-nowcast-prereg-20261012.md -- do not move it after the data exists.
#
# WHY HOURLY: the gate needs >= 3 qualifying samples per hour bucket (16:00+ and 18:00+ local) per
# venue per day, and the pre-14:00 distribution read needs morning samples. Hourly gives 8 in the
# 16:00+ bucket; the sample then accrues over >= 20 distinct settled days (weeks, not days).
#
# OBSERVABILITY CONTRACT (matches the other copybot watchdogs)
# -----------------------------------------------------------
# Silent when healthy; prints ONE line (delivered, deliver=origin) per broken thing: a failed city, or a
# city whose artifact did not get a row THIS tick. Freshness is a property of the ARTIFACT, not the job,
# so a script that "succeeds" while writing nothing cannot look healthy -- and with two cities, a healthy
# NYC must not be able to hide a dead DFW, which is why the check is per city and on its OWN file.
set -uo pipefail

REPO=/Users/xsnyde2/polymarket-copybot
LOG="$REPO/logs/cron/copybot-weather-nowcast.log"
CITIES="nyc dfw"
mkdir -p "$(dirname "$LOG")"

stamp=$(date "+%Y-%m-%dT%H:%M:%S%z")

samples_for() {
  case "$1" in
    nyc) echo "$REPO/data/weather-nowcast-samples.jsonl" ;;
    dfw) echo "$REPO/data/weather-nowcast-samples-dfw.jsonl" ;;
    *)   echo "" ;;
  esac
}

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

for city in $CITIES; do
  SAMPLES=$(samples_for "$city")
  OUT=$(python3 scripts/weather-nowcast-sampler.py --city "$city" 2>&1)
  RC=$?
  echo "[$city] $OUT" >>"$LOG"

  if [ $RC -ne 0 ]; then
    echo "🔴 weather-nowcast[$city] FAILED (rc=$RC) at $stamp — last lines: $(echo "$OUT" | tail -2 | tr '\n' ' ')"
    continue
  fi

  # non-empty stdout means the sampler itself raised its hand (e.g. no brackets captured)
  if [ -n "$OUT" ]; then
    echo "$OUT" | tail -1
  fi

  # artifact freshness per city: the newest row in THIS city's file must be from THIS run
  STALE=$(python3 scripts/weather-nowcast-freshness.py "$SAMPLES" "$stamp" "$city")
  if [ -n "$STALE" ]; then
    echo "🟠 $STALE"
  fi
done
exit 0
