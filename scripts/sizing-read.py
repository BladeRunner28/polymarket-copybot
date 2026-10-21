#!/usr/bin/env python3
"""
sizing-read.py — is position SIZE allocated to edge, and which rail actually binds?

WHY THIS EXISTS
The live sizing stack has several ceilings that can bind in different places:
  rule             kellyEnabled=1, kellyFraction=0.5, kellyMaxBankrollPct=0.10,
                   kellyMaxSizeUsd=100, kellyMinBetUsd=2, kellyMinEdgePct=0.02
  BotBankroll      STANDARD min 0.25 / max 20.00 ; BANKROLL_200 min 0.10 / max 30.00
If the BotBankroll max is below the Kelly cap, Kelly's ceiling never binds and the Kelly machinery
may be inert — a ceiling that cannot be reached is not a rail. That is checkable.

The second question is the one the profit review raised and never measured cleanly: does a bigger
clip earn MORE per dollar, or is size uncorrelated with edge? If size does not predict ROI, then
sizing is decoration and the edge lives entirely in selection.

METHOD (matches src/lib/accounting.ts invariants)
  - cost basis is `simulatedPositionSize`, which is DOLLARS. Multiplying it by entryPrice understates
    cost and once inflated a band ROI by ~8x in this repo. Do not repeat that.
  - both `closed` and `resolved` count as realised.
  - dedupe to the FIRST leg per (wallet, market, outcome).
  - CIs cluster by MARKET: legs inside one market share an outcome.

Run: .venv-ml/bin/python scripts/sizing-read.py [--bot BANKROLL_200|STANDARD]
"""

import argparse
import sqlite3
import sys
from collections import defaultdict

import numpy as np

DB = "prisma/dev.db"


def cluster_ci(pairs, iters=1200, seed=7):
    by = defaultdict(list)
    for m, v in pairs:
        by[m].append(v)
    groups = [np.array(v) for v in by.values() if v]
    if len(groups) < 2:
        return (float("nan"), None, None)
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(iters):
        idx = rng.integers(0, len(groups), len(groups))
        means.append(np.concatenate([groups[i] for i in idx]).mean())
    means.sort()
    return (float(np.mean([x for g in groups for x in g])),
            float(means[int(0.025 * len(means))]), float(means[int(0.975 * len(means))]))


def load(bot):
    con = sqlite3.connect(DB)
    q = """
    SELECT walletAddress, marketId, outcome, simulatedPositionSize, realizedPnl, openedAt, status
    FROM PaperTrade
    WHERE botId = ? AND isDemo = 0 AND status IN ('closed','resolved')
      AND simulatedPositionSize > 0
    ORDER BY openedAt ASC
    """
    seen = set()
    rows = []
    for w, m, o, size, pnl, opened, status in con.execute(q, (bot,)):
        k = (w, m, o)
        if k in seen:
            continue
        seen.add(k)
        rows.append({"market": m, "size": float(size), "pnl": float(pnl or 0),
                     "roi": float(pnl or 0) / float(size), "opened": opened, "status": status})
    return rows


def summarise(rows, label, indent="  "):
    if not rows:
        print(f"{indent}{label:<30} n=0")
        return None
    cost = sum(r["size"] for r in rows)
    pnl = sum(r["pnl"] for r in rows)
    m, lo, hi = cluster_ci([(r["market"], r["roi"]) for r in rows])
    ci = f"[{lo*100:+.1f}, {hi*100:+.1f}]" if lo is not None else "n/a"
    print(f"{indent}{label:<30} n={len(rows):>5,}  cost ${cost:>9,.0f}  PnL ${pnl:>9,.2f}  "
          f"ROI {pnl/cost*100:>+6.2f}%  clusterCI {ci}")
    return {"n": len(rows), "cost": cost, "pnl": pnl, "roi": pnl / cost}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default=None)
    args = ap.parse_args()
    bots = [args.bot] if args.bot else ["BANKROLL_200", "STANDARD"]

    print("=" * 92)
    print("SIZING READ — is size allocated to edge, and which rail binds?")
    print("=" * 92)

    con = sqlite3.connect(DB)
    print("\nRAILS AS CONFIGURED")
    for bot, mn, mx in con.execute("SELECT botId,minPositionSize,maxPositionSize FROM BotBankroll"):
        print(f"  {bot:<14} BotBankroll min ${mn:>6.2f}  max ${mx:>6.2f}")
    print("  rules: kellyMaxSizeUsd 100 · kellyMaxBankrollPct 0.10 · kellyMinBetUsd 2")

    for bot in bots:
        rows = load(bot)
        if not rows:
            print(f"\n{bot}: no realised legs")
            continue
        sizes = np.array([r["size"] for r in rows])
        print(f"\n{'=' * 92}\n{bot} — {len(rows):,} realised legs, deduped to first leg per (wallet, market, outcome)")
        print(f"  clip size: p10 ${np.percentile(sizes,10):.2f}  median ${np.median(sizes):.2f}  "
              f"p90 ${np.percentile(sizes,90):.2f}  max ${sizes.max():.2f}  mean ${sizes.mean():.2f}")
        summarise(rows, "all realised legs")

        print("\n  -- ROI by size quintile (does a bigger clip earn more per dollar?) --")
        qs = np.percentile(sizes, [20, 40, 60, 80])
        edges = [0, qs[0], qs[1], qs[2], qs[3], sizes.max() + 1e-9]
        out = []
        for i in range(5):
            sel = [r for r in rows if edges[i] <= r["size"] < edges[i + 1]]
            s = summarise(sel, f"size [${edges[i]:.2f}, ${edges[i+1]:.2f})" if i < 4
                          else f"size >= ${edges[i]:.2f}")
            if s:
                out.append((i, s))
        if len(out) >= 3:
            # rank correlation between quintile index and ROI: +1 = size follows edge
            idx = np.array([o[0] for o in out], dtype=float)
            roi = np.array([o[1]["roi"] for o in out])
            if roi.std() > 0:
                corr = float(np.corrcoef(idx, roi)[0, 1])
                print(f"\n  size-vs-ROI rank correlation across quintiles: {corr:+.3f}")
                print("    +1 = capital concentrated in the best cohorts; 0 = size is decoration;")
                print("    negative = capital allocated INVERSELY to edge (the profit review's claim).")

        print("\n  -- notional allocation vs share of PnL --")
        cost = sum(r["size"] for r in rows)
        pnl = sum(r["pnl"] for r in rows)
        print(f"  total cost ${cost:,.0f}  total PnL ${pnl:,.2f}")

    print("\n" + "=" * 92)
    print("READ: a ceiling nobody reaches is not a rail. If every clip sits at or below the")
    print("BotBankroll max, and that max is far under kellyMaxSizeUsd, then Kelly's size ceiling")
    print("has never bound and sizing is being decided by the bankroll clamp, not by edge.")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
