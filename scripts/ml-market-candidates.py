#!/usr/bin/env python3
"""
ml-market-candidates.py — build the ML lane's MARKET-ONLY candidate dataset, labelled NET OF the
taker premium and the taker fee.

WHY THIS EXISTS, and why it is not the existing ML dataset
---------------------------------------------------------
The trained model in data/ml/ is WALLET-CONDITIONED: its top feature by gain is
`wallet_entry_price`, and the design carries wallet, copy_score, wallet_quality, copyability,
thesis_score, wallet_quality. That is the right model for "was copying THIS WALLET profitable",
which is the question copybot asks. It is structurally the wrong model for an independent-entry
ML lane, which by definition has no wallet signal. So the existing model cannot be reused here —
it has to be re-fit on market-only features.

The second reason this cannot reuse the old labels: they price entries at the MID. The lane trades
at the ASK (phase 1 books taker fills behind a premium cap). Measured 2026-10-20 on 8,997,897 cheap-
band quotes, the median taker premium in <0.20 is 33.3% of mid against 1.1% in 0.40-0.60 — 70% of
that band's gross edge. A model trained on mid-priced labels learns an edge that does not survive
the spread, so every label here is computed at ask + fee.

DECISION POINTS
---------------
For each labelled market we sample the single snapshot nearest to T-24h before resolution (and
T-6h). Sampling at the LAST snapshot before resolution would be near-tautological — the last price
of a resolved market encodes the outcome — so the cutoffs are fixed horizons, not "last seen".

COST MODEL (deliberately identical to the live scorer, not re-derived)
---------------------------------------------------------------------
  feePerShare = rate * price * (1 - price)        [takerFeePerShare, src/lib/scoring/price-edge.ts]
  rate        = 0.07 crypto / 0.04 politics-finance / 0.05 default  [categoryFeeRate keyword map]
  costPerShare = ask + feePerShare(ask)
  ROI          = (payout - costPerShare) / costPerShare
Both sides are evaluated: buying YES costs bestAsk against y_yes; buying NO costs (1 - bestBid)
against (1 - y_yes). A side is only tradeable if its quoted premium (ask-mid)/mid is <= the cap.

Run:  .venv-ml/bin/python scripts/ml-market-candidates.py --horizons 24,6 --cap 0.35
"""

import argparse
import math
import os
import sqlite3
import sys
import time

import pandas as pd

DB = os.environ.get("DB_PATH", "prisma/dev.db")

