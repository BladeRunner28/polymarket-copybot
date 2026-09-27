#!/usr/bin/env python3
"""U1 -- fit the conditional maker-fill model on the archive's cell aggregates.

Input : data/archive-analysis/fill-hazard-cells-<tag>.csv      (scripts/archive-fill-hazard-conditional.py)
Output: data/archive-analysis/fill-model-<tag>-<target>.json   (coefficients, metrics, C-200-weighted view)

WHAT IT FITS, AND AGAINST WHAT
  Cells are AGGREGATED BINOMIAL COUNTS (n fills, `hit` fills), so this is a binomial logistic GLM fitted
  by IRLS on the rate hit/n with weights = n. Not sklearn's LogisticRegression -- it rejects a continuous
  label outright ("Unknown label type: continuous") -- and not a per-fill logistic over 760M rows.
      y = P(the tape prints at or below print - delta within the horizon) = the fill event of a resting bid
  Pre-registered gate (card ml-u1-conditional-fill-model): beat the FLAT band-hazard baseline on
  Brier/log-loss, reproduce the adverse-selection sign, and print the expected markout beside the naive
  `intent - 0.02`. Baselines, all on the same holdout cells:
      flat           -- one number across the archive (71.1% @5m / 77.6% @1h published)
      band-flat      -- per-price-band rate, fitted on train bands only (the honest bar: price alone
                        explains most of it, so a model that cannot beat this has learned nothing but price)
      C-200-weighted -- band-flat re-weighted onto OUR settled C-200 entry-price mix (published 74.3% @5m)
  Holdout = deterministic hash split of CELLS (70/30). A WEAK check and labelled as such -- cells are not
  time-ordered, so the real test is the card's forward gate (>=50 measured C-200 legs, L2/tape-anchored).

Run with: venv-calib/bin/python scripts/fit-fill-model.py        (numpy only; no sklearn, no pandas)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, "data", "archive-analysis")

HOUR_BUCKETS = [(0, 5), (6, 11), (12, 17), (18, 23)]


def fnum(v):
    """CSV numerics from duckdb SUM()s arrive as a mix of '123' and '123.0' -> always go through float."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def hour_bucket(h):
    for i, (a, b) in enumerate(HOUR_BUCKETS):
        if a <= h <= b:
            return i
    return len(HOUR_BUCKETS) - 1


def side_idx(s):
    return {"buy": 0, "sell": 1}.get((s or "").lower(), 2)


def expit(z):
    """Numerically safe sigmoid (no overflow warnings on either tail)."""
    out = np.empty_like(z, dtype=np.float64)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    if (~pos).any():
        ez = np.exp(z[~pos])
        out[~pos] = ez / (1.0 + ez)
    return out


def design(rows, target_col, n_col="n", cats=None, include_cat=True):
    """One-hot + band-polynomial design matrix, weights, cell keys, and the filled-arm markout."""
    if cats is None and include_cat:
        counts = {}
        for r in rows:
            counts[r["category"]] = counts.get(r["category"], 0) + fnum(r[n_col])
        cats = [c for c, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:8]]
    cats = cats or []
    X, y, w, keys, mark = [], [], [], [], []
    for r in rows:
        n = fnum(r[n_col])
        if n <= 0:
            continue
        # y must be the RATE (hits / n): feeding raw counts makes the loss overflow on iteration 1.
        yv = fnum(r[target_col]) / n
        row = [1.0, float(r["band"]), float(r["band"]) ** 2]
        hb = hour_bucket(int(r["hour_et"]))
        row += [1.0 if hb == i else 0.0 for i in range(len(HOUR_BUCKETS))]
        row += [1.0 if int(fnum(r["size_b"])) == i else 0.0 for i in range(5)]
        row += [1.0 if int(fnum(r["vol_b"])) == i else 0.0 for i in range(5)]
        row += [1.0 if int(fnum(r["act_b"])) == i else 0.0 for i in range(5)]
        row += [1.0 if int(fnum(r["ttr_b"])) == i else 0.0 for i in range(-1, 6)]
        si = side_idx(r["tdir"])
        row += [1.0 if si == i else 0.0 for i in range(3)]
        if include_cat:
            row += [1.0 if r["category"] == c else 0.0 for c in cats]
        X.append(row); y.append(yv); w.append(n)
        hit1h = fnum(r["hit_d02_h3600"])
        mark.append(fnum(r["mo_fill_sum_h3600"]) / hit1h if hit1h > 0 else np.nan)
        keys.append((int(fnum(r["band"])), int(fnum(r["hour_et"])), r["size_b"], r["vol_b"], r["act_b"],
                     r["ttr_b"], r["tdir"], r["category"]))
    return (np.array(X, dtype=np.float64), np.array(y, dtype=np.float64),
            np.array(w, dtype=np.float64), keys, cats, np.array(mark, dtype=np.float64))


