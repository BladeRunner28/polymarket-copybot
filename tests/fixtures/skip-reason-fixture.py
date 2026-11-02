#!/usr/bin/env python3
"""Deterministic DecisionJournal for tests/skip-reason-levels.test.ts.

Five rows, chosen so the two measurement facts the caption used to assert are
each visible in the output:

  s1  skip  3 DISTINCT tags        -> inflation: 3 entries for 1 decision
  s2  skip  the SAME tag twice     -> the ONLY thing that makes the levels diverge
  s3  skip  empty risksJson,
            one tag in reasonsJson -> the documented fallback path
  s4  skip  no tags at all         -> a bare row
  p1  paper_copy, 2 tags           -> must be EXCLUDED (population is refusals)

Expected on this fixture: 4 rows, 1 bare, 3 tagged, entries 6, within-row
duplicates 1, and DIVERGE on exactly one tag.
"""
import json
import os
import sqlite3
import sys

DAY = 86_400_000
NOW = 1_900_000_000_000


def build(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)
    c = sqlite3.connect(path)
    c.execute(
        """CREATE TABLE DecisionJournal (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             marketId TEXT, decision TEXT, confidence REAL,
             reasonsJson TEXT, risksJson TEXT, isDemo INTEGER,
             createdAt INTEGER)"""
    )
    rows = [
        ("m1", "skip", json.dumps(["a-gate", "b-gate", "c-gate"]), json.dumps([])),
        ("m2", "skip", json.dumps(['v45 blacklist category "cs2"', 'v45 blacklist category "cs2"']), json.dumps([])),
        ("m3", "skip", json.dumps([]), json.dumps(["price drifted 0.005 (too late)"])),
        ("m4", "skip", json.dumps([]), json.dumps([])),
        ("m5", "paper_copy", json.dumps(["a-gate", "b-gate"]), json.dumps([])),
    ]
    for i, (mid, dec, risks, reasons) in enumerate(rows):
        c.execute(
            "INSERT INTO DecisionJournal (marketId, decision, confidence, reasonsJson, risksJson, isDemo, createdAt)"
            " VALUES (?,?,?,?,?,0,?)",
            (mid, dec, 0.5, reasons, risks, NOW - i * 1000),
        )
    c.commit()
    c.close()


if __name__ == "__main__":
    build(sys.argv[1])
