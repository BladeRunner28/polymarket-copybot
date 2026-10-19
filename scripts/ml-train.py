#!/usr/bin/env python3
"""
Train the batch arms (LightGBM + regularized logistic) against the RE-DERIVED bar and judge them
with a PAIRED market-clustered bootstrap.

Run: .venv-ml/bin/python scripts/ml-train.py [--label y_side_win] [--quick]

THE BAR
  The label is "did the direction we would take win". The price that predicts it is the price of
  OUR SIDE, not the YES price: side_price = yes_price if outcome == YES else no_price. The first
  comparator I quoted used logit(yes_price) alone, which cannot flip sign with the side and so
  understates what price knows. Both are reported here; the CORRECTED one (logit_side_price) is
  the bar:
      beat AUC + Brier of a logistic on logit(side_price), with the market-clustered 95% CI on the
      DELTA excluding 0. The delta is computed paired on identical bootstrap resamples, because
      two independent CIs overlapping is not evidence of no difference.

DISCIPLINE
  * frozen boundary 2026-08-21, purge train rows whose market became decidable on/after it
  * early stopping / hyper-parameter choices use a TIME-ORDERED inner validation carved from the
    train window only; the test period is touched once, at the end
  * monotone constraint on the side-price feature in LightGBM: the anchor already knows the
    relationship, and a tree is only allowed to add to it, never to invert it
"""
import argparse, json, os, time
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.calibration import calibration_curve

BASE = os.path.expanduser("~/polymarket-copybot")
OUT = os.path.join(BASE, "data/ml")
BOUNDARY = pd.Timestamp("2026-08-21T00:00:00Z")
RNG = np.random.default_rng(20261019)

NUMERIC = [
    "size_usd", "copy_score", "confidence", "raw_confidence", "adjusted_copy_score",
    "wallet_quality", "roi", "consistency", "copyability", "category_fit", "entry_timing",
    "spread_score", "liquidity_score", "thesis_score", "wallet_entry_price", "detected_price",
    "obs_size_usd", "price_drift", "best_bid", "best_ask", "spread",
    "liquidity", "volume", "ttr_hours", "snapshot_age_min", "logit_yes", "log_liquidity",
    "log_volume", "spread_bps", "hour_utc", "dow",
    # horizon_hours is deliberately EXCLUDED: it is (first 0.90/0.10 crossing - decision time),
    # i.e. a quantity computed from a FUTURE event, and how quickly a market reached a terminal
    # price correlates with the terminal price itself. It is a label leak that arrives disguised
    # as a timing feature. It stays in the parquet (it is a legitimate PURGE and reporting key)
    # and never enters a model.
]
CATEGORICAL = ["decision", "outcome", "side", "category_class", "category_fine", "research_category"]


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def load(label):
    df = pd.read_parquet(os.path.join(OUT, "decisions.parquet"))
    for c in NUMERIC + ["yes_price", "no_price"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["decided_at"] = pd.to_datetime(df["decided_at"], errors="coerce", utc=True)
    df["resolved_at"] = pd.to_datetime(df["resolved_at"], errors="coerce", utc=True)

    # --- the side-price feature (the honest price frame) ---
    is_no = df["outcome"].astype(str).str.upper().str.startswith("N")
    df["side_price"] = np.where(is_no, df["no_price"], df["yes_price"])
    # fall back to the recorded entry price when the book was missing
    df["side_price"] = df["side_price"].fillna(df["wallet_entry_price"]).fillna(df["detected_price"])
    df["logit_side_price"] = logit(df["side_price"])
    df.loc[df["side_price"].isna(), "logit_side_price"] = np.nan

    d = df[df[label].notna()].copy()
    d[label] = d[label].astype(int)
    # ---- LEAKAGE GUARD: label must NOT have been knowable when the decision was made ----
    # A decision taken in a market that had already crossed to a terminal price is not a
    # decision: the outcome was visible. Measured on this book, 70.2% of the test window is
    # such rows and they win 91.5% of the time against 60.0% for genuinely open markets — the
    # single largest source of fake skill in the whole exercise. Kept out of every arm.
    n_all = len(d)
    d = d[d["resolved_at"].notna() & (d["resolved_at"] > d["decided_at"])]
    print(f"  open-at-decision guard: kept {len(d):,} of {n_all:,} labelled rows "
          f"({100*len(d)/max(n_all,1):.1f}%)")

    train = d[d["decided_at"] < BOUNDARY].copy()
    test = d[d["decided_at"] >= BOUNDARY].copy()
    purge = train[train["resolved_at"].isna() | (train["resolved_at"] >= BOUNDARY)]
    train = train.drop(purge.index)
    return df, train, test, len(purge)


def design(train, test, numeric, categorical):
    """Median-impute + scale numerics, one-hot categoricals, missing-indicator for the sparsest."""
    num_tr = train[numeric].astype(float)
    num_te = test[numeric].astype(float)
    imp = SimpleImputer(strategy="median")
    sc = StandardScaler()
    A = sc.fit_transform(imp.fit_transform(num_tr))
    B = sc.transform(imp.transform(num_te))
    cat_tr = train[categorical].astype(str)
    cat_te = test[categorical].astype(str)
    both = pd.concat([cat_tr, cat_te], axis=0)
    dums = pd.get_dummies(both, columns=categorical, dummy_na=True)
    d_tr = dums.iloc[: len(cat_tr)].values.astype(float)
    d_te = dums.iloc[len(cat_tr):].values.astype(float)
    return np.hstack([A, d_tr]), np.hstack([B, d_te]), list(numeric) + list(dums.columns)


def clustered_delta_bootstrap(y, p_a, p_b, groups, n_boot=400):
    """PAIRED cluster bootstrap: resample MARKETS, return delta AUC (a - b) distribution."""
    groups = np.array([str(g) for g in groups], dtype=object)
    uniq = np.unique(groups)
    idx_by_g = {g: np.where(groups == g)[0] for g in uniq}
    deltas, auc_a, auc_b = [], [], []
    for _ in range(n_boot):
        pick = RNG.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([idx_by_g[g] for g in pick])
        yy = y[idx]
        if yy.min() == yy.max():
            continue
        a, b = roc_auc_score(yy, p_a[idx]), roc_auc_score(yy, p_b[idx])
        auc_a.append(a); auc_b.append(b); deltas.append(a - b)
    q = lambda v: [round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)]
    return {"delta_mean": round(float(np.mean(deltas)), 4), "delta_ci95": q(deltas),
            "auc_a_ci95": q(auc_a), "auc_b_ci95": q(auc_b),
            "p_delta_gt_0": round(float(np.mean(np.array(deltas) > 0)), 4), "n_boot": len(deltas)}


