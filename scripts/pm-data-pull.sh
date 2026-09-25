#!/bin/bash
# pm-data-pull.sh — resumable, rate-limit-tolerant pull of the external prediction-market
# datasets onto /Volumes/Storage/pm-data (the external NX-512 NVMe; NOT the internal volume).
#
# Why a retry loop: the Hub rate-limits anonymous clients (observed HTTP 429 on the xet
# read-token endpoint and a ~0.8-0.9 MB/s admission while unauthenticated). Every attempt
# resumes from what is on disk, so re-running is free. Authenticate (`hf auth login`) to
# lift the limit; the script uses whatever token the CLI has.
#
# Usage:  bash scripts/pm-data-pull.sh [repo_id ...]      (default = both datasets)
# Verify: /Volumes/Storage/pm-data/.venv/bin/python  + manifest.json per dataset
set -uo pipefail
export PATH=/Users/xsnyde2/.hermes/hermes-agent/venv/bin:$PATH
ROOT=/Volumes/Storage/pm-data
LOG="$ROOT/download.log"
mkdir -p "$ROOT"; cd "$ROOT" || exit 1
echo "=== pm-data-pull $(date '+%F %T') user=$(whoami) token=$([ -f "$HOME/.cache/huggingface/token" ] && echo present || echo none) ===" >>"$LOG"

pull() {
  repo="$1"; dir="$2"
  for i in $(seq 1 20); do
    echo "--- attempt $i $repo $(date '+%T')" >>"$LOG"
    if hf download "$repo" --repo-type dataset --local-dir "$dir" --max-workers 4 >>"$LOG" 2>&1; then
      echo "DONE $repo ($(du -sh "$dir" | cut -f1))" >>"$LOG"; return 0
    fi
    sleep 45
  done
  echo "GAVE UP $repo after 20 attempts" >>"$LOG"; return 1
}

if [ $# -gt 0 ]; then
  for repo in "$@"; do pull "$repo" "$(basename "$repo")"; done
else
  pull smf-ulm/polymarket-quant-bench quant-bench
  pull TimeSeventeen/Polymarket-v1 polymarket-v1
fi
echo "=== finished $(date '+%F %T') ===" >>"$LOG"
du -sh "$ROOT"/* >>"$LOG"; df -h /Volumes/Storage | tail -1 >>"$LOG"
