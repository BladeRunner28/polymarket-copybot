#!/usr/bin/env python3
"""Deterministic-convergence READER (card btx2) — the gate's only voice. Read-only.

PRE-REGISTRATION: `drafts/btc-convergence-prereg-20261013.md`. This script implements the frozen
gate; it never invents a statistic the pre-registration does not name, and below the sample floor it
prints the SHORTFALL, not a percentage.

Order of output is part of the contract (the pair lane's lesson): the IDENTITY and STRUCTURAL checks
print BEFORE any verdict, so a verdict cannot be read without the checks that could explain it away.
  1. freshness + code-revision census (rows written under any other revision are EXCLUDED, counted)
  2. structural census: on a decided leg, was there an ASK on the determined side at all?
  3. sanity identities (mirror sum ~= 1.00 + spreads; loser's ask when a winner trades >= 0.99)
  4. Q1 gate: median edge, day-clustered bootstrap CI, canonical AND the 0.07 sensitivity arm
  5. the decision curve by minutes-since-determined (an edge that decays is a latency artefact)
  6. Q2: NO CLAIM until an estimator revision is frozen and pinned in the pre-registration

Usage: python3 scripts/btc-convergence-read.py [--dir data] [--json /tmp/out.json]
"""

from __future__ import annotations

import argparse
import glob
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PINNED_CODE = "b06650b8c215"          # sampler revision frozen by the pre-registration
SIZE_FLOOR = 50
FEE_SENSITIVITY_RATE = 0.07           # the pair lane's pinned crypto_fees_v2 taker rate
FLOOR_ROWS_Q1 = 1500                  # pre-registered: executable decided observations
FLOOR_DAYS_Q1 = 14
FLOOR_SUB99 = 200                     # determined-side ask < 0.99
BOOT_DRAWS = 10_000
STALE_HOURS = 6                       # no coverage line in this long -> say so loudly

SENSITIVITY_TREAT_AS_UNKNOWN = ("no_schedule_zero",)


def load(dirpath):
    rows, cov = [], []
    for f in sorted(glob.glob(str(Path(dirpath) / "btc-convergence-samples-*.jsonl"))):
        with open(f) as fh:
            for line in fh:
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    cpath = Path(dirpath) / "btc-convergence-coverage.jsonl"
    if cpath.exists():
        with open(cpath) as fh:
            for line in fh:
                if line.strip():
                    try:
                        cov.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return rows, cov


def cluster_bootstrap_ci(pairs, draws=BOOT_DRAWS, seed=13):
    """95% CI of the mean, resampling UTC DAYS with replacement (the pre-registered cluster).

    Rows inside a day are not independent: one day's High/Low decides many strikes at once, so an
    i.i.d. bootstrap would report a precision the sample does not have.
    """
    if not pairs:
        return None, None, 0
    by_day = defaultdict(list)
    for day, v in pairs:
        by_day[day].append(v)
    days = list(by_day)
    if not days:
        return None, None, 0
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        pick = [by_day[rng.choice(days)] for _ in days]
        flat = [v for grp in pick for v in grp]
        if flat:
            means.append(sum(flat) / len(flat))
    if not means:
        return None, None, len(days)
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[int(0.975 * len(means)) - 1]
    return lo, hi, len(days)


def edge_of_row(r, sensitivity=False):
    """(executable edge or None, why).  Sensitivity arm re-prices no_schedule_zero rows at 0.07."""
    q1 = r.get("q1") or {}
    ask, size = q1.get("ask"), q1.get("size")
    if ask is None:
        return None, "no_ask"
    fee = q1.get("fee")
    law = q1.get("fee_law")
    if sensitivity and law in SENSITIVITY_TREAT_AS_UNKNOWN:
        fee = FEE_SENSITIVITY_RATE * min(ask, 1.0 - ask)
    if fee is None:
        return None, law or "no_fee"
    if size is None or size < SIZE_FLOOR:
        return None, "thin"
    return 1.0 - ask - fee, "edge"


def q1_stats(rows, sensitivity=False):
    edges, reasons = [], Counter()
    for r in rows:
        e, why = edge_of_row(r, sensitivity)
        reasons[why] += 1
        if e is not None:
            day = str(r.get("ts", ""))[:10]
            edges.append((day, e))
    if not edges:
        return None
    vals = [v for _, v in edges]
    lo, hi, ndays = cluster_bootstrap_ci(edges)
    return {"n": len(vals), "days": ndays, "median": statistics.median(vals),
            "mean": statistics.fmean(vals), "ci_low": lo, "ci_high": hi,
            "p10": sorted(vals)[int(0.10 * len(vals))], "reasons": dict(reasons)}


