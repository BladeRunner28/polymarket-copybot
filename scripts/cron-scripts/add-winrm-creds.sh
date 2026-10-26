#!/bin/bash
# add-winrm-creds.sh — interactively collect a WinRM username/password and install
# them into a Hermes .env file (default: ~/.hermes/.env).
#
# Run it yourself on the Mac. The password is read with echo off, never appears in
# shell history, in argv (so `ps` cannot see it), or in the terminal.
#
#   chmod +x ~/.hermes/scripts/add-winrm-creds.sh
#   ~/.hermes/scripts/add-winrm-creds.sh
#
# Username format matters. A Windows LOCAL account must carry the NetBIOS prefix —
# `ODIN\hermes` or `.\hermes`. A Microsoft/Entra account (anything email-shaped, e.g.
# hermes@example.com) CANNOT authenticate over WinRM at all, on either transport, no
# matter what is configured server-side. Basic auth is usually refused as well; the
# verifier tries NTLM first.
#
# Options:
#   --host HOST       WinRM host to record           (default 192.168.1.106)
#   --port PORT       WinRM port to record           (default 5985)
#   --env-file PATH   target .env                    (default ~/.hermes/.env)
#   --no-backup       skip the timestamped backup
#   --verify-winrm    after writing, try a real WinRM connection (needs pywinrm)
#   --help            show this help
#
# Exit codes: 0 ok | 1 bad usage | 2 refused/unrepresentable value | 3 verification failed

set -u
umask 077

ENV_FILE="${ENV_FILE:-$HOME/.hermes/.env}"
HOST="192.168.1.106"
PORT="5985"
USER_KEY="ODIN_WINRM_USER"
PASS_KEY="ODIN_WINRM_PASSWORD"
HOST_KEY="ODIN_WINRM_HOST"
PORT_KEY="ODIN_WINRM_PORT"
DO_BACKUP=1
VERIFY_WINRM=0

HERMES_PY="/Users/xsnyde2/.hermes/hermes-agent/venv/bin/python3"

while [ $# -gt 0 ]; do
  case "$1" in
    --host)         HOST="${2:?}"; shift 2 ;;
    --port)         PORT="${2:?}"; shift 2 ;;
    --env-file)     ENV_FILE="${2:?}"; shift 2 ;;
    --no-backup)    DO_BACKUP=0; shift ;;
    --verify-winrm) VERIFY_WINRM=1; shift ;;
    --help|-h)      sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 1 ;;
  esac
done

# ---------- helpers ----------

# Encode a value so BOTH python-dotenv and `source .env` read it back literally.
# Single quotes are literal in both. A value containing a single quote falls back to
# double quotes only when nothing else in it is special; otherwise we refuse rather
# than write something that silently mis-parses.
encode() {
  _v="$1"
  case "$_v" in
    *\'*)
      case "$_v" in
        *\"*|*\\*|*'$'*|*\`*) return 2 ;;
        *) printf '"%s"' "$_v"; return 0 ;;
      esac
      ;;
    *) printf "'%s'" "$_v"; return 0 ;;
  esac
}

# sha256 of a string, printed as bare hex — used to compare values without printing them.
sha_of() { printf '%s' "$1" | shasum -a 256 | awk '{print $1}'; }

abort() { echo "ERROR: $1" >&2; exit "${2:-2}"; }

[ -f "$ENV_FILE" ] || abort "no such env file: $ENV_FILE" 1
[ -r "$ENV_FILE" ] || abort "env file not readable: $ENV_FILE" 1
[ -w "$ENV_FILE" ] || abort "env file not writable: $ENV_FILE" 1

echo "Target: $ENV_FILE  ($(wc -l < "$ENV_FILE" | tr -d ' ') lines, mode $(stat -f '%Lp' "$ENV_FILE"))"
echo "Keys to write: $USER_KEY, $PASS_KEY, $HOST_KEY, $PORT_KEY"
echo

# ---------- prompts ----------

printf 'WinRM username: '
IFS= read -r USER_VAL || abort "no input" 1
[ -n "$USER_VAL" ] || abort "username is empty" 1

