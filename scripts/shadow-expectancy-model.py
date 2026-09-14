"""Walk-forward expectancy model — what a score fitted to MONEY (not win rate) would have earned.

Read-only over prisma/dev.db. numpy only.

Design decisions that matter:
  * Target = realized PnL per dollar staked (edge), NOT a win flag. The
    measured trap: win-rate-optimal features (favorites, "high quality"
    wallets) sit in negative expectancy.
  * Features are DECISION-TIME only. WalletProfile columns are deliberately
    excluded: they hold current (not point-in-time) values and leak the future.
  * Expanding-window walk-forward with periodic refits — no random CV.
  * The policy backtest RE-RANKS the existing trade population (a filter),
    it does not re-simulate a different population. Read it that way.

Run: python3 scripts/shadow-expectancy-model.py
"""
import math
import sqlite3

import numpy as np

DB = "prisma/dev.db"

FEATURES = [
    "copyScore", "confidence", "raw_composite", "entryPrice", "entryPrice_sq",
    "drift", "trade_size_log", "size", "hour_et", "is_swarm", "is_sentiment",
    "is_lane", "walletQualityScore", "categoryFitScore", "entryTimingScore",
    "spreadScore", "liquidityScore", "thesisScore",
]

L2 = 10.0


def load():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    rows = con.execute(
        """SELECT t.botId, t.venue, t.entryPrice, t.simulatedPositionSize, t.realizedPnl,
                  t.openedAt, t.status, d.copyScore, d.confidence, d.reasonsJson,
                  d.walletQualityScore, d.categoryFitScore, d.entryTimingScore,
                  d.spreadScore, d.liquidityScore, d.thesisScore,
                  o.walletEntryPrice, o.detectedPrice, o.size, d.ruleSetVersion,
                  COALESCE(t.closedAt, t.resolvedAt) AS closed_ts
           FROM PaperTrade t
           JOIN DecisionJournal d ON d.id = t.decisionJournalId
           JOIN ObservedTrade o ON o.id = d.observedTradeId
           WHERE t.status IN ('closed','resolved') AND t.realizedPnl IS NOT NULL
             AND t.isDemo = 0 AND t.simulatedPositionSize > 0"""
    ).fetchall()
    con.close()
    return rows


def build(rows):
    out = []
    for r in rows:
        (bot, venue, entry, size, pnl, opened, status, cs, conf, reasons,
         wq, cat, timing, spread, liq, thesis, wentry, detp, tsize, rsv, closed) = r
        raw = (wq or 0) * 0.30 + (cat or 0) * 0.15 + (timing or 0) * 0.20 + \
              (spread or 0) * 0.10 + (liq or 0) * 0.15 + (thesis or 0) * 0.10
        rj = (reasons or "").lower()
        out.append({
            "bot": bot, "venue": venue, "opened": opened, "size": float(size),
            "closed": float(closed or opened or 0), "status": status,
            "pnl": float(pnl), "edge": float(pnl) / float(size), "win": 1.0 if pnl > 0 else 0.0,
            "copyScore": cs, "confidence": conf, "raw_composite": raw,
            "entryPrice": entry, "entryPrice_sq": (entry or 0) ** 2,
            "drift": abs((detp or 0) - (wentry or 0)),
            "trade_size_log": math.log1p(max(0.0, tsize or 0.0)), "size": float(size),
            "hour_et": int(((opened or 0) / 3600000.0 - 4) % 24),
            "is_swarm": 1.0 if "swarm" in rj else 0.0,
            "is_sentiment": 1.0 if "sentiment evidence" in rj else 0.0,
            "is_lane": 1.0 if (conf == 0 and cs) else 0.0,
            "walletQualityScore": wq, "categoryFitScore": cat, "entryTimingScore": timing,
            "spreadScore": spread, "liquidityScore": liq, "thesisScore": thesis,
            "ruleSetVersion": rsv or 0,
        })
    return out


