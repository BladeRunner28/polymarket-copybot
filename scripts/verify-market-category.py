#!/usr/bin/env python3
"""verify-market-category (reference side) — observed-trade-category-field card.

Emits a STRATIFIED sample of stored observed trades with the label the validated
Python classifier gives them (scripts/wallet-concentration-test.py::classify, the
implementation that agreed with the vendor's own category map at r = +0.548 over
353 wallets). The TypeScript port is then diffed against this file by
scripts/verify-market-category.ts — parity is verified, not assumed.

  python3 scripts/verify-market-category.py            # -> data/market-category-reference.json
  python3 scripts/verify-market-category.py --out /tmp/x.json   # don't touch the fixture

Read-only against prisma/dev.db.

2026-11-07 SELF-AUDIT (Lane B) — this sampler was both UNRUNNABLE and LYING, and
neither was visible from its own output:

  * UNRUNNABLE. The random arm drew 2,000 offsets as `LIMIT 1 OFFSET ?` over
    ObservedTrade. That is O(offset) per draw on a table that is now 5,959,230 rows
    (measured: ONE offset-3,000,000 query takes 9.1 s; 2,000 draws average ~1.5M
    rows each), so the run needs hours and never completed inside a 300 s budget.
    Consequence on disk: data/market-category-reference.json was still the
    2026-09-23T15:44 artefact — a 45-day-old fixture that the card's PARITY PASS
    is worded against, with nothing anywhere saying it could not be rebuilt.
    The arm is now a rowid SEEK (`WHERE rowid >= ? ORDER BY rowid LIMIT 1`), which
    is O(log n): 2,000 draws in ~2 s, whole run ~20 s.
  * LYING. The summary line printed "(30 tokens x 200 + 2000 random)" — components
    that add to 8,000 — beside a row count that was 2,599. The missing 5,401 rows
    are DEDUPE: `rows` is keyed by (marketId, marketQuestion), and ObservedTrade
    holds 5,959,230 trades over only 374,234 distinct (marketId, question) pairs,
    so 6,000 token-arm rows collapse to ~1,453 distinct pairs and the 2,000 random
    draws add ~1,790. Measured on live data 2026-11-07: requested 8,000 -> distinct
    3,243 (token arm 6,000 drawn / 1,453 distinct; random arm 2,000 drawn / 1,790).
    The line now prints drawn/returned/distinct per arm and the dedupe loss, and the
    composition is also frozen INTO the artefact under "sampling" so a later reader
    does not have to re-derive what the sample was.

Also: every query now has an explicit ORDER BY rowid. Without one, `LIMIT ?` over a
table scan returns whatever order the storage engine happened to produce — the
offline run reproduced, but nothing in the code said so.
"""
import argparse
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
DEFAULT_OUT = os.path.join(ROOT, "data", "market-category-reference.json")
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="artefact path (default: the committed fixture)")
    args = ap.parse_args()

    classify = load_classifier()
    db = sqlite3.connect(DB, uri=True)
    c = db.cursor()
    rows = {}
    top = [r[0] for r in c.execute(
        "SELECT marketCategory FROM ObservedTrade WHERE marketCategory IS NOT NULL "
        "GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 30"
    )]
    tok_drawn = tok_new = 0
    for tok in top:
        for mid, q in c.execute(
            "SELECT marketId, marketQuestion FROM ObservedTrade WHERE marketCategory=? "
            "ORDER BY rowid LIMIT ?", (tok, PER_TOKEN)
        ):
            tok_drawn += 1
            if (mid, q) not in rows:
                tok_new += 1
            rows[(mid, q)] = tok

    # Random arm: seek by rowid (O(log n)) instead of OFFSET (O(offset)).
    rnd = random.Random(SEED)
    lo, hi = c.execute("SELECT min(rowid), max(rowid) FROM ObservedTrade").fetchone()
    rnd_drawn = rnd_returned = rnd_new = 0
    rnd_past_end = 0
    for _ in range(RANDOM_ROWS):
        if lo is None:
            break
        target = rnd.randrange(lo, hi + 1)
        r = c.execute(
            "SELECT marketId, marketQuestion, marketCategory FROM ObservedTrade "
            "WHERE rowid >= ? ORDER BY rowid LIMIT 1", (target,)
        ).fetchone()
        rnd_drawn += 1
        if r is None:          # target past the last rowid — count it, never crash on it
            rnd_past_end += 1
            continue
        rnd_returned += 1
        if (r[0], r[1]) not in rows:
            rnd_new += 1
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

    requested = len(top) * PER_TOKEN + RANDOM_ROWS
    sampling = {
        "tokens": len(top),
        "perToken": PER_TOKEN,
        "randomRows": RANDOM_ROWS,
        "seed": SEED,
        "requested": requested,
        "distinct": len(out),
        "tokenArm": {"drawn": tok_drawn, "distinct": tok_new},
        "randomArm": {"drawn": rnd_drawn, "returned": rnd_returned,
                      "distinct": rnd_new, "pastEnd": rnd_past_end},
        "dedupeLoss": requested - len(out),
        "key": "(marketId, marketQuestion) — ObservedTrade holds many trades per market",
        "order": "ORDER BY rowid on every query (reproducible sample)",
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump({"generatedAt": __import__("datetime").datetime.now().isoformat(),
                   "classifier": "scripts/wallet-concentration-test.py::classify",
                   "sampling": sampling,
                   "rows": out}, f)

    print(f"wrote {args.out}: {len(out)} DISTINCT (marketId,question) rows")
    print(f"  requested {requested} = {len(top)} tokens x {PER_TOKEN} + {RANDOM_ROWS} random draws")
    print(f"  token arm : {tok_drawn} drawn -> {tok_new} distinct")
    print(f"  random arm: {rnd_drawn} drawn -> {rnd_returned} returned ({rnd_past_end} past end) -> {rnd_new} distinct")
    print(f"  dedupe    : {sampling['dedupeLoss']} row(s) collapsed "
          f"({100.0 * sampling['dedupeLoss'] / requested:.1f}% of the requested draws are repeat "
          f"(marketId,question) pairs, not new rows)")


if __name__ == "__main__":
    sys.exit(main())
