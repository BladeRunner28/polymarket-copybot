#!/bin/bash
# Weekly cross-platform gaps digest (Phase Data-1) → Discord.
cd /Users/xsnyde2/polymarket-copybot || exit 1
python3 scripts/gaps-digest.py 2>&1
