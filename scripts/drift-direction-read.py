#!/usr/bin/env python3
"""
drift-direction-read.py — is the drift gate blocking ADVERSE moves, or does it reject
entries that got CHEAPER?

The live `maxPriceDrift = 0.004` gate rejects a candidate when the price has moved more than
0.4% since the copied wallet's own entry. If that comparison is UNSIGNED, then for a BUY it
blocks entries whose price FELL below what the wallet paid — i.e. it refuses BETTER prices
under the label "too late".

This matters because gate-pricing-read.py found the marginal cohort with the LARGEST drift
(> 5%) to be the MOST profitable (+11.5% net, CI [+7.0, +16.5]). A gate that is supposed to
protect against chasing should not have its best returns in its worst-scoring tail. That
inversion is the signature of a sign error, so this script tests it directly:

    favourable = currentPrice < walletEntryPrice   (BUY got cheaper)
    adverse    = currentPrice > walletEntryPrice   (BUY got dearer — the real "too late")

Run: .venv-ml/bin/python scripts/drift-direction-read.py
"""

import json
import sys
from collections import defaultdict

import numpy as np

DUST = 0.10
CRYPTO = ["btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "token", "airdrop", "fdv", "market cap"]
POLFIN = ["election", "president", "senate", "congress", "nominee", "parliament", "prime minister",
          "fed", "rate cut", "inflation", "cpi", "gdp", "recession", "tariff", "stock", "nasdaq",
          "s&p", "earnings", "shutdown", "impeach", "poll", "vote", "governor", "mayor"]


def fee_rate(text):
    t = (text or "").lower()
    if any(w in t for w in CRYPTO):
        return 0.07
    if any(w in t for w in POLFIN):
        return 0.04
    return 0.05


def load(path):
    cands, res = [], {}
    with open(path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("type") == "candidate":
                cands.append(r)
            elif r.get("type") == "resolve":
                res[(r.get("marketId"), r.get("outcome"))] = r.get("value")
    return cands, res


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
    return (float(np.mean([v for g in groups for v in g])),
            float(means[int(0.025 * len(means))]), float(means[int(0.975 * len(means))]))


def summarise(rows, label):
    if not rows:
        print(f"  {label:<32} n=0")
        return
    m, lo, hi = cluster_ci([(r["market"], r["net"]) for r in rows])
    ci = f"[{lo*100:+.1f}, {hi*100:+.1f}]" if lo is not None else "n/a"
    print(f"  {label:<32} n={len(rows):>6,}  net {m*100:>+7.1f}%  CI {ci}")


def main():
    cands, res = load("data/drift-shadow.jsonl")

    # 1) what IS the drift field?
    n = absd = sig = 0
    for c in cands[:20000]:
        we, cp, d = c.get("walletEntryPrice"), c.get("currentPrice"), c.get("drift")
        if we and cp and d is not None:
            n += 1
            if abs(abs(cp - we) - d) < 1e-9:
                absd += 1
            if abs((cp - we) - d) < 1e-9:
                sig += 1
    print("=== THE DRIFT FIELD ===")
    print(f"  checked {n:,} rows: matches |current-walletEntry| {absd:,} | matches signed {sig:,}")
    print(f"  => drift is {'UNSIGNED (absolute)' if absd > sig else 'signed'}")

    # 2) build settled rows
    seen = {}
    for c in cands:
        k = (c.get("marketId"), c.get("outcome"), c.get("wallet"))
        if k not in seen or (c.get("ts") or "") < (seen[k].get("ts") or ""):
            seen[k] = c
    rows = []
    for c in seen.values():
        val = res.get((c.get("marketId"), c.get("outcome")))
        p = c.get("currentPrice")
        if val is None or not p or p <= 0 or p >= 1 or p < DUST:
            continue
        stake = c.get("stakeUsd") or 10.0
        shares = stake / p
        won = 1 if val in (1, True, "1", "yes", "YES", "true", "True") else 0
        fee_ps = fee_rate(c.get("marketQuestion")) * p * (1 - p)
        net = (shares * won) - (stake + shares * fee_ps)
        cost = stake + shares * fee_ps
        we = c.get("walletEntryPrice")
        if not we:
            continue
        direction = "favourable" if p < we - 1e-12 else ("adverse" if p > we + 1e-12 else "flat")
        rows.append({"market": c.get("marketId"), "net": net / cost, "dir": direction,
                     "drift": c.get("drift") or 0.0, "p": p})

    print(f"\n=== SETTLED, EX-DUST ({len(rows):,} rows) SPLIT BY DIRECTION ===")
    for d in ("favourable", "adverse", "flat"):
        summarise([r for r in rows if r["dir"] == d], f"{d} (current vs wallet entry)")
    summarise(rows, "ALL")

    print("\n=== ADVERSE ONLY: does chase-risk scale with drift? ===")
    adv = [r for r in rows if r["dir"] == "adverse"]
    for lo, hi in [(0, 0.004), (0.004, 0.006), (0.006, 0.01), (0.01, 0.02), (0.02, 0.05), (0.05, 99)]:
        sel = [r for r in adv if lo <= r["drift"] < hi]
        summarise(sel, f"drift [{lo}, {hi})")

    print("\n=== FAVOURABLE ONLY: same buckets ===")
    fav = [r for r in rows if r["dir"] == "favourable"]
    for lo, hi in [(0, 0.004), (0.004, 0.006), (0.006, 0.01), (0.01, 0.02), (0.02, 0.05), (0.05, 99)]:
        sel = [r for r in fav if lo <= r["drift"] < hi]
        summarise(sel, f"drift [{lo}, {hi})")

    print("\n=== THE DECISION THE GATE IS MAKING TODAY ===")
    blocked = rows  # every row here was blocked by the drift gate
    fav_n = sum(1 for r in blocked if r["dir"] == "favourable")
    print(f"  blocked candidates: {len(blocked):,}")
    print(f"    of which FAVOURABLE (would have paid LESS): {fav_n:,} ({fav_n/max(len(blocked),1)*100:.1f}%)")
    print(f"    of which ADVERSE   (genuinely late):        {len(blocked)-fav_n:,} "
          f"({(len(blocked)-fav_n)/max(len(blocked),1)*100:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
