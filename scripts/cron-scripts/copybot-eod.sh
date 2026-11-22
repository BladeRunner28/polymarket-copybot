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
# 2026-11-14 self-audit: EVERY pre-report step is BOUNDED.
#
# On 2026-11-13 this chain was killed by the harness at its 3600 s ceiling inside one
# step, so `report:daily` — six lines down — never ran: DailyReport has NO row for
# 2026-11-13 (every prior day has one) and no Discord report went out. The offending
# step could not be identified after the fact because each step's output is piped
# through `tail -N`, which flushes only at EOF, and a killed step never reaches EOF.
# Bounding each step (scripts/run-bounded.py kills the whole process group, so no orphan
# holds the SQLite DB) makes a slow step cost its OWN output and nothing else.
BOUNDED="python3 $PWD/scripts/run-bounded.py"

# NON-POSITIONAL CAPTURE (2026-11-22 self-audit, Lane B — instrument repair).
#
# A fixed `tail -N` on a step whose body GREW is a silent truncation of the review record, and it
# truncates the TOP, which is where the population, the clock and the lane label live. Measured
# against the live scripts on 2026-11-22 (not read off the code):
#   report:daily          prints 33 lines -> `tail -30` dropped lines 1-3, i.e. the title
#                         "CopyBot Comparative EOD Report — <date>", its
#                         "calendar day (closedAt ?? resolvedAt)" clock/basis line, and the
#                         "🤖 STANDARD Bot (Infinite Pool)" heading. The 2026-11-21 EOD log
#                         contains 0 occurrences of either string, so the first PnL line in the
#                         record belonged to no named lane and carried no clock.
#   analyze-calibration   prints 43 lines -> `tail -30` kept lines 14-43 (log's first row is
#                         "04:00 ET"): lost the header "Calibration analysis (BANKROLL_200,
#                         all-time, N=2862)", the WHOLE price-band block (ALL + 5 bands, incl.
#                         the longshot band +$5,128.30) and the "Returns by hour" label — the
#                         hour rows survived with no header saying what they were.
# The two `tail -20`->`tail -30` repairs documented below hit the same wall twice already; the N
# was never the fix, the positional cut was. Print the body whole. Only a runaway (>RUN_SHOW_MAX
# lines) is cut, and then it prints HEAD + TAIL with the real line count so the truncation is
# visible in the log instead of inferred from a missing header.
RUN_SHOW_MAX=400
show_run() {   # show_run <label> <file>
  local label=$1 f=$2 n
  n=$(wc -l < "$f" 2>/dev/null | tr -d ' '); n=${n:-0}
  if [ "$n" -le "$RUN_SHOW_MAX" ]; then
    cat "$f"
  else
    head -20 "$f"
    echo "[EOD] $label: body is $n lines, over the $RUN_SHOW_MAX-line log cap — HEAD 20 + TAIL $((RUN_SHOW_MAX - 20)) shown here; the run's full output was NOT written to this log."
    tail -n $((RUN_SHOW_MAX - 20)) "$f"
  fi
  return 0
}

$BOUNDED --timeout 300 --label "scan:leaderboard" -- npm run --silent scan:leaderboard 2>&1 | tail -1 \
  || echo "[EOD] scan:leaderboard BOUNDED OUT or failed — continuing so the report still runs"
# v41 (tuning review #12, approved): ML-1 review/export output must be visible
# in the EOD log — tail -5 keeps the counts (previously tail -1 hid them).
$BOUNDED --timeout 900 --label "review:outcomes" -- npm run --silent review:outcomes 2>&1 | tail -5 \
  || echo "[EOD] review:outcomes BOUNDED OUT or failed — labels deferred to the next run"
# tuning review #54 rec 2 (approved 2026-10-13): the export block grew past `tail -5`, so the
# EXPORT ROW COUNT and the PER-ERA lines were being cut from the capture (last seen 10-10).
# Select those lines by PATTERN rather than by position, so growth cannot push them out again.
# Log-only: no report, PnL figure, rule or gate reads this block; `|| true` keeps `set -o pipefail`
# from failing the whole EOD when a pattern is absent (grep exits 1 on no match).
$BOUNDED --timeout 300 --label "export:training" -- npm run --silent export:training 2>&1 \
  | grep -E "Exported [0-9]+ rows|: n=[0-9]+ y_net_entry=|^(  (label arms|market features|columns|target distribution|sums):)|pnl_(gross|net_entry|net_full):|reconciliation:|reproduce:" || true
$BOUNDED --timeout 300 --label "update:rules" -- npm run --silent update:rules 2>&1 | tail -2 \
  || echo "[EOD] update:rules BOUNDED OUT or failed — the rules pass is deferred, the report is NOT"
# polycopy-edge-cost-pair (2026-09-23): the report body grew 23 → 28 lines when
# the edge/copy-cost block landed, so `tail -20` would have dropped the report
# HEADER and the whole STANDARD block from the log (the report itself is
# unaffected — Discord and DailyReport.summary carry all of it). tail -30 keeps
# the block visible to the reviewer.
# 2026-11-22: the body is now 33 lines and `tail -30` was cutting the title, the
# calendar-day/clock line and the STANDARD lane heading. Captured whole via show_run()
# (see the NON-POSITIONAL CAPTURE note above); the exit code still fails the EOD, but only
# after the body is in the log.
RPT_TMP=$(mktemp "${TMPDIR:-/tmp}/copybot-eod-report.XXXXXX")
if npm run --silent report:daily >"$RPT_TMP" 2>&1; then RPT_RC=0; else RPT_RC=$?; fi
show_run "report:daily" "$RPT_TMP"
rm -f "$RPT_TMP"
[ "$RPT_RC" -eq 0 ] || { echo "[EOD] report:daily FAILED (rc=$RPT_RC) — body above, EOD marked failed"; exit "$RPT_RC"; }
# Calibration significance (excess return + z per price band / hour) — feeds
# the dashboard Performance page + the 18:00 Discord report next day.
# 2026-11-22: 43 lines vs `tail -30` — whole price-band block was being cut (see above).
CAL_TMP=$(mktemp "${TMPDIR:-/tmp}/copybot-eod-calibration.XXXXXX")
if python3 scripts/analyze-calibration.py >"$CAL_TMP" 2>&1; then CAL_RC=0; else CAL_RC=$?; fi
show_run "analyze-calibration" "$CAL_TMP"
rm -f "$CAL_TMP"
[ "$CAL_RC" -eq 0 ] || { echo "[EOD] analyze-calibration FAILED (rc=$CAL_RC) — body above"; exit "$CAL_RC"; }
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
