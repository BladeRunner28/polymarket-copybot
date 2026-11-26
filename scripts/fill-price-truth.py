#!/usr/bin/env python3
"""Is the book overpaying AT THE FILL, and by how many cents?

Every ROI this repo publishes divides PnL by dollars at risk, which mixes two different costs:
what we paid above fair value per share, and how much we staked. This script separates them.

Construction, per leg (natural settlement only, status='resolved'):
    shares  = simulatedPositionSize / entryPrice
    payout  = entryPrice + realizedPnl / shares        (0 or 1 on a natural settlement)
    gap_c   = 100 * (payout - entryPrice)  = the P&L per share, in cents

gap_c > 0  -> we paid LESS than the contract turned out to be worth (good entry)
gap_c < 0  -> we paid MORE  (the adverse-selection / crossed-spread cost, in cents)

ROI on the same leg is gap_c / (100 * entryPrice): a fixed cents cost becomes a bigger
percentage loss the cheaper the contract. This is why the loss concentrates in longshots.

Basis (identical to profit-path-research.py so the two read against each other):
  cost   = PaperTrade.simulatedPositionSize  (dollars at risk, not notional)
  pnl    = realizedPnl, status IN ('closed','resolved')  -- but this script keeps only 'resolved'
  dedupe = first leg per (botId, walletAddress, marketId, outcome)
  clock  = entry vintage (openedAt)
  CI     = market-clustered bootstrap 2000 draws (resample MARKETS, not legs)

Early exits (status='closed') are excluded on purpose: their payout is an exit price, not a
settlement, so the "did the contract turn out worth what we paid" question is not defined on
them. Fees are gross (realizedPnl carries none), so every gap below understates the true cost.

Read-only. Writes data/fill-price-truth.json. Changes no rule and no threshold.
"""
from __future__ import annotations

import collections
import json
import math
import os
import random
import re
import sqlite3

DB = os.path.join(os.path.dirname(__file__), "..", "prisma", "dev.db")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "fill-price-truth.json")

BASE = """
WITH legs AS (
  SELECT id, botId, walletAddress, marketId, outcome, entryPrice, realizedPnl,
         simulatedPositionSize, fillStatus, openedAt, status
  FROM PaperTrade
  WHERE isDemo=0 AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL
    AND entryPrice > 0 AND simulatedPositionSize > 0
), dedup AS (
  SELECT *, ROW_NUMBER() OVER (
      PARTITION BY botId, walletAddress, marketId, outcome ORDER BY openedAt) rn
  FROM legs
)
SELECT * FROM dedup WHERE rn=1
"""

QUESTION = {"will", "highest", "lowest", "elon"}
ESPORTS = {"cs2", "dota2", "lol", "lec", "val"}
SPORTS = {"ufc", "atp", "swe", "fif", "cbb", "mlb", "col", "ucl", "ere", "unl", "bel1",
          "clf", "us", "bun", "itsb", "por", "lal", "nhl", "wta", "crichundred", "den",
          "mls", "itf", "fl1", "mex", "bra", "elc", "sea", "fifwc", "uel", "arg", "nfl",
          "efl", "wnba", "cfb", "epl"}
BANDS = ((0.0, 0.10), (0.10, 0.20), (0.20, 0.40), (0.40, 0.60), (0.60, 0.80), (0.80, 1.01))


def load():
    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(BASE)]
    con.close()
    return rows


def category(market_id):
    m = re.match(r"^([a-z0-9]+)", (market_id or "").lower())
    return m.group(1) if m else "?"


def vertical(row):
    c = category(row["marketId"])
    if c in QUESTION: return "question"
    if c in ESPORTS: return "esports"
    if c in SPORTS: return "sports"
    return "other"


def band(p):
    for lo, hi in BANDS:
        if lo <= p < hi:
            return f"{lo:.2f}-{hi:.2f}"
    return "?"


def clip(size):
    if size >= 90: return "$100"
    if size >= 40: return "$40-99"
    if size >= 18: return "$18-39"
    return "<$18"


