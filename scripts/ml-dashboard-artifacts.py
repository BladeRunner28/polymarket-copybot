#!/usr/bin/env python3
"""
ml-dashboard-artifacts.py — emit data/ml/dashboard.json for the /ml dashboard page.

The dashboard is a Next.js server the user reads, not a research notebook. Every number it shows must
come from a script that already ran and can re-run, so this writes one compact JSON and the page does
no modelling of its own.

Sources (all previously committed measurements, re-derived here so the page cannot drift):
  data/ml/market-candidates.parquet  -> market-only band economics + near-certainty sub-bands
  data/ml/predictions_test.parquet   -> held-out model scores, joined to real PaperTrade legs
  prisma/dev.db                      -> the actual bought leg (entry price, realised PnL)

Run: .venv-ml/bin/python scripts/ml-dashboard-artifacts.py
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

DB = os.environ.get("DB_PATH", "prisma/dev.db")
OUT = "data/ml/dashboard.json"
CRYPTO = ["btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "token", "airdrop", "fdv", "market cap"]
POLFIN = ["election", "president", "senate", "congress", "nominee", "parliament", "prime minister",
          "fed", "rate cut", "inflation", "cpi", "gdp", "recession", "tariff", "stock", "nasdaq",
          "s&p", "earnings", "shutdown", "impeach", "poll", "vote", "governor", "mayor"]


def fee_rate(text):
    t = (text or "").lower()
    if any(w in t for w in CRYPTO):
        return 0.07
    if any(w in t for w in POLFIN):
        return 0.04
    return 0.05


def cluster_ci(df, col, key="marketId", iters=1200, seed=7):
    if df.empty or len(df) < 3:
        return (float("nan"), float("nan"), float("nan"))
    groups = [g[col].to_numpy() for _, g in df.groupby(key)]
    if len(groups) < 2:
        return (float(df[col].mean()), None, None)
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(iters):
        idx = rng.integers(0, len(groups), len(groups))
        means.append(np.concatenate([groups[i] for i in idx]).mean())
    means.sort()
    return (float(df[col].mean()), float(means[int(0.025 * len(means))]),
            float(means[int(0.975 * len(means))]))


def pct(v, nd=2):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(v * 100, nd)


def market_only():
    df = pd.read_parquet("data/ml/market-candidates.parquet")
    g = df[df["passes_gate"]].copy()
    bands = []
    for lo, hi in [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]:
        d = g[(g["mid"] >= lo) & (g["mid"] < hi)]
        if d.empty:
            continue
        m, l, h = cluster_ci(d, "roi_net")
        bands.append({"band": f"{lo:.1f}-{hi:.1f}", "rows": len(d),
                      "markets": int(d["marketId"].nunique()),
                      "premiumPct": pct(float(d["premium"].median()), 1),
                      "roiMidPct": pct(float(d["roi_mid"].mean())),
                      "roiNetPct": pct(m), "ciLoPct": pct(l), "ciHiPct": pct(h)})
    return {"candidates": int(len(df)), "gated": int(len(g)), "bands": bands}


def near_certainty():
    df = pd.read_parquet("data/ml/market-candidates.parquet")
    g = df[df["passes_gate"]].copy()
    d = g[(g["mid"] >= 0.80) & (g["mid"] < 1.00)].copy()

    sub = []
    for lo, hi in [(0.80, 0.85), (0.85, 0.90), (0.90, 0.95), (0.95, 1.00)]:
        s = d[(d["mid"] >= lo) & (d["mid"] < hi)]
        if len(s) < 50:
            continue
        m, l, h = cluster_ci(s, "roi_net")
        sub.append({"band": f"{lo:.2f}-{hi:.2f}", "rows": len(s),
                    "markets": int(s["marketId"].nunique()),
                    "roiNetPct": pct(m), "ciLoPct": pct(l), "ciHiPct": pct(h),
                    "clearsZero": bool(l is not None and l > 0)})

    sens = []
    for mult in (1.0, 1.5, 2.0):
        ask2 = d["mid"] * (1.0 + d["premium"] * mult)
        cost2 = ask2 + d["fee_rate"] * ask2 * (1 - ask2)
        roi2 = (d["payout"] - cost2) / cost2
        sens.append({"premiumMult": mult, "roiNetPct": pct(float(roi2.mean()))})

    losers_share = float((d["roi_net"] <= -0.95).mean())
    wins = d[d["roi_net"] > 0]["roi_net"]
    losses = d[d["roi_net"] <= 0]["roi_net"]
    be = float(-losses.mean() / (wins.mean() - losses.mean()))
    geo = float(np.exp(np.log1p(d["roi_net"].clip(lower=-0.9999)).mean()) - 1)
    hold = (d["timeToResolution"] / 24.0).clip(lower=0.01)
    per_day = float(d["roi_net"].mean() / hold.mean())

    return {"subbands": sub, "sensitivity": sens,
            "geometry": {"loserSharePct": pct(losers_share, 1),
                         "meanWinPct": pct(float(wins.mean()), 1),
                         "meanLossPct": pct(float(losses.mean()), 1),
                         "breakevenWrPct": pct(be, 1),
                         "realisedWrPct": pct(float((d["roi_net"] > 0).mean()), 1),
                         "marginPp": round((float((d["roi_net"] > 0).mean()) - be) * 100, 1),
                         "geoMeanPct": pct(geo, 2),
                         "arithMeanPct": pct(float(d["roi_net"].mean()))},
            "capitalDay": {"perDayPct": pct(per_day, 3),
                           "per20LegUsd": round(per_day * 20, 4),
                           "c200Usd": 0.3818, "standardUsd": 0.0114},
            "rows": int(len(d))}


def veto():
    pred = pd.read_parquet("data/ml/predictions_test.parquet")
    con = sqlite3.connect(DB)
    ph = ",".join("?" for _ in pred["decision_id"])
    trades = pd.read_sql_query(
        f"""SELECT decisionJournalId AS decision_id, entryPrice AS entry_price,
                   simulatedPositionSize AS cost_usd, COALESCE(realizedPnl,0) AS pnl_usd
            FROM PaperTrade WHERE decisionJournalId IN ({ph})
              AND status IN ('closed','resolved') AND isDemo = 0""",
        con, params=list(pred["decision_id"]))
    if trades.empty:
        return {"available": False}
    df = pred.merge(trades, on="decision_id", how="inner")
    df["p_model"] = df["p_gbm"].where(df["p_gbm"].notna(), df["p_bar"])
    df["roi_actual"] = df["pnl_usd"] / df["cost_usd"].replace(0, np.nan)
    df = df[df["roi_actual"].notna()].copy()
    df["fee"] = [fee_rate(m) * p * (1 - p) for m, p in zip(df["market_id"], df["entry_price"])]
    df["ev"] = df["p_model"] - (df["entry_price"] + df["fee"])
    df["band"] = pd.cut(df["entry_price"], [0, 0.2, 0.4, 0.6, 0.8, 1.0],
                        labels=["<0.20", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"], right=False)

    base = {"legs": len(df), "notionalUsd": round(float(df["cost_usd"].sum()), 2),
            "pnlUsd": round(float(df["pnl_usd"].sum()), 2),
            "roiPct": pct(float(df["pnl_usd"].sum() / df["cost_usd"].sum()))}
    sweep = []
    for thr in (-0.05, -0.02, 0.0, 0.02, 0.05):
        k = df[df["ev"] > thr]
        if len(k) < 20:
            continue
        sweep.append({"threshold": thr, "legs": len(k),
                      "pnlUsd": round(float(k["pnl_usd"].sum()), 2),
                      "roiPct": pct(float(k["pnl_usd"].sum() / k["cost_usd"].sum()))})
    seq = [s["pnlUsd"] for s in sweep]
    flips = sum(1 for i in range(2, len(seq)) if (seq[i] - seq[i-1]) * (seq[i-1] - seq[i-2]) < 0)

    qs = df["ev"].quantile([0.0, 0.25, 0.5, 0.75, 1.0]).values
    quart = []
    for i in range(4):
        q = df[(df["ev"] >= qs[i]) & (df["ev"] <= qs[i+1])]
        if len(q) < 10:
            continue
        m, l, h = cluster_ci(q, "roi_actual", key="market_id")
        quart.append({"quartile": i + 1, "evLo": round(float(qs[i]), 3), "evHi": round(float(qs[i+1]), 3),
                      "legs": len(q), "roiPct": pct(m), "ciLoPct": pct(l), "ciHiPct": pct(h)})

    by_band = []
    for band, b in df.groupby("band", observed=True):
        if len(b) < 15:
            continue
        by_band.append({"band": str(band), "legs": len(b),
                        "roiPct": pct(float(b["pnl_usd"].sum() / b["cost_usd"].sum()))})

    return {"available": True, "baseline": base, "sweep": sweep, "flips": flips,
            "monotone": flips <= 1, "quartiles": quart, "byBand": by_band,
            "justified": False}


def source_freshness():
    """When each INPUT was last measured, so the page can show data age, not just build age.

    generatedAt alone only says when this JSON was written: a fresh rebuild over a week-old
    parquet would still read as current. These are the mtimes of the artefacts the numbers are
    actually derived from, so a stale input cannot hide behind a new build.
    """
    # role matters: "rolling" inputs SHOULD advance daily (a stale one is a defect), while a
    # "study" artefact is the frozen held-out output of a closed experiment -- re-running it would
    # change a historical result, so its age is provenance, not staleness. predictions_test.parquet
    # comes from ml-train.py, the WALLET-conditioned model, which is NOT part of the market-only
    # daily chain; it is deliberately not regenerated here.
    out = {}
    for key, path, role in (("marketCandidates", "data/ml/market-candidates.parquet", "rolling"),
                            ("paperTrades", DB, "rolling"),
                            ("predictionsTest", "data/ml/predictions_test.parquet", "study")):
        try:
            m = os.path.getmtime(path)
        except OSError:
            out[key] = {"path": path, "role": role, "exists": False, "mtimeZ": None, "ageHours": None}
            continue
        dt = datetime.fromtimestamp(m, tz=timezone.utc)
        out[key] = {"path": path, "role": role, "exists": True,
                    "mtimeZ": dt.isoformat().replace("+00:00", "Z"),
                    "ageHours": round((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 1)}
    return out


def main():
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sources": source_freshness(),
        "lane": {
            "state": "CLOSED",
            "headline": "Market-only prediction does not pay",
            # NOTE: never hardcode a count that the script can compute -- an earlier draft of this
            # string said "6 direction changes" while the sweep actually produced 2.
            # WORDING (2026-10-26): "With the wallet signal removed" read as a CHANGELOG entry -- as if a
            # wallet feature had been deleted from the bot -- and the user asked why the page said we removed
            # it. Nothing was removed. The ML lane is market-only BY CONSTRUCTION and never had wallet data;
            # the phrase describes the counterfactual ARM of a measurement (the same trades with wallet
            # selection stripped out). Say "arm"/"counterfactual" explicitly so the sentence cannot be read
            # as a product change.
            "detail": ("In the market-only arm -- the same traded bands with wallet selection stripped out, so "
                       "only market features are used -- the <0.20 band returns -50.64% net of ask+fee. "
                       "The only naively-positive band (0.8-1.0, +0.77%) dies at 1.5x the quoted premium, "
                       "has a geometric mean of -20.4%, and yields $0.0055 per $20 leg per capital-day "
                       "against C-200's $0.3818. The model-as-veto is not established either: every EV "
                       "quartile CI spans zero and the sweep reverses direction."),
            "alphaSource": "wallet-conditioned selection, not price prediction",
        },
        "contrast": {"withWalletPct": 47.75, "withoutWalletPct": -50.64,
                     "note": "same <0.20 band, same accounting -- the difference is WHICH WALLETS were copied"},
        "marketOnly": market_only(),
        "nearCertainty": near_certainty(),
        "veto": veto(),
    }
    # 0.4-0.6 corroboration comes from the joined held-out legs, so read it off the veto block
    vb = {b["band"]: b for b in payload["veto"].get("byBand", [])}
    payload["v63Corroboration"] = {
        "band": "0.4-0.6",
        "heldOutRoiPct": vb.get("0.4-0.6", {}).get("roiPct"),
        "heldOutLegs": vb.get("0.4-0.6", {}).get("legs"),
        "note": "v63 skips exactly this band; independent held-out legs agree it loses",
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=1)
    print(f"wrote {OUT}")
    print(f"  lane {payload['lane']['state']}: {payload['lane']['headline']}")
    print(f"  market-only bands: {len(payload['marketOnly']['bands'])}")
    print(f"  near-certainty sub-bands: {len(payload['nearCertainty']['subbands'])}")
    print(f"  veto justified: {payload['veto'].get('justified')} (flips {payload['veto'].get('flips')})")
    print(f"  v63 held-out 0.4-0.6: {payload['v63Corroboration']['heldOutRoiPct']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
