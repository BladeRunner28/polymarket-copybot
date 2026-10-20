#!/usr/bin/env python3
"""
gate-pricing-read.py — price the two gates that reject ~51% of candidate flow.

The funnel last 7d: 10,202 decisions -> 106 copies (1.04%). The two biggest blockers are
`price drifted since entry > max (too late)` (5,470 reason-instances, 26%) and
`confidence N < min N` (5,139, 25%). This script prices both from the counterfactual
instruments that already record them and mark them to settlement:

  data/drift-shadow.jsonl    (candidate rows + resolve rows)
  data/lowconf-shadow.jsonl  (candidate rows + resolve rows)

METHOD
  For each candidate: shares = stake / currentPrice, payout = shares if that OUTCOME resolved
  true else 0, gross PnL = payout - stake. `currentPrice` is the price as detected, i.e. AFTER
  the drift — so the hypothetical honestly pays the drifted price rather than the wallet's.
  Net-of-fee subtracts takerFeePerShare = rate x p x (1-p) per share (the lane trades taker).

  Thresholds are then priced as ADMITTED SETS: "if maxPriceDrift were X, the candidates with
  drift <= X would have been copied, and they returned ..." — that is the decision the change
  would actually make, not the ROI of a bucket.

  CIs cluster by marketId: candidates inside one market share an outcome.

TWO HONESTY GUARDS
  1. Rows shaped by the pre-registered decay bar (2026-09-20) are reported, not overridden.
     That bar decides when a maxPriceDrift relaxation may be brought forward; if it has not
     tripped, a relaxation proposal contradicts a standing pre-registration.
  2. The confidence gate is priced on `confidenceOnly` rows where available, because a
     candidate blocked by confidence AND other gates would not have been copied anyway —
     including it inflates the counterfactual.

Run: .venv-ml/bin/python scripts/gate-pricing-read.py
"""

import json
import sys
from collections import defaultdict

import numpy as np

STAKES = 10.0
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


def pnl_of(c, resolved):
    """(gross_pnl, net_pnl, entry_price) or None if unsettled/degenerate."""
    key_out = c.get("outcome")
    val = resolved.get((c.get("marketId"), key_out))
    if val is None:
        return None
    p = c.get("currentPrice")
    if not p or p <= 0 or p >= 1:
        return None
    stake = c.get("stakeUsd") or STAKES
    shares = stake / p
    won = 1 if (val in (1, True, "1", "yes", "YES", "true", "True")) else 0
    payout = shares * won
    gross = payout - stake
    fee_ps = fee_rate(c.get("marketQuestion")) * p * (1 - p)
    cost = stake + shares * fee_ps
    net = payout - cost
    return gross, net, p, stake, cost


def cluster_ci(rows, key, iters=1200, seed=7):
    """rows: list of (roi) with a parallel market id. Resample MARKETS."""
    by = defaultdict(list)
    for m, v in rows:
        by[m].append(v)
    groups = [np.array(v) for v in by.values() if v]
    if len(groups) < 2:
        return (float(np.mean([v for g in groups for v in g])), None, None)
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(iters):
        idx = rng.integers(0, len(groups), len(groups))
        means.append(np.concatenate([groups[i] for i in idx]).mean())
    means.sort()
    return (float(np.mean([v for g in groups for v in g])),
            float(means[int(0.025 * len(means))]), float(means[int(0.975 * len(means))]))


def summarise(recs, label, indent="  "):
    """recs: list of dicts with market, gross_roi, net_roi, p."""
    if not recs:
        print(f"{indent}{label:<34} n=0")
        return None
    m, lo, hi = cluster_ci([(r["market"], r["net_roi"]) for r in recs], "market")
    gm, glo, ghi = cluster_ci([(r["market"], r["gross_roi"]) for r in recs], "market")
    ci = f"[{lo*100:+.1f}, {hi*100:+.1f}]" if lo is not None else "n/a"
    print(f"{indent}{label:<34} n={len(recs):>6,}  gross {gm*100:>+7.1f}%  net {m*100:>+7.1f}%  CI {ci}")
    return {"n": len(recs), "gross": gm, "net": m, "lo": lo, "hi": hi}


def dedupe(cands):
    """One row per (marketId, outcome, wallet), earliest — the per-signal basis."""
    seen = {}
    for c in cands:
        k = (c.get("marketId"), c.get("outcome"), c.get("wallet"))
        ts = c.get("ts") or ""
        if k not in seen or ts < (seen[k].get("ts") or ""):
            seen[k] = c
    return list(seen.values())


