#!/usr/bin/env python3
"""
ml-veto-calibration.py — calibrate the ML model as a VETO on copy legs, on held-out data.

WHY THIS, AND NOT INDEPENDENT ENTRY
-----------------------------------
2026-10-20 measurements closed the market-only lane: with the wallet signal removed, the <0.20 band
returns -50.64% net of ask+fee, and the one naively-positive band (0.8-1.0, +0.77%) dies at 1.5x the
quoted premium, has a geometric mean of -20.4%, and yields $0.0055 per $20 leg per capital-day
against C-200's $0.3818. The contrast is the finding: same band, +47.75% WITH wallet selection vs
-50.64% WITHOUT. So the alpha in this system is in WHICH WALLETS GET COPIED, and the model's useful
job is therefore not to invent entries but to VETO bad copies.

THE RIGHT QUANTITY IS EDGE, NOT PROBABILITY
-------------------------------------------
A high modelled probability on a near-certain market is not an opportunity — it is fairly priced.
The tradeable quantity is expected value per share:

    EV = p_model - cost_per_share,   cost = entry_price + feePerShare(entry_price, feeRate)

so a veto should fire on EV <= threshold, not on low p. This script calibrates that threshold on
HELD-OUT rows only (data/ml/predictions_test.parquet, the time-ordered holdout) joined to the real
bought leg (PaperTrade) for its actual entry price and realised PnL.

WHAT IT REPORTS: for a grid of EV thresholds, legs kept, realised ROI, total PnL, and whether the
veto IMPROVES total PnL versus taking everything. A veto that raises ROI by shrinking the book but
lowers total PnL is not an improvement — that distinction is the whole point.

Run: .venv-ml/bin/python scripts/ml-veto-calibration.py
"""

import os
import sqlite3
import sys

import numpy as np
import pandas as pd

DB = os.environ.get("DB_PATH", "prisma/dev.db")
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


