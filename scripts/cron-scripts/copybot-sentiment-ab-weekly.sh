#!/bin/bash
# Weekly sentiment A/B comparison (Phase Local-1): rules vs local LLM (qwen2.5:7b).
# Runs the compare script and delivers its digest verbatim (no_agent cron job).
cd /Users/xsnyde2/polymarket-copybot || exit 1
python3 scripts/compare-sentiment.py 2>&1
