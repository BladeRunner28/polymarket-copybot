#!/usr/bin/env python3
"""
SHADOW READ — what would have been admitted if "we could not read the market" were not
treated as "the market has zero liquidity".

Nothing here changes a live path. It reads the decision journal, classifies the recorded
hard skips, and reports the realised edge of the rows the data-availability gates killed.

Run: .venv-ml/bin/python scripts/shadow-liquidity-unknown.py
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

DB = "prisma/dev.db"
DEC = "data/ml/decisions.parquet"

# Non-blocking annotation strings that appear in risksJson alongside real gates.
ANNOT = (
    "coalesced", "high-quality wallet", "liquid market", "regulatory", "swarm detected",
    "strongly", " aligns", "underpriced", "premium", "very long time",
)

# The two hard skips produced by a FAILED/ABSENT market fetch (score-trades.ts:428-455):
#   liquidity undefined -> `input.liquidity ?? 0`      -> "liquidity $0 < min $..."
#   spread    undefined -> `input.spread ?? 0.1`       -> "spread 0.100 > max ..."
FALLBACK_LIQ = "liquidity $0 < min"
FALLBACK_SPRD = "spread 0.100 > max"


def is_annot(s: str) -> bool:
    return any(a in s.lower() for a in ANNOT)


def classify(risks_json):
    """-> (all_blocks, data_blocks, other_blocks)"""
    try:
        raw = json.loads(risks_json or "[]")
    except Exception:
        return None
    blocks = [str(x) for x in raw if not is_annot(str(x))]
    data = [b for b in blocks if b.startswith(FALLBACK_LIQ) or b.startswith(FALLBACK_SPRD)]
    other = [b for b in blocks if b not in data]
    return blocks, data, other


def cost_rail(df: pd.DataFrame) -> np.ndarray:
    """The ask we would pay for OUR side — identical to scripts/ml-ev.py."""
    is_no = df["outcome"].astype(str).str.upper().str.startswith("N")
    d_yes = (df["detected_price"] - df["yes_price"]).abs()
    d_no = (df["detected_price"] - df["no_price"]).abs()
    is_yes = np.where(df["yes_price"].notna() & df["no_price"].notna(), d_no >= d_yes, ~is_no)
    c = np.where(is_yes, df["best_ask"], 1 - df["best_bid"])
    mid = np.where(is_yes, df["yes_price"], df["no_price"])
    spr = pd.to_numeric(df["spread"], errors="coerce").fillna(0) / 2
    c = np.where(pd.notna(c), c, mid + spr)
    c = np.where(pd.notna(c), c, df["detected_price"])
    return np.clip(np.asarray(c, dtype=float), 0.01, 0.99)


def roi_ci(hit: np.ndarray, cost: np.ndarray, mkts: np.ndarray, n=600, seed=7):
    """ROI on a $1 stake per trade, plus a market-clustered bootstrap CI."""
    def roi(idx):
        h, c = hit[idx], cost[idx]
        shares = 1.0 / c
        pnl = np.where(h > 0, shares - 1.0, -1.0)
        return pnl.mean()

    allidx = np.arange(len(hit))
    point = roi(allidx)
    uq, inv = np.unique(mkts, return_inverse=True)
    groups = {g: np.where(inv == i)[0] for i, g in enumerate(uq)}
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(400 if len(uq) > 200 else 200):
        pick = rng.choice(len(uq), size=len(uq), replace=True)
        ii = np.concatenate([groups[uq[p]] for p in pick])
        out.append(roi(ii))
    return point, float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def main() -> int:
    df = pd.read_parquet(DEC)
    df = df[df["y_side_win"].notna()].copy()
    df["cost"] = cost_rail(df)
    decl = df[df["acted_any"] == 0].copy()

    con = sqlite3.connect(DB)
    rows = []
    ids = decl["decision_id"].tolist()
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        q = "SELECT id, risksJson FROM DecisionJournal WHERE id IN (%s)" % ",".join("?" * len(chunk))
        rows.extend(con.execute(q, chunk).fetchall())
    rmap = {r[0]: r[1] for r in rows}

    cls = decl["decision_id"].map(rmap).map(classify)
    decl["blocks"] = cls.map(lambda t: t[0] if t else None)
    decl["data_blocks"] = cls.map(lambda t: t[1] if t else None)
    decl["other_blocks"] = cls.map(lambda t: t[2] if t else None)
    got = decl[decl["blocks"].notna()].copy()

    # --- mechanism check ---
    has_liq0 = got["data_blocks"].map(lambda b: any(x.startswith(FALLBACK_LIQ) for x in b))
    has_spr = got["data_blocks"].map(lambda b: any(x.startswith(FALLBACK_SPRD) for x in b))
    print("=" * 78)
    print("MECHANISM — is 'liquidity $0' really a failed market fetch?")
    print("=" * 78)
    print(f"declined decisions classified : {len(got):,}")
    print(f"  carry 'liquidity $0'        : {int(has_liq0.sum()):,}")
    print(f"  of those, ALSO 'spread 0.100'> max': "
          f"{int((has_liq0 & has_spr).sum()):,} "
          f"({100*(has_liq0 & has_spr).sum()/max(int(has_liq0.sum()),1):.1f}%)")
    print("  ^ both fallbacks come from the same undefined-fetch path, so co-occurrence\n"
          "    near 100% confirms the gates are firing on absence, not on market quality.")

    # --- shadow population: killed ONLY by data-availability gates ---
    shadow = got[got["data_blocks"].map(len).gt(0) & got["other_blocks"].map(len).eq(0)].copy()
    print()
    print("=" * 78)
    print("SHADOW READ — rows whose ONLY blockers were the data-availability fallbacks")
    print("=" * 78)
    if shadow.empty:
        print("no such rows")
        return 0
    print(f"would be reconsidered : {len(shadow):,} decisions "
          f"({100*len(shadow)/len(got):.1f}% of declined flow)")

    # --- realised performance of the shadow population ---
    h = shadow["y_side_win"].values.astype(float)
    c = shadow["cost"].values
    m = shadow["market_id"].astype(str).values
    edge = float(np.mean(h - c))
    roi, lo, hi = roi_ci(h, c, m)
    print(f"  realised hit      : {h.mean():.3f}")
    print(f"  mean cost         : {c.mean():.3f}")
    print(f"  edge (hit - cost) : {edge:+.4f} per share")
    print(f"  ROI on $1 stakes  : {roi:+.4f}  CI[{lo:+.4f}, {hi:+.4f}]")

    # baseline: the rest of the declined book
    rest = got[~got.index.isin(shadow.index)]
    hr = rest["y_side_win"].values.astype(float)
    cr = rest["cost"].values
    print(f"\n  declined baseline : hit {hr.mean():.3f}  cost {cr.mean():.3f}  "
          f"edge {float(np.mean(hr-cr)):+.4f}")

    # acted baseline
    act = df[df["acted_any"] == 1]
    ha = act["y_side_win"].values.astype(float)
    ca = act["cost"].values
    print(f"  acted baseline    : hit {ha.mean():.3f}  cost {ca.mean():.3f}  "
          f"edge {float(np.mean(ha-ca)):+.4f}")

    # --- by price band: where would these rows have landed? ---
    print("\n  BY PRICE BAND (edge = realised hit - cost):")
    shadow["band"] = pd.cut(shadow["cost"], [0, .1, .2, .35, .5, .65, .8, .9, 1.01])
    tb = shadow.groupby("band", observed=True).apply(
        lambda g: pd.Series({
            "n": len(g),
            "hit": g["y_side_win"].mean(),
            "cost": g["cost"].mean(),
            "edge": g["y_side_win"].mean() - g["cost"].mean(),
            "roi": float(np.mean(np.where(g["y_side_win"] > 0, 1 / g["cost"] - 1, -1))),
        }), include_groups=False)
    print(tb.round(3).to_string())

    # --- capacity sensitivity: how many would actually clear the later gates? ---
    print("\n  NOTE: these rows failed no other gate, but the copy cap and sizing are\n"
          "  applied downstream of scoring, so this is an UPPER BOUND on new flow.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
