#!/usr/bin/env python3
"""Is the STANDARD book's profit real, or booked at entries that never existed?

Joins the STANDARD fill booth's per-leg book stamps (data/standard-fill-stamp-backfill-*.jsonl)
to realized PnL and splits the book on REACHABILITY: was there a seller at or below the price we
booked, at any lag bucket? Reachability is an UPPER bound on fill probability (min-ask over up to
60 min, no queue position, no size), so a leg that fails this test could not have filled.

Basis: cost = simulatedPositionSize (dollars at risk); PnL = realizedPnl on
status IN ('closed','resolved'); label = realizedPnl > 0; CI = market-clustered bootstrap.

Read-only. Changes no rule, no figure, no row.
"""
import collections
import glob
import json
import os
import random
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "prisma", "dev.db")
STAMP_GLOB = os.path.join(HERE, "..", "data", "standard-fill-stamp-backfill-*.jsonl")


def latest_stamp():
    files = sorted(glob.glob(STAMP_GLOB))
    if not files:
        raise SystemExit("no backfill artifact found")
    with open(files[-1]) as fh:
        return files[-1], json.loads(fh.readline())


def cluster_ci(sub, key="market", iters=2000, seed=11):
    by = collections.defaultdict(list)
    for x in sub:
        by[x[key]].append(x)
    keys = list(by)
    if len(keys) < 5:
        return None
    rng = random.Random(seed)
    out = []
    for _ in range(iters):
        cost = pnl = 0.0
        for _ in keys:
            for x in by[keys[rng.randrange(len(keys))]]:
                cost += x["cost"]
                pnl += x["pnl"]
        if cost:
            out.append(100 * pnl / cost)
    out.sort()
    return [round(out[int(0.025 * len(out))], 1), round(out[int(0.975 * len(out))], 1)]


def summarise(sub, label):
    if not sub:
        print(f"  {label:24s} n=0")
        return {}
    cost = sum(x["cost"] for x in sub)
    pnl = sum(x["pnl"] for x in sub)
    ordered = sorted((x["pnl"] for x in sub), reverse=True)
    ex3 = sum(ordered[3:]) if len(ordered) > 3 else 0.0
    win = 100 * sum(1 for x in sub if x["pnl"] > 0) / len(sub)
    roi = 100 * pnl / cost if cost else 0
    print(f"  {label:24s} n={len(sub):4d} at-risk=${cost:7,.0f} PnL=${pnl:8,.2f} "
          f"ROI={roi:6.1f}%  win={win:5.1f}%  ex-top3=${ex3:8,.2f}  CI={cluster_ci(sub)}")
    return {"n": len(sub), "cost": round(cost, 2), "pnl": round(pnl, 2),
            "roi_pct": round(roi, 1), "ex_top3": round(ex3, 2), "ci95": cluster_ci(sub)}


def main():
    path, d = latest_stamp()
    print(f"stamp: {os.path.relpath(path)}")
    cov = d["coverage"]
    print(f"STANDARD legs ever: {cov['standardLegsAll']:,}   in L2 scope: {cov['standardLegsInScope']:,}"
          f"   with a book: {cov['bookStamped']:,}   tape: {cov['tapeStamped']:,}")
    print(f"-> only {100*cov['bookStamped']/cov['standardLegsAll']:.1f}% of the STANDARD book is "
          f"adjudicable at all; the rest predates the L2 corpus and can never be verified")

    legs = [l for l in d["legs"] if l.get("book")]
    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
    ids = [l["id"] for l in legs]
    rows = {r[0]: r for r in con.execute(
        f"SELECT id,realizedPnl,simulatedPositionSize,status,marketId FROM PaperTrade "
        f"WHERE id IN ({','.join('?' * len(ids))})", ids)}
    con.close()

    def min_attainable(l):
        b = (l["book"].get("byBucket") or {})
        vals = [v["price"] for v in b.values() if v and v.get("price") is not None]
        return min(vals) if vals else l["book"].get("firstAsk")

    recs = []
    for l in legs:
        r = rows.get(l["id"])
        if not r or r[3] not in ("closed", "resolved") or r[1] is None:
            continue
        ma = min_attainable(l)
        if ma is None:
            continue
        recs.append({"id": l["id"], "dp": l["decisionPrice"], "ma": ma,
                     "pnl": r[1], "cost": r[2] or 0, "market": r[4]})

    print(f"\nevaluable settled legs: {len(recs)}")
    art = {"stamp": path, "n_evaluable": len(recs)}

    for tol, label in ((0.0, "tolerance 0"), (0.01, "+1c slack")):
        reach = [x for x in recs if x["ma"] <= x["dp"] + tol + 1e-9]
        unreach = [x for x in recs if x["ma"] > x["dp"] + tol + 1e-9]
        print(f"\n=== reachability at the booked price ({label}) ===")
        art[f"reachable_{label}"] = summarise(reach, "REACHABLE at booked")
        art[f"unreachable_{label}"] = summarise(unreach, "NOT reachable")
        print(f"  reachability rate: {len(reach)}/{len(recs)} = {100*len(reach)/len(recs):.1f}%")

    art["all"] = summarise(recs, "ALL adjudicable")
    share = (art["reachable_tolerance 0"]["pnl"] / art["all"]["pnl"]) if art["all"]["pnl"] else 0
    print(f"\nshare of adjudicable profit sitting on ATTAINABLE entries: {100*share:.0f}%")

    out = os.path.join(HERE, "..", "data", "standard-fill-reachability.json")
    with open(out, "w") as fh:
        json.dump(art, fh, indent=1)
    print(f"artifact -> {os.path.relpath(out)}")


if __name__ == "__main__":
    main()
