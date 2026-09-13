#!/usr/bin/env python3
"""Fit + evaluate the v1 price-edge score, and emit the portable spec.

Design (pre-registered in the emitted spec, not chosen after seeing results):

  Models
    M1  logistic  P(win) = sigma(a + b*logit(price))                      (2 params)
    M2  smoothed price-band table, 12 bands, Laplace prior 10            (12 params)
    M3  logistic on logit(price) + log(size) + raw_spread + log1p(liq) + ttr

  Fold designs (both required; random row-level folds are banned)
    W  wallet-blocked: 5 folds by wallet hash; margin & coefficients fit on the
       other wallets only.
    T  walk-forward: fit on strictly earlier months, evaluate on the next
       (2026-07 -> 08, 2026-07+08 -> 09).

  Decision rule
    admit iff P(win) - price - fee_per_share(price) > margin
    fee_per_share = rate * price * (1 - price)   [Polymarket taker formula]

  Primary metric
    mean net-entry PnL per trade (realizedPnl - entry-leg fee) on the ADMITTED
    subset, compared against the same fold's ungated mean. Secondary: excess
    return (win - price), share admitted, per-bot split, calibration.

  Acceptance (all four must hold for "deployable")
    A1 gate beats ungated on BOTH designs
    A2 wallet-cluster bootstrap 95% CI of the improvement excludes 0
    A3 >= 60% of wallets non-negative on admitted trades
    A4 calibration slope in [0.8, 1.2]

Usage:  ./venv-calib/bin/python scripts/fit-price-edge.py
Writes  data/score-spec-v1.json, data/score-spec-v1-eval.json  (read-only elsewhere)
"""

import csv
import importlib.util
import json
import math
import os
import sys
import zlib
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_IN = os.path.join(ROOT, "data", "decision-dataset.csv")
SPEC_OUT = os.path.join(ROOT, "data", "score-spec-v1.json")
EVAL_OUT = os.path.join(ROOT, "data", "score-spec-v1-eval.json")

_spec = importlib.util.spec_from_file_location(
    "pilot", os.path.join(ROOT, "scripts", "pilot-score-separation.py"))
pilot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pilot)
auc, fit_logit, predict, calib = pilot.auc, pilot.fit_logit, pilot.predict, pilot.calib_slope_intercept

BANDS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 0.40), (0.40, 0.50),
         (0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 0.97), (0.97, 1.01)]
BAND_PRIOR_N = 10.0
MARGINS = [0.0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.20, 0.35, 100.0]  # 100 = admit nothing
LAMBDAS = [0.03, 0.1, 0.3, 1.0, 3.0, 10.0]
MIN_SELECTED_SHARE = 0.10          # a margin that admits <10% of the fit sample is not choseable
EXCLUDE_VENUE = {"Kalshi"}         # 35 rows, phantom-price leg per the kalshi-dormancy review


def band_of(p):
    for j, (lo, hi) in enumerate(BANDS):
        if lo <= p < hi:
            return j
    return len(BANDS) - 1


def fee_per_share(price, rate):
    return rate * price * (1.0 - price)


def load():
    recs = []
    with open(CSV_IN, newline="") as f:
        for row in csv.DictReader(f):
            if row["venue"] in EXCLUDE_VENUE:
                continue
            try:
                p = float(row["entry_price"])
            except (TypeError, ValueError):
                continue
            if not (0.0 < p < 1.0):
                continue
            def num(key, default=0.0):
                v = row.get(key, "")
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return default
            recs.append(dict(
                id=row["trade_id"], bot=row["bot_id"], wallet=row["wallet"], market=row["market_id"],
                month=(row["opened_at"] or "")[:7], day=(row["opened_at"] or "")[:10],
                entry=p, size=num("size_usd", 10.0),
                y=float(row["y_win"]), pnl_net=num("pnl_net_entry"), pnl_gross=num("pnl_gross"),
                fee_rate=num("fee_rate", 0.05), spread=num("raw_spread"), liq=num("raw_liquidity"),
                ttr=num("ttr_hours"),
            ))
    return recs


