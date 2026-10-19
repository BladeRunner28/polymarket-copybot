#!/usr/bin/env python3
"""
Does the model's ranking edge survive contact with a real entry price and the taker fee?

Run: .venv-ml/bin/python scripts/ml-ev.py

THE ACCOUNTING IS THE REPO'S, NOT MINE
  src/lib/scoring/price-edge.ts defines feePerShare(price, rate) = rate * price * (1 - price)
  and the admission rule edge = p_hat - price - feePerShare. src/lib/training-export.ts defines
  feeRate by category: 0.07 crypto, 0.04 politics/finance, 0.05 default, and shares = stake / price.
  Those are reused verbatim here so an offline EV number and a live admission agree.

WHAT MAKES THIS "EXECUTABLE"
  price = the ask we would actually pay for OUR side: best_ask if we hold YES, else 1 - best_bid
  (the NO ask is the complement of the YES bid). Falls back to mid + half-spread, then to the
  detected price, and says how many rows needed each fallback. wallet_entry_price is NEVER used:
  it is the price the wallet got, which we cannot have.

WHAT IT REPORTS
  Per admission policy (all / edge>0 / edge>2c / edge>5c / top decile) and per model:
  n, hit rate, mean edge per share, and REALISED PnL on a fixed $1 stake per admitted trade,
  with a market-clustered bootstrap CI on ROI. Copybot's own selection is the control arm.
"""
import os
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression  # noqa: F401  (documented dependency chain)

BASE = os.path.expanduser("~/polymarket-copybot")
OUT = os.path.join(BASE, "data/ml")
RNG = np.random.default_rng(20261019)

