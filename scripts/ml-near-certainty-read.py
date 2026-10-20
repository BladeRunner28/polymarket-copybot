#!/usr/bin/env python3
"""
ml-near-certainty-read.py — does the 0.8-1.0 band survive at REALISTIC size?

WHY THIS EXISTS
---------------
scripts/ml-market-candidates.py measured the market-only candidate population net of the taker
premium and fee. Every band lost money except 0.8-1.0, which returned +0.77% with a tight
market-clustered CI [+0.5, +1.1] on 38,925 candidates. That is the only statistically solid
positive in unselected market entry, so it deserves a real test rather than a paragraph.

"+0.77% per trade" is NOT an answer. The questions that decide whether it is a business:
  1. Where inside 0.8-1.0 does the edge actually live? A band average can hide one profitable
     sub-region and three losing ones.
  2. How much of the gross is eaten by premium + fee, and how fast does it die if fills are worse
     than the quoted ask?
  3. How many opportunities exist PER DAY, and therefore how much capital must be tied up per
     dollar of return — the edge-per-capital-day test that already decided STANDARD vs C-200
     ($0.011 vs $0.382 per capital-day).
  4. Is the edge one-sided (YES vs NO)?
  5. Capacity: how much notional actually trades near these prices, per the L2 tape.

METHOD
------
Population: candidates from data/ml/market-candidates.parquet, gated (taker premium <= 35%),
band 0.8-1.0. Labels are already net of ask + fee. CIs are market-clustered bootstrap (resample
MARKETS, not rows) — legs inside one market share an outcome.

Run: .venv-ml/bin/python scripts/ml-near-certainty-read.py
"""

import argparse
import sys

import numpy as np
import pandas as pd

BANDS = [(0.80, 0.85), (0.85, 0.90), (0.90, 0.95), (0.95, 1.00)]


