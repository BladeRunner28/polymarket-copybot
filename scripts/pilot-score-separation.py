#!/usr/bin/env python3
"""Pilot: does ANY stored feature set separate copy outcomes? (read-only)

Companion measurement for drafts/scoring-fix-methods-20260913.md.

Builds the labeled decision set from the live DB
(OutcomeReview JOIN DecisionJournal JOIN ObservedTrade), then runs
grouped cross-validation (folds by marketId, to respect the 178-market /
10-wallet cluster structure) on three model classes:

  A. hand-weighted composite:      copyScore / confidence as-is
  B. price-only baseline:          logit(entry price) alone
  C. ridge-logistic refit:         price + size + liquidity + spread + ttr + wallet prior

Target is P(copied token wins) — a mechanically price-dependent quantity.
The trading-relevant quantity is the EXCESS RETURN (win_rate - price), so the
script also prints out-of-fold excess return per predicted-probability decile:
that is the number an admission/fee-aware gate would actually consume.

No sklearn: numpy + scipy only (venv-calib). Writes
data/pilot-scoring-separation.json. Does not touch the DB.
"""

import json
import math
import os
import sqlite3
import zlib
from collections import defaultdict

import numpy as np
from scipy.optimize import minimize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
OUT = os.path.join(ROOT, "data", "pilot-scoring-separation.json")
K_FOLDS = 5
LAMBDAS = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0]


def norm_label(s):
    if s is None:
        return None
    return "".join(ch for ch in str(s).upper() if ch.isalnum())


def auc(y, s):
    y = np.asarray(y)
    s = np.asarray(s, dtype=float)
    n1 = y.sum()
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    order = np.argsort(s)
    ranks = np.empty(len(s), dtype=float)
    ranks[order] = np.arange(1, len(s) + 1)
    # average ranks for ties
    _, inv, counts = np.unique(s, return_inverse=True, return_counts=True)
    for i, c in enumerate(counts):
        if c > 1:
            m = inv == i
            ranks[m] = ranks[m].mean()
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def fit_logit(X, y, lam):
    """L2-penalised logistic MLE. X excludes the intercept column."""
    n, d = X.shape
    Xd = np.hstack([np.ones((n, 1)), X])

    def obj(w):
        z = Xd @ w
        # stable log-loss
        ll = np.sum(np.logaddexp(0.0, z) - y * z) / n
        return ll + (lam / (2 * n)) * np.sum(w[1:] ** 2)

    def grad(w):
        z = Xd @ w
        p = 1.0 / (1.0 + np.exp(-z))
        g = Xd.T @ (p - y) / n
        g[1:] += (lam / n) * w[1:]
        return g

    res = minimize(obj, np.zeros(d + 1), jac=grad, method="L-BFGS-B",
                   options={"maxiter": 500})
    return res.x


def predict(w, X):
    Xd = np.hstack([np.ones((len(X), 1)), X])
    return 1.0 / (1.0 + np.exp(-(Xd @ w)))


def calib_slope_intercept(y, p):
    """Logit(p) -> y logistic regression (out-of-fold). slope<1 = overfit/too extreme."""
    p = np.clip(p, 1e-6, 1 - 1e-6)
    lp = np.log(p / (1 - p))
    X = (lp - lp.mean()).reshape(-1, 1)
    w = fit_logit(X, np.asarray(y, dtype=float), 0.0)
    return float(w[1]), float(w[0])


def load():
    con = sqlite3.connect(DB)
    rows = con.execute(
        """
        SELECT o.id, o.simulatedPnl, o.finalOutcome, o.wasDecisionGood,
               d.decision, d.copyScore, d.confidence,
               d.walletQualityScore, d.categoryFitScore, d.entryTimingScore,
               d.spreadScore, d.liquidityScore, d.thesisScore,
               d.walletAddress, d.marketId, d.createdAt,
               t.outcome, t.side, t.walletEntryPrice, t.detectedPrice, t.size,
               t.marketCategory, t.timestamp
        FROM OutcomeReview o
        JOIN DecisionJournal d ON d.id = o.decisionJournalId
        JOIN ObservedTrade t ON t.id = d.observedTradeId
        WHERE o.wasDecisionGood IS NOT NULL
        """
    ).fetchall()
    con.close()
    return rows


