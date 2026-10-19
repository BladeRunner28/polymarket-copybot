#!/usr/bin/env python3
"""
Prepare the ML matrices: CSV -> parquet, build the time-ordered purged split, and establish
the PRICE-ONLY comparator on THIS population (the entry book), not on the old acted book.

Run with the ML venv:  .venv-ml/bin/python scripts/ml-prepare.py

WHY THE BAR MUST BE RE-DERIVED HERE
  The ML-1 gate bar (AUC >= 0.729, Brier <= 0.212) was measured on the ACTED export with label
  y_net_entry (base rate 54.2%). This dataset is a different population AND a different label
  (y_side_win, base rate ~79%): the direction we'd take usually wins because we copy the side a
  tracked wallet bought. Brier is base-rate dependent — a CONSTANT predictor on a 79% base
  scores ~0.164, i.e. "better" than the 0.212 bar while having zero skill. So the bar is quoted
  here against this population's own constant reference, and the model target is skill OVER
  price-only, which is the only comparator that means anything for an entry decision.
"""
import json, os, sys
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss

BASE = os.path.expanduser("~/polymarket-copybot")
OUT = os.path.join(BASE, "data/ml")
BOUNDARY = pd.Timestamp("2026-08-21T00:00:00Z")

NUMERIC = [
    "size_usd", "copy_score", "confidence", "raw_confidence", "adjusted_copy_score",
    "wallet_quality", "roi", "consistency", "copyability", "category_fit", "entry_timing",
    "spread_score", "liquidity_score", "thesis_score", "wallet_entry_price", "detected_price",
    "obs_size_usd", "price_drift", "yes_price", "no_price", "best_bid", "best_ask", "spread",
    "liquidity", "volume", "ttr_hours", "snapshot_age_min", "logit_yes", "log_liquidity",
    "log_volume", "spread_bps", "hour_utc", "dow", "horizon_hours",
]
CATEGORICAL = ["decision", "outcome", "side", "category", "category_class", "category_fine",
               "research_category"]
LABELS = ["y_side_win", "y_yes"]
META = ["decision_id", "decided_at", "resolved_at", "market_id", "wallet", "rule_set_version",
        "acted_this_decision", "acted_any", "label_status"]


def clustered_ci(y, p, groups, n_boot=400, seed=7):
    """Market-clustered bootstrap CI for AUC: rows inside a market share one label."""
    rng = np.random.default_rng(seed)
    # market_id can arrive with NaN mixed with str -> np.unique refuses to sort it
    groups = np.array([str(g) for g in groups], dtype=object)
    uniq = np.unique(groups)
    idx_by_g = {g: np.where(groups == g)[0] for g in uniq}
    aucs = []
    for _ in range(n_boot):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([idx_by_g[g] for g in pick])
        yy, pp = y[idx], p[idx]
        if yy.min() == yy.max():
            continue
        aucs.append(roc_auc_score(yy, pp))
    if not aucs:
        return (float("nan"), float("nan"))
    return (float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5)))


