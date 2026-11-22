#!/usr/bin/env python3
"""Where, if anywhere, does the fill-confirmed book make money?

Question this answers: the all-time headline is positive only because it counts legs that never
traded (unfilled) or were never adjudicated (NULL). On the class we can PROVE we held, the book is
-19.2% C-200 and 0% adjudicated on STANDARD. So before proposing any new rule, find whether a
profitable subpopulation exists at all, and what the loss concentrates in.

Basis (stated because every figure depends on it):
  cost   = PaperTrade.simulatedPositionSize  (DOLLARS AT RISK, not notional)
  pnl    = realizedPnl, status IN ('closed','resolved')  (TR-15 OR)
  dedupe = first leg per (botId, walletAddress, marketId, outcome)
  label  = realizedPnl > 0  (a PnL label, NOT the market outcome)
  clock  = entry vintage (openedAt), never settlement date
  CI     = market-clustered bootstrap, because legs on one market are one bet

Read-only. Writes data/profit-path.json. Changes no rule and no threshold.
"""
from __future__ import annotations

import collections
import json
import os
import random
import re
import sqlite3

DB = os.path.join(os.path.dirname(__file__), "..", "prisma", "dev.db")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "profit-path.json")

BASE = """
WITH legs AS (
  SELECT id, botId, walletAddress, marketId, outcome, entryPrice, realizedPnl,
         simulatedPositionSize, fillStatus, fillResolvedAt, openedAt, closedAt, resolvedAt
  FROM PaperTrade
  WHERE isDemo=0 AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL
), dedup AS (
  SELECT *, ROW_NUMBER() OVER (
      PARTITION BY botId, walletAddress, marketId, outcome ORDER BY openedAt) rn
  FROM legs
)
SELECT * FROM dedup WHERE rn=1
"""


def load():
    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(BASE)]
    con.close()
    return rows


def category(market_id):
    """Market ids are '<category>-<rest>-<date>'; the first token names the vertical."""
    m = re.match(r"^([a-z0-9]+)", (market_id or "").lower())
    return m.group(1) if m else "?"


def band(p):
    if p is None: return "?"
    for lo, hi in ((0.0, 0.1), (0.1, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)):
        if lo <= p < hi:
            return f"{lo:.2f}-{hi:.2f}"
    return "?"


def clip(size):
    if size is None: return "?"
    if size >= 90: return "$100"
    if size >= 40: return "$40-99"
    if size >= 18: return "$18-39"
    return "<$18"


QUESTION = {"will", "highest", "lowest", "elon"}
ESPORTS = {"cs2", "dota2", "lol", "lec", "val"}
SPORTS = {"ufc", "atp", "swe", "fif", "cbb", "mlb", "col", "ucl", "ere", "unl", "bel1",
          "clf", "us", "bun", "itsb", "por", "lal", "nhl", "wta", "crichundred", "den",
          "mls", "itf", "fl1", "mex", "bra", "elc", "sea", "fifwc", "uel", "arg", "nfl",
          "efl", "wnba", "cfb", "epl"}


def vertical(row):
    """Coarse bucket. Question markets are the ones whose ids carry no league token."""
    c = category(row["marketId"])
    if c in QUESTION:
        return "question"
    if c in ESPORTS:
        return "esports"
    if c in SPORTS:
        return "sports"
    return "other"


def hold_bucket(h):
    if h is None: return "?"
    if h < 1: return "<1d"
    if h < 3: return "1-3d"
    if h < 7: return "3-7d"
    if h < 30: return "7-30d"
    return ">30d"


def stats(rows):
    n = len(rows)
    if not n:
        return {"n": 0}
    cost = sum(r["simulatedPositionSize"] or 0 for r in rows)
    pnl = sum(r["realizedPnl"] or 0 for r in rows)
    wins = [r["realizedPnl"] for r in rows if (r["realizedPnl"] or 0) > 0]
    losses = [r["realizedPnl"] for r in rows if (r["realizedPnl"] or 0) <= 0]
    # ex-top-3 PnL: is the cell carried by a few legs?
    ordered = sorted((r["realizedPnl"] or 0 for r in rows), reverse=True)
    ex3 = sum(ordered[3:]) if n > 3 else 0.0
    return {
        "n": n,
        "markets": len({r["marketId"] for r in rows}),
        "wallets": len({r["walletAddress"] for r in rows}),
        "cost": round(cost, 2),
        "pnl": round(pnl, 2),
        "roi_pct": round(100.0 * pnl / cost, 1) if cost else None,
        "win_pct": round(100.0 * len(wins) / n, 1),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "breakeven_win_pct": (round(100.0 * abs(sum(losses) / len(losses)) /
                                   ((sum(wins) / len(wins)) + abs(sum(losses) / len(losses))), 1)
                              if wins and losses else None),
        "ex_top3_pnl": round(ex3, 2),
        "ex_top3_roi_pct": round(100.0 * ex3 / cost, 1) if cost else None,
    }


