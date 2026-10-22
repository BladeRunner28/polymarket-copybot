#!/usr/bin/env bash
# ML lane daily chain — labels → sentiment features → export → fit → gate read.
#
# ORDER MATTERS: sentiment features are derived from the signal corpus as-of each
# decision, so they must run BEFORE the export reads them; the export must run before
# the fit; the fit before the gate read.
#
# SAFETY: this chain MEASURES. It never writes a RuleSet, never touches the live lane,
# never promotes a candidate. Promotion is a Discord approval to the operator, always.
# A step failing does not stop later steps (a broken fit must not hide a broken export),
# and every step's exit code lands in the ledger.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
LEDGER="data/ml-ledger.jsonl"
mkdir -p data
: > /tmp/ml-chain.$$.log

step() { # name, command...
  local name="$1"; shift
  local t0 t1 rc
  t0=$(date +%s)
  printf '\n=== %s ===\n' "$name" >> /tmp/ml-chain.$$.log
  "$@" >> /tmp/ml-chain.$$.log 2>&1
  rc=$?
  t1=$(date +%s)
  STEP_NAMES+=("$name"); STEP_RC+=("$rc"); STEP_SECS+=("$((t1 - t0))")
  printf '  [%s] %s (%ss)\n' "$([ $rc -eq 0 ] && echo OK || echo "FAIL rc=$rc")" "$name" "$((t1 - t0))" >> /tmp/ml-chain.$$.log
}

STEP_NAMES=(); STEP_RC=(); STEP_SECS=()

# One-decimal percentage. Integer division reported 140/4994 as "2%" against a true
# 2.8% — the difference between "rounding noise" and "the feature is dead", so it
# must not be truncated.
pct1() { awk -v a="$1" -v b="$2" 'BEGIN { if (b > 0) printf "%.1f", a * 100 / b; else printf "0.0" }'; }

step "backfill-labels"   npx tsx scripts/backfill-copy-labels.ts
step "sentiment-features" npx tsx scripts/export-sentiment-features.ts
step "export-training"   npx tsx scripts/export-training-data.ts
step "ml1-fit"           npx tsx scripts/ml1-fit-candidate.ts
step "ml1-gate"          npx tsx scripts/ml1-gate-read.ts

# The /ml page reads data/ml/dashboard.json. Nothing refreshed it on a schedule before this, so
# it sat two days stale while this job still reported ok -- the page kept showing 10-20 numbers as
# if current. It only reads committed artefacts, so it runs LAST, after the export above has
# rewritten them, and its failure must not be silent: the step rc lands in the ledger like any other.
# market-candidates.parquet had NO scheduled producer either, so the page's band economics were
# 41h old while this job reported ok. Measured 2026-10-22: 239.6s, 120,884 candidates -> 99,561
# gated. It must run BEFORE dashboard-artifacts, which reads the parquet it writes.
step "market-candidates" .venv-ml/bin/python scripts/ml-market-candidates.py
step "dashboard-artifacts" .venv-ml/bin/python scripts/ml-dashboard-artifacts.py

# ---- facts for the ledger + report (never inferred, always read back from artifacts) ----
export_rows=0; term_pct=0; sent_rows=0; gate_line="none"; fit_line="none"
if [ -f training_data.csv ]; then
  read -r export_rows term_rows sent_rows <<<"$(python3 - <<'PY'
import csv
try:
    rows=list(csv.DictReader(open("training_data.csv")))
except Exception:
    print("0 0 0"); raise SystemExit
n=len(rows)
t=sum(1 for r in rows if r.get("terminal_at"))
s=sum(1 for r in rows if r.get("sentiment_delta_signed"))
print(n,t,s)
PY
)"
  [ "$export_rows" -gt 0 ] && term_pct=$((100 * term_rows / export_rows))
fi
if [ -f data/ml1-gate-read.json ]; then
  gate_line="$(python3 -c "import json;d=json.load(open('data/ml1-gate-read.json'));print({k:d[k] for k in list(d)[:6]})" 2>/dev/null | cut -c1-400)"
fi
if [ -f data/ml1-fit-candidate.json ]; then
  fit_line="$(python3 -c "import json;d=json.load(open('data/ml1-fit-candidate.json'));print({k:d[k] for k in list(d)[:6]})" 2>/dev/null | cut -c1-400)"
fi
fails=0; for rc in "${STEP_RC[@]}"; do [ "$rc" -ne 0 ] && fails=$((fails + 1)); done

python3 - "$STAMP" "$fails" "$export_rows" "$term_pct" "$sent_rows" "$LEDGER" "$gate_line" "$fit_line" <<'PY'
import json, sys
stamp, fails, rows, term_pct, sent, ledger, gate, fit = sys.argv[1:9]
rec = {"at": stamp, "steps_failed": int(fails), "export_rows": int(rows),
       "terminal_pct": int(term_pct), "sentiment_rows": int(sent),
       "gate": gate, "fit": fit}
with open(ledger, "a") as f:
    f.write(json.dumps(rec) + "\n")
PY

# ---- report ----
printf '\nML CHAIN %s\n' "$STAMP"
for i in "${!STEP_NAMES[@]}"; do
  printf '  %-18s %s (%ss)\n' "${STEP_NAMES[$i]}" "$([ "${STEP_RC[$i]}" -eq 0 ] && echo OK || echo "FAILED rc=${STEP_RC[$i]}")" "${STEP_SECS[$i]}"
done
printf '  export rows          %s (terminal_at %s%%)\n' "$export_rows" "$term_pct"
printf '  sentiment features   %s rows (%s%%)\n' "$sent_rows" "$(pct1 "$sent_rows" "$export_rows")"
printf '  gate                 %s\n' "$gate_line"
printf '  fit                  %s\n' "$fit_line"
printf '  ledger               %s\n' "$LEDGER"
if [ "$fails" -ne 0 ]; then
  printf '\n--- failing step output (tail) ---\n'
  grep -A 12 -E '^\s*\[FAIL' /tmp/ml-chain.$$.log | tail -40
fi
rm -f /tmp/ml-chain.$$.log
exit 0