printf 'WinRM password (typing is hidden): '
IFS= read -rs PASS_VAL || abort "no input" 1
printf '\n'

printf 'Confirm password: '
IFS= read -rs PASS2 || abort "no input" 1
printf '\n'

[ -n "$PASS_VAL" ] || abort "password is empty" 1
[ "$PASS_VAL" = "$PASS2" ] || abort "passwords do not match — nothing written" 2

case "$USER_VAL" in
  " "*|*" ") echo "WARNING: username has a leading/trailing space; keeping it verbatim." >&2 ;;
esac

U_ENC=$(encode "$USER_VAL") || abort "username contains an unrepresentable character mix" 2
P_ENC=$(encode "$PASS_VAL") || abort "password contains a single quote plus one of  \"  \\  \$  \`  — cannot be written unambiguously. Choose another password or edit the file by hand." 2

# ---------- write ----------

if [ "$DO_BACKUP" = "1" ]; then
  BK_DIR="$HOME/.hermes/backups"
  mkdir -p "$BK_DIR" && chmod 700 "$BK_DIR"
  BK="$BK_DIR/env-backup-$(date +%Y%m%d-%H%M%S)"
  cp -p "$ENV_FILE" "$BK" && chmod 600 "$BK" || abort "backup failed — nothing written" 1
  echo "Backup: $BK"
fi

TMP="$ENV_FILE.tmp.$$"
trap 'rm -f "$TMP"' EXIT INT TERM

# Drop the entire previous managed block (header through end marker, inclusive) so
# nothing accumulates across runs, then also drop any stray bare copies of our keys.
HDR='# ===== ODIN (WinRM) — managed by add-winrm-creds.sh ====='
ENDM='# ===== end ODIN (WinRM) ====='
awk -v u="$USER_KEY" -v p="$PASS_KEY" -v h="$HOST_KEY" -v pt="$PORT_KEY" \
    -v hdr="$HDR" -v endm="$ENDM" '
  $0 == hdr  {inblk=1; next}
  $0 == endm {inblk=0; next}
  inblk      {next}
  $0 ~ "^"u"="   {next}
  $0 ~ "^"p"="   {next}
  $0 ~ "^"h"="   {next}
  $0 ~ "^"pt"="  {next}
  {print}
' "$ENV_FILE" > "$TMP" || abort "read/transform failed" 1

# Guarantee exactly one newline before the new block.
[ -s "$TMP" ] && [ "$(tail -c 1 "$TMP" | wc -l | tr -d ' ')" = "0" ] && printf '\n' >> "$TMP"

{
  echo "$HDR"
  echo "# Written $(date '+%Y-%m-%d %H:%M:%S %Z'). Re-run the script to change the password;"
  echo "# it replaces this whole block in place instead of appending duplicates."
  echo "$USER_KEY=$U_ENC"
  echo "$PASS_KEY=$P_ENC"
  echo "$HOST_KEY=$HOST"
  echo "$PORT_KEY=$PORT"
  echo "$ENDM"
} >> "$TMP" || abort "append failed — original untouched" 1

chmod 600 "$TMP" && mv "$TMP" "$ENV_FILE" || abort "atomic replace failed" 1
trap - EXIT INT TERM

echo "Wrote 4 keys."

# ---------- verify (booleans + hash comparison, never the values) ----------

FAIL=0
for k in "$USER_KEY" "$PASS_KEY" "$HOST_KEY" "$PORT_KEY"; do
  n=$(grep -c "^$k=" "$ENV_FILE")
  if [ "$n" = "1" ]; then echo "  $k: SET (exactly once)"
  else echo "  $k: PROBLEM — found $n occurrences"; FAIL=1; fi
done

MODE=$(stat -f '%Lp' "$ENV_FILE")
if [ "$MODE" = "600" ]; then echo "  file mode: 600 (unchanged)"; else echo "  file mode: $MODE — WARNING, expected 600"; FAIL=1; fi

