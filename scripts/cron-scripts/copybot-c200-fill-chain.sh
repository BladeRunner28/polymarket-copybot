#!/bin/bash
# c200 fill-aware booking chain — refresh the print-through evidence, then stamp verdicts.
#
# WHY THIS EXISTS: the resolver (scripts/c200-fill-resolve.ts) can only stamp a leg when the
# print-through artifact holds evidence for its intent. The artifact had no scheduled writer
# (mtime 2026-10-26, two days stale), so on its own the flip would decay to a no-op within days:
# every new leg would stay fillStatus NULL and keep booking at p(fill)=1, which is exactly the
# fiction the flip exists to remove. An artifact with no writer is a card that lies.
#
# Run by cron with no_agent=true: stdout is the notification. Silent on a healthy no-op tick
# (watchdog pattern); speaks when it stamped something, when a stage failed, when the resolver
# ran but printed no result line, or when it stamped 0 of a non-empty pending set (see below).
#
# FILL_CHAIN_REPORT_ONLY=<resolver stdout> runs ONLY the report step against that text and exits.
# It is a test hook (scripts/test-c200-fill-chain-report.sh) so the shipped parsing runs against
# real resolver output; unset in cron, so production always executes the stages below.

set -uo pipefail
cd "$HOME/polymarket-copybot" 2>/dev/null || { echo "c200 fill chain: repo directory missing"; exit 1; }
export DATABASE_URL="${DATABASE_URL:-file:./dev.db}"
STATE="logs/c200-fill-chain-state.json"

# Turn the resolver's stdout into either silence or one line. $1 = resolver stdout.
report() {
  local out="$1" done_line n pending cov now last
  # The resolver's result line is the ONLY thing that tells this shim what happened. If it is absent
  # the interface drifted, and the old code's `N=${N:-0}` turned that into a silent healthy no-op
  # forever. Say so instead.
  done_line=$(printf '%s' "$out" | grep -oE 'DONE\. [0-9,]+ legs stamped' | head -1)
  if [ -z "$done_line" ]; then
    echo "c200 fill chain: resolver exited 0 but printed NO 'DONE. N legs stamped' line — this shim cannot tell what it did this tick (interface drift, not a clean no-op). Output tail:"
    printf '%s\n' "$out" | tail -6
    return 1
  fi
  n=$(printf '%s' "$done_line" | grep -oE '[0-9,]+' | head -1 | tr -d ',')
  n=${n:-0}

  # Pending = legs with no stamp yet, with the coverage denominator the resolver printed for them.
  pending=$(printf '%s' "$out" | awk '/^ *unresolved /{gsub(",","",$2); print $2; exit}')
  pending=${pending:-0}
  cov=$(printf '%s' "$out" | grep -oE 'resolution coverage (n/a|[0-9.]+% of [0-9,]+)' | head -1)
  cov=${cov:-resolution coverage not printed}

  if [ "$n" -gt 0 ]; then
    echo "c200 fill-aware: stamped $n new legs — $cov"
    return 0
  fi
  if [ "$pending" -le 0 ]; then
    return 0                      # genuine no-op: nothing pending, nothing to say
  fi

  # 0 stamped WITH a non-empty pending set is not a no-op: every pending leg resolved to
  # 'unresolved' (no evidence in either direction), which is the decay this chain exists to catch.
  # Speaking every tick would be a nag over one permanently unmeasurable leg (the backlog is
  # re-attempted each run), so: speak on any CHANGE in the pending count, else at most weekly.
  now=$(date +%s)
  last=$(sed -n 's/.*"at": *\([0-9][0-9]*\).*/\1/p' "$STATE" 2>/dev/null | head -1)
  last=${last:-0}
  lastn=$(sed -n 's/.*"pending": *\([0-9][0-9]*\).*/\1/p' "$STATE" 2>/dev/null | head -1)
  lastn=${lastn:--1}
  mkdir -p logs
  if [ "$pending" -ne "$lastn" ] || [ $((now - last)) -ge 604800 ]; then
    printf '{"at": %s, "pending": %s, "stamped": %s}\n' "$now" "$pending" "$n" > "$STATE"
    echo "c200 fill-aware: ran clean but stamped 0 of $pending pending leg(s) — ALL unresolved, so no leg got evidence this tick and those legs keep booking at p(fill)=1. $cov. Re-reported only when this count changes, or weekly."
  else
    printf '{"at": %s, "pending": %s, "stamped": %s}\n' "$last" "$pending" "$n" > "$STATE"
  fi
  return 0
}

if [ -n "${FILL_CHAIN_REPORT_ONLY:-}" ]; then
  report "$FILL_CHAIN_REPORT_ONLY"
  exit $?
fi

# Stage 1 — evidence. Network-dependent (data-api prints + our L2 corpus).
PT_OUT=$(/usr/bin/env python3 scripts/c200-printthrough.py 2>&1)
PT_RC=$?
if [ $PT_RC -ne 0 ]; then
  echo "c200 fill chain: print-through FAILED (rc=$PT_RC) — resolver NOT run, so no leg was stamped this tick"
  printf '%s\n' "$PT_OUT" | tail -8
  exit 1
fi

# Stage 2 — verdicts. --apply stamps only fillStatus IS NULL rows (idempotent).
OUT=$(/usr/bin/env npx tsx scripts/c200-fill-resolve.ts --apply 2>&1)
RC=$?
if [ $RC -ne 0 ]; then
  echo "c200 fill chain: resolver FAILED (rc=$RC) — booking unchanged"
  printf '%s\n' "$OUT" | tail -10
  exit 1
fi

report "$OUT"
exit $?
