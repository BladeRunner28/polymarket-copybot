"""What actually separates winning from losing copies in our own book?

Read-only analysis over prisma/dev.db (numpy only, no pandas/sklearn).
Purpose: ground the 'scoring fix' in measured evidence before any model work.

Outputs
  1. per-feature decile separation (win rate, mean PnL, z of win-rate vs base)
  2. wins-vs-losses feature means with a Welch t
  3. time-ordered train/test check: can a ridge logistic model beat the
     incumbent copyScore on held-out data?

Run: python3 scripts/analyze-score-separation.py
"""
import math
import sqlite3

import numpy as np

DB = "prisma/dev.db"

COMPONENTS = [
    ("walletQualityScore", 0.30),
    ("categoryFitScore", 0.15),
    ("entryTimingScore", 0.20),
    ("spreadScore", 0.10),
    ("liquidityScore", 0.15),
    ("thesisScore", 0.10),
]

FEATURES = [
    "copyScore",
    "confidence",
    "raw_composite",
    "entryPrice",
    "size",
    "whale_entry",
    "detected_price",
    "drift",
    "trade_size",
    "wallet_global",
    "wallet_winrate30d",
    "wallet_roi30d",
    "wallet_consistency",
    "wallet_copyability",
    "wallet_trades30d",
    "wallet_avgsize",
    "hour_et",
    "is_lane",
    "is_swarm",
    "is_sentiment",
    "walletQualityScore",
    "categoryFitScore",
    "entryTimingScore",
    "spreadScore",
    "liquidityScore",
    "thesisScore",
]


def load():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    rows = con.execute(
        """SELECT t.id, t.botId, t.venue, t.entryPrice, t.simulatedPositionSize,
                  t.realizedPnl, t.openedAt, t.status,
                  d.copyScore, d.confidence, d.reasonsJson,
                  d.walletQualityScore, d.categoryFitScore, d.entryTimingScore,
                  d.spreadScore, d.liquidityScore, d.thesisScore,
                  o.walletEntryPrice, o.detectedPrice, o.size, o.marketId, o.marketCategory,
                  w.globalScore, w.winRate30d, w.roi30d, w.consistencyScore,
                  w.copyabilityScore, w.tradeCount30d, w.averageTradeSize
           FROM PaperTrade t
           JOIN DecisionJournal d ON d.id = t.decisionJournalId
           JOIN ObservedTrade o ON o.id = d.observedTradeId
           LEFT JOIN WalletProfile w ON w.address = t.walletAddress
           WHERE t.status IN ('closed','resolved') AND t.realizedPnl IS NOT NULL
             AND t.isDemo = 0"""
    ).fetchall()
    con.close()
    return rows


def build(rows):
    out = []
    for r in rows:
        (tid, bot, venue, entry, size, pnl, opened, status, cs, conf, reasons,
         wq, cat, timing, spread, liq, thesis, wentry, detp, tsize, mkt, mcat,
         wglob, wwin, wroi, wcons, wcopy, wtrades, wsize) = r
        raw = (wq or 0) * 0.30 + (cat or 0) * 0.15 + (timing or 0) * 0.20 + \
              (spread or 0) * 0.10 + (liq or 0) * 0.15 + (thesis or 0) * 0.10
        rj = (reasons or "").lower()
        # ET hour of entry (UTC-4 in Sep; kept simple and documented)
        hour_et = int(((opened or 0) / 3600000.0 - 4) % 24)
        d = {
            "id": tid, "bot": bot, "venue": venue, "pnl": float(pnl), "win": 1.0 if pnl > 0 else 0.0,
            "opened": opened, "status": status, "marketId": mkt or "", "mcat": mcat,
            "copyScore": cs, "confidence": conf, "raw_composite": raw,
            "entryPrice": entry, "size": size or 0.0,
            "whale_entry": wentry, "detected_price": detp, "drift": abs((detp or 0) - (wentry or 0)),
            "trade_size": tsize or 0.0,
            "wallet_global": wglob if wglob is not None else np.nan,
            "wallet_winrate30d": wwin if wwin is not None else np.nan,
            "wallet_roi30d": wroi if wroi is not None else np.nan,
            "wallet_consistency": wcons if wcons is not None else np.nan,
            "wallet_copyability": wcopy if wcopy is not None else np.nan,
            "wallet_trades30d": wtrades if wtrades is not None else np.nan,
            "wallet_avgsize": wsize if wsize is not None else np.nan,
            "hour_et": hour_et,
            "is_lane": 1.0 if (conf == 0 and cs) else 0.0,
            "is_swarm": 1.0 if "swarm" in rj else 0.0,
            "is_sentiment": 1.0 if "sentiment evidence" in rj else 0.0,
            "walletQualityScore": wq, "categoryFitScore": cat, "entryTimingScore": timing,
            "spreadScore": spread, "liquidityScore": liq, "thesisScore": thesis,
        }
        out.append(d)
    return out


