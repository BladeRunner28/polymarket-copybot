#!/bin/bash
# Feed the kanban board from data/roadmap.json, so the dispatcher has something to spawn.
#
# The scheduler's PATH is thinner than an interactive shell's, and the feeder shells out to `hermes`
# and `sqlite3`, so pin PATH here rather than discovering a missing-binary failure at 03:00.
export PATH="/Users/xsnyde2/.hermes/hermes-agent/venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd /Users/xsnyde2/polymarket-copybot || exit 1

# --quiet is REQUIRED here: this runs no_agent, so stdout is delivered to the user verbatim. Quiet
# means an empty stdout when nothing was promoted, which the scheduler treats as "nothing to say".
# --lane-a honours the standing instruction to feed Lane A once Lane B has drained; Lane A cards are
# created with a no-apply contract and must tag `awaiting-approval` on completion.
exec /usr/bin/python3 scripts/backlog-feeder.py \
  --quiet --lane-a --max-promote 3 --max-active 3
