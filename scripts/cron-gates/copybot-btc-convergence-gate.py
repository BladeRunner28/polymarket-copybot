#!/usr/bin/env python3
"""Gate for the btx2 deterministic-convergence READ job (deterministic, one token on stdout).

Used as a cronjob `monitor`: its output is compared with the previous tick and the agent only wakes
when it CHANGES — so it prints a CONSTANT token while nothing has changed, never a counter, never a
percentage. Progress inside the floor must NOT wake anyone: 14 days of silence is the expected state.

Tokens:
  STALE:<h>       no coverage line in > 6h — the instrument stopped writing; wake so a dead sampler
                  cannot sit silent behind a "still below floor" verdict
  BELOW           floors not met and nothing structural has changed — agent stays asleep
  PREMISE         a premise-level finding has appeared: decided legs exist (>= 50) and >= 95% of them
                  have NO ASK on the determined side. That is the "unbuyable at any price" answer to
                  Q1 and it is worth a human seeing; it changes at most once.
  MET             the pre-registered sample floors are reached — wake the agent to write the gate read
  PASS / NOCLAIM  only after MET (the reader computes it); suffixed :E when the last 12 ticks logged
                  errors, so a broken sampler wakes the agent rather than sitting quiet

Read-only: reads the project's own sample/coverage files, writes nothing.
"""

from __future__ import annotations

import glob
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/Users/xsnyde2/polymarket-copybot")
DATA = REPO / "data"
COVERAGE = DATA / "btc-convergence-coverage.jsonl"
PINNED_CODE = "762ca9de3047"
FLOOR_ROWS_Q1 = 1500
FLOOR_DAYS_Q1 = 14
FLOOR_SUB99 = 200
STALE_HOURS = 6


def tail_jsonl(path, n):
    if not Path(path).exists():
        return []
    lines = []
    with open(path) as fh:
        for line in fh:
            if line.strip():
                lines.append(line)
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def main():
    cov = tail_jsonl(COVERAGE, 12)
    if not cov:
        print("STALE:never-ran")
        return 0
    try:
        age_h = (datetime.now(timezone.utc)
                 - datetime.fromisoformat(str(cov[-1]["ts"]).replace("Z", "+00:00"))).total_seconds() / 3600
    except Exception:  # noqa: BLE001
        print("STALE:unparsable-ts")
        return 0
    err_suffix = ":E" if any((c.get("errors") or []) for c in cov) else ""
    if age_h > STALE_HOURS:
        print(f"STALE:{age_h:.1f}h")
        return 0

    rows, decided = [], []
    for f in sorted(glob.glob(str(DATA / "btc-convergence-samples-*.jsonl*"))):
        opener = gzip.open if f.endswith(".gz") else open
        try:
            fh = opener(f, "rt")
        except OSError:
            continue
        with fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(r.get("code")) != PINNED_CODE:
                    continue        # rows from any other revision are not eligible, by pre-registration
                rows.append(r)
                if r.get("determined"):
                    decided.append(r)

    asks = [r for r in decided if (r.get("q1") or {}).get("ask") is not None]
    n_exec = len(asks)
    sub99 = sum(1 for r in asks if r["q1"]["ask"] < 0.99)
    days = len({str(r.get("ts", ""))[:10] for r in decided})

    if n_exec >= FLOOR_ROWS_Q1 and days >= FLOOR_DAYS_Q1 and sub99 >= FLOOR_SUB99:
        print(f"MET{err_suffix}")
        return 0
    if len(decided) >= 50 and not asks:
        print(f"PREMISE{err_suffix}")
        return 0
    print(f"BELOW{err_suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
