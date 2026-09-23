#!/usr/bin/env python3
"""
wallet-selection-score-information — READ-ONLY (roadmap card
`wallet-selection-score-information`, 2026-09-23).

QUESTION: how much information do the scores we SELECT wallets with carry about
the outcome of the legs we actually booked? Side finding of the concentration /
thin-record measurements was that at leg grain they read like coin flips
(globalScore 0.497 / 0.496, roi30d 0.496 / 0.426) while the market's own entry
price reads 0.653 / 0.758. This instrument is the full version of that claim:

  * EVERY stored wallet-selection score, per lane (C-200 / STANDARD);
  * AUC against leg outcome, WITH a wallet-clustered bootstrap CI (legs inside a
    wallet are not independent draws — a leg-level interval is too narrow);
  * the Hanley-McNeil minimum detectable AUC at A=0.5 for each lane's leg counts;
  * each score re-measured WITHIN entry-price quintiles, with the price-only AUC
    printed as the bar (both overall and within quintile) — because a score that
    only proxies price adds nothing;
  * the token-based category-fit the copy score currently consumes
    (`categoryStrengthsJson[eventSlug token].winRate`) so the reader can see what
    the category dimension is worth in its present form.

NOT measured here, and deliberately: a class-based category fit. Computing a
wallet's per-category win rate needs the outcome of its RESOLVED activity sample,
which only exists inside the scan (WalletActivityTrade.won) and is not stored.
The class now exists at ingest (src/lib/market-category.ts,
ObservedTrade.marketCategoryClass), so that feature becomes measurable only once
scoring itself derives class strengths — a change, not a measurement.

Measurements gate nothing. One command re-runs everything:
  python3 scripts/wallet-selection-score-information.py
Writes data/wallet-selection-score-information.json.
"""
import importlib.util
import json
import os
import sqlite3
import statistics
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_PATH = os.path.join(ROOT, "prisma", "dev.db")
OUT = os.path.join(ROOT, "data", "wallet-selection-score-information.json")
LANES = ("BANKROLL_200", "STANDARD")
QUINTILES = 5
BOOT_DRAWS = 2000
random_seed = 20260923


def load_conc():
    """Reuse the validated helpers rather than re-deriving them."""
    path = os.path.join(HERE, "wallet-concentration-test.py")
    spec = importlib.util.spec_from_file_location("conc_instrument", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CONC = load_conc()
money = CONC.money


# ------------------------------------------------------------------ estimators
def rankdata(a):
    """Average ranks (scipy-style) — tie-aware, needed because many scores repeat."""
    a = np.asarray(a, dtype=np.float64)
    sorter = np.argsort(a, kind="mergesort")
    inv = np.empty(len(a), dtype=np.int64)
    inv[sorter] = np.arange(len(a))
    sa = a[sorter]
    obs = np.r_[True, sa[1:] != sa[:-1]]
    dense = obs.cumsum()
    count = np.r_[np.nonzero(obs)[0], len(obs)]
    return (0.5 * (count[dense] + count[dense - 1] + 1))[inv]


def auc_np(scores, labels):
    """Rank AUC; nan when one class is empty. Must agree with the pure-Python
    reference in wallet-concentration-test.py (checked at startup)."""
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=bool)
    n_pos = int(labels.sum())
    n_neg = int(len(labels) - n_pos)
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = rankdata(scores)
    rsum = float(ranks[labels].sum())
    return (rsum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def boot_ci_wallet(scores, labels, groups, draws=BOOT_DRAWS, seed=random_seed):
    """Percentile CI resampling the SHARED UNIT (the wallet), not the legs."""
    rng = np.random.default_rng(seed)
    n_wallets = len(groups)
    vals = []
    for _ in range(draws):
        pick = rng.integers(0, n_wallets, n_wallets)
        idx = np.concatenate([groups[p] for p in pick])
        v = auc_np(scores[idx], labels[idx])
        if v == v:
            vals.append(v)
    if len(vals) < 50:
        return (float("nan"), float("nan"))
    vals.sort()
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))])


# ----------------------------------------------------------------------- data
SCORE_COLS = [
    ("globalScore", "globalScore"),
    ("roi30d", "roi30d"),
    ("consistencyScore", "consistencyScore"),
    ("copyabilityScore", "copyabilityScore"),
    ("winRate30d", "winRate30d"),
    ("resolvedTradeCount30d", "resolvedTradeCount30d"),
    ("tradeCount30d", "tradeCount30d"),
    ("oneHitWonderPenalty", "oneHitWonderPenalty"),
    ("averageLiquidity", "averageLiquidity"),
    ("averageSpread", "averageSpread"),
    ("averageEntryTiming", "averageEntryTiming"),
]


