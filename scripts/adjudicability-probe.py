#!/usr/bin/env python3
"""adjudicability-probe.py — how much of a vintage COULD ever be fill-adjudicated?

Question: the Sep-2026 question-market vintage carries $5,055 of the book's question
profit and is 2.5% adjudicated. Is that because nobody has tried yet, or because the
L2 recorder never had a book at dispatch for those markets? The second is permanent.

Method (READ ONLY, sqlite opened immutable=1):
  1. take one settled lane x vertical x entry-vintage cell from PaperTrade;
  2. map marketId -> assetIds from data/l2-asset-map.jsonl (the recorder's own map);
  3. open data/l2/<assetId>.jsonl and look for ANY snapshot inside
     [openedAt - pre_ms, openedAt + post_ms];
  4. report legs/markets/cost/PnL split by "book at dispatch" vs "no book at dispatch".

A leg with no book at dispatch cannot be adjudicated by any later instrument, so the
covered share is the HARD CEILING on fill adjudication for that vintage. This is a
reachability bound, not a fill: a book existing is necessary, never sufficient.

  python3 scripts/adjudicability-probe.py --from 2026-09-01 --to 2026-10-01 \
      --lane BANKROLL_200 --vertical question
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(ROOT, "prisma", "dev.db")
MAP = os.path.join(ROOT, "data", "l2-asset-map.jsonl")
L2 = os.path.join(ROOT, "data", "l2")

QUESTION = ("will%", "highest%", "lowest%", "elon%")


def ms(day: str) -> int:
    """'YYYY-MM-DD' -> epoch ms (UTC)."""
    import calendar
    import time
    return calendar.timegm(time.strptime(day, "%Y-%m-%d")) * 1000


def load_asset_map():
    m = {}
    with open(MAP) as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("marketId") and isinstance(o.get("assetIds"), list):
                m[o["marketId"]] = o["assetIds"]
    return m


def book_at(path: str, t0: int, lo: int, hi: int) -> tuple[bool, str]:
    """Scan one recorder file for a snapshot in [lo, hi]. Returns (hit, first_ts_note)."""
    if not os.path.exists(path):
        return False, "absent"
    try:
        with open(path, "rb") as fh:
            first = fh.readline()
            if not first:
                return False, "empty"
            try:
                t_first = json.loads(first).get("ts")
            except ValueError:
                t_first = None
            note = f"first={t_first}"
            if isinstance(t_first, int) and t_first > hi:
                return False, note  # starts after our window
            for raw in fh:
                if not raw.strip():
                    continue
                try:
                    ts = json.loads(raw).get("ts")
                except ValueError:
                    continue
                if ts is None:
                    continue
                if ts > hi:
                    return False, note
                if ts >= lo:
                    return True, note
    except OSError as e:
        return False, f"io:{e}"
    return False, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", default="2026-09-01")
    ap.add_argument("--to", dest="d1", default="2026-10-01")
    ap.add_argument("--lane", default="BANKROLL_200")
    ap.add_argument("--vertical", default="question", choices=["question", "other"],
                    help="question = will/highest/lowest/elon ids; other = everything else")
    ap.add_argument("--pre-ms", type=int, default=60_000)
    ap.add_argument("--post-ms", type=int, default=300_000)
    args = ap.parse_args()

    t0, t1 = ms(args.d0), ms(args.d1)
    q = " OR ".join(f"marketId LIKE '{p}'" for p in QUESTION)
    where_v = f"({q})" if args.vertical == "question" else f"NOT ({q})"
    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(f"""
        SELECT id, marketId, openedAt, simulatedPositionSize cost, realizedPnl pnl, fillStatus
        FROM PaperTrade
        WHERE isDemo=0 AND botId=? AND status IN ('closed','resolved')
          AND realizedPnl IS NOT NULL AND openedAt >= ? AND openedAt < ? AND {where_v}
    """, (args.lane, t0, t1))]
    con.close()
    if not rows:
        print("no legs in that cell", file=sys.stderr)
        return 2

    amap = load_asset_map()
    covered, uncovered, unmapped = [], [], []
    for r in rows:
        assets = amap.get(r["marketId"])
        if not assets:
            unmapped.append(r)
            continue
        hit = False
        for a in assets:
            ok, _ = book_at(os.path.join(L2, f"{a}.jsonl"), r["openedAt"],
                            r["openedAt"] - args.pre_ms, r["openedAt"] + args.post_ms)
            if ok:
                hit = True
                break
        (covered if hit else uncovered).append(r)

    def agg(name, sub, denom):
        if not sub:
            print(f"{name:22s} n=0")
            return
        cost = sum(x["cost"] or 0 for x in sub)
        pnl = sum(x["pnl"] or 0 for x in sub)
        adj = sum(1 for x in sub if x["fillStatus"] is not None)
        print(f"{name:22s} n={len(sub):4d} ({100.0*len(sub)/denom:5.1f}%) "
              f"mkts={len({x['marketId'] for x in sub}):4d} cost=${cost:8.0f} "
              f"pnl={pnl:+8.0f} adjudicated={adj:3d}")

    print(f"\ncell: lane={args.lane} vertical={args.vertical} "
          f"vintage={args.d0}..{args.d1} window=[-{args.pre_ms//1000}s,+{args.post_ms//1000}s]")
    print(f"legs={len(rows)}  markets={len({r['marketId'] for r in rows})}\n")
    agg("BOOK AT DISPATCH", covered, len(rows))
    agg("no book at dispatch", uncovered, len(rows))
    agg("market never mapped", unmapped, len(rows))
    # Inside the only adjudicable slice, what does the fill verdict already say?
    for fs in ("filled", "unfilled", "NULL"):
        sub = [x for x in covered
               if (x["fillStatus"] == fs if fs != "NULL" else x["fillStatus"] is None)]
        if sub:
            cost = sum(x["cost"] or 0 for x in sub)
            pnl = sum(x["pnl"] or 0 for x in sub)
            print(f"   covered/{fs:8s} n={len(sub):3d} cost=${cost:7.0f} pnl={pnl:+7.0f}")
    print(f"\nceiling = {100.0*(len(covered)+0)/len(rows):.1f}% of legs could ever be adjudicated "
          f"(book at dispatch is necessary, not sufficient)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
