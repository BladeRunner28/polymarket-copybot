#!/usr/bin/env python3
"""Why did the tracked set's pooled band-excess move? Print-time vs settlement-completion split.

READ-ONLY. Built 2026-11-09 for kanban `t_7c91b4a1` (Lane A approval card of the wallet-FDR audit).

The audit measured the tracked SET pooled at +2.59pp over its own entry bands on 2026-10-29
(scripts/wallet-fdr-audit.py, truth cache 8,619 settled markets). Ten days later the same
instrument on the same cache lineage reads NEGATIVE on the same cohort. Two different things can
move that number and they mean opposite things:

  (1) SETTLEMENT COMPLETION -- markets the cohort printed before 2026-10-29 that had not resolved
      then are in today's join and were not in the parent's. That is survivorship on the JOIN, i.e.
      the old number was measured on a winner-skewed subset of its own bets. The cohort did not get
      worse; we started seeing the losses.
  (2) NEW PRINTS / REGIME -- bets the cohort printed AFTER 2026-10-29, carrying markets as they
      resolve. That is a forward read of the same cohort.

So the read is decomposed into three buckets, all scored with the SAME band baseline (the band
means are taken over the whole joined population once, so a bucket cannot be moved by re-meaning
its own bands):

  A  printed before the split, market END before the split   -> was measurable on the parent's run
  B  printed before the split, market END after the split    -> the completion effect (1)
  C  printed at/after the split                              -> the new-print read (2)

`--parent-truth PATH` (a snapshot of data/wallet-fdr-truth.json as it was at the parent's run)
sharpens bucket A/B: a bet whose conditionId was already SETTLED in that snapshot is bucket A
whatever its end date, and one that was not is bucket B. Without the flag the split is by the
market's own end date, which is a proxy (a market can end before it settles).

USAGE
  python3 scripts/wallet-fdr-cohort-split.py --split 2026-10-29
  python3 scripts/wallet-fdr-cohort-split.py --split 2026-10-29 \
      --parent-truth /tmp/truth-oct29.json --json data/wallet-fdr-cohort-split.json

REPRO: none of this writes to prisma/dev.db (opened mode=ro); the only output is --json.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import statistics
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_PATH = os.path.join(ROOT, "scripts", "wallet-fdr-audit.py")
SHADOW_PATH = os.path.join(ROOT, "scripts", "wallet-rank-shadow.py")
DEFAULT_SPLIT = "2026-10-29"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ms(iso):
    return int(time.mktime(time.strptime(iso[:10], "%Y-%m-%d")) * 1000)


def _read_cache(path):
    """{cid: rec} settled-only from one truth cache file (same shape as the audit's)."""
    if not path or not os.path.exists(path):
        return None
    d = json.load(open(path))
    return {k: v for k, v in (d.get("markets") or {}).items() if v and not v.get("unsettled")}


def bucket_of(bet, split_ms, parent_settled):
    if parent_settled is not None:
        measurable = bet["cid"] in parent_settled
    else:
        end = bet.get("end")
        measurable = bool(end) and _ms(end) <= split_ms
    if bet["ts"] < split_ms:
        return "A_parent_measurable" if measurable else "B_settled_after"
    return "C_printed_after"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default=DEFAULT_SPLIT, help="ISO date of the parent's run")
    ap.add_argument("--parent-truth", default=None,
                    help="snapshot of data/wallet-fdr-truth.json as of the parent's run")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    A = _load("wallet_fdr_audit", AUDIT_PATH)
    SH = _load("wallet_rank_shadow", SHADOW_PATH)
    SH.A = A                                        # cluster_read borrows the audit's t_sf
    split_ms = _ms(args.split)
    parent_settled = _read_cache(args.parent_truth)
    if args.parent_truth and parent_settled is None:
        raise SystemExit(f"parent truth cache not readable: {args.parent_truth}")

    import sqlite3
    c = sqlite3.connect("file:" + A.DB + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    cache, settled = A.load_truth()
    status = {r[0]: r[1] for r in c.execute("SELECT address, status FROM WalletProfile")}
    track = {w for w, s in status.items() if s == "track"}

    bets, stats = A.load_bets(c, cache)
    # per-market end date: taken off the truth record the audit already stores
    for b in bets:
        rec = cache.get(b["cid"]) or {}
        b["end"] = rec.get("end")
    A.band_excess(bets)                              # ONE baseline for every bucket
    print(f"population: {len(bets):,} first-print bets over {len({b['w'] for b in bets}):,} wallets "
          f"({len(settled):,} settled markets in the join)"
          + (f"; parent snapshot: {len(parent_settled):,} settled markets"
             if parent_settled is not None else "; split by market end date"))

    trk = [b for b in bets if b["w"] in track]
    buckets = collections.defaultdict(list)
    for b in trk:
        buckets[bucket_of(b, split_ms, parent_settled)].append(b)

    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "split_iso": args.split, "split_ms": split_ms,
           "parent_truth": args.parent_truth, "track_wallets": len(track),
           "join_settled_markets": len(settled),
           "parent_settled_markets": None if parent_settled is None else len(parent_settled),
           "buckets": {}}
    order = ["A_parent_measurable", "B_settled_after", "C_printed_after"]
    print(f"\ntracked set = {len(track)} wallets, {len(trk):,} bets in the join\n")
    hdr = f"{'bucket':22} {'bets':>6} {'mkts':>5} {'mean_pp':>8} {'t':>6} {'p_pos':>7} {'CI95':>20}"
    print(hdr)
    print("-" * len(hdr))
    for name in order:
        rows = buckets.get(name) or []
        r = SH.cluster_read(rows, reps=2000)
        raw = statistics.mean([b["edge"] for b in rows]) if rows else None
        out["buckets"][name] = {**r, "raw_mean": raw,
                               "window": {"first": min((b["ts"] for b in rows), default=None),
                                          "last": max((b["ts"] for b in rows), default=None)}}
        if r["mean"] is None:
            print(f"{name:22} {0:>6} {0:>5} {'--':>8}")
            continue
        ci = "" if r["ci_lo"] is None else f"[{r['ci_lo']:+.2f}, {r['ci_hi']:+.2f}]"
        print(f"{name:22} {r['bets']:>6} {r['markets']:>5} {r['mean']:>+8.2f} "
              f"{(r['t'] if r['t'] is not None else float('nan')):>6.2f} "
              f"{(r['p_pos'] if r['p_pos'] is not None else float('nan')):>7.3f} {ci:>20}")
        print(f"{'':22} raw edge (no band adjustment) {raw:+.2f}pp")
    if len(trk) > 1:
        tot = SH.cluster_read(trk, reps=2000)
        out["tracked_all"] = tot
        print(f"\ntracked set, every joined bet regardless of bucket: {tot['bets']:,} bets / "
              f"{tot['markets']:,} markets, mean {tot['mean']:+.2f}pp")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1)
        print(f"\n  json -> {os.path.relpath(args.json, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
