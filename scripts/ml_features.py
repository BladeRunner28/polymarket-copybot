#!/usr/bin/env python3
"""
ml_features.py — the ONE definition of the market-only feature set and candidate geometry.

WHY THIS MODULE EXISTS
Training and serving must build features identically or the served scores are meaningless in a way
that looks fine. The original trainer inlined its feature construction and ml-market-candidates.py
inlined the side/ask/fee geometry; a second copy for live scoring is exactly how a train/serve skew
gets introduced and never noticed. Both now import from here.

Python 3.9: no PEP 604 unions, no nested f-string expressions.
"""

import numpy as np
import pandas as pd

# Anything derived from the outcome. These must never reach the model.
LEAK_COLS = ["payout", "cost_ps", "roi_net", "roi_mid", "y_yes", "label_status", "resolved_at"]

NUM_FEATURES = [
    "yesPrice", "ask", "mid", "spread", "premium", "fee_ps", "liquidity", "volume",
    "timeToResolution", "horizon_h", "log_liquidity", "log_volume", "is_yes",
    "q_words", "q_chars", "q_has_year", "q_upper_tokens",
]

CAT_FEATURES = ["band", "ttr_band", "fee_band"]

# Fee rates mirror src/lib/scoring/price-edge.ts: 0.07 crypto, 0.04 politics/finance, 0.05 default.
CRYPTO = ["bitcoin", "btc", "ethereum", "eth", "solana", "sol ", "crypto", "token", "coin"]
POLFIN = ["election", "president", "senate", "congress", "nominee", "parliament", "prime minister",
          "fed ", "rate cut", "inflation", "cpi", "gdp", "treasury", "recession", "tariff",
          "stock", "s&p", "nasdaq", "earnings", "ipo"]


def category_fee_rate(text):
    """Mirror of categoryFeeRate(): 0.07 crypto / 0.04 politics-finance / 0.05 default."""
    t = str(text or "").lower()
    if any(k in t for k in CRYPTO):
        return 0.07
    if any(k in t for k in POLFIN):
        return 0.04
    return 0.05


def fee_per_share(price, rate):
    """Mirror of takerFeePerShare(): rate * price * (1 - price)."""
    p = float(price)
    return float(rate) * p * (1.0 - p)


def ttr_band(hours):
    h = float(hours)
    if h < 6:
        return "<6h"
    if h < 24:
        return "6-24h"
    if h < 72:
        return "1-3d"
    if h < 168:
        return "3-7d"
    if h < 720:
        return "1-4w"
    return ">4w"


def fee_band(rate):
    if rate is None or pd.isna(rate):
        return "na"
    if rate >= 0.06:
        return "high"
    if rate >= 0.045:
        return "mid"
    return "low"


def band_label(mid):
    """Same bins as the training build: [0,0.2,0.4,0.6,0.8,1.0]."""
    m = float(mid)
    if m < 0.2:
        return "(0.0, 0.2]"
    if m < 0.4:
        return "(0.2, 0.4]"
    if m < 0.6:
        return "(0.4, 0.6]"
    if m < 0.8:
        return "(0.6, 0.8]"
    return "(0.8, 1.0]"


def expand_sides(snap, cap=0.35, horizon_h=24):
    """
    Turn one row per MARKET into one row per tradeable SIDE, using the exact geometry the training
    labels were built with:

        YES: mid = yesPrice,  ask = bestAsk,        pays y_yes
        NO : mid = 1-yesPrice, ask = 1 - bestBid,   pays 1 - y_yes

        costPerShare = ask + takerFeePerShare(ask)
        premium      = (ask - mid) / mid      -> gated at `cap`

    `snap` needs: marketId, question, yesPrice, bestBid, bestAsk, spread, liquidity, volume,
    timeToResolution, collectedAt.
    """
    out = []
    for side in ("YES", "NO"):
        d = snap.copy()
        if side == "YES":
            d["mid"] = d["yesPrice"]
            d["ask"] = d["bestAsk"]
        else:
            d["mid"] = 1.0 - d["yesPrice"]
            d["ask"] = 1.0 - d["bestBid"]
        d["side"] = side
        ok = (d["mid"] > 0.001) & (d["mid"] < 0.999) & (d["ask"] > 0.001) & (d["ask"] < 0.999)
        d = d[ok].copy()
        if d.empty:
            continue
        d["premium"] = (d["ask"] - d["mid"]) / d["mid"]
        d["fee_rate"] = d["question"].map(category_fee_rate)
        d["fee_ps"] = [fee_per_share(a, r) for a, r in zip(d["ask"], d["fee_rate"])]
        d["cost_ps"] = d["ask"] + d["fee_ps"]
        d["passes_gate"] = d["premium"] <= cap
        d["horizon_h"] = horizon_h
        out.append(d)
    if not out:
        return pd.DataFrame()
    return pd.concat(out, ignore_index=True)


def derive_features(d):
    """
    Add every derived column the model consumes. Idempotent. Takes a frame that already has
    yesPrice/ask/mid/spread/premium/fee_ps/liquidity/volume/timeToResolution/side/question/
    fee_rate.
    """
    d = d.copy()
    d["log_liquidity"] = np.log1p(d["liquidity"].clip(lower=0))
    d["log_volume"] = np.log1p(d["volume"].clip(lower=0))
    d["is_yes"] = (d["side"] == "YES").astype(float)
    q = d["question"].fillna("").astype(str)
    d["q_words"] = q.str.split().str.len().astype(float)
    d["q_chars"] = q.str.len().astype(float)
    d["q_has_year"] = q.str.contains(r"20\d\d", regex=True).astype(float)
    d["q_upper_tokens"] = q.apply(
        lambda s: sum(1 for t in s.split() if t.isupper() and len(t) > 1)
    ).astype(float)
    d["fee_band"] = d["fee_rate"].apply(fee_band)
    d["band"] = d["mid"].apply(band_label)
    d["ttr_band"] = d["timeToResolution"].map(
        lambda h: ttr_band(float(h)) if pd.notna(h) else "n/a"
    )
    # Categoricals must never carry NaN.
    for c in CAT_FEATURES:
        d[c] = d[c].fillna("na").astype(str)
    return d


def feature_matrix(d):
    """Exactly the columns the model was fitted on, in the fitted order."""
    return d[NUM_FEATURES + CAT_FEATURES]