def decision_curve(rows, sensitivity=False):
    buckets = [(0, 2), (2, 5), (5, 10), (10, 20), (20, 60), (60, 10 ** 6)]
    out = []
    for lo, hi in buckets:
        sel = [r for r in rows if (r.get("minutes_since_determined") is not None
                                   and lo <= r["minutes_since_determined"] < hi)]
        st = q1_stats(sel, sensitivity)
        if st:
            out.append({"bucket_min": [lo, None if hi > 10 ** 5 else hi], "n": st["n"],
                        "median_edge": st["median"], "mean_edge": st["mean"]})
    return out


def sanity_identities(rows):
    """The checks that come BEFORE the verdict. A cross-venue/book identity that fails means the
    numbers are a snapshot artefact, not an edge."""
    out = {}
    mirrors = []
    for r in rows:
        ya, na = r.get("yes_ask"), r.get("no_ask")
        if ya is not None and na is not None:
            mirrors.append(ya + na)
    if mirrors:
        out["mirror_sum_asks"] = {"n": len(mirrors), "median": round(statistics.median(mirrors), 4),
                                  "p10": round(sorted(mirrors)[int(0.1 * len(mirrors))], 4),
                                  "note": "buying both sides should cost ~1.00 + both spreads"}
    losers = [r.get("yes_ask") for r in rows
              if r.get("no_bid") is not None and r["no_bid"] >= 0.99 and r.get("yes_ask") is not None]
    if losers:
        out["loser_ask_when_winner_bids_99"] = {"n": len(losers), "max": max(losers),
                                                "median": round(statistics.median(losers), 4)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "data"))
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    rows_all, cov = load(a.dir)
    now = datetime.now(timezone.utc)

    print("=== btx2 · deterministic convergence · GATE READ ===")
    print(f"pre-registration: drafts/btc-convergence-prereg-20261013.md | pinned sampler code "
          f"{PINNED_CODE} | size floor {SIZE_FLOOR} shares | boot {BOOT_DRAWS} draws, cluster = UTC day")
    print(f"pre-registered floors: Q1 >= {FLOOR_ROWS_Q1} executable decided rows over >= {FLOOR_DAYS_Q1} "
          f"UTC days, incl >= {FLOOR_SUB99} rows with determined-side ask < 0.99")

    # ---- 1. freshness + revision census
    print("\n--- 1. coverage & revision census (rows under any other revision are EXCLUDED) ---")
    if not cov:
        print("  NO COVERAGE FILE — the sampler has never run (or wrote nowhere near here).")
    else:
        last = cov[-1]
        try:
            age = (now - datetime.fromisoformat(str(last["ts"]).replace("Z", "+00:00"))).total_seconds() / 3600
            print(f"  last tick : {last['ts']}  ({age:.1f} h ago)")
            if age > STALE_HOURS:
                print(f"  🟠 STALE: no coverage line in {age:.1f} h (threshold {STALE_HOURS} h)")
        except Exception:  # noqa: BLE001
            print(f"  last tick : {last.get('ts')}")
        print(f"  ticks recorded: {len(cov)} | rows this tick: {last.get('rows')} "
              f"| decided: {last.get('determined')} | stale-dropped: {last.get('dropped_stale')}")
        errs = [e for c in cov[-24:] for e in (c.get("errors") or [])]
        if errs:
            print(f"  errors in last 24 ticks: {len(errs)} | e.g. {errs[:2]}")
        hashes = Counter(str(r.get("code")) for r in rows_all)
        for h, n in hashes.most_common():
            tag = "PINNED" if h == PINNED_CODE else "EXCLUDED (other revision)"
            print(f"  sampler revision {h}: {n} rows  [{tag}]")

    rows = [r for r in rows_all if str(r.get("code")) == PINNED_CODE]
    decided = [r for r in rows if r.get("determined")]
    print(f"  eligible rows: {len(rows)} | decided: {len(decided)}")

    # ---- 2. structural census: is the determined side even buyable?
    print("\n--- 2. STRUCTURAL census on decided legs (the question that can kill the premise) ---")
    if decided:
        c = Counter(((r.get("q1") or {}).get("reason") or "missing") for r in decided)
        for k, v in c.most_common():
            print(f"  q1 reason {k:16}: {v:6}  ({100*v/len(decided):5.1f}%)")
        with_ask = [r for r in decided if (r.get("q1") or {}).get("ask") is not None]
        print(f"  determined side HAD an ask: {len(with_ask)}/{len(decided)} "
              f"({100*len(with_ask)/len(decided):.1f}%)")
        if not with_ask:
            print("  >>> PREMISE-LEVEL FINDING: no decided leg in the sample had a buyable ask on the")
            print("      determined side. The venue's book on a decided market is bid-only on the")
            print("      winner (observed: 20 bid levels <= 0.999, ZERO asks) with the loser offered")
            print("      at ~0.001. Nothing to price: the leg is unbuyable at ANY price, not at a bad")
            print("      price. That is a complete answer to Q1 as stated, and no statistic follows.")
    else:
        print("  no decided rows yet")

    # ---- 3. identities before any verdict
    print("\n--- 3. sanity identities (printed BEFORE the gate, by contract) ---")
    ids = sanity_identities(rows)
    if ids:
        for k, v in ids.items():
            print(f"  {k}: {v}")
    else:
        print("  not enough two-sided books in the sample to check the mirror identity")

    by_fam = defaultdict(list)
    for r in decided:
        by_fam[r.get("family")].append(r)

    # ---- 4. Q1 gate
    print("\n--- 4. Q1 GATE (determined legs) ---")
    for arm, sensitivity in (("canonical (market's own fee schedule)", False),
                             (f"sensitivity (every no_schedule_zero row charged {FEE_SENSITIVITY_RATE})", True)):
        st = q1_stats(decided, sensitivity)
        print(f"  [{arm}]")
        if not st:
            print("    no executable decided observations -> NO CLAIM")
            continue
        ci = ("n/a" if st["ci_low"] is None else f"{st['ci_low']:+.4f} .. {st['ci_high']:+.4f}")
        print(f"    n={st['n']} over {st['days']} UTC days | median edge {st['median']:+.4f} "
              f"| mean {st['mean']:+.4f} | day-clustered 95% CI {ci} | p10 {st['p10']:+.4f}")
        print(f"    excluded from this arm: {st['reasons']}")
    for fam, rs in sorted(by_fam.items()):
        st = q1_stats(rs)
        print(f"    family {fam}: decided {len(rs)} | " + ("no executable obs" if not st else
              f"n={st['n']} median {st['median']:+.4f} mean {st['mean']:+.4f}"))

    # ---- 5. decision curve
    print("\n--- 5. decision curve by minutes since determination (decay = latency artefact) ---")
    curve = decision_curve(decided)
    if curve:
        for b in curve:
            print(f"    {str(b['bucket_min'][0]):>3}-{str(b['bucket_min'][1]):<5} min: n={b['n']:5} "
                  f"median {b['median_edge']:+.4f} mean {b['mean_edge']:+.4f}")
    else:
        print("    no executable observations to bucket")

    # ---- floor / verdict
    st_d = q1_stats(decided)
    n = st_d["n"] if st_d else 0
    sub99 = sum(1 for r in decided if ((r.get("q1") or {}).get("ask") is not None
                                       and r["q1"]["ask"] < 0.99))
    days = len({str(r.get("ts", ""))[:10] for r in decided})
    print("\n--- FLOOR ---")
    print(f"  executable decided rows {n}/{FLOOR_ROWS_Q1} | UTC days {days}/{FLOOR_DAYS_Q1} "
          f"| ask<0.99 rows {sub99}/{FLOOR_SUB99}")
    if n < FLOOR_ROWS_Q1 or days < FLOOR_DAYS_Q1 or sub99 < FLOOR_SUB99:
        print("  VERDICT: INSUFFICIENT SAMPLE — no claim, as pre-registered. Shortfall above.")
    else:
        st_c, st_s = q1_stats(decided), q1_stats(decided, True)
        ok = (st_c and st_s and st_c["median"] > 0 and st_s["median"] > 0
              and (st_c["ci_low"] or -1) > 0 and (st_s["ci_low"] or -1) > 0)
        print(f"  VERDICT: {'PASS' if ok else 'NO CLAIM'} (canonical and sensitivity arms both "
              f"median > 0 and CI lower bound > 0: {bool(ok)})")

    # ---- 6. Q2
    print("\n--- 6. Q2 (undetermined ladders) ---")
    undet = [r for r in rows if r.get("determined") is False and r.get("family") == "hit_day"]
    print(f"  undetermined bracket rows recorded: {len(undet)}")
    print("  VERDICT: NO CLAIM — the estimator revision is not yet frozen/pinned in the")
    print("  pre-registration (section 6), so no Q2 row is analysis-eligible. Rows are recorded,")
    print("  not analysed: pre-estimator rows can never be scored.")

    if a.json:
        Path(a.json).write_text(json.dumps({"rows_total": len(rows_all), "eligible": len(rows),
                                            "decided": len(decided),
                                            "q1_canonical": q1_stats(decided),
                                            "q1_sensitivity": q1_stats(decided, True),
                                            "floor": {"n": n, "days": days, "sub99": sub99},
                                            "identities": ids, "curve": curve}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
