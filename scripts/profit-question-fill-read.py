#!/usr/bin/env python3
"""Item 2's decision rule, computed on the population item 2 actually names.

The approved path (drafts/profit-path-20261117.md, item 2) says: adjudicate the QUESTION-market
class, and the rule is "if >=60% of the question-market legs tape out as filled at non-negative
ROI, the profit is real; otherwise it is written off permanently."

That rule has never been evaluated on question-market legs. The lane-wide STANDARD reachability
read (scripts/standard-fill-reachability-read.py) answers "is the STANDARD book's profit real",
pooled over every vertical, on the 353 settled legs of the 2026-11-17 backfill. This read joins the
CURRENT union stamp (data/standard-fill-stamp.jsonl, all book-stamped legs) to settled PnL and splits
by vertical x reachability, so the question cell gets its own n, its own at-risk and its own
market-clustered CI.

Basis (identical to profit-path-research.py so the numbers are comparable):
  cost   = PaperTrade.simulatedPositionSize   (DOLLARS AT RISK, not notional)
  pnl    = realizedPnl, status IN ('closed','resolved')  (TR-15 OR), isDemo=0
  dedupe = first leg per (botId, walletAddress, marketId, outcome)
  clock  = entry vintage, never settlement date
  CI     = market-clustered bootstrap (resample markets, not legs)
  reach  = min ask across the stamp's lag buckets <= booked price (+ tol). An UPPER bound on fill:
           no queue position, no size. A leg that fails it could not have filled.

Read-only. Writes data/profit-question-fill-read.json. Changes no rule, no figure, no row.
"""
from __future__ import annotations

import collections
import json
import os
import random
import re
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "prisma", "dev.db")
UNION = os.path.join(HERE, "..", "data", "standard-fill-stamp.jsonl")
OUT = os.path.join(HERE, "..", "data", "profit-question-fill-read.json")

QUESTION = {"will", "highest", "lowest", "elon"}
ESPORTS = {"cs2", "dota2", "lol", "lec", "val"}
SPORTS = {"ufc", "atp", "swe", "fif", "cbb", "mlb", "col", "ucl", "ere", "unl", "bel1",
          "clf", "us", "bun", "itsb", "por", "lal", "nhl", "wta", "crichundred", "den",
          "mls", "itf", "fl1", "mex", "bra", "elc", "sea", "fifwc", "uel", "arg", "nfl",
          "efl", "wnba", "cfb", "epl"}


def category(market_id):
    m = re.match(r"^([a-z0-9]+)", (market_id or "").lower())
    return m.group(1) if m else "?"


def vertical(market_id):
    c = category(market_id)
    if c in QUESTION:
        return "question"
    if c in ESPORTS:
        return "esports"
    if c in SPORTS:
        return "sports"
    return "other"


def cluster_ci(sub, iters=2000, seed=13):
    by = collections.defaultdict(list)
    for x in sub:
        by[x["market"]].append(x)
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
            out.append(100.0 * pnl / cost)
    out.sort()
    if not out:
        return None
    return [round(out[int(0.025 * len(out))], 1), round(out[int(0.975 * len(out))], 1)]


def summarise(sub):
    if not sub:
        return {"n": 0}
    cost = sum(x["cost"] for x in sub)
    pnl = sum(x["pnl"] for x in sub)
    ordered = sorted((x["pnl"] for x in sub), reverse=True)
    ex3 = sum(ordered[3:]) if len(ordered) > 3 else 0.0
    wins = [x["pnl"] for x in sub if x["pnl"] > 0]
    losses = [x["pnl"] for x in sub if x["pnl"] <= 0]
    return {
        "n": len(sub),
        "markets": len({x["market"] for x in sub}),
        "cost": round(cost, 2),
        "pnl": round(pnl, 2),
        "roi_pct": round(100.0 * pnl / cost, 1) if cost else None,
        "win_pct": round(100.0 * len(wins) / len(sub), 1),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "ex_top3_pnl": round(ex3, 2),
        "ex_top3_roi_pct": round(100.0 * ex3 / cost, 1) if cost else None,
        "ci95": cluster_ci(sub),
    }


def line(label, s):
    if not s.get("n"):
        print(f"  {label:26s} n=0")
        return
    roi = s["roi_pct"] if s["roi_pct"] is not None else 0.0
    print(f"  {label:26s} n={s['n']:4d} mkts={s['markets']:4d} at-risk=${s['cost']:8,.0f} "
          f"PnL=${s['pnl']:9,.2f} ROI={roi:7.1f}% win={s['win_pct']:5.1f}% "
          f"ex-top3=${s['ex_top3_pnl']:8,.2f} CI={s['ci95']}")