def main():
    path = os.path.join(OUT, "decisions.csv")
    print(f"reading {path} ...")
    df = pd.read_csv(path, low_memory=False)
    print(f"  {len(df):,} rows x {len(df.columns)} cols")

    for c in NUMERIC:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df["decided_at"] = pd.to_datetime(df["decided_at"], errors="coerce", utc=True)
    df["resolved_at"] = pd.to_datetime(df["resolved_at"], errors="coerce", utc=True)

    # ---------------- split: time-ordered, PURGED on the label's knowability ----------------
    labelled = df[df["y_side_win"].notna()].copy()
    labelled["y_side_win"] = labelled["y_side_win"].astype(int)
    labelled["y_yes"] = pd.to_numeric(labelled["y_yes"], errors="coerce")

    train = labelled[labelled["decided_at"] < BOUNDARY].copy()
    test = labelled[labelled["decided_at"] >= BOUNDARY].copy()
    # purge: a train row whose market only became decidable after the boundary has a label
    # polluted by information the test period owns.
    purge = train[train["resolved_at"].isna() | (train["resolved_at"] >= BOUNDARY)]
    train = train.drop(purge.index)
    print(f"\nlabelled {len(labelled):,}  train {len(train):,}  test {len(test):,}  purged {len(purge):,}")
    print(f"  train markets {train['market_id'].nunique():,} | test markets {test['market_id'].nunique():,}")
    print(f"  train wallets {train['wallet'].nunique():,} | test wallets {test['wallet'].nunique():,}")

    # ---------------- comparator: price-only ----------------
    res = {"boundary": BOUNDARY.isoformat(), "rows": {"labelled": int(len(labelled)),
           "train": int(len(train)), "test": int(len(test)), "purged": int(len(purge))},
           "power": {"train_markets": int(train["market_id"].nunique()),
                     "test_markets": int(test["market_id"].nunique()),
                     "wallets": int(labelled["wallet"].nunique())},
           "labels": {}}

    for lab in LABELS:
        tr = train[train[lab].notna() & train["logit_yes"].notna()]
        te = test[test[lab].notna() & test["logit_yes"].notna()]
        if len(tr) < 100 or len(te) < 100:
            continue
        y_tr, y_te = tr[lab].astype(int).values, te[lab].astype(int).values
        X_tr = tr[["logit_yes"]].values
        X_te = te[["logit_yes"]].values
        m = LogisticRegression(max_iter=1000).fit(X_tr, y_tr)
        p_tr, p_te = m.predict_proba(X_tr)[:, 1], m.predict_proba(X_te)[:, 1]
        base = y_te.mean()
        const_brier = float(np.mean((base - y_te) ** 2))
        auc = float(roc_auc_score(y_te, p_te))
        br = float(brier_score_loss(y_te, p_te))
        lo, hi = clustered_ci(y_te, p_te, te["market_id"].values)
        res["labels"][lab] = {
            "train_n": int(len(tr)), "test_n": int(len(te)),
            "train_base_rate": round(float(y_tr.mean()), 4),
            "test_base_rate": round(base, 4),
            "price_only_auc": round(auc, 4),
            "price_only_auc_ci95_market_clustered": [round(lo, 4), round(hi, 4)],
            "price_only_brier": round(br, 4),
            "constant_brier": round(const_brier, 4),
            "brier_skill_vs_constant": round(1 - br / const_brier, 4) if const_brier else None,
        }
        print(f"\n[{lab}] train n={len(tr):,} base={y_tr.mean():.3f} | test n={len(te):,} base={base:.3f}")
        print(f"  price-only AUC {auc:.4f}  CI95 [{lo:.4f}, {hi:.4f}] (market-clustered)")
        print(f"  price-only Brier {br:.4f}  vs constant {const_brier:.4f}  skill {1 - br/const_brier:+.4f}")

    # ---------------- parquet out ----------------
    keep = [c for c in (META + NUMERIC + CATEGORICAL + LABELS) if c in df.columns]
    pq = os.path.join(OUT, "decisions.parquet")
    df[keep].to_parquet(pq, index=False)
    print(f"\nwrote {pq} ({os.path.getsize(pq)/1e6:.1f} MB, {len(df):,} rows, {len(keep)} cols)")

    # missingness — the model must be able to tell "absent" from "zero"
    miss = (df[keep].isna().mean().sort_values(ascending=False) * 100).round(1)
    res["missing_pct"] = {k: float(v) for k, v in miss.items() if v > 0}
    res["columns"] = keep
    with open(os.path.join(OUT, "prep-baseline.json"), "w") as f:
        json.dump(res, f, indent=2)
    print(f"wrote {OUT}/prep-baseline.json")
    top = [f"{k}={v}%" for k, v in list(res["missing_pct"].items())[:10]]
    print("  most-missing columns: " + ", ".join(top))


if __name__ == "__main__":
    main()
