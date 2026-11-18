#!/usr/bin/env python3
"""What does Polymarket's 2026-11-20 fee/rebate change cost (or save) this book?

Source of the schedule (read 2026-11-18):
  https://docs.polymarket.com/programs/fee-and-rebate-changes-november-2026.md  (effective 2026-11-20 23:59 UTC)
  https://docs.polymarket.com/trading/fees.md                                    (current, until then)
  https://docs.polymarket.com/programs/maker-rebates.md                          (current distribution)

Fee model, both regimes:  fee$ = shares x feeRate x p x (1-p).
Because cost (dollars at risk) = shares x p, the fee per dollar at risk is simply
feeRate x (1-p) -- no share count needed, and independent of clip size.

Basis: PaperTrade, isDemo=0, status IN ('closed','resolved'), realizedPnl NOT NULL,
dedupe = first leg per (botId, walletAddress, marketId, outcome), clock = openedAt.

Category mapping is the one uncertainty and it is stated per vertical:
  sports / esports  -> 'Sports' 0.05 -> 0.05            (unchanged)
  question          -> politics-non-election 0.04 -> 0.01, and the OTHER/GENERAL floor
                       0.05 -> 0.05 is printed beside it, because a question market could be
                       either. Both readings are shown; neither is assumed.

Read-only. Writes data/fee-schedule-delta.json.
"""
from __future__ import annotations

import collections
import json
import os
import sqlite3

DB = os.path.join(os.path.dirname(__file__), "..", "prisma", "dev.db")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "fee-schedule-delta.json")

# current coefficient -> coefficient from 2026-11-20 23:59 UTC
CUR = {"sports": 0.05, "esports": 0.05, "question_politics": 0.04,
       "question_other": 0.05, "question_election": 0.04}
NEW = {"sports": 0.05, "esports": 0.05, "question_politics": 0.01,
       "question_other": 0.05, "question_election": 0.05}

QUESTION = {"will", "highest", "lowest", "elon"}
ESPORTS = {"cs2", "dota2", "lol", "lec", "val"}
SPORTS = {"ufc", "atp", "swe", "fif", "cbb", "mlb", "col", "ucl", "ere", "unl", "bel1",
          "clf", "us", "bun", "itsb", "por", "lal", "nhl", "wta", "crichundred", "den",
          "mls", "itf", "fl1", "mex", "bra", "elc", "sea", "fifwc", "uel", "arg", "nfl",
          "efl", "wnba", "cfb", "epl"}

BASE = """
WITH legs AS (
  SELECT id, botId, walletAddress, marketId, outcome, entryPrice, realizedPnl,
         simulatedPositionSize, fillStatus, openedAt
  FROM PaperTrade
  WHERE isDemo=0 AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL
    AND simulatedPositionSize > 0 AND entryPrice > 0 AND entryPrice < 1
), dedup AS (
  SELECT *, ROW_NUMBER() OVER (
      PARTITION BY botId, walletAddress, marketId, outcome ORDER BY openedAt) rn
  FROM legs
)
SELECT * FROM dedup WHERE rn=1
"""


def cat(market_id):
    tok = (market_id or "").split("-")[0].lower()
    return tok


def vertical(market_id):
    c = cat(market_id)
    if c in QUESTION:
        return "question"
    if c in ESPORTS:
        return "esports"
    if c in SPORTS:
        return "sports"
    return "other"


def load():
    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(BASE)]
    con.close()
    return rows


def block(rows, label, cur_key, new_key):
    cost = sum(r["simulatedPositionSize"] for r in rows)
    if not cost:
        return None
    # fee$ per dollar at risk = rate x (1-p)
    fee_cur = sum(r["simulatedPositionSize"] * CUR[cur_key] * (1 - r["entryPrice"]) for r in rows)
    fee_new = sum(r["simulatedPositionSize"] * NEW[new_key] * (1 - r["entryPrice"]) for r in rows)
    pnl = sum(r["realizedPnl"] or 0 for r in rows)
    mean_1mp = sum((1 - r["entryPrice"]) for r in rows) / len(rows)
    return {
        "cell": label, "n": len(rows), "cost": round(cost, 2), "pnl": round(pnl, 2),
        "roi_pct": round(100 * pnl / cost, 1),
        "mean_1_minus_p": round(mean_1mp, 3),
        "fee_usd_cur": round(fee_cur, 2), "fee_usd_new": round(fee_new, 2),
        "fee_pct_cur": round(100 * fee_cur / cost, 2),
        "fee_pct_new": round(100 * fee_new / cost, 2),
        "roi_net_cur_pct": round(100 * (pnl - fee_cur) / cost, 1),
        "roi_net_new_pct": round(100 * (pnl - fee_new) / cost, 1),
    }


