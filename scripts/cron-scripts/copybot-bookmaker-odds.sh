#!/bin/bash
# copybot-bookmaker-odds.sh — forward recorder for REC 2 (bookmaker consensus pre-match odds).
#
# CHANGE-GATED, NOT POLLED-FOR-FAILURE: while there is no ODDSRELAY_TOKEN in ~/.hermes/.env this exits 0
# and prints nothing, so it never nags. The moment the token (and endpoint) land it starts recording on
# its own, which is why this can be scheduled before the operator has signed up.
#
# When the token IS present it runs --mode api in the foreground and passes through whatever it says.
# That script deliberately refuses to invent an endpoint: a wrong URL returns an empty board that parses
# identically to "no events listed", so it stops and asks for the real one instead of recording silence.
set -uo pipefail

REPO="/Users/xsnyde2/polymarket-copybot"
ENVF="$HOME/.hermes/.env"

if ! grep -q '^ODDSRELAY_TOKEN=' "$ENVF" 2>/dev/null; then
  exit 0            # not configured yet — heartbeat, not an alarm
fi

cd "$REPO" || { echo "BOOKMAKER ODDS RECORDER FAILED: repo missing at $REPO"; exit 2; }

OUT=$(python3 scripts/bookmaker-odds-record.py --mode api 2>&1)
RC=$?

if [ $RC -ne 0 ]; then
  echo "BOOKMAKER ODDS RECORDER FAILED (exit $RC):"
  echo "$OUT"
  exit $RC
fi

echo "$OUT"
