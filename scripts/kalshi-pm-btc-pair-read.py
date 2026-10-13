#!/usr/bin/env python3
"""Kalshi x Polymarket BTC up/down PAIRED read — ANALYZER and GATE (card kalshi-pm-btc-pair-prereg).

PRE-REGISTERED 2026-10-13, BEFORE any sample row existed (the sampler's first row is the
`run_id` epoch of the first invocation after this file was written). Do not move the gate.

THE TRADE BEING PRICED
----------------------
Two legs, opposite venues, same 15-minute window, same binary proposition:
    direction A = PM Up   + Kalshi No     (both lose only when Kalshi=up  AND PM=down)
    direction B = PM Down + Kalshi Yes    (both lose only when Kalshi=down AND PM=up)
Under oracle AGREEMENT each pair pays exactly 1.00; the fatal case above pays 0.00; the other
disagreement direction pays 2.00 and is deliberately IGNORED (conservative). Note A and B are
mirrors of each other: A_cost + B_cost is pinned near 2.00 + both spreads, so ONE of them being
cheap necessarily means the other is expensive, and neither is "free" — the question the gate
answers is whether the cheap side's expected value survives its own fatal-oracle rate.

IDENTITY CHECK (printed before any verdict) — is a "net" a real dislocation or just the spread?
    net_B ~= (PM's bid for Up) - (Kalshi's ask for Yes) - fees     [the cross-venue side spread]
so the read also prints that side spread, its persistence WITHIN each window (first vs last
sample), and the A+B mirror sum. A gap that collapses inside the window is a latency artefact,
not an opportunity.

GATE (frozen)
    For each direction: take per-window the BEST net available at an executable size of at
    least --min-size pairs (default 50), then charge that leg's MEASURED fatal-oracle rate:
        EV = net * (1 - p_fatal) + (-cost) * p_fatal
    with p_fatal the Wilson 95% UPPER bound of P(PM=down & Kalshi=up) for A and
    P(PM=up & Kalshi=down) for B, read from the oracle matrix (scripts/kalshi-pm-btc-updown-read.py
    --json data/kalshi-pm-btc-oracle.json). Report the market-clustered bootstrap CI over windows.
    PASS  <=> CI lower bound > 0 on at least one direction.
    FAIL  -> the honest close is "both venues price the same 15 minutes correctly" and nothing
             is built; the failure is a result, not a setback.

Both `net` (conservative Kalshi ask) and `net_optimistic` (better Kalshi ask) are reported; the
GATE is evaluated on the CONSERVATIVE pair only.

Usage: python3 scripts/kalshi-pm-btc-pair-read.py [--min-size 50] [--min-windows 288]
"""

from __future__ import annotations

import argparse
import json
import math
import glob
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "kalshi-pm-btc-pair.jsonl"
ORACLE = ROOT / "data" / "kalshi-pm-btc-oracle.json"
DIRS = ("A", "B")


def wilson_ci(k, n, z=1.96):
    if not n:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def load_oracle():
    """Per-direction fatal-oracle probability from the measured 2x2 confusion matrix."""
    if not ORACLE.exists():
        return None
    with ORACLE.open() as fh:
        data = json.load(fh)
    cells = data.get("cells") or {}
    total = sum(cells.values()) or 0
    if not total:
        return None
    # A is fatal when PM=down AND Kalshi=up ; B when PM=up AND Kalshi=down
    fatal_a = cells.get("kalshi_up_pm_down", 0)
    fatal_b = cells.get("kalshi_down_pm_up", 0)
    lo_a, hi_a = wilson_ci(fatal_a, total)
    lo_b, hi_b = wilson_ci(fatal_b, total)
    return {"asOf": data.get("asOf"), "windows": data.get("windows_checked"), "total": total,
            "cells": cells,
            "A": {"fatal_point": fatal_a / total, "fatal_upper": hi_a, "fatal_lower": lo_a},
            "B": {"fatal_point": fatal_b / total, "fatal_upper": hi_b, "fatal_lower": lo_b},
            "aggregate_disagreement_upper": wilson_ci(fatal_a + fatal_b, total)[1]}


