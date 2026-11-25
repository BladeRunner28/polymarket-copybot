#!/bin/bash
# CopyBot: FORWARD capture of order-book depth at the 1c tail of Kalshi's KXBTCD daily
# BTC ladder (card t_0cb77acd). Sibling of copybot-kalshi-tape.sh, same discipline.
#
# WHY A SCHEDULE IS THE WHOLE POINT
# ---------------------------------
# Kalshi publishes NO historical order book (the v2 websocket refuses keyless clients:
# GET /trade-api/ws/v2 -> 401 token_authentication_failure), so the resting size at the 1c
# level that a maker order would queue behind exists only in the live book. Every second not
# captured is permanently lost — the same argument that makes copybot-kalshi-tape.sh run on a
# clock. The tape tells you WHAT traded at 1c; only this capture tells you WHAT WAS IN FRONT.
#
# WHAT ONE RUN PRODUCES
# ---------------------
# data/kalshi-1c-queue/{snaps-<date>.jsonl.gz, events-<date>.jsonl, markets-<date>.jsonl,
# coverage.jsonl, state.json}. Read it with scripts/kalshi-1c-queue-estimate.py, never by
# eyeballing a single run: one window is a sample, the rate only means something over days.
#
# WINDOW DISCIPLINE
# -----------------
# 14-minute window every 15 minutes (~93% duty) — the same setting as the tape capture, chosen
# there after measuring that a run's wall time tracks the span it captures. Polling is 2 reads
# per 1.5s cycle (~1.3 req/s, one markets list + one tape page), well inside Kalshi's read limit;
# a cycle cannot fall behind because to limit /markets/trades?limit=1000 covers ~5.5s of tape.
# Consecutive runs MEET at the boundary; the capture dedupes on trade_id, so overlap is harmless
# and visible in coverage.jsonl (prints_scanned_new counts only unseen trades).
#
# OBSERVABILITY CONTRACT (matches the other copybot watchdogs)
# -----------------------------------------------------------
# Silent when healthy; ONE line to stdout (cron delivers it) only when a run fails, a run
# captured far less than its window, or the previous run left a large hole. Never quote a fill
# probability from this artifact without the coverage row that produced it.
set -uo pipefail

REPO=/Users/xsnyde2/polymarket-copybot
OUTDIR="${CAPTURE_OUTDIR:-$REPO/data/kalshi-1c-queue}"
LOG="$REPO/logs/cron/copybot-kalshi-1c-queue.log"
COVERAGE="$OUTDIR/coverage.jsonl"
WORKTREE=/Users/xsnyde2/polymarket-copybot/.worktrees/t_0cb77acd
mkdir -p "$(dirname "$LOG")" "$OUTDIR"

# source of truth is the repo copy; the branch that adds it is unmerged until Lane A merges it,
# so fall back to the worktree that built it. Repoints itself on merge — no edit needed.
SCRIPT=""
for cand in "$REPO/scripts/kalshi-1c-queue-capture.py" "$WORKTREE/scripts/kalshi-1c-queue-capture.py"; do
  if [ -f "$cand" ]; then SCRIPT="$cand"; break; fi
done
if [ -z "$SCRIPT" ]; then
  echo "🔴 kalshi-1c-queue: capture script not found in $REPO/scripts or $WORKTREE/scripts — the 1c depth series is NOT being recorded"
  exit 0
fi

stamp=$(date "+%Y-%m-%dT%H:%M:%S%z")

# single-instance lock; a stale lock (crashed run) is broken after 20 minutes
LOCKDIR=/tmp/copybot-kalshi-1c-queue.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  if [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +20 2>/dev/null)" ]; then
    rmdir "$LOCKDIR" 2>/dev/null || true
    mkdir "$LOCKDIR" 2>/dev/null || { echo "kalshi-1c-queue: lock held — skipping tick ($stamp)"; exit 0; }
  else
    echo "kalshi-1c-queue: previous run still active — skipping tick ($stamp)" >>"$LOG"
    exit 0
  fi
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

cd "$REPO" || exit 1
echo "=== run $stamp (script=$SCRIPT) ===" >>"$LOG"

# CAPTURE_MINUTES exists so the wiring can be smoke-tested without a 14-minute wait;
# cron always runs the default. CAPTURE_INTERVAL likewise.
MINUTES=${CAPTURE_MINUTES:-14}
INTERVAL=${CAPTURE_INTERVAL:-1.5}

OUT=$(python3 "$SCRIPT" --minutes "$MINUTES" --interval "$INTERVAL" --outdir "$OUTDIR" 2>&1)
RC=$?
echo "$OUT" >>"$LOG"

if [ $RC -ne 0 ]; then
  echo "🔴 kalshi-1c-queue FAILED (rc=$RC) at $stamp — 1c book depth is being lost. Last lines: $(echo "$OUT" | tail -2 | tr '\n' ' ')"
  exit 0
fi

# honour the contract: read the coverage row this run just appended
python3 - "$COVERAGE" "$stamp" "$MINUTES" <<'PY'
import json, sys
path, stamp, minutes = sys.argv[1], sys.argv[2], float(sys.argv[3])
try:
    cov = json.loads(open(path).readlines()[-1])
except Exception as exc:
    print("🟠 kalshi-1c-queue: run at %s wrote no readable coverage row (%s)" % (stamp, exc))
    sys.exit(0)

window = minutes * 60.0
bad = []
if cov.get("stopped_early"):
    bad.append("stopped early")
if (cov.get("wall_seconds") or 0) < 0.75 * window:
    bad.append("only %.0fs of a %.0fs window" % (cov.get("wall_seconds") or 0, window))
if (cov.get("request_errors") or 0) > 10:
    bad.append("%d request errors" % cov["request_errors"])
if (cov.get("cycles") or 0) == 0:
    bad.append("no poll cycles")
if bad:
    print("🟠 kalshi-1c-queue: degraded at %s — %s (%.0fs, %s cycles, %s events, p90 snap age %sms)"
          % (stamp, "; ".join(bad), cov.get("wall_seconds") or 0, cov.get("cycles"),
             cov.get("events_kept"), cov.get("snap_age_ms_p90")))
PY
exit 0