def fit_binomial_irls(X, y, n, lam=1e-4, iters=60, tol=1e-10):
    """Weighted binomial logistic regression by IRLS. Returns (beta, se, n_iter)."""
    p = X.shape[1]
    beta = np.zeros(p)
    XtWX = np.eye(p) * lam
    it = 0
    for it in range(1, iters + 1):
        eta = np.clip(X @ beta, -30.0, 30.0)
        mu = np.clip(expit(eta), 1e-9, 1 - 1e-9)
        W = n * mu * (1 - mu)
        z = eta + (y - mu) / (mu * (1 - mu))
        XtWX = X.T @ (X * W[:, None]) + np.eye(p) * lam
        rhs = X.T @ (W * z)
        try:
            new = np.linalg.solve(XtWX, rhs)
        except np.linalg.LinAlgError:
            new = np.linalg.lstsq(XtWX, rhs, rcond=None)[0]
        delta = float(np.max(np.abs(new - beta)))
        beta = new
        if delta < tol:
            break
    se = np.sqrt(np.maximum(np.diag(np.linalg.inv(XtWX)), 0.0))
    return beta, se, it


def brier(y, p, w):
    """FILLS-weighted Brier from aggregated cells.

    Cells hold counts, not labels: the `hit` fills score (p-1)^2 and the misses score p^2, so the
    per-fill Brier of a cell is y*(p-1)^2 + (1-y)*p^2. Scoring (p-y)^2 instead measures only the
    calibration of the cell mean and understates the error by ~30x (observed 0.006 vs the true 0.19
    at a flat-ish cell rate of 0.73) -- that mistake would have "passed" the gate on its own.
    """
    return float(np.sum(w * (y * (p - 1) ** 2 + (1 - y) * p ** 2)) / np.sum(w))


def logloss(y, p, w):
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return float(-np.sum(w * (y * np.log(p) + (1 - y) * np.log(1 - p))) / np.sum(w))