def matrix(data, feats):
    X = np.array([[0.0 if d[f] is None or (isinstance(d[f], float) and math.isnan(d[f])) else float(d[f])
                   for f in feats] for d in data], float)
    return np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)


def ridge(X, y, l2):
    n, p = X.shape
    Xb = np.nan_to_num(np.hstack([np.ones((n, 1)), X]), nan=0.0, posinf=0.0, neginf=0.0)
    pen = np.eye(p + 1) * l2
    pen[0, 0] = 0.0
    A = np.nan_to_num(Xb.T @ Xb, nan=0.0, posinf=0.0, neginf=0.0) + pen
    b = np.nan_to_num(Xb.T @ y, nan=0.0, posinf=0.0, neginf=0.0)
    return np.linalg.solve(A, b)


def apply_beta(beta, X):
    return np.hstack([np.ones((X.shape[0], 1)), X]) @ beta


def walk_forward(data, feats, l2=10.0, refit_days=10, min_train=300):
    """Expanding-window OOS predictions, refit every `refit_days` (single pass).

    PURGED: a training row is eligible only once its OUTCOME was knowable, i.e.
    `closed <= prediction time`. Training on rows that were still open at
    prediction time leaks the future (a trade opened Aug 1 may only settle in
    September).
    """
    data = sorted(data, key=lambda d: d["opened"])
    day = 86400000.0
    start = data[0]["opened"]
    preds = np.full(len(data), np.nan)
    mu = sd = beta = None
    last_fit = None
    for i, d in enumerate(data):
        t = (d["opened"] - start) / day
        if beta is None or (t - last_fit) >= refit_days:
            # purge: only outcomes already settled before this decision
            tr = [x for x in data[:i] if x["closed"] <= d["opened"]]
            if len(tr) >= min_train:
                Xtr, ytr = matrix(tr, feats), np.array([x["edge"] for x in tr], float)
                ytr = np.clip(ytr, -3.0, 10.0)
                mu, sd = Xtr.mean(0), Xtr.std(0)
                sd = np.where(sd < 1e-6, 1.0, sd)
                beta = ridge(np.clip((Xtr - mu) / sd, -10, 10), ytr, l2)
                last_fit = t
        if beta is not None:
            Xi = np.clip((matrix([d], feats) - mu) / sd, -10, 10)
            preds[i] = float(apply_beta(beta, Xi)[0])
    return preds


def spear(a, b):
    """Spearman rank IC (no scipy)."""
    m = ~(np.isnan(a) | np.isnan(b))
    a, b = a[m], b[m]
    if len(a) < 30:
        return float("nan")
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean()
    rb -= rb.mean()
    den = math.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / den) if den else float("nan")


def policy(name, data, score_key, frac=0.30, higher_is_better=True):
    """Re-rank the same population and report the realized money in the chosen slice."""
    m = np.array([not (s is None or (isinstance(s, float) and math.isnan(s))) for s in score_key])
    sub = [d for d, keep in zip(data, m) if keep]
    sc = np.array([s for s, keep in zip(score_key, m) if keep], float)
    if len(sub) < 50:
        print("   %-28s n=%d too small" % (name, len(sub)))
        return
    k = max(1, int(len(sub) * frac))
    order = np.argsort(-sc if higher_is_better else sc)
    sel = [sub[i] for i in order[:k]]
    rej = [sub[i] for i in order[k:]]
    pnl = sum(x["pnl"] for x in sel)
    staked = sum(x["size"] for x in sel)
    print("   %-28s keep %4d/%4d  kept PnL $%+9.2f  ROI %+7.1f%%  (rejected $%+9.2f)  wr %.0f%%" % (
        name, k, len(sub), pnl, 100 * pnl / staked if staked else 0.0,
        sum(x["pnl"] for x in rej), 100 * sum(x["win"] for x in sel) / k))


