#!/bin/bash
# Odds API sportsbook-vs-Polymarket gap detector (Phase Data-1, shadow).
# Logs |implied - PM| >= 10pp for MLB to data/odds-gaps.jsonl. Local delivery.
cd /Users/xsnyde2/polymarket-copybot || exit 1
python3 scripts/odds-gaps.py 2>&1 | tail -20
