#!/usr/bin/env python3
"""ml-readmission-read.py — forward read on the ML-1b readmission pocket (READ-ONLY).

WHAT THIS ANSWERS
ML-1a found, in-sample on the discovery window, that skipped decisions in the live regime
(ruleSetVersion >= 49) at 0.50 <= price < 0.65 carried +0.1199 per share, CI [+0.0362, +0.2085].
This labels that pocket FORWARD, from venue truth rather than a snapshot proxy, and reports the
edge with a market-clustered bootstrap.

LABELS
Each skipped leg is labelled by comparing the outcome the wallet bought (`ObservedTrade.outcome`)
against the winning token name on the venue (`GET clob.polymarket.com/markets/{conditionId}` ->
the token whose `winner` is true -> its `outcome` string). Comparing NAMES rather than token
indices avoids assuming anything about token ordering for named-outcome markets
(Over/Under, team names). A leg whose stored outcome matches no token is excluded and counted,
never guessed.

MONEY
edge/share = payout(0 or 1) - detectedPrice. This is GROSS, matching how the discovery figure was
reported, so the two are directly comparable. Fees are NOT asserted: no defensible single fee law
covers this population (the 7% crypto schedule applies to crypto markets; most of these markets
carry no taker fee at all), so the read reports a sensitivity at 1c and 2c per share instead of
inventing one.

PRE-REGISTERED GATE (written before running)
  At the target sample, the market-clustered bootstrap CI on edge/share must exclude zero.
  REFUTED if the CI includes zero, or the positive edge is carried by < 10 markets, or the effect
  sits only in the 0.60-0.65 sub-band -- which would exonerate v63's 0.4-0.6 band and make the
  finding about the band v63 never covered.

READ-ONLY: writes data/ml/readmission-report.json and a resolution cache. It changes no rule,
opens no position, and touches no live lane.

Usage:
  python3 scripts/ml-readmission-read.py                      # whole live regime (v49+)
  python3 scripts/ml-readmission-read.py --from-version 63    # only since v63 (the contested band)
"""
import argparse
import json
import os
import sqlite3
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

DB = "prisma/dev.db"
OUT = "data/ml/readmission-report.json"
CACHE = "data/ml/readmission-cache.json"
CLOB = "https://clob.polymarket.com/markets/"
BAND_LO, BAND_HI = 0.50, 0.65
SPLIT = 0.60          # v63's skip band ends here; above this v63 does not cut
DISCOVERY_N = 1886    # ML-1a's sample size, for reference only
DISCOVERY_EDGE = 0.1199
MIN_MARKETS_FOR_GATE = 10
FEE_SENSITIVITY = (0.01, 0.02)


def load_legs(db, from_version, band_lo, band_hi):
    con = sqlite3.connect("file:{}?mode=ro".format(db), uri=True)
    q = """
        SELECT j.ruleSetVersion, o.marketId, o.conditionId, o.outcome, o.detectedPrice,
               j.reasonsJson, j.createdAt
        FROM DecisionJournal j
        JOIN ObservedTrade o ON o.id = j.observedTradeId
        WHERE j.decision != 'copy'
          AND j.ruleSetVersion >= ?
          AND o.detectedPrice >= ? AND o.detectedPrice < ?
          AND o.conditionId IS NOT NULL AND o.conditionId <> ''
    """
    rows = con.execute(q, (from_version, band_lo, band_hi)).fetchall()
    con.close()
    return [
        {"version": r[0], "market": r[1], "conditionId": r[2], "outcome": r[3],
         "price": float(r[4]), "reasons": r[5], "createdAt": r[6]}
        for r in rows
    ]