def load():
    con = sqlite3.connect("file:%s?mode=ro" % DB_PATH, uri=True)
    legs = con.execute(
        """SELECT p.botId, p.walletAddress, p.marketId, p.entryPrice,
                  p.simulatedPositionSize, p.realizedPnl, p.status
           FROM PaperTrade p
           WHERE p.isDemo = 0 AND p.status IN ('closed','resolved')
             AND p.realizedPnl IS NOT NULL"""
    ).fetchall()
    wallets = {
        r[0]: r
        for r in con.execute(
            """SELECT address, coalesce(globalScore,0), coalesce(roi30d,0),
                      coalesce(consistencyScore,0), coalesce(copyabilityScore,0),
                      coalesce(winRate30d,0), coalesce(resolvedTradeCount30d,0),
                      coalesce(tradeCount30d,0), coalesce(oneHitWonderPenalty,0),
                      coalesce(averageLiquidity,0), coalesce(averageSpread,0),
                      coalesce(averageEntryTiming,0.5), coalesce(categoryStrengthsJson,'{}'),
                      status
               FROM WalletProfile WHERE isDemo = 0"""
        )
    }
    markets = {
        r[0]: (r[1], r[2])
        for r in con.execute("SELECT marketId, marketQuestion, marketCategory FROM ObservedTrade GROUP BY marketId")
    }
    con.close()
    return legs, wallets, markets


def category_fit(cats_json, token):
    """What the copy score reads today: the wallet's win rate in the leg's raw
    event-slug token bucket (WalletProfile.categoryStrengthsJson)."""
    if not token:
        return None
    try:
        d = json.loads(cats_json or "{}")
    except Exception:
        return None
    v = d.get(token)
    if isinstance(v, dict) and isinstance(v.get("winRate"), (int, float)) and v.get("trades"):
        return float(v["winRate"])
    return None


def build_lane(legs, wallets, markets, lane):
    rows = [l for l in legs if l[0] == lane]
    keep, scores = [], defaultdict(list)
    for (_bot, wallet, market_id, price, size, pnl, status) in rows:
        w = wallets.get(wallet)
        if not w or price is None:
            continue
        q, token = markets.get(market_id, (None, None))
        keep.append(
            {
                "wallet": wallet,
                "marketId": market_id,
                "price": float(price),
                "size": float(size or 0.0),
                "pnl": float(pnl),
                "won": 1 if pnl > 0 else 0,
                "status": status,
                "question": q,
                "token": token,
            }
        )
        for i, (label, _col) in enumerate(SCORE_COLS):
            scores[label].append(float(w[1 + i]))
        cf = category_fit(w[12], token)
        scores["categoryFit (token)"].append(float("nan") if cf is None else cf)
        scores["entryPrice"].append(float(price))
    return keep, scores