def main():
    with open(UNION) as fh:
        d = json.loads(fh.readline())
    cov = d.get("coverage") or {}
    legs = d.get("legs") or []
    stamped = [l for l in legs if l.get("book") and l.get("decisionPrice") is not None]
    print(f"union stamp: {os.path.relpath(UNION)} ranAt={d.get('ranAt')}")
    print(f"union legs={len(legs)}  with a book stamp={len(stamped)}  "
          f"book coverage of in-scope={100.0*len(stamped)/len(legs):.1f}%")

    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    ids = [l["id"] for l in stamped]
    placeholders = ",".join("?" * len(ids))
    raw = [dict(r) for r in con.execute(
        f"SELECT id,botId,walletAddress,marketId,outcome,entryPrice,realizedPnl,"
        f"simulatedPositionSize,fillStatus,status,openedAt FROM PaperTrade "
        f"WHERE id IN ({placeholders}) AND isDemo=0 AND status IN ('closed','resolved') "
        f"AND realizedPnl IS NOT NULL", ids)]
    con.close()

    # dedupe: first leg per (botId, wallet, market, outcome) -- same rule as profit-path
    raw.sort(key=lambda r: r["openedAt"] or 0)
    seen, rows = set(), {}
    for r in raw:
        key = (r["botId"], r["walletAddress"], r["marketId"], r["outcome"])
        if key in seen:
            continue
        seen.add(key)
        rows[r["id"]] = r
    print(f"settled deduped rows joinable from stamped legs: {len(rows)}")

    def min_attainable(l):
        b = (l.get("book") or {}).get("byBucket") or {}
        vals = [v["price"] for v in b.values() if v and v.get("price") is not None]
        return min(vals) if vals else (l.get("book") or {}).get("firstAsk")

    recs = []
    for l in stamped:
        r = rows.get(l["id"])
        if not r:
            continue
        ma = min_attainable(l)
        if ma is None:
            continue
        recs.append({
            "id": l["id"],
            "vert": vertical(r["marketId"]),
            "dp": l["decisionPrice"],
            "ma": ma,
            "pnl": r["realizedPnl"] or 0.0,
            "cost": r["simulatedPositionSize"] or 0.0,
            "market": r["marketId"],
            "botId": r["botId"],
            "fillStatus": r["fillStatus"],
        })

    art = {
        "stamp": os.path.relpath(UNION),
        "stamp_ranAt": d.get("ranAt"),
        "union_legs": len(legs),
        "stamped_with_book": len(stamped),
        "evaluable_settled": len(recs),
        "basis": ("cost=simulatedPositionSize dollars at risk; realizedPnl on status IN "
                  "(closed,resolved); isDemo=0; dedupe first leg per bot|wallet|market|outcome; "
                  "entry vintage; market-clustered bootstrap 2000 draws; reachability = min ask "
                  "in the stamp's lag buckets <= booked price (upper bound on fill, no queue, no size)"),
    }
    print(f"evaluable settled legs (book + price + settled): {len(recs)}\n")

    for tol, tlabel in ((0.0, "tol 0"), (0.01, "+1c slack")):
        print(f"=== REACHABILITY AT BOOKED PRICE ({tlabel}) ===")
        tot_reach = tot = 0
        for v in ("question", "sports", "esports", "other"):
            sub = [x for x in recs if x["vert"] == v]
            reach = [x for x in sub if x["ma"] <= x["dp"] + tol + 1e-9]
            unreach = [x for x in sub if x["ma"] > x["dp"] + tol + 1e-9]
            tot += len(sub); tot_reach += len(reach)
            if not sub:
                continue
            line(f"{v} ALL", summarise(sub))
            line(f"{v} REACHABLE", summarise(reach))
            line(f"{v} NOT reachable", summarise(unreach))
            rate = 100.0 * len(reach) / len(sub)
            print(f"  {v} reachability rate: {len(reach)}/{len(sub)} = {rate:.1f}%\n")
            art[f"{v}_{tlabel}"] = {
                "all": summarise(sub),
                "reachable": summarise(reach),
                "unreachable": summarise(unreach),
                "reachability_pct": round(rate, 1),
            }
        print(f"  ALL VERTICALS reachability: {tot_reach}/{tot} = "
              f"{100.0*tot_reach/tot if tot else 0:.1f}%\n")
        art[f"all_{tlabel}"] = {"n": tot, "reachable": tot_reach,
                                "reachability_pct": round(100.0 * tot_reach / tot, 1) if tot else None}

    # --- Why the tolerance decides the verdict: the attainable-minus-booked delta distribution.
    # On 1c-tick markets a strict 0-tolerance test rejects every leg whose ask printed one cent
    # above the booked price, so the answer can turn on tick rounding rather than on fills.
    print("=== ATTAINABLE MINUS BOOKED (cents), by vertical ===")
    delta_out = {}
    for v in ("question", "sports", "esports", "other"):
        sub = [x for x in recs if x["vert"] == v]
        if not sub:
            continue
        cents = sorted(round((x["ma"] - x["dp"]) * 100.0, 2) for x in sub)
        buckets = collections.Counter()
        for c in cents:
            if c <= 0: buckets["<=0"] += 1
            elif c <= 1: buckets["(0,1]"] += 1
            elif c <= 2: buckets["(1,2]"] += 1
            elif c <= 5: buckets["(2,5]"] += 1
            else: buckets[">5"] += 1
        exact1 = sum(1 for c in cents if abs(c - 1.0) < 1e-9)
        print(f"  {v:9s} n={len(sub):3d} median={cents[len(cents)//2]:6.2f}c  "
              f"exactly +1c={exact1} ({100.0*exact1/len(sub):.0f}%)  buckets={dict(buckets)}")
        delta_out[v] = {"n": len(sub), "median_c": cents[len(cents)//2],
                        "exactly_1c": exact1, "exactly_1c_pct": round(100.0 * exact1 / len(sub), 1),
                        "buckets": dict(buckets)}
    art["attainable_minus_booked_cents"] = delta_out

    # --- Lane split: the stamp is STANDARD-only, so name that explicitly rather than letting a
    # reader take the question cell for the whole book. Two lanes can answer the same question in
    # opposite directions, and the C-200 question read already exists in profit-path-research.py.
    print("=== LANE MIX OF THE STAMPED POPULATION ===")
    lanes = collections.Counter(x["botId"] for x in recs)
    for k, v in lanes.most_common():
        print(f"  {k:20s} n={v}")
    art["lane_mix"] = dict(lanes)
    print("\n=== REACHABILITY BY LANE x VERTICAL (tol 0) ===")
    lane_out = {}
    for lane in sorted(lanes):
        for v in ("question", "sports", "esports", "other"):
            sub = [x for x in recs if x["botId"] == lane and x["vert"] == v]
            if not sub:
                continue
            reach = [x for x in sub if x["ma"] <= x["dp"] + 1e-9]
            s, sr = summarise(sub), summarise(reach)
            lane_out[f"{lane}|{v}"] = {"all": s, "reachable": sr,
                                       "reachability_pct": round(100.0 * len(reach) / len(sub), 1)}
            line(f"{lane[:10]} {v} ALL", s)
            line(f"{lane[:10]} {v} REACH", sr)
    art["lane_x_vertical_tol0"] = lane_out

    # --- Item 2's decision rule, stated as the rule states it -------------------------------
    q = art.get("question_tol 0") or {}
    print("=== ITEM 2 DECISION RULE (question class, tol 0) ===")
    if q.get("all", {}).get("n"):
        r = q["reachable"]
        print(f"  gate: >=60% of question legs reachable at booked, and reachable ROI >= 0")
        print(f"  measured: {q['reachability_pct']}% reachable; reachable ROI "
              f"{r.get('roi_pct')}% on n={r.get('n')} (CI {r.get('ci95')})")
        verdict = ("PASS" if q["reachability_pct"] >= 60 and (r.get("roi_pct") or 0) >= 0
                   else "FAIL")
        art["item2_rule"] = {
            "reachability_pct": q["reachability_pct"],
            "reachable_roi_pct": r.get("roi_pct"),
            "reachable_n": r.get("n"),
            "reachable_ci95": r.get("ci95"),
            "verdict": verdict,
        }
        print(f"  -> {verdict}")
    else:
        art["item2_rule"] = {"verdict": "NO POPULATION"}
        print("  no question-class legs carry both a book stamp and a settled PnL")

    with open(OUT, "w") as fh:
        json.dump(art, fh, indent=1)
    print(f"\nartifact -> {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
