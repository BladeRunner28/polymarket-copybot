#!/bin/bash
# CopyBot: forward venue-shadow book — the same C-200 copies booked at Polymarket's
# entry and at KALSHI's own top-of-book (same size, each venue's own taker fee), then
# print a compact status (used as cron context for the venue-shadow report).
#
# 2026-09-13 (user-approved): observability only. Never touches live rules, positions,
# routing, or sizing. This book cannot be backfilled (Kalshi order books are not
# archived), so it only accrues while this job runs — target read: the post-Oct-8
# Kelly-window decision (drafts/kalshi-venue-shadow-20260913.md).
#
# Requires the Rust sidecar's read-only POST /quote on :3014 (added 2026-09-13).
set -euo pipefail

REPO=/Users/xsnyde2/polymarket-copybot
LOG="$REPO/logs/cron/copybot-kalshi-venue-shadow.log"
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

echo "=== run $(date "+%Y-%m-%dT%H:%M:%S") ==="

LOCKDIR=/tmp/copybot-kalshi-venue-shadow.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  if [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +20 2>/dev/null)" ]; then
    echo "breaking stale lock (>20 min)"
    rmdir "$LOCKDIR" 2>/dev/null || true
    mkdir "$LOCKDIR" 2>/dev/null || { echo "lock re-acquired — skipping"; exit 0; }
  else
    echo "previous run still active — skipping (lockfile-skip)"
    exit 0
  fi
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

cd "$REPO"

# Fail loud if the sidecar route is missing: without it every row would be recorded
# as sidecar_route_missing and the book would silently collect nothing.
if ! curl -s -m 10 -o /dev/null -w "" -X POST http://127.0.0.1:3014/quote \
      -H 'content-type: application/json' -d '{"market_id":"x","market_question":"","side":"BUY"}' ; then
  echo "!! sidecar /quote unreachable — venue shadow cannot quote this tick"
fi

npx tsx scripts/kalshi-venue-shadow.ts

python3 - <<'PY'
import datetime, json, os
p = "data/kalshi-venue-shadow-summary.json"
if not os.path.exists(p):
    print("no venue-shadow summary yet")
    raise SystemExit(0)
s = json.load(open(p))
c, b = s["coverage"], s["books"]
print("--- VENUE SHADOW STATUS (%s) ---" % s["asOf"][:19])
print("window start: %s | collecting %d copies, %d in window"
      % (s["windowStart"][:10], c["copiesSeen"], c["inWindow"]))
print("coverage: verified=%d (%.0f%% cross-listed) | no-match=%d | unverified=%d | stale-skips=%d"
      % (c["withKalshiQuote"], 100 * c["crossListRate"], c["quoteFailures"],
         c.get("unverifiedMatches", 0), c["staleSkips"]))
if c.get("rejectionReasons"):
    print("  quoting buckets: %s" % json.dumps(c["rejectionReasons"]))
print("books (settled pairs only): PM $%+.2f (n=%d) | Kalshi $%+.2f (n=%d) | delta $%+.2f (%+.2f/trade)"
      % (b["pm"]["pnl"], b["pm"]["n"], b["kalshi"]["pnl"], b["kalshi"]["n"],
         b["delta"]["pnl"], b["delta"]["perTrade"]))
days = (datetime.date(2026, 10, 8) - datetime.date.today()).days
print("days to Kelly window close (Oct 8): %d" % days)
if c["withKalshiQuote"] == 0:
    print("NOTE: zero verified cross-listings so far — the binding constraint is matcher coverage, "
          "not the delta.")
PY

echo "=== done $(date "+%H:%M:%S") ==="