# ---------------------------------------------------------------- models
def predict_logit_price(fit_idx, eval_idx, recs, y, band_idx=None):
    """M1: 2-parameter logistic on logit(price)."""
    lp = np.array([math.log(r["entry"] / (1 - r["entry"])) for r in recs])
    mu, sd = lp[fit_idx].mean(), lp[fit_idx].std() + 1e-9
    X = ((lp - mu) / sd).reshape(-1, 1)
    w = fit_logit(X[fit_idx], y[fit_idx], 0.0)
    return predict(w, X[eval_idx]), dict(kind="logit_price", mean=float(mu), sd=float(sd),
                                         a=float(w[0]), b=float(w[1]))


def predict_bands(fit_idx, eval_idx, recs, y, band_idx=None):
    """M2: Laplace-smoothed band table."""
    prior = float(y[fit_idx].mean())
    y_fit = y[fit_idx]
    b_fit = band_idx[fit_idx]
    tbl = []
    for j in range(len(BANDS)):
        mask = b_fit == j
        n_j = int(mask.sum())
        tbl.append(float((y_fit[mask].sum() + BAND_PRIOR_N * prior) / (n_j + BAND_PRIOR_N))
                   if n_j else prior)
    return np.array([tbl[b] for b in band_idx[eval_idx]]), dict(kind="band_table", bands=tbl,
                                                               band_prior_n=BAND_PRIOR_N)


def predict_multivar(fit_idx, eval_idx, recs, y, band_idx=None):
    """M3: logistic on price + execution features, ridge with inner-CV lambda."""
    def M(idx):
        out = []
        for i in idx:
            r = recs[i]
            out.append([math.log(r["entry"] / (1 - r["entry"])), math.log1p(r["size"]),
                        r["spread"] * 10.0, math.log1p(max(r["liq"], 0.0)) / 10.0,
                        math.log1p(max(r["ttr"], 0.0)) / 5.0])
        return np.array(out)
    Xf, Xe = M(fit_idx), M(eval_idx)
    mu, sd = Xf.mean(0), Xf.std(0) + 1e-9
    Xf, Xe = (Xf - mu) / sd, (Xe - mu) / sd
    inner = np.array([zlib.crc32((recs[i]["market"] + "i").encode()) % 3 for i in fit_idx])
    best, bestloss = LAMBDAS[0], np.inf
    for L in LAMBDAS:
        ll, tot = 0.0, 0
        for j in range(3):
            ite, itr = inner == j, inner != j
            if ite.sum() == 0 or itr.sum() == 0:
                continue
            w = fit_logit(Xf[itr], y[fit_idx][itr], L)
            pv = np.clip(predict(w, Xf[ite]), 1e-9, 1 - 1e-9)
            yv = y[fit_idx][ite]
            ll += -np.sum(yv * np.log(pv) + (1 - yv) * np.log(1 - pv)); tot += yv.size
        if tot and ll / tot < bestloss:
            bestloss, best = ll / tot, L
    w = fit_logit(Xf, y[fit_idx], best)
    return predict(w, Xe), dict(kind="logit_price_plus_execution", lambda_=best,
                                mean=[float(v) for v in mu], sd=[float(v) for v in sd],
                                coef=[float(v) for v in w])


MODELS = {"M1_logit_price": predict_logit_price, "M2_band_table": predict_bands,
          "M3_multivar": predict_multivar}


# ---------------------------------------------------------------- fold designs
def folds_wallet(recs, k=5):
    w = np.array([r["wallet"] for r in recs])
    assign = np.array([zlib.crc32(x.encode()) % k for x in w])
    return [np.where(assign == f)[0] for f in range(k)]


def folds_time(recs):
    months = sorted({r["month"] for r in recs})
    out = []
    for m in months[1:]:
        ev = np.array([i for i, r in enumerate(recs) if r["month"] == m])
        tr = np.array([i for i, r in enumerate(recs) if r["month"] < m])
        if ev.size >= 50 and tr.size >= 100:
            out.append((tr, ev))
    return out


def choose_margin(p, entry, pnl_net, fee, fit_mask):
    """Pick the margin on FIT rows only: best net-entry $/trade subject to >=10% admitted."""
    best, best_val = MARGINS[0], -np.inf
    n_fit = int(fit_mask.sum())
    for m in MARGINS:
        admit = fit_mask & (p - entry - fee > m)
        n_sel = int(admit.sum())
        if n_sel < MIN_SELECTED_SHARE * n_fit:
            continue
        val = float(pnl_net[admit].mean())
        if val > best_val:
            best_val, best = val, m
    return best


