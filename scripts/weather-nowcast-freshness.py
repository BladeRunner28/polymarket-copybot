#!/usr/bin/env python3
"""Artifact-freshness check for one weather-sampler city file (used by the hourly wrapper).

Freshness is a property of the ARTIFACT, not of the job: a sampler that exits 0 while writing nothing
must not look healthy. Prints ONE line (which the wrapper delivers) when the newest row is unreadable,
older than --max-age-min, or not from THIS tick. Prints nothing when fresh. Exit code is always 0.

WHY THE "THIS TICK" BOUND (2026-10-27): the wrapper's own contract says "the newest row in THIS city's
file must be from THIS run", but the check only had an UPPER bound (75 min). With hourly ticks a run
that wrote nothing leaves the previous tick's row ~60 min old -- under the bar -- so a dead sampler
read as healthy for a full extra hour before alerting. Measured on a fixture holding only the
previous tick's rows (ts 60 min old): the old check printed nothing and exited 0.

Why this is its own file (2026-10-27): the wrapper now samples TWO cities, and the check used to be an
inline python heredoc that could only look at one file. One file cannot tell a healthy NYC from a dead DFW.

Usage: python3 scripts/weather-nowcast-freshness.py <samples.jsonl> <stamp> <city> [--max-age-min 75]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta


def parse_ts(value: str) -> datetime | None:
    """ISO 8601, tolerating a COMPACT UTC offset.

    `date +%Y-%m-%dT%H:%M:%S%z` (what the wrapper passes as <stamp>) emits `-0500`,
    which datetime.fromisoformat rejects before 3.11's strict form -- it wants
    `-05:00`. Without this normalisation the "this tick" bound parsed the stamp to
    None and switched ITSELF OFF silently, i.e. a probe that cannot fail. Measured
    2026-10-27: fromisoformat('2026-10-27T06:54:56-0500') -> ValueError.
    """
    s = str(value or "").strip()
    if not s:
        return None
    if len(s) >= 5 and s[-5] in "+-" and s[-4:].isdigit() and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("stamp")
    ap.add_argument("city")
    ap.add_argument("--max-age-min", type=float, default=75.0)
    # The lower bound: the newest row must come from the tick that just ran. A full run
    # takes ~30-60s per city (measured: nyc 11:44:34Z, dfw 11:45:02Z in the same tick), so
    # 6 minutes cannot false-alarm on a slow-but-working sampler.
    ap.add_argument("--this-run-grace-min", type=float, default=6.0)
    a = ap.parse_args()
    try:
        with open(a.path) as fh:
            fh.seek(max(0, fh.seek(0, 2) - 8000))
            last = [ln for ln in fh.read().splitlines() if ln.strip()][-1]
        row = json.loads(last)
        row_ts = parse_ts(row["ts"])
        if row_ts is None:
            raise ValueError("unparseable ts: " + str(row.get("ts"))[:40])
        age_min = (time.time() - row_ts.timestamp()) / 60.0
    except Exception as exc:  # noqa: BLE001
        print("stale: weather-nowcast[" + a.city + "] no readable sample row (" + str(exc) + ") at " + a.stamp)
        return 0
    # Reference for "this tick" is the wrapper's OWN stamp (taken before the sampler ran),
    # not the wall clock at check time: the sampler's row ts is always >= the stamp when the
    # run worked, and stays below it when the run wrote nothing — so a slow-but-working
    # sampler cannot false-alarm and a silent one cannot hide.
    stamp_ts = parse_ts(a.stamp)
    if age_min > a.max_age_min:
        print("stale: weather-nowcast[" + a.city + "]: newest sample row is " + str(round(age_min))
              + " min old at " + a.stamp + " - the lane wrote nothing this tick")
    elif stamp_ts is not None and row_ts < stamp_ts - timedelta(minutes=a.this_run_grace_min):
        print("stale: weather-nowcast[" + a.city + "]: wrote nothing THIS tick - newest row is "
              + str(round(age_min)) + " min old at " + a.stamp
              + " (previous tick's row, still inside the " + str(round(a.max_age_min)) + " min window)")
    if stamp_ts is None:
        # the max-age check above still ran; only the tighter bound is missing. Say so on
        # stderr rather than passing quietly with half a probe.
        print("stale-check: weather-nowcast[" + a.city + "] could not parse the run stamp '"
              + str(a.stamp) + "' — the 'wrote nothing THIS tick' bound was NOT applied",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
