#!/usr/bin/env python3
"""
horizon-margin-replay.py — the read-only measurement approved from the DRADIS audit (2026-10-15).

Question (pre-registered in drafts/asset-audit-dradis-20261015.md §5): do the C-200 legs that our
SHADOW price-edge gate admits on a FLAT 0.05 margin, but that a time-to-resolution-scaled margin would
reject, carry realized net PnL at or below zero?

Pre-registered decision rule:
    if flip-set mean realized net PnL/leg < 0 with a wallet-clustered CI excluding 0 at n >= 30
        -> adopt the scaled margin as a SHADOW spec for a further 30-day window
    else drop

Read-only: no rule, no size, no live path, no stored value is touched. Nothing is adopted by this run.

WHAT IS OURS vs WHAT IS BORROWED
  ours:     the gate (src/lib/scoring/price-edge.ts, status shadow): edge = pWin - price - fee,
            admit iff edge > 0.05; pWin = sigmoid(a + b*z), constants read from PRICE_EDGE_SPEC_V1.
  borrowed: only the SHAPE of DRADIS's required_edge (src/vipers/bookline_impl.rs):
            base * sqrt(remaining / span), capped at base, floored at min_edge — i.e. demand more
            discount the further out settlement is, relax it into the endgame.
  NOT borrowed: its absolute scale. Their base/min edges are per-share numbers for a resting-bid
            strategy on a 1-hour window; ours is a probability-space admission margin on legs with
            hours-to-days TTR. So the anchor is a DECLARED CHOICE here, and the sensitivity grid
            below is what tells you whether the answer survives it.

Usage:
  python3 scripts/horizon-margin-replay.py                 # primary parameterization + grid
  python3 scripts/horizon-margin-replay.py --csv X --reps 20000
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CSV = REPO / "data" / "decision-dataset.csv"
OUT_JSON = REPO / "data" / "horizon-margin-replay.json"

# --- our gate, verbatim from src/lib/scoring/price-edge.ts (asserted equal by tests/price-edge.test.ts)
SPEC = {"mean": 0.6672113499908179, "sd": 1.8361025406657638,
        "a": 0.4991328447815187, "b": 1.234131940373049, "margin": 0.05}

# --- declared PRIMARY parameterization (fixed before looking at outcomes)
PRIMARY = {"taper_secs": 24 * 3600, "min_edge": 0.02, "cap": 0.10, "base": 0.05}
GRID_TAPER = [6 * 3600, 24 * 3600, 72 * 3600, 168 * 3600]
GRID_CAP = [0.10, 0.20]


def p_win(price: float) -> float | None:
    if not (0 < price < 1):
        return None
    logit = math.log(price / (1 - price))
    z = SPEC["a"] + SPEC["b"] * ((logit - SPEC["mean"]) / SPEC["sd"])
    return 1 / (1 + math.exp(-z))


def scaled_margin(secs_left: float, taper: float, mn: float, cap: float, base: float) -> float:
    """DRADIS shape: base*sqrt(secs/taper), floored at mn, capped at cap. base is the value the
    scaled bar takes AT the taper (so inside the taper it is looser than flat, beyond it stricter)."""
    if secs_left <= 0:
        return mn
    m = base * math.sqrt(secs_left / taper)
    return max(mn, min(cap, m))


def load(csv_path: Path, bot: str, settled_only: bool) -> tuple[list[dict], dict]:
    rows, drops = [], defaultdict(int)
    with csv_path.open() as fh:
        for r in csv.DictReader(fh):
            if r.get("bot_id") != bot:
                drops["other-bot"] += 1
                continue
            if settled_only and not (r.get("closed_at") or "").strip():
                drops["unsettled"] += 1
                continue
            try:
                price = float(r["entry_price"])
            except (TypeError, ValueError):
                drops["no-price"] += 1
                continue
            p = p_win(price)
            if p is None:
                drops["price-outside-(0,1)"] += 1
                continue
            raw_fee = (r.get("fee_rate") or "").strip()
            try:
                fee_rate = float(raw_fee) if raw_fee else 0.05
            except ValueError:
                fee_rate = 0.05
            fee = fee_rate * price * (1 - price)
            # realized NET pnl per leg (the REC's metric); fall back to entry-net, then gross
            raw_pnl = (r.get("pnl_net_full") or r.get("pnl_net_entry") or r.get("pnl_gross") or "").strip()
            try:
                pnl_f = float(raw_pnl)
            except ValueError:
                drops["no-pnl"] += 1
                continue
            try:
                secs = float(r["ttr_hours"]) * 3600.0
            except (TypeError, ValueError):
                drops["no-ttr"] += 1
                continue
            rows.append({"wallet": r.get("wallet") or "?", "price": price, "edge": p - price - fee,
                         "pnl": pnl_f, "secs": secs, "win": 1.0 if str(r.get("y_win")) == "1" else 0.0,
                         "fee_rate": fee_rate})
    return rows, dict(drops)


def cluster_bootstrap_ci(rows: list[dict], reps: int, seed: int = 20261015) -> tuple[float, float]:
    """95% CI for the mean, resampling WALLETS (not legs): legs from one wallet are one decision."""
    by_wallet: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_wallet[r["wallet"]].append(r["pnl"])
    wallets = list(by_wallet)
    if len(wallets) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = []
    for _ in range(reps):
        pool = [pnl for _ in wallets for pnl in by_wallet[rng.choice(wallets)]]
        if pool:
            means.append(sum(pool) / len(pool))
    means.sort()
    return means[int(0.025 * len(means))], means[int(0.975 * len(means)) - 1]


def evaluate(rows: list[dict], taper: float, mn: float, cap: float, base: float,
             reps: int) -> dict:
    flat, flip, kept = 0, [], []
    for r in rows:
        m = scaled_margin(r["secs"], taper, mn, cap, base)
        admitted_flat = r["edge"] > SPEC["margin"]
        admitted_scaled = r["edge"] > m
        r = {**r, "margin_scaled": m}
        if admitted_flat:
            flat += 1
            (kept if admitted_scaled else flip).append(r)
    def stats(rs: list[dict]) -> dict:
        if not rs:
            return {"n": 0}
        pnls = [x["pnl"] for x in rs]
        lo, hi = cluster_bootstrap_ci(rs, reps)
        return {"n": len(rs), "mean_pnl_per_leg": round(statistics.mean(pnls), 4),
                "median": round(statistics.median(pnls), 4),
                "win_rate": round(sum(x["win"] for x in rs) / len(rs), 4),
                "wallets": len({x["wallet"] for x in rs}),
                "ci95_clustered": [round(lo, 4), round(hi, 4)]}
    return {"params": {"taper_hours": taper / 3600, "min_edge": mn, "cap": cap, "base": base},
            "universe": len(rows), "admitted_flat": flat,
            "flip_set": stats(flip), "kept_set": stats(kept)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--bot", default="BANKROLL_200")
    ap.add_argument("--reps", type=int, default=10000)
    ap.add_argument("--include-unsettled", action="store_true")
    a = ap.parse_args()

    rows, drops = load(Path(a.csv), a.bot, settled_only=not a.include_unsettled)
    if not rows:
        print("no usable legs — check the dataset path/columns", file=sys.stderr)
        return 1

    primary = evaluate(rows, PRIMARY["taper_secs"], PRIMARY["min_edge"], PRIMARY["cap"],
                       PRIMARY["base"], a.reps)
    grid = []
    for taper in GRID_TAPER:
        for cap in GRID_CAP:
            g = evaluate(rows, taper, PRIMARY["min_edge"], cap, PRIMARY["base"], a.reps)
            grid.append({"taper_hours": taper / 3600, "cap": cap,
                         "flip_n": g["flip_set"]["n"],
                         "flip_mean": g["flip_set"].get("mean_pnl_per_leg"),
                         "flip_ci": g["flip_set"].get("ci95_clustered"),
                         "kept_mean": g["kept_set"].get("mean_pnl_per_leg")})

    # ---- pre-registered decision rule, applied literally
    fs = primary["flip_set"]
    n, mean = fs.get("n", 0), fs.get("mean_pnl_per_leg")
    lo, hi = fs.get("ci95_clustered", [float("nan")] * 2)
    if n < 30:
        verdict, why = "INSUFFICIENT", f"flip set n={n} < 30 — the rule requires n>=30"
    elif mean is not None and mean < 0 and hi < 0:
        verdict, why = "RULE FIRES — ADOPT AS SHADOW", \
            f"flip mean {mean:+.4f}/leg with clustered CI [{lo:+.4f}, {hi:+.4f}] excluding 0 at n={n}"
    else:
        verdict, why = "DROP", (f"flip mean {mean:+.4f}/leg, clustered CI [{lo:+.4f}, {hi:+.4f}]"
                                + (" includes 0" if not (lo > 0 or hi < 0) else "")
                                + (f"; mean not negative" if (mean is not None and mean >= 0) else ""))

    ttr = sorted(r["secs"] / 3600 for r in rows)
    out = {"generated": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
           "source_csv": str(Path(a.csv).relative_to(REPO)), "bot": a.bot,
           "settled_only": not a.include_unsettled, "bootstrap_reps": a.reps,
           "drops": drops,
           "ttr_hours": {"min": round(ttr[0], 2), "p25": round(ttr[len(ttr) // 4], 2),
                         "median": round(ttr[len(ttr) // 2], 2), "p75": round(ttr[3 * len(ttr) // 4], 2),
                         "max": round(ttr[-1], 2)},
           "primary": primary, "grid": grid, "verdict": {"state": verdict, "why": why},
           "note": "Read-only replay. Nothing adopted or changed by this run; the shadow spec is only "
                   "written if the pre-registered rule fires AND the user approves that step."}
    OUT_JSON.write_text(json.dumps(out, indent=1) + "\n")

    print(f"universe: {primary['universe']} settled {a.bot} legs · admitted flat@0.05: "
          f"{primary['admitted_flat']} · drops: {drops or 'none'}")
    print(f"TTR hours: min {out['ttr_hours']['min']} · p25 {out['ttr_hours']['p25']} · "
          f"median {out['ttr_hours']['median']} · p75 {out['ttr_hours']['p75']} · max {out['ttr_hours']['max']}")
    for label in ("flip_set", "kept_set"):
        s = primary[label]
        if s.get("n"):
            print(f"{label:9s}: n={s['n']:4d} wallets={s['wallets']:3d} mean {s['mean_pnl_per_leg']:+.4f}/leg "
                  f"median {s['median']:+.4f} win {s['win_rate']:.1%} CI95(clustered) "
                  f"[{s['ci95_clustered'][0]:+.4f}, {s['ci95_clustered'][1]:+.4f}]")
        else:
            print(f"{label:9s}: n=0")
    print(f"\nVERDICT: {verdict}\n  {why}")
    print("\nsensitivity grid (taper x cap):")
    for g in grid:
        ci = g["flip_ci"] or [float("nan")] * 2
        print(f"  taper {g['taper_hours']:6.0f}h cap {g['cap']:.2f} → flip n={g['flip_n']:4d} "
              f"mean {g['flip_mean'] if g['flip_mean'] is not None else float('nan'):+.4f} "
              f"CI [{ci[0]:+.3f}, {ci[1]:+.3f}] · kept mean "
              f"{g['kept_mean'] if g['kept_mean'] is not None else float('nan'):+.4f}")
    print(f"\nartifact: {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
