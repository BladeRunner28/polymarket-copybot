#!/usr/bin/env python3
"""
ml-train-market.py — train a MARKET-ONLY selector that is deployable, and measure whether it
beats simply sorting by price.

WHY
The ML paper lane starts with $2,500 and must trade a MODEL-SELECTED candidate set (user,
2026-10-20). The existing `ml-train.py` model is wallet-conditioned -- `wallet_entry_price` is its
top feature -- so it cannot answer a market-only question and is unusable for this lane. Nothing
had ever been saved as an artifact either, so there was nothing to serve.

WHAT IT DOES
Trains on `data/ml/market-candidates.parquet`, whose labels are ALREADY net of the taker fee and
the quoted spread at the ask (`roi_net`, computed by ml-market-candidates.py). Target = roi_net > 0,
i.e. "would this candidate have made money at the price we could actually have paid".

DESIGN DECISIONS THAT MATTER
1. TIME-ORDERED SPLIT, never random. Rows inside a market share one label, and a random split puts
   the same market on both sides -- that is how the earlier 25% label leak happened. Train on the
   earlier period, evaluate on the later one.
2. The PRICE-ONLY CONTROL (`-ask` as the score) is evaluated with the SAME decile machinery. If the
   model cannot beat sorting by price, it is not a selector, it is a decoration -- and the honest
   answer is to say so rather than ship a model because it exists.
3. Every uncertainty interval bootstraps by MARKET, not by row. n_effective is the market count.
4. No label-derived column is a feature: payout, cost_ps, roi_net, roi_mid, y_yes are all downstream
   of the outcome and are excluded explicitly.

Usage:
  .venv-ml/bin/python scripts/ml-train-market.py [--deciles 10] [--test-frac 0.25]
"""

import argparse
import json
import os
import sys

import joblib
import numpy as np
import pandas as pd

DEFAULT_PARQUET = "data/ml/market-candidates.parquet"
OUT_MODEL = "data/ml/model-market.pkl"
OUT_REPORT = "data/ml/train-report-market.json"

# Explicit leak barrier: anything derived from the outcome.
LEAK_COLS = ["payout", "cost_ps", "roi_net", "roi_mid", "y_yes", "label_status", "resolved_at"]
NUM_FEATURES = ["yesPrice", "ask", "mid", "spread", "premium", "fee_ps", "liquidity", "volume",
                "timeToResolution", "horizon_h", "log_liquidity", "log_volume", "is_yes",
                "q_words", "q_chars", "q_has_year", "q_upper_tokens"]
CAT_FEATURES = ["band", "ttr_band", "fee_band"]


def fee_band(rate):
    if rate is None or pd.isna(rate):
        return "na"
    if rate >= 0.06:
        return "high"
    if rate >= 0.045:
        return "mid"
    return "low"


