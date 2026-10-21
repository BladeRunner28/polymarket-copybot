#!/usr/bin/env python3
"""
ml-observe-record.py — the ML lane's OBSERVE-ONLY recorder.

WHAT THIS IS
The user chose (2026-10-20) to run the ML lane observe-only rather than trade a selector that
failed: no arm cleared zero across 40 clustered tests (see train-report-market.json). So this
records the model's full ranking on every live candidate each cycle WITHOUT opening positions, so
forward decile economics accumulate on data the model has never seen and can be compared against
the historical null.

WHY IT IS BUILT THIS WAY
1. Features come from `ml_features.py`, the same module the trainer uses. A second inlined copy of
   the feature construction is how train/serve skew happens silently.
2. IN-DISTRIBUTION ONLY. In training `horizon_h` was only ever 6 or 24, and `timeToResolution` only
   spanned the hours around those horizons. Feeding a market with 400 hours to resolution would put
   the model far outside its support and the scores would be meaningless-but-plausible. So candidates
   are restricted to a TTR band around the trained horizons, and `horizon_h` is mapped to the
   nearest trained value (<=12h -> 6, else 24) rather than being set to the raw TTR.
3. One observation per (market, side, calendar day). Without this, a market that stays open for
   weeks would dominate the sample and the decile economics would be a few markets wearing a large n.
4. It never writes PaperTrade rows and never touches a RuleSet. Observing cannot move the book.

Usage:
  .venv-ml/bin/python scripts/ml-observe-record.py --dry-run
  .venv-ml/bin/python scripts/ml-observe-record.py
"""

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

import joblib
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ml_features import expand_sides, derive_features, feature_matrix  # noqa: E402

DEFAULT_DB = "prisma/dev.db"
DEFAULT_MODEL = "data/ml/model-market.pkl"
DEFAULT_OUT = "data/ml/observe-log.jsonl"


def load_existing_keys(path):
    keys = set()
    if not os.path.exists(path):
        return keys
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            keys.add((r.get("market_id"), r.get("side"), r.get("day")))
    return keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--window-hours", type=int, default=24)
    ap.add_argument("--cap", type=float, default=0.35)
    ap.add_argument("--ttr-min", type=float, default=3.0)
    ap.add_argument("--ttr-max", type=float, default=30.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.model):
        print("FATAL: no model artifact at {} -- run scripts/ml-train-market.py first".format(args.model))
        sys.exit(1)
    art = joblib.load(args.model)
    clf, roi_model = art["model"], art.get("roi_model")
    if roi_model is None:
        print("FATAL: artifact has no roi_model; retrain to persist all arms")
        sys.exit(1)
    trained_through = art.get("trained_through_day", "?")

    con = sqlite3.connect("file:{}?mode=ro".format(args.db), uri=True)
    now_ms = con.execute("SELECT MAX(collectedAt) FROM MarketSnapshot").fetchone()[0]
    if not now_ms:
        print("no snapshots"); sys.exit(1)
    cut = now_ms - args.window_hours * 3600 * 1000

    # Latest snapshot per market inside the window.
    q = """
        SELECT s.marketId, s.question, s.yesPrice, s.bestBid, s.bestAsk, s.spread,
               s.liquidity, s.volume, s.timeToResolution, s.collectedAt
        FROM MarketSnapshot s
        JOIN (SELECT marketId, MAX(collectedAt) AS mx FROM MarketSnapshot
              WHERE isDemo = 0 AND collectedAt >= ? GROUP BY marketId) l
          ON l.marketId = s.marketId AND l.mx = s.collectedAt
        WHERE s.isDemo = 0
    """
    snap = pd.read_sql_query(q, con, params=(cut,))
    con.close()
    print("markets seen in last {}h: {:,}".format(args.window_hours, len(snap)))
    if snap.empty:
        print("nothing to observe"); return

    # Still trading, and inside the model's trained time-to-resolution support.
    snap = snap[
        snap["yesPrice"].notna()
        & (snap["yesPrice"] > 0.10) & (snap["yesPrice"] < 0.90)
        & snap["timeToResolution"].notna()
        & (snap["timeToResolution"] >= args.ttr_min)
        & (snap["timeToResolution"] <= args.ttr_max)
    ].copy()
    print("in-distribution candidates (0.10<yes<0.90, TTR {}..{}h): {:,}".format(
        args.ttr_min, args.ttr_max, len(snap)))
    if snap.empty:
        print("nothing in band"); return

    # horizon_h must be a trained value, never the raw TTR.
    snap["horizon_h"] = snap["timeToResolution"].map(lambda h: 6 if float(h) <= 12.0 else 24)

    cand = expand_sides(snap, cap=args.cap, horizon_h=24)
    cand["horizon_h"] = cand["timeToResolution"].map(lambda h: 6 if float(h) <= 12.0 else 24)
    cand = cand[cand["passes_gate"]].copy()
    print("side-expanded and premium-gated: {:,}".format(len(cand)))
    if cand.empty:
        print("nothing passed the premium gate"); return

    cand = derive_features(cand)
    X = feature_matrix(cand)
    p = clf.predict_proba(X)[:, 1]
    cand["p_profit"] = p
    cand["ev"] = p / (cand["ask"].values + cand["fee_ps"].values) - 1.0
    cand["roi_reg"] = roi_model.predict(X)

    day = dt.datetime.utcfromtimestamp(now_ms / 1000).strftime("%Y-%m-%d")
    ts = dt.datetime.utcfromtimestamp(now_ms / 1000).isoformat() + "Z"
    existing = load_existing_keys(args.out)
    rows = []
    for _, r in cand.iterrows():
        key = (r["marketId"], r["side"], day)
        if key in existing:
            continue
        rows.append({
            "ts": ts, "kind": "live", "day": day,
            "market_id": r["marketId"], "question": r["question"], "side": r["side"],
            "yesPrice": float(r["yesPrice"]), "mid": float(r["mid"]), "ask": float(r["ask"]),
            "fee_ps": float(r["fee_ps"]), "cost_ps": float(r["cost_ps"]),
            "premium": float(r["premium"]), "spread": float(r["spread"]) if pd.notna(r["spread"]) else None,
            "liquidity": float(r["liquidity"]) if pd.notna(r["liquidity"]) else None,
            "volume": float(r["volume"]) if pd.notna(r["volume"]) else None,
            "timeToResolution": float(r["timeToResolution"]), "horizon_h": int(r["horizon_h"]),
            "band": r["band"], "ttr_band": r["ttr_band"], "fee_band": r["fee_band"],
            "p_profit": float(r["p_profit"]), "ev": float(r["ev"]), "roi_reg": float(r["roi_reg"]),
            "model_trained_through": trained_through,
        })

    print("new observations to write: {} (skipped {} already recorded today)".format(
        len(rows), len(cand) - len(rows)))
    if not rows:
        print("log already current for {}"); return

    if args.dry_run:
        print("\nDRY RUN — sample of what would be appended:")
        for r in rows[:4]:
            print("  {} {:<4} ask {:.3f} p {:.3f} ev {:+.3f} roi_reg {:+.3f} {:.55}".format(
                r["market_id"][:14], r["side"], r["ask"], r["p_profit"], r["ev"], r["roi_reg"],
                str(r["question"])[:55]))
        return

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print("appended {} observations to {}".format(len(rows), args.out))
    print("log now holds {} rows".format(sum(1 for _ in open(args.out))))


if __name__ == "__main__":
    main()