def enrich(rows):
    out = []
    for r in rows:
        p = r["entryPrice"]
        size = r["simulatedPositionSize"]
        shares = size / p
        payout = p + (r["realizedPnl"] or 0) / shares
        out.append({**r, "_shares": shares, "_payout": payout,
                    "_gap_c": 100.0 * (payout - p)})
    return out


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def cluster_ci_gap(rows, iters=2000, seed=11):
    """Market-clustered bootstrap of the MEAN gap in cents, dollar-share weighted.

    Weighted by shares so the estimate is '$ per contract', not 'cents per leg' -- a $100 clip
    and a $9 clip are one leg each but very different amounts of exposure to the same overpay.
    """
    by_market = collections.defaultdict(list)
    for r in rows:
        by_market[r["marketId"]].append(r)
    keys = list(by_market)
    if len(keys) < 5:
        return None
    rng = random.Random(seed)
    out = []
    for _ in range(iters):
        num = den = 0.0
        for _ in range(len(keys)):
            k = keys[rng.randrange(len(keys))]
            for r in by_market[k]:
                num += r["_gap_c"] * r["_shares"]
                den += r["_shares"]
        if den:
            out.append(num / den)
    out.sort()
    if not out:
        return None
    return [round(out[int(0.025 * len(out))], 3), round(out[int(0.975 * len(out))], 3)]


def p_at_most(wins, n, p):
    """P(W <= wins) under Binomial(n, p), computed in LOG SPACE.

    The market-clustered bootstrap DEGENERATES when a cell has no wins at all: every resampled
    cluster is 100% loss, so the interval collapses to -price and reads 'CI[-7.7,-5.8]' on a cell
    that is perfectly consistent with fair pricing. This column is the guard: if we cannot reject
    'the price was fair', that cell's ROI is an accounting fact, not an edge estimate.
    """
    if n == 0 or p <= 0 or p >= 1:
        return 1.0
    logs = []
    for k in range(0, min(wins, n) + 1):
        lg = (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
              + k * math.log(p) + (n - k) * math.log1p(-p))
        logs.append(lg)
    m = max(logs)
    return min(1.0, math.exp(m) * sum(math.exp(x - m) for x in logs))


def gap_cents(rows):
    w = sum(r["_shares"] for r in rows)
    return (sum(r["_gap_c"] * r["_shares"] for r in rows) / w, w) if w else (0.0, 0.0)


def block(rows, label, minn=20):
    if len(rows) < minn:
        return None
    w = sum(r["_shares"] for r in rows)
    if not w:
        return None
    gap, _ = gap_cents(rows)
    top3 = sorted(rows, key=lambda r: -((r["_gap_c"] or 0) * r["_shares"]))[3:]
    gap3, _ = gap_cents(top3) if len(top3) >= minn else (0.0, 0.0)
    price = sum(r["entryPrice"] * r["_shares"] for r in rows) / w
    p_ref = sum(r["entryPrice"] for r in rows) / len(rows)   # LEG-mean, the binomial's p
    wins = sum(1 for r in rows if r["_payout"] > 0.5)
    win_rows = [r for r in rows if r["_payout"] > 0.5]
    loss_rows = [r for r in rows if r["_payout"] <= 0.5]
    ci = cluster_ci_gap(rows)
    s = {
        "cell": label, "n": len(rows), "markets": len({r["marketId"] for r in rows}),
        "cost": round(sum(r["simulatedPositionSize"] for r in rows), 2),
        "pnl": round(sum(r["realizedPnl"] or 0 for r in rows), 2),
        "mean_entry": round(price, 4),
        "mean_entry_leg": round(p_ref, 4),
        "gap_cents": round(gap, 3),
        "gap_cents_ex_top3": round(gap3, 3),
        "ci95": ci,
        "roi_pct": round(100.0 * gap / (100.0 * price), 1),
        "wins": wins,
        "win_pct": round(100.0 * wins / len(rows), 1),
        "p_fair": round(p_at_most(wins, len(rows), p_ref), 4),
        # does the book put MORE money on the legs that lose? that is the allocation defect, and
        # it is invisible in a win rate (which is why every win-rate read in this repo is suspect).
        "size_on_wins": round(sum(r["simulatedPositionSize"] for r in win_rows) / len(win_rows), 2)
        if win_rows else None,
        "size_on_losses": round(sum(r["simulatedPositionSize"] for r in loss_rows) / len(loss_rows), 2)
        if loss_rows else None,
        "avg_win_usd": round(sum(r["realizedPnl"] for r in win_rows) / len(win_rows), 2)
        if win_rows else None,
        "avg_loss_usd": round(sum(r["realizedPnl"] for r in loss_rows) / len(loss_rows), 2)
        if loss_rows else None,
    }
    cis = f"CI[{ci[0]:+7.3f},{ci[1]:+7.3f}]" if ci else "CI[  n/a  ]"
    print(f"  {label:26s} n={s['n']:4d} mkts={s['markets']:4d} pr={s['mean_entry']:6.3f} "
          f"gap={s['gap_cents']:+7.3f}c {cis} roi={s['roi_pct']:+6.1f}% "
          f"win={s['win_pct']:5.1f}%/{100*s['mean_entry_leg']:4.1f} p_fair={s['p_fair']:.3f} "
          f"ex3={s['gap_cents_ex_top3']:+7.3f}c size w/l={s['size_on_wins']}/{s['size_on_losses']}")
    return s