def hash_split(keys, frac=0.7):
    tr, te = [], []
    for i, k in enumerate(keys):
        h = int(hashlib.sha256(repr(k).encode()).hexdigest()[:8], 16) % 1000
        (tr if h < frac * 1000 else te).append(i)
    return np.array(tr), np.array(te)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="2026_01-2026_04-n20")
    ap.add_argument("--delta", type=float, default=0.02)
    ap.add_argument("--horizon", type=int, default=300)
    ap.add_argument("--min-fit-n", type=int, default=500,
                    help="keep only cells with n >= this from the fit (thin cells are noise)")
    ap.add_argument("--c200-mix", default=None,
                    help="JSON {band: count} of OUR settled C-200 entry prices; default = 2026-09-26 histogram")
    args = ap.parse_args()

    d = int(round(args.delta * 100))
    target = "hit_d%02d_h%d" % (d, args.horizon)
    path = os.path.join(OUTDIR, "fill-hazard-cells-%s.csv" % args.tag)
    if not os.path.exists(path):
        print("missing %s -- run archive-fill-hazard-conditional.py first" % path)
        return 1

    rows = list(csv.DictReader(open(path, newline="")))
    before = len(rows)
    rows = [r for r in rows if fnum(r["n"]) >= args.min_fit_n]
    print("cell filter n >= %d: %d -> %d cells" % (args.min_fit_n, before, len(rows)), flush=True)
    total_n = int(sum(fnum(r["n"]) for r in rows))
    print("cells %d | fills %s | target %s" % (len(rows), format(total_n, ","), target), flush=True)

    print("building design matrix ...", flush=True)
    X, y, w, keys, cats, mark = design(rows, target)
    tr, te = hash_split(keys)
    print("design %s | split %d train / %d test cells (%s / %s fills)"
          % (X.shape, len(tr), len(te), format(int(w[tr].sum()), ","), format(int(w[te].sum()), ",")), flush=True)

    flat = float(np.sum(w * y) / np.sum(w))
    band_arr = np.array([k[0] for k in keys])
    band_p = {}
    for b in range(10):
        m = band_arr == b
        if w[m].sum() > 0:
            band_p[b] = float(np.sum(w[m] * y[m]) / np.sum(w[m]))
    p_band = np.array([band_p.get(k[0], flat) for k in keys])   # band-flat rate on ALL cells (train metrics)

    print("fitting binomial logistic GLM (IRLS) ...", flush=True)
    beta, se, iters = fit_binomial_irls(X[tr], y[tr], w[tr])
    p_tr = expit(np.clip(X[tr] @ beta, -30, 30))
    p_te = expit(np.clip(X[te] @ beta, -30, 30))
    p_all = expit(np.clip(X @ beta, -30, 30))
    print("fit done in %d IRLS iterations" % iters, flush=True)

    band_tr = {}
    for b in range(10):
        m = np.array([keys[i][0] == b for i in tr])
        if m.any() and w[tr][m].sum() > 0:
            band_tr[b] = float(np.sum(w[tr][m] * y[tr][m]) / np.sum(w[tr][m]))
    p_band_te = np.array([band_tr.get(keys[i][0], flat) for i in te])
    p_band_all = np.array([band_tr.get(k[0], flat) for k in keys])

    metrics = {
        "flat_rate_archive": round(flat, 4),
        "test": {
            "n_fills": int(w[te].sum()), "cells": len(te),
            "brier_model": round(brier(y[te], p_te, w[te]), 5),
            "brier_flat": round(brier(y[te], np.full_like(p_te, flat), w[te]), 5),
            "brier_band_flat": round(brier(y[te], p_band_te, w[te]), 5),
            "logloss_model": round(logloss(y[te], p_te, w[te]), 5),
            "logloss_flat": round(logloss(y[te], np.full_like(p_te, flat), w[te]), 5),
            "logloss_band_flat": round(logloss(y[te], p_band_te, w[te]), 5),
        },
        "train": {
            "n_fills": int(w[tr].sum()),
            "brier_model": round(brier(y[tr], p_tr, w[tr]), 5),
            "brier_band_flat": round(brier(y[tr], p_band[tr], w[tr]), 5),
        },
    }

    # ---- C-200 price-mix view ---------------------------------------------------
    c200 = json.load(open(args.c200_mix)) if args.c200_mix else {
        "0": 90, "1": 98, "2": 182, "3": 195, "4": 442,
        "5": 408, "6": 226, "7": 205, "8": 85, "9": 76}
    c200 = {int(k): float(v) for k, v in c200.items()}
    tot_c200 = sum(c200.values())
    c200w = {b: v / tot_c200 for b, v in c200.items()}

    pred_by_band, obs_by_band = {}, {}
    for b in range(10):
        m = band_arr == b
        if not m.any():
            continue
        pred_by_band[b] = float(np.sum(w[m] * p_all[m]) / w[m].sum())
        obs_by_band[b] = float(np.sum(w[m] * y[m]) / w[m].sum())

    def weighted(rate_by_band):
        return sum(c200w[b] * rate_by_band.get(b, 0.0) for b in c200w)

    c200_view = {
        "band_shares": {str(k): round(v, 5) for k, v in c200w.items()},
        "flat_rate_all_fills": round(flat, 4),
        "band_flat_rate_weighted_to_c200_bands": round(weighted(obs_by_band), 4),
        "model_rate_weighted_to_c200_bands": round(weighted(pred_by_band), 4),
        "published_flat_reference": {"at_5m": 0.743, "at_1h": 0.811,
                                     "source": "fee-maker-calibration-20260925 §5 (C-200 price weighted, delta=0.02)"},
    }

    # ---- adverse selection on the same cells ------------------------------------
    filled_n = int(sum(fnum(r["hit_d%02d_h3600" % d]) for r in rows))
    future_n = int(sum(fnum(r["f3600"]) for r in rows))
    miss_n = future_n - filled_n
    mo_fill = sum(fnum(r["mo_fill_sum_h3600"]) for r in rows) / filled_n if filled_n else None
    mo_miss = sum(fnum(r["mo_miss_sum_h3600"]) for r in rows) / miss_n if miss_n else None
    markout = {
        "horizon_s": 3600,
        "filled": {"n": filled_n, "mean_px_end_minus_p": round(mo_fill, 5) if mo_fill is not None else None},
        "missed": {"n": miss_n, "mean_px_end_minus_p": round(mo_miss, 5) if mo_miss is not None else None},
        "reading": ("filled cases drift NEGATIVE (the market comes through us) while the missed cases are the "
                    "up-moves we forgo: the 2c credit is a fill model, not free money"),
    }

    # ---- conditional markout model: E[px_end - p | filled] -----------------------
    ok = np.isfinite(mark)
    wm = np.where((w * y)[ok] <= 0, 1e-9, (w * y)[ok])   # weight = FILLED fill count
    sw = np.sqrt(wm)
    mk_beta, *_ = np.linalg.lstsq(X[ok] * sw[:, None], mark[ok] * sw, rcond=None)
    mo_pred = X @ mk_beta
    wfill = w * y
    markout["model"] = {
        "fit": "weighted least squares on filled-cell mean markout (weights = filled counts)",
        "c200_weighted_predicted_filled_markout": round(
            sum(c200w[b] * (float(np.sum(wfill[band_arr == b] * mo_pred[band_arr == b]) /
                                   max(1e-9, np.sum(wfill[band_arr == b])))) for b in c200w), 5),
        "unconditional_filled_markout": round(mo_fill, 5) if mo_fill is not None else None,
        "naive_assumption": -0.02,
        "expected_entry_vs_naive": ("naive books -0.02 on EVERY leg; the model books -0.02 only on the "
                                    "P(fill) share and adds the filled-arm markout to it"),
    }

    # ---- coefficients ------------------------------------------------------------
    names = ["intercept", "band", "band^2"]
    names += ["hour_%d-%d" % HOUR_BUCKETS[i] for i in range(len(HOUR_BUCKETS))]
    names += ["size_b%d" % i for i in range(5)]
    names += ["vol_b%d" % i for i in range(5)]
    names += ["act_b%d" % i for i in range(5)]
    names += ["ttr_b%d" % i for i in range(-1, 6)]
    names += ["side_buy", "side_sell", "side_unknown"]
    names += ["cat:%s" % c for c in cats]
    coefs = sorted(
        [{"name": n, "beta": round(float(b), 4), "se": round(float(s), 4),
          "z": round(float(b / s), 2) if s > 0 else None,
          "odds_ratio": round(float(np.exp(b)), 4) if abs(b) < 50 else None}
         for n, b, s in zip(names, beta, se)],
        key=lambda x: -abs(x["z"] or 0))[:20]

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "input_cells": os.path.basename(path),
        "target": target, "delta": args.delta, "horizon_s": args.horizon,
        "cells_fitted": len(rows), "fills": total_n,
        "model": "binomial logistic GLM, IRLS, ridge lambda=1e-4, weights = cell fill counts",
        "irls_iterations": iters,
        "metrics": metrics,
        "c200_view": c200_view,
        "markout": markout,
        "top_coefficients": coefs,
        "per_band": {str(b): {"observed": round(obs_by_band[b], 4), "model": round(pred_by_band[b], 4),
                              "band_flat_train": round(band_tr.get(b, flat), 4)}
                     for b in sorted(obs_by_band)},
        "gate": {
            "pre_registered": ("beat the flat band-hazard baseline on Brier/log-loss, reproduce the "
                               "adverse-selection sign, and print expected markout beside naive intent-0.02 on "
                               ">=50 measured C-200 legs"),
            "status_holdout": ("PASS" if metrics["test"]["brier_model"] < metrics["test"]["brier_band_flat"]
                               else "FAIL") + " vs band-flat on the hash-split holdout (weak check: cells are not time-ordered)",
            "status_forward": "PENDING -- needs >=50 measured C-200 legs with an L2/tape-anchored level check",
        },
        "caveats": [
            "archive era ends 2026-04-28 on CTF Exchange v1: structure transfers, levels do not",
            "no order-book depth / quotes / cancellations in the archive -> spread and queue are NOT features here",
            "PRINT-anchored: our intent price is the detection MID, so intent-2c is a deeper, different event",
            "prints are not queue position and size is ignored (a bid is swept only up to the printed size)",
            "holdout is a hash split of cells, not a time split: use it to reject a model, never to promote one",
        ],
    }
    outp = os.path.join(OUTDIR, "fill-model-%s-%s.json" % (args.tag, target))
    with open(outp, "w") as fh:
        json.dump(out, fh, indent=1)

    print(json.dumps(out["metrics"], indent=1))
    print(json.dumps(out["c200_view"], indent=1))
    print(json.dumps(out["markout"], indent=1))
    print("\ntop coefficients (|z| ordered):")
    for c in coefs[:12]:
        print("  %-14s %+8.4f  se %.4f  z %+6.2f  OR %s" % (c["name"], c["beta"], c["se"], c["z"] or 0, c["odds_ratio"]))
    print("\nwrote %s" % outp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
