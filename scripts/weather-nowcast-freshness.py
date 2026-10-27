#!/usr/bin/env python3
"""Artifact-freshness check for one weather-sampler city file (used by the hourly wrapper).

Freshness is a property of the ARTIFACT, not of the job: a sampler that exits 0 while writing nothing
must not look healthy. Prints ONE line (which the wrapper delivers) when the newest row is unreadable or
older than --max-age-min; prints nothing when fresh. Exit code is always 0.

Why this is its own file (2026-10-27): the wrapper now samples TWO cities, and the check used to be an
inline python heredoc that could only look at one file. One file cannot tell a healthy NYC from a dead DFW.

Usage: python3 scripts/weather-nowcast-freshness.py <samples.jsonl> <stamp> <city> [--max-age-min 75]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("stamp")
    ap.add_argument("city")
    ap.add_argument("--max-age-min", type=float, default=75.0)
    a = ap.parse_args()
    try:
        with open(a.path) as fh:
            fh.seek(max(0, fh.seek(0, 2) - 8000))
            last = [ln for ln in fh.read().splitlines() if ln.strip()][-1]
        row = json.loads(last)
        age_min = (time.time() - datetime.fromisoformat(row["ts"]).timestamp()) / 60.0
    except Exception as exc:  # noqa: BLE001
        print("stale: weather-nowcast[" + a.city + "] no readable sample row (" + str(exc) + ") at " + a.stamp)
        return 0
    if age_min > a.max_age_min:
        print("stale: weather-nowcast[" + a.city + "]: newest sample row is " + str(round(age_min))
              + " min old at " + a.stamp + " - the lane wrote nothing this tick")
    return 0


if __name__ == "__main__":
    sys.exit(main())
