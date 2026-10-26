#!/bin/bash
# CopyBot end-of-day: refresh leaderboard, judge outcomes, evolve rules, report.
set -euo pipefail
LOG=/Users/xsnyde2/polymarket-copybot/logs/cron/copybot-eod.log
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "=== run $(date "+%Y-%m-%dT%H:%M:%S") ==="
cd /Users/xsnyde2/polymarket-copybot
unset DATABASE_URL
set -a; source .env; set +a
npm run --silent scan:leaderboard 2>&1 | tail -1
# v41 (tuning review #12, approved): ML-1 review/export output must be visible
# in the EOD log — tail -5 keeps the counts (previously tail -1 hid them).
npm run --silent review:outcomes 2>&1 | tail -5
# tuning review #54 rec 2 (approved 2026-10-13): the export block grew past `tail -5`, so the
# EXPORT ROW COUNT and the PER-ERA lines were being cut from the capture (last seen 10-10).
# Select those lines by PATTERN rather than by position, so growth cannot push them out again.
# Log-only: no report, PnL figure, rule or gate reads this block; `|| true` keeps `set -o pipefail`
# from failing the whole EOD when a pattern is absent (grep exits 1 on no match).
npm run --silent export:training 2>&1 | grep -E "Exported [0-9]+ rows|: n=[0-9]+ y_net_entry=|^(  (label arms|market features|columns|target distribution|sums):)|pnl_(gross|net_entry|net_full):|reconciliation:|reproduce:" || true
npm run --silent update:rules 2>&1 | tail -2
# polycopy-edge-cost-pair (2026-09-23): the report body grew 23 → 28 lines when
# the edge/copy-cost block landed, so `tail -20` would have dropped the report
# HEADER and the whole STANDARD block from the log (the report itself is
# unaffected — Discord and DailyReport.summary carry all of it). tail -30 keeps
# the block visible to the reviewer.
npm run --silent report:daily 2>&1 | tail -30
# Calibration significance (excess return + z per price band / hour) — feeds
# the dashboard Performance page + the 18:00 Discord report next day.
python3 scripts/analyze-calibration.py 2>&1 | tail -30
# Insider/anomaly wallet scoring (v40, Homerun audit) — stores scores, alerts
# Discord when a tracked wallet trips the flagged/watch thresholds.
npx tsx scripts/score-insiders.ts 2>&1 | tail -15

# tuning review #33 rec 2 (user-approved 2026-09-22): READ-ONLY C-200 realized-PnL
# split across the wallet's CURRENT status. One greppable line per EOD run so the
# "tracked wallets lose / demoted wallets win" claim can be re-checked against a
# same-day SQL re-run instead of being re-derived from a fresh ad-hoc query each
# cycle. Measurement only — it gates nothing, so a failure here is a warning, not
# an EOD failure.
npx tsx scripts/wallet-status-split.ts 2>&1 | tail -2 || echo "WARN: wallet-status-split failed (measurement only, EOD unaffected)"

# polycopy-edge-cost-pair (2026-09-23): the daily report now carries the EDGE /
# COPY-COST pair (src/lib/copy-cost.ts → src/lib/report.ts). This READ-ONLY
# script re-prints the same pair plus the ALL-LEGS variant that reconciles with
# the card's 2026-09-23 baseline (C-200 -3.03% on 1,982 legs, STANDARD +0.84% on
# 9,863) — the reviewer's re-runnable form. Measurement only; a failure is a
# warning, not an EOD failure. The script prints 8 lines (one-liner, window,
# report block, ALL-LEGS reconciliation, reproduce) — tail -10 keeps all of them,
# including the greppable first line.
npx tsx scripts/edge-copy-cost.ts 2>&1 | tail -10 || echo "WARN: edge-copy-cost failed (measurement only, EOD unaffected)"

# tuning review #38 rec 2 (user-approved 2026-09-28; carried from #36 R1 for a 3rd
# cycle): READ-ONLY concentration of the C-200 OPEN book by EVENT FAMILY. Why: the
# book is four single-leg $100 positions, one per family, and v55 (per-market) and
# v59 (per-wallet) both read 0 — the exposure is correlated ACROSS markets, which is
# the shape that produced the -$300 realisation #37 documented. The line prints the
# top-3 families with their share of open cost, the pre-registered family rule and
# the reproduce command, the top family's wallet split and the open-book wallet
# concentration (tuning #48 rec 1, approved 2026-10-07: a family can be eight city bets or
# ONE wallet's weather book); tail -8 keeps all six lines. Measurement only (no rule,
# size or cap reads it), so a failure is a warning, not an EOD failure.
npx tsx scripts/event-family-concentration.ts 2>&1 | tail -8 || echo "WARN: event-family-concentration failed (measurement only, EOD unaffected)"