def cluster_ci(rows, iters=2000, seed=7):
    """Market-clustered bootstrap of ROI: resample MARKETS, not legs."""
    by_market = collections.defaultdict(list)
    for r in rows:
        by_market[r["marketId"]].append(r)
    keys = list(by_market)
    if len(keys) < 5:
        return None
    rng = random.Random(seed)
    out = []
    for _ in range(iters):
        pick = [keys[rng.randrange(len(keys))] for _ in range(len(keys))]
        cost = pnl = 0.0
        for k in pick:
            for r in by_market[k]:
                cost += r["simulatedPositionSize"] or 0
                pnl += r["realizedPnl"] or 0
        if cost:
            out.append(100.0 * pnl / cost)
    out.sort()
    if not out:
        return None
    return [round(out[int(0.025 * len(out))], 1), round(out[int(0.975 * len(out))], 1)]


SUPPRESSED = []


def table(rows, keyfn, title, minn=8):
    """Print one grouped table. Cells with fewer than `minn` legs are NOT printed, which is
    fine as a display choice and a lie as a population claim: on 2026-11-22 the
    FILL-CONFIRMED clip table summed to 299 of 302 legs and $4,506 of $4,676 at risk because
    the 3-leg "$40-99" cell was suppressed, so its rows could not be reconciled with the
    headline ROI. Every suppressed cell is now declared in a footer line and in the artifact
    (art["suppressed_cells"]) so no reader can mistake a table for the whole population."""
    print(f"\n=== {title} ===")
    print(f"{'cell':16s} {'legs':>5s} {'mkts':>5s} {'cost':>9s} {'pnl':>9s} {'roi%':>7s} "
          f"{'win%':>6s} {'be%':>6s} {'ex-top3':>9s}")
    groups = collections.defaultdict(list)
    for r in rows:
        groups[keyfn(r)].append(r)
    out, dropped = [], []
    for k, v in sorted(groups.items(), key=lambda kv: -(sum(x["realizedPnl"] or 0 for x in kv[1]))):
        if len(v) < minn:
            dropped.extend(v)
            continue
        s = stats(v)
        out.append({"cell": k, **s})
        print(f"{k:16s} {s['n']:5d} {s['markets']:5d} {s['cost']:9.0f} {s['pnl']:9.0f} "
              f"{s['roi_pct'] if s['roi_pct'] is not None else 0:7.1f} "
              f"{s['win_pct']:6.1f} {s['breakeven_win_pct'] or 0:6.1f} {s['ex_top3_pnl']:9.0f}")
    shown = stats([r for r in rows])
    if dropped:
        ds = stats(dropped)
        print(f"{'[suppressed]':16s} {ds['n']:5d} {ds['markets']:5d} {ds['cost']:9.0f} "
              f"{ds['pnl']:9.0f} {ds['roi_pct'] if ds['roi_pct'] is not None else 0:7.1f} "
              f"{ds['win_pct']:6.1f} {ds['breakeven_win_pct'] or 0:6.1f} {ds['ex_top3_pnl']:9.0f}"
              f"   (cells below minn={minn}; shown rows are NOT the whole population)")
        SUPPRESSED.append({"table": title, "minn": minn,
                           "suppressed": ds,
                           "population": {"n": shown["n"], "cost": shown["cost"], "pnl": shown["pnl"]}})
    return out


