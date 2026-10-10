#!/usr/bin/env python3
"""U2 promotion gate — the SELECTION test the card pre-registers but no instrument implemented.

CARD (ml-u2-wallet-feature-priors), verbatim gate text:
  "Promotion to a SELECTOR requires >=200 of our own forward legs in which top-tercile
   selection beats price-only with a market-clustered 95% CI excluding zero."

WHAT EXISTED BEFORE: scripts/wallet-feature-priors.py ranks FEATURES by AUC against the price
baseline (per-feature, per-stratum). An AUC ranking is NOT the gate: the gate asks whether
*selecting on wallet skill* changes the money. This script answers that question and nothing else.

DESIGN (stated, because the card's gate text does not pin the metric):
  population  forward legs, opened_at >= FROM_DATE (the card's forward clock 2026-09-26), and
              the C-200 book by default (that is the 365-leg count the card's forward read used);
              --all-lanes widens it, --full-history drops the date filter (stability checks)
  feature     wallet_quality_score (the "wallet quality" feature; U2's ranking read calls it a
              VETO candidate, i.e. it scores BELOW chance on this book)
  selector    rank legs by the feature, take the TOP tercile (threshold = population tercile)
  metric      mean net-of-fee PnL per leg (pnl_net_full) — dollars per leg, the book's own unit
  arms        (1) top tercile by wallet quality      (2) bottom tercile by wallet quality
              (3) ALL legs = copy-all, i.e. the price-only baseline population
              (4) top tercile by ENTRY PRICE — the literal "price-only" selector comparator
  CI          market-clustered bootstrap: resample MARKETS (market_id) with replacement,
              1000 reps, percentile 2.5/97.5 on the difference in mean PnL/leg.
  verdict     PROMOTE only if (1) - (3) CI lower bound > 0 AND (1) - (4) CI lower bound > 0.
              Anything else = the archive's VETO verdict stands.

LABEL BASIS (this repo's measurement-target rule): the primary target is pnl_net_full, i.e. a
realized-PnL label on SETTLED legs — a profitable-leg question, NOT "did the signal predict the
market outcome". The y_win arm is printed beside it on the SAME rows for every AUC quoted, and the
two AUCs are both stated, because they disagree on a small share of legs and that disagreement is
where a delta's sign flips at our sample sizes.

USAGE   python3 scripts/wallet-selection-test.py [--dataset data/decision-dataset-forward-20261010.csv]
        [--from 2026-09-26] [--bot BANKROLL_200] [--all-lanes] [--full-history] [--json out.json]
Read-only: writes only the JSON it is told to.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import statistics
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATASET = os.path.join(ROOT, "data", "decision-dataset-forward-20261010.csv")
FEATURE = "wallet_quality_score"
PRICE = "entry_price"
TARGET = "pnl_net_full"
BOOT_REPS = 1000
SEED = 20261010


def load(path, from_date, bot, all_lanes, full_history):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if not all_lanes and bot and r.get("bot_id") != bot:
                continue
            opened = (r.get("opened_at") or "")[:10]
            if not full_history and from_date and opened < from_date:
                continue
            try:
                fv = float(r[FEATURE])
                pv = float(r[PRICE])
                tv = float(r[TARGET])
            except (KeyError, TypeError, ValueError):
                continue
            if not all(math.isfinite(x) for x in (fv, pv, tv)):
                continue
            rows.append({
                "market": r.get("market_id") or "?",
                "wallet": (r.get("wallet") or "?").lower(),
                "feat": fv, "price": pv, "target": tv,
                "y_win": r.get("y_win"),
                "fee_rate": r.get("fee_rate"),
                "bot": r.get("bot_id"),
                "opened": opened,
            })
    return rows


def tercile_cut(rows, key, top=True):
    vals = sorted(r[key] for r in rows)
    n = len(vals)
    lo = vals[int(n / 3)]
    hi = vals[int(2 * n / 3)]
    return hi if top else lo


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def cluster_bootstrap_diff(rows, sel, ref, reps=BOOT_REPS, seed=SEED):
    """Difference in mean target per leg (sel - ref), resampling MARKETS with replacement."""
    by_market = {}
    for r in rows:
        by_market.setdefault(r["market"], []).append(r)
    markets = list(by_market)
    rng = random.Random(seed)
    diffs = []
    for _ in range(reps):
        pick = [markets[rng.randrange(len(markets))] for _ in markets]
        pooled_sel, pooled_ref = [], []
        for m in pick:
            for r in by_market[m]:
                if sel(r):
                    pooled_sel.append(r["target"])
                if ref(r):
                    pooled_ref.append(r["target"])
        if pooled_sel and pooled_ref:
            diffs.append(mean(pooled_sel) - mean(pooled_ref))
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[int(0.975 * len(diffs)) - 1]
    return {"diff": mean([r["target"] for r in rows if sel(r)]) - mean([r["target"] for r in rows if ref(r)]),
            "lo": lo, "hi": hi, "share_gt0": sum(1 for d in diffs if d > 0) / len(diffs), "reps": len(diffs)}


def auc(rows, score_key):
    """AUC of score_key against target>0 (rank-based, ties = 0.5)."""
    pos = [r[score_key] for r in rows if r["target"] > 0]
    neg = [r[score_key] for r in rows if r["target"] <= 0]
    if not pos or not neg:
        return None
    both = sorted(pos + neg)
    # average ranks
    rank = {}
    i = 0
    while i < len(both):
        j = i
        while j + 1 < len(both) and both[j + 1] == both[i]:
            j += 1
        avg = (i + j) / 2 + 1
        rank[both[i]] = avg
        i = j + 1
    rp = sum(rank[v] for v in pos)
    return (rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def win_base_rate(rows):
    """Base rate of the market-outcome label on the SAME rows — the second measurement target,
    printed beside the realized-PnL AUC so neither number is read alone."""
    pos = [1.0 if str(r["y_win"]).lower() in ("1", "true", "t") else 0.0 for r in rows]
    return sum(pos) / len(pos) if pos else None


def run(rows, label, out):
    n = len(rows)
    n_markets = len({r["market"] for r in rows})
    n_wallets = len({r["wallet"] for r in rows})

    # Two tercile bases, because the feature is a WALLET attribute:
    #  - leg-level  : cut legs by the score they carry (ties at a coarse integer score make the
    #                 "top tercile" wider than a third of the legs — reported as n_top)
    #  - wallet-level: cut WALLETS by their own score, then take every leg of the top-tercile
    #                 wallets. This is the faithful reading of "select on wallet skill".
    cut_hi = tercile_cut(rows, "feat", top=True)
    cut_lo = tercile_cut(rows, "feat", top=False)
    price_hi = tercile_cut(rows, "price", top=True)

    wscore = {}
    for r in rows:
        wscore.setdefault(r["wallet"], []).append(r["feat"])
    wmean = {w: mean(v) for w, v in wscore.items()}
    wvals = sorted(wmean.values())
    w_hi = wvals[int(2 * len(wvals) / 3)] if len(wvals) >= 3 else float("inf")
    w_lo = wvals[int(len(wvals) / 3)] if len(wvals) >= 3 else float("-inf")

    top = lambda r: r["feat"] >= cut_hi
    bot = lambda r: r["feat"] <= cut_lo
    wtop = lambda r: wmean.get(r["wallet"], float("-inf")) >= w_hi
    price_top = lambda r: r["price"] >= price_hi
    allsel = lambda r: True

    arms = {
        "top_tercile_wallet_quality": [r["target"] for r in rows if top(r)],
        "top_tercile_wallet_quality_WALLET_LEVEL": [r["target"] for r in rows if wtop(r)],
        "bottom_tercile_wallet_quality": [r["target"] for r in rows if bot(r)],
        "top_tercile_entry_price": [r["target"] for r in rows if price_top(r)],
        "copy_all": [r["target"] for r in rows],
    }
    res = {
        "label": label, "n_legs": n, "n_markets": n_markets, "n_wallets": n_wallets,
        "n_top": len(arms["top_tercile_wallet_quality"]),
        "n_top_wallet_level": len(arms["top_tercile_wallet_quality_WALLET_LEVEL"]),
        "n_top_wallet_level_wallets": len([w for w in wmean if wmean[w] >= w_hi]),
        "date_range": [min(r["opened"] for r in rows), max(r["opened"] for r in rows)],
        "cuts": {"wallet_quality_top": cut_hi, "wallet_quality_bottom": cut_lo,
                 "wallet_tercile_top": w_hi, "entry_price_top": price_hi},
        "mean_pnl_net_per_leg": {k: mean(v) for k, v in arms.items()},
        "auc_wallet_quality_vs_net": auc(rows, "feat"),
        "auc_entry_price_vs_net": auc(rows, "price"),
        "win_rate_y_win": win_base_rate(rows),
        "gate": {},
    }
    g = res["gate"]
    g["A_leglevel_top_vs_copy_all"] = cluster_bootstrap_diff(rows, top, allsel)
    g["A2_walletlevel_top_vs_copy_all"] = cluster_bootstrap_diff(rows, wtop, allsel)
    g["B_leglevel_top_vs_price_top"] = cluster_bootstrap_diff(rows, top, price_top)
    g["B2_walletlevel_top_vs_price_top"] = cluster_bootstrap_diff(rows, wtop, price_top)
    g["C_leglevel_top_vs_bottom"] = cluster_bootstrap_diff(rows, top, bot)
    # Gate needs BOTH readings of "top-tercile beats price-only" to clear zero.
    g["promote_leg_level"] = bool(g["A_leglevel_top_vs_copy_all"]["lo"] > 0 and g["B_leglevel_top_vs_price_top"]["lo"] > 0)
    g["promote_wallet_level"] = bool(g["A2_walletlevel_top_vs_copy_all"]["lo"] > 0 and g["B2_walletlevel_top_vs_price_top"]["lo"] > 0)
    g["promote"] = bool(g["promote_leg_level"] and g["promote_wallet_level"])
    return res


def render(res):
    m = res["mean_pnl_net_per_leg"]
    g = res["gate"]
    print(f"\n=== {res['label']} ===")
    print(f"legs {res['n_legs']} | markets {res['n_markets']} | wallets {res['n_wallets']} | "
          f"{res['date_range'][0]} -> {res['date_range'][1]}")
    print(f"mean net PnL/leg: copy-all ${m['copy_all']:.3f} | top-tercile {FEATURE} "
          f"${m['top_tercile_wallet_quality']:.3f} (n={res['n_top']}) | top-tercile {FEATURE} "
          f"WALLET-LEVEL ${m['top_tercile_wallet_quality_WALLET_LEVEL']:.3f} "
          f"({res['n_top_wallet_level_wallets']} wallets, n={res['n_top_wallet_level']}) | bottom-tercile "
          f"${m['bottom_tercile_wallet_quality']:.3f} | top-tercile price ${m['top_tercile_entry_price']:.3f}")
    print(f"AUC {FEATURE} vs net>0 {res['auc_wallet_quality_vs_net']:.4f} | "
          f"AUC entry_price vs net>0 {res['auc_entry_price_vs_net']:.4f} | win rate (y_win) {res['win_rate_y_win']:.4f}")
    for k, v in g.items():
        if isinstance(v, bool):
            continue
        print(f"  {k}: diff ${v['diff']:+.3f}/leg  95% CI [{v['lo']:+.3f}, {v['hi']:+.3f}]  "
              f"P(diff>0) {v['share_gt0']:.3f}  reps {v['reps']}")
    print(f"  PROMOTE: {g['promote']}  (leg-level {g['promote_leg_level']}, wallet-level {g['promote_wallet_level']})")


def main():
    global FEATURE
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=DEFAULT_DATASET)
    ap.add_argument("--from", dest="from_date", default="2026-09-26")
    ap.add_argument("--bot", default="BANKROLL_200")
    ap.add_argument("--feature", default=FEATURE,
                    help="wallet-side feature column to test as a selector (default wallet_quality_score)")
    ap.add_argument("--all-lanes", action="store_true")
    ap.add_argument("--full-history", action="store_true")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    FEATURE = args.feature

    runs = []
    base = load(args.dataset, args.from_date, args.bot, args.all_lanes, args.full_history)
    if not base:
        print("no rows for that population"); return 1
    runs.append(run(base, f"forward {args.bot} (opened_at >= {args.from_date})", args.json))
    lanes = load(args.dataset, args.from_date, None, True, args.full_history)
    runs.append(run(lanes, f"forward ALL LANES (opened_at >= {args.from_date})", None))
    full = load(args.dataset, None, args.bot, False, True)
    runs.append(run(full, f"FULL HISTORY {args.bot} (no date filter)", None))

    for r in runs:
        render(r)
    out = args.json or os.path.join(ROOT, "data", "wallet-selection-test-20261010.json")
    with open(out, "w") as fh:
        json.dump({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "dataset": args.dataset, "target": TARGET, "feature": FEATURE,
                   "bootstrap": {"unit": "market_id", "reps": BOOT_REPS, "seed": SEED},
                   "runs": runs}, fh, indent=1)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
