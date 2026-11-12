#!/bin/bash
# standard fill chain — give the STANDARD fill booth a WRITER.
#
# WHY THIS EXISTS: scripts/standard-fill-stamp.ts measures what entry was actually attainable for
# each STANDARD leg, but nothing scheduled ever ran it. data/standard-fill-stamp.jsonl held exactly
# ONE snapshot (2026-10-29T17:14Z) for 14 days, while 130 STANDARD legs opened since 10-29 and 0 of
# them carried a stamp — the evidence existed in the retained L2 corpus (data/l2/, alive), only the
# run was missing. It is the c6222f7 lesson one layer down: an artifact with no writer is a card
# that lies. The C-200 lane already has this chain (copybot-c200-fill-chain.sh, every 2h).
#
# What it does, every 2h, offline (no tape fetches, no network at all):
#   1. npx tsx scripts/standard-fill-stamp.ts --book-only --since-ms <last run> \
#        --out data/standard-fill-stamp-<UTC day>.jsonl
#   2. fold that snapshot into the union artifact data/standard-fill-stamp.jsonl
#      (scripts/standard-fill-stamp-merge.py — union of legs, newer wins, atomic write)
#   3. print ONE line, and only when it matters (watchdog pattern, see report() below).
#
# WRITES: data/standard-fill-stamp*.jsonl and logs/standard-fill-chain-state.json — nothing else.
# No DB write, no schema change, no bookedPnl change, no fillStatus/fillEntryPrice stamp: that is
# the Lane A half (drafts/standard-fill-aware-booking-20261112.md) and it waits for the operator.
# The 12 GB dev.db is read only through `sqlite3 -readonly`, which the booth already does.
#
# STANDARD_FILL_REPORT_ONLY=<booth stdout> STANDARD_FILL_MERGE_ONLY=<merge stdout> run ONLY the
# report step against that text and exit (test hook, mirrors FILL_CHAIN_REPORT_ONLY in
# copybot-c200-fill-chain.sh); both unset in cron.

set -uo pipefail
cd "$HOME/polymarket-copybot" 2>/dev/null || { echo "standard fill chain: repo directory missing"; exit 1; }
export DATABASE_URL="${DATABASE_URL:-file:./dev.db}"

STATE="logs/standard-fill-chain-state.json"
UNION="data/standard-fill-stamp.jsonl"
# First run starts at the census start of the never-stamped population (2026-10-29T00:00:00Z);
# every later run starts from its own previous start.
DEFAULT_SINCE_MS=1793232000000
# Set by report() for the state write, because the pending count is report()'s business.
REPORT_PENDING=0
REPORT_SPOKE=0