# Does the value parse back to exactly what was typed? Compare hashes, not values.
EXPECT_P=$(sha_of "$PASS_VAL")
EXPECT_U=$(sha_of "$USER_VAL")
GOT=$("$HERMES_PY" - "$ENV_FILE" "$PASS_KEY" "$USER_KEY" 2>/dev/null <<'PY'
import sys, hashlib
from dotenv import dotenv_values
f, pk, uk = sys.argv[1], sys.argv[2], sys.argv[3]
v = dotenv_values(f)
for key in (uk, pk):
    val = v.get(key)
    print("MISSING" if val is None else hashlib.sha256(val.encode()).hexdigest())
PY
)
GOT_U=$(echo "$GOT" | sed -n '1p')
GOT_P=$(echo "$GOT" | sed -n '2p')
if [ "$GOT_U" = "$EXPECT_U" ] && [ "$GOT_P" = "$EXPECT_P" ]; then
  echo "  round-trip via python-dotenv: MATCH (both values parse back byte-identical)"
else
  echo "  round-trip via python-dotenv: MISMATCH — the loader is not reading what was written"
  FAIL=1
fi

# Does a cron-style `source .env` see them too?
SRC=$(( set -a; . "$ENV_FILE" >/dev/null 2>&1; set +a; \
        [ -n "${ODIN_WINRM_PASSWORD:-}" ] && [ -n "${ODIN_WINRM_USER:-}" ] && echo OK ) 2>/dev/null)
if [ "$SRC" = "OK" ]; then echo "  source .env (cron style): both visible"
else echo "  source .env (cron style): NOT both visible"; FAIL=1; fi

# ---------- optional live WinRM check ----------

if [ "$VERIFY_WINRM" = "1" ]; then
  echo
  echo "Live WinRM check against $HOST:$PORT ..."
  WINRM_PY="${WINRM_PY:-$HOME/.venvs/winrm/bin/python}"
  [ -x "$WINRM_PY" ] || WINRM_PY="$HERMES_PY"
  if "$WINRM_PY" -c "import winrm" 2>/dev/null; then
    WINRM_OUT=$(U="$USER_VAL" P="$PASS_VAL" H="$HOST" PT="$PORT" "$WINRM_PY" - 2>/dev/null <<'PY'
import os, winrm
u, p = os.environ["U"], os.environ["P"]
h, pt = os.environ["H"], os.environ["PT"]
url = f"http://{h}:{pt}/wsman"
# NTLM first: a Windows local account over WinRM usually refuses Basic. This host
# rejected Basic for every username form and accepted NTLM.
for transport in ("ntlm", "basic"):
    try:
        s = winrm.Session(url, auth=(u, p), transport=transport)
        r = s.run_cmd("cmd", ["/c", "echo", "ping"])
        print("  auth: OK via %s, exit %s, stdout: %s" % (transport, r.status_code, (r.std_out or b"").decode(errors="replace").strip()))
        break
    except Exception as e:
        print("  auth via %-5s: FAILED — %s: %s" % (transport, type(e).__name__, str(e)[:140]))
else:
    print("  BOTH transports rejected the credential.")
    print("  If the account is a Microsoft/Entra account (username looks like an email),")
    print("  WinRM cannot use it at all — store a LOCAL account instead, prefixed with the")
    print("  NetBIOS name: DOMAIN\\user (e.g. ODIN\\hermes).")
PY
)
    echo "$WINRM_OUT"
    case "$WINRM_OUT" in
      *"auth: OK"*) : ;;
      *) echo "  NOTE: the live login was rejected. The .env write above is still valid —"
         echo "        this only means the server would not accept the credential as typed."
         FAIL=1 ;;
    esac
  else
    echo "  pywinrm not available (looked in $WINRM_PY). Skipping."
    echo "  one-time setup: python3 -m venv ~/.venvs/winrm && ~/.venvs/winrm/bin/pip install pywinrm"
  fi
fi

echo
if [ "$FAIL" = "0" ]; then
  echo "Done — credentials installed and verified."
  exit 0
else
  echo "Done with PROBLEMS — see the lines marked above." >&2
  exit 3
fi