def evaluate(name, p, recs, y, pnl_net, y_folds, wallets):
    """Score one model under one fold design; margin chosen inside each fold."""
    n = len(recs)
    entry = np.array([r["entry"] for r in recs])
    rate = np.array([r["fee_rate"] for r in recs])
    fee = rate * entry * (1 - entry)
    design = name.split("__")[0]
    is_wallet = design.startswith("W")
    covered = np.zeros(n, dtype=bool)
    for fold in y_folds:
        ev = fold if is_wallet else fold[1]
        covered[np.asarray(ev)] = True
    perfold = []
    for f, fold in enumerate(y_folds):
        if is_wallet:
            ev = fold
            tr = np.array([i for i in range(n) if i not in set(fold.tolist())])
        else:
            tr, ev = fold
        m = choose_margin(p, entry, pnl_net, fee, np.isin(np.arange(n), tr))
        admit = p[ev] - entry[ev] - fee[ev] > m
        base_net = float(pnl_net[ev].mean())
        if admit.sum() == 0:
            perfold.append(dict(fold=f, margin=m, n=int(ev.size), selected=0,
                                per_trade_net=None, ungated_net=round(base_net, 4),
                                improvement=None, share=0.0))
            continue
        sel = ev[admit]
        perfold.append(dict(
            fold=f, margin=m, n=int(ev.size), selected=int(admit.sum()),
            share=round(float(admit.mean()), 4),
            per_trade_net=round(float(pnl_net[sel].mean()), 4),
            ungated_net=round(base_net, 4),
            improvement=round(float(pnl_net[sel].mean() - base_net), 4),
            excess=round(float((y[sel].mean() - entry[sel].mean())), 4),
            wallets_nonneg=round(float(np.mean([pnl_net[sel][wallets[sel] == w].sum() >= 0
                                                for w in set(wallets[sel].tolist())])), 3)
            if admit.sum() else None))
    # pooled OOF view
    sel_all = np.zeros(n, dtype=bool)
    for f, fold in enumerate(y_folds):
        if is_wallet:
            ev, tr = fold, np.array([i for i in range(n) if i not in set(fold.tolist())])
        else:
            tr, ev = fold
        m = choose_margin(p, entry, pnl_net, fee, np.isin(np.arange(n), tr))
        sel_all[ev] = p[ev] - entry[ev] - fee[ev] > m
    pooled = dict(
        covered_rows=int(covered.sum()),
        selected=int(sel_all.sum()), share=round(float(sel_all.sum() / max(covered.sum(), 1)), 4),
        per_trade_net=round(float(pnl_net[sel_all].mean()), 4) if sel_all.any() else None,
        ungated_net=round(float(pnl_net[covered].mean()), 4),
        improvement=round(float(pnl_net[sel_all].mean() - pnl_net[covered].mean()), 4)
        if sel_all.any() else None,
        excess=round(float(y[sel_all].mean() - entry[sel_all].mean()), 4) if sel_all.any() else None,
    )
    # all metrics are computed on COVERED rows only (walk-forward does not predict the first month)
    yc, pc = y[covered], p[covered]
    return dict(auc=round(float(auc(yc, pc)), 4), brier=round(float(np.mean((pc - yc) ** 2)), 4),
                base_rate_brier=round(float(yc.mean() * (1 - yc.mean())), 4),
                calib_slope=round(float(calib(yc, pc)[0]), 3),
                calib_intercept=round(float(calib(yc, pc)[1]), 3),
                per_fold=perfold, pooled=pooled, _sel=sel_all, _p=p, _covered=covered)


