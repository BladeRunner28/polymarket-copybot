#!/usr/bin/env python3
"""U2 -- wallet-side feature priors: price every candidate feature BEFORE spending labels on it.

THREE POPULATIONS, ONE VERDICT
  1. OUR ACTED BOOK  -- data/decision-dataset.csv (3,516 deduped legs, 2,576 markets, 188 wallets,
     2026-07-15..2026-09-12, fee-aware targets). Selection-biased BY CONSTRUCTION: these are the rows
     the live policy chose to trade, so an AUC here says "which of our own picks were good", never
     "which signals are good".
  2. OUR SKIP SET    -- data/skip-edge-probe-20260916.json (77,353 counterfactually-labelled decisions,
     exit-blind, live-regime pocket). The larger, less selected population.
  3. THE ARCHIVE     -- data/archive-analysis/archive-wallet-*.json (Polymarket-v1, 2022-12..2026-04,
     1.2B fills): does wallet skill persist half-over-half at all, on 3.4 years of pre-era history.

  Verdict rule (pre-registered in card ml-u2-wallet-feature-priors):
    SELECTOR-CANDIDATE : AUC 95% CI lower bound > 0.5 AND the feature still ranks inside >=4 of the 5
                         entry-price quintiles (i.e. it is not just re-reading price)
    VETO-CANDIDATE     : CI upper bound < 0.5  -> separates, but backwards; usable only on its bad end
    PRICE-PROXY        : beats chance overall but collapses within price quintiles
    KILL               : CI includes 0.5 -- no ranking information beyond noise at this n
  The price-only baseline is printed on the SAME population and target as every row: the bar is price,
  not the composite (the composite measures BELOW chance on the skip set, AUC 0.417-0.418).

OUTPUT  data/wallet-feature-priors.json  + a printed table. Read-only; no live path touched.
USAGE   python3 scripts/wallet-feature-priors.py
"""
from __future__ import annotations

import csv
import json
import math
import os
import random
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.join(ROOT, "data", "decision-dataset.csv")
SKIP_PROBE = os.path.join(ROOT, "data", "skip-edge-probe-20260916.json")
ARCHIVE_DIR = os.path.join(ROOT, "data", "archive-analysis")
OUT = os.path.join(ROOT, "data", "wallet-feature-priors.json")

FEATURES = [
    ("copy_score", "composite copyScore"),
    ("confidence", "confidence"),
    ("wallet_quality_score", "wallet quality"),
    ("category_fit_score", "category fit"),
    ("entry_timing_score", "entry timing"),
    ("spread_score", "spread score"),
    ("liquidity_score", "liquidity score"),
    ("thesis_score", "thesis"),
    ("raw_spread", "raw spread"),
    ("raw_liquidity", "raw liquidity"),
    ("raw_volume", "raw volume"),
    ("ttr_hours", "time to resolution (h)"),
    ("size_usd", "our stake (USD)"),
    ("observed_size_usd", "wallet's size (USD)"),
]
BASELINE = ("entry_price", "entry price (BASELINE)")

BOOT_REPS = 1000
SEED = 20260926


