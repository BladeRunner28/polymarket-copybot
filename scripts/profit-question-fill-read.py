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
import math
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

    def attainable_detail(l):
        """(min ask, its mid, its bucket name) across the stamp's lag buckets."""
        b = (l.get("book") or {}).get("byBucket") or {}
        cand = [(v["price"], v.get("mid"), k) for k, v in b.items() if v and v.get("price") is not None]
        if cand:
            return min(cand, key=lambda t: t[0])
        fa = (l.get("book") or {}).get("firstAsk")
        return (fa, None, None) if fa is not None else (None, None, None)

    def min_attainable(l):
        return attainable_detail(l)[0]

    recs = []
    for l in stamped:
        r = rows.get(l["id"])
        if not r:
            continue
        ma, am, _bkt = attainable_detail(l)
        if ma is None:
            continue
        recs.append({
            "id": l["id"],
            "vert": vertical(r["marketId"]),
            "dp": l["decisionPrice"],
            "ma": ma,
            "am": am,
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

    # --- COVERAGE: what share of the class the gate can even see --------------------------------
    # The gate decides a permanent write-off, so it must name the population it was computed on
    # beside the population the claim sits on. The union artifact is the post-corpus STANDARD book;
    # legs without a book stamp are not evidence, they are missing evidence.
    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row

    def dedupe(rows_):
        rows_.sort(key=lambda r: r["openedAt"] or 0)
        seen_, out_ = set(), []
        for r in rows_:
            k = (r["botId"], r["walletAddress"], r["marketId"], r["outcome"])
            if k in seen_:
                continue
            seen_.add(k)
            out_.append(r)
        return out_

    SEL = ("SELECT id,botId,walletAddress,marketId,outcome,entryPrice,realizedPnl,"
           "simulatedPositionSize,status,openedAt FROM PaperTrade "
           "WHERE isDemo=0 AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL ")
    epoch = int((d.get("coverage") or {}).get("l2CorpusEpochMs") or 0)
    pop = dedupe([dict(r) for r in con.execute(SEL + "AND openedAt >= ?", (epoch,))])
    alltime = dedupe([dict(r) for r in con.execute(SEL)])
    con.close()
    qstd = [r for r in pop if vertical(r["marketId"]) == "question" and r["botId"] == "STANDARD"]
    map_path = os.path.join(HERE, "..", "data", "l2-asset-map.jsonl")
    mapped_markets = set()
    if os.path.exists(map_path):
        with open(map_path) as fh:
            for ln in fh:
                try:
                    o = json.loads(ln)
                except ValueError:
                    continue
                if o.get("marketId"):
                    mapped_markets.add(o["marketId"])
    q_mapped_universe = [r for r in qstd if r["marketId"] in mapped_markets]
    stamped_ids = {x["id"] for x in recs}
    q_mapped = [r for r in qstd if r["id"] in stamped_ids]
    c_all = sum(r["simulatedPositionSize"] or 0 for r in qstd)
    p_all = sum(r["realizedPnl"] or 0 for r in qstd)
    c_map = sum(r["simulatedPositionSize"] or 0 for r in q_mapped_universe)
    p_map = sum(r["realizedPnl"] or 0 for r in q_mapped_universe)
    q_at_all = [r for r in alltime if vertical(r["marketId"]) == "question"]
    q_post_all = [r for r in pop if vertical(r["marketId"]) == "question"]
    p_at = sum(r["realizedPnl"] or 0 for r in q_at_all)
    c_at = sum(r["simulatedPositionSize"] or 0 for r in q_at_all)
    p_post = sum(r["realizedPnl"] or 0 for r in q_post_all)
    c_post = sum(r["simulatedPositionSize"] or 0 for r in q_post_all)
    print("=== COVERAGE OF THE QUESTION CLASS (STANDARD, settled, deduped) ===")
    print(f"  post-corpus STANDARD legs: {len(pop)}  question legs: {len(qstd)} "
          f"({100.0*len(qstd)/len(pop):.1f}% of the lane's legs)")
    print(f"  of those, market present in the L2 asset map (adjudicable universe): "
          f"{len(q_mapped_universe)} legs, ${p_map:,.2f} PnL")
    print(f"  carrying a book stamp AND settled: {len(q_mapped)} "
          f"({100.0*len(q_mapped)/len(q_mapped_universe):.1f}% of the adjudicable universe, "
          f"{100.0*len(q_mapped)/len(qstd):.1f}% of the class)")
    print(f"  class PnL, full post-corpus population: ${p_all:,.2f} on ${c_all:,.0f} at risk "
          f"({100.0*p_all/c_all if c_all else 0:.1f}%)")
    print(f"  class PnL, ALL TIME both lanes: ${p_at:,.2f} on ${c_at:,.0f} at risk "
          f"(n={len(q_at_all)})")
    print(f"  class PnL, POST-CORPUS both lanes: ${p_post:,.2f} on ${c_post:,.0f} at risk "
          f"(n={len(q_post_all)}) -> {100.0*(p_at-p_post)/p_at if p_at else 0:.1f}% of the "
          f"all-time headline is pre-corpus")
    for lane, rr in sorted(collections.Counter(r["botId"] for r in q_post_all).items()):
        sub_l = [r for r in q_post_all if r["botId"] == lane]
        print(f"    post-corpus question, {lane}: n={len(sub_l)} "
              f"PnL=${sum(r['realizedPnl'] or 0 for r in sub_l):,.2f} "
              f"cost=${sum(r['simulatedPositionSize'] or 0 for r in sub_l):,.0f}")
    import datetime as _dt
    hist_m = collections.Counter(
        _dt.datetime.utcfromtimestamp((r["openedAt"] or 0) / 1000.0).strftime("%Y-%m")
        for r in q_mapped_universe)
    hist_l = collections.Counter(
        _dt.datetime.utcfromtimestamp((r["openedAt"] or 0) / 1000.0).strftime("%Y-%m")
        for r in q_mapped)
    print(f"  opened-month histogram, adjudicable universe: {dict(sorted(hist_m.items()))}")
    print(f"  opened-month histogram, the 89 stamped:       {dict(sorted(hist_l.items()))}")
    art["coverage_class"] = {
        "post_corpus_standard_legs": len(pop),
        "question_legs": len(qstd),
        "question_share_of_lane_legs_pct": round(100.0*len(qstd)/len(pop), 1),
        "question_legs_in_asset_map": len(q_mapped_universe),
        "question_pnl_in_asset_map": round(p_map, 2),
        "question_legs_mapped_settled": len(q_mapped),
        "question_coverage_pct_of_adjudicable": round(100.0*len(q_mapped)/len(q_mapped_universe), 1)
        if q_mapped_universe else None,
        "question_coverage_pct_of_class": round(100.0*len(q_mapped)/len(qstd), 1) if qstd else None,
        "class_pnl_full": round(p_all, 2),
        "class_cost_full": round(c_all, 2),
        "class_roi_full_pct": round(100.0*p_all/c_all, 1) if c_all else None,
        "class_pnl_mapped": round(sum(r["realizedPnl"] or 0 for r in q_mapped), 2),
        "class_pnl_alltime_both_lanes": round(p_at, 2),
        "class_cost_alltime_both_lanes": round(c_at, 2),
        "class_n_alltime_both_lanes": len(q_at_all),
    }
    print()

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

    # --- EXECUTION-MODEL ARMS -----------------------------------------------------------------
    # The booked level is PaperTrade.entryPrice, the quote STANDARD read at scoring time — the
    # market MID, not an ask. The ask sits on a 1c grid, so (ask - booked) = (ask - mid)
    # half-spread + (mid - booked) booking drift. A tolerance is therefore not a fudge factor:
    # it names WHICH execution model the gate is testing.
    #   tol 0            -> a resting bid at the booked mid must be hit by the ask  (maker)
    #   tick-rounding    -> same, but never reject a leg whose booked level is off the 1c grid
    #                       by construction (tolerance = the leg's own sub-tick remainder)
    #   +1c              -> crossing to the ask, i.e. a TAKER fill at one tick above the mid.
    #                       A taker may not keep the maker's PnL: entry moves from dp to ma,
    #                       so pnl_taker = pnl*dp/ma - cost*(ma-dp)/ma  (constant $ at risk,
    #                       same per-share price path, fewer shares). Cost stays the cost basis.
    print("=== EXECUTION-MODEL ARMS (question class) ===")
    q = [x for x in recs if x["vert"] == "question"]

    def tick_round(dp):
        grid = 0.01
        n = dp / grid
        return (math.ceil(n - 1e-6) * grid) - dp

    def arm(rows_, label):
        s = summarise(rows_)
        line(label, s)
        return s

    arms = {}
    if q:
        with_mid = [x for x in q if x["am"] is not None]
        exact_mid = sum(1 for x in with_mid if abs(x["dp"] - x["am"]) <= 1e-4)
        print(f"  booked level == stamped anchor mid (<=0.01c): {exact_mid}/{len(with_mid)} "
              f"({100.0*exact_mid/len(with_mid) if with_mid else 0:.1f}%)")
        cross = {(dp_mid, at_mid): 0 for dp_mid in (True, False) for at_mid in (True, False)}
        for x in q:
            if x["am"] is None:
                continue
            cross[(abs(x["dp"] - x["am"]) <= 1e-4, x["ma"] <= x["dp"] + 1e-9)] += 1
        print(f"  crosstab booked==mid x reachable-at-tol0: {cross}")
        stale = sorted(round((x["dp"] - x["am"]) * 100.0, 2) for x in q
                       if x["am"] is not None and x["ma"] <= x["dp"] + 1e-9)
        if stale:
            print(f"  tol-0 passes are legs booked ABOVE the prevailing mid: "
                  f"{len(stale)} legs, (booked - anchor mid) median="
                  f"{stale[len(stale)//2]:.2f}c, range {stale[0]:.2f}..{stale[-1]:.2f}c")
        if with_mid:
            hs = sorted(round((x["ma"] - x["am"]) * 100.0, 2) for x in with_mid)
            print(f"  ask - mid (half-spread), cents: median={hs[len(hs)//2]:.2f} "
                  f"min={hs[0]:.2f} max={hs[-1]:.2f}")
        grp_mid = [x for x in q if x["am"] is not None and abs(x["dp"] - x["am"]) <= 1e-4]
        grp_pass = [x for x in q if x["ma"] <= x["dp"] + 1e-9]
        grp_rest = [x for x in q if x["am"] is not None and abs(x["dp"] - x["am"]) > 1e-4
                    and x["ma"] > x["dp"] + 1e-9]
        for gl, g in (("group M booked at the mid", grp_mid),
                      ("group U booked off-mid, never reached", grp_rest),
                      ("group P reached at tol 0", grp_pass)):
            line(gl, summarise(g))
        tick_tols = [tick_round(x["dp"]) for x in q]
        print(f"  leg-level tick tolerance (cents): median={sorted(round(t*100,2) for t in tick_tols)[len(q)//2]:.2f} "
              f"zero for {sum(1 for t in tick_tols if t <= 1e-9)}/{len(q)} legs")

        for label, pred in (
            ("arm A tol 0 (maker at booked mid)",
             lambda x: x["ma"] <= x["dp"] + 1e-9),
            ("arm B tick-rounding (tolerance = sub-tick remainder)",
             lambda x: x["ma"] <= x["dp"] + tick_round(x["dp"]) + 1e-9),
            ("arm C +1c (taker crossing one tick)",
             lambda x: x["ma"] <= x["dp"] + 0.01 + 1e-9),
        ):
            reach = [x for x in q if pred(x)]
            s = arm(reach, label)
            arms[label] = {"reachable": s, "reachability_pct": round(100.0*len(reach)/len(q), 1),
                           "n_legs": len(q)}

        # Taker re-pricing of arm C: pay the ask, keep the same per-share path.
        c_reach = [x for x in q if x["ma"] <= x["dp"] + 0.01 + 1e-9]
        repriced = []
        for x in c_reach:
            dp, ma, c = x["dp"], x["ma"], x["cost"]
            if ma <= 0 or dp <= 0:
                continue
            pnl_t = x["pnl"] * dp / ma - c * (ma - dp) / ma
            repriced.append({"cost": c, "pnl": pnl_t, "market": x["market"], "vert": "question"})
        s = arm(repriced, "arm C' +1c re-priced at the ask (taker PnL)")
        arms["arm C' taker repriced"] = {"reachable": s,
                                        "reachability_pct": arms["arm C +1c (taker crossing one tick)"]["reachability_pct"],
                                        "n_legs": len(q)}
        b_reach = [x for x in q if x["ma"] <= x["dp"] + tick_round(x["dp"]) + 1e-9]
        repriced_b = []
        for x in b_reach:
            dp, ma, c = x["dp"], x["ma"], x["cost"]
            if ma <= 0 or dp <= 0:
                continue
            pnl_t = x["pnl"] * dp / ma - c * (ma - dp) / ma
            repriced_b.append({"cost": c, "pnl": pnl_t, "market": x["market"], "vert": "question"})
        s = arm(repriced_b, "arm B' tick-aligned re-priced at the ask")
        arms["arm B' tick-aligned taker repriced"] = {
            "reachable": s,
            "reachability_pct": arms["arm B tick-rounding (tolerance = sub-tick remainder)"]["reachability_pct"],
            "n_legs": len(q)}
        # B'': price every reachable leg at the ask its OWN booked mid implies (dp + sub-tick
        # remainder), not at the best ask seen in the window. Deterministic, no best-of-window bias.
        repriced_bb = []
        for x in b_reach:
            dp, c = x["dp"], x["cost"]
            f = dp + tick_round(dp)
            if f <= 0 or dp <= 0:
                continue
            pnl_t = x["pnl"] * dp / f - c * (f - dp) / f
            repriced_bb.append({"cost": c, "pnl": pnl_t, "market": x["market"], "vert": "question"})
        s = arm(repriced_bb, "arm B'' tick-aligned, priced at the tick-implied ask")
        arms["arm B'' tick-implied ask"] = {
            "reachable": s,
            "reachability_pct": arms["arm B tick-rounding (tolerance = sub-tick remainder)"]["reachability_pct"],
            "n_legs": len(q)}
        art["execution_model_arms"] = arms
        print()

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
        print(f"  gate: >=60% of question legs reachable at booked, and reachable ROI >= 0 "
              f"[LEGACY tol-0 arm; pre-registered basis is arm B in EXECUTION-MODEL ARMS]")
        print(f"  measured: {q['reachability_pct']}% reachable; reachable ROI "
              f"{r.get('roi_pct')}% on n={r.get('n')} (CI {r.get('ci95')})")
        verdict = ("PASS" if q["reachability_pct"] >= 60 and (r.get("roi_pct") or 0) >= 0
                   else "FAIL")
        art["item2_rule"] = {
            "basis": ("tol 0 at the booked price (LEGACY arm; the pre-registered basis proposed in "
                      "drafts/profit-item2-question-gate-basis-20261123.md is the tick-aligned arm B), "
                      "read this verdict only beside execution_model_arms"),
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
