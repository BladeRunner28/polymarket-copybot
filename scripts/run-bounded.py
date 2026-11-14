#!/usr/bin/env python3
"""Run a command under a WALL-CLOCK DEADLINE, killing its whole process group.

Why this exists (2026-11-14 self-audit)
---------------------------------------
The nightly EOD chain (scripts/cron-scripts/copybot-eod.sh) had no deadline on any
step. On 2026-11-13 the 22:00 run was killed by the cron harness at its 3600 s ceiling
inside one step, so `npm run report:daily` — six steps later — NEVER RAN. Result: no
DailyReport row for 2026-11-13 at all (every prior day has one) and no Discord report.
A slow step must cost its own output, not the whole day's report.

That step could not be shown to be slow ON ITS OWN: `review:outcomes` completed in 16 s
when re-run on 2026-11-14, so the trigger was transient and is not claimed here. What IS
reproducible is the structural defect: with no per-step bound, ANY step can consume the
whole budget and take the report with it.

macOS has no `timeout(1)` on this host (verified 2026-11-14: `which timeout gtimeout`
returns nothing), and `perl -e 'alarm..'` cannot kill the grandchildren a killed shell
leaves behind. Hence this helper: new session (pgid == pid), SIGTERM the GROUP, then
SIGKILL the group. No orphans holding the SQLite DB.

Exit codes: the command's own status when it finishes; 124 when the deadline fired.
"""
import argparse
import os
import signal
import subprocess
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser(description="run a command with a kill-the-group deadline")
    ap.add_argument("--timeout", type=float, required=True, help="deadline in seconds")
    ap.add_argument("--label", default="step", help="name printed in the deadline message")
    ap.add_argument("--grace", type=float, default=10.0, help="seconds between SIGTERM and SIGKILL")
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="-- command [args...]")
    args = ap.parse_args()

    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("[BOUNDED] no command given", file=sys.stderr)
        return 2

    started = time.time()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # its own process group; we kill the group, not just the shell
    )
    try:
        return proc.wait(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        elapsed = int(time.time() - started)
        print(
            "\n[BOUNDED] %s hit its %ds deadline (ran %ds) and was KILLED — the output above "
            "is PARTIAL; the caller continues so the report still runs."
            % (args.label, int(args.timeout), elapsed),
            file=sys.stderr,
        )
        for sig, wait in ((signal.SIGTERM, args.grace), (signal.SIGKILL, 5.0)):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                break
            try:
                proc.wait(timeout=wait)
                break
            except subprocess.TimeoutExpired:
                continue
        return 124


if __name__ == "__main__":
    sys.exit(main())
