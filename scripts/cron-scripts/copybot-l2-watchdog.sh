#!/bin/bash
# CopyBot L2 recorder watchdog (v40, Homerun audit) — SUPERSEDED 2026-11-03, now a DELEGATE.
#
# WHY IT CHANGED: this job and `copybot-l2-recorder-watchdog` (every 5m) are two enabled cron
# entries that both self-start the same process. Only the 5m one is safe. This one had three
# independent instrument defects, all measured on 2026-11-03:
#
#  1. WRONG LAUNCHER. It started the recorder with `nohup npx tsx ... &` from the cron shell.
#     That is exactly the parentage scripts/start-l2-recorder.py was written to avoid — its
#     docstring records an instance started that way dying mid-collection at 2026-09-26
#     03:28:38 "with no alarm". A rescue path that produces a corpse is worse than no rescue:
#     it prints "L2 recorder started (pid N)" and the recorder dies at the next gateway
#     session boundary, so the alarm that would have fired is consumed.
#  2. NO LOCK. It took no lock of any kind, while the 5m supervisor takes
#     /tmp/copybot-l2-recorder-watchdog.lock and spends ~25s (pkill; sleep 5; start; sleep 20)
#     with NO process in the table. The two jobs fire in the same second (measured: both ran
#     at 06:40:38 on 2026-11-03, and the 15m ticks are a subset of the 5m ticks), so any
#     recorder death near a quarter hour puts a 15m tick inside that window: this script then
#     passes its "not running" test and starts a SECOND recorder on a different code path.
#     Two writers into data/l2/ is a corrupted measurement input, not a nuisance.
#  3. PASS CONDITION THAT CANNOT FAIL. "Healthy" meant `pgrep -f "record-l2"` matched, which
#     is true for a hung recorder as well as a live one, and which returns 2 PIDs for 1
#     recorder (tsx cli wrapper + its loader child, measured 56476/56478). The printed
#     "pid" was the wrapper, not the recorder.
#
# The job stays in the scheduler (the entry is not touched), but it now execs the supervisor:
# one code path, one lock, one heartbeat test, one launcher.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec /bin/bash "$HERE/copybot-l2-recorder-watchdog.sh" "$@"
