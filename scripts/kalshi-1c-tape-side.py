#!/usr/bin/env python3
"""Kalshi 1c tail, RETROSPECTIVE side: how much volume ever trades at the 1c level?

Reads the verbatim print files written by scripts/kalshi-tape-capture.py (>=100-contract floor)
and answers two questions the forward depth capture cannot answer from history:

  1. how often a >=100-contract 1c lift happens (events per captured hour), and
  2. per market, the TOTAL >=100-lot contracts printed at 1c — a LOWER bound on how much size
     stood at the 1c level and was consumed over that market's life.

(2) is the independent cross-check on the forward capture: if a market's whole-life 1c lift is
smaller than the resting size observed at 1c, then no order at the back of that queue can ever
fill, whatever the print sizes were. Because the tape floor is 100 contracts, both numbers
under-count the true volume — that direction is stated, not hidden.

Defaults to the capture that built the parent read; override with --tape.
"""
import argparse
import collections
import glob
import gzip
import json
import statistics


def q(sorted_vals, p):
    if not sorted_vals:
        return None
    return sorted_vals[min(len(sorted_vals) - 1, int(p * len(sorted_vals)))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tape", default="/Users/xsnyde2/polymarket-copybot/.worktrees/t_bcf3492a/data/kalshi-tape")
    ap.add_argument("--out", default=None, help="write a JSON summary here")
    args = ap.parse_args()

    tape = args.tape
    captured = holes = 0.0
    for line in open(tape + "/coverage.jsonl"):
        r = json.loads(line)
        if r.get("window_captured_seconds"):
            captured += r["window_captured_seconds"] / 3600.0
        if r.get("hole_minutes_before_window"):
            holes += r["hole_minutes_before_window"] / 60.0
    print("captured hours (all families): %.2f   holes: %.2f h" % (captured, holes))

    per_market = collections.defaultdict(float)
    prints = big = 0
    byhour = collections.Counter()
    sizes = []
    for fp in sorted(glob.glob(tape + "/prints-*.jsonl.gz")):
        with gzip.open(fp, "rt") as fh:
            for line in fh:
                r = json.loads(line)
                if r["family"] != "KXBTCD" or r["yes_price"] != 0.01 or r["taker_side"] != "yes":
                    continue
                prints += 1
                c = r["contracts"]
                per_market[r["ticker"]] += c
                sizes.append(c)
                if c >= 100:
                    big += 1
                    byhour[r["ts"][:13]] += 1

    print("KXBTCD 1c taker-buy-yes prints (>=100 floor): %d over %d markets" % (prints, len(per_market)))
    print("of those >=100 contracts: %d" % big)
    sizes.sort()
    if sizes:
        print("print size at 1c: min=%.0f p25=%.0f median=%.0f p75=%.0f p90=%.0f max=%.0f"
              % (sizes[0], q(sizes, .25), statistics.median(sizes), q(sizes, .75), q(sizes, .90), sizes[-1]))

    tot = sorted(per_market.values())
    print("\nper-market TOTAL >=100-lot contracts lifted at 1c (lower bound on level depth consumed):")
    print("  n=%d min=%.0f p25=%.0f median=%.0f p75=%.0f p90=%.0f max=%.0f"
          % (len(tot), tot[0], q(tot, .25), statistics.median(tot), q(tot, .75), q(tot, .90), tot[-1]))
    shares = {}
    for thr in (100, 500, 1000, 5000, 10000, 20000, 40000):
        k = sum(1 for t in tot if t >= thr)
        shares[str(thr)] = [k, round(100.0 * k / len(tot), 1)]
        print("  share of markets with total lifted >= %6d: %5d/%d (%.1f%%)" % (thr, k, len(tot), 100.0 * k / len(tot)))

    hrs = sorted(byhour.items())
    print("\n>=100-lot 1c print events per captured hour, across %d distinct hours: %.2f"
          % (len(hrs), big / captured if captured else 0))
    print("busiest hours (events/hour):")
    for h, n in sorted(byhour.items(), key=lambda kv: -kv[1])[:6]:
        print("   %s  %d" % (h, n))

    if args.out:
        payload = {
            "source_tape": tape,
            "captured_hours": round(captured, 2),
            "hole_hours": round(holes, 2),
            "prints_at_1c": prints,
            "markets_with_a_1c_print": len(per_market),
            "print_size_floor": 100,
            "print_size_percentiles": {
                "min": sizes[0] if sizes else None,
                "p25": q(sizes, .25), "median": statistics.median(sizes) if sizes else None,
                "p75": q(sizes, .75), "p90": q(sizes, .90), "max": sizes[-1] if sizes else None,
            },
            "per_market_total_lifted": {
                "p25": q(tot, .25), "median": statistics.median(tot),
                "p75": q(tot, .75), "p90": q(tot, .90), "max": tot[-1],
            },
            "share_of_markets_with_total_lifted_ge": shares,
            "events_per_captured_hour": round(big / captured, 2) if captured else None,
            "hourly_event_counts": dict(sorted(byhour.items())),
        }
        with open(args.out, "w") as fh:
            json.dump(payload, fh, indent=1)
        print("\nwrote ->", args.out)


if __name__ == "__main__":
    main()