def z_winrate(sub):
    """z of the subset's win rate against the base rate (binomial)."""
    n = len(sub)
    if n == 0:
        return 0.0
    w = sum(x["win"] for x in sub)
    return (w / n - BASE) / math.sqrt(max(BASE * (1 - BASE) / n, 1e-12))


BASE = 0.5


def deciles(data, feat, n_bins=5):
    vals = [(d[feat], d) for d in data if d[feat] is not None and not (isinstance(d[feat], float) and math.isnan(d[feat]))]
    if len(vals) < 40:
        return []
    uniq = sorted({v for v, _ in vals})
    bins = []
    if len(uniq) <= 2:  # binary flag: compare the positive group with the rest
        pos = [d for v, d in vals if v == uniq[-1]]
        neg = [d for v, d in vals if v != uniq[-1]]
        for grp in (neg, pos):
            if grp:
                bins.append((uniq[-1] if grp is pos else uniq[0], grp))
    else:
        vals.sort(key=lambda t: t[0])
        step = len(vals) // n_bins
        for i in range(n_bins):
            chunk = vals[i * step: (i + 1) * step] if i < n_bins - 1 else vals[i * step:]
            if chunk:
                bins.append((chunk[0][0], [d for _, d in chunk]))
    out = []
    for lo, sub in bins:
        staked = sum(x["size"] for x in sub)
        pnl = sum(x["pnl"] for x in sub)
        out.append((lo, 0.0, len(sub), sum(x["win"] for x in sub) / len(sub),
                    pnl / len(sub), z_winrate(sub), pnl, staked, pnl / staked if staked else 0.0))
    return out


def welch(data, feat):
    a = [d[feat] for d in data if d["win"] == 1 and d[feat] is not None and not (isinstance(d[feat], float) and math.isnan(d[feat]))]
    b = [d[feat] for d in data if d["win"] == 0 and d[feat] is not None and not (isinstance(d[feat], float) and math.isnan(d[feat]))]
    if len(a) < 10 or len(b) < 10:
        return None
    a, b = np.array(a, float), np.array(b, float)
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    if se == 0:
        return None
    return a.mean(), b.mean(), (a.mean() - b.mean()) / se


