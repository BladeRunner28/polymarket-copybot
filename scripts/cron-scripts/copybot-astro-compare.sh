#!/bin/bash
# Monthly astro shadow comparison (Phase Astro-1). Joins accumulated astro rows
# against PaperTrade realized PnL and prints the verdict digest for Discord.
cd /Users/xsnyde2/polymarket-copybot || exit 1
python3 scripts/compare-astro.py 2>&1