def main():
    rows = load()
    filled = [r for r in rows if r["fillStatus"] == "filled"]
    print(f"settled deduped legs: {len(rows)}   fill-confirmed: {len(filled)}")

    doc = __doc__ or ""
    art = {"basis": (doc.split("Basis")[1].split("Read-only")[0].strip()
                     if "Basis" in doc and "Read-only" in doc else ""),
           "n_all": len(rows), "n_filled": len(filled)}

    art["filled_by_category"] = table(filled, lambda r: category(r["marketId"]),
                                     "FILL-CONFIRMED by market category")
    art["filled_by_band"] = table(filled, lambda r: band(r["entryPrice"]),
                                  "FILL-CONFIRMED by entry price band")
    art["filled_by_clip"] = table(filled, lambda r: clip(r["simulatedPositionSize"]),
                                  "FILL-CONFIRMED by clip size")
    art["all_by_category"] = table(rows, lambda r: category(r["marketId"]),
                                   "ALL SETTLED by market category (incl. unadjudicated)")
    art["all_by_vertical"] = table(rows, vertical, "ALL SETTLED by vertical")
    art["filled_by_vertical"] = table(filled, vertical, "FILL-CONFIRMED by vertical")

    # --- 2026-11-19: is the loss UNIFORM across the filled class, or concentrated in one
    # price cell? The clip table already says the $100 tier carries it; the band table says
    # the sub-0.10 band is 0 wins. Print the CI on every band cell so the cell that is
    # distinguishable from zero is named, not inferred.
    bands = collections.defaultdict(list)
    for r in filled:
        bands[band(r["entryPrice"])].append(r)
    print("\n=== FILL-CONFIRMED by entry band, with market-clustered CI ===")
    band_ci = []
    for k in sorted(bands):
        v = bands[k]
        if len(v) < 10:
            continue
        s, ci = stats(v), cluster_ci(v)
        band_ci.append({"band": k, **s, "ci95": ci})
        print(f"  {k:10s} n={s['n']:4d} cost=${s['cost']:8.0f} roi={s['roi_pct']:7.1f}% "
              f"win={s['win_pct']:5.1f}% be={s['breakeven_win_pct'] or 0:5.1f}% "
              f"ex-top3={s['ex_top3_roi_pct']:6.1f}% CI {ci}")
    art["filled_by_band_ci"] = band_ci

    # Composition of the sub-0.10 cell: is it the $100 clip wearing a price label?
    penny = bands.get("0.00-0.10", [])
    if penny:
        p100 = [r for r in penny if (r["simulatedPositionSize"] or 0) >= 90]
        rest = [r for r in penny if (r["simulatedPositionSize"] or 0) < 90]
        print(f"\n  sub-0.10 composition: n={len(penny)}  $100-clip={len(p100)} "
              f"(${sum(r['simulatedPositionSize'] or 0 for r in p100):.0f})  "
              f"other={len(rest)} (${sum(r['simulatedPositionSize'] or 0 for r in rest):.0f}, "
              f"pnl ${sum(r['realizedPnl'] or 0 for r in rest):.2f})")
        art["penny_cell"] = {"n": len(penny), "n_100clip": len(p100), "n_other": len(rest),
                             "pnl_other": round(sum(r["realizedPnl"] or 0 for r in rest), 2),
                             "prices": sorted(round(r["entryPrice"], 3) for r in penny)}

    # --- 2026-11-19: ADJUDICABILITY CEILING. Item 2 asks for >=60% of the question-market
    # legs to tape out as filled. Two hard bounds sit above that rule: a leg opened before
    # the L2 corpus existed can never be adjudicated, and a leg on a market the recorder never
    # mapped has no book to read either. Print both, so "unadjudicated" is separated from
    # "unadjudicable" instead of being reported as one unmeasured mass.
    L2_EPOCH_MS = 1788180352649  # 2026-08-31T12:45:52Z, the earliest L2 book on disk
    mapped = set()
    map_path = os.path.join(os.path.dirname(__file__), "..", "data", "l2-asset-map.jsonl")
    if os.path.exists(map_path):
        with open(map_path) as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get("marketId"):
                    mapped.add(o["marketId"])
    print(f"\n=== ADJUDICABILITY CEILING (L2 epoch {L2_EPOCH_MS}; asset map {len(mapped)} markets) ===")
    print(f"{'vertical':9s} {'era':5s} {'legs':>5s} {'cost':>8s} {'pnl':>7s} {'adj%':>5s} "
          f"{'mapped%':>7s} {'pnl_provable':>12s}")
    ceilout = []
    for v in ("question", "sports", "esports", "other"):
        for era, pred in (("pre", lambda r: r["openedAt"] < L2_EPOCH_MS),
                          ("post", lambda r: r["openedAt"] >= L2_EPOCH_MS)):
            sub = [r for r in rows if vertical(r) == v and pred(r)]
            if not sub:
                continue
            adj = sum(1 for r in sub if r["fillStatus"] is not None)
            mp = [r for r in sub if r["marketId"] in mapped]
            s = stats(sub)
            prov = round(sum(r["realizedPnl"] or 0 for r in mp), 0)
            ceilout.append({"vertical": v, "era": era, **s, "adjudicated": adj,
                            "adj_pct": round(100.0 * adj / len(sub), 1),
                            "mapped_legs": len(mp),
                            "mapped_pct": round(100.0 * len(mp) / len(sub), 1),
                            "mapped_pnl": prov})
            print(f"{v:9s} {era:5s} {s['n']:5d} ${s['cost']:7.0f} {s['pnl']:+7.0f} "
                  f"{100.0 * adj / len(sub):5.1f} {100.0 * len(mp) / len(sub):7.1f} {prov:+12.0f}")
    art["adjudicability_ceiling"] = ceilout

    # --- 2026-11-19: BOOKING vs VERDICT ORDER. A leg booked before its no-fill verdict
    # existed keeps its PnL; the fill-aware path only zeroes legs it already knows are
    # unfilled. Print the order split, because it decides whether the "measured window" is
    # a book result or a booking artefact. fillResolvedAt is the verdict stamp.
    print("\n=== BOOKING vs VERDICT ORDER (settled, adjudicated) ===")
    order_out = []
    for era, pred in (("pre-oct", lambda r: r["openedAt"] < 1790812800000),
                      ("oct+", lambda r: r["openedAt"] >= 1790812800000)):
        for fs in ("filled", "unfilled"):
            sub = [r for r in rows if pred(r) and r["fillStatus"] == fs]
            if not sub:
                continue
            book_ts = lambda r: r["closedAt"] or r["resolvedAt"] or 0
            late = [r for r in sub if (r.get("fillResolvedAt") or 0) >= book_ts(r)]
            s, sl = stats(sub), stats(late)
            order_out.append({"era": era, "fillStatus": fs, "n": s["n"], "cost": s["cost"],
                              "pnl": s["pnl"], "late_n": sl["n"], "late_pnl": sl.get("pnl")})
            print(f"  {era:8s} {fs:9s} n={s['n']:4d} cost=${s['cost']:8.0f} pnl={s['pnl']:+8.0f}"
                  f"  | verdict-after-booking n={sl['n']:4d} pnl={(sl.get('pnl') or 0):+8.0f}")
    art["booking_vs_verdict"] = order_out




    # Coverage by lane, and by entry vintage -- the number that decides whether a lane's
    # headline PnL is admissible at all. Read straight from PaperTrade, dedupe-free.
    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
    cov = [{"botId": r[0], "n": r[1], "adj": r[2], "filled": r[3]} for r in con.execute("""
        SELECT botId, COUNT(*), SUM(fillStatus IS NOT NULL), SUM(fillStatus='filled')
        FROM PaperTrade WHERE isDemo=0 AND status IN ('closed','resolved')
          AND realizedPnl IS NOT NULL GROUP BY botId""")]
    for c in cov:
        c["coverage_pct"] = round(100.0 * (c["adj"] or 0) / c["n"], 1) if c["n"] else None
    art["coverage_by_lane"] = cov
    print("\n=== FILL-ADJUDICATION COVERAGE by lane (settled legs) ===")
    for c in cov:
        print(f"  {c['botId']:13s} n={c['n']:5d} adjudicated={c['adj'] or 0:5d} "
              f"({c['coverage_pct']}%) filled={c['filled'] or 0}")

    covw = [dict(zip(("botId", "week", "n", "coverage_pct"), r)) for r in con.execute("""
        SELECT botId, strftime('%Y-%m-%d', openedAt/1000, 'unixepoch') wk, COUNT(*),
               ROUND(100.0*SUM(fillStatus IS NOT NULL)/COUNT(*),1)
        FROM PaperTrade WHERE isDemo=0 AND openedAt > (strftime('%s','now','-15 days')*1000)
        GROUP BY botId, wk ORDER BY wk DESC, botId""")]
    art["coverage_recent_by_week"] = covw
    print("\n=== COVERAGE, entry vintage, last 15d ===")
    for c in covw:
        print(f"  {c['week']} {c['botId']:13s} n={c['n']:4d} cov={c['coverage_pct']}%")
    con.close()

    # hold time needs settlement timestamps
    for r in rows:
        ts = r["closedAt"] or r["resolvedAt"]
        r["_hold"] = ((ts - r["openedAt"]) / 86400000.0) if ts and r["openedAt"] else None
    art["filled_by_hold"] = table(filled, lambda r: hold_bucket(r["_hold"]),
                                  "FILL-CONFIRMED by holding time")

    # CI on anything that looks positive in the filled class
    print("\n=== market-clustered 95% CI on FILL-CONFIRMED cells ===")
    ci_out = []
    for label, subset in (("filled:ALL", filled),
                          ("filled:ex-$100-clip",
                           [r for r in filled if (r["simulatedPositionSize"] or 0) < 90]),
                          ("filled:sports", [r for r in filled if vertical(r) == "sports"]),
                          ("filled:sports ex-top3",
                           sorted([r for r in filled if vertical(r) == "sports"],
                                  key=lambda r: -(r["realizedPnl"] or 0))[3:]),
                          ("filled:question", [r for r in filled if vertical(r) == "question"]),
                          ("filled:esports", [r for r in filled if vertical(r) == "esports"])):
        if len(subset) >= 20:
            ci = cluster_ci(subset)
            s = stats(subset)
            ci_out.append({"cell": label, "n": s["n"], "roi_pct": s["roi_pct"], "ci95": ci})
            print(f"  {label:22s} n={s['n']:4d} roi={s['roi_pct']:7.1f}%  CI {ci}")
    art["filled_ci"] = ci_out
    art["suppressed_cells"] = SUPPRESSED

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(art, fh, indent=1)
    print(f"\nartifact -> {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
