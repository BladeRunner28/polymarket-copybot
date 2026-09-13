#!/usr/bin/env python3
"""Pilot #2: same separation question, but on the FULL resolved paper-trade book.

Pilot #1 (scripts/pilot-score-separation.py) used the OutcomeReview label set:
688 rows, only 10 wallets, all created inside one ~24h window (2026-07-14/15).
This script uses what the DB actually has: every resolved/closed Polymarket
paper trade that carries a DecisionJournal (stored component scores, copyScore,
confidence, rule set version), i.e. ~9.6k decisions over ~60 days and ~188
wallets, with entry price and booked realizedPnl.

Target: did the copied position make money (realizedPnl > 0).
Read-only. Writes data/pilot-score-separation-papers.json.

Usage:  ./venv-calib/bin/python scripts/pilot-score-separation-papers.py
"""

import json
import math
import os
import sqlite3
import zlib

import numpy as np

import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
OUT = os.path.join(ROOT, "data", "pilot-score-separation-papers.json")

_spec = importlib.util.spec_from_file_location(
    "pilot", os.path.join(ROOT, "scripts", "pilot-score-separation.py"))
pilot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pilot)
auc = pilot.auc
fit_logit = pilot.fit_logit
predict = pilot.predict
calib = pilot.calib_slope_intercept

K_FOLDS = 5
LAMBDAS = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0]


def load():
    con = sqlite3.connect(DB)
    rows = con.execute(
        """
        SELECT pt.id, pt.botId, pt.walletAddress, pt.marketId, pt.entryPrice,
               pt.realizedPnl, pt.simulatedPositionSize, pt.openedAt, pt.closedAt,
               d.copyScore, d.confidence, d.walletQualityScore, d.categoryFitScore,
               d.entryTimingScore, d.spreadScore, d.liquidityScore, d.thesisScore,
               d.ruleSetVersion
        FROM PaperTrade pt
        JOIN DecisionJournal d ON d.id = pt.decisionJournalId
        WHERE pt.status IN ('resolved','closed') AND pt.isDemo = 0
          AND pt.venue != 'Kalshi' AND pt.realizedPnl IS NOT NULL
          AND pt.entryPrice > 0 AND pt.entryPrice < 1
        """
    ).fetchall()
    con.close()
    return rows


