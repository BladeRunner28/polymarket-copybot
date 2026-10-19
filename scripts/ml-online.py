#!/usr/bin/env python3
"""
The online arm: a model that learns from each settled trade, in time order, and shouts when the
data starts fighting it. This is the "learn live as it trades" component.

Run: .venv-ml/bin/python scripts/ml-online.py [--model hat|arf|logit]

HOW IT IS JUDGED (prequential / interleaved test-then-train)
  Every row is PREDICTED FIRST and LEARNED FROM AFTERWARDS. That is the only honest way to score
  a model that updates itself: a model that learns a row before predicting it has seen the answer.
  The batch LightGBM is scored on the SAME rows from `predictions_test*.parquet` (trained on the
  train window only), so the two numbers are comparable.

WHY DRIFT DETECTION IS NOT DECORATION HERE
  The train base rate is 0.696 and the test base rate is 0.821 for the same target. The book's
  composition moves (which wallets are watched, which categories are live, the rule set version),
  so a fixed model silently mis-calibrates. ADWIN watches the loss stream and reports WHERE it
  breaks — each alarm is a candidate regime boundary, not a bug.

SAFETY
  Shadow only. This writes a ledger and a report; it never places, sizes or approves anything.
"""
import argparse, json, os, time
import numpy as np
import pandas as pd
from river import drift, linear_model, metrics, preprocessing, tree, utils

BASE = os.path.expanduser("~/polymarket-copybot")
OUT = os.path.join(BASE, "data/ml")
BOUNDARY = pd.Timestamp("2026-08-21T00:00:00Z")

NUMERIC = [
    "size_usd", "copy_score", "confidence", "raw_confidence", "adjusted_copy_score",
    "wallet_quality", "roi", "consistency", "copyability", "category_fit", "entry_timing",
    "spread_score", "liquidity_score", "thesis_score", "detected_price", "obs_size_usd",
    "best_bid", "best_ask", "spread", "liquidity", "volume", "ttr_hours", "snapshot_age_min",
    "logit_yes", "log_volume", "spread_bps", "hour_utc", "dow", "side_price",
]
# wallet_entry_price / price_drift excluded on purpose: the executable arm. See ml-train.py.


def build(arm: str):
    if arm == "hat":
        return ("HoeffdingAdaptiveTree", preprocessing.StandardScaler() | tree.HoeffdingAdaptiveTreeClassifier(
            grace_period=100, delta=0.001, leaf_prediction="nba", seed=20261019))
    if arm == "arf":
        return ("AdaptiveRandomForest", preprocessing.StandardScaler() | tree.AdaptiveRandomForestClassifier(
            n_models=10, seed=20261019))
    return ("OnlineLogistic", preprocessing.StandardScaler() | linear_model.LogisticRegression())


