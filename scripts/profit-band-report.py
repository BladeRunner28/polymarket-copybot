#!/usr/bin/env python3
"""
Band-ROI report with market-clustered CIs -- the instrument behind every band claim.

WHY THIS FILE EXISTS: the 2026-10-20 profit review quoted per-band ROIs, market-clustered
CIs and an ex-top-N concentration figure, committed the write-up, and committed NO SCRIPT.
Unreproducible numbers in a review are a Lane B defect, not a stylistic choice -- the first
independent re-run disagreed on two of its three load-bearing claims and was only settled
by writing this.

COST BASIS IS THE TRAP: `PaperTrade.simulatedPositionSize` is DOLLARS at risk (~$10-13 clip),
NOT a share count. Multiplying it by `entryPrice` understates cost on cheap legs and inflated
the 0.0-0.2 band from +47.8% to +407% on the first attempt. Cost = simulatedPositionSize.

Original docstring follows.

Independent reproduction of the profit-review 2026-10-20 band table.

Draft claims (STANDARD, trailing 90d, deduped first leg per bot|wallet|market|outcome,
status in closed|resolved, isDemo=0):
    0.4-0.6  ROI -7.91%  CI [-13.1,-0.2]  n=1076   42.4% of lane notional
    lane     ROI  +2.13%
Anything that matches here was reproduced; anything that doesn't is a claim I should not
let the user act on.
"""
import sqlite3
import time
import numpy as np

DB = "prisma/dev.db"
BOTS = ["STANDARD", "BANKROLL_200"]
BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]


def band_of(p):
    for lo, hi in BANDS:
        if lo <= p < hi:
            return f"{lo:.1f}-{hi:.1f}" if hi <= 1 else "0.8-1.0"
    return None


def load(bot, days=90):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    since = int((time.time() - days * 86400) * 1000)
    rows = con.execute(
        """
        SELECT id, walletAddress, marketId, outcome, entryPrice,
               simulatedPositionSize, realizedPnl, openedAt
        FROM PaperTrade
        WHERE botId=? AND isDemo=0 AND status IN ('closed','resolved')
          AND openedAt >= ?
          AND realizedPnl IS NOT NULL
        ORDER BY openedAt ASC
        """, (bot, since)).fetchall()
    seen = set()
    out = []
    for r in rows:
        k = (r["walletAddress"], r["marketId"], r["outcome"])
        if k in seen:
            continue
        seen.add(k)
        if not r["entryPrice"] or r["entryPrice"] <= 0:
            continue
        # cost basis = DOLLARS at risk. simulatedPositionSize is a dollar clip (~$10-13),
        # not a share count -- multiplying by entryPrice understates cost on cheap legs and
        # inflates their ROI by an order of magnitude (first run printed +407% for 0.0-0.2).
        notional = r["simulatedPositionSize"] or 0
        if notional <= 0:
            continue
        out.append({"market": r["marketId"], "band": band_of(r["entryPrice"]),
                    "px": r["entryPrice"], "notional": notional,
                    "pnl": r["realizedPnl"]})
    return out


def roi(legs):
    n = sum(l["notional"] for l in legs)
    return (sum(l["pnl"] for l in legs) / n * 100) if n else 0.0


def cluster_ci(legs, reps=2000, seed=7):
    """Market-clustered bootstrap of notional-weighted ROI."""
    if not legs:
        return (0.0, 0.0)
    by = {}
    for l in legs:
        by.setdefault(l["market"], []).append(l)
    keys = list(by)
    rng = np.random.default_rng(seed)
    out = np.empty(reps)
    for i in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        s_p = s_n = 0.0
        for j in pick:
            for l in by[keys[j]]:
                s_p += l["pnl"]
                s_n += l["notional"]
        out[i] = (s_p / s_n * 100) if s_n else 0.0
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)))


for bot in BOTS:
    legs = load(bot)
    if not legs:
        print(f"\n{bot}: no legs"); continue
    tot_n = sum(l["notional"] for l in legs)
    print(f"\n=== {bot}  90d deduped: {len(legs)} legs, ${tot_n:,.0f} notional, "
          f"ROI {roi(legs):+.2f}% ===")
    print(f"{'band':9} {'legs':>6} {'notional':>11} {'%ntl':>6} {'ROI%':>8} {'95% CI':>20}")
    for lo, hi in BANDS:
        name = f"{lo:.1f}-{hi:.1f}" if hi <= 1 else "0.8-1.0"
        g = [l for l in legs if l["band"] == name]
        if not g:
            continue
        n_ = sum(l["notional"] for l in g)
        lo_ci, hi_ci = cluster_ci(g)
        print(f"{name:9} {len(g):>6} {n_:>11,.0f} {100*n_/tot_n:>5.1f}% "
              f"{roi(g):>+8.2f} [{lo_ci:>+7.2f},{hi_ci:>+7.2f}]")

# ex-top-10 concentration check on STANDARD+? draft says "the book" 90d deduped
alllegs = load("STANDARD") + load("BANKROLL_200")
alllegs.sort(key=lambda l: -l["pnl"])
for k in (0, 10):
    sub = alllegs[k:]
    n_ = sum(l["notional"] for l in sub)
    print(f"\nALL LANES 90d deduped, ex-top-{k}: {len(sub)} legs, "
          f"${n_:,.0f} notional, ROI {roi(sub):+.2f}% (PnL ${sum(l['pnl'] for l in sub):+,.2f})")
