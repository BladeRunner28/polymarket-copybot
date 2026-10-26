#!/bin/bash
# Daily astro shadow logger (Phase Astro-1). Appends today's D-tier astro row to
# data/astro-shadow.jsonl (idempotent per day). Silent when nothing new.
cd /Users/xsnyde2/political-research-bot || exit 1
OUT=$(venv/bin/python src/astro_shadow.py 2>&1)
if echo "$OUT" | grep -q "already exists"; then
  exit 0
fi
echo "$OUT" | grep -vE "\.bsp"
