#!/usr/bin/env python3
"""
ml-observe-read.py — forward decile economics for the ML lane's observe-only record.

WHAT IT DOES
Reads `data/ml/observe-log.jsonl` (written by ml-observe-record.py), derives each market's outcome
from its LAST snapshot using the same rule the training labels used, computes each observation's net
ROI at the ask it was recorded at, and reports decile economics per arm with CIs bootstrapped by
MARKET — the identical machinery used on the historical holdout, so the two are directly comparable.

RESOLUTION RULE (changed 2026-10-22, user-approved):
    DEFAULT is VENUE TRUTH -- join each market to its conditionId and read
    GET clob.polymarket.com/markets/{conditionId} -> tokens[].winner. A resolved market is cached
    permanently in data/ml/settlement-cache.json because resolutions are immutable.
    `--settlement-source=snapshot` restores the previous rule:
        last snapshot yesPrice >= 0.90 -> YES, <= 0.10 -> NO, else ABSTAIN (excluded).
    That rule is kept and still computed on every run for side-by-side comparison, because it was
    measured on 2026-10-22 to be reading noise: over 72 venue-resolved markets it settled ZERO, its
    last price sat a median 0.075 from 0.50 (the band needs 0.40), and it leaned the correct way only
    45.8% of the time -- below a coin flip. See drafts/ml-settlement-source-20261022.md.
    The old docstring claimed 99.5% agreement with OutcomeReview.finalOutcome; that was measured on
    the ACTED population, and OutcomeReview carries no marketId, so it cannot settle observe-lane
    markets at all.

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
import time
import urllib.error
import urllib.request
from collections import Counter

import numpy as np
import pandas as pd

DEFAULT_DB = "prisma/dev.db"
DEFAULT_LOG = "data/ml/observe-log.jsonl"
DEFAULT_OUT = "data/ml/observe-report.json"
DEFAULT_CACHE = "data/ml/settlement-cache.json"
# Bump when the outcome mapping changes: entries carrying a different value are refetched rather
# than trusted, so a mapping fix can never be masked by a stale cache.
CACHE_MAPPING = "tokens[0].winner"
CLOB_MARKET = "https://clob.polymarket.com/markets/"
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


def _snapshot_outcomes(ids, db=DEFAULT_DB):
    """The previous rule, kept for comparison: last snapshot yesPrice band."""
    con = sqlite3.connect("file:{}?mode=ro".format(db), uri=True)
    out = {}
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
                out[mid] = 1
            elif yes <= 0.10:
                out[mid] = 0
    con.close()
    return out


def _condition_ids(ids, db=DEFAULT_DB):
    con = sqlite3.connect("file:{}?mode=ro".format(db), uri=True)
    ph = ",".join("?" * len(ids))
    q = ("SELECT marketId, MAX(conditionId) FROM MarketSnapshot WHERE marketId IN ({}) "
         "AND conditionId IS NOT NULL AND conditionId <> '' GROUP BY marketId").format(ph)
    out = dict(con.execute(q, ids))
    con.close()
    return out


def _load_cache(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _venue_outcomes(ids, cache_path=DEFAULT_CACHE, db=DEFAULT_DB, sleep=0.25, fetch=True):
    """Venue truth: CLOB tokens[].winner. Resolutions are immutable, so they are cached forever.

    Returns (outcomes, stats). Any network failure leaves the market UNSETTLED rather than guessing --
    an abstention is honest, a fabricated label is not.
    """
    stats = Counter()
    cache = _load_cache(cache_path)
    out = {}
    cids = _condition_ids(ids, db)
    for mid in ids:
        cached = cache.get(mid)
        if isinstance(cached, dict) and cached.get("y") in (0, 1) and cached.get("mapping") == CACHE_MAPPING:
            out[mid] = int(cached["y"])
            stats["from_cache"] += 1
            continue
        cid = cids.get(mid)
        if not cid:
            stats["no_conditionId"] += 1
            continue
        if not fetch:
            stats["fetch_disabled"] += 1
            continue
        req = urllib.request.Request(CLOB_MARKET + cid, headers={"User-Agent": "Mozilla/5.0"})
        try:
            d = json.load(urllib.request.urlopen(req, timeout=20))
        except urllib.error.HTTPError as e:
            stats["http_%d" % e.code] += 1
            time.sleep(sleep)
            continue
        except Exception as e:
            stats["fetch_" + type(e).__name__] += 1
            time.sleep(sleep)
            continue
        toks = d.get("tokens") or []
        winners = [t for t in toks if t.get("winner") in (True, "true")]
        if winners:
            # y_yes is relative to TOKEN 0 -- Polymarket's tokens[0] is the YES / first-listed outcome.
            # Testing outcome == "Yes" instead would score every named-outcome market (Over/Under,
            # team names, "Under") as NO regardless of who actually won, which silently collapsed the
            # first run of this cache to 63 NO vs 9 YES.
            y = 1 if (toks and toks[0].get("winner") in (True, "true")) else 0
            out[mid] = y
            cache[mid] = {"y": y, "conditionId": cid, "mapping": CACHE_MAPPING,
                          "outcome": winners[0].get("outcome"),
                          "cachedAt": pd.Timestamp.utcnow().isoformat()}
            stats["resolved_now"] += 1
        elif d.get("closed"):
            stats["closed_without_winner"] += 1
        else:
            stats["not_closed_yet"] += 1
        time.sleep(sleep)
    try:
        with open(cache_path, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print("  !! could not write settlement cache: {}".format(e))
    return out, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--buckets", type=int, default=5)
    ap.add_argument("--settlement-source", choices=["venue", "snapshot"], default="venue",
                    help="which derivation labels y_yes; both are always computed and reported")
    ap.add_argument("--settlement-cache", default=DEFAULT_CACHE)
    ap.add_argument("--no-venue-fetch", action="store_true",
                    help="skip the CLOB network calls entirely (offline); falls back to snapshot")
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

    # --- settlement derivation -------------------------------------------------------------
    # Venue truth is the default; the old snapshot proxy is still computed every run so the two
    # can be reported side by side during the verification week.
    ids = obs["market_id"].dropna().unique().tolist()
    snap_map = _snapshot_outcomes(ids, args.db)
    venue_map, venue_stats = _venue_outcomes(
        ids, cache_path=args.settlement_cache, db=args.db, fetch=not args.no_venue_fetch)

    if args.settlement_source == "venue" and not (args.no_venue_fetch and not venue_map):
        resolved = venue_map
        source_used = "venue (clob tokens[].winner)"
    else:
        resolved = snap_map
        source_used = ("snapshot (last-price band) -- venue fetch disabled"
                       if args.no_venue_fetch else "snapshot (last-price band)")

    overlap = [m for m in ids if m in snap_map and m in venue_map]
    disagree = [m for m in overlap if snap_map[m] != venue_map[m]]
    obs_by_market = obs["market_id"].value_counts().to_dict()
    settled_obs_venue = int(sum(obs_by_market.get(m, 0) for m in venue_map))
    settled_obs_snap = int(sum(obs_by_market.get(m, 0) for m in snap_map))

    settlement = {
        "source": source_used,
        "venue_settled_markets": len(venue_map),
        "venue_settled_observations": settled_obs_venue,
        "snapshot_settled_markets": len(snap_map),
        "snapshot_settled_observations": settled_obs_snap,
        "decisive_overlap": len(overlap),
        "agreement_pct": (round(100.0 * (len(overlap) - len(disagree)) / len(overlap), 2)
                          if overlap else None),
        "disagreements": [{"market": m, "venue": venue_map[m], "snapshot": snap_map[m]}
                          for m in disagree[:50]],
        "market_state": dict(venue_stats),
        "cache": args.settlement_cache,
    }

    print("settlement source: {}".format(source_used))
    print("  markets with a venue outcome    : {:,} of {:,} ({:.1f}%)".format(
        len(venue_map), len(ids), 100.0 * len(venue_map) / max(len(ids), 1)))
    print("  markets with a snapshot outcome : {:,} of {:,} ({:.1f}%)".format(
        len(snap_map), len(ids), 100.0 * len(snap_map) / max(len(ids), 1)))
    print("  venue market states             : {}".format(dict(venue_stats)))
    if overlap:
        print("  decisive overlap {} | disagreements {}".format(len(overlap), len(disagree)))
    else:
        print("  decisive overlap 0 -> the two sources cannot be compared on this population")

    obs["y_yes"] = obs["market_id"].map(resolved)
    settled = obs[obs["y_yes"].notna()].copy()
    print("settled observations: {:,} (venue {:,} | snapshot {:,})".format(
        len(settled), settled_obs_venue, settled_obs_snap))

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
                "settlement": settlement,
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

    # A zero-test run is NOT the same as a tested-and-failed run. Before the settlement switch this
    # path was unreachable (settled was always empty); now that venue truth yields settlements early,
    # reporting "NOT_ESTABLISHED" here would claim a negative result we have not earned.
    if n_tests == 0:
        print("\n  => NOT YET: {:,} settled observations exist, but no arm has enough per bucket".format(
            len(settled)))
        print("     to build a table (needs >= {} settled per bucket). Still accumulating.".format(
            MIN_PER_BUCKET))
        write_report("NOT_YET", tables=tables, hits=[], n_tests=0, expected=0.0,
                     baseline=round(float(settled["roi_net_pct"].mean()), 3))
        return

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