def main():
    rows = enrich(load())
    resolved = [r for r in rows if r["status"] == "resolved"]
    filled = [r for r in resolved if r["fillStatus"] == "filled"]
    unfilled = [r for r in resolved if r["fillStatus"] == "unfilled"]
    null = [r for r in resolved if r["fillStatus"] is None]
    print(f"resolved deduped legs={len(resolved)}  filled={len(filled)}  "
          f"unfilled={len(unfilled)}  unadjudicated={len(null)}")

    art = {"basis": __doc__.split("Basis")[1].split("Read-only")[0].strip() if "Basis" in __doc__ else "",
           "n_resolved": len(resolved), "n_filled": len(filled),
           "n_unfilled": len(unfilled), "n_null": len(null)}

    print("\n=== GAP IN CENTS PER CONTRACT, by fill class ===")
    art["by_fill_class"] = [b for b in (
        block(filled, "filled"),
        block(unfilled, "unfilled (never traded)"),
        block(null, "unadjudicated"),
        block(resolved, "ALL resolved"),
    ) if b]

    print("\n=== FILLED, by entry band ===")
    g = collections.defaultdict(list)
    for r in filled:
        g[band(r["entryPrice"])].append(r)
    art["filled_by_band"] = [b for b in (block(g[k], k, minn=10) for k in sorted(g)) if b]

    print("\n=== UNFILLED, by entry band (the counterfactual on the same signals) ===")
    g2 = collections.defaultdict(list)
    for r in unfilled:
        g2[band(r["entryPrice"])].append(r)
    art["unfilled_by_band"] = [b for b in (block(g2[k], k, minn=10) for k in sorted(g2)) if b]

    print("\n=== FILLED, by vertical ===")
    g3 = collections.defaultdict(list)
    for r in filled:
        g3[vertical(r)].append(r)
    art["filled_by_vertical"] = [b for b in (block(g3[k], k, minn=20) for k in sorted(g3)) if b]

    print("\n=== FILLED, by lane ===")
    g4 = collections.defaultdict(list)
    for r in filled:
        g4[r["botId"]].append(r)
    art["filled_by_lane"] = [b for b in (block(g4[k], k, minn=20) for k in sorted(g4)) if b]

    print("\n=== FILLED, by clip ===")
    g5 = collections.defaultdict(list)
    for r in filled:
        g5[clip(r["simulatedPositionSize"])].append(r)
    art["filled_by_clip"] = [b for b in (block(g5[k], k, minn=10) for k in sorted(g5)) if b]

    print("\n=== FILLED, split by HOW the leg ended (natural settlement vs early exit) ===")
    # The natural-settlement basis above is the only one where "what was this contract worth"
    # is defined. Everything excluded from it is an early exit -- and if the excluded legs carry
    # a different sign, the exit logic (not the entry logic) is where the filled loss lives.
    allfilled = [r for r in enrich(load()) if r["fillStatus"] == "filled"]
    gs = collections.defaultdict(list)
    for r in allfilled:
        gs[r["status"]].append(r)
    # and crossed with the clip, because those two cuts are not independent: 5 of the 22 $100
    # clips were closed early, so 'the $100 cap fixes it' and 'the exit path fixes it' are
    # competing explanations for the same dollars and must be separated.
    for st in ("closed", "resolved"):
        for cl in ("$100", "sub-$100"):
            sel = [r for r in gs.get(st, [])
                   if (r["simulatedPositionSize"] >= 90) == (cl == "$100")]
            if len(sel) >= 10:
                gs[f"{st}/{cl}"] = sel
    art["filled_by_exit"] = [b for b in (block(gs[k], k, minn=10) for k in sorted(gs)) if b]

    # THE DECISION NUMBER: does size itself carry the loss, at a controlled price?
    # If size-on-losers > size-on-winners only because of the $100 tier, a cap fixes it. If it
    # holds INSIDE one price band at ordinary clips, the size FORMULA is anti-predictive and a
    # cap only clips its tail.
    print("\n=== FILLED, size quartile inside one price band (controlled) ===")
    ctrl = []
    for lo, hi in ((0.10, 0.40), (0.20, 0.60)):
        sub = [r for r in filled if lo <= r["entryPrice"] < hi]
        if len(sub) < 40:
            continue
        sub.sort(key=lambda r: r["simulatedPositionSize"])
        q = len(sub) // 4
        for i in range(4):
            part = sub[i * q:(i + 1) * q] if i < 3 else sub[3 * q:]
            if len(part) < 8:
                continue
            s = block(part, f"px{lo:.2f}-{hi:.2f} Q{i+1}", minn=8)
            if s:
                s["band"] = f"{lo:.2f}-{hi:.2f}"
                s["quartile"] = i + 1
                ctrl.append(s)
    art["size_quartile_within_band"] = ctrl

    # THE DECISION NUMBER: a price floor. If the gap in cents is roughly constant across
    # bands, then a floor is a statement about the 1/price amplification, not about a class.
    print("\n=== COUNTERFACTUAL: drop the filled legs below a price floor ===")
    cf = []
    for floor in (0.00, 0.10, 0.20, 0.30, 0.40, 0.50):
        sub = [r for r in filled if r["entryPrice"] >= floor]
        if len(sub) < 20:
            continue
        gap = sum(r["_gap_c"] * r["_shares"] for r in sub) / sum(r["_shares"] for r in sub)
        price = sum(r["entryPrice"] * r["_shares"] for r in sub) / sum(r["_shares"] for r in sub)
        cf.append({"floor": floor, "n": len(sub),
                   "kept_cost": round(sum(r["simulatedPositionSize"] for r in sub), 2),
                   "kept_pnl": round(sum(r["realizedPnl"] or 0 for r in sub), 2),
                   "roi_pct": round(100.0 * gap / (100.0 * price), 1),
                   "gap_cents": round(gap, 3), "ci95": cluster_ci_gap(sub)})
        c = cf[-1]
        print(f"  floor {floor:.2f}  n={c['n']:4d} kept_cost=${c['kept_cost']:7.0f} "
              f"kept_pnl={c['kept_pnl']:+8.0f} roi={c['roi_pct']:+6.1f}% "
              f"gap={c['gap_cents']:+6.3f}c CI[{c['ci95'][0]:+7.3f},{c['ci95'][1]:+7.3f}]")
    art["price_floor_counterfactual"] = cf

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(art, fh, indent=1)
    print(f"\nartifact -> {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
