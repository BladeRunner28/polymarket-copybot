#!/usr/bin/env python3
"""
drift-coblocker-read.py — attribute the drift gate's blocked candidates by their CO-BLOCKERS.

WHY: the drift gate has a sign defect (`Math.abs` at src/lib/scoring/trade.ts:75 rejects prices
BELOW the wallet's entry as "too late"). The favourable cohort is genuinely profitable
(+29.9 % net, n=4,043, CI [+25.8, +34.1]) but **0 of 6,838** field-carrying rows had drift as the
SOLE blocker, so fixing the sign alone admits nothing. The question is no longer "is the sign
wrong" (it is) but "which co-blockers hold the favourable cohort, and is any SUBSET reachable".

This script answers that from `otherRiskKinds` (added 2026-10-20), which records the identities of
the co-blockers rather than just their count.

THE KEY OUTPUT is the "nearest-reachable" table: favourable rows whose ONLY co-blocker is a single
named kind. Those are the candidates a bundle of exactly two changes would admit. Everything else
needs three or more changes and is not a real option.

Run:  .venv-ml/bin/python scripts/drift-coblocker-read.py [--days 7] [--json]
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np

DUST = 0.10
CRYPTO = ["btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "token", "airdrop", "fdv", "market cap"]
POLFIN = ["election", "president", "senate", "congress", "nominee", "parliament", "prime minister",
          "fed", "rate cut", "inflation", "cpi", "gdp", "recession", "tariff", "stock", "nasdaq",
          "s&p", "earnings", "shutdown", "impeach", "poll", "vote", "governor", "mayor"]

# Ordered: first match wins. Each maps a free-text risk string to a stable kind label.
KINDS = [
    ("ttr floor", re.compile(r"resolves in .*< min", re.I)),
    ("confidence", re.compile(r"confidence .*< min", re.I)),
    ("copy score", re.compile(r"copy ?score .*< min", re.I)),
    ("spread", re.compile(r"spread .* > max", re.I)),
    ("liquidity", re.compile(r"liquidity .*< min", re.I)),
    ("wallet score", re.compile(r"wallet score .*< min", re.I)),
    ("near certainty", re.compile(r"near certainty", re.I)),
    ("blacklist category", re.compile(r"blacklist category", re.I)),
    ("band skip", re.compile(r"band skip", re.I)),
    ("per-market cap", re.compile(r"per-market|market cap", re.I)),
    ("per-wallet cap", re.compile(r"wallet .*cap", re.I)),
    ("drift", re.compile(r"price drifted", re.I)),
]


def kind_of(text):
    for label, rx in KINDS:
        if rx.search(text or ""):
            return label
    return "other"


def fee_rate(text):
    t = (text or "").lower()
    if any(w in t for w in CRYPTO):
        return 0.07
    if any(w in t for w in POLFIN):
        return 0.04
    return 0.05


def cluster_ci(pairs, iters=1200, seed=7):
    by = defaultdict(list)
    for m, v in pairs:
        by[m].append(v)
    groups = [np.array(v) for v in by.values() if v]
    if len(groups) < 2:
        return (float(np.mean([x for g in groups for x in g])) if groups else float("nan"), None, None)
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(iters):
        idx = rng.integers(0, len(groups), len(groups))
        means.append(np.concatenate([groups[i] for i in idx]).mean())
    means.sort()
    return (float(np.mean([x for g in groups for x in g])),
            float(means[int(0.025 * len(means))]), float(means[int(0.975 * len(means))]))


def independent(rows):
    """Collapse repeat snapshots of the same position to one row per outcome.

    The shadow instrument writes a candidate row every monitor cycle, so a single
    position can appear 5-6x. Row counts overstate the evidence base: n rows is not
    n independent observations, and the nearest-reachable tables are priced off that
    count. One row per (market, outcome), earliest snapshot kept.
    """
    seen = {}
    for r in sorted(rows, key=lambda r: r.get("ts") or ""):
        seen.setdefault((r["market"], r.get("outcome")), r)
    return list(seen.values())


def summarise(rows, label, indent="  "):
    if not rows:
        print(f"{indent}{label:<40} n=0")
        return None
    m, lo, hi = cluster_ci([(r["market"], r["net"]) for r in rows])
    ci = f"[{lo*100:+.1f}, {hi*100:+.1f}]" if lo is not None else "n/a"
    print(f"{indent}{label:<40} n={len(rows):>5,}  net {m*100:>+7.1f}%  CI {ci}")
    return {"n": len(rows), "net": m, "lo": lo, "hi": hi}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="0 = all rows")
    ap.add_argument("--json", action="store_true", help="emit JSON on stdout")
    args = ap.parse_args()

    cutoff = None
    if args.days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    resol = {}
    recs = []
    with open("data/drift-shadow.jsonl") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("type") == "resolve":
                resol[(r.get("marketId"), r.get("outcome"))] = r.get("value")
            elif r.get("type") == "candidate":
                recs.append(r)

    cands = [r for r in recs if "otherRiskKinds" in r and r.get("otherRiskKinds") is not None]
    if cutoff is not None:
        cands = [r for r in cands if (r.get("ts") or "") >= cutoff.isoformat()[:19]]

    # ERA BOUNDARY (Lane B instrument repair, 2026-11-03). The drift gate became DIRECTIONAL
    # on 2026-10-26 (commit f61fdbe, user-approved): a price BELOW the wallet's entry is no
    # longer a block, so such rows can never be appended to this feed again. The FAVOURABLE
    # arm is therefore STRUCTURALLY empty from that commit on — a zero there is an era
    # boundary, NOT cohort decay, and must never be reported as the cohort shrinking.
    fav_all = [r for r in recs
               if r.get("otherRiskKinds") is not None and r.get("currentPrice") and r.get("walletEntryPrice")
               and r["currentPrice"] < r["walletEntryPrice"] - 1e-12]
    last_fav_ts = max((r.get("ts") or "" for r in fav_all), default="")
    directional_since = "2026-10-26T21:18"  # f61fdbe committed 2026-10-26 16:18 CST
    fav_arm_dead = not any((r.get("ts") or "") >= directional_since for r in fav_all)

    instrument_rows = len(cands)
    settled = 0
    built = []
    for c in cands:
        val = resol.get((c.get("marketId"), c.get("outcome")))
        p = c.get("currentPrice")
        we = c.get("walletEntryPrice")
        if val is None or not p or p <= 0 or p >= 1 or p < DUST or not we:
            continue
        settled += 1
        stake = c.get("stakeUsd") or 10.0
        shares = stake / p
        won = 1 if val in (1, True, "1", "yes", "YES", "true", "True") else 0
        fee_ps = fee_rate(c.get("marketQuestion")) * p * (1 - p)
        cost = stake + shares * fee_ps
        net = (shares * won - cost) / cost
        direction = "favourable" if p < we - 1e-12 else ("adverse" if p > we + 1e-12 else "flat")
        kinds = sorted({kind_of(k) for k in (c.get("otherRiskKinds") or [])})
        kinds = [k for k in kinds if k != "drift"]
        built.append({"market": c.get("marketId"), "outcome": c.get("outcome"), "net": net,
                      "dir": direction, "kinds": kinds, "ts": c.get("ts") or ""})

    out = {"instrumentRows": instrument_rows, "settled": settled}

    if not args.json:
        print("=" * 78)
        print("DRIFT GATE — CO-BLOCKER ATTRIBUTION")
        print("=" * 78)
        print(f"rows carrying otherRiskKinds: {instrument_rows:,}"
              + (f" (last {args.days}d)" if args.days else " (all)"))
        print(f"  settled + ex-dust:          {settled:,}")
        if settled == 0:
            print("\n  No settled rows yet — the instrument began 2026-10-20 and markets must resolve")
            print("  before a counterfactual can be priced. Nothing to attribute. Re-run later.")
            print("=" * 78)
            return 0

    # sole-blocker check: the number that decides whether a sign fix alone does anything
    sole = [r for r in built if len(r["kinds"]) == 0]
    out["soleBlocker"] = len(sole)
    if not args.json:
        print(f"\nSOLE-BLOCKER CHECK (the number that decides if a sign fix alone pays)")
        print(f"  drift was the ONLY blocker: {len(sole):,} of {settled:,} "
              f"({len(sole)/settled*100:.2f}%)")
        if len(sole) == 0:
            print("  => still zero. Fixing the sign alone admits NOTHING. Bundle required.")
        summarise(sole, "sole-blocker cohort")

    # co-blocker frequency by direction
    print_lines = []
    for d in ("favourable", "adverse"):
        rows = [r for r in built if r["dir"] == d]
        freq = Counter(k for r in rows for k in r["kinds"])
        if not args.json:
            print(f"\n{d.upper()} ({len(rows):,} settled rows) — co-blockers by frequency:")
            if d == "favourable" and fav_arm_dead:
                print("    STRUCTURAL ZERO — the drift gate is DIRECTIONAL since 2026-10-26 (f61fdbe):")
                print("    below-entry prices are never blocked, so this arm cannot accrue. Not decay.")
                print(f"    last favourable candidate row on file: {last_fav_ts or 'none'}")
            for k, n in freq.most_common(10):
                print(f"    {k:<22} {n:>5,}  ({n/max(len(rows),1)*100:.1f}% of cohort)")
        out[d] = {"rows": len(rows), "freq": dict(freq)}
    out["favourableArm"] = {"structuralZero": fav_arm_dead, "lastRowTs": last_fav_ts}

    # NEAREST-REACHABLE: favourable rows with exactly ONE co-blocker kind
    fav = [r for r in built if r["dir"] == "favourable"]
    single = defaultdict(list)
    for r in fav:
        if len(set(r["kinds"])) == 1:
            single[r["kinds"][0]].append(r)
    if not args.json:
        print("\nNEAREST-REACHABLE — favourable rows held by exactly ONE other gate:")
        print("  (a bundle of {fix the drift sign + relieve this gate} would admit these)")
        if fav_arm_dead:
            print("    FAVOURABLE-ONLY ARM and structurally empty since 2026-10-26 (directional gate):")
            print("    this table cannot populate from post-change rows. Adverse single-co-blocker")
            print("    bundles are NOT priced here — they are the sole-blocker count above.")
        if not single:
            print("    none yet")
    out["nearestReachable"] = {}
    for k, rows in sorted(single.items(), key=lambda kv: -len(kv[1])):
        s = summarise(rows, f"drift + {k}")
        if s:
            ind = independent(rows)
            s["independentOutcomes"] = len(ind)
            if len(ind) != len(rows):
                si = summarise(ind, f"  same, 1 row per outcome", indent="    ")
                for key in ("n", "net", "lo", "hi"):
                    s[f"ind_{key}"] = si[key] if si else None
                s["independentMarkets"] = len({r["market"] for r in ind})
                if not args.json:
                    print(f"    => {len(rows):,} rows are {len(ind):,} independent outcomes "
                          f"across {s['independentMarkets']:,} markets; n>=100 rule applies to the latter")
        out["nearestReachable"][k] = s

    if not args.json:
        print("\n" + "=" * 78)
        print("READ: a cohort is only actionable if it is reachable. Anything needing three or more")
        print("gate changes is not an option — it is a rewrite of the funnel.")
        print("=" * 78)
    else:
        print(json.dumps(out, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