def calibrate(bp: pd.DataFrame, args) -> None:
    """Online recalibration of a frozen batch scorer, scored prequentially.

    Uses sklearn's SGDClassifier.partial_fit because river's LogisticRegression will not let the
    weights be seeded, and an unseeded online logistic predicts ~0.5 for its first hundreds of
    rows -- ties that collapse AUC and make recalibration look harmful when it is only untrained.
    Seeded at IDENTITY (w=1, b=0 on logit p) the calibrator starts exactly at the frozen scorer.
    """
    from sklearn.metrics import brier_score_loss, roc_auc_score
    from sklearn.linear_model import SGDClassifier

    y_all, p_raw, p_cal, ledger, alarms = [], [], [], [], []
    adwin = drift.ADWIN(delta=0.002)
    clf = SGDClassifier(loss="log_loss", learning_rate="constant", eta0=0.002,
                        random_state=20261019)
    seeded = False
    lg = lambda p: float(np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6))))
    for i, d in enumerate(bp.itertuples(index=False)):
        x = np.array([[lg(d.p_gbm)]])
        y = int(d.y)
        if not seeded:
            clf.partial_fit(x, [y], classes=np.array([0, 1]))
            clf.coef_ = np.array([[1.0]]); clf.intercept_ = np.array([0.0])
            seeded = True
        p = float(clf.predict_proba(x)[0][1])
        p = min(max(p, 1e-6), 1 - 1e-6)
        adwin.update((p - y) ** 2)
        if adwin.drift_detected:
            alarms.append({"at": str(d.decided_at)[:19], "rows_seen": i})
        clf.partial_fit(x, [y], classes=np.array([0, 1]))
        y_all.append(y); p_raw.append(float(d.p_gbm)); p_cal.append(p)
        ledger.append({"decision_id": d.decision_id, "decided_at": d.decided_at, "y": y,
                       "p_raw": round(float(d.p_gbm), 6), "p_calibrated": round(p, 6),
                       "drift": bool(adwin.drift_detected)})
    led = pd.DataFrame(ledger)
    led.to_parquet(os.path.join(OUT, "online-ledger_calibrator.parquet"), index=False)
    ya, pr, pc = np.array(y_all), np.array(p_raw), np.array(p_cal)
    const_b = float(np.mean((ya.mean() - ya) ** 2))
    cal_b, raw_b = float(brier_score_loss(ya, pc)), float(brier_score_loss(ya, pr))
    rep = {
        "model": "OnlineCalibrator (sklearn SGD, identity-seeded)", "streamed_rows": int(len(ya)),
        "prequential_calibrated": {"auc": round(float(roc_auc_score(ya, pc)), 4),
                                    "brier": round(cal_b, 4),
                                    "brier_skill_vs_constant": round(1 - cal_b / const_b, 4)},
        "frozen_batch": {"auc": round(float(roc_auc_score(ya, pr)), 4), "brier": round(raw_b, 4),
                          "brier_skill_vs_constant": round(1 - raw_b / const_b, 4)},
        "constant_brier": round(const_b, 4),
        "delta_brier": round(cal_b - raw_b, 4),
        "drift_alarms": {"n": len(alarms), "first_20": alarms[:20]},
        "ledger": "data/ml/online-ledger_calibrator.parquet",
    }
    with open(os.path.join(OUT, "online-report_calibrator.json"), "w") as f:
        json.dump(rep, f, indent=2)
    print(f"  rows streamed {len(ya):,}")
    print(f"  frozen batch   AUC {rep['frozen_batch']['auc']:.4f}  Brier {raw_b:.4f}")
    print(f"  + online calib AUC {rep['prequential_calibrated']['auc']:.4f}  Brier {cal_b:.4f} "
          f"(delta {cal_b - raw_b:+.4f})")
    print(f"  drift alarms: {len(alarms)}")
    for a in alarms[:5]:
        print(f"    alarm at {a['at']} after {a['rows_seen']:,} rows")
    print(f"\nwrote {OUT}/online-report_calibrator.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="hat", choices=["hat", "arf", "logit", "calibrator"])
    ap.add_argument("--window", type=int, default=2000)
    ap.add_argument("--prime", action="store_true",
                    help="learn the train window first (how it would ship), then go prequential")
    args = ap.parse_args()
    T0 = time.time()

    df = pd.read_parquet(os.path.join(OUT, "decisions.parquet"))
    for c in NUMERIC:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["decided_at"] = pd.to_datetime(df["decided_at"], errors="coerce", utc=True)

    is_no = df["outcome"].astype(str).str.upper().str.startswith("N")
    df["side_price"] = np.where(is_no, pd.to_numeric(df["no_price"], errors="coerce"),
                                pd.to_numeric(df["yes_price"], errors="coerce"))
    df["side_price"] = df["side_price"].fillna(pd.to_numeric(df["wallet_entry_price"], errors="coerce"))

    lab = df[df["y_side_win"].notna()].copy()
    lab["y_side_win"] = lab["y_side_win"].astype(int)
    # only decisions taken while the market was still genuinely undecided (see ml-train.py):
    # 70.2% of the raw test window had a label that was already knowable at decision time.
    n_raw = len(lab)
    lab = lab[lab["resolved_at"].notna() & (lab["resolved_at"] > lab["decided_at"])]
    print(f"  open-at-decision guard: kept {len(lab):,} of {n_raw:,} labelled rows "
          f"({100*len(lab)/max(n_raw,1):.1f}%)")
    train = lab[lab["decided_at"] < BOUNDARY]
    test = lab[lab["decided_at"] >= BOUNDARY].sort_values("decided_at")

    # medians from the TRAIN window only -- imputing from the stream would leak the future
    med = {c: float(train[c].median()) if train[c].notna().any() else 0.0
           for c in NUMERIC if c in train.columns}
    feats = [c for c in NUMERIC if c in train.columns]

    def row(d):
        return {c: (float(d[c]) if pd.notna(d[c]) else med[c]) for c in feats}

    if args.model == "calibrator":
        # THE USEFUL FORM OF LIVE LEARNING: keep the batch scorer, learn to RE-CALIBRATE it.
        # A 1-feature online logistic on logit(p_batch) adapts to base-rate drift without
        # relearning the whole problem from 20k rows. This is what should ship.
        pth = os.path.join(OUT, "predictions_test_wallet_entry_price.parquet")
        bp = pd.read_parquet(pth)[["decision_id", "decided_at", "y", "p_gbm"]].copy()
        bp = bp.merge(test[["decision_id"]], on="decision_id", how="inner").sort_values("decided_at")
        return calibrate(bp, args)

    name, model = build(args.model)
    adwin = drift.ADWIN(delta=0.002)
    # river >= 0.15 keeps Rolling under utils, not metrics
    roll_auc = utils.Rolling(metrics.ROCAUC(), window_size=args.window)
    # river has no Brier metric; MSE of a probability prediction IS the Brier score
    roll_brier = utils.Rolling(metrics.MSE(), window_size=args.window)

    print(f"online arm {name}: streaming {len(test):,} settled decisions in time order "
          f"({test['decided_at'].min().date()} -> {test['decided_at'].max().date()})")
    print(f"  train window {len(train):,} rows, medians imputed from train only")

    if args.prime:
        # Ship-ready mode: the model starts from the train window (data it is allowed to have),
        # then keeps learning from every settled trade in the test window.
        import random
        tr = train.sample(frac=1.0, random_state=20261019)  # order within train is irrelevant
        for _, d in tr.iterrows():
            model.learn_one(row(d), int(d["y_side_win"]))
        print(f"  PRIMED on {len(tr):,} train rows before streaming")

    ledger, alarms = [], []
    n, seen = 0, 0
    for _, d in test.iterrows():
        x, y = row(d), int(d["y_side_win"])
        p = float(model.predict_one(x) or 0.5)
        p = min(max(p, 1e-6), 1 - 1e-6)
        loss = (p - y) ** 2
        adwin.update(loss)
        if adwin.drift_detected:
            alarms.append({"at": str(d["decided_at"])[:19], "rows_seen": n})
        roll_auc.update(y, p)
        roll_brier.update(y, p)
        model.learn_one(x, y)
        ledger.append({"decision_id": d["decision_id"], "decided_at": d["decided_at"],
                       "y": y, "p_online": round(p, 6),
                       "rolling_auc": round(float(roll_auc.get() or 0.5), 5),
                       "rolling_brier": round(float(roll_brier.get() or 0.25), 5),
                       "drift": bool(adwin.drift_detected)})
        n += 1
        seen += 1

    led = pd.DataFrame(ledger)
    led.to_parquet(os.path.join(OUT, f"online-ledger_{args.model}.parquet"), index=False)

    y_all, p_all = led["y"].values, led["p_online"].values
    from sklearn.metrics import brier_score_loss, roc_auc_score
    const_b = float(np.mean((y_all.mean() - y_all) ** 2))
    preq_auc = float(roc_auc_score(y_all, p_all))
    preq_brier = float(brier_score_loss(y_all, p_all))

    # batch comparator on the SAME rows
    batch_auc = batch_brier = None
    preds_path = os.path.join(OUT, "predictions_test_wallet_entry_price.parquet")
    if os.path.exists(preds_path):
        b = pd.read_parquet(preds_path)[["decision_id", "p_gbm"]]
        j = led.merge(b, on="decision_id", how="inner")
        if len(j) > 1000:
            batch_auc = round(float(roc_auc_score(j["y"], j["p_gbm"])), 4)
            batch_brier = round(float(brier_score_loss(j["y"], j["p_gbm"])), 4)
            preq_auc_same = round(float(roc_auc_score(j["y"], j["p_online"])), 4)
        else:
            preq_auc_same = None
    else:
        preq_auc_same = None

    report = {
        "model": name, "arm": args.model,
        "streamed_rows": int(n),
        "prequential": {"auc": round(preq_auc, 4), "brier": round(preq_brier, 4),
                        "constant_brier": round(const_b, 4),
                        "brier_skill_vs_constant": round(1 - preq_brier / const_b, 4)},
        "batch_same_rows": {"lightgbm_auc": batch_auc, "lightgbm_brier": batch_brier,
                            "online_auc_same_rows": preq_auc_same,
                            "note": "batch trained on the train window only; online never saw a row "
                                    "before predicting it"},
        "drift_alarms": {"n": len(alarms), "first_20": alarms[:20]},
        "final_rolling_auc": round(float(led["rolling_auc"].iloc[-1]), 4),
        "final_rolling_brier": round(float(led["rolling_brier"].iloc[-1]), 4),
        "ledger": f"data/ml/online-ledger_{args.model}.parquet",
        "elapsed_s": round(time.time() - T0, 1),
    }
    with open(os.path.join(OUT, f"online-report_{args.model}.json"), "w") as f:
        json.dump(report, f, indent=2)

    print(f"  prequential AUC {preq_auc:.4f}  Brier {preq_brier:.4f} "
          f"(constant {const_b:.4f}, skill {1 - preq_brier/const_b:+.4f})")
    print(f"  batch LightGBM on the same rows: AUC {batch_auc} Brier {batch_brier}")
    print(f"  drift alarms: {len(alarms)}")
    for a in alarms[:5]:
        print(f"    alarm at {a['at']} after {a['rows_seen']:,} rows")
    print(f"\nwrote {OUT}/online-report_{args.model}.json ({report['elapsed_s']}s)")


if __name__ == "__main__":
    main()