def build(df):
    d = df.copy()
    d = d[d["passes_gate"].astype(bool)]
    d = d[d["roi_net"].notna() & d["y_yes"].notna()]
    d["log_liquidity"] = np.log1p(d["liquidity"].clip(lower=0))
    d["log_volume"] = np.log1p(d["volume"].clip(lower=0))
    d["is_yes"] = (d["side"] == "YES").astype(float)
    q = d["question"].fillna("").astype(str)
    d["q_words"] = q.str.split().str.len().astype(float)
    d["q_chars"] = q.str.len().astype(float)
    d["q_has_year"] = q.str.contains(r"20\d\d", regex=True).astype(float)
    d["q_upper_tokens"] = q.apply(lambda s: sum(1 for t in s.split() if t.isupper() and len(t) > 1)).astype(float)
    d["fee_band"] = d["fee_rate"].apply(fee_band)
    d["band"] = d["band"].astype(str)
    d["ttr_band"] = d["ttr_band"].astype(str)
    # Categoricals must never carry NaN (OneHotEncoder would emit a spurious category or raise).
    for c in CAT_FEATURES:
        d[c] = d[c].fillna("na").astype(str)
    d["target"] = (d["roi_net"] > 0).astype(int)
    d["day"] = pd.to_datetime(d["collectedAt"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    return d


def cluster_ci(values, clusters, B=400, seed=7):
    """Bootstrap the mean by resampling CLUSTERS (markets)."""
    values = np.asarray(values, dtype=float)
    clusters = np.asarray(clusters)
    uniq = pd.unique(clusters)
    if len(uniq) < 3 or len(values) == 0:
        return (float("nan"), float("nan"))
    idx_by = pd.Series(range(len(clusters)), index=clusters).groupby(level=0).apply(lambda s: s.to_numpy())
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(B):
        pick = rng.choice(len(idx_by), size=len(idx_by), replace=True)
        take = np.concatenate([idx_by.iloc[i] for i in pick])
        means.append(values[take].mean())
    means = np.asarray(means)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def decile_table(df, score_col, label, deciles=10):
    d = df[[score_col, "roi_net", "market_id"]].dropna().copy()
    if d.empty:
        return []
    d["bin"] = pd.qcut(d[score_col].rank(method="first"), deciles, labels=False)
    out = []
    for b in range(deciles):
        g = d[d["bin"] == b]
        if g.empty:
            continue
        lo = float(np.percentile(g[score_col], 0))
        hi = float(np.percentile(g[score_col], 100))
        lo_ci, hi_ci = cluster_ci(g["roi_net"].values * 100.0, g["market_id"].values)
        out.append({
            "decile": b + 1,
            "n": int(len(g)),
            "markets": int(g["market_id"].nunique()),
            "score_lo": round(lo, 4),
            "score_hi": round(hi, 4),
            "win_rate": round(float((g["roi_net"] > 0).mean()) * 100.0, 2),
            "roi_net_pct": round(float(g["roi_net"].mean()) * 100.0, 3),
            "ci_lo": round(lo_ci, 3) if lo_ci == lo_ci else None,
            "ci_hi": round(hi_ci, 3) if hi_ci == hi_ci else None,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default=DEFAULT_PARQUET)
    ap.add_argument("--deciles", type=int, default=10)
    ap.add_argument("--test-frac", type=float, default=0.25)
    args = ap.parse_args()

    from sklearn.compose import ColumnTransformer
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from lightgbm import LGBMClassifier

    d = build(pd.read_parquet(args.parquet))
    print("gated + labelled rows: {:,} | markets: {:,}".format(len(d), d["market_id"].nunique()))
    print("label base rate (net-profitable): {:.3f}".format(d["target"].mean()))

    # TIME-ORDERED split.
    days = np.sort(d["day"].unique())
    cut_i = int(len(days) * (1 - args.test_frac))
    cutoff_day = days[cut_i]
    tr = d[d["day"] < cutoff_day].copy()
    te = d[d["day"] >= cutoff_day].copy()
    print("cutoff day {} -> train {:,} rows/{:,} mkt, test {:,} rows/{:,} mkt".format(
        cutoff_day, len(tr), tr["market_id"].nunique(), len(te), te["market_id"].nunique()))
    if len(tr) < 500 or len(te) < 200:
        print("FATAL: split too small"); sys.exit(1)

    # LightGBM accepts NaN natively and would have hidden this; LogisticRegression raises. Median
    # impute so BOTH arms see the same matrix and the comparison is honest.
    pre = ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]), NUM_FEATURES),
        ("cat", Pipeline([("imp", SimpleImputer(strategy="most_frequent")),
                          ("oh", OneHotEncoder(handle_unknown="ignore"))]), CAT_FEATURES),
    ])
    models = {
        "logistic": Pipeline([("pre", pre), ("clf", LogisticRegression(max_iter=2000, C=0.5))]),
        "lgbm": Pipeline([("pre", pre), ("clf", LGBMClassifier(
            n_estimators=350, learning_rate=0.05, num_leaves=31, min_child_samples=100,
            subsample=0.9, colsample_bytree=0.9, random_state=7, verbose=-1))]),
    }

    y_tr, y_te = tr["target"].values, te["target"].values
    results = {}
    best_name, best_auc = None, -1.0
    for name, mdl in models.items():
        mdl.fit(tr[NUM_FEATURES + CAT_FEATURES], y_tr)
        p = mdl.predict_proba(te[NUM_FEATURES + CAT_FEATURES])[:, 1]
        auc = float(roc_auc_score(y_te, p))
        brier = float(brier_score_loss(y_te, p))
        ll = float(log_loss(y_te, np.clip(p, 1e-6, 1 - 1e-6)))
        results[name] = {"auc": round(auc, 4), "brier": round(brier, 4), "logloss": round(ll, 4)}
        print("{:<9} AUC {:.4f}  Brier {:.4f}  logloss {:.4f}".format(name, auc, brier, ll))
        te["p_" + name] = p
        if auc > best_auc:
            best_auc, best_name = auc, name

    # REGRESSION ARM -- predict roi_net DIRECTLY.
    # The two classifiers rank P(net-profitable), but profitability and return are not the same
    # quantity: a 99% win at 0.97 is +3% when it wins and -100% when it loses. A regressor minimising
    # loss on the return targets the economics instead of the outcome, so ranking by its prediction
    # IS "expected ROI". Huber + a clip guard because roi_net has a +9900% tail (a 0.01 entry).
    from lightgbm import LGBMRegressor
    y_reg_tr = tr["roi_net"].clip(-1.0, 5.0).values
    reg = Pipeline([("pre", pre), ("reg", LGBMRegressor(
        objective="huber", alpha=0.5, n_estimators=350, learning_rate=0.05, num_leaves=31,
        min_child_samples=100, subsample=0.9, colsample_bytree=0.9, random_state=7, verbose=-1))])
    reg.fit(tr[NUM_FEATURES + CAT_FEATURES], y_reg_tr)
    te["p_roi_reg"] = reg.predict(te[NUM_FEATURES + CAT_FEATURES])
    results["roi_reg"] = {"objective": "huber on roi_net clipped [-1, 5]"}
    print("roi_reg   predicted-return ranking (no AUC -- it is a regressor)")

    # PRICE-ONLY CONTROL: lower ask = cheaper entry = the naive ranking. Negate so higher = better.
    te["p_price_only"] = -te["ask"].values
    results["price_only"] = {"auc": None, "brier": None, "logloss": None}

    # ECONOMICALLY CORRECT SCORE. Ranking by P(profit) structurally prefers near-certainties:
    # a 99% win bought at 0.97 pays +3% on a win and -100% on a loss, so "most likely to be
    # profitable" is a steamroller, not an edge. What we want is expected ROI PER DOLLAR, so
    # convert the calibrated probability into money: EV = p * (1/cost) - 1.
    te["p_ev"] = te["p_" + best_name].values / (te["ask"].values + te["fee_ps"].values) - 1.0
    results["ev_model"] = {"from": best_name, "score": "p / (ask + fee) - 1"}
    print("\nbest model by AUC: {}".format(best_name))

    # Decile economics -- model vs the price-only control, same machinery.
    deciles_blob = {}
    arms = [(best_name, "p_" + best_name), ("price_only", "p_price_only"), ("ev_model", "p_ev"),
            ("roi_reg", "p_roi_reg")]
    for label, col in arms:
        t = decile_table(te, col, label, args.deciles)
        deciles_blob[label] = t
        print("\n--- decile economics: {} (holdout, net of fee+spread at ask) ---".format(label))
        for r in t:
            ci = "[{:+.2f}, {:+.2f}]".format(r["ci_lo"], r["ci_hi"]) if r["ci_lo"] is not None else "[na]"
            print("  D{:<2} n={:<6} mkt={:<5} win {:>6.2f}%  net ROI {:+8.3f}%  CI {}".format(
                r["decile"], r["n"], r["markets"], r["win_rate"], r["roi_net_pct"], ci))

    # Verdict: does the BEST decile of the model clear zero on its clustered CI, and does it beat
    # the price-only control's best decile? Both must hold for the model to be a selector.
    def best_positive(rows):
        cand = [r for r in rows if r["ci_lo"] is not None and r["ci_lo"] > 0]
        return max(cand, key=lambda r: r["roi_net_pct"]) if cand else None

    m_best = best_positive(deciles_blob[best_name])
    p_best = best_positive(deciles_blob["price_only"])
    ev_best = best_positive(deciles_blob["ev_model"])
    # Multiple-comparison guard: 10 deciles x 3 arms = 30 nominal 95% tests, so ~1.5 "hits" are
    # expected by chance alone. A single decile clearing zero is NOT evidence.
    n_tests = args.deciles * len(arms)
    expected_by_chance = round(n_tests * 0.05, 2)
    reg_best = best_positive(deciles_blob["roi_reg"])
    ev_clears = ev_best is not None
    hits = sum([m_best is not None, p_best is not None, ev_clears, reg_best is not None])
    verdict = {
        "nominal_tests": n_tests,
        "expected_hits_by_chance_at_95pct": expected_by_chance,
        "model_best_positive_decile": m_best,
        "price_only_best_positive_decile": p_best,
        "ev_model_best_positive_decile": ev_best,
        "roi_reg_best_positive_decile": reg_best,
        "model_clears_zero": m_best is not None,
        "price_only_clears_zero": p_best is not None,
        "model_beats_price_only": bool(
            m_best and p_best and m_best["roi_net_pct"] > p_best["roi_net_pct"]
        ) if (m_best and p_best) else (True if (m_best and not p_best) else False),
        "arms_clearing_zero": hits,
    }
    print("\n=== VERDICT ===")
    print("  nominal 95% tests run: {} ({} deciles x {} arms) -> {:.2f} hits expected by chance"
          .format(n_tests, args.deciles, len(arms), expected_by_chance))
    print("  actual arms with a decile clearing zero: {}  -- at or below chance means no signal"
          .format(hits))
    print("  P(profit) model clears zero: {}".format(verdict["model_clears_zero"]))
    print("  price-only control clears:   {}".format(verdict["price_only_clears_zero"]))
    print("  EV-ranked model clears:      {}".format(ev_clears))
    print("  ROI-regression clears:       {}".format(reg_best is not None))
    if reg_best:
        print("  roi_reg best decile: D{} net ROI {:+.3f}% CI [{:+.2f}, {:+.2f}] n={} mkt={}".format(
            reg_best["decile"], reg_best["roi_net_pct"], reg_best["ci_lo"], reg_best["ci_hi"],
            reg_best["n"], reg_best["markets"]))
    if ev_best:
        print("  EV arm best decile: D{} net ROI {:+.3f}% CI [{:+.2f}, {:+.2f}] n={} mkt={}".format(
            ev_best["decile"], ev_best["roi_net_pct"], ev_best["ci_lo"], ev_best["ci_hi"],
            ev_best["n"], ev_best["markets"]))
    if hits <= expected_by_chance:
        print("  => NO ARM IS ESTABLISHED. The number of deciles clearing zero is within what chance")
        print("     produces across this many tests. No selector has been earned by this data.")
    elif ev_best and (not m_best or ev_best["roi_net_pct"] > m_best["roi_net_pct"]):
        print("  => The EV-ranked arm is the only candidate: ranking by expected ROI per dollar beats")
        print("     ranking by P(profit), as the payoff geometry demands. Forward test still required.")
    elif m_best:
        print("  => P(profit) ranking is the candidate selector. Forward test still required.")
    else:
        print("  => Only the naive price rule clears zero; the model adds nothing.")

    # Refit best model on ALL data for serving, and persist.
    final = models[best_name]
    final.fit(d[NUM_FEATURES + CAT_FEATURES], d["target"].values)
    joblib.dump({
        "model": final,
        "num_features": NUM_FEATURES,
        "cat_features": CAT_FEATURES,
        "trained_at": pd.Timestamp.utcnow().isoformat(),
        "train_rows": int(len(d)),
        "train_markets": int(d["market_id"].nunique()),
        "cutoff_day": str(cutoff_day),
        "holdout_auc": results[best_name]["auc"],
        "kind": best_name,
    }, OUT_MODEL)
    print("\nsaved {} (refit on all {:,} rows)".format(OUT_MODEL, len(d)))

    report = {
        "built_at": pd.Timestamp.utcnow().isoformat(),
        "source": args.parquet,
        "gated_labelled_rows": int(len(d)),
        "markets": int(d["market_id"].nunique()),
        "label": "roi_net > 0 (net of taker fee and spread at ask)",
        "base_rate": round(float(d["target"].mean()), 4),
        "cutoff_day": str(cutoff_day),
        "train": {"rows": int(len(tr)), "markets": int(tr["market_id"].nunique())},
        "test": {"rows": int(len(te)), "markets": int(te["market_id"].nunique())},
        "leak_cols_excluded": LEAK_COLS,
        "results": results,
        "best_model": best_name,
        "deciles": deciles_blob,
        "verdict": verdict,
    }
    with open(OUT_REPORT, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print("saved {}".format(OUT_REPORT))


if __name__ == "__main__":
    main()
