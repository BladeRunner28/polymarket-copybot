#!/bin/bash
# CopyBot: rebuild the Kalshi shadow ledger + shadow-score journal, then print a
# compact status (used as cron context for the Kalshi shadow report).
#
# 2026-09-13 (user-approved): observability only. Never touches live rules,
# positions, routing, or sizing — the shadow ledger is a counterfactual
# attribution of the C-200 book plus an expectancy-score journal.
set -euo pipefail

REPO=/Users/xsnyde2/polymarket-copybot
LOG="$REPO/logs/cron/copybot-kalshi-shadow.log"
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

echo "=== run $(date "+%Y-%m-%dT%H:%M:%S") ==="

LOCKDIR=/tmp/copybot-kalshi-shadow.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  if [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +20 2>/dev/null)" ]; then
    echo "breaking stale lock (>20 min)"
    rmdir "$LOCKDIR" 2>/dev/null || true
    mkdir "$LOCKDIR" 2>/dev/null || { echo "lock re-acquired — skipping"; exit 0; }
  else
    echo "previous run still active — skipping (lockfile-skip)"
    exit 0
  fi
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

cd "$REPO"

# 1) refit the shadow expectancy score weekly-ish (cheap, keeps the artifact
#    current as labels accrue); failure is non-fatal for the ledger rebuild.
if [ ! -f data/shadow-score-model.json ] || [ -n "$(find data/shadow-score-model.json -mmin +10080 2>/dev/null)" ]; then
  echo "-- refitting shadow-score model"
  python3 scripts/shadow-expectancy-model.py --fit 2>/dev/null | tail -2 || echo "!! refit failed — reusing existing artifact"
fi

# 2) rebuild the ledger + summary (idempotent)
python3 scripts/kalshi-shadow.py --quiet

# 2b) archive the OOS verdict BEFORE any future refit resets the clock
#     (2026-10-23, observability only: appends one line to
#      data/kalshi-shadow-oos-history.jsonl when the OOS read changes; never fatal)
python3 scripts/snapshot-kalshi-shadow-oos.py || echo "!! oos snapshot failed (non-fatal)"

# 3) compact status for the report prompt
python3 - <<'PY'
import json, time
s = json.load(open("data/kalshi-shadow-summary.json"))
live, ss = s["live"], s["shadowScoreSplit"]
print("--- KALSHI SHADOW STATUS (%s) ---" % s["asOf"])
# 2026-11-06 (self-audit, Lane B): this line used to read "live C-200 (all Polymarket)" while
# `live` is the whole BANKROLL_200 book INCLUDING the 93 historical Kalshi legs (re-priced onto
# the PM reference 2026-09-05 and deliberately re-joined to the C-200 series, card
# kalshi-reprice-92). Measured on the live book: the mixed figure is n=2,660/+$8,240.47/34.4%
# vs Polymarket-only n=2,568/+$8,288.10/35.9% -- so the label understated PM ROI by 1.5pp and
# PM PnL by $47.63. Both readings are now printed; nothing about the numbers changed.
print("live C-200 (BANKROLL_200 book, BOTH venues — not Polymarket-only): n=%d pnl=$%.2f roi=%.1f%% win[EXIT]=%.0f%%"
      % (live["n"], live["pnl"], live["roi_pct"], live["win_rate_pct"]))
for v in sorted(s.get("liveByVenue") or {}):
    x = s["liveByVenue"][v]
    print("  by venue %-10s n=%4d settled=%4d pnl=$%9.2f roi=%6.1f%% win[EXIT]=%2.0f%%"
          % (v, x["n"], x["n_settled"], x["pnl"], x["roi_pct"], x["win_rate_pct"]))
# CLOCK: `liveSinceSep5` is anchored on OPENINGS (openedAt>=Sep 5), so its PnL is "these legs,
# as far as they have settled" -- not "PnL booked since Sep 5". The settled-clock twin prints
# beside it because the two are not the same number and do not have to agree in sign.
o5 = s["liveSinceSep5"]
f5 = s.get("liveSinceSep5Settled") or {}
print("since Sep 5, OPENED cohort: n=%d pnl=$%.2f | since Sep 5, SETTLED cohort: n=%d pnl=$%.2f"
      % (o5["n"], o5["pnl"], f5.get("n", 0), f5.get("pnl", 0.0)))