def main():
    rows = load()
    recs = []
    for r in rows:
        (pid, bot, wallet, market, entry, pnl, size, opened, closed,
         cscore, conf, wq, cfit, etim, spr, liq, thes, rsv) = r
        recs.append(dict(id=pid, bot=bot, wallet=wallet, market=market,
                         entry=float(entry), pnl=float(pnl), size=float(size or 0),
                         copyScore=float(cscore), confidence=float(conf),
                         wq=float(wq), cfit=float(cfit), etim=float(etim),
                         spr=float(spr), liq=float(liq), thes=float(thes),
                         rsv=rsv, opened=opened))
    n = len(recs)
    y = np.array([1.0 if r["pnl"] > 0 else 0.0 for r in recs])
    pnl = np.array([r["pnl"] for r in recs])
    print(f"N resolved copies: {n}  win-rate(realizedPnl>0) {y.mean():.3f}  "
          f"mean ${pnl.mean():+.2f}/trade  sd ${pnl.std(ddof=1):.2f}")
    print(f"wallets {len({r['wallet'] for r in recs})}  markets {len({r['market'] for r in recs})}  "
          f"rule sets {sorted({r['rsv'] for r in recs if r['rsv'] is not None})}")

    # ---- ICC + design effect on the full book ----
    def icc_by(key):
        g = {}
        for i, r in enumerate(recs):
            g.setdefault(r[key], []).append(i)
        k = len(g); mbar = n / k; pbar = y.mean()
        msb = sum(len(v) * (y[v].mean() - pbar) ** 2 for v in g.values()) / (k - 1)
        msw = sum(sum((y[i] - y[v].mean()) ** 2 for i in v) for v in g.values()) / (n - k)
        v = max(0.0, (msb - msw) / (msb + (mbar - 1) * msw))
        de = 1 + (mbar - 1) * v
        return dict(groups=k, mean_cluster=round(mbar, 2), icc=round(v, 4),
                    design_effect=round(de, 2), effective_n=round(n / de, 1))

    icc_w = icc_by("wallet"); icc_m = icc_by("market")
    print(f"ICC(wallet) {icc_w}  ICC(market) {icc_m}")

    # ---- MDE ----
    sd = float(pnl.std(ddof=1))
    mde = {}
    for m in [688, 2000, 9642, 25000]:
        meff = m / icc_w["design_effect"]
        mde[m] = dict(m_eff=round(meff, 1), se=round(sd / math.sqrt(meff), 2),
                      mde_80pct=round(2.80 * sd / math.sqrt(meff), 2))

    rng = np.random.default_rng(17)
    groups_w = {}
    for i, r in enumerate(recs):
        groups_w.setdefault(r["wallet"], []).append(i)
    folds = np.array([zlib.crc32(r["market"].encode()) % K_FOLDS for r in recs])
    results = {}

    def per_fold(a_pred, fold_arr=None):
        fa = folds if fold_arr is None else fold_arr
        out = []
        for k in range(K_FOLDS):
            m = fa == k
            if y[m].sum() in (0, m.sum()):
                continue
            out.append(round(float(auc(y[m], a_pred[m])), 3))
        return out

    def report(name, pred, is_prob=True):
        a = float(auc(y, pred))
        b = float(np.mean((pred - y) ** 2))
        sl, ic = calib(y, pred) if is_prob else (float("nan"), float("nan"))
        pf = per_fold(np.asarray(pred))
        results[name] = dict(auc=round(a, 4), brier=round(b, 4),
                             calib_slope=round(sl, 3), calib_intercept=round(ic, 3),
                             per_fold_auc=pf,
                             per_fold_auc_mean=round(float(np.mean(pf)), 4))
        print(f"{name}: AUC={a:.3f} per-fold mean={np.mean(pf):.3f} "
              f"(min {min(pf):.2f}/max {max(pf):.2f}) Brier={b:.4f} slope={sl:.2f} icpt={ic:+.2f}")

    report("A_stored_copyScore", np.array([r["copyScore"] for r in recs]) / 100.0, is_prob=False)
    report("B_entry_price", np.array([r["entry"] for r in recs]), is_prob=False)

    def oof(M, inner_cv=True):
        pred = np.zeros(n)
        inner_all = np.array([zlib.crc32((r["market"] + "i").encode()) % 3 for r in recs])
        for k in range(K_FOLDS):
            te, tr = folds == k, folds != k
            mu, sdv = M[tr].mean(0), M[tr].std(0) + 1e-9
            Xtr, Xte = (M[tr] - mu) / sdv, (M[te] - mu) / sdv
            ytr, itr_all = y[tr], inner_all[tr]
            best, bestloss = None, np.inf
            for L in LAMBDAS:
                ll, tot = 0.0, 0
                for j in range(3):
                    ite, itr = itr_all == j, itr_all != j
                    if ite.sum() == 0 or itr.sum() == 0:
                        continue
                    w = fit_logit(Xtr[itr], ytr[itr], L)
                    pv = np.clip(predict(w, Xtr[ite]), 1e-9, 1 - 1e-9)
                    yv = ytr[ite]
                    ll += -np.sum(yv * np.log(pv) + (1 - yv) * np.log(1 - pv)); tot += yv.size
                if tot and ll / tot < bestloss:
                    bestloss, best = ll / tot, L
            w = fit_logit(Xtr, ytr, best)
            pred[te] = predict(w, Xte)
        return pred

    cols = ["wq", "cfit", "etim", "spr", "liq", "thes", "copyScore", "confidence"]
    Mc = np.array([[r[c] for c in cols] for r in recs]) / 100.0
    report("C_stored_components_ridge", oof(Mc))

    # price (logit) + size + execution scores: honest refit with only 5 inputs
    MD = np.array([[math.log(r["entry"] / (1 - r["entry"])), math.log1p(r["size"]),
                    r["spr"] / 100.0, math.log1p(max(r["liq"], 0)) / 10.0,
                    r["etim"] / 100.0] for r in recs])
    report("D_refit_price_plus_execution", oof(MD))

    # price-band lookup, OOF with Laplace smoothing (portable baseline)
    BANDS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 0.40),
             (0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90),
             (0.90, 0.97), (0.97, 1.01)]
    bidx = np.array([next((j for j, (lo, hi) in enumerate(BANDS) if lo <= r["entry"] < hi), 0)
                     for r in recs])
    prior = y.mean()
    pred_band = np.zeros(n)
    for k in range(K_FOLDS):
        te, tr = folds == k, folds != k
        for j in range(len(BANDS)):
            m = tr & (bidx == j)
            pred_band[te & (bidx == j)] = ((y[m].sum() + 10 * prior) / (m.sum() + 10)
                                           if m.sum() else prior)
    report("F_price_band_lookup_oof", pred_band)

    # excess return by EV gate (copy iff P(win) - entry - fee > 0), out-of-fold
    gate = {}
    for fee in [0.0, 0.01, 0.02, 0.03]:
        sel = np.where(pred_band - np.array([r["entry"] for r in recs]) > fee)[0]
        if len(sel) == 0:
            gate[fee] = dict(n=0); continue
        gate[fee] = dict(
            n=int(len(sel)), share=round(len(sel) / n, 3),
            winRate=round(float(y[sel].mean()), 4),
            meanEntry=round(float(np.mean([recs[i]["entry"] for i in sel])), 4),
            excess=round(float(y[sel].mean() - np.mean([recs[i]["entry"] for i in sel])), 4),
            realizedPnl=round(float(pnl[sel].sum()), 1),
            perTrade=round(float(pnl[sel].mean()), 2))
        print(f"EV gate fee={fee}: {gate[fee]}")

    # wallet-blocked evaluation of the EV gate
    loo = []
    for w_, v_ in groups_w.items():
        tr_i = [i for i in range(n) if i not in v_]
        if len(v_) < 5:
            continue
        prior_tr = y[tr_i].mean()
        tbl = {}
        for j in range(len(BANDS)):
            m = np.array([i in tr_i and bidx[i] == j for i in range(n)])
            tbl[j] = ((y[m].sum() + 10 * prior_tr) / (m.sum() + 10)) if m.sum() else prior_tr
        sel = [i for i in v_ if tbl[bidx[i]] - recs[i]["entry"] > 0.02]
        if not sel:
            loo.append(dict(wallet=w_[:10], n=len(v_), selected=0, perTrade=None))
            continue
        loo.append(dict(wallet=w_[:10], n=len(v_), selected=len(sel),
                        winRate=round(float(y[sel].mean()), 3),
                        meanEntry=round(float(np.mean([recs[i]["entry"] for i in sel])), 3),
                        perTrade=round(float(pnl[sel].mean()), 2),
                        pnl=round(float(pnl[sel].sum()), 1)))
    pos = [d for d in loo if (d.get("perTrade") or 0) > 0]
    neg = [d for d in loo if (d.get("perTrade") or 0) < 0]
    print(f"wallet-blocked EV gate: {len(pos)} wallets positive / {len(neg)} negative "
          f"(of {len(loo)} with n>=5)")

    out = dict(
        generated_for="drafts/scoring-fix-methods-20260913.md",
        source="PaperTrade resolved/closed, Polymarket, joined to DecisionJournal",
        n=n, base_win_rate=round(float(y.mean()), 4),
        mean_pnl=round(float(pnl.mean()), 2), sd_pnl=round(sd, 2),
        n_wallets=len({r["wallet"] for r in recs}), n_markets=len({r["market"] for r in recs}),
        per_bot={b: int(sum(1 for r in recs if r["bot"] == b)) for b in {r["bot"] for r in recs}},
        icc_wallet=icc_w, icc_market=icc_m, mde_table=mde,
        models=results, ev_gate=gate, wallet_blocked_gate=dict(per_wallet=loo,
                                                               wallets_positive=len(pos),
                                                               wallets_negative=len(neg)),
        note=("Target = realizedPnl > 0 on resolved copies (no hypothetical rows). "
              "Grouped CV by marketId, lambda by inner 3-fold CV on the training part. "
              "Read-only."),
    )
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