def build(cands, res, field):
    out = []
    for c in dedupe(cands):
        r = pnl_of(c, res)
        if r is None:
            continue
        gross, net, p, stake, cost = r
        out.append({"market": c.get("marketId"), "p": p, "gross_roi": gross / stake,
                    "net_roi": net / cost, "row": c, "field": c.get(field)})
    return out


def main():
    print("=" * 78)
    print("GATE PRICING — drift and confidence, priced as ADMITTED SETS")
    print("=" * 78)

    # ---------------- drift ----------------
    dcands, dres = load("data/drift-shadow.jsonl")
    dall = build(dcands, dres, "drift")
    nodust = [r for r in dall if r["p"] >= DUST]
    print(f"\nDRIFT GATE (maxPriceDrift = 0.004 live)")
    print(f"  candidates {len(dcands):,} | settled {len(dall):,} | ex-dust {len(nodust):,}")
    summarise(dall, "all settled")
    summarise(nodust, "ex-dust (entry >= $0.10)")

    print("\n  -- priced as admitted sets: if maxPriceDrift were X --")
    for x in (0.004, 0.006, 0.008, 0.012, 0.02, 0.05, 99):
        sel = [r for r in nodust if (r["field"] or 0) <= x]
        if not sel:
            continue
        tag = "CURRENT" if x == 0.004 else ("no limit" if x == 99 else f"raise to {x}")
        summarise(sel, f"drift <= {x:<6} ({tag})")

    # incremental: what does each relaxation ADD?
    print("\n  -- what each relaxation ADDS (the marginal cohort) --")
    edges = [(0.004, 0.006), (0.006, 0.008), (0.008, 0.012), (0.012, 0.02), (0.02, 0.05), (0.05, 99)]
    for lo, hi in edges:
        sel = [r for r in nodust if lo < (r["field"] or 0) <= hi]
        lbl = f"drift ({lo}, {hi if hi != 99 else 'inf'}]"
        summarise(sel, lbl)

    # ---------------- confidence ----------------
    lcands, lres = load("data/lowconf-shadow.jsonl")
    lall = build(lcands, lres, "rawConfidence")
    lnd = [r for r in lall if r["p"] >= DUST]
    print(f"\n\nCONFIDENCE GATE (minConfidence = 0.7 live; longshotMinConfidence = 0.55)")
    print(f"  candidates {len(lcands):,} | settled {len(lall):,} | ex-dust {len(lnd):,}")

    only = [r for r in lnd if r["row"].get("confidenceOnly") is True]
    print(f"  confidence-only rows (no other blocker): {len(only):,} of {len(lnd):,}")
    summarise(lnd, "all settled ex-dust")
    summarise(only, "confidence-ONLY ex-dust")

    print("\n  -- priced as admitted sets on confidence-ONLY rows: if minConfidence were X --")
    for x in (0.7, 0.6, 0.55, 0.5, 0.45, 0.4, 0.3, 0.0):
        sel = [r for r in only if (r["field"] or 0) >= x]
        if not sel:
            continue
        tag = "CURRENT" if x == 0.7 else f"lower to {x}"
        summarise(sel, f"conf >= {x:<5} ({tag})")

    print("\n  -- confidence buckets (confidence-ONLY rows) --")
    for lo, hi in [(0.0, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5), (0.5, 0.55), (0.55, 0.7)]:
        sel = [r for r in only if lo <= (r["field"] or 0) < hi]
        summarise(sel, f"conf [{lo}, {hi})")

    # ---------------- pre-registration ----------------
    print("\n" + "=" * 78)
    try:
        s = json.load(open("data/drift-shadow-summary.json"))
        db = s.get("decayBar", {})
        print(f"PRE-REGISTERED DECAY BAR (2026-09-20): threshold ${db.get('thresholdUsd')}/trade, "
              f"{db.get('daysRequired')} consecutive days")
        print(f"  consecutiveDaysAtOrBelow : {db.get('consecutiveDaysAtOrBelow')}")
        print(f"  cohort7d                 : ${db.get('cohort7d')}")
        print(f"  cohortAtOrBelow          : {db.get('cohortAtOrBelow')}")
        print(f"  TRIPPED                  : {db.get('tripped')}")
        if not db.get("tripped"):
            print("  => the standing pre-registration does NOT license a maxPriceDrift relaxation.")
            print("     Any proposal to raise it contradicts that bar and must say so out loud.")
        ps = s.get("decayBarPerSignal", {})
        print(f"  per-signal basis: tripped={ps.get('tripped')} cohort7d=${ps.get('cohort7d')} "
              f"consecDaysAtOrBelow={ps.get('consecutiveDaysAtOrBelow')}")
    except Exception as e:
        print(f"  (could not read decay bar: {e})")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