# -------------------------------------------------------------------- analysis
def analyse(lane, legs, scores):
    n = len(legs)
    labels = np.array([l["won"] for l in legs], dtype=bool)
    n_pos, n_neg = int(labels.sum()), int(n - labels.sum())
    mde = CONC.auc_half(n_pos, n_neg) if n_pos and n_neg else float("nan")
    by_wallet = defaultdict(list)
    for i, l in enumerate(legs):
        by_wallet[l["wallet"]].append(i)
    groups = [np.array(v, dtype=np.int64) for v in by_wallet.values()]

    order = np.argsort([l["price"] for l in legs], kind="mergesort")
    edges = [order[int(n * k / QUINTILES)] for k in range(1, QUINTILES)]
    quints = defaultdict(list)
    for rank, i in enumerate(order):
        quints[min(QUINTILES - 1, sum(1 for e in edges if rank >= e))].append(i)
    qw = int(sum(l["size"] for l in legs)) or 1

    print("\n%s — %d settled legs / %d wallets | win legs %d (%.1f%%) | realized %s | cost %s"
          % (lane, n, len(groups), n_pos, 100.0 * n_pos / n,
             money(sum(l["pnl"] for l in legs)), money(qw)))
    print("   entry price: mean %.3f median %.3f | MDE (Hanley-McNeil, A=0.5, %d pos / %d neg) = ±%.3f"
          % (statistics.mean([l["price"] for l in legs]), statistics.median([l["price"] for l in legs]),
             n_pos, n_neg, mde))
    print("   status split: resolved %d / early-exit closed %d (the exit rule is not neutral: "
          "resolved-only is winner-enriched)"
          % (sum(1 for l in legs if l["status"] == "resolved"), sum(1 for l in legs if l["status"] == "closed")))

    results = {}
    print("\n   %-24s %6s %22s %8s %7s %16s" % ("score (as stored)", "AUC", "95% CI (wallet-clustered)", "MDE±", "clears", "AUC within price quintiles"))
    for label in list(dict.fromkeys([s[0] for s in SCORE_COLS] + ["categoryFit (token)", "entryPrice"])):
        arr = np.array(scores.get(label, []), dtype=np.float64)
        if len(arr) != n:
            continue
        mask = ~np.isnan(arr)
        if mask.sum() < 50 or len(set(arr[mask].tolist())) < 3:
            print("   %-24s %6s %22s %8s %7s %16s" % (label, "n/a", "(constant or too sparse)", "", "", ""))
            continue
        a = auc_np(arr[mask], labels[mask])
        lo, hi = boot_ci_wallet(arr, labels, groups)
        qs = []
        for qi in range(QUINTILES):
            idx = np.array([i for i in quints[qi] if mask[i]], dtype=np.int64)
            if len(idx) < 30:
                continue
            ql = labels[idx]
            if ql.sum() == 0 or ql.sum() == len(ql):
                continue
            qs.append((qi, auc_np(arr[idx], ql), int(ql.sum()), len(idx)))
        q_mean = (statistics.mean([q[1] for q in qs]) if qs else float("nan"))
        clears = (abs(a - 0.5) > mde) and (lo > 0.5 or hi < 0.5)
        print("   %-24s %6.3f [%6.3f, %6.3f] %8.3f %7s %16s"
              % (label, a, lo, hi, mde, "YES" if clears else "no", "%.3f" % q_mean))
        results[label] = {
            "auc": a,
            "ci": [lo, hi],
            "mde": mde,
            "clears_mde": bool(clears),
            "auc_within_price_quintiles_mean": q_mean if q_mean == q_mean else None,
            "per_quintile": [{"quintile": q[0] + 1, "n": q[3], "auc": q[1]} for q in qs],
        }

    print("\n   entry-price quintiles (the bar the scores must beat):")
    for qi in range(QUINTILES):
        idx = np.array(quints[qi], dtype=np.int64)
        ql = labels[idx]
        if len(idx) < 5 or ql.sum() == 0 or ql.sum() == len(ql):
            continue
        print("     q%d  n=%4d  price %.3f-%.3f  win %5.1f%%  realized %10s  AUC(price within) %.3f"
              % (qi + 1, len(idx), min(legs[i]["price"] for i in idx), max(legs[i]["price"] for i in idx),
                 100.0 * ql.sum() / len(idx), money(sum(legs[i]["pnl"] for i in idx)),
                 auc_np(np.array([legs[i]["price"] for i in idx]), ql)))
    return {"n_legs": n, "n_wallets": len(groups), "n_pos": n_pos, "n_neg": n_neg, "mde": mde, "scores": results}


def main():
    rng = np.random.default_rng(1)
    for _ in range(3):
        s = rng.normal(size=200)
        lb = [rng.random() > 0.5 for _ in range(200)]
        assert abs(auc_np(s, lb) - CONC.auc(list(s), lb)) < 1e-9, "numpy AUC disagrees with the reference implementation"
    print("estimator check: numpy AUC == pure-Python ranked AUC on 3 random draws (tie handling included)")

    legs, wallets, markets = load()
    print("loaded %d settled legs and %d wallet profiles (%d distinct marketIds for category lookup)"
          % (len(legs), len(wallets), len(markets)))

    out = {"generatedAt": __import__("datetime").datetime.now().isoformat(),
           "instrument": "scripts/wallet-selection-score-information.py",
           "note": "AUC on 'leg won'; AUC is not EV. Wallet-level scores are as-of-print snapshots.",
           "lanes": {}}
    for lane in LANES:
        lane_legs, scores = build_lane(legs, wallets, markets, lane)
        if not lane_legs:
            continue
        out["lanes"][lane] = analyse(lane, lane_legs, scores)

    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print("\nwrote %s" % OUT)
    print("\nREAD: a score 'clears' only if its AUC is further than the lane's MDE from 0.5 AND its")
    print("wallet-clustered CI excludes 0.5. AUC on leg outcome is not EV (the book profits at ~50%")
    print("win rate because winners and losers are not the same size), and the wallet sample only")
    print("contains wallets that already cleared every gate — this is a measurement, not a licence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
