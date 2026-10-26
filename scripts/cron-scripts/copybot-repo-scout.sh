#!/bin/bash
# Weekly prediction-market repo scout (triage layer). Runs the Python scout
# and prints its digest — delivered to Discord by the no-agent cron job.
# The digest is always informative (even "nothing new"), so always print.
set -euo pipefail
cd /Users/xsnyde2/polymarket-copybot
python3 scripts/scan-github-repos.py