CRYPTO = ["btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "token", "airdrop", "fdv", "market cap"]
POLFIN = ["election", "president", "senate", "congress", "nominee", "parliament", "prime minister",
          "fed", "rate cut", "inflation", "cpi", "gdp", "recession", "tariff", "stock", "nasdaq",
          "s&p", "earnings", "shutdown", "impeach", "poll", "vote", "governor", "mayor"]
DEFAULT_RATE = 0.05


def fee_rate(text: str) -> float:
    t = (text or "").lower()
    if any(w in t for w in CRYPTO):
        return 0.07
    if any(w in t for w in POLFIN):
        return 0.04
    return DEFAULT_RATE


def load(arm_tag: str):
    preds = pd.read_parquet(os.path.join(OUT, f"predictions_test{arm_tag}.parquet"))
    dec = pd.read_parquet(os.path.join(OUT, "decisions.parquet"))
    dec = dec[[c for c in dec.columns if c in (
        "decision_id", "outcome", "best_bid", "best_ask", "spread", "yes_price", "no_price",
        "detected_price", "category", "category_fine", "category_class", "market_id",
        "acted_any", "is_yes_side")]].copy()
    df = preds.merge(dec, on="decision_id", how="left", suffixes=("", "_dec"))

    # --- which side do we hold? (same price-proximity rule validated at 97.31%) ---
    is_no = df["outcome"].astype(str).str.upper().str.startswith("N")
    d_yes = (df["detected_price"] - df["yes_price"]).abs()
    d_no = (df["detected_price"] - df["no_price"]).abs()
    prox_no = d_no < d_yes
    is_yes_side = np.where(df["yes_price"].notna() & df["no_price"].notna(), ~prox_no, ~is_no)

    # --- executable cost for OUR side ---
    ask_yes = df["best_ask"]
    ask_no = 1 - df["best_bid"]
    mid_yes = df["yes_price"]
    mid_no = df["no_price"]
    half = pd.to_numeric(df["spread"], errors="coerce").fillna(0) / 2
    cost = np.where(is_yes_side, ask_yes, ask_no)
    rail = np.where(pd.notna(cost), "ask", None)
    miss = pd.isna(cost)
    cost = np.where(miss, np.where(is_yes_side, mid_yes + half, mid_no + half), cost)
    rail = np.where(miss & pd.notna(cost), "mid_plus_half_spread", rail)
    miss = pd.isna(cost)
    cost = np.where(miss, df["detected_price"], cost)
    rail = np.where(miss & pd.notna(cost), "detected_price", rail)

    df["is_yes_side"] = is_yes_side
    df["cost"] = np.clip(np.asarray(cost, dtype=float), 0.01, 0.99)
    df["cost_rail"] = rail
    text = (df["category"].astype(str) + " " + df["category_fine"].astype(str) + " "
            + df["category_class"].astype(str))
    df["fee_rate"] = text.map(fee_rate)
    df["fee_per_share"] = df["fee_rate"] * df["cost"] * (1 - df["cost"])
    return df


def realised(df: pd.DataFrame, p_col: str, thr: float, stake: float = 1.0):
    """Fixed stake per admitted trade, repo fee accounting, actual outcomes."""
    e = df[p_col] - df["cost"] - df["fee_per_share"]
    adm = df[e > thr].copy()
    adm["edge"] = e[e > thr]
    if len(adm) == 0:
        return {"n": 0}
    shares = stake / adm["cost"]
    fee_usd = shares * adm["fee_per_share"]
    win = adm["y"].values.astype(bool)
    pnl = np.where(win, shares * 1.0 - stake, -stake) - fee_usd
    staked = stake * len(adm)
    return {"n": int(len(adm)), "staked": float(staked), "pnl": float(pnl.sum()),
            "roi": float(pnl.sum() / staked), "hit": float(win.mean()),
            "mean_edge": float(adm["edge"].mean()),
            # numpy, not Series: the bootstrap indexes positionally and the admitted rows carry
            # non-contiguous pandas labels
            "_pnl": np.asarray(pnl, dtype=float),
            "_mkts": np.asarray(adm["market_id"].values, dtype=object)}


def cluster_ci(pnl: np.ndarray, mkts: np.ndarray, stake: float, n_boot=400):
    groups = np.array([str(g) for g in mkts], dtype=object)
    uniq = np.unique(groups)
    idx = {g: np.where(groups == g)[0] for g in uniq}
    out = []
    for _ in range(n_boot):
        pick = RNG.choice(uniq, size=len(uniq), replace=True)
        ii = np.concatenate([idx[g] for g in pick])
        denom = stake * len(ii)
        if denom > 0:
            out.append(pnl[ii].sum() / denom)
    return [round(float(np.percentile(out, 2.5)), 4), round(float(np.percentile(out, 97.5)), 4)]


def main():
    rows = []
    for tag, label in [("_wallet_entry_price_price_drift", "executable-clean"),
                       ("_wallet_entry_price", "executable")]:
        path = os.path.join(OUT, f"predictions_test{tag}.parquet")
        if not os.path.exists(path):
            print(f"missing {path}")
            continue
        df = load(tag)
        print(f"\n=== {label} ({tag}) n={len(df):,} ===")
        rails = df["cost_rail"].value_counts().to_dict()
        print(f"  cost rail: {rails}")
        print(f"  fee rate mix: {df['fee_rate'].value_counts().to_dict()}")
        print(f"  mean cost {df['cost'].mean():.4f} | mean fee/share {df['fee_per_share'].mean():.4f}")

        models = [("p_gbm", "lightgbm"), ("p_anchor", "logistic"), ("p_bar", "price-only")]
        for pcol, mname in models:
            sub = df[df[pcol].notna()]
            for thr, tname in [(-9, "all"), (0.0, "edge>0"), (0.02, "edge>2c"), (0.05, "edge>5c")]:
                r = realised(sub, pcol, thr)
                if r["n"] == 0:
                    continue
                ci = cluster_ci(r["_pnl"], r["_mkts"], 1.0)
                rows.append({"arm": label, "model": mname, "policy": tname, "n": r["n"],
                             "hit": round(r["hit"], 3), "mean_edge": round(r["mean_edge"], 4),
                             "roi": round(r["roi"], 4), "roi_ci95": ci, "pnl_per_bet": round(r["roi"], 4)})
                print(f"  {mname:11s} {tname:8s} n={r['n']:6,} hit={r['hit']:.3f} "
                      f"edge={r['mean_edge']:+.4f} ROI={r['roi']:+.4f} CI{ci}")

        # control: copybot's own selection, scored with the same accounting
        act = df[df["acted_any"] == 1]
        if len(act) > 0:
            r = realised(act.assign(_all=0.0), "_all", -9)
            ci = cluster_ci(r["_pnl"], r["_mkts"], 1.0)
            rows.append({"arm": label, "model": "copybot-actual", "policy": "acted", "n": r["n"],
                         "hit": round(r["hit"], 3), "mean_edge": None,
                         "roi": round(r["roi"], 4), "roi_ci95": ci, "pnl_per_bet": round(r["roi"], 4)})
            print(f"  {'copybot':11s} {'acted':8s} n={r['n']:6,} hit={r['hit']:.3f} "
                  f"ROI={r['roi']:+.4f} CI{ci}   <-- control")

    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(OUT, "ev-read.csv"), index=False)
    print(f"\nwrote {OUT}/ev-read.csv ({len(out)} rows)")

    if len(out):
        best = out[out["policy"].isin(["edge>0", "edge>2c"])].sort_values("roi", ascending=False).head(6)
        print("\nbest admission policies by realised ROI:")
        for _, r in best.iterrows():
            print(f"  {r['arm']:16s} {r['model']:13s} {r['policy']:8s} n={r['n']:5,} "
                  f"ROI={r['roi']:+.4f} CI{r['roi_ci95']}")


if __name__ == "__main__":
    main()