CRYPTO = ["btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "token", "airdrop", "fdv", "market cap"]
POLFIN = ["election", "president", "senate", "congress", "nominee", "parliament", "prime minister",
          "fed", "rate cut", "inflation", "cpi", "gdp", "recession", "tariff", "stock", "nasdaq",
          "s&p", "earnings", "shutdown", "impeach", "poll", "vote", "governor", "mayor"]


def category_fee_rate(text) -> float:
    """Mirror of categoryFeeRate() in src/lib/scoring/price-edge.ts — keyword map, same order."""
    t = (text or "").lower()
    if any(w in t for w in CRYPTO):
        return 0.07
    if any(w in t for w in POLFIN):
        return 0.04
    return 0.05


def fee_per_share(price: float, rate: float) -> float:
    """Mirror of takerFeePerShare() — feeRate * price * (1 - price)."""
    return rate * price * (1.0 - price)


def ttr_band(hours: float) -> str:
    if hours < 1:
        return "0-1h"
    if hours < 24:
        return "1-24h"
    if hours < 168:
        return "1-7d"
    if hours < 720:
        return "7-30d"
    return ">30d"


def load_targets(con: sqlite3.Connection, horizons: list[int]) -> pd.DataFrame:
    """Labelled markets with, per horizon, the timestamp we want a snapshot near."""
    mk = pd.read_csv("data/ml/markets.csv")
    mk = mk[mk["y_yes"].notna() & mk["resolved_at"].notna()].copy()
    # resolved_at is an ISO-8601 string in markets.csv (e.g. "2026-08-01T06:31:47Z"), not epoch ms
    mk["resolved_ms"] = pd.to_datetime(mk["resolved_at"], utc=True, errors="coerce").astype("int64") // 1_000_000
    mk = mk[mk["resolved_ms"].notna() & (mk["resolved_ms"] > 0)].copy()
    for h in horizons:
        mk[f"target_{h}"] = mk["resolved_ms"] - int(h * 3_600_000)
    return mk


def fetch_snapshots(con: sqlite3.Connection, mk: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """
    One scan of MarketSnapshot, picking the snapshot nearest each horizon per market.
    ROW_NUMBER() over the per-market absolute time distance keeps this a single pass with the
    (marketId, collectedAt) index rather than 46k correlated subqueries.
    """
    con.execute("DROP TABLE IF EXISTS _tgt")
    con.execute("CREATE TEMP TABLE _tgt (marketId TEXT PRIMARY KEY, t24 INTEGER, t6 INTEGER)")
    rows = [
        (r.market_id,
         int(getattr(r, "target_24", None)) if getattr(r, "target_24", None) is not None else None,
         int(getattr(r, "target_6", None)) if getattr(r, "target_6", None) is not None else None)
        for r in mk[["market_id"] + [f"target_{h}" for h in horizons]].itertuples(index=False)
    ]
    con.executemany("INSERT INTO _tgt VALUES (?,?,?)", rows)

    parts = []
    for h in horizons:
        q = f"""
        SELECT marketId, collectedAt, yesPrice, bestBid, bestAsk, spread, liquidity, volume,
               timeToResolution, question, {h} AS horizon_h
        FROM (
          SELECT s.marketId, s.collectedAt, s.yesPrice, s.bestBid, s.bestAsk, s.spread,
                 s.liquidity, s.volume, s.timeToResolution, s.question,
                 ROW_NUMBER() OVER (PARTITION BY s.marketId
                                    ORDER BY ABS(s.collectedAt - t.t{h})) AS rn
          FROM MarketSnapshot s
          JOIN _tgt t ON t.marketId = s.marketId
          WHERE s.isDemo = 0
            AND s.yesPrice > 0.001 AND s.yesPrice < 0.999
            AND s.bestAsk > 0.001 AND s.bestAsk < 0.999
            AND s.bestBid > 0.001 AND s.bestBid < 0.999
        ) WHERE rn = 1
        """
        df = pd.read_sql_query(q, con)
        df["horizon_h"] = h
        parts.append(df)
        print(f"  horizon T-{h}h: {len(df):,} market snapshots", flush=True)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def build_candidates(snaps: pd.DataFrame, mk: pd.DataFrame, cap: float) -> pd.DataFrame:
    df = snaps.merge(
        mk[["market_id", "y_yes", "label_status", "resolved_at"]],
        left_on="marketId", right_on="market_id", how="inner",
    )
    out = []
    for side in ("YES", "NO"):
        d = df.copy()
        if side == "YES":
            d["mid"] = d["yesPrice"]
            d["ask"] = d["bestAsk"]
            d["payout"] = d["y_yes"].astype(float)
        else:
            d["mid"] = 1.0 - d["yesPrice"]
            d["ask"] = 1.0 - d["bestBid"]          # crossing the book to buy NO
            d["payout"] = 1.0 - d["y_yes"].astype(float)
        d["side"] = side
        ok = (d["mid"] > 0.001) & (d["mid"] < 0.999) & (d["ask"] > 0.001) & (d["ask"] < 0.999)
        d = d[ok].copy()
        d["premium"] = (d["ask"] - d["mid"]) / d["mid"]
        d["fee_rate"] = d["question"].map(category_fee_rate)
        d["fee_ps"] = [fee_per_share(a, r) for a, r in zip(d["ask"], d["fee_rate"])]
        d["cost_ps"] = d["ask"] + d["fee_ps"]
        d["roi_net"] = (d["payout"] - d["cost_ps"]) / d["cost_ps"]
        d["roi_mid"] = (d["payout"] - d["mid"]) / d["mid"]   # what a mid-priced label would say
        d["passes_gate"] = d["premium"] <= cap
        out.append(d)
    cand = pd.concat(out, ignore_index=True)
    cand["band"] = pd.cut(cand["mid"], [0, 0.2, 0.4, 0.6, 0.8, 1.0],
                          labels=["<0.20", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"], right=False)
    cand["ttr_band"] = cand["timeToResolution"].map(lambda h: ttr_band(float(h)) if pd.notna(h) else "n/a")
    return cand


def cluster_ci(df: pd.DataFrame, col: str, iters: int = 1500, seed: int = 7) -> tuple[float, float]:
    """Market-clustered bootstrap of mean(col): resample MARKETS, not legs."""
    if df.empty:
        return (float("nan"), float("nan"))
    groups = [g[col].to_numpy() for _, g in df.groupby("marketId")]
    if len(groups) < 2:
        return (float("nan"), float("nan"))
    import numpy as np
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(iters):
        idx = rng.integers(0, len(groups), len(groups))
        vals = np.concatenate([groups[i] for i in idx])
        means.append(vals.mean())
    means.sort()
    return (means[int(0.025 * len(means))], means[int(0.975 * len(means))])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", default="24,6")
    ap.add_argument("--cap", type=float, default=0.35, help="taker premium cap as a fraction of mid")
    ap.add_argument("--out", default="data/ml/market-candidates.parquet")
    args = ap.parse_args()
    horizons = [int(h) for h in args.horizons.split(",")]

    t0 = time.time()
    con = sqlite3.connect(DB)
    con.execute("PRAGMA query_only=0")

    mk = load_targets(con, horizons)
    print(f"labelled markets: {len(mk):,}")
    snaps = fetch_snapshots(con, mk, horizons)
    if snaps.empty:
        print("no snapshots found — aborting")
        return 1

    cand = build_candidates(snaps, mk, args.cap)
    print(f"\ncandidates (both sides, both horizons): {len(cand):,}")
    print(f"  passing the {args.cap:.0%} taker-premium gate: {cand['passes_gate'].sum():,} "
          f"({cand['passes_gate'].mean()*100:.1f}%)")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    cand.to_parquet(args.out, index=False)
    print(f"  written: {args.out}")

    g = cand[cand["passes_gate"]].copy()
    print("\n=== WHAT THE SPREAD AND FEE COST, per band (gated population) ===")
    print(f"{'band':<8} {'rows':>8} {'med prem':>9} {'ROI @mid':>9} {'ROI net':>9} {'95% CI net':>20}")
    for band, d in g.groupby("band", observed=True):
        lo, hi = cluster_ci(d, "roi_net")
        print(f"{str(band):<8} {len(d):>8,} {d['premium'].median()*100:>8.1f}% "
              f"{d['roi_mid'].mean()*100:>8.2f}% {d['roi_net'].mean()*100:>8.2f}% "
              f"{'[' + format(lo*100,'.1f') + ', ' + format(hi*100,'.1f') + ']':>20}")

    print("\n=== THE DECISIVE COMPARISON: mid-labelled vs taker-labelled ===")
    for side, d in g.groupby("side"):
        lo, hi = cluster_ci(d, "roi_net")
        print(f"  {side:<4} n={len(d):>7,}  ROI@mid {d['roi_mid'].mean()*100:>7.2f}%  "
              f"ROI net {d['roi_net'].mean()*100:>7.2f}%  CI [{lo*100:.1f}, {hi*100:.1f}]")
    print(f"\nelapsed {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