def score(y, p, const_ref):
    br = float(brier_score_loss(y, p))
    return {"auc": round(float(roc_auc_score(y, p)), 4),
            "brier": round(br, 4),
            "constant_brier": round(float(const_ref), 4),
            "brier_skill_vs_constant": round(1 - br / const_ref, 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="y_side_win", choices=["y_side_win", "y_yes"])
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--drop", default="", help="comma-separated features to exclude (ablation)")
    args = ap.parse_args()
    T0 = time.time()
    tag = ("_" + args.drop.replace(",", "_")) if args.drop else ""

    df, train, test, n_purged = load(args.label)
    # ABLATION: wallet_entry_price is the price the WALLET paid, known at decision time but not
    # tradeable -- by the time we see the trade the book has usually moved, and detected_price is
    # what we would actually pay. A model whose gain is mostly wallet_entry_price is answering
    # "would this have won at a price we could not get", which is not a decision lane. Dropping
    # it produces the EXECUTABLE arm.
    global NUMERIC
    if args.drop:
        dropped = [c.strip() for c in args.drop.split(",") if c.strip()]
        NUMERIC = [c for c in NUMERIC if c not in dropped]
        for c in dropped:
            if c in train.columns:
                train = train.drop(columns=[c]); test = test.drop(columns=[c])
        print(f"  ABLATION: dropped {dropped}")
    y_tr, y_te = train[args.label].values, test[args.label].values
    print(f"[{args.label}] train {len(train):,} (base {y_tr.mean():.3f}) | test {len(test):,} "
          f"(base {y_te.mean():.3f}) | purged {n_purged:,}")
    print(f"  train markets {train['market_id'].nunique():,} | test markets {test['market_id'].nunique():,}")

    # ---------------- comparators ----------------
    comp = {}
    for name, cols in [("price_yes_frame", ["logit_yes"]), ("price_side_frame", ["logit_side_price"])]:
        tr = train[train[cols[0]].notna()]
        te = test[test[cols[0]].notna()]
        m = LogisticRegression(max_iter=1000).fit(tr[cols].values.astype(float), tr[args.label].values)
        p = m.predict_proba(te[cols].values.astype(float))[:, 1]
        const = float(np.mean((te[args.label].mean() - te[args.label]) ** 2))
        comp[name] = {**score(te[args.label].values, p, const), "n_train": int(len(tr)), "n_test": int(len(te))}
        comp[name]["coef"] = round(float(m.coef_[0][0]), 4)
        comp[name]["intercept"] = round(float(m.intercept_[0]), 4)
        print(f"  comparator {name:16s} AUC {comp[name]['auc']:.4f}  Brier {comp[name]['brier']:.4f}")

    # The bar is the STRONGEST price-only frame, not the one I expected to win. Both frames
    # are legitimate price-only models; letting the weaker one be "the bar" would manufacture
    # a +0.04 AUC improvement out of a feature-frame choice.
    BAR_NAME = max(comp, key=lambda k: comp[k]["auc"])
    BAR_AUC = comp[BAR_NAME]["auc"]
    BAR_BRIER = comp[BAR_NAME]["brier"]
    BAR_FEATURE = "logit_yes" if BAR_NAME == "price_yes_frame" else "logit_side_price"
    print(f"  BAR = {BAR_NAME} (AUC {BAR_AUC:.4f} / Brier {BAR_BRIER:.4f}) via {BAR_FEATURE}")

    # ---------------- inner time-ordered validation (train window only) ----------------
    tr_sorted = train.sort_values("decided_at")
    cut = int(len(tr_sorted) * 0.8)
    inner_tr, inner_va = tr_sorted.iloc[:cut], tr_sorted.iloc[cut:]
    print(f"  inner val: {len(inner_tr):,} fit / {len(inner_va):,} early-stop (time-ordered)")

    # ---------------- logistic anchor ----------------
    ANUM = NUMERIC + ["logit_side_price"]
    Xa, Xb, cols = design(inner_tr, inner_va, ANUM, CATEGORICAL)
    best_c, best_a, grid = 1.0, -1, {}
    for C in (0.01, 0.03, 0.1, 0.3, 1.0):
        mm = LogisticRegression(max_iter=2000, C=C).fit(Xa, inner_tr[args.label].values)
        a = roc_auc_score(inner_va[args.label].values, mm.predict_proba(Xb)[:, 1])
        grid[C] = round(float(a), 4)
        if a > best_a:
            best_c, best_a = C, a
    print(f"  anchor C grid (inner-val AUC) {grid} -> C={best_c}")
    Xa_full, Xb_full, _ = design(train, test, ANUM, CATEGORICAL)
    anchor = LogisticRegression(max_iter=2000, C=best_c).fit(Xa_full, y_tr)
    p_anchor = anchor.predict_proba(Xb_full)[:, 1]
    const_te = float(np.mean((y_te.mean() - y_te) ** 2))
    res_anchor = {**score(y_te, p_anchor, const_te), "n_features": int(Xa_full.shape[1]),
                  "C": best_c, "inner_val_auc_grid": grid}
    print(f"  logistic anchor      AUC {res_anchor['auc']:.4f}  Brier {res_anchor['brier']:.4f}")

    # ---------------- LightGBM ----------------
    feats_tr = [c for c in NUMERIC + ["logit_side_price"] if c in train.columns]
    cat_feats = [c for c in CATEGORICAL if c in train.columns]
    use = feats_tr + cat_feats

    def frame(d):
        x = d[use].copy()
        for c in NUMERIC + ["logit_side_price"]:
            if c in x.columns:
                x[c] = pd.to_numeric(x[c], errors="coerce")
        for c in cat_feats:
            x[c] = x[c].astype("category")
        return x

    mono = [1 if c in ("logit_side_price", "best_bid") else 0 for c in use]
    params = dict(
        objective="binary", metric="auc", learning_rate=0.03, num_leaves=7, max_depth=4,
        min_data_in_leaf=200, feature_fraction=0.7, bagging_fraction=0.8, bagging_freq=1,
        lambda_l1=1.0, lambda_l2=5.0, monotone_constraints=mono, verbosity=-1, seed=20261019,
    )
    dtrain = lgb.Dataset(frame(inner_tr), label=inner_tr[args.label].values,
                         categorical_feature=cat_feats, free_raw_data=False)
    dval = lgb.Dataset(frame(inner_va), label=inner_va[args.label].values,
                       categorical_feature=cat_feats, reference=dtrain, free_raw_data=False)
    n_rounds = 200 if args.quick else 3000
    gbm = lgb.train(params, dtrain, num_boost_round=n_rounds, valid_sets=[dval],
                    callbacks=[lgb.early_stopping(80, verbose=False), lgb.log_evaluation(0)])
    print(f"  lightgbm best_iteration {gbm.best_iteration}")

    # refit on the FULL train window at the chosen iteration count, then test once
    dall = lgb.Dataset(frame(train), label=y_tr, categorical_feature=cat_feats, free_raw_data=False)
    gbm_full = lgb.train(params, dall, num_boost_round=gbm.best_iteration or 100)
    p_gbm = gbm_full.predict(frame(test))
    res_gbm = {**score(y_te, p_gbm, const_te), "best_iteration": int(gbm.best_iteration)}
    print(f"  lightgbm             AUC {res_gbm['auc']:.4f}  Brier {res_gbm['brier']:.4f}")

    # ---------------- paired clustered deltas ----------------
    # paired comparison on the rows where the BAR is defined (identical resamples for both arms)
    bar_mask = test[BAR_FEATURE].notna().values
    m = LogisticRegression(max_iter=1000).fit(
        train[train[BAR_FEATURE].notna()][[BAR_FEATURE]].values.astype(float),
        train[train[BAR_FEATURE].notna()][args.label].values)
    p_bar_full = np.full(len(test), np.nan)
    p_bar_full[bar_mask] = m.predict_proba(
        test.loc[bar_mask, [BAR_FEATURE]].values.astype(float))[:, 1]
    groups = test["market_id"].values[bar_mask]
    y_cmp = y_te[bar_mask]
    print(f"  paired bootstrap on {bar_mask.sum():,} rows where the bar is defined")

    deltas = {}
    for name, p in (("logistic_anchor", p_anchor), ("lightgbm", p_gbm)):
        deltas[name] = clustered_delta_bootstrap(y_cmp, p[bar_mask], p_bar_full[bar_mask], groups,
                                                n_boot=150 if args.quick else 400)
        print(f"  delta {name:16s} {deltas[name]['delta_mean']:+.4f} "
              f"CI {deltas[name]['delta_ci95']} p(>0)={deltas[name]['p_delta_gt_0']:.3f}")

    # ---------------- calibration + importance + predictions ----------------
    frac_pos, mean_pred = calibration_curve(y_te, p_gbm, n_bins=10, strategy="quantile")
    imp = pd.DataFrame({"feature": gbm_full.feature_name(),
                        "gain": gbm_full.feature_importance("gain"),
                        "split": gbm_full.feature_importance("split")}).sort_values("gain", ascending=False)
    imp.to_csv(os.path.join(OUT, f"feature-importance{tag}.csv"), index=False)

    preds = pd.DataFrame({
        "decision_id": test["decision_id"].values, "decided_at": test["decided_at"].values,
        "market_id": test["market_id"].values, "wallet": test["wallet"].values,
        "y": y_te, "p_bar": p_bar_full, "p_anchor": p_anchor, "p_gbm": p_gbm,
    })
    preds.to_parquet(os.path.join(OUT, f"predictions_test{tag}.parquet"), index=False)

    verdict = {}
    for name, r in (("logistic_anchor", res_anchor), ("lightgbm", res_gbm)):
        d = deltas[name]
        verdict[name] = {
            "beats_bar_auc": bool(r["auc"] > BAR_AUC),
            "beats_bar_brier": bool(r["brier"] < BAR_BRIER),
            "delta_ci_excludes_zero": bool(d["delta_ci95"][0] > 0),
            "PROMOTABLE": bool(r["auc"] > BAR_AUC and r["brier"] < BAR_BRIER
                               and d["delta_ci95"][0] > 0),
        }

    report = {
        "label": args.label, "ablated": args.drop, "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "boundary": BOUNDARY.isoformat(),
        "rows": {"train": int(len(train)), "test": int(len(test)), "purged": int(n_purged),
                 "train_markets": int(train["market_id"].nunique()),
                 "test_markets": int(test["market_id"].nunique())},
        "comparators": comp,
        "bar": {"auc": BAR_AUC, "brier": BAR_BRIER, "name": BAR_NAME, "feature": BAR_FEATURE,
                "definition": "the STRONGER of the two price-only logistic frames"},
        "correction_note": ("the bar first quoted used logit(yes_price); that frame cannot flip sign "
                            "with the side, so it understated price. price_side_frame is the bar."),
        "models": {"logistic_anchor": res_anchor, "lightgbm": res_gbm},
        "deltas_vs_bar": deltas,
        "verdict": verdict,
        "calibration_gbm": {"mean_predicted": [round(float(x), 4) for x in mean_pred],
                            "fraction_positive": [round(float(x), 4) for x in frac_pos]},
        "top_features": imp.head(15).to_dict("records"),
        "elapsed_s": round(time.time() - T0, 1),
    }
    with open(os.path.join(OUT, f"train-report{tag}.json"), "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nwrote {OUT}/train-report{tag}.json ({report['elapsed_s']}s)")
    for k, v in verdict.items():
        print(f"  {k:16s} beats_auc={v['beats_bar_auc']} beats_brier={v['beats_bar_brier']} "
              f"ci_excludes_0={v['delta_ci_excludes_zero']} => PROMOTABLE={v['PROMOTABLE']}")


if __name__ == "__main__":
    main()