def main():
    rows = load()
    recs = []
    for r in rows:
        (rid, pnl, final, good, dec, cscore, conf, wq, cfit, etim, spr, liq, thes,
         wallet, market, created, outcome, side, wep, dp, size, cat, ts) = r
        won = 1 if (norm_label(final) and norm_label(final) == norm_label(outcome)) else 0
        p = float(dp or wep or 0.5)
        if not (0.0 < p < 1.0):
            continue
        # hypothetical $10 copy at detection price: 10*(1-p)/p on win, -10 on loss
        hypo = 10.0 * (1.0 - p) / p if won else -10.0
        recs.append(dict(
            id=rid, decision=dec, wallet=wallet, market=market, won=won,
            entry=p, size=float(size or 0.0), category=cat, ts=ts,
            copyScore=float(cscore), confidence=float(conf),
            wq=float(wq), cfit=float(cfit), etim=float(etim),
            spr=float(spr), liq=float(liq), thes=float(thes),
            pnl_real=(None if pnl is None else float(pnl)), hypo=hypo,
            good=int(bool(good)),
        ))

    n = len(recs)
    y = np.array([r["won"] for r in recs], dtype=float)
    print(f"N labeled rows with a usable price: {n}  (base win-rate {y.mean():.3f})")
    print(f"distinct markets: {len({r['market'] for r in recs})}  "
          f"distinct wallets: {len({r['wallet'] for r in recs})}")
    print(f"decisions: { {d: sum(1 for r in recs if r['decision'] == d) for d in {r['decision'] for r in recs} } }")

    # label consistency: does wasDecisionGood agree with the hypothetical copy PnL?
    agree = sum(1 for r in recs if (r["good"] == 1) == (r["hypo"] > 0))
    print(f"\nLABEL AUDIT: wasDecisionGood == sign(copy PnL) for {agree}/{n} rows "
          f"({agree / n:.1%}).  Disagreement = the stored label is NOT the trade outcome.")

    # ---------- fold assignment (grouped by market) ----------
    folds = np.array([zlib.crc32(r["market"].encode()) % K_FOLDS for r in recs])

    def out_of_fold(builder, lam=None):
        pred = np.zeros(n)
        for k in range(K_FOLDS):
            te = folds == k
            tr = ~te
            if lam is None:
                pred[te] = builder(None, tr, te)
            else:
                # inner CV on the training part to pick lambda
                best, bestloss = None, np.inf
                inner = np.array([zlib.crc32((recs[i]["market"] + "i").encode()) % 3
                                  for i in range(n)])
                for L in LAMBDAS:
                    ll = 0.0
                    for j in range(3):
                        ite = tr & (inner == j)
                        itr = tr & (inner != j)
                        Xtr, ytr = builder("X", itr, ite)
                        w = fit_logit(Xtr, ytr, L)
                        pv = np.clip(predict(w, builder("X", ite, ite)), 1e-9, 1 - 1e-9)
                        yv = y[ite]
                        ll += -np.mean(yv * np.log(pv) + (1 - yv) * np.log(1 - pv)) * yv.size
                    if ll < bestloss:
                        bestloss, best = ll, L
                Xtr = builder("X", tr, tr)
                w = fit_logit(Xtr, y[tr], best)
                pred[te] = predict(w, builder("X", te, te))
        return pred

    results = {}
    rng = np.random.default_rng(7)

    def boot_auc_ci(pred, n_boot=1000):
        """Percentile bootstrap CI on pooled OOF AUC (resample rows)."""
        vals = []
        idx = np.arange(n)
        for _ in range(n_boot):
            b = rng.choice(idx, size=n, replace=True)
            if y[b].sum() in (0, len(b)):
                continue
            vals.append(auc(y[b], pred[b]))
        if not vals:
            return (float("nan"), float("nan"))
        return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))

    def per_fold_auc(pred):
        out = []
        for k in range(K_FOLDS):
            m = folds == k
            if y[m].sum() in (0, m.sum()):
                continue
            out.append(auc(y[m], pred[m]))
        return out

    def report(name, pred, is_prob=True, do_boot=True):
        a = auc(y, pred)
        b = float(np.mean((pred - y) ** 2))
        sl, ic = calib_slope_intercept(y, pred) if is_prob else (float("nan"), float("nan"))
        pf = per_fold_auc(pred)
        lo, hi = boot_auc_ci(pred) if do_boot else (float("nan"), float("nan"))
        # excess return by predicted decile (the decision-relevant view)
        q = np.quantile(pred, np.linspace(0, 1, 6))
        dec = np.clip(np.digitize(pred, q[1:-1]), 0, 4)
        buckets = []
        for d in range(5):
            m = dec == d
            if m.sum() == 0:
                continue
            buckets.append(dict(
                bucket=d + 1, n=int(m.sum()),
                meanP=round(float(pred[m].mean()), 4),
                winRate=round(float(y[m].mean()), 4),
                meanEntry=round(float(np.mean([recs[i]["entry"] for i in np.where(m)[0]])), 4),
                excess=round(float(y[m].mean() - np.mean([recs[i]["entry"] for i in np.where(m)[0]])), 4),
                hypoPnl=round(float(sum(recs[i]["hypo"] for i in np.where(m)[0])), 1),
            ))
        results[name] = dict(auc=round(a, 4), auc_ci95=[round(lo, 4), round(hi, 4)],
                             per_fold_auc=[round(v, 3) for v in pf],
                             per_fold_auc_mean=round(float(np.mean(pf)), 4) if pf else None,
                             brier=None if not is_prob else round(b, 4),
                             calib_slope=None if not is_prob else round(sl, 3),
                             calib_intercept=None if not is_prob else round(ic, 3),
                             deciles=buckets)
        extra = f"  Brier={b:.4f}  calib slope={sl:.2f}  intercept={ic:+.2f}" if is_prob else "  (rank score — no Brier/calibration)"
        pf_s = "/".join(f"{v:.2f}" for v in pf)
        print(f"\n{name}: AUC={a:.3f} [{lo:.3f},{hi:.3f}]  per-fold={pf_s} (mean {np.mean(pf):.3f}){extra}")
        for bk in buckets:
            print(f"   d{bk['bucket']}: n={bk['n']:>3}  P̂={bk['meanP']:.3f}  win={bk['winRate']:.3f} "
                  f"entry={bk['meanEntry']:.3f}  excess={bk['excess']:+.3f}  $-copyPnL={bk['hypoPnl']:+.0f}")

    # A. stored composite
    report("A_stored_copyScore", np.array([r["copyScore"] for r in recs]) / 100.0, is_prob=False)

    # B. entry price alone (market baseline)
    report("B_entry_price_higher_is_win", np.array([r["entry"] for r in recs]), is_prob=False)

    # C. the six stored components, standardized, ridge-logistic
    cols = ["wq", "cfit", "etim", "spr", "liq", "thes", "copyScore", "confidence"]
    Mc = np.array([[recs[i][c] for c in cols] for i in range(n)], dtype=float) / 100.0

    inner_all = np.array([zlib.crc32((r["market"] + "i").encode()) % 3 for r in recs])

    def oof_matrix(M, lam=None, inner_cv=True):
        pred = np.zeros(n)
        for k in range(K_FOLDS):
            te, tr = folds == k, folds != k
            mu, sd = M[tr].mean(0), M[tr].std(0) + 1e-9
            Xtr, Xte = (M[tr] - mu) / sd, (M[te] - mu) / sd
            ytr = y[tr]
            inner_tr = inner_all[tr]
            if inner_cv:
                best, bestloss = None, np.inf
                for L in LAMBDAS:
                    ll, tot = 0.0, 0
                    for j in range(3):
                        ite, itr = inner_tr == j, inner_tr != j
                        if ite.sum() == 0 or itr.sum() == 0:
                            continue
                        w = fit_logit(Xtr[itr], ytr[itr], L)
                        pv = np.clip(predict(w, Xtr[ite]), 1e-9, 1 - 1e-9)
                        yv = ytr[ite]
                        ll += -np.sum(yv * np.log(pv) + (1 - yv) * np.log(1 - pv))
                        tot += yv.size
                    if tot and ll / tot < bestloss:
                        bestloss, best = ll / tot, L
                lam_used = best
            else:
                lam_used = lam
            w = fit_logit(Xtr, ytr, lam_used)
            pred[te] = predict(w, Xte)
        return pred

    # F. price-band lookup, out-of-fold with Laplace smoothing (the portable baseline:
    #    a table of band -> win rate is what a TS scorer can consume with zero deps)
    BANDS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 0.40),
             (0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90),
             (0.90, 0.97), (0.97, 1.01)]
    prior = y.mean()
    band_of = np.array([next((i for i, (lo, hi) in enumerate(BANDS) if lo <= r["entry"] < hi), 0)
                        for r in recs])
    pred_band = np.zeros(n)
    for k in range(K_FOLDS):
        te, tr = folds == k, folds != k
        for b in range(len(BANDS)):
            m = tr & (band_of == b)
            pred_band[te & (band_of == b)] = ((y[m].sum() + 10 * prior) / (m.sum() + 10)
                                             if m.sum() else prior)
    report("F_price_band_lookup_oof", pred_band)

    report("C_stored_components_ridge", oof_matrix(Mc))

    # D. honest refit: price (logit) + log size + log liquidity + spread-score + ttr-proxy
    def build_D():
        X = []
        for r in recs:
            lp = math.log(r["entry"] / (1 - r["entry"]))
            X.append([
                lp,
                math.log1p(r["size"]),
                r["spr"] / 100.0,
                math.log1p(max(r["liq"], 0)) / 10.0,
                r["etim"] / 100.0,
            ])
        return np.array(X, dtype=float)

    MD = build_D()
    report("D_refit_price_plus_execution", oof_matrix(MD))

    # E. add wallet prior (leave-one-wallet-out win rate = no leakage across wallets)
    priors = {}
    for r in recs:
        others = [q["won"] for q in recs if q["wallet"] != r["wallet"]]
        priors[r["id"]] = float(np.mean(others)) if others else 0.5
    ME = np.hstack([MD, np.array([[priors[r["id"]]] for r in recs])])
    report("E_refit_plus_wallet_prior", oof_matrix(ME))

    # leave-one-wallet-out evaluation of the best-class model (generalisation across wallets)
    pred_w = np.zeros(n)
    for w in {r["wallet"] for r in recs}:
        te = np.array([r["wallet"] == w for r in recs])
        tr = ~te
        mu, sd = ME[tr].mean(0), ME[tr].std(0) + 1e-9
        wgt = fit_logit((ME[tr] - mu) / sd, y[tr], 0.3)
        pred_w[te] = predict(wgt, (ME[te] - mu) / sd)
    report("E_leave_one_wallet_out", pred_w)

    # per-wallet label sanity (the cluster that dominates the sample)
    print("\nPer-wallet label vs copy-PnL agreement:")
    for w in sorted({r["wallet"] for r in recs}, key=lambda w: -sum(1 for r in recs if r["wallet"] == w)):
        sub = [r for r in recs if r["wallet"] == w]
        ag = sum(1 for r in sub if (r["good"] == 1) == (r["hypo"] > 0)) / len(sub)
        print(f"   {w[:10]}… n={len(sub):>3} win={np.mean([r['won'] for r in sub]):.2f} "
              f"label-agree={ag:.2f} meanCopyPnL=${np.mean([r['hypo'] for r in sub]):+.2f}")

    # ---------------- supplementary: clustering, cluster-CI, MDE, wallet-blocked gate ----------------
    def icc_by(key):
        g = {}
        for i, r in enumerate(recs):
            g.setdefault(r[key], []).append(i)
        k = len(g)
        mbar = n / k
        pbar = y.mean()
        msb = sum(len(v) * (y[v].mean() - pbar) ** 2 for v in g.values()) / (k - 1)
        msw = sum(sum((y[i] - y[v].mean()) ** 2 for i in v) for v in g.values()) / (n - k)
        icc_v = max(0.0, (msb - msw) / (msb + (mbar - 1) * msw))
        de = 1 + (mbar - 1) * icc_v
        return dict(groups=k, mean_cluster=round(mbar, 2), icc=round(icc_v, 4),
                    design_effect=round(de, 2), effective_n=round(n / de, 1))

    wkeys = [r["wallet"] for r in recs]
    groups_w = {}
    for i, w in enumerate(wkeys):
        groups_w.setdefault(w, []).append(i)

    def cluster_boot(vals, B=2000, stat=np.mean):
        ks = list(groups_w)
        out = []
        for _ in range(B):
            pick = rng.choice(ks, size=len(ks), replace=True)
            sel = np.array([i for p_ in pick for i in groups_w[p_]])
            out.append(stat(vals[sel]))
        return [round(float(v), 3) for v in np.percentile(out, [2.5, 97.5])]

    pnl = np.array([r["hypo"] for r in recs])
    sd = float(pnl.std(ddof=1))
    de_w = icc_by("wallet")["design_effect"]
    mde = {}
    for m in [141, 300, 688, 1500, 3000]:
        meff = m / de_w
        mde[m] = dict(se=round(sd / math.sqrt(meff), 2), mde_80pct=round(2.80 * sd / math.sqrt(meff), 2))
    supp = dict(
        icc_wallet=icc_by("wallet"), icc_market=icc_by("market"),
        per_decision_pnl_sd=round(sd, 2), per_decision_pnl_mean=round(float(pnl.mean()), 2),
        mean_pnl_ci_wallet_cluster=cluster_boot(pnl),
        mde_table=mde,
    )
    aucs = []
    for _ in range(1000):
        pick = rng.choice(list(groups_w), size=len(groups_w), replace=True)
        sel = np.array([i for p_ in pick for i in groups_w[p_]])
        if y[sel].sum() in (0, len(sel)):
            continue
        aucs.append(auc(y[sel], pred_band[sel]))
    supp["band_model_auc_cluster_ci"] = [round(float(np.percentile(aucs, 2.5)), 3),
                                         round(float(np.percentile(aucs, 97.5)), 3)]
    # wallet-blocked EV gate (band table fit on the other 9 wallets)
    gr = {}
    for i, r in enumerate(recs):
        gr.setdefault(r["wallet"], []).append(i)
    loo = []; sel_idx = []
    for w_, v_ in gr.items():
        tr_i = [i for i in range(n) if i not in v_]
        prior_tr = y[tr_i].mean()
        tbl = {}
        for j in range(len(BANDS)):
            m = [i for i in tr_i if band_of[i] == j]
            tbl[j] = ((y[m].sum() + 10 * prior_tr) / (len(m) + 10)) if m else prior_tr
        sel = [i for i in v_ if tbl[band_of[i]] - recs[i]["entry"] > 0.02]
        if not sel:
            loo.append(dict(wallet=w_[:10], n=len(v_), selected=0))
            continue
        sel_idx += sel
        loo.append(dict(wallet=w_[:10], n=len(v_), selected=len(sel),
                        winRate=round(float(y[sel].mean()), 3),
                        meanEntry=round(float(np.mean([recs[i]["entry"] for i in sel])), 3),
                        excess=round(float(y[sel].mean() - np.mean([recs[i]["entry"] for i in sel])), 3),
                        copyPnl=round(float(sum(recs[i]["hypo"] for i in sel)), 1)))
    if sel_idx:
        supp["loo_ev_gate"] = dict(
            per_wallet=loo, selected=len(sel_idx),
            aggregate=dict(
                winRate=round(float(y[sel_idx].mean()), 3),
                meanEntry=round(float(np.mean([recs[i]["entry"] for i in sel_idx])), 3),
                excess=round(float(y[sel_idx].mean() - np.mean([recs[i]["entry"] for i in sel_idx])), 3),
                copyPnl=round(float(sum(recs[i]["hypo"] for i in sel_idx)), 1),
                perTrade=round(float(np.mean([recs[i]["hypo"] for i in sel_idx])), 2),
                wallets_positive=int(sum(1 for d in loo if d.get("copyPnl", 0) > 0)),
                wallets_negative=int(sum(1 for d in loo if d.get("copyPnl", 0) < 0)),
            ))
    # price-band win rate with and without the three largest wallets (cluster sensitivity)
    big3 = [w for w, _ in sorted(gr.items(), key=lambda kv: -len(kv[1]))[:3]]
    keep = [i for i in range(n) if recs[i]["wallet"] not in big3]
    stab = []
    for j, (lo, hi) in enumerate(BANDS):
        m_all = band_of == j
        m_keep = np.array([i in set(keep) and band_of[i] == j for i in range(n)])
        stab.append(dict(band=f"{lo:.2f}-{hi:.2f}",
                         all_n=int(m_all.sum()),
                         all_win=round(float(y[m_all].mean()), 3) if m_all.sum() else None,
                         excl_win=round(float(y[m_keep].mean()), 3) if m_keep.sum() else None,
                         excl_n=int(m_keep.sum())))
    supp["band_stability_excl_top3_wallets"] = dict(excluded=[w[:10] for w in big3], bands=stab)
    supp["mean_entry_price"] = round(float(np.mean([r["entry"] for r in recs])), 4)

    print("\n--- supplementary ---")
    print(f"ICC(wallet)={supp['icc_wallet']}  ICC(market)={supp['icc_market']}")
    print(f"mean entry price in label set {supp['mean_entry_price']}")
    print(f"OOF band-model AUC {auc(y, pred_band):.3f}, wallet-cluster 95% CI {supp['band_model_auc_cluster_ci']}")
    if "loo_ev_gate" in supp:
        print(f"wallet-blocked EV gate: n={supp['loo_ev_gate']['selected']} of {n}, "
              f"per-trade ${supp['loo_ev_gate']['aggregate']['perTrade']:+.2f}, "
              f"{supp['loo_ev_gate']['aggregate']['wallets_positive']} wallets positive / "
              f"{supp['loo_ev_gate']['aggregate']['wallets_negative']} negative")

    out = dict(
        generated_for="drafts/scoring-fix-methods-20260913.md",
        n=n, base_win_rate=round(float(y.mean()), 4),
        n_markets=len({r["market"] for r in recs}), n_wallets=len({r["wallet"] for r in recs}),
        label_agreement=dict(agree=agree, n=n, rate=round(agree / n, 4)),
        models=results, supplementary=supp,
        note=("Grouped CV by marketId (5 folds); lambda chosen by inner 3-fold CV on the "
              "training part only. Target = P(copied token wins). Excess = winRate - mean entry. "
              "Read-only; no DB writes."),
    )
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
