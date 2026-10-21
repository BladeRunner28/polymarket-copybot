#!/usr/bin/env python3
"""
ml-observe-read.py — forward decile economics for the ML lane's observe-only record.

WHAT IT DOES
Reads `data/ml/observe-log.jsonl` (written by ml-observe-record.py), derives each market's outcome
from its LAST snapshot using the same rule the training labels used, computes each observation's net
ROI at the ask it was recorded at, and reports decile economics per arm with CIs bootstrapped by
MARKET — the identical machinery used on the historical holdout, so the two are directly comparable.

RESOLUTION RULE (deliberately the same as build-ml-dataset.py):
    last snapshot yesPrice >= 0.90 -> YES, <= 0.10 -> NO, else ABSTAIN (excluded).
It agreed 99.5% with OutcomeReview.finalOutcome on the resolved acted population. It is a proxy, not
ground truth, so an abstaining or barely-crossing market is excluded rather than guessed.

HONESTY RULES BAKED IN
1. Nothing is reported until there are settled observations; the script says NOT YET rather than
   printing a decile table over a handful of rows.
2. Multiple-comparison count is printed alongside any "hit", because with N deciles x 3 arms a
   nominal 95% interval clears zero by chance about N/20 times.
3. Rows are split by `kind` (live vs anything else) and by day, so accumulation progress is visible
   and a forward read cannot silently include in-sample backfill.

Usage:
  .venv-ml/bin/python scripts/ml-observe-read.py
  .venv-ml/bin/python scripts/ml-observe-read.py --buckets 5
"""

import argparse
import json
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

DEFAULT_DB = "prisma/dev.db"
DEFAULT_LOG = "data/ml/observe-log.jsonl"
DEFAULT_OUT = "data/ml/observe-report.json"
MIN_PER_BUCKET = 60


def cluster_ci(values, clusters, B=400, seed=7):
    values = np.asarray(values, dtype=float)
    clusters = np.asarray(clusters)
    uniq = pd.unique(clusters)
    if len(uniq) < 3 or len(values) == 0:
        return (None, None)
    idx_by = pd.Series(range(len(clusters)), index=clusters).groupby(level=0).apply(
        lambda s: s.to_numpy()
    )
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(B):
        pick = rng.choice(len(idx_by), size=len(idx_by), replace=True)
        take = np.concatenate([idx_by.iloc[i] for i in pick])
        means.append(values[take].mean())
    means = np.asarray(means)
    return (round(float(np.percentile(means, 2.5)), 3), round(float(np.percentile(means, 97.5)), 3))


