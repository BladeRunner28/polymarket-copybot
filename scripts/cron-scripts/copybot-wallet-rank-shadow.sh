#!/bin/bash
# Wallet-rank SHADOW runner (card t_7c91b4a1 -> roadmap `crowdintel-wallet-fdr-audit`, Lane A APPROVED
# 2026-11-09 as SHADOW-ONLY: two ranking arms + a coverage gate, no selection/status/size/rule change).
#
# It widens settlement truth, re-scores the FROZEN arms against "keep the current track set", and
# appends one line to data/wallet-rank-shadow-history.jsonl. Silent on a normal day: empty stdout
# sends nothing. It pages only twice-ish: when a pre-registered arm leaves PENDING (the card's own
# decision rule fired -- the operator must then read the draft), or when the run itself fails.
set -uo pipefail
cd /Users/xsnyde2/polymarket-copybot || exit 3
LOG=/Users/xsnyde2/polymarket-copybot/logs/cron/copybot-wallet-rank-shadow.log
mkdir -p "$(dirname "$LOG")"
echo "=== run $(date "+%Y-%m-%dT%H:%M:%S") ===" >> "$LOG"

LOCKDIR=/tmp/copybot-wallet-rank-shadow.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  if [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +90 2>/dev/null)" ]; then
    echo "breaking stale lock (>90 min) and continuing" >> "$LOG"
    rmdir "$LOCKDIR" 2>/dev/null; mkdir "$LOCKDIR" 2>/dev/null || exit 0
  else
    echo "previous run still active -- skipping (lockfile-skip)" >> "$LOG"; exit 0
  fi
fi
trap 'rmdir "$LOCKDIR"' EXIT

SCRIPT=/Users/xsnyde2/polymarket-copybot/scripts/wallet-rank-shadow.py
AUDIT=/Users/xsnyde2/polymarket-copybot/scripts/wallet-fdr-audit.py
if [ ! -f "$SCRIPT" ] || [ ! -f "$AUDIT" ]; then
  # FAIL LOUD. This guard used to `exit 0` with a line in the log only, so the shadow sat dead for
  # three days (2026-11-09..11-11) while every run reported success and nothing reached Discord.
  # A missing instrument is an alert, not a quiet day.
  echo "wallet-rank-shadow: scripts absent from the primary checkout ($SCRIPT / $AUDIT) -- "
  echo "the shadow did NOT run; the forward window is not accruing. See $LOG"
  echo "wallet-rank-shadow: scripts absent -- exit 2" >> "$LOG"
  exit 2
fi

python3 "$SCRIPT" --fetch "${WALLET_RANK_FETCH:-1500}" >> "$LOG" 2>&1
rc=$?
echo "wallet-rank-shadow complete: exit $rc" >> "$LOG"
if [ "$rc" -ne 0 ]; then
  echo "wallet-rank-shadow FAILED (exit $rc) -- see logs/cron/copybot-wallet-rank-shadow.log"
  exit "$rc"
fi

# Alert once per distinct verdict state (a FAIL would otherwise repeat every morning).
python3 - <<'PY'
import json, os
OUT = "/Users/xsnyde2/polymarket-copybot/data/wallet-rank-shadow.json"
SIG = "/Users/xsnyde2/polymarket-copybot/data/wallet-rank-shadow-alert.json"
try:
    d = json.load(open(OUT))
except Exception as exc:
    print(f"wallet-rank shadow: read failed ({exc}) -- state file missing or unreadable")
    raise SystemExit(0)
dec = d.get("decision") or {}
sig = {k: v.get("verdict") for k, v in dec.items()}
prev = {}
if os.path.exists(SIG):
    try:
        prev = json.load(open(SIG)).get("verdicts") or {}
    except Exception:
        prev = {}
hot = {k: v for k, v in sig.items() if v and v != "PENDING" and prev.get(k) != v}
if hot:
    print(f"wallet-rank shadow -- a pre-registered arm left PENDING ({d.get('generated_at','')}):")
    for k, v in hot.items():
        rec = dec[k]
        print(f"  {k}: {v} -- {rec.get('why')}  (arm-minus-baseline CI {rec.get('diff_ci')})")
    print(f"  forward bets so far: {d.get('bets_forward')}  truth settled: {d.get('truth',{}).get('settled')}")
    print("  Lane A: read drafts/wallet-rank-shadow-20261109 before acting. Nothing ships without the operator.")
with open(SIG, "w") as f:
    json.dump({"at": d.get("generated_at"), "verdicts": sig}, f, indent=1)
PY
exit 0