# Turn (booth stdout, merge machine line) into either silence or one line.
report() {
  local out="$1" mline="$2" arm_line in_scope stamped pending pct fresh now last lastn
  local added added_stamped upgraded union_n
  # The booth's "book arm: N/M legs stamped" line is the ONLY thing that tells this shim what
  # happened. If it is absent, the interface drifted — do NOT default it to 0 and report a healthy
  # no-op forever. Say so instead.
  arm_line=$(printf '%s' "$out" | grep -E 'book arm: [0-9]+/[0-9]+ legs stamped' | head -1)
  if [ -z "$arm_line" ]; then
    echo "standard fill chain: booth exited 0 but printed NO 'book arm: N/M legs stamped' line — this shim cannot tell what it did this tick (interface drift, not a clean no-op). Output tail:"
    printf '%s\n' "$out" | tail -6
    return 1
  fi
  stamped=$(printf '%s' "$arm_line" | grep -oE 'arm: [0-9]+/' | head -1 | grep -oE '[0-9]+')
  in_scope=$(printf '%s' "$arm_line" | grep -oE '/[0-9]+ legs' | head -1 | grep -oE '[0-9]+')
  stamped=${stamped:-0}; in_scope=${in_scope:-0}
  pending=$(( in_scope - stamped )); [ "$pending" -lt 0 ] && pending=0
  REPORT_PENDING=$pending
  pct=$(printf '%s' "$arm_line" | grep -oE '\([0-9]+%\)' | head -1)

  # The merge line carries what THIS tick ADDED to the union. The booth's own count is not that:
  # every tick re-scans an overlap window, so re-stamping already-known legs would read as news.
  if [ -z "$mline" ]; then
    echo "standard fill chain: the merge step produced no 'MERGE ...' line — the union's provenance for this tick is unknown (interface drift)."
    return 1
  fi
  added=$(printf '%s' "$mline" | grep -oE 'added=[0-9]+' | head -1); added=${added#added=}; added=${added:-0}
  added_stamped=$(printf '%s' "$mline" | grep -oE 'addedStamped=[0-9]+' | head -1)
  added_stamped=${added_stamped#addedStamped=}; added_stamped=${added_stamped:-0}
  upgraded=$(printf '%s' "$mline" | grep -oE 'upgraded=[0-9]+' | head -1); upgraded=${upgraded#upgraded=}; upgraded=${upgraded:-0}
  union_n=$(printf '%s' "$mline" | grep -oE 'union=[0-9]+' | head -1); union_n=${union_n#union=}; union_n=${union_n:-0}
  fresh=$(( added_stamped + upgraded ))

  if [ "$fresh" -gt 0 ]; then
    REPORT_SPOKE=1
    echo "standard fill-aware: stamped $fresh new STANDARD leg(s) ($added new leg(s) in this snapshot, $stamped/$in_scope in scope this tick ${pct:-}) — union now $union_n legs"
    return 0
  fi
  if [ "$pending" -le 0 ]; then
    return 0                      # genuine no-op: no new leg, nothing pending, nothing to say
  fi

  # 0 fresh WITH a non-empty pending set is not a no-op: every leg in this tick's scope resolved to
  # 'no L2 evidence', which is the coverage decay this chain exists to catch. Speaking every tick
  # would be a nag over a couple of permanently unmeasurable legs, so: speak on any CHANGE in the
  # pending count, else at most weekly.
  now=$(date +%s)
  last=$(sed -n 's/.*"at": *\([0-9][0-9]*\).*/\1/p' "$STATE" 2>/dev/null | head -1); last=${last:-0}
  lastn=$(sed -n 's/.*"pending": *\([0-9][0-9]*\).*/\1/p' "$STATE" 2>/dev/null | head -1); lastn=${lastn:--1}
  if [ "$pending" -ne "$lastn" ] || [ $((now - last)) -ge 604800 ]; then
    REPORT_SPOKE=1
    echo "standard fill-aware: ran clean but stamped 0 of $pending in-scope leg(s) — no L2 evidence for them, so they stay unstamped and the union carries no reading for them. ${pct:-coverage n/a}. Re-reported only when this count changes, or weekly."
  fi
  return 0
}

if [ -n "${STANDARD_FILL_REPORT_ONLY:-}" ]; then
  report "$STANDARD_FILL_REPORT_ONLY" "${STANDARD_FILL_MERGE_ONLY:-}"
  exit $?
fi

RUN_START_MS=$(( $(date +%s) * 1000 ))
# Overlap 2 min behind the previous run's start so a leg opened while that run was scanning is not
# lost. Re-scanning is harmless: the merge counts NEW ids, and a re-stamp only upgrades evidence.
SINCE_MS=$DEFAULT_SINCE_MS
if [ -f "$STATE" ]; then
  prev=$(sed -n 's/.*"nextSinceMs": *\([0-9][0-9]*\).*/\1/p' "$STATE" | head -1)
  if [ -n "$prev" ] && [ "$prev" -gt "$SINCE_MS" ]; then
    SINCE_MS=$(( prev - 120000 ))
  fi
fi
[ "$SINCE_MS" -ge "$RUN_START_MS" ] && SINCE_MS=$(( RUN_START_MS - 120000 ))

DAY=$(date -u +%Y%m%d)
OUT_PATH="data/standard-fill-stamp-$DAY.jsonl"
mkdir -p data logs

# Preserve the pre-merge union snapshot under its own date the first time this chain runs, so the
# 2026-10-29 record (taken on the PRE-repair price basis) survives as an immutable file instead of
# being folded away. Writes only data/standard-fill-stamp*.jsonl.
if [ -f "$UNION" ]; then
  ran=$(grep -oE '"ranAt": *"[^"]+"' "$UNION" | head -1 | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}')
  if [ -n "$ran" ]; then
    keeper="data/standard-fill-stamp-${ran//-/}.jsonl"
    [ -f "$keeper" ] || cp "$UNION" "$keeper"
  fi
fi

LINES_BEFORE=$(wc -l < "$OUT_PATH" 2>/dev/null | tr -d ' '); LINES_BEFORE=${LINES_BEFORE:-0}

# Stage 1 — stamps. Offline: --book-only reads the retained L2 corpus only, no tape fetches.
BOOTH_OUT=$(/usr/bin/env npx tsx scripts/standard-fill-stamp.ts --book-only --since-ms "$SINCE_MS" --out "$OUT_PATH" 2>&1)
RC=$?
LINES_AFTER=$(wc -l < "$OUT_PATH" 2>/dev/null | tr -d ' '); LINES_AFTER=${LINES_AFTER:-0}
if [ $RC -ne 0 ]; then
  echo "standard fill chain: fill booth FAILED (rc=$RC) — no snapshot written, union unchanged this tick"
  printf '%s\n' "$BOOTH_OUT" | tail -8
  exit 1
fi
if [ "$LINES_AFTER" -le "$LINES_BEFORE" ]; then
  echo "standard fill chain: booth exited 0 but appended NO snapshot to $OUT_PATH — the union was not advanced this tick (interface drift, not a clean no-op). Output tail:"
  printf '%s\n' "$BOOTH_OUT" | tail -6
  exit 1
fi

# Stage 2 — union. Atomic in-place merge (tmp + rename); newer evidence wins per leg id.
MERGE_OUT=$(/usr/bin/env python3 scripts/standard-fill-stamp-merge.py "$UNION" "$OUT_PATH" "$UNION" 2>&1)
MRC=$?
MLINE=$(printf '%s' "$MERGE_OUT" | grep -oE 'MERGE old=.*' | head -1)
if [ $MRC -ne 0 ] || [ -z "$MLINE" ]; then
  echo "standard fill chain: union merge FAILED (rc=$MRC) — this tick's snapshot exists in $OUT_PATH but $UNION was not advanced"
  printf '%s\n' "$MERGE_OUT" | tail -8
  exit 1
fi

# Stage 3 — say what happened (or stay quiet).
report "$BOOTH_OUT" "$MLINE"
RRC=$?

# State for the next tick: advance only on a tick whose evidence made it into the union.
if [ $RRC -eq 0 ]; then
  union_n=$(printf '%s' "$MLINE" | grep -oE 'union=[0-9]+' | head -1); union_n=${union_n#union=}; union_n=${union_n:-0}
  printf '{"at": %s, "nextSinceMs": %s, "ranAt": "%s", "pending": %s, "unionLegs": %s}\n' \
    "$(date +%s)" "$RUN_START_MS" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$REPORT_PENDING" "$union_n" > "$STATE"
fi
exit $RRC