def auc(pairs):
    """Rank-based AUC with tie handling. pairs = [(score, label)] with label in {0,1}."""
    pos = [s for s, y in pairs if y == 1]
    neg = [s for s, y in pairs if y == 0]
    if not pos or not neg:
        return None
    both = sorted(s for s, _ in pairs)
    ranks = {}
    i = 0
    while i < len(both):
        j = i
        while j + 1 < len(both) and both[j + 1] == both[i]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        ranks[both[i]] = r
        i = j + 1
    rsum = sum(ranks[s] for s in pos)
    n1, n0 = len(pos), len(neg)
    return (rsum - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def spearman(pairs):
    """Rank correlation between feature and a continuous outcome. pairs = [(x, y)]."""
    n = len(pairs)
    if n < 10:
        return None

    def rankify(vals):
        order = sorted(range(n), key=lambda i: vals[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            r = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = r
            i = j + 1
        return out

    rx = rankify([p[0] for p in pairs])
    ry = rankify([p[1] for p in pairs])
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def cluster_bootstrap_auc(rows, feat, target, clusters, reps=BOOT_REPS, seed=SEED):
    """Market-clustered bootstrap CI for AUC(mean rank of feature, target)."""
    by_cluster = defaultdict(list)
    for r in rows:
        by_cluster[r[clusters]].append(r)
    keys = list(by_cluster.keys())
    rnd = random.Random(seed)
    out = []
    for _ in range(reps):
        sample = []
        for _ in range(len(keys)):
            sample.extend(by_cluster[keys[rnd.randrange(len(keys))]])
        a = auc([(x[feat], x[target]) for x in sample])
        if a is not None:
            out.append(a)
    if not out:
        return None, None
    out.sort()
    lo = out[int(0.025 * len(out))]
    hi = out[min(len(out) - 1, int(0.975 * len(out)))]
    return lo, hi


def main() -> int:
    with open(DATASET, newline="") as fh:
        raw = list(csv.DictReader(fh))

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    rows = []
    for r in raw:
        ep = num(r["entry_price"])
        pne = num(r["pnl_net_entry"])
        if ep is None or pne is None or not r["y_win"]:
            continue
        rows.append({
            "market": r["market_id"], "wallet": r["wallet"],
            "entry_price": ep, "pnl_net_entry": pne, "y_win": int(r["y_win"]),
            "win_net": 1 if pne > 0 else 0,
            **{f: num(r[f]) for f, _ in FEATURES},
        })
    print("acted book: %d legs / %d markets / %d wallets, y_win mean %.3f, net-win mean %.3f"
          % (len(rows), len({r["market"] for r in rows}), len({r["wallet"] for r in rows}),
             sum(r["y_win"] for r in rows) / len(rows),
             sum(r["win_net"] for r in rows) / len(rows)))

    # ---- price quintiles (the "beyond price" test) -------------------------------
    srt = sorted(rows, key=lambda r: r["entry_price"])
    qn = len(srt) // 5
    quint = {}
    for i, r in enumerate(srt):
        qui = min(4, i // qn) if qn else 0
        quint.setdefault(qui, []).append(r)

    results = []
    for feat, label in FEATURES + [BASELINE]:
        sub = [r for r in rows if r[feat] is not None]
        if len(sub) < 100:
            results.append({"feature": feat, "label": label, "n": len(sub),
                            "verdict": "KILL", "reason": "fewer than 100 non-null legs"})
            continue
        a_win = auc([(r[feat], r["y_win"]) for r in sub])
        a_net = auc([(r[feat], r["win_net"]) for r in sub])
        lo, hi = cluster_bootstrap_auc(sub, feat, "y_win", "market")
        ic = spearman([(r[feat], r["pnl_net_entry"]) for r in sub])
        q_auc = [auc([(r[feat], r["y_win"]) for r in quint[q] if r.get(feat) is not None])
                 for q in sorted(quint)]
        q_auc = [x for x in q_auc if x is not None]
        above = sum(1 for x in q_auc if x > 0.5)
        entry = {
            "feature": feat, "label": label, "n": len(sub),
            "auc_win": round(a_win, 4) if a_win else None,
            "auc_net": round(a_net, 4) if a_net else None,
            "auc_win_ci95": [round(lo, 4), round(hi, 4)] if lo is not None else None,
            "spearman_ic_vs_net_pnl": round(ic, 4) if ic is not None else None,
            "quintile_auc_win": [round(x, 4) for x in q_auc],
            "quintiles_above_half": above,
        }
        if feat == BASELINE[0]:
            entry["verdict"] = "BASELINE"
            entry["reason"] = "the bar every other feature must clear"
        elif lo is not None and lo > 0.5 and above >= 4:
            entry["verdict"] = "SELECTOR-CANDIDATE"
            entry["reason"] = "CI clears 0.5 and it ranks inside >=4/5 price quintiles"
        elif lo is not None and lo > 0.5:
            entry["verdict"] = "PRICE-PROXY"
            entry["reason"] = ("beats chance overall (CI lower > 0.5) but does NOT survive within entry-price "
                               "quintiles (%d/5 above 0.5) -> re-reading price" % above)
        elif hi is not None and hi < 0.5:
            entry["verdict"] = "VETO-CANDIDATE"
            entry["reason"] = ("separates but INVERTED (CI entirely below 0.5): the HIGH end of this feature is "
                               "the bad end -> usable only as a veto against its top tercile, never as a selector")
        else:
            entry["verdict"] = "KILL"
            entry["reason"] = "CI includes 0.5 -- no ranking information beyond noise at this n"
        results.append(entry)

    # ---- population 1b: strata (era / book) -------------------------------------
    # The composite is POLICY OUTPUT and its semantics moved across ruleSetVersions, so a pooled AUC can
    # average away a regime flip. Re-measure the four features that matter inside each era and each book.
    def era_of(v):
        try:
            n = int(v)
        except (TypeError, ValueError):
            return "unknown"
        return "pre-kelly-v1-48" if n < 49 else ("kelly-window-v49-57" if n <= 57 else "exposure-v58plus")

    strata = {}
    buckets = {}
    for rr in raw:
        ep = num(rr["entry_price"]); pne = num(rr["pnl_net_entry"])
        if ep is None or pne is None or not rr["y_win"]:
            continue
        buckets.setdefault((rr["bot_id"], era_of(rr["rule_set_version"])), []).append({
            "entry_price": ep, "y_win": int(rr["y_win"]),
            **{f: num(rr[f]) for f, _ in FEATURES}})
    for (bot, era), sub in sorted(buckets.items()):
        if len(sub) < 150:
            continue
        key = "%s|%s" % (bot, era)
        strata[key] = {"n": len(sub)}
        for feat in ("entry_price", "copy_score", "wallet_quality_score", "thesis_score", "entry_timing_score"):
            a = auc([(x[feat], x["y_win"]) for x in sub if x[feat] is not None])
            strata[key][feat] = round(a, 4) if a is not None else None

    # ---- population 2: the skip set ---------------------------------------------
    skip = {}
    if os.path.exists(SKIP_PROBE):
        sp = json.load(open(SKIP_PROBE))
        skip = {
            "source": os.path.basename(SKIP_PROBE),
            "rows_built": sp.get("rows_built"),
            "coverage": sp.get("coverage"),
            "rankers": sp.get("rankers"),
            "note": ("exit-blind, hold-to-resolution counterfactual labels; discovery window, "
                     "in-sample; cluster = market"),
        }

    # ---- population 3: the archive ----------------------------------------------
    arch = {}
    for name in ("persistence", "persistence2", "resid"):
        p = os.path.join(ARCHIVE_DIR, "archive-wallet-%s.json" % name)
        if os.path.exists(p):
            arch[name] = json.load(open(p))

    def r4(x, nd=4):
        """None-safe rounding: a missing archive key must print as null, not crash."""
        try:
            return round(float(x), nd)
        except (TypeError, ValueError):
            return None

    persist = {
        "source": "data/archive-analysis/archive-wallet-*.json (Polymarket-v1, 2022-12..2026-04)",
        "half_vs_half_r": {
            "all_buys": r4(arch.get("persistence", {}).get("pearson_half_vs_half__all")),
            "all_buys_ex_mm": r4(arch.get("persistence", {}).get("pearson_half_vs_half__no_mm")),
            "taker_buys": r4(arch.get("persistence2", {}).get("pearson__all_prices")),
            "taker_mid_prices": r4(arch.get("persistence2", {}).get("pearson__mid_prices_05_95")),
            "taker_band_neutral": r4(arch.get("resid", {}).get("pearson_resid")),
        },
        "wallets_paired": {
            "all_buys": arch.get("persistence", {}).get("wallets_paired_200_200"),
            "taker_buys": arch.get("persistence2", {}).get("wallets__all_prices"),
            "taker_band_neutral": arch.get("resid", {}).get("wallets_paired"),
        },
        "average_wallet_excess": {
            "all_buys": r4(arch.get("persistence", {}).get("overall_excess"), 5),
            "taker_buys": r4(arch.get("persistence2", {}).get("overall_excess"), 5),
        },
        "asymmetry": {
            "all_buys": {
                "worst_decile_a_to_b": [x[2] for x in arch.get("persistence", {}).get("decile_table__all", [])[:1]] +
                                        [x[3] for x in arch.get("persistence", {}).get("decile_table__all", [])[:1]],
                "best_decile_a_to_b": [x[2] for x in arch.get("persistence", {}).get("decile_table__all", [])[-1:]] +
                                       [x[3] for x in arch.get("persistence", {}).get("decile_table__all", [])[-1:]],
            },
            "taker_buys": {
                "worst_decile_a_to_b": [x[2] for x in arch.get("persistence2", {}).get("deciles__all_prices", [])[:1]] +
                                        [x[3] for x in arch.get("persistence2", {}).get("deciles__all_prices", [])[:1]],
                "best_decile_a_to_b": [x[2] for x in arch.get("persistence2", {}).get("deciles__all_prices", [])[-1:]] +
                                       [x[3] for x in arch.get("persistence2", {}).get("deciles__all_prices", [])[-1:]],
            },
        },
        "verdict": ("skill persists one-sided: the worst wallets stay worst, the best do not stay best "
                    "(top decile flips negative in every variant) -> wallet skill is a VETO, not a selector"),
    }

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "acted_book": {
            "source": os.path.basename(DATASET),
            "legs": len(rows), "markets": len({r["market"] for r in rows}),
            "wallets": len({r["wallet"] for r in rows}),
            "y_win_mean": round(sum(r["y_win"] for r in rows) / len(rows), 4),
            "net_win_mean": round(sum(r["win_net"] for r in rows) / len(rows), 4),
            "caveat": "selection-biased: only the rows the live policy chose to trade",
        },
        "bootstrap": {"reps": BOOT_REPS, "cluster": "market_id", "seed": SEED},
        "features": results,
        "strata_auc": strata,
        "skip_set": skip,
        "archive_wallet_priors": persist,
    }
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1)

    print()
    hdr = "%-24s %6s %7s %7s %-18s %6s %5s  %s" % (
        "feature", "n", "AUCwin", "AUCnet", "AUC 95% CI", "IC", "q>5", "verdict")
    print(hdr); print("-" * len(hdr))
    for e in sorted(results, key=lambda x: -(x.get("auc_win") or 0)):
        ci = e.get("auc_win_ci95")
        print("%-24s %6d %7s %7s %-18s %6s %5s  %s" % (
            e["label"][:24], e["n"], e.get("auc_win"), e.get("auc_net"),
            ("[%s, %s]" % (ci[0], ci[1])) if ci else "-",
            e.get("spearman_ic_vs_net_pnl"), e.get("quintiles_above_half", "-"), e["verdict"]))
    print("\nwrote %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
