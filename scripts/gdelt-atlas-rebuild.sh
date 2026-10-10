#!/bin/bash
# GDELT Atlas rebuild — regenerates atlas.html from the KEYLESS bulk route.
#
# CANONICAL COPY (git-backed daily 22:30). ~/.hermes/scripts/copybot-gdelt-atlas-rebuild.sh is a
# shim to this file so the logic survives on the internal disk alone.
#
# Re-pointed 2026-10-10 (user-approved): the GDELT Cloud source (fetch_stories.py) is dead from this
# host — the free plan answers 403 "API keys are not included in your current plan" — so the job had
# been "succeeding" while keeping its 2026-10-02 snapshot. The replacement source is the same keyless
# 15-minute event-export corpus the GDELT shadow lane already consumes
# (~/polymarket-copybot/data/gdelt-bulk/, written by political-research-bot/src/gdelt_bulk.py).
#
# Output is delivered verbatim to Discord (no_agent cron): one summary line set on success, loud on
# failure; a thin corpus keeps the previous snapshot and exits 0.
set -uo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

ATLAS=/Users/xsnyde2/gdelt-atlas
REPO=/Users/xsnyde2/polymarket-copybot
LOG=$REPO/logs/cron/copybot-gdelt-atlas.log
cd "$ATLAS" || exit 1
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "=== atlas rebuild $(date "+%Y-%m-%dT%H:%M:%S") ==="

# 1) fetch from the bulk corpus (exit 2 = too few stories -> keep the previous snapshot)
python3 fetch_bulk_stories.py --days 3 --out data/stories_latest.json
rc=$?
if [ $rc -eq 2 ]; then
  echo "Bulk corpus too thin — atlas.html unchanged (previous snapshot kept)."
  exit 0
elif [ $rc -ne 0 ]; then
  echo "fetch_bulk_stories.py failed (rc=$rc) — atlas.html unchanged."
  exit 1
fi

# 2) rebuild
python3 build.py --stories data/stories_latest.json --out atlas.html
if [ $? -ne 0 ]; then
  echo "build.py failed — atlas.html unchanged."
  exit 1
fi

# 3) publish to the dashboard static area (live at http://localhost:3013/atlas.html)
cp atlas.html "$REPO/public/atlas.html" && echo "published to dashboard /atlas.html"

# 4) verify + summarize for Discord
python3 << 'EOF'
import json, os, re
src = open('/Users/xsnyde2/gdelt-atlas/atlas.html').read()
m = re.search(r'const SNAPSHOT = (\{.*?\});', src, re.S)
snap = json.loads(m.group(1))
kb = os.path.getsize('/Users/xsnyde2/gdelt-atlas/atlas.html') // 1024
top = sorted([(c['name'], c['stats']['count']) for c in snap['countries'] if c.get('stats')],
             key=lambda x: -x[1])[:5]
top_s = ', '.join(f"{n} {c}" for n, c in top)
print(f"GDELT Atlas rebuilt: {len(snap['feed'])} feed / {snap['total_stories']} stories | {snap['covered']} countries | {kb} KB")
print(f"Top coverage: {top_s}")
print(f"Generated: {snap['generated'][:16]} UTC")
EOF

echo "=== atlas rebuild complete ==="
