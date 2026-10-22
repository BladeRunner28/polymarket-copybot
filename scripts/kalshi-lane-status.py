#!/usr/bin/env python3
"""Kalshi lane status -> data/ml/kalshi-lane.json

The ML page's rule is that it must never be able to drift from the script that measured
it, so the Kalshi card reads this artefact rather than carrying hardcoded numbers.
Recomputes from the same files the 2026-10-22 study used; read-only, no live lane.

Run: python3 scripts/kalshi-lane-status.py
"""
import glob
import json
import statistics
from datetime import datetime, timezone

PAIR_GLOB = "data/kalshi-pm-btc-pair-*.jsonl"
SHADOW_SUMMARY = "data/kalshi-venue-shadow-summary.json"
OUT = "data/ml/kalshi-lane.json"

FEE_BAND = 0.07  # one taker fee, both venues quote 7%


def mid(bid, ask):
    try:
        b, a = float(bid), float(ask)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= b <= a <= 1.0):
        return None
    return (b + a) / 2.0


def feats(r):
    pm_d = r.get("pm") or {}
    k_d = r.get("kalshi") or {}
    return mid(pm_d.get("up_bid"), pm_d.get("up_ask")), mid(k_d.get("yes_bid"), k_d.get("yes_ask"))


def auc(score, y):
    pairs = [(s, t) for s, t in zip(score, y) if s is not None]
    pos = [s for s, t in pairs if t == 1]
    neg = [s for s, t in pairs if t == 0]
    if not pos or not neg:
        return None, 0
    # P(random positive scores above random negative), ties counted half
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return wins / (len(pos) * len(neg)), len(pairs)


def main():
    rows = []
    for f in sorted(glob.glob(PAIR_GLOB)):
        with open(f) as fh:
            rows += [json.loads(l) for l in fh if l.strip()]

    # ---- arb form: complete-pair cost vs a $1 payout -------------------------
    nets = {"A": [], "B": []}
    for r in rows:
        for d, v in (r.get("pairs") or {}).items():
            if isinstance(v, dict) and v.get("complete") and v.get("net") is not None:
                nets.setdefault(d, []).append(float(v["net"]))

    arb = {}
    for d, vals in nets.items():
        if not vals:
            continue
        arb[d] = {
            "n": len(vals),
            "medianNet": round(statistics.median(vals), 4),
            "netPositivePct": round(100 * sum(1 for v in vals if v > 0) / len(vals), 2),
        }
    allnets = nets.get("A", []) + nets.get("B", [])

    # ---- informational form: does Kalshi predict better than Polymarket? -----
    by_window = {}
    for r in rows:
        if r.get("bucket") is None or not isinstance(r.get("pm"), dict) or not isinstance(r.get("kalshi"), dict):
            continue
        by_window.setdefault(r["bucket"], []).append(r)

    y, pm_f, k_f, dis = [], [], [], []
    for _, rs in by_window.items():
        rs.sort(key=lambda x: float(x.get("secs_into_window") or 0))
        pm_last, k_last = feats(rs[-1])
        ref = pm_last if pm_last is not None else k_last
        if ref is None:
            continue
        if ref >= 0.90:
            lab = 1
        elif ref <= 0.10:
            lab = 0
        else:
            continue
        cand = [x for x in rs if feats(x)[0] is not None or feats(x)[1] is not None]
        if not cand:
            continue
        f = min(cand, key=lambda x: abs(float(x.get("secs_into_window") or 0) - 450.0))
        p, k = feats(f)
        y.append(lab)
        pm_f.append(p)
        k_f.append(k)
        if p is not None and k is not None:
            dis.append(p - k)

    auc_pm, n_pm = auc(pm_f, y)
    auc_k, n_k = auc(k_f, y)

    # ---- venue-shadow cross-list coverage ------------------------------------
    coverage = None
    try:
        with open(SHADOW_SUMMARY) as fh:
            c = json.load(fh)["coverage"]
        coverage = {
            "copiesSeen": c["copiesSeen"],
            "withKalshiQuote": c["withKalshiQuote"],
            "crossListPct": round(100 * c["crossListRate"], 2),
            "unverifiedMatches": c.get("unverifiedMatches", 0),
        }
    except Exception:
        pass

    out = {
        "builtAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "CLOSED",
        "closedOn": "2026-10-22",
        "reason": "pre-registered refutation triggered on both forms",
        "arb": {
            "form": "complete pair: cost to buy a $1 payout",
            "byDirection": arb,
            "medianNetAll": round(statistics.median(allnets), 4) if allnets else None,
            "feeBand": FEE_BAND,
        },
        "information": {
            "form": "predictive AUC for P(up), mid-window quote",
            "windows": len(by_window),
            "labelled": len(y),
            "aucPm": None if auc_pm is None else round(auc_pm, 4),
            "aucKalshi": None if auc_k is None else round(auc_k, 4),
            "nPm": n_pm,
            "nKalshi": n_k,
            "disagreementMedian": round(statistics.median(dis), 4) if dis else None,
            "disagreementOverOneFeePct": round(100 * sum(1 for d in dis if abs(d) > FEE_BAND) / len(dis), 2) if dis else None,
        },
        "coverage": coverage,
        "reopenCondition": (
            "a new hypothesis on Kalshi's event-driven macro families (KXFED / KXCPI / KXPAYROLLS, "
            "75,278 quotes already on disk with venue-truth labels) rather than 15-minute BTC"
        ),
    }
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=2)
    print("wrote %s" % OUT)
    print("  arb median net        : %s" % out["arb"]["medianNetAll"])
    print("  net-positive          : %s" % {k: v["netPositivePct"] for k, v in arb.items()})
    print("  AUC pm/kalshi         : %s / %s  (windows %d, labelled %d)"
          % (out["information"]["aucPm"], out["information"]["aucKalshi"], len(by_window), len(y)))
    print("  disagreement median   : %s | >1 fee %s%%"
          % (out["information"]["disagreementMedian"], out["information"]["disagreementOverOneFeePct"]))


if __name__ == "__main__":
    main()
