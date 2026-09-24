#!/usr/bin/env python3
"""verify-market-category (reference side) — observed-trade-category-field card.

Emits a STRATIFIED sample of stored observed trades with the label the validated
Python classifier gives them (scripts/wallet-concentration-test.py::classify, the
implementation that agreed with the vendor's own category map at r = +0.548 over
353 wallets). The TypeScript port is then diffed against this file by
scripts/verify-market-category.ts — parity is verified, not assumed.

  python3 scripts/verify-market-category.py            # -> data/market-category-reference.json

Read-only against prisma/dev.db.
"""
import importlib.util
import json
import os
import random
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# mode=ro, deliberately NOT immutable=1: the DB now runs journal_mode=wal (tuning #35
# Rec 1, applied 2026-09-24), and immutable=1 tells SQLite the file can never change, so
# it would skip the WAL entirely and read a stale (possibly pre-checkpoint) snapshot.
# Read-only + busy_timeout reads the current committed state without taking write locks.
DB = f"file:{os.path.join(ROOT, 'prisma', 'dev.db')}?mode=ro"
OUT = os.path.join(ROOT, "data", "market-category-reference.json")
PER_TOKEN = 200
RANDOM_ROWS = 2000
SEED = 20260923


def load_classifier():
    path = os.path.join(ROOT, "scripts", "wallet-concentration-test.py")
    spec = importlib.util.spec_from_file_location("conc_instrument", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.classify


def main():
    classify = load_classifier()
    db = sqlite3.connect(DB, uri=True)
    c = db.cursor()
    rows = {}
    top = [r[0] for r in c.execute(
        "SELECT marketCategory FROM ObservedTrade WHERE marketCategory IS NOT NULL "
        "GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 30"
    )]
    for tok in top:
        for mid, q in c.execute(
            "SELECT marketId, marketQuestion FROM ObservedTrade WHERE marketCategory=? LIMIT ?", (tok, PER_TOKEN)
        ):
            rows[(mid, q)] = tok
    rnd = random.Random(SEED)
    total = c.execute("SELECT COUNT(*) FROM ObservedTrade").fetchone()[0]
    for _ in range(RANDOM_ROWS):
        off = rnd.randrange(total)
        r = c.execute(
            "SELECT marketId, marketQuestion, marketCategory FROM ObservedTrade LIMIT 1 OFFSET ?", (off,)
        ).fetchone()
        rows[(r[0], r[1])] = r[2]

    out = []
    for (mid, q), tok in rows.items():
        coarse, fine = classify(mid, q)
        out.append({
            "marketId": mid,
            "question": q,
            "token": tok,
            "refCoarse": coarse,
            "refFine": fine,
        })
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"generatedAt": __import__("datetime").datetime.now().isoformat(),
                   "classifier": "scripts/wallet-concentration-test.py::classify",
                   "rows": out}, f)
    print(f"wrote {OUT}: {len(out)} stratified rows ({len(top)} tokens x {PER_TOKEN} + {RANDOM_ROWS} random)")


if __name__ == "__main__":
    sys.exit(main())
