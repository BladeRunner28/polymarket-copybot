#!/usr/bin/env bash
# copybot-asset-audit.sh — context for the asset-audit worker job.
#
# Prints, in order:
#   1. the queue status (backlog, and anything awaiting the user's approval)
#   2. the 2 leads this run should audit, already claimed (status -> auditing)
#   3. the deterministic anatomy of each claimed repo (asset-inspect.py: read-only, no clone,
#      no execution, no keys)
#
# The worker turns that into drafts/asset-audit-<slug>-<date>.md and records a recommendation
# against the queue item, which the DAILY and WEEKLY reports then put to the user for approval.
set -uo pipefail
cd /Users/xsnyde2/polymarket-copybot || exit 1

echo "## Seeding from the newest fact sheet's radar block"
python3 scripts/asset-queue.py seed -v || echo "**SOURCE FAILED — seed**"

echo
echo "## Queue status"
python3 scripts/asset-queue.py status || echo "**SOURCE FAILED — queue status**"

echo
echo "## Claims for this run"
CLAIMED=$(python3 scripts/asset-queue.py pending --limit "${AUDIT_LIMIT:-2}") || { echo "**SOURCE FAILED — pending**"; exit 0; }
echo "$CLAIMED"

echo
echo "## Deterministic anatomy (read-only; no cloning, no execution)"
echo "$CLAIMED" | python3 -c '
import json, subprocess, sys
ids = []
for line in sys.stdin:
    line = line.strip()
    if line.startswith("{"):
        try:
            ids.append(json.loads(line)["id"])
        except Exception:
            pass
if not ids:
    print("_(nothing claimed — no anatomy to fetch)_")
for rid in ids:
    print(f"\n### {rid}")
    p = subprocess.run(["python3", "scripts/asset-inspect.py", "--repo", rid],
                       capture_output=True, text=True, timeout=180)
    print(p.stdout.strip() or f"**SOURCE FAILED — anatomy for {rid}**: {p.stderr.strip()[:200]}")
'