def fit_and_save(path="data/shadow-score-model.json", as_of=None):
    """Fit the shadow expectancy score on settled C-200 copies and persist an artifact.

    Only rows whose outcome is already realized can be trained on, so the
    artifact is trained on every settled C-200 copy (the same population the
    diagnostics use) and carries its own purged walk-forward metrics so the
    consumer can see how trustworthy it is.
    """
    import json
    import os
    import time

    data = [d for d in build(load()) if d["bot"] == "BANKROLL_200"]
    if len(data) < 300:
        raise SystemExit("not enough settled C-200 copies to fit (%d)" % len(data))
    X = matrix(data, FEATURES)
    y = np.clip(np.array([d["edge"] for d in data], float), -3.0, 10.0)
    mu, sd = X.mean(0), X.std(0)
    sd = np.where(sd < 1e-6, 1.0, sd)
    beta = ridge(np.clip((X - mu) / sd, -10, 10), y, L2)
    oos = walk_forward(data, FEATURES, l2=L2)
    ic = spear(oos, np.array([d["edge"] for d in data], float))
    art = {
        "fitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "as_of_ms": as_of or int(time.time() * 1000),
        "target": "realized PnL per dollar staked (edge)",
        "population": "settled BANKROLL_200 copies (closed/resolved, isDemo=0)",
        "n_train": len(data),
        "l2": L2,
        "features": FEATURES,
        "mu": [float(v) for v in mu],
        "sd": [float(v) for v in sd],
        "beta": [float(v) for v in beta],
        "oos_rank_ic_purged": round(ic, 4),
        "caveats": [
            "decision-time features only; WalletProfile columns excluded (not point-in-time)",
            "training rows are eligible only after their outcome settled (purged walk-forward diagnostics)",
            "small sample: treat the score as a shadow candidate, not a proven edge",
        ],
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(art, fh, indent=2)
    print("wrote %s  n_train=%d  purged OOS rank IC=%+.3f" % (path, len(data), ic))
    return art


def main():
    data = build(load())
    print("finished copies with size + realized PnL: %d" % len(data))
    for label, sub in [("ALL", data),
                       ("C-200", [d for d in data if d["bot"] == "BANKROLL_200"]),
                       ("C-200 main-lane", [d for d in data if d["bot"] == "BANKROLL_200" and not d["is_lane"]])]:
        if len(sub) < 200:
            print("\n== %s: n=%d too small ==" % (label, len(sub)))
            continue
        print("\n== %s: n=%d  total PnL $%+.2f  ROI %+.1f%% ==" % (
            label, len(sub), sum(d["pnl"] for d in sub),
            100 * sum(d["pnl"] for d in sub) / sum(d["size"] for d in sub)))
        preds = walk_forward(sub, FEATURES)
        actual = np.array([d["edge"] for d in sub], float)
        oos = ~np.isnan(preds)
        print("   OOS rank IC (predicted edge vs realized edge): %+.3f   n_oos=%d/%d" % (
            spear(preds, actual), int(oos.sum()), len(sub)))
        # apples-to-apples: every policy is ranked on the SAME rows that have OOS predictions
        same = [d for d, keep in zip(sub, oos) if keep]
        same_pred = [p for p, keep in zip(preds, oos) if keep]
        print("   policy comparison (keep top 30%% of the %d OOS rows):" % len(same))
        print("     reference: keep ALL of those rows  PnL $%+.2f  ROI %+.1f%%" % (
            sum(x["pnl"] for x in same), 100 * sum(x["pnl"] for x in same) / sum(x["size"] for x in same)))
        policy("incumbent copyScore", same, [d["copyScore"] for d in same])
        policy("incumbent raw_composite", same, [d["raw_composite"] for d in same])
        policy("model predicted edge (OOS)", same, same_pred)


if __name__ == "__main__":
    import sys

    if "--fit" in sys.argv:
        fit_and_save()
    else:
        main()
