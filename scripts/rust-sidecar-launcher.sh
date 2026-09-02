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

echo "=== sidecar start $(date '+%Y-%m-%d %H:%M:%S') (launcher pid $$) ===" >> "$ARCHIVE"
"$BIN" 2>&1 | tee -a "$ARCHIVE" > "$LIVE"
CODE=$?
echo "=== sidecar EXITED code=$CODE at $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$ARCHIVE"
exit "$CODE"