def cluster_ci(df, col, iters=1500, seed=7):
    if df.empty or len(df) < 3:
        return (float("nan"), float("nan"), float("nan"))
    groups = [g[col].to_numpy() for _, g in df.groupby("market_id")]
    if len(groups) < 2:
        return (df[col].mean(), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(iters):
        idx = rng.integers(0, len(groups), len(groups))
        means.append(np.concatenate([groups[i] for i in idx]).mean())
    means.sort()
    return (df[col].mean(), means[int(0.025 * len(means))], means[int(0.975 * len(means))])


def main():
    pred = pd.read_parquet("data/ml/predictions_test.parquet")
    print(f"held-out predictions: {len(pred):,} rows")

    con = sqlite3.connect(DB)
    placeholders = ",".join("?" for _ in pred["decision_id"])
    trades = pd.read_sql_query(
        # NOTE: do not select marketId here -- pred already carries market_id and the merge would
        # produce market_id_x/market_id_y, which silently broke this script on first run.
        f"""SELECT decisionJournalId AS decision_id, entryPrice AS entry_price,
                   simulatedPositionSize AS cost_usd, COALESCE(realizedPnl,0) AS pnl_usd,
                   openedAt AS opened_at, status
            FROM PaperTrade
            WHERE decisionJournalId IN ({placeholders})
              AND status IN ('closed','resolved') AND isDemo = 0""",
        con, params=list(pred["decision_id"]),
    )
    print(f"  joined to finished paper legs: {len(trades):,}")
    if trades.empty:
        print("no joinable legs — the holdout may predate the leg population")
        return 1

    df = pred.merge(trades, on="decision_id", how="inner")
    df["p_model"] = df["p_gbm"] if df["p_gbm"].notna().all() else df["p_bar"]
    # realised ROI per leg, and the fee on the actual entry price
    df["roi_actual"] = df["pnl_usd"] / df["cost_usd"].replace(0, np.nan)
    df = df[df["roi_actual"].notna()].copy()
    df["fee"] = [fee_rate(t) * p * (1 - p) for t, p in zip(df["market_id"], df["entry_price"])]
    df["cost_ps"] = df["entry_price"] + df["fee"]
    df["ev"] = df["p_model"] - df["cost_ps"]
    df["band"] = pd.cut(df["entry_price"], [0, 0.2, 0.4, 0.6, 0.8, 1.0],
                        labels=["<0.20", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"], right=False)

    base_n = len(df)
    base_pnl = df["pnl_usd"].sum()
    base_roi = base_pnl / df["cost_usd"].sum()
    print(f"\nBASELINE (no veto): {base_n:,} legs, ${df['cost_usd'].sum():,.0f} notional, "
          f"PnL ${base_pnl:,.2f}, ROI {base_roi*100:.2f}%")

    print("\n=== EV THRESHOLD SWEEP (veto fires when EV <= threshold) ===")
    print(f"{'threshold':>10} {'kept':>6} {'kept%':>6} {'notional':>10} {'PnL':>10} {'ROI':>8} {'d PnL':>10} {'verdict':>9}")
    rows = []
    for thr in (-0.20, -0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10, 0.20):
        keep = df[df["ev"] > thr]
        if len(keep) < 20:
            print(f"{thr:>+10.2f} {len(keep):>6}  too few")
            continue
        pnl = keep["pnl_usd"].sum()
        roi = pnl / keep["cost_usd"].sum()
        delta = pnl - base_pnl
        verdict = "BETTER" if delta > 0 else "worse"
        rows.append((thr, len(keep), pnl, roi, delta))
        print(f"{thr:>+10.2f} {len(keep):>6,} {len(keep)/base_n*100:>5.1f}% "
              f"${keep['cost_usd'].sum():>9,.0f} ${pnl:>9,.2f} {roi*100:>7.2f}% "
              f"${delta:>+9,.2f} {verdict:>9}")

    if rows:
        best = max(rows, key=lambda r: r[4])
        print(f"\nBEST BY TOTAL PnL: threshold {best[0]:+.2f} -> {best[1]:,} legs ({best[1]/base_n*100:.1f}% kept), "
              f"ROI {best[3]*100:.2f}%, PnL ${best[2]:,.2f} (delta ${best[4]:+,.2f})")
        # ARGMAX IS NOT EVIDENCE. A real veto ordering must be monotone: raising the threshold keeps a
        # strictly better subset, so PnL-by-threshold must not zigzag. On the 2026-10-20 holdout it
        # went +44 -> +26 -> -21 -> +138 -> +314 -> -165, which is noise, not signal. Report the test.
        seq = [r[2] for r in rows]
        ups = sum(1 for i in range(1, len(seq)) if seq[i] > seq[i - 1])
        downs = sum(1 for i in range(1, len(seq)) if seq[i] < seq[i - 1])
        flips = sum(1 for i in range(2, len(seq))
                    if (seq[i] - seq[i - 1]) * (seq[i - 1] - seq[i - 2]) < 0)
        monotone = flips <= 1
        print(f"  monotonicity: {flips} direction changes across {len(seq)} thresholds "
              f"({ups} up, {downs} down) -> {'monotone' if monotone else 'NON-MONOTONE'}")
        if not monotone or best[4] <= 0:
            print("  -> NO justified veto. The argmax above is a point on a noisy curve, not a signal;")
            print("     picking it is curve-fitting to this holdout. Do not propose a RuleSet change.")
        else:
            print("  -> monotone improvement; still require more settled legs before proposing")

    print("\n=== PER-BAND: does EV separate winners from losers where the model was said to work? ===")
    print(f"{'band':<8} {'legs':>5} {'ROI all':>9} {'ROI EV>0':>10} {'legs EV>0':>10} {'spread':>8}")
    for band, d in df.groupby("band", observed=True):
        pos = d[d["ev"] > 0]
        if len(d) < 15 or len(pos) < 5:
            print(f"{str(band):<8} {len(d):>5}  too few")
            continue
        ra = d["pnl_usd"].sum() / d["cost_usd"].sum()
        rp = pos["pnl_usd"].sum() / pos["cost_usd"].sum()
        print(f"{str(band):<8} {len(d):>5} {ra*100:>8.2f}% {rp*100:>9.2f}% {len(pos):>10} {(rp-ra)*100:>+7.2f}pp")

    print("\n=== EV SEPARATION: is EV itself predictive of realised ROI? ===")
    q = df["ev"].quantile([0.0, 0.25, 0.5, 0.75, 1.0]).values
    for i in range(4):
        d = df[(df["ev"] >= q[i]) & (df["ev"] <= q[i + 1])]
        if len(d) < 10:
            continue
        m, lo, hi = cluster_ci(d, "roi_actual")
        print(f"  EV quartile {i+1} [{q[i]:+.3f}, {q[i+1]:+.3f}]  n={len(d):>5}  "
              f"ROI {m*100:>7.2f}%  CI [{lo*100:.1f}, {hi*100:.1f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
