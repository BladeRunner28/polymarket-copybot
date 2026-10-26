#!/bin/bash
# CopyBot: Kalshi x Polymarket BTC up/down PAIRED read — sampler (card kalshi-pm-btc-pair-prereg).
#
# WHAT THIS IS
# ------------
# A read-only measurement instrument for the ONLY cross-venue pair that aligns exactly:
# Kalshi `KXBTC15M` vs Polymarket `btc-updown-15m-*` (same 15-minute wall-clock window, same
# binary proposition). Every 15 minutes it samples BOTH venue books back-to-back for ~12 minutes
# and appends one row per sample to data/kalshi-pm-btc-pair.jsonl, so the paired cost distribution
# (not a point estimate) can be read later against the pre-registered gate in
# scripts/kalshi-pm-btc-pair-read.py. It never trades and touches no live path.
#
# WHY A SCHEDULE
# --------------
# The gate needs >=288 aligned windows (72h of 15-minute windows). Neither venue publishes a
# historical two-sided book, so the sample can only be accumulated FORWARD — a tick not sampled is
# a window that can never be priced.
#
# CADENCE AND DUTY CYCLE (quote this beside any window count)
# ---------------------------------------------------------
# Interval 15 min, span 700s (~11.7 min) at 20s resolution -> ~78% window duty, ~35 samples per
# window per tick. Unlike the tape capture, a sampling run costs seconds, not minutes, so the
# remaining slack is deliberate: the PM side is thin (touch sizes of 5-150 shares are normal here),
# and a slow tick would cost a whole window.
#
# OBSERVABILITY CONTRACT (matches the other copybot jobs)
# ------------------------------------------------------
# Silent when healthy; prints ONE line (cron delivers, deliver=origin) only when a run is degraded
# (a quarter or more of its samples failed). Coverage is written to
# data/kalshi-pm-pair-coverage.jsonl, one row per invocation (different prefix on purpose: the
# analyzer globs the sample series kalshi-pm-btc-pair-*.jsonl, which coverage must not join).
# Samples themselves rotate per UTC day (kalshi-pm-btc-pair-<date>.jsonl, ~7 MB/day) so no single
# tracked file can approach the nightly backup's 95 MB guard.
set -uo pipefail

REPO=/Users/xsnyde2/polymarket-copybot
LOG="$REPO/logs/cron/copybot-kalshi-pm-pair.log"
mkdir -p "$(dirname "$LOG")"

stamp=$(date "+%Y-%m-%dT%H:%M:%S%z")

# single-instance lock; a stale lock is broken after 20 minutes
LOCKDIR=/tmp/copybot-kalshi-pm-pair.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  if [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +20 2>/dev/null)" ]; then
    rmdir "$LOCKDIR" 2>/dev/null || true
    mkdir "$LOCKDIR" 2>/dev/null || { echo "kalshi-pm-pair: lock held — skipping tick ($stamp)"; exit 0; }
  else
    echo "kalshi-pm-pair: previous run still active — skipping tick ($stamp)" >>"$LOG"
    exit 0
  fi
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

cd "$REPO" || exit 1
echo "=== run $stamp ===" >>"$LOG"

OUT=$(python3 scripts/kalshi-pm-btc-pair-sampler.py --seconds 700 --interval 20 2>&1)
RC=$?
echo "$OUT" >>"$LOG"

if [ $RC -ne 0 ]; then
  echo "🔴 kalshi-pm-pair FAILED (rc=$RC) at $stamp — a window was not sampled. Last lines: $(echo "$OUT" | tail -2 | tr '\n' ' ')"
  exit 0
fi

# honour the contract: pass through only the sampler's degraded-run line, if any
if [ -n "$OUT" ]; then
  echo "$OUT" | grep -v '^$' || true
fi
exit 0
