#!/bin/bash
# copybot-rust-sidecar-launcher — append-only logging wrapper for the Rust
# execution sidecar (audit 2026-08-29).
#
# Why: launchd TRUNCATES StandardOutPath on every job (re)start, so each
# restart during the Aug 17-28 crash-loop destroyed the previous instance's
# stdout — the only diagnostic trail. This wrapper tees stdout+stderr to a
# dated archive with start/EXIT markers and an exit code, so the next death
# leaves definitive evidence. The live log still shows only the current
# instance (matches previous behavior for tailing).
set -o pipefail

LOG_DIR=/Users/xsnyde2/polymarket-copybot/logs
mkdir -p "$LOG_DIR"
LIVE="$LOG_DIR/rust-sidecar.log"
ARCHIVE="$LOG_DIR/rust-sidecar-$(date +%Y%m%d).log"
BIN=/Users/xsnyde2/polymarket-copybot/rust-sidecar/target/debug/polyhydra-whale-signal
PROJECT=/Users/xsnyde2/polymarket-copybot

# v45 fix (2026-09-03): the binary reads INTERNAL_API_SECRET (and POLYGON_WS_URL)
# from its environment; launchd provides none. Without sourcing .env here, every
# execution-result POST to :3013 401'd silently (fail-closed, unlogged) — C-200
# ran shadow-only from Aug 31 00:04 (launchd restart) to Sep 3: 846 intents
# parked inside the spread, 0 DB fills. Pre-Aug-31 runs worked only because the
# watchdog's nohup fallback (which sources .env) had launched the process.
cd "$PROJECT"
set -a; source .env 2>/dev/null; set +a

echo "=== sidecar start $(date '+%Y-%m-%d %H:%M:%S') (launcher pid $$) ===" >> "$ARCHIVE"
"$BIN" 2>&1 | tee -a "$ARCHIVE" > "$LIVE"
CODE=$?
echo "=== sidecar EXITED code=$CODE at $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$ARCHIVE"
exit "$CODE"
