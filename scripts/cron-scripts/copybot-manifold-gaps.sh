#!/bin/bash
# Manifold cross-platform gap detector (Phase Data-1, shadow). Scans the most
# liquid active Polymarket markets, searches Manifold for matching questions,
# logs |probability gap| >= 10pp to data/manifold-gaps.jsonl. Local delivery.
cd /Users/xsnyde2/polymarket-copybot || exit 1
python3 scripts/manifold-gaps.py 2>&1 | tail -20