def auc(y, s):
    y, s = np.asarray(y, float), np.asarray(s, float)
    order = np.argsort(s)
    ranks = np.empty(len(s), float)
    ranks[order] = np.arange(1, len(s) + 1)
    # average ranks for ties
    _, inv, cnt = np.unique(s, return_inverse=True, return_counts=True)
    for i, c in enumerate(cnt):
        if c > 1:
            m = inv == i
            ranks[m] = ranks[m].mean()
    n1, n0 = y.sum(), len(y) - y.sum()
    if n1 == 0 or n0 == 0:
        return float("nan")
    return (ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def fit_logreg(X, y, l2=1.0, iters=60):
    """Ridge logistic regression via IRLS (numpy only, numerically guarded)."""
    n, p = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    Xb = np.clip(Xb, -50.0, 50.0)
    beta = np.zeros(p + 1)
    pen = np.eye(p + 1) * l2
    pen[0, 0] = 0.0
    for _ in range(iters):
        z = np.clip(Xb @ beta, -30.0, 30.0)
        mu = 1.0 / (1.0 + np.exp(-z))
        W = np.clip(mu * (1 - mu), 1e-6, None)
        H = Xb.T @ (Xb * W[:, None]) + pen
        g = Xb.T @ (y - mu) - pen @ beta
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        step = np.clip(step, -5.0, 5.0)
        beta = np.clip(beta + step, -50.0, 50.0)
        if np.max(np.abs(step)) < 1e-6:
            break
    return beta


def predict(beta, X):
    Xb = np.clip(np.hstack([np.ones((X.shape[0], 1)), X]), -50.0, 50.0)
    return 1.0 / (1.0 + np.exp(-np.clip(Xb @ beta, -30.0, 30.0)))


def logloss(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def main():
    global BASE
    rows = load()
    data = build(rows)
    print("finished copies with realized PnL: %d (C-200 %d / STANDARD %d)" % (
        len(data),
        sum(1 for d in data if d["bot"] == "BANKROLL_200"),
        sum(1 for d in data if d["bot"] == "STANDARD")))
    for group, sub in [("ALL", data),
                       ("C-200", [d for d in data if d["bot"] == "BANKROLL_200"]),
                       ("C-200 main-lane", [d for d in data if d["bot"] == "BANKROLL_200" and not d["is_lane"]])]:
        if not sub:
            continue
        BASE = sum(x["win"] for x in sub) / len(sub)
        print("\n===== %s: n=%d base win rate %.1f%% mean PnL $%.2f =====" % (
            group, len(sub), BASE * 100, np.mean([x["pnl"] for x in sub])))
        ranked = []
        for f in FEATURES:
            dec = deciles(sub, f)
            if not dec:
                continue
            zmax = max(abs(t[5]) for t in dec)
            fp = dec[-1][4] - dec[0][4]     # top-bin minus bottom-bin mean PnL
            ranked.append((zmax, f, fp, dec))
        ranked.sort(reverse=True)
        print("  top separators (|z| of any bin's win rate vs base, then bin-PnL spread):")
        for zmax, f, fp, dec in ranked[:8]:
            lo = " | ".join("%s: n=%d wr=%.0f%% pnl=%+.2f tot=%+.0f roi=%+.1f%%" % (
                ("%.3g" % d[0]), d[2], d[3] * 100, d[4], d[6], d[8] * 100) for d in dec)
            print("   %-18s |z|max=%4.1f  binPnL spread %+7.2f" % (f, zmax, fp))
            print("       %s" % lo)
        print("  wins vs losses (Welch t):")
        for f in FEATURES:
            r = welch(sub, f)
            if r:
                print("   %-18s win %8.3f  loss %8.3f   t=%+5.2f" % (f, r[0], r[1], r[2]))

    # ---- time-ordered model check on C-200 (the live lane) ----
    print("\n===== time-ordered check: incumbent score vs ridge logistic =====")
    for label, sub in [("C-200 (all copies)", [d for d in data if d["bot"] == "BANKROLL_200"]),
                       ("C-200 main-lane", [d for d in data if d["bot"] == "BANKROLL_200" and not d["is_lane"]])]:
        if len(sub) < 200:
            print("  %s: n=%d too small" % (label, len(sub)))
            continue
        cut = int(np.quantile([d["opened"] for d in sub], 0.7))
        tr = [d for d in sub if d["opened"] <= cut]
        te = [d for d in sub if d["opened"] > cut]
        Xcols = [f for f in ("copyScore", "confidence", "raw_composite", "entryPrice", "drift",
                            "trade_size", "wallet_global", "wallet_winrate30d", "wallet_roi30d",
                            "wallet_consistency", "wallet_copyability", "wallet_trades30d",
                            "hour_et", "is_swarm", "is_sentiment", "categoryFitScore",
                            "entryTimingScore", "spreadScore", "liquidityScore", "thesisScore")]

        def mat(ds):
            arr = np.array([[0.0 if (d[c] is None or (isinstance(d[c], float) and math.isnan(d[c]))) else float(d[c])
                             for c in Xcols] for d in ds], float)
            return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)

        ytr = np.array([d["win"] for d in tr], float)
        yte = np.array([d["win"] for d in te], float)
        mu, sd = mat(tr).mean(0), mat(tr).std(0)
        sd = np.where(sd < 1e-6, 1.0, sd)          # constant columns: pass through unscaled
        Xtr = np.clip((mat(tr) - mu) / sd, -10.0, 10.0)
        Xte = np.clip((mat(te) - mu) / sd, -10.0, 10.0)
        print("  %s: train n=%d test n=%d  (test base wr %.1f%%)" % (label, len(tr), len(te), yte.mean() * 100))
        print("   incumbent raw_composite   AUC=%.3f  logloss=%.4f" % (
            auc(yte, -mat(te)[:, Xcols.index("raw_composite")]), logloss(yte, np.clip(mat(te)[:, Xcols.index("raw_composite")] / 100.0, 1e-3, 1 - 1e-3))))
        print("   incumbent copyScore       AUC=%.3f" % auc(yte, -mat(te)[:, Xcols.index("copyScore")]))
        beta = fit_logreg(Xtr, ytr, l2=2.0)
        pte = predict(beta, Xte)
        ptr = predict(beta, Xtr)
        print("   ridge logistic            AUC=%.3f  logloss=%.4f (train AUC=%.3f, train logloss=%.4f)" % (
            auc(yte, pte), logloss(yte, pte), auc(ytr, ptr), logloss(ytr, ptr)))
        top = np.argsort(-np.abs(beta[1:]))[:8]
        print("   largest |coef|: %s" % ", ".join("%s %+0.2f" % (Xcols[i], beta[1 + i]) for i in top))
        print("   NOTE: wallet_* columns are WalletProfile CURRENT values (not point-in-time) -> optimistic.")


if __name__ == "__main__":
    main()
