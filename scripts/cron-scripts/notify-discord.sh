#!/usr/bin/env bash
# notify-discord.sh "<message>" — post a plain-text alert to $DISCORD_WEBHOOK_URL and REPORT
# whether it actually landed.
#
# WHY THIS EXISTS (self-audit 2026-11-12): copybot-sidecar-watchdog.sh is the one cron job in
# the system whose alert does not travel through Hermes delivery — it runs with deliver=local,
# so its stdout goes nowhere, and the only path to Discord was a hand-rolled
#   curl -s -m 15 -H 'content-type: application/json' -d "$PAYLOAD" "$WEBHOOK" >/dev/null 2>&1
# Every failure mode of that line is invisible: HTTP 429 (Discord rate-limits webhooks), a
# deleted/rotated webhook (404), a malformed payload, and — the worst one — DISCORD_WEBHOOK_URL
# simply being unset, which skipped the post entirely inside `if [ -n ... ]`. In all four cases
# the watchdog still printed its message, exited 0 and recorded last_status=ok. The watchdog
# measured the sidecar and never measured its own alarm.
#
# Contract: exit 0 = Discord accepted the message (HTTP 2xx). Exit 1 = NOT delivered, with the
# reason AND the undelivered text on stdout. Callers must turn exit 1 into a non-zero exit of
# their own so the job's failure_deliver carries the text to the operator.
set -uo pipefail

MSG=${1:-}
URL=${DISCORD_WEBHOOK_URL:-}

if [ -z "$MSG" ]; then
  echo "notify-discord: no message argument — nothing attempted"
  exit 1
fi
if [ -z "$URL" ]; then
  echo "notify-discord: DISCORD_WEBHOOK_URL is UNSET — alert NOT delivered. Undelivered text:"
  echo "${MSG:0:1500}"
  exit 1
fi

# Discord caps webhook content at 2000 chars; truncate first so the JSON never 400s on length.
PAYLOAD=$(printf '%s' "${MSG:0:1990}" | jq -Rsc '{content: .}') || PAYLOAD=""
if [ -z "$PAYLOAD" ]; then
  echo "notify-discord: payload encoding failed (jq) — alert NOT delivered. Undelivered text:"
  echo "${MSG:0:1500}"
  exit 1
fi

post() {
  # -w prints the status even when the body is discarded; 000 = no response at all.
  curl -s -m 15 -o /dev/null -w '%{http_code}' \
    -H "content-type: application/json" -d "$PAYLOAD" "$URL" 2>/dev/null || echo "000"
}

code=$(post); code=${code:-000}
if [ "$code" != "200" ] && [ "$code" != "204" ]; then
  # One retry: 429 (rate limit) and 5xx are the realistic transient cases, and an alert about a
  # down trading sidecar is worth 3 more seconds.
  sleep 3
  code2=$(post); code2=${code2:-000}
  case "$code2" in
    200|204) code=$code2 ;;
    *) code="$code->$code2" ;;
  esac
fi

case "$code" in
  200|204) exit 0 ;;
  *)
    echo "notify-discord: webhook REJECTED the alert (HTTP $code; 404 = webhook deleted, 429 = rate-limited) — NOT delivered. Undelivered text:"
    echo "${MSG:0:1500}"
    exit 1
    ;;
esac