def bucket_table(df, score_col, buckets):
    d = df[[score_col, "roi_net_pct", "market_id"]].dropna()
    if len(d) < buckets * MIN_PER_BUCKET:
        return []
    d = d.assign(bin=pd.qcut(d[score_col].rank(method="first"), buckets, labels=False))
    out = []
    for b in range(buckets):
        g = d[d["bin"] == b]
        if g.empty:
            continue
        lo, hi = cluster_ci(g["roi_net_pct"].values, g["market_id"].values)
        out.append({
            "bucket": b + 1, "n": int(len(g)), "markets": int(g["market_id"].nunique()),
            "win_rate": round(float((g["roi_net_pct"] > 0).mean()) * 100.0, 2),
            "roi_net_pct": round(float(g["roi_net_pct"].mean()), 3),
            "ci_lo": lo, "ci_hi": hi,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--buckets", type=int, default=5)
    args = ap.parse_args()

    if not os.path.exists(args.log):
        print("NOT YET: no observe log at {}".format(args.log))
        print("Run scripts/ml-observe-record.py first.")
        return

    rows = []
    with open(args.log) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        print("NOT YET: observe log is empty")
        return
    obs = pd.DataFrame(rows)
    print("observations: {:,} | distinct markets: {:,} | kinds: {}".format(
        len(obs), obs["market_id"].nunique(), obs["kind"].value_counts().to_dict()))
    by_day = obs.groupby("day").size().to_dict()
    print("by day: {}".format(dict(sorted(by_day.items()))))

    # Derive y_yes from each market's LAST snapshot.
    con = sqlite3.connect("file:{}?mode=ro".format(args.db), uri=True)
    ids = obs["market_id"].dropna().unique().tolist()
    resolved = {}
    CHUNK = 900
    for i in range(0, len(ids), CHUNK):
        batch = ids[i:i + CHUNK]
        ph = ",".join("?" * len(batch))
        q = """
            SELECT s.marketId, s.yesPrice
            FROM MarketSnapshot s
            JOIN (SELECT marketId, MAX(collectedAt) AS mx FROM MarketSnapshot
                  WHERE isDemo = 0 GROUP BY marketId) l
              ON l.marketId = s.marketId AND l.mx = s.collectedAt
            WHERE s.marketId IN ({})
        """.format(ph)
        for mid, yes in con.execute(q, batch):
            if yes is None:
                continue
            if yes >= 0.90:
                resolved[mid] = 1
            elif yes <= 0.10:
                resolved[mid] = 0
    con.close()
    print("markets with a derived outcome: {:,} of {:,} ({:.1f}%)".format(
        len(resolved), len(ids), 100.0 * len(resolved) / max(len(ids), 1)))

    obs["y_yes"] = obs["market_id"].map(resolved)
    settled = obs[obs["y_yes"].notna()].copy()
    print("settled observations: {:,}".format(len(settled)))

    def write_report(status, tables=None, hits=None, n_tests=0, expected=0.0, baseline=None):
        """Always leave a report behind, including the NOT YET state -- the dashboard must be able
        to show 'accumulating' honestly rather than 404 on a missing file."""
        with open(args.out, "w") as f:
            json.dump({
                "built_at": pd.Timestamp.utcnow().isoformat(),
                "status": status,
                "observations": int(len(obs)),
                "distinct_markets": int(obs["market_id"].nunique()),
                "settled_observations": int(len(settled)),
                "settled_markets": int(settled["market_id"].nunique()) if len(settled) else 0,
                "by_day": dict(sorted(by_day.items())),
                "baseline_roi_net_pct": baseline,
                "buckets": args.buckets,
                "tables": tables or {},
                "nominal_tests": n_tests,
                "expected_hits_by_chance": expected,
                "hits": hits or [],
                "established": status == "CANDIDATE",
                "note": "Observe-only: the lane rates candidates and records them; it opens no positions.",
            }, f, indent=2, default=str)
        print("\nwrote {}".format(args.out))

    if settled.empty:
        print("\nNOT YET: no observations have resolved. The lane is recording; nothing to price.")
        write_report("NOT_YET")
        return

    settled["payout"] = np.where(settled["side"] == "YES", settled["y_yes"], 1.0 - settled["y_yes"])
    settled["roi_net"] = settled["payout"] / settled["cost_ps"] - 1.0
    settled["roi_net_pct"] = settled["roi_net"] * 100.0

    arms = ["p_profit", "ev", "roi_reg"]
    tables = {a: bucket_table(settled, a, args.buckets) for a in arms}
    n_tests = sum(len(t) for t in tables.values())
    print("\n=== FORWARD DECILE ECONOMICS (settled, net of fee+spread at the recorded ask) ===")
    print("    baseline mean net ROI: {:+.3f}%  over {} markets".format(
        float(settled["roi_net_pct"].mean()), settled["market_id"].nunique()))
    hits = []
    for a in arms:
        t = tables[a]
        if not t:
            print("\n  {}: NOT YET (needs >= {} settled per bucket)".format(a, MIN_PER_BUCKET))
            continue
        print("\n  --- {} ---".format(a))
        for r in t:
            ci = "[{:+.2f}, {:+.2f}]".format(r["ci_lo"], r["ci_hi"]) if r["ci_lo"] is not None else "[na]"
            print("    B{:<2} n={:<5} mkt={:<5} win {:>6.2f}%  net {:>+8.3f}%  CI {}".format(
                r["bucket"], r["n"], r["markets"], r["win_rate"], r["roi_net_pct"], ci))
            if r["ci_lo"] is not None and r["ci_lo"] > 0:
                hits.append({"arm": a, "bucket": r["bucket"], "roi": r["roi_net_pct"],
                             "ci": [r["ci_lo"], r["ci_hi"]], "n": r["n"], "markets": r["markets"]})

    expected = round(n_tests * 0.05, 2)
    print("\n=== VERDICT ===")
    print("  nominal 95% intervals computed: {} -> {:.2f} hits expected by chance".format(n_tests, expected))
    print("  buckets clearing zero: {}".format(len(hits)))
    if not hits:
        print("  => NOT ESTABLISHED. No arm ranks a forward cohort that is distinguishable from zero.")
    elif len(hits) <= expected:
        print("  => NOT ESTABLISHED. Hits are within chance for this many tests.")
    else:
        print("  => CANDIDATE: {} bucket(s) clear zero, above chance. Keep accumulating before".format(len(hits)))
        print("     any promotion decision; this is a forward signal, not a licence to trade.")

    write_report(
        "CANDIDATE" if (hits and len(hits) > expected) else "NOT_ESTABLISHED",
        tables=tables, hits=hits, n_tests=n_tests, expected=expected,
        baseline=round(float(settled["roi_net_pct"].mean()), 3),
    )


if __name__ == "__main__":
    main()
