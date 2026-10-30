#!/usr/bin/env python3
"""outcome-text-variant-read -- READ-ONLY. Does the venue spell one token two ways,
and did that ever split a position or a copy?

WHY: data-api-v2-outcome-normalisation predicted that v2 stripping punctuation would
break every join keyed on outcome TEXT across the 2026-10-19 cutover. This measures
the class directly instead of trusting the prediction. No writes, no decisions.

BASIS IS PRINTED WITH EVERY NUMBER: population (which table, which rows), clock (the
DB read instant), level (token text / position / fill).

Run: python3 scripts/outcome-text-variant-read.py [db-path]
"""
import datetime
import re
import sqlite3
import sys
from collections import defaultdict

DB = sys.argv[1] if len(sys.argv) > 1 else "prisma/dev.db"
PUNCT = re.compile(r"[^A-Za-z0-9]")


def norm(s):
    """Same contract as normalizeOutcomeLabel in src/lib/resolution.ts."""
    return PUNCT.sub("", s or "").upper()


def ts(ms):
    return datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%dT%H:%MZ")


con = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
cur = con.cursor()
print("outcome text-variant read | db " + DB + " | clock " + datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"))

texts = cur.execute("SELECT outcome, COUNT(*) FROM ObservedTrade GROUP BY outcome").fetchall()
ids = defaultdict(list)
for o, n in texts:
    ids[norm(o)].append((o, n))
twins = sorted([sorted(v) for v in ids.values() if len(v) > 1])
print("")
print("[1] TOKEN TEXT   level=token text, population=ObservedTrade all rows")
print("    rows " + str(sum(n for _, n in texts)) + " | distinct texts " + str(len(texts)) + " | distinct identities " + str(len(ids)))
print("    twin pairs (one token, two spellings) " + str(len(twins)))
for pair in twins:
    bits = []
    for o, n in pair:
        r = cur.execute("SELECT MIN(timestamp), MAX(timestamp) FROM ObservedTrade WHERE outcome = ?", (o,)).fetchone()
        bits.append(repr(o) + " n=" + str(n) + " " + ts(r[0]) + ".." + ts(r[1]))
    print("      " + " | ".join(bits))
apos = cur.execute("SELECT COUNT(*) FROM ObservedTrade WHERE outcome LIKE ?", ("%" + chr(39) + "%",)).fetchone()[0]
print("    rows whose outcome carries an apostrophe (the v2 strip signature): " + str(apos))

print("")
print("[2] POSITION SPLIT   level=position (wallet, marketId, token identity)")
for table in ("ObservedTrade", "PaperTrade"):
    seen = defaultdict(set)
    for w, m, o in cur.execute("SELECT walletAddress, marketId, outcome FROM " + table):
        seen[(w, m, norm(o))].add(o)
    print("    " + table + ": positions " + str(len(seen)) + " | carrying 2+ spellings " + str(sum(1 for v in seen.values() if len(v) > 1)))

print("")
print("[3] CROSS-TABLE   level=position, population=PaperTrade vs ObservedTrade")
obs = defaultdict(set)
for w, m, o in cur.execute("SELECT walletAddress, marketId, outcome FROM ObservedTrade"):
    obs[(w, m, norm(o))].add(o)
paper = defaultdict(set)
for w, m, o in cur.execute("SELECT walletAddress, marketId, outcome FROM PaperTrade"):
    paper[(w, m, norm(o))].add(o)
cross = [k for k in paper if k in obs and obs[k] != paper[k]]
print("    copied positions whose incoming fills spell the token differently: " + str(len(cross)))
for k in cross[:10]:
    print("      " + k[0][:10] + " " + k[1][:44] + " copy=" + str(sorted(paper[k])) + " fills=" + str(sorted(obs[k])))

print("")
print("[4] DOUBLE-BOOK   level=fill, population=ObservedTrade rows with no DecisionJournal")
q = "SELECT t.walletAddress, t.marketId, t.outcome FROM ObservedTrade t LEFT JOIN DecisionJournal d ON d.observedTradeId = t.id WHERE d.id IS NULL"
n = 0
for w, m, o in cur.execute(q):
    v = paper.get((w, m, norm(o)))
    if v and v != {o}:
        n += 1
print("    unscored fills on a copied position under a different spelling: " + str(n))
print("")
print("READ: twins are venue name variance (their eras interleave; most predate the cutover).")
print("The apostrophe count is the v2 strip signature; split and double-book counts are the cost.")
con.close()
