#!/usr/bin/env python3
"""measure-category-fit-basis — the class-swap card's measurement half.

WHAT IT ANSWERS: the copy score reads the wallet's win rate in the leg's RAW
event-slug token bucket (WalletProfile.categoryStrengthsJson). The card proposes
swapping that dimension onto the real class (marketCategoryClass / Fine, stamped
at ingest since 2026-09-23). Before any wire-up we owe the measurement: does a
category fit built on the class clear the lane's MDE where the token basis does
not — or is it the same null with prettier bucket names?

SOURCES / WHY:
  - Per-wallet bucket maps come from data/category-fit-source.json, produced by
    scripts/measure-category-fit-source.ts running the SAME adapter call the
    scanner runs (fetchWalletActivity, 30d). The per-category win rate is derived
    from that sample at scan time and never stored, so it cannot be rebuilt from
    SQLite.
  - Every basis is read off THAT ONE FETCH (fresh snapshot), so the comparison
    isolates the BASIS, not the snapshot age. The production token fit as stored
    in WalletProfile is reported beside it as the reference column.
  - The leg's class: ObservedTrade.marketCategoryClass when stamped; otherwise
    the validated Python classifier (scripts/wallet-concentration-test.py::
    classify, the implementation the TS port was parity-checked against) is
    applied to the stored marketId/question — because only rows written after the
    ingest change carry the column, and no backfill has been run.

READ-ONLY: no DB writes, no scoring changes. Legs are settled non-demo PaperTrade
rows in both lanes, exactly as scripts/wallet-selection-score-information.py.

  python3 scripts/measure-category-fit-basis.py

Output: data/category-fit-basis.json
"""

import importlib.util
import json
import os
import sqlite3
import statistics
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = "file:%s?mode=ro" % os.path.join(ROOT, "prisma", "dev.db")
CACHE = os.path.join(ROOT, "data", "category-fit-source.json")
OUT = os.path.join(ROOT, "data", "category-fit-basis.json")

LANES = ["BANKROLL_200", "STANDARD"]
QUINTILES = 5    # same as the information instrument — price is the bar
BOOT_DRAWS = 400

# tokens that are question fragments, not categories (the v45 blacklist axis)
JUNK_TOKENS = {
    "highest", "lowest", "best", "worst", "what", "which", "will", "would",
    "who", "when", "where", "how", "many", "much", "more", "most", "any",
    "all", "new", "first", "next", "last", "this", "that", "than", "the",
    "of", "in", "on", "at", "by", "for", "to", "be", "is", "are", "was",
    "market", "price", "above", "below", "between", "reach", "hit", "end",
    "before", "after", "during", "over", "under", "win", "vs",
}