def load_cache(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def fetch_winner(condition_id, timeout=20):
    """Return the winning token's outcome NAME, or a state string. Never guesses."""
    req = urllib.request.Request(CLOB + condition_id, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        return {"state": "http_%d" % e.code}
    except Exception as e:
        return {"state": "fetch_" + type(e).__name__}
    toks = d.get("tokens") or []
    win = [t for t in toks if t.get("winner") in (True, "true")]
    if win:
        return {"state": "resolved", "winner": win[0].get("outcome"),
                "tokens": [t.get("outcome") for t in toks]}
    return {"state": "closed_without_winner" if d.get("closed") else "not_closed_yet"}


def resolve_all(condition_ids, cache_path, workers=8):
    cache = load_cache(cache_path)
    todo = [c for c in condition_ids if c not in cache or cache[c].get("state") != "resolved"]
    print("  markets: %d | cached resolved: %d | fetching: %d"
          % (len(condition_ids), len(condition_ids) - len(todo), len(todo)))
    if todo:
        def work(cid):
            return cid, fetch_winner(cid)
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for cid, res in ex.map(work, todo):
                cache[cid] = res
                done += 1
                if done % 250 == 0:
                    print("    ...%d/%d fetched" % (done, len(todo)))
        try:
            with open(cache_path, "w") as f:
                json.dump(cache, f)
        except Exception as e:
            print("  !! cache write failed: %s" % e)
    return cache


def cluster_bootstrap(values, clusters, B=2000, seed=11):
    """Resample MARKETS, not legs -- legs inside one market are not independent."""
    rng = np.random.default_rng(seed)
    by = defaultdict(list)
    for v, c in zip(values, clusters):
        by[c].append(v)
    keys = list(by)
    means = []
    for _ in range(B):
        pick = rng.choice(len(keys), size=len(keys), replace=True)
        pooled = []
        for i in pick:
            pooled.extend(by[keys[i]])
        if pooled:
            means.append(float(np.mean(pooled)))
    if not means:
        return None, None
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def summarise(legs, label):
    if not legs:
        print("  %-22s n=0" % label)
        return None
    v = np.array([l["edge"] for l in legs])
    cl = [l["market"] for l in legs]
    lo, hi = cluster_bootstrap(v.tolist(), cl)
    n_markets = len(set(cl))
    # concentration: what share of total positive edge comes from the single best market
    pos = defaultdict(float)
    for l in legs:
        pos[l["market"]] += l["edge"]
    top = sorted(pos.values(), reverse=True)
    total_pos = sum(p for p in top if p > 0) or 1e-9
    top10_share = sum(p for p in top[:10] if p > 0) / total_pos if total_pos > 0 else None
    row = {
        "label": label, "n": len(legs), "markets": n_markets,
        "edgePerShare": round(float(v.mean()), 4),
        "ci95": [None if lo is None else round(lo, 4), None if hi is None else round(hi, 4)],
        "winRatePct": round(100.0 * float(np.mean([l["payout"] for l in legs])), 2),
        "meanPrice": round(float(v.mean() + np.mean([l["price"] for l in legs])), 4),
        "top10MarketShareOfPositivePct": None if top10_share is None else round(100 * top10_share, 2),
        "netOfFee": {("%dc" % round(f * 100)): round(float(v.mean()) - f, 4) for f in FEE_SENSITIVITY},
    }
    print("  %-22s n=%-6d mkt=%-5d edge/sh %+0.4f  CI [%s, %s]  win %.2f%%  top10 %.1f%%"
          % (label, row["n"], row["markets"], row["edgePerShare"],
             "na" if lo is None else "%+0.4f" % lo, "na" if hi is None else "%+0.4f" % hi,
             row["winRatePct"], row["top10MarketShareOfPositivePct"] or 0.0))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--from-version", type=int, default=49)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    legs = load_legs(args.db, args.from_version, BAND_LO, BAND_HI)
    print("readmission pocket %.2f-%.2f, ruleSetVersion >= %d: %d skipped legs over %d markets"
          % (BAND_LO, BAND_HI, args.from_version, len(legs), len({l["market"] for l in legs})))
    if not legs:
        raise SystemExit("no legs in the pocket")

    cids = sorted({l["conditionId"] for l in legs})
    cache = resolve_all(cids, args.cache, workers=args.workers)

    states = Counter()
    labelled = []
    for l in legs:
        r = cache.get(l["conditionId"]) or {}
        st = r.get("state")
        if st != "resolved":
            states[st] += 1
            continue
        winner = (r.get("winner") or "").strip().lower()
        side = (l["outcome"] or "").strip().lower()
        if not winner or not side:
            states["blank_name"] += 1
            continue
        if side not in [str(t).strip().lower() for t in (r.get("tokens") or []) if t]:
            states["outcome_name_not_in_tokens"] += 1
            continue
        l2 = dict(l)
        l2["payout"] = 1.0 if side == winner else 0.0
        l2["edge"] = l2["payout"] - l2["price"]
        labelled.append(l2)
    states["resolved_labelled"] = len(labelled)

    print("\nlabelling: %s" % dict(states))
    if not labelled:
        raise SystemExit("nothing labelled")

    print("\n=== EDGE PER SHARE, venue-labelled (gross of fees) ===")
    rows = []
    overall = summarise(labelled, "all %0.2f-%0.2f" % (BAND_LO, BAND_HI))
    if overall is None:
        raise SystemExit("labelled legs produced no summary")
    rows.append(overall)
    inband = [l for l in labelled if l["price"] < SPLIT]
    above = [l for l in labelled if l["price"] >= SPLIT]
    r1 = summarise(inband, "in v63 band <%0.2f" % SPLIT)
    r2 = summarise(above, "%0.2f-%0.2f (v63 open)" % (SPLIT, BAND_HI))
    rows += [x for x in (r1, r2) if x]

    if args.from_version < 63:
        v63 = [l for l in labelled if l["version"] >= 63]
        r3 = summarise(v63, "v63+ subgroup")
        if r3:
            rows.append(r3)

    # --- pre-registered gate ---------------------------------------------------
    verdict, why = None, []
    ci_lo = overall["ci95"][0] if overall else None
    if overall is None or ci_lo is None:
        verdict, why = "INSUFFICIENT", ["no usable CI"]
    elif overall["markets"] < MIN_MARKETS_FOR_GATE:
        verdict, why = "INSUFFICIENT", ["fewer than %d markets" % MIN_MARKETS_FOR_GATE]
    elif ci_lo <= 0:
        verdict = "REFUTED"
        why.append("CI includes zero (lo %+.4f)" % ci_lo)
    elif r2 and r1 and r1["ci95"][0] is not None and r1["ci95"][0] <= 0 and r2["ci95"][0] > 0:
        verdict = "REFUTED"
        why.append("edge sits only in the %0.2f-%0.2f band v63 never covered -> v63 band exonerated"
                   % (SPLIT, BAND_HI))
    else:
        verdict = "CLEARED"
    print("\n=== PRE-REGISTERED GATE ===")
    print("  discovery reference: n=%d edge/sh %+0.4f (in-sample)" % (DISCOVERY_N, DISCOVERY_EDGE))
    print("  forward sample     : n=%d over %d markets (%.0f%% of discovery size)"
          % (overall["n"], overall["markets"], 100.0 * overall["n"] / DISCOVERY_N))
    print("  VERDICT: %s  %s" % (verdict, "; ".join(why) if why else ""))
    if overall["n"] < DISCOVERY_N:
        print("  NOTE: sample is below the discovery size, so a CLEARED read is provisional and a")
        print("        REFUTED read is not yet final -- keep accruing and re-run.")

    out = {
        "builtAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fromVersion": args.from_version,
        "band": [BAND_LO, BAND_HI], "split": SPLIT,
        "legs": len(legs), "labelled": len(labelled),
        "labelStates": dict(states),
        "rows": rows,
        "discovery": {"n": DISCOVERY_N, "edgePerShare": DISCOVERY_EDGE},
        "verdict": verdict, "reasons": why,
        "feeNote": "edge is GROSS. No single defensible fee law covers this population; the "
                   "netOfFee block shows a 1c and 2c sensitivity rather than asserting one.",
        "readOnly": True,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print("\nwrote %s" % args.out)


if __name__ == "__main__":
    main()
