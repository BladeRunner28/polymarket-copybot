#!/bin/bash
# btx2 deterministic-convergence WINDOW sampler (card btx2). This is the half of the instrument that
# can actually see a Q1 edge: the venue's post-determination trading window is ~11-12 MINUTES (measured
# on its own closedTime), which a 15-minute grid would systematically miss. Runs at minutes 1 and 7.
# Frozen pre-registration: drafts/btc-convergence-prereg-20261013.md §3.1.
set -uo pipefail
cd "$HOME/polymarket-copybot" || exit 0
python3 scripts/btc-convergence-sampler.py \
  --assets all \
  --families hourly_above,updown_1h,noon_close \
  --hours-back 1 \
  --max-minutes-since-determined 12 2>&1 | tail -3
exit 0
