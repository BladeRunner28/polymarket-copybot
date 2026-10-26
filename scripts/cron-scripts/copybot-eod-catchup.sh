#!/bin/bash
# CopyBot EOD chain WITHOUT the auto-tuner — the catch-up / held-rule variant of
# copybot-eod.sh.
#
# WHY THIS EXISTS (2026-10-14): the 10-13 22:00 EOD crashed mid-chain (load-time
# ReferenceError in src/lib/fill-intent.ts, card outage-20261013-fill-intent-tdz),
# so the leaderboard refresh, outcome review, training export, daily report,
# calibration pass, insider scoring and the three measurement lines never ran.
# Re-running copybot-eod.sh to recover them would ALSO run `update:rules`, which
# applies evidence-based RuleSet changes automatically (`runRuleUpdate`, changedBy
# "hermes") — and its 48h governance lockout (v44, after the last user-approved
# v62 change at 2026-10-12 11:20) had just expired at 2026-10-14 11:20, so it was
# free to fire on a day the user had marked VOID (16h of frozen booking). Auto
# rule application is a live-lane change and needs its own approval: this script
# runs everything EXCEPT that step, and says so in the log.
#
# Use it for: catching up a missed EOD, or any night the auto-tuner must be held.
# Use copybot-eod.sh for normal nights (it includes update:rules).
#
# Idempotent enough to re-run: scan/leaderboard is an upsert, review:outcomes
# re-judges settled rows, report:daily upserts by DATE (so tonight's 22:00 run
# overwrites whatever this writes), and every measurement stage here is read-only.
set -uo pipefail
LOG=/Users/xsnyde2/polymarket-copybot/logs/cron/copybot-eod-catchup.log
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "=== EOD CATCH-UP run $(date "+%Y-%m-%dT%H:%M:%S") — chain minus update:rules ==="
cd /Users/xsnyde2/polymarket-copybot
unset DATABASE_URL
set -a; source .env; set +a

step() { echo; echo "--- $1 ---"; }

step "scan:leaderboard"
npm run --silent scan:leaderboard 2>&1 | tail -1

step "review:outcomes (judge settled outcomes)"
npm run --silent review:outcomes 2>&1 | tail -5

step "export:training (ML-1 capture)"
npm run --silent export:training 2>&1 | grep -E "Exported [0-9]+ rows|: n=[0-9]+ y_net_entry=|^(  (label arms|market features|columns|target distribution|sums):)|pnl_(gross|net_entry|net_full):|reconciliation:|reproduce:" || true

step "update:rules — HELD"
echo "SKIPPED (not failed): auto rule application is a live-lane change and this chain ran on a"
echo "day marked VOID (16h booking outage). Run copybot-eod.sh tonight, or ask for it explicitly."
echo "No read-only preview exists: runRuleUpdate() calls collectSamples()/applyRuleChanges() together"
echo "and neither is exposed for a proposal-only probe, so the alternative is running it or not."

step "report:daily"
npm run --silent report:daily 2>&1 | tail -30

step "analyze-calibration.py (band z / excess return)"
python3 scripts/analyze-calibration.py 2>&1 | tail -30

step "score-insiders.ts"
npx tsx scripts/score-insiders.ts 2>&1 | tail -15

step "wallet-status-split.ts (measurement only)"
npx tsx scripts/wallet-status-split.ts 2>&1 | tail -2 || echo "WARN: wallet-status-split failed (measurement only, EOD unaffected)"

step "edge-copy-cost.ts (measurement only)"
npx tsx scripts/edge-copy-cost.ts 2>&1 | tail -10 || echo "WARN: edge-copy-cost failed (measurement only, EOD unaffected)"

step "event-family-concentration.ts (measurement only)"
npx tsx scripts/event-family-concentration.ts 2>&1 | tail -8 || echo "WARN: event-family-concentration failed (measurement only, EOD unaffected)"

echo
echo "=== EOD CATCH-UP complete $(date "+%Y-%m-%dT%H:%M:%S") ==="