def main():
    rows = load()
    filled = [r for r in rows if r["fillStatus"] == "filled"]
    print(f"settled deduped legs with a usable price: {len(rows)}  (fill-confirmed {len(filled)})")

    out = {"source_schedule": "docs.polymarket.com/programs/fee-and-rebate-changes-november-2026.md",
           "effective": "2026-11-20T23:59:00Z", "n": len(rows)}

    print("\n=== fee per dollar at risk, current vs 2026-11-20 (coefficient x (1-p)) ===")
    print(f"{'cell':26s} {'n':>5s} {'cost':>8s} {'1-p':>6s} {'fee%C':>6s} {'fee%N':>6s} "
          f"{'roi':>7s} {'netC':>7s} {'netN':>7s}")
    cells = []
    for v, key, nkey in (("question", "question_politics", "question_politics"),
                         ("question", "question_other", "question_other"),
                         ("sports", "sports", "sports"),
                         ("esports", "esports", "esports"),
                         ("other", "question_other", "question_other")):
        sub = [r for r in rows if vertical(r["marketId"]) == v]
        b = block(sub, f"{v} [{key}]", key, nkey)
        if b:
            cells.append(b)
            print(f"{b['cell']:26s} {b['n']:5d} {b['cost']:8.0f} {b['mean_1_minus_p']:6.3f} "
                  f"{b['fee_pct_cur']:6.2f} {b['fee_pct_new']:6.2f} {b['roi_pct']:7.1f} "
                  f"{b['roi_net_cur_pct']:7.1f} {b['roi_net_new_pct']:7.1f}")
    out["by_vertical"] = cells

    # the population that actually decided the loss
    print("\n=== the fill-confirmed class, same arithmetic ===")
    fc = []
    for v in ("question", "sports", "esports", "other"):
        sub = [r for r in filled if vertical(r["marketId"]) == v]
        if len(sub) < 5:
            continue
        key = "question_politics" if v == "question" else ("question_other" if v == "other" else v)
        b = block(sub, f"filled:{v}", key, key)
        fc.append(b)
        print(f"{b['cell']:26s} {b['n']:5d} {b['cost']:8.0f} {b['mean_1_minus_p']:6.3f} "
              f"{b['fee_pct_cur']:6.2f} {b['fee_pct_new']:6.2f} {b['roi_pct']:7.1f} "
              f"{b['roi_net_cur_pct']:7.1f} {b['roi_net_new_pct']:7.1f}")
    out["filled_by_vertical"] = fc

    # maker weighted volume: the new rebate floor is $200k / 30d
    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
    since = con.execute("SELECT strftime('%s','now','-30 days')*1000").fetchone()[0]
    mv = con.execute("""
        SELECT COUNT(*), SUM(simulatedPositionSize*(1-entryPrice))
        FROM PaperTrade
        WHERE isDemo=0 AND openedAt > ? AND simulatedPositionSize > 0
          AND entryPrice > 0 AND entryPrice < 1""", (since,)).fetchone()
    con.close()
    vol = mv[1] or 0.0
    print("\n=== maker weighted-volume floor (new rebate tiers start at $200,000 / 30d) ===")
    print(f"  opened last 30d: {mv[0]} legs, weighted volume ${vol:,.0f}")
    print(f"  multiple of current flow needed to reach the first tier: "
          f"{200000.0 / vol:.1f}x" if vol else "  no volume")
    out["maker_volume_30d"] = {"legs": mv[0], "weighted_usd": round(vol, 2),
                               "multiple_to_first_tier": round(200000.0 / vol, 1) if vol else None}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"\nartifact -> {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
