#!/usr/bin/env python3
"""Diff recent RuleSet versions (read-only) to see what each change touched."""
import datetime
import json
import sqlite3

db = sqlite3.connect("file:prisma/dev.db?mode=ro", uri=True)
rows = db.execute(
    "SELECT version, createdAt, rulesJson FROM RuleSet ORDER BY version ASC"
).fetchall()
prev = None
for v, ts, rj in rows:
    cur = json.loads(rj)
    if prev is not None:
        diff = {
            k: (prev.get(k), cur.get(k))
            for k in set(prev) | set(cur)
            if prev.get(k) != cur.get(k)
        }
        if diff:
            d = datetime.datetime.utcfromtimestamp(ts / 1000)
            print("=== v%s  %s UTC" % (v, d.strftime("%Y-%m-%d %H:%M")))
            for k, (a, b) in sorted(diff.items()):
                print("    %-34s %s -> %s" % (k, a, b))
    prev = cur