print("shadow-score split (IN-SAMPLE, model fitted %s, n_train=%d, purged OOS rank IC=%+.3f):"
      % (s["model"]["fittedAt"][:16], s["model"]["nTrain"], s["model"]["oosRankIcPurged"]))
print("  selected: n=%d pnl=$%.2f roi=%.1f%% win[EXIT]=%.0f%%   rejected: n=%d pnl=$%.2f roi=%.1f%%"
      % (ss["selected"]["n"], ss["selected"]["pnl"], ss["selected"]["roi_pct"], ss["selected"]["win_rate_pct"],
         ss["rejected"]["n"], ss["rejected"]["pnl"], ss["rejected"]["roi_pct"]))
o = ss["oosSinceFit"]; r = ss["oosRejected"]
print("  OOS clock (trades opened after fit): selected n=%d pnl=$%.2f | rejected n=%d pnl=$%.2f"
      % (o["n"], o["pnl"], r["n"], r["pnl"]))
# 2026-09-20 (user-approved, rec 2): the raw OOS line is ONE ROW away from inverting
# — the rejected arm's whole positive side is a single +$1,076.47 row. Print the same
# window with its biggest winner removed, always beside the raw number, so the Oct 8
# retire call cannot be made on a single row's tail.
oe, re_ = o.get("exTop1"), r.get("exTop1")
if oe and re_:
    print("  OOS clock exTop1 (biggest winner removed): selected n=%d pnl=$%.2f roi=%+.1f%% (dropped %s +$%.2f) | rejected n=%d pnl=$%.2f roi=%+.1f%% (dropped %s +$%.2f)"
          % (oe["n_settled"], oe["pnl"], oe["roi_pct"], oe["droppedTradeId"] or "-", oe["droppedPnl"],
             re_["n_settled"], re_["pnl"], re_["roi_pct"], re_["droppedTradeId"] or "-", re_["droppedPnl"]))
    print("    retop1 spread: selected %+.1f%% vs rejected %+.1f%% = %+.1fpp (raw spread %+.1fpp)"
          % (oe["roi_pct"], re_["roi_pct"], re_["roi_pct"] - oe["roi_pct"], r["roi_pct"] - o["roi_pct"]))
print("candidate venue rules (attribution of the C-200 book — BOTH venues, not PM-only):")
for k, v in s["variants"].items():
    sel = v["selected"]
    print("  %-18s n=%4d share=%5.1f%% pnl=$%+8.2f roi=%+7.1f%% win[EXIT]=%3.0f%%"
          % (k, sel["n"], v["share_of_book_pct"], sel["pnl"], sel["roi_pct"], sel["win_rate_pct"]))
print("series days=%d last=%s live_cum=$%.2f shadow_cum=$%.2f pm_only_cum=$%.2f"
      % (len(s["series"]["dates"]), s["series"]["dates"][-1] if s["series"]["dates"] else "-",
         s["series"]["liveCum"][-1] if s["series"]["liveCum"] else 0.0,
         s["series"]["kalshiShadowCum"][-1] if s["series"]["kalshiShadowCum"] else 0.0,
         s["series"]["pmOnlyCum"][-1] if s["series"]["pmOnlyCum"] else 0.0))
print("open C-200 copies not yet settled: %d" % live["n_open"])
PY

# Lane B repair 2026-10-25: this script rebuilds the shadow ledger, but the /ml Kalshi
# CARD comes from data/ml/kalshi-lane.json, which was written ONLY by a manual run of
# scripts/kalshi-lane-status.py. Nothing on cron regenerated it, so builtAt froze at
# 2026-10-22 10:58 while the tape/macro/pm-pair capture crons kept writing right up to
# the minute — a card describing a lane three days behind the lane. Regenerate at most
# hourly (this script runs every 15m) so the card cannot drift from what it describes.
CARD="$REPO/data/ml/kalshi-lane.json"
if [ ! -e "$CARD" ] || [ -n "$(find "$CARD" -maxdepth 0 -mmin +60 2>/dev/null)" ]; then
  if ( cd "$REPO" && python3 scripts/kalshi-lane-status.py >/dev/null 2>&1 ); then
    echo "kalshi-lane.json refreshed (was stale >60m)"
  else
    echo "WARN: kalshi-lane.json refresh FAILED — /ml Kalshi card is now stale"
  fi
else
  echo "kalshi-lane.json fresh (<60m) — not regenerated"
fi

echo "=== done $(date "+%H:%M:%S") ==="
