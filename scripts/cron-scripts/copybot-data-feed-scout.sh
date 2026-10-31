#!/bin/bash
# copybot-data-feed-scout.sh — weekly mechanical pass for the ML data-feed research agent.
#
# Runs scripts/data-feed-scout.py, which WRITES data/data-feed-scout.json and
# drafts/data-feed-scout-<date>.md, then prints a compact digest on stdout. The cron job injects that
# digest into the agent's prompt; the agent's job is the interpretation (recommendations + decision
# rules), which by policy it only proposes and never applies.
#
# Deterministic on purpose: same day, same candidate set -> same digest. The agent uses `continuity`
# to spot what is genuinely NEW rather than re-litigating last week.
set -uo pipefail

REPO="/Users/xsnyde2/polymarket-copybot"
PY="/usr/bin/env python3"

cd "$REPO" || { echo "DATA-FEED SCOUT FAILED: repo missing at $REPO"; exit 2; }

OUT=$(python3 scripts/data-feed-scout.py --top 12 2>&1)
RC=$?

# The scout records per-source health itself. Surface failures FIRST: a run where half the sources 429'd
# must not read as "we looked everywhere and found little".
echo "$OUT" | sed -n '/=== SOURCE HEALTH ===/,/^$/p'
echo
echo "$OUT" | grep -E "^=== CANDIDATES|^\s+\[(eligible|review)" | head -14
echo

if [ $RC -ne 0 ]; then
  echo "SCOUT EXIT $RC — artefact may be stale; treat this digest as unreliable."
fi

# Read the count the scout itself computed. `grep -c FAIL` also matched its own summary line and printed
# 3 when the real number was 2 -- a printed number whose basis lies is worse than no number.
FAILED=$(echo "$OUT" | sed -n 's/.*!! \([0-9][0-9]*\) source(s) FAILED.*/\1/p' | head -1)
echo "---"
echo "source failures this run: ${FAILED:-0}"
echo "artefact: data/data-feed-scout.json"
echo "candidate report: drafts/data-feed-scout-$(date +%F).md"
