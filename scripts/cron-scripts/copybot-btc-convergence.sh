#!/bin/bash
# btx2 deterministic-convergence COVERAGE sampler (card btx2, approved in-thread 2026-10-13).
# Pre-registration: ~/polymarket-copybot/drafts/btc-convergence-prereg-20261013.md (gate FROZEN before
# the first sample). Read-only, keyless, no orders. Silent on success by design: the sampler's stdout
# is an observability channel, not a log, and the READ job reports freshness/staleness.
set -uo pipefail
cd "$HOME/polymarket-copybot" || exit 0
python3 scripts/btc-convergence-sampler.py --assets all --hours-back 1 2>&1 | tail -3
exit 0
