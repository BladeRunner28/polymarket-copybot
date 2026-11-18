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
         simulatedPositionSize, fillStatus, openedAt, closedAt, resolvedAt
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


def table(rows, keyfn, title, minn=8):
    print(f"\n=== {title} ===")
    print(f"{'cell':16s} {'legs':>5s} {'mkts':>5s} {'cost':>9s} {'pnl':>9s} {'roi%':>7s} "
          f"{'win%':>6s} {'be%':>6s} {'ex-top3':>9s}")
    groups = collections.defaultdict(list)
    for r in rows:
        groups[keyfn(r)].append(r)
    out = []
    for k, v in sorted(groups.items(), key=lambda kv: -(sum(x["realizedPnl"] or 0 for x in kv[1]))):
        if len(v) < minn:
            continue
        s = stats(v)
        out.append({"cell": k, **s})
        print(f"{k:16s} {s['n']:5d} {s['markets']:5d} {s['cost']:9.0f} {s['pnl']:9.0f} "
              f"{s['roi_pct'] if s['roi_pct'] is not None else 0:7.1f} "
              f"{s['win_pct']:6.1f} {s['breakeven_win_pct'] or 0:6.1f} {s['ex_top3_pnl']:9.0f}")
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

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(art, fh, indent=1)
    print(f"\nartifact -> {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