def load_module(name, filename):
    path = os.path.join(ROOT, "scripts", filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


INFO = load_module("score_info", "wallet-selection-score-information.py")
CONC = load_module("conc_instrument", "wallet-concentration-test.py")
AUC = INFO.auc_np
BOOT = INFO.boot_ci_wallet


def money(x):
    return "${:,.0f}".format(x)


# ------------------------------------------------------------------- loading
def load_market_class():
    """marketId -> (question, token, coarse, fine). Stored class when present,
    classifier otherwise; agreement between the two is reported so the fallback
    is verified on live rows, not assumed."""
    db = sqlite3.connect(DB, uri=True)
    rows = db.execute(
        """SELECT marketId, marketQuestion, marketCategory,
                  marketCategoryClass, marketCategoryFine
           FROM ObservedTrade GROUP BY marketId"""
    ).fetchall()
    db.close()
    out, agree, disagree, stored = {}, 0, 0, 0
    for market_id, question, token, coarse, fine in rows:
        c, f = CONC.classify(market_id, question)
        if coarse:
            stored += 1
            if (coarse, fine) == (c, f):
                agree += 1
            else:
                disagree += 1
        else:
            coarse, fine = c, f
        out[market_id] = (question, token, coarse, fine)
    return out, {"rows": len(rows), "stored_class": stored, "agree": agree,
                 "disagree": disagree}


def load_legs():
    db = sqlite3.connect(DB, uri=True)
    legs = db.execute(
        """SELECT p.botId, p.walletAddress, p.marketId, p.entryPrice,
                  p.simulatedPositionSize, p.realizedPnl, p.status
           FROM PaperTrade p
           WHERE p.isDemo = 0 AND p.status IN ('closed','resolved')
             AND p.realizedPnl IS NOT NULL"""
    ).fetchall()
    wallets = {r[0]: r[1] for r in db.execute(
        "SELECT address, coalesce(categoryStrengthsJson,'{}') FROM WalletProfile WHERE isDemo = 0")}
    db.close()
    return legs, wallets


def fit_from(map_for_wallet, key):
    """Production's read: the wallet's winRate in the bucket for this key."""
    if not key:
        return None
    b = (map_for_wallet or {}).get(key)
    if isinstance(b, dict) and b.get("trades"):
        wr = b.get("winRate")
        if isinstance(wr, (int, float)):
            return float(wr)
    return None


def build_lane(legs, stored_json, cache, markets, lane):
    rows = []
    for (bot, wallet, market_id, price, size, pnl, status) in legs:
        if bot != lane or price is None or wallet not in cache:
            continue
        _q, token, coarse, fine = markets.get(market_id, (None, None, None, None))
        maps = cache[wallet]
        rows.append({
            "wallet": wallet,
            "marketId": market_id,
            "class": coarse,
            "fine": fine,
            "price": float(price),
            "size": float(size or 0.0),
            "pnl": float(pnl),
            "won": 1 if pnl > 0 else 0,
            "status": status,
            "fits": {
                "categoryFit (token, stored)": fit_from(json.loads(stored_json.get(wallet, "{}")), token),
                "categoryFit (token, fresh)": fit_from(maps.get("token"), token),
                "categoryFit (coarse class, fresh)": fit_from(maps.get("coarse"), coarse),
                "categoryFit (fine class, fresh)": fit_from(maps.get("fine"), fine),
            },
        })
    return rows


# ------------------------------------------------------------------ analysis
def analyse(label, rows, fits_key):
    n = len(rows)
    labels = np.array([r["won"] for r in rows], dtype=bool)
    vals = np.array([np.nan if r["fits"][fits_key] is None else r["fits"][fits_key] for r in rows],
                    dtype=np.float64)
    mask = ~np.isnan(vals)
    if mask.sum() < 50 or len(set(vals[mask].tolist())) < 3:
        return {"n_legs": int(mask.sum()), "defined": int(mask.sum()), "auc": None,
                "note": "undefined or too sparse to rank"}
    n_pos, n_neg = int(labels.sum()), int(n - labels.sum())
    mde = CONC.auc_half(n_pos, n_neg) if n_pos and n_neg else float("nan")
    # Bootstrap on the DEFINED subset only, with the wallet clusters remapped to it.
    # (The reference instrument passes the full array including NaNs, and NaN sorts to
    # the top of the score axis, which biases its percentile CI — this one does not.)
    keep_idx = np.where(mask)[0]
    remap = {int(i): k for k, i in enumerate(keep_idx)}
    by_wallet = defaultdict(list)
    for i, r in enumerate(rows):
        if int(i) in remap:
            by_wallet[r["wallet"]].append(remap[int(i)])
    groups = [np.array(v, dtype=np.int64) for v in by_wallet.values() if v]
    a = AUC(vals[mask], labels[mask])
    lo, hi = BOOT(vals[mask], labels[mask], groups)

    order = np.argsort([r["price"] for r in rows], kind="mergesort")
    edges = [order[int(n * k / QUINTILES)] for k in range(1, QUINTILES)]
    quints = defaultdict(list)
    for rank, i in enumerate(order):
        quints[min(QUINTILES - 1, sum(1 for e in edges if rank >= e))].append(i)
    qs = []
    for qi in range(QUINTILES):
        idx = np.array([i for i in quints[qi] if mask[i]], dtype=np.int64)
        if len(idx) < 30:
            continue
        ql = labels[idx]
        if ql.sum() == 0 or ql.sum() == len(ql):
            continue
        qs.append(AUC(vals[idx], ql))
    q_mean = statistics.mean(qs) if qs else float("nan")
    clears = (abs(a - 0.5) > mde) and (lo > 0.5 or hi < 0.5)
    return {"n_legs": n, "defined": int(mask.sum()), "coverage": mask.sum() / n,
            "auc": a, "ci": [lo, hi], "mde": mde, "clears_mde": bool(clears),
            "auc_within_price_quintiles_mean": None if q_mean != q_mean else q_mean}


def stored_structure(wallets_json):
    """The PRODUCTION-side picture: what the token maps stored in WalletProfile look
    like across every non-demo profile (3,201 of them), not just the fetched sample."""
    buckets_per_wallet, total, junk, jtrades, singleton, best_junk, with_map = [], 0, 0, 0, 0, 0, 0
    for raw in wallets_json.values():
        try:
            m = json.loads(raw or "{}")
        except Exception:
            m = {}
        if not isinstance(m, dict):
            m = {}
        if m:
            with_map += 1
        buckets_per_wallet.append(len(m))
        sizes = [b.get("trades", 0) for b in m.values() if isinstance(b, dict)]
        total += sum(sizes)
        singleton += sum(1 for s in sizes if s == 1)
        jt = sum(s for k, s in ((k, b.get("trades", 0)) for k, b in m.items() if isinstance(b, dict))
                 if k.lower() in JUNK_TOKENS)
        jtrades += jt
        junk += 1 if jt else 0
        b, bp = None, -float("inf")
        for k, v in m.items():
            if isinstance(v, dict) and v.get("trades", 0) >= 2 and v.get("pnl", 0) > bp:
                bp, b = v["pnl"], k
        best_junk += bool(b and b.lower() in JUNK_TOKENS)
    n = len(buckets_per_wallet) or 1
    return {
        "profiles": len(buckets_per_wallet),
        "profiles_with_a_category_map": with_map,
        "buckets_per_wallet_median": statistics.median(buckets_per_wallet) if buckets_per_wallet else None,
        "buckets_per_wallet_max": max(buckets_per_wallet) if buckets_per_wallet else None,
        "share_bucket_trades_that_are_singletons": (singleton / total) if total else None,
        "share_trades_in_junk_token_buckets": (jtrades / total) if total else None,
        "wallets_with_any_junk_token_bucket": junk / n,
        "bestCategory_is_a_junk_token_share": best_junk / n,
    }


def structure(cache):
    """Bucket density per basis — the reason a class basis is even proposed."""
    per_basis = {}
    for basis in ("token", "coarse", "fine"):
        buckets_per_wallet, med_sizes, covered, total = [], [], 0, 0
        junk_trades = junk_wallets = 0
        for w in cache.values():
            m = w.get(basis) or {}
            buckets_per_wallet.append(len(m))
            sizes = sorted((b["trades"] for b in m.values()), reverse=True)
            if sizes:
                med_sizes.append(statistics.median(sizes))
                covered += sum(s for s in sizes if s >= 2)
            total += sum(sizes)
            if basis == "token":
                jt = sum(b["trades"] for k, b in m.items() if k.lower() in JUNK_TOKENS)
                junk_trades += jt
                if jt:
                    junk_wallets += 1
        per_basis[basis] = {
            "wallets": len(cache),
            "buckets_per_wallet_median": statistics.median(buckets_per_wallet) if buckets_per_wallet else None,
            "bucket_trades_median": statistics.median(med_sizes) if med_sizes else None,
            "share_trades_in_buckets_ge2": (covered / total) if total else None,
            "share_trades_in_junk_token_buckets": (junk_trades / total) if total and basis == "token" else None,
        }
    # How concentrated is the "strongest category" claim, per basis? (A token best
    # bucket inside a 14-bucket map cannot carry the same meaning as a class best
    # bucket inside a 3-bucket map.) The two bases are different namespaces, so they
    # can never be compared by key equality — compare the mass they carry instead.
    def best(m):
        b, bp = None, -float("inf")
        for k, v in (m or {}).items():
            if v.get("trades", 0) >= 2 and v.get("pnl", 0) > bp:
                bp, b = v["pnl"], k
        return b

    best_share, tjunk, kinds_used = {}, 0, {}
    for basis in ("token", "coarse", "fine"):
        shares, kinds = [], []
        for w in cache.values():
            m = w.get(basis) or {}
            tot = sum(b["trades"] for b in m.values())
            b = best(m)
            if b is not None and tot:
                shares.append(m[b]["trades"] / tot)
                kinds.append(b.lower())
        best_share[basis] = statistics.median(shares) if shares else None
        kinds_used[basis] = kinds
        if basis == "token":
            tjunk = sum(1 for k in kinds if k in JUNK_TOKENS)
    n = len(cache) or 1
    per_basis["bestCategory"] = {
        "median_share_of_wallet_sample_in_best_bucket": best_share,
        "distinct_best_buckets_across_wallets": {k: len(set(v)) for k, v in kinds_used.items()},
        "best_is_a_fragment_token_share": tjunk / n,
    }
    return per_basis


def main():
    if not os.path.exists(CACHE):
        print("missing %s — run: npx tsx scripts/measure-category-fit-source.ts" % CACHE)
        return 1
    blob = json.load(open(CACHE))
    fetched = blob.get("wallets") or {}
    markets, parity = load_market_class()
    legs, stored = load_legs()
    print("cache: %d wallet(s) fetched %s" % (len(fetched), blob.get("generatedAt", "?")[:19]))
    print("class map: %d marketIds | stored class on %d, classifier fallback used on the rest"
          % (parity["rows"], parity["stored_class"]))
    if parity["stored_class"]:
        print("  classifier vs stored class on those rows: %d agree / %d disagree"
              % (parity["agree"], parity["disagree"]))
    print("legs: %d settled non-demo PaperTrade rows (%d wallets with a stored profile)"
          % (len(legs), len(stored)))

    out = {"generatedAt": __import__("datetime").datetime.now().isoformat(),
           "instrument": "scripts/measure-category-fit-basis.py",
           "cache": {"wallets": len(fetched), "generatedAt": blob.get("generatedAt")},
           "class_parity": parity,
           "stored_wallet_profiles": stored_structure(stored),
           "bucket_structure": structure(fetched),
           "lanes": {}}

    ss = out["stored_wallet_profiles"]
    print("\nproduction-side token maps (WalletProfile.categoryStrengthsJson, all non-demo profiles):")
    print("  %d profiles, %d with a map | buckets/wallet median %.0f (max %d) | "
          "singleton buckets %.0f%% of bucket trades"
          % (ss["profiles"], ss["profiles_with_a_category_map"], ss["buckets_per_wallet_median"] or 0,
             ss["buckets_per_wallet_max"] or 0,
             100 * (ss["share_bucket_trades_that_are_singletons"] or 0)))
    print("  trades sitting in question-fragment token buckets: %.1f%% | wallets with any such bucket: "
          "%.1f%% | bestCategory is a fragment token: %.1f%% of wallets"
          % (100 * (ss["share_trades_in_junk_token_buckets"] or 0),
             100 * ss["wallets_with_any_junk_token_bucket"], 100 * ss["bestCategory_is_a_junk_token_share"]))

    print("\nbucket structure (per wallet, from the single fresh fetch):")
    for basis in ("token", "coarse", "fine"):
        s = out["bucket_structure"][basis]
        print("  %-7s buckets/wallet median %5.1f | bucket trades median %5.1f | "
              "trades in buckets >=2: %s"
              % (basis, s["buckets_per_wallet_median"] or 0, s["bucket_trades_median"] or 0,
                 "%.1f%%" % (100 * s["share_trades_in_buckets_ge2"] if s["share_trades_in_buckets_ge2"] else 0)))
    bs = out["bucket_structure"]["bestCategory"]
    print("  strongest-category claim (pnl-max bucket with >=2 trades): median wallet-sample share "
          "token %.1f%% | coarse %.1f%% | fine %.1f%%"
          % (100 * (bs["median_share_of_wallet_sample_in_best_bucket"]["token"] or 0),
             100 * (bs["median_share_of_wallet_sample_in_best_bucket"]["coarse"] or 0),
             100 * (bs["median_share_of_wallet_sample_in_best_bucket"]["fine"] or 0)))
    print("  distinct best buckets across %d wallets: token %d | coarse %d | fine %d | "
          "token best is a question-fragment token in %.1f%% of wallets"
          % (len(fetched), bs["distinct_best_buckets_across_wallets"]["token"],
             bs["distinct_best_buckets_across_wallets"]["coarse"],
             bs["distinct_best_buckets_across_wallets"]["fine"],
             100 * bs["best_is_a_fragment_token_share"]))

    for lane in LANES:
        rows = build_lane(legs, stored, fetched, markets, lane)
        if not rows:
            print("\n%s: no legs with a fetched wallet sample" % lane)
            continue
        labels = np.array([r["won"] for r in rows], dtype=bool)
        n = len(rows)
        n_pos, n_neg = int(labels.sum()), int(n - labels.sum())
        mde = CONC.auc_half(n_pos, n_neg)
        print("\n%s — %d legs / %d wallet-lane pairs | win %d (%.1f%%) | MDE ±%.3f"
              % (lane, n, len({r["wallet"] for r in rows}), n_pos, 100.0 * n_pos / n, mde))
        print("   %-34s %6s %20s %8s %6s %10s" % ("basis (win rate in leg's bucket)", "AUC",
                                                  "95% CI (clustered)", "MDE±", "clears", "cov%"))
        res = {}
        for key in list(rows[0]["fits"].keys()):
            r = analyse(lane, rows, key)
            res[key] = r
            if r.get("auc") is None:
                print("   %-34s %6s %20s %8s %6s %9.0f%%" % (key, "n/a", "(too sparse)", "", "",
                                                              100 * r["coverage"]))
                continue
            print("   %-34s %6.3f [%6.3f, %6.3f] %8.3f %6s %9.0f%%"
                  % (key, r["auc"], r["ci"][0], r["ci"][1], r["mde"],
                     "YES" if r["clears_mde"] else "no", 100 * r["coverage"]))
        # how often does the token bucket even exist while the class bucket does?
        both = sum(1 for r in rows
                   if r["fits"]["categoryFit (token, fresh)"] is not None
                   and r["fits"]["categoryFit (coarse class, fresh)"] is not None)
        token_only = sum(1 for r in rows
                         if r["fits"]["categoryFit (token, fresh)"] is not None
                         and r["fits"]["categoryFit (coarse class, fresh)"] is None)
        class_only = sum(1 for r in rows
                         if r["fits"]["categoryFit (token, fresh)"] is None
                         and r["fits"]["categoryFit (coarse class, fresh)"] is not None)
        moved = sum(1 for r in rows
                    if r["fits"]["categoryFit (token, fresh)"] is not None
                    and r["fits"]["categoryFit (coarse class, fresh)"] is not None
                    and abs(r["fits"]["categoryFit (token, fresh)"]
                            - r["fits"]["categoryFit (coarse class, fresh)"]) > 0.10)
        print("   leg-level fit availability: both %d | token only %d | class only %d | "
              "|ΔwinRate| > 0.10 on %d legs" % (both, token_only, class_only, moved))
        res["_availability"] = {"both": both, "token_only": token_only,
                                "class_only": class_only, "delta_gt_10pp": moved}
        out["lanes"][lane] = res

    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print("\nwrote %s" % OUT)
    print("READ: the class basis only earns the swap if its AUC clears the lane's MDE AND its")
    print("clustered CI excludes 0.5 where the token basis does not. A denser bucket map that")
    print("still ranks at chance is not an improvement — it is the same null with better names.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
