#!/usr/bin/env python3
"""C-200 sole-blocker census over the last N days of DecisionJournal rows (read-only).

Usage: python3 scripts/c200-blocker-census.py [days]
"""
import json
import sqlite3
import sys
from collections import Counter

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
db = sqlite3.connect("file:prisma/dev.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row

SQL = (
    "SELECT id, createdAt, risksJson, decision, ruleSetVersion FROM DecisionJournal "
    "WHERE isDemo = 0 AND ruleSetVersion >= 49 "
    "AND createdAt > (strftime('%%s','now','-%d days') * 1000)" % DAYS
)
rows = db.execute(SQL).fetchall()

sole = Counter()
anyb = Counter()
n_rows = 0
n_blocked = 0

for r in rows:
    raw = r["risksJson"]
    if not raw:
        continue
    n_rows += 1
    try:
        arr = json.loads(raw)
    except Exception:
        continue
    if not isinstance(arr, list):
        continue
    # normalized blocker keys: strip the free-text tail after a colon
    keys = []
    for item in arr:
        if not isinstance(item, str):
            continue
        k = item.split(":")[0].strip()
        if not k:
            continue
        keys.append(k)
    if not keys:
        continue
    n_blocked += 1
    uniq = sorted(set(keys))
    for k in uniq:
        anyb[k] += 1
    if len(uniq) == 1:
        sole[uniq[0]] += 1

print("rows with risksJson=%d  rows with >=1 blocker=%d  (last %dd)" % (n_rows, n_blocked, DAYS))
print("\nSOLE blockers (only gate that fired):")
for k, v in sole.most_common(20):
    print("  %5d  %s" % (v, k))
print("\nANY blocker (presence):")
for k, v in anyb.most_common(20):
    print("  %5d  %s" % (v, k))
