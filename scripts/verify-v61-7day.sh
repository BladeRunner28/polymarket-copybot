#!/bin/bash
# verify-v61-7day — the v61 (per-market notional ceiling 0.10 -> 0.20, live 2026-10-10 02:26 CDT)
# verification that tuning review #51 rec 1 pre-registered for its 7-day mark: TWO null checks,
# because the hypothesis on the record is that v61 is INERT BY CONSTRUCTION and the live constraint
# is a different rail (the "legs <= 2" clause, card permarket-legs-rail-finding).
#
#   (a) 0 `per-market cap (notional ...)` vetoes AFTER the first `with rules v61` monitor header;
#   (b) whether a Kelly admit ever books a 2nd leg in the same market.
#
# Both null => v61 changed nothing reachable and the open question is the legs rail, not the
# ceiling. Either non-null => v61 IS binding and the ceiling is doing work: report the numbers, do
# not re-tune on this run.
#
# Deterministic, read-only (logs + dev.db reads only). Writes nothing.
cd /Users/xsnyde2/polymarket-copybot || exit 1
export DATABASE_URL="file:./dev.db"
LOG=logs/cron/copybot-monitor-score.log

echo "=== verify-v61 — 7-day mark ($(date '+%Y-%m-%d %H:%M %Z')) ==="
echo "v61 live since: $(sqlite3 "file:$PWD/prisma/dev.db?mode=ro" "SELECT datetime(createdAt/1000,'unixepoch','-5 hours') FROM RuleSet WHERE version=61;")"
echo "active RuleSet: $(sqlite3 "file:$PWD/prisma/dev.db?mode=ro" "SELECT version FROM RuleSet WHERE active=1 ORDER BY version DESC LIMIT 1;")"

# ---- (a) log checks: vetoes since the first v61 header -------------------------------------------
V61=$(grep -n "with rules v61" "$LOG" 2>/dev/null | head -1 | cut -d: -f1)
if [ -z "$V61" ]; then
  echo "(a) NOTIONAL-CAP VETOES: UNKNOWN — no 'with rules v61' header in $LOG"
else
  NOTIONAL=$(awk -v v="$V61" 'NR>v && /per-market cap \(notional/' "$LOG" 2>/dev/null | wc -l | tr -d ' ')
  LEGS=$(awk -v v="$V61" 'NR>v && /per-market cap \(legs/' "$LOG" 2>/dev/null | wc -l | tr -d ' ')
  echo "(a) NOTIONAL-CAP VETOES after the v61 header (log line $V61): $NOTIONAL  [expected 0]"
  echo "    (context) LEGS-clause vetoes after the v61 header: $LEGS"
fi
echo "    lifetime notional-cap vetoes in the whole log: $(grep -c 'per-market cap (notional' "$LOG" 2>/dev/null) (all at the old \$125.12 ceiling)"

# ---- durable-store checks ------------------------------------------------------------------------
echo ""
echo "(b) POST-v61 LANE LEGS (BANKROLL_200, ruleSetVersion >= 61, non-demo):"
sqlite3 -header "file:$PWD/prisma/dev.db?mode=ro" "
  SELECT COUNT(*) AS booked_legs,
         COUNT(DISTINCT pt.marketId) AS markets,
         SUM(CASE WHEN pt.simulatedPositionSize > 20 THEN 1 ELSE 0 END) AS kelly_sized_legs
  FROM PaperTrade pt JOIN DecisionJournal dj ON dj.id = pt.decisionJournalId
  WHERE pt.botId='BANKROLL_200' AND pt.isDemo=0 AND dj.ruleSetVersion>=61;"
echo "    markets with >= 2 legs booked post-v61 (the check that matters):"
sqlite3 "file:$PWD/prisma/dev.db?mode=ro" "
  SELECT COALESCE(GROUP_CONCAT(marketId || ' (' || c || ')'), '  none — no market has booked a 2nd leg')
  FROM (SELECT pt.marketId, COUNT(*) c FROM PaperTrade pt
        JOIN DecisionJournal dj ON dj.id = pt.decisionJournalId
        WHERE pt.botId='BANKROLL_200' AND pt.isDemo=0 AND dj.ruleSetVersion>=61
        GROUP BY 1 HAVING c >= 2);"
echo "    decision rows at ruleSetVersion >= 61 that mention the per-market cap at all:"
sqlite3 "file:$PWD/prisma/dev.db?mode=ro" "SELECT COUNT(*) FROM DecisionJournal WHERE ruleSetVersion>=61 AND risksJson LIKE '%per-market cap%';"
echo "    decisions post-v61: $(sqlite3 "file:$PWD/prisma/dev.db?mode=ro" "SELECT COALESCE(GROUP_CONCAT(decision || '=' || c, ' '), 'none') FROM (SELECT decision, COUNT(*) c FROM DecisionJournal WHERE ruleSetVersion>=61 GROUP BY 1);")"

# ---- verdict -------------------------------------------------------------------------------------
ADMITS=$(sqlite3 "file:$PWD/prisma/dev.db?mode=ro" "SELECT COUNT(*) FROM PaperTrade pt JOIN DecisionJournal dj ON dj.id=pt.decisionJournalId WHERE dj.ruleSetVersion>=61 AND pt.simulatedPositionSize>20;")
SECOND=$(sqlite3 "file:$PWD/prisma/dev.db?mode=ro" "SELECT COUNT(*) FROM (SELECT pt.marketId FROM PaperTrade pt JOIN DecisionJournal dj ON dj.id=pt.decisionJournalId WHERE pt.botId='BANKROLL_200' AND pt.isDemo=0 AND dj.ruleSetVersion>=61 GROUP BY pt.marketId HAVING COUNT(*)>=2);")
echo ""
echo "VERDICT:"
echo "  Kelly admits post-v61 (size > \$20): $ADMITS | markets with a 2nd leg: $SECOND"
if [ "$ADMITS" = "0" ]; then
  echo "  v61 INERT BY CONSTRUCTION **and untested**: no Kelly admit has occurred post-v61 at all, so"
  echo "  the 2-leg allowance the ceiling was raised for has never been exercised. The open question is"
  echo "  why admits are absent (kelly no-edge / the legs <= 2 rail — card permarket-legs-rail-finding),"
  echo "  NOT the notional ceiling. Do not re-tune v61 on this run."
elif [ "$SECOND" = "0" ]; then
  echo "  v61 is BINDING: Kelly admits exist but no market books a 2nd leg — inspect the cap and the"
  echo "  legs-clause counts above before proposing anything."
else
  echo "  v61 is ACTIVE: a 2nd leg has booked, so the ceiling no longer blocks the 2-leg allowance."
fi
echo "=== end verify-v61 ==="