def percentile(sorted_vals, q):
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, max(0, int(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-size", type=float, default=50.0,
                    help="pairs executable at the touch required to count an opportunity")
    ap.add_argument("--min-windows", type=int, default=288,
                    help="pre-registered sample floor: 288 windows = 72h of 15-min windows")
    ap.add_argument("--boot", type=int, default=4000)
    ap.add_argument("--out", default=None)
    ap.add_argument("--samples", default=str(ROOT / "data" / "kalshi-pm-btc-pair-*.jsonl"),
                    help="samples JSONL or glob (default: the cron sampler's rotated series; "
                         "coverage rows live in kalshi-pm-pair-coverage.jsonl and are not read)")
    args = ap.parse_args()

    # the sampler rotates per UTC day, so read the whole series (and tolerate a plain path)
    if any(ch in args.samples for ch in "*?["):
        samples_paths = [Path(p) for p in sorted(glob.glob(args.samples))]
    else:
        samples_paths = [Path(args.samples)] if Path(args.samples).exists() else []
    if not samples_paths:
        print("no samples yet at %s — the sampler has not run." % args.samples)
        return 0
    rows = []
    for sp in samples_paths:
        with sp.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    # a sample row must carry a window and a pairs block; this also keeps any non-sample JSONL
    # (e.g. a coverage row) out of the statistics
    ok = [r for r in rows if not r.get("error") and r.get("bucket") and isinstance(r.get("pairs"), dict)]
    print("samples: %d rows total, %d without error, %d windows"
          % (len(rows), len(ok), len({r.get("bucket") for r in ok})))
    if not ok:
        print("no usable samples yet.")
        return 0

    oracle = load_oracle()
    if oracle:
        print("oracle matrix: %d windows, fatal(A)=%.4f (upper %.4f), fatal(B)=%.4f (upper %.4f)"
              % (oracle["total"], oracle["A"]["fatal_point"], oracle["A"]["fatal_upper"],
                 oracle["B"]["fatal_point"], oracle["B"]["fatal_upper"]))
    else:
        print("⚠️  oracle matrix missing (%s) — run: python3 scripts/kalshi-pm-btc-updown-read.py "
              "--outcomes 288 --json data/kalshi-pm-btc-oracle.json  (gate needs it)" % ORACLE.name)

    # ---- per-window aggregation -------------------------------------------------
    print("sample files: %d (%s)" % (len(samples_paths),
                                     ", ".join(p.name for p in samples_paths[:4])))
    per_window = defaultdict(lambda: {"A": [], "B": [], "skew": [], "side_gaps": []})
    for r in ok:
        bucket = r.get("bucket")
        w = per_window[bucket]
        for d in DIRS:
            p = (r.get("pairs") or {}).get(d) or {}
            if p.get("complete") and (p.get("pairs_executable") or 0) >= args.min_size:
                w[d].append({"net": p["net"], "net_opt": p.get("net_optimistic"),
                             "cost": p["cost"], "size": p["pairs_executable"]})
        if r.get("read_skew_ms") is not None:
            w["skew"].append(r["read_skew_ms"])
        # cross-venue side spread: PM bid for Up vs Kalshi ask for Yes
        pm_bid = (r.get("pm") or {}).get("up_bid")
        kal_ask = (r.get("kalshi") or {}).get("yes_ask")
        if pm_bid is not None and kal_ask is not None:
            w["side_gaps"].append(round(pm_bid - kal_ask, 4))

    windows = sorted(per_window)
    print("windows with ≥1 qualifying sample: %d (floor %d)" % (len(windows), args.min_windows))
    skews = sorted(s for w in per_window.values() for s in w["skew"])
    if skews:
        print("read skew between venues: median %d ms, p90 %d ms, max %d ms (card spec: <1000)"
              % (skews[len(skews) // 2], skews[int(0.9 * len(skews))], skews[-1]))

    # ---- identity checks --------------------------------------------------------
    both = [w for w in per_window.values() if w["A"] and w["B"]]
    if both:
        sums = [max(x["cost"] for x in w["A"]) + max(x["cost"] for x in w["B"]) for w in both]
        sums.sort()
        print("mirror identity: median best A_cost + best B_cost = %.4f (2.00 + both spreads "
              "would be expected)" % percentile(sums, 0.5))
    gaps_first_last = []
    for w in per_window.values():
        if len(w["side_gaps"]) >= 2:
            gaps_first_last.append((w["side_gaps"][0], w["side_gaps"][-1]))
    if gaps_first_last:
        firsts = sorted(a for a, _ in gaps_first_last)
        lasts = sorted(b for _, b in gaps_first_last)
        print("cross-venue side spread (PM Up bid − Kalshi Yes ask): first-sample median %+.4f, "
              "last-sample median %+.4f across %d windows — a gap that collapses inside the "
              "window is a latency artefact" % (percentile(firsts, 0.5), percentile(lasts, 0.5),
                                                len(gaps_first_last)))

    # ---- GATE -------------------------------------------------------------------
    results = {}
    for d in DIRS:
        best = [max(x["net"] for x in per_window[w][d]) for w in windows if per_window[w][d]]
        if not best:
            print("\ndirection %s: no qualifying opportunities at size ≥ %.0f" % (d, args.min_size))
            results[d] = {"n_windows": 0}
            continue
        best_sorted = sorted(best)
        point = sum(best) / len(best)
        rng = random.Random(11)
        boots = sorted(sum(best[rng.randrange(len(best))] for _ in range(len(best))) / len(best)
                       for _ in range(args.boot))
        lo, hi = boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]
        share_pos = sum(1 for b in best if b > 0) / len(best)
        # per-window cost for the fatal-case loss term
        costs = [max(x["cost"] for x in per_window[w][d]) for w in windows if per_window[w][d]]
        mean_cost = sum(costs) / len(costs)
        line = ("direction %s: %d windows, best net median %+.4f mean %+.4f p10 %+.4f p90 %+.4f, "
                "%d%% of windows positive, clustered 95%% CI [%+.4f, %+.4f]"
                % (d, len(best), percentile(best_sorted, 0.5), point, percentile(best_sorted, 0.1),
                   percentile(best_sorted, 0.9), round(100 * share_pos), lo, hi))
        print("\n" + line)
        results[d] = {"n_windows": len(best), "best_median": percentile(best_sorted, 0.5),
                      "best_mean": point, "ci95": [lo, hi], "share_positive": share_pos,
                      "mean_cost": mean_cost}
        if oracle:
            for label, p_fatal in (("point", oracle[d]["fatal_point"]),
                                   ("upper-bound", oracle[d]["fatal_upper"])):
                ev = sum(b * (1 - p_fatal) - c * p_fatal
                         for b, c in zip(best, costs)) / len(best)
                boots_ev = []
                pairs = list(zip(best, costs))
                for _ in range(args.boot):
                    s = [pairs[rng.randrange(len(pairs))] for _ in range(len(pairs))]
                    boots_ev.append(sum(b * (1 - p_fatal) - c * p_fatal for b, c in s) / len(s))
                boots_ev.sort()
                elo, ehi = boots_ev[int(0.025 * len(boots_ev))], boots_ev[int(0.975 * len(boots_ev)) - 1]
                verdict = "PASS" if elo > 0 else "fail"
                print("    EV after %s fatal-oracle haircut (%.4f): %+.4f  95%% CI [%+.4f, %+.4f] -> %s"
                      % (label, p_fatal, ev, elo, ehi, verdict))
                results[d]["ev_" + label] = {"p_fatal": p_fatal, "ev": ev, "ci95": [elo, ehi],
                                             "verdict": verdict}

    passes = [d for d in DIRS if (results.get(d) or {}).get("ev_upper-bound", {}).get("verdict") == "PASS"]
    enough = len(windows) >= args.min_windows
    print("\n" + ("=" * 78))
    if not enough:
        print("VERDICT: INSUFFICIENT SAMPLE — %d/%d windows at size ≥ %.0f. No claim is made."
              % (len(windows), args.min_windows, args.min_size))
    elif passes:
        print("VERDICT: GATE PASS on direction(s) %s — the paired trade clears its measured "
              "oracle-basis risk at the conservative (worse-ask) price. Approval required before "
              "anything is built; this card proposes no live-path change by itself." % ",".join(passes))
    else:
        print("VERDICT: GATE FAIL — no direction clears its own fatal-oracle rate at the "
              "conservative price. The honest close: both venues price the same 15 minutes "
              "correctly, and nothing gets built.")
    print("=" * 78)

    out = args.out or str(ROOT / "data" / ("kalshi-pm-btc-pair-read-%s.json"
                                           % datetime.now(timezone.utc).strftime("%Y%m%d")))
    payload = {"asOf": datetime.now(timezone.utc).isoformat(), "samples": len(rows),
               "usable_samples": len(ok), "windows": len(windows),
               "min_size_pairs": args.min_size, "min_windows_floor": args.min_windows,
               "oracle": oracle, "results": results, "gate_pass": passes,
               "sufficient_sample": enough}
    Path(out).write_text(json.dumps(payload, indent=1))
    print("wrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