def cluster_ci(df, col, iters=1500, seed=7):
    """Market-clustered bootstrap of the MEAN of col: resample markets with replacement."""
    if df.empty:
        return (float("nan"), float("nan"), float("nan"))
    groups = [g[col].to_numpy() for _, g in df.groupby("marketId")]
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/ml/market-candidates.parquet")
    ap.add_argument("--lo", type=float, default=0.80)
    ap.add_argument("--hi", type=float, default=1.00)
    ap.add_argument("--leg", type=float, default=20.0, help="notional per leg, USD")
    args = ap.parse_args()

    df = pd.read_parquet(args.parquet)
    df = df[df["passes_gate"]].copy()
    df = df[(df["mid"] >= args.lo) & (df["mid"] < args.hi)].copy()
    if df.empty:
        print("no candidates in that range")
        return 1

    span_days = max((df["collectedAt"].max() - df["collectedAt"].min()) / 86_400_000, 1.0)
    print(f"band {args.lo:.2f}-{args.hi:.2f}: {len(df):,} candidates over {span_days:.0f} days")
    print(f"  distinct markets: {df['marketId'].nunique():,}")
    print(f"  {len(df)/span_days:,.1f} candidates/day (both sides x 2 horizons)\n")

    print("=== 1. WHERE DOES THE EDGE LIVE (sub-bands) ===")
    print(f"{'sub-band':<10} {'rows':>7} {'mkts':>6} {'prem':>7} {'ROI@mid':>9} {'ROI net':>9} {'95% CI':>18}")
    for lo, hi in BANDS:
        d = df[(df["mid"] >= lo) & (df["mid"] < hi)]
        if len(d) < 50:
            print(f"{f'{lo:.2f}-{hi:.2f}':<10} {len(d):>7} too few")
            continue
        m, l, h = cluster_ci(d, "roi_net")
        print(f"{f'{lo:.2f}-{hi:.2f}':<10} {len(d):>7,} {d['marketId'].nunique():>6,} "
              f"{d['premium'].median()*100:>6.1f}% {d['roi_mid'].mean()*100:>8.2f}% "
              f"{m*100:>8.2f}% {'[' + format(l*100,'.2f') + ', ' + format(h*100,'.2f') + ']':>18}")

    print("\n=== 2. WHAT PREMIUM + FEE COST, AND HOW FAST THE EDGE DIES ===")
    base = df["roi_net"].mean() * 100
    print(f"  gross at mid          : {df['roi_mid'].mean()*100:>8.3f}%")
    print(f"  net of ask + fee      : {base:>8.3f}%   (cost {(df['roi_mid'].mean()-df['roi_net'].mean())*100:.3f} pp)")
    for mult in (1.0, 1.5, 2.0, 3.0):
        # worse fill: pay mult x the quoted premium, fee recomputed at the worse price
        ask2 = df["mid"] * (1.0 + df["premium"] * mult)
        cost2 = ask2 + df["fee_rate"] * ask2 * (1 - ask2)
        roi2 = (df["payout"] - cost2) / cost2
        print(f"  premium x{mult:<4}          : {roi2.mean()*100:>8.3f}%")

    print("\n=== 3. EDGE PER CAPITAL-DAY (the metric that decided STANDARD vs C-200) ===")
    # NOTE: computing mean(roi/hold) row-by-row explodes on near-zero holds and once printed an
    # impossible $14.80/leg/capital-day. Use the AGGREGATE ratio instead: mean ROI / mean hold.
    # That is the honest capital productivity of the population, and it cannot blow up.
    hold_days = (df["timeToResolution"] / 24.0).clip(lower=0.01)
    mean_hold = hold_days.mean()
    med_hold = hold_days.median()
    per_day_frac = df["roi_net"].mean() / mean_hold
    print(f"  median hold at entry  : {med_hold:.2f} days   (mean {mean_hold:.2f})")
    print(f"  mean ROI net          : {df['roi_net'].mean()*100:.3f}%")
    print(f"  edge per capital-day  : {per_day_frac*100:.3f}% of capital "
          f"= ${per_day_frac*args.leg:.4f} per ${args.leg:.0f} leg")
    print(f"  COMPARISON            : C-200 $0.3818/capital-day, STANDARD $0.0114 (measured 2026-10-20)")

    print("\n=== 3b. PAYOFF GEOMETRY -- a mean is not a return when most trades lose everything ===")
    losers = (df["roi_net"] <= -0.95).mean()
    wins = df[df["roi_net"] > 0]["roi_net"]
    losses = df[df["roi_net"] <= 0]["roi_net"]
    breakeven_wr = (-losses.mean()) / (wins.mean() - losses.mean()) if len(wins) and len(losses) else float("nan")
    print(f"  share of trades losing >=95% : {losers*100:>6.1f}%")
    print(f"  mean WIN                     : {wins.mean()*100:>6.1f}%  (n={len(wins):,})")
    print(f"  mean LOSS                    : {losses.mean()*100:>6.1f}%  (n={len(losses):,})")
    wr = (df["roi_net"] > 0).mean()
    margin_pp = (wr - breakeven_wr) * 100
    print(f"  realised win rate            : {wr*100:>6.1f}%")
    print(f"  breakeven win rate implied   : {breakeven_wr*100:>6.1f}%  (margin {margin_pp:+.1f} pp)")
    geo = float(np.exp(np.log1p(df["roi_net"].clip(lower=-0.9999)).mean()) - 1)
    print(f"  GEOMETRIC mean per trade     : {geo*100:>6.3f}%   (arithmetic {df['roi_net'].mean()*100:.3f}%)")
    print(f"  -> at this geometry, position size must be small: one loss costs 100% of the leg")

    print("\n=== 4. SIDEDNESS ===")
    for side, d in df.groupby("side"):
        m, l, h = cluster_ci(d, "roi_net")
        print(f"  {side:<4} n={len(d):>7,}  ROI net {m*100:>7.3f}%  CI [{l*100:.2f}, {h*100:.2f}]")

    print("\n=== 5. CAPACITY FROM THE CANDIDATE TABLE (proxy only) ===")
    for q in (0.10, 0.25, 0.50, 0.75, 0.90):
        print(f"  liquidity p{int(q*100):<2} : ${df['liquidity'].quantile(q):,.0f}"
              f"   volume p{int(q*100):<2} : ${df['volume'].quantile(q):,.0f}")

    print(f"\n=== 6. WHAT {args.leg:.0f}/LEG WOULD EARN ===")
    per_day = len(df) / span_days
    print(f"  candidates/day        : {per_day:,.1f}")
    print(f"  at ${args.leg:.0f}/leg, gross/day     : ${per_day*args.leg*df['roi_net'].mean():,.2f}")
    print(f"  capital tied up (hold {med_hold:.2f}d): ${per_day*args.leg*med_hold:,.0f}")
    print(f"  return on that capital: {df['roi_net'].mean()/med_hold*100:.3f}%/day "
          f"(vs C-200 0.382/20 = 1.909%/day on its own leg)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
