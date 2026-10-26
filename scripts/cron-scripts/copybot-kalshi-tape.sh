#!/bin/bash
# CopyBot: capture a GAP-FREE window of Kalshi's public trade tape (workstream
# "complementary Kalshi", option A) for the allowlisted families in
# data/kalshi-tape-families.json.
#
# WHY A SCHEDULE IS THE WHOLE POINT
# ---------------------------------
# Kalshi's tape is keyless but it is a ROLLING ~8-week window (verified 2026-10-12:
# data exists for 2026-08-15, nothing for 2026-07-25). Every hour not captured is
# history that can never be recovered, so this job is the artifact's only source.
# It writes data/kalshi-tape/{bars.jsonl,prints-<date>.jsonl.gz,coverage.jsonl,state.json}.
#
# WINDOW DISCIPLINE (do not "optimise" this without re-reading the script's header)
# -----------------------------------------------------------------------------
# POLICY (user-overridden 2026-10-12, "override both"): maximise coverage. Interval
# 15 min, window 14 min -> ~93% duty cycle, ~4-5 GB/day of transfer, ~1 min of slack
# per tick. A run takes roughly as long in WALL time as the span it captures (paging
# is slower than the tape), so the window must stay under the interval or the next
# tick's lock skips and holes grow — 14/15 is the practical ceiling for one process.
#
# Near-continuous coverage means consecutive windows can MEET at the minute boundary.
# That is safe ONLY because the capture script's dedupe guard refuses to write a
# (ticker, minute) bar twice (counted per run as `bars_deduped`); overlapping windows
# are therefore visible and harmless rather than silent duplicates. The nightly
# integrity check is still `rows == distinct (ticker,minute)` in data/kalshi-tape/bars.jsonl.
# NEVER quote a bar total without its coverage row.
#
# OBSERVABILITY CONTRACT (matches the other copybot watchdogs)
# -----------------------------------------------------------
# Silent when healthy; prints ONE line to stdout (which cron delivers, deliver=origin)
# only when a run failed, hit its page/byte cap, or did not complete its window.
set -uo pipefail

REPO=/Users/xsnyde2/polymarket-copybot
LOG="$REPO/logs/cron/copybot-kalshi-tape.log"
COVERAGE="$REPO/data/kalshi-tape/coverage.jsonl"
mkdir -p "$(dirname "$LOG")"

stamp=$(date "+%Y-%m-%dT%H:%M:%S%z")

# single-instance lock; a stale lock is broken after 10 minutes
LOCKDIR=/tmp/copybot-kalshi-tape.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  if [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +25 2>/dev/null)" ]; then
    rmdir "$LOCKDIR" 2>/dev/null || true
    mkdir "$LOCKDIR" 2>/dev/null || { echo "kalshi-tape: lock held — skipping tick ($stamp)"; exit 0; }
  else
    echo "kalshi-tape: previous run still active — skipping tick ($stamp)" >>"$LOG"
    exit 0
  fi
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

cd "$REPO" || exit 1
echo "=== run $stamp ===" >>"$LOG"

OUT=$(python3 scripts/kalshi-tape-capture.py --window-minutes 14 --max-pages 600 2>&1)
RC=$?
echo "$OUT" >>"$LOG"

if [ $RC -ne 0 ]; then
  echo "🔴 kalshi-tape FAILED (rc=$RC) at $stamp — tape history is being lost. Last lines: $(echo "$OUT" | tail -2 | tr '\n' ' ')"
  exit 0
fi

# read the coverage row this run just appended and honour the contract
python3 - "$COVERAGE" "$stamp" <<'PY'
import json, sys
path, stamp = sys.argv[1], sys.argv[2]
try:
    with open(path) as fh:
        rows = fh.readlines()
    cov = json.loads(rows[-1])
except Exception as exc:
    print("🟠 kalshi-tape: run at %s wrote no readable coverage row (%s)" % (stamp, exc))
    sys.exit(0)

bad = []
if cov.get("cap_hit"):
    bad.append("CAP HIT (%s) — window truncated" % cov.get("stop_reason"))
if cov.get("stop_reason") not in ("window_complete", "watermark_reached"):
    bad.append("stop=%s" % cov.get("stop_reason"))
hole = cov.get("hole_minutes_before_window")
if hole is not None and hole > 20:
    bad.append("hole %.1f min before this window" % hole)
if bad:
    print("🟠 kalshi-tape: coverage degraded at %s — %s (captured %.0fs, %d pages, %d prints)"
          % (stamp, "; ".join(bad), cov.get("window_captured_seconds") or 0, cov.get("pages") or 0, cov.get("prints_scanned") or 0))
PY
exit 0
