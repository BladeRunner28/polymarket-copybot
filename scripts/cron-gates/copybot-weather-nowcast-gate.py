#!/usr/bin/env python3
"""Gate for the wx2 weather read-report job (deterministic, one token on stdout).

Used as a cronjob `monitor`: its output is compared with the previous tick and the agent only wakes
when it CHANGES. So it must print a CONSTANT token while nothing has changed, never a counter.

Tokens:
  BELOW   sample floor not yet reached and everything is READABLE — agent stays asleep
  MET     >= 20 settled in-window days for at least one venue — wake the agent to write the read
  STALE   the newest sample row is older than 48h — the instrument stopped writing; wake the agent
          so a dead sampler cannot sit silent for weeks behind a "still below floor" verdict
  STALE:no-samples      the samples file does not exist (never ran, or wrote nowhere)
  STALE:unreadable      the newest row cannot be parsed (truncated/partial append) so freshness
                        cannot be established — BELOW would be a claim we cannot support
  STALE:reader-error…   the analyzer could not be run or wrote no usable census

WHY THE FAILURE TOKENS EXIST (fixed 2026-10-24): every one of the paths above used to `return None`
or fall through to `print("BELOW")`. Measured on the real module against fixtures: a truncated last
line, a garbage file, a missing file, a crashing reader and a reader that wrote nothing ALL printed
`BELOW` — byte-identical to the healthy tick, i.e. a dead instrument was indistinguishable from a
patient one. Worse, `OUT` (the reader's JSON) persisted in /tmp between ticks, so a crashing reader
left the PREVIOUS run's census on disk and the gate printed `MET` from it — a wake on a census
today's data never produced. Now OUT is unlinked before the run, a non-zero rc or missing/unparseable
census is a STALE token, and no token is ever printed that the artifacts do not support.

Read-only: runs the project's own analyzer, writes nothing but /tmp scratch.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/Users/xsnyde2/polymarket-copybot")
# Path overrides exist so the failure paths can be VERIFIED by pointing at fixtures instead of
# corrupting the live inputs (same reason kelly-window-report got C200_DRAWDOWN_FILE).
SAMPLES = Path(os.environ.get("WX2_SAMPLES") or REPO / "data" / "weather-nowcast-samples.jsonl")
READ = Path(os.environ.get("WX2_READ") or REPO / "scripts" / "weather-nowcast-read.py")
OUT = Path(os.environ.get("WX2_OUT") or "/tmp/wx2-read-gate.json")
FLOOR = 20
STALE_H = 48


def newest_sample_age_hours() -> float | None:
    """Hours since the newest sample row, or None when freshness cannot be established."""
    if not SAMPLES.exists():
        return None
    try:
        with SAMPLES.open() as fh:
            # 64 KB tail: a single bracket row can approach a few KB, and seeking into the middle
            # of the LAST line would make json.loads fail and turn a healthy file into a false
            # STALE:unreadable. 64 KB holds dozens of rows even at the widest observed width.
            fh.seek(max(0, fh.seek(0, 2) - 64000))
            last = [ln for ln in fh.read().splitlines() if ln.strip()][-1]
        row = json.loads(last)
        ts = row["ts"].replace("Z", "+00:00")
        from datetime import datetime
        return (time.time() - datetime.fromisoformat(ts).timestamp()) / 3600.0
    except Exception:
        return None


def main() -> int:
    if not SAMPLES.exists():
        print("STALE:no-samples")
        return 0

    age = newest_sample_age_hours()
    if age is None:
        # Distinct from a missing file: the file is there but its newest row is unreadable, so
        # "the sampler is fine and we are merely below floor" is not a supportable claim.
        print("STALE:unreadable")
        return 0
    if age > STALE_H:
        print("STALE")
        return 0

    # Never let a previous tick's census stand in for this one.
    try:
        OUT.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass

    try:
        p = subprocess.run([sys.executable, str(READ), "--json", str(OUT)],
                           cwd=str(REPO), capture_output=True, timeout=600, check=False)
        rc = p.returncode
    except Exception:
        print("STALE:reader-error:unrunnable")
        return 0

    if rc != 0:
        print(f"STALE:reader-error:rc{rc}")
        return 0

    try:
        settled = json.loads(OUT.read_text()).get("census", {}).get("settled_days", {})
    except Exception:
        print("STALE:reader-error:no-census")
        return 0

    met = any(int(v or 0) >= FLOOR for v in settled.values())
    print("MET" if met else "BELOW")
    return 0


if __name__ == "__main__":
    sys.exit(main())