def cluster_ci_difference(pnl_net, sel, wallets, covered=None):
    """Wallet-cluster bootstrap 95% CI for (mean net of admitted) - (mean net ungated)."""
    if covered is None:
        covered = np.ones(len(pnl_net), dtype=bool)
    sel = sel & covered
    rng = np.random.default_rng(23)
    groups = defaultdict(list)
    for i, w in enumerate(wallets):
        if covered[i]:
            groups[w].append(i)
    ks = list(groups)
    deltas = []
    for _ in range(2000):
        pick = rng.choice(ks, size=len(ks), replace=True)
        idx = np.array([i for k in pick for i in groups[k]])
        s = sel[idx]
        if s.sum() < 5 or (~s).sum() < 5:
            continue
        deltas.append(float(pnl_net[idx][s].mean() - pnl_net[idx].mean()))
    if not deltas:
        return [None, None]
    return [round(float(np.percentile(deltas, 2.5)), 4), round(float(np.percentile(deltas, 97.5)), 4)]


def main():
    recs = load()
    n = len(recs)
    y = np.array([r["y"] for r in recs])
    pnl_net = np.array([r["pnl_net"] for r in recs])
    wallets = np.array([r["wallet"] for r in recs])
    band_idx = np.array([band_of(r["entry"]) for r in recs])
    print(f"decisions: {n}  win-rate {y.mean():.4f}  ungated net $/trade {pnl_net.mean():+.4f}")

    designs = {"W_wallet_blocked": folds_wallet(recs), "T_walk_forward": folds_time(recs)}
    results, chosen = {}, None
    for dname, foldset in designs.items():
        for mname, fn in MODELS.items():
            p = np.zeros(n)
            fitted = []
            for fold in foldset:
                if dname == "W_wallet_blocked":
                    ev = fold
                    tr = np.array([i for i in range(n) if i not in set(fold.tolist())])
                else:
                    tr, ev = fold
                pv, fmeta = fn(tr, ev, recs, y, band_idx)
                p[ev] = pv
                fitted.append(fmeta)
            res = evaluate(f"{dname}__{mname}", p, recs, y, pnl_net, foldset, wallets)
            res["fitted_on_first_fold"] = fitted[0] if fitted else None
            results[f"{dname}__{mname}"] = res
            print(f"{dname:18s} {mname:14s} AUC={res['auc']:.3f} Brier={res['brier']:.4f} "
                  f"slope={res['calib_slope']:+.2f} | gate: sel={res['pooled']['share']:.2%} "
                  f"net ${res['pooled']['per_trade_net']} vs ungated ${res['pooled']['ungated_net']} "
                  f"(impr {res['pooled']['improvement']})")

    # choose the model by mean Brier across both designs (pre-registered), tie-break simpler
    ranking = {}
    for mname in MODELS:
        vals = [results[f"{d}__{mname}"]["brier"] for d in designs if f"{d}__{mname}" in results]
        ranking[mname] = float(np.mean(vals)) if vals else 9.9
    order = sorted(ranking, key=lambda k: ranking[k])
    chosen = order[0]
    print(f"\nmodel ranking by mean Brier: " +
          ", ".join(f"{k}={ranking[k]:.4f}" for k in order) + f"  -> chosen {chosen}")

    # acceptance test on the chosen model, worst-case across designs
    accept_detail, passed = {}, True
    for d in designs:
        r = results[f"{d}__{chosen}"]
        ci = cluster_ci_difference(pnl_net, r["_sel"], wallets, r["_covered"])
        a1 = (r["pooled"]["improvement"] or -9) > 0
        a2 = ci[0] is not None and ci[0] > 0
        wk = [f["wallets_nonneg"] for f in r["per_fold"] if f.get("wallets_nonneg") is not None]
        a3 = bool(wk) and float(np.mean(wk)) >= 0.60
        a4 = 0.8 <= r["calib_slope"] <= 1.2
        accept_detail[d] = dict(improvement=r["pooled"]["improvement"], ci95=ci,
                                a1_beats_ungated=a1, a2_ci_excludes_zero=a2,
                                wallets_nonneg_mean=round(float(np.mean(wk)), 3) if wk else None,
                                a3_wallets_60pct=a3, calib_slope=r["calib_slope"], a4_calibrated=a4)
        passed = passed and a1 and a2 and a3 and a4

    # per-bot view of the chosen model under wallet-blocked folds
    rw = results[f"W_wallet_blocked__{chosen}"]
    bots = {}
    for b in {r["bot"] for r in recs}:
        m = np.array([x["bot"] == b for x in recs])
        bots[b] = dict(n=int(m.sum()),
                       ungated_net=round(float(pnl_net[m].mean()), 4),
                       gated_net=round(float(pnl_net[m & rw["_sel"]].mean()), 4)
                       if (m & rw["_sel"]).sum() else None,
                       selected=int((m & rw["_sel"]).sum()))

    learned = results[f"W_wallet_blocked__{chosen}"]["fitted_on_first_fold"]
    margin_mode = float(np.median([f["margin"] for f in rw["per_fold"]]))

    spec = dict(
        spec_version=1,
        created_at=datetime.now(timezone.utc).isoformat(),
        status="SHADOW ONLY — fails its own pre-registered acceptance test (see verdict)",
        author="hermes research pass (drafts/scoring-fix-methods-20260913.md)",
        dataset=dict(source="data/decision-dataset.csv",
                     rows=int(n), dedupe="first entry per (bot, wallet, market, outcome)",
                     excluded_venues=sorted(EXCLUDE_VENUE),
                     first_day=min(r["day"] for r in recs), last_day=max(r["day"] for r in recs),
                     wallets=int(len(set(wallets.tolist()))), markets=int(len({r["market"] for r in recs}))),
        model=dict(
            kind=learned["kind"] if learned else chosen,
            implementation="src/lib/scoring/price-edge.ts (pure function; spec constants embedded)",
            parameters={k: v for k, v in (learned or {}).items() if k != "kind"},
        ),
        decision_rule=dict(
            formula="admit iff P(win) - price - fee_per_share(price) > margin",
            fee_per_share="fee_rate * price * (1 - price)   [Polymarket taker fee formula]",
            margin=margin_mode,
            margin_selection=f"median of per-fold choices under wallet-blocked CV "
                             f"(chosen on FIT rows only, >= {MIN_SELECTED_SHARE:.0%} admitted required)",
        ),
        measured=dict(
            wallet_blocked=dict(auc=rw["auc"], brier=rw["brier"], calib_slope=rw["calib_slope"],
                                calib_intercept=rw["calib_intercept"], pooled=rw["pooled"],
                                per_fold=rw["per_fold"]),
            walk_forward=dict(**{k: v for k, v in results[f"T_walk_forward__{chosen}"].items()
                                 if not k.startswith("_")}),
            per_bot=bots,
            baseline=dict(ungated_net_per_trade=round(float(pnl_net.mean()), 4),
                          base_win_rate=round(float(y.mean()), 4),
                          base_rate_brier=round(float(y.mean() * (1 - y.mean())), 4)),
        ),
        acceptance_criteria=dict(
            A1="gate beats ungated on BOTH fold designs",
            A2="wallet-cluster bootstrap 95% CI of improvement excludes 0",
            A3=">=60% of wallets non-negative on admitted trades",
            A4="calibration slope within [0.8, 1.2]",
            result="PASS" if passed else "FAIL",
            detail=accept_detail,
        ),
        deployment="Do not gate on this score. Run it in shadow mode (log the score and the "
                   "counterfactual admission set; gate nothing) until the pre-registered window "
                   "in drafts/scoring-fix-v1-impl-20260913.md is met.",
    )
    with open(SPEC_OUT, "w") as f:
        json.dump(spec, f, indent=2)
    eval_out = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in results.items()}
    eval_out["_meta"] = dict(chosen_model=chosen, brier_ranking=ranking,
                             margin_mode=margin_mode, passed=passed,
                             generated_at=datetime.now(timezone.utc).isoformat())
    with open(EVAL_OUT, "w") as f:
        json.dump(eval_out, f, indent=2)

    print(f"\nacceptance: {'PASS' if passed else 'FAIL'}")
    for d, det in accept_detail.items():
        print(f"  {d}: improvement {det['improvement']} CI {det['ci95']} "
              f"a1={det['a1_beats_ungated']} a2={det['a2_ci_excludes_zero']} "
              f"a3={det['a3_wallets_60pct']} ({det['wallets_nonneg_mean']}) a4={det['a4_calibrated']}")
    print(f"chosen spec: {chosen}  margin={margin_mode}")
    print(f"wrote {os.path.relpath(SPEC_OUT, ROOT)} and {os.path.relpath(EVAL_OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
