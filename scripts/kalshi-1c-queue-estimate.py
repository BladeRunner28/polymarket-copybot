#!/usr/bin/env python3
"""Kalshi 1c-tail QUEUE read: p(fill | print size, contracts ahead of us) from the forward capture.

INPUT  data/kalshi-1c-queue/{snaps-<date>.jsonl.gz, events-<date>.jsonl, coverage.jsonl}
OUTPUT stdout table + data/kalshi-1c-queue-read.json

THE QUESTION (card t_0cb77acd)
------------------------------
The pre-registered gate cell is "sell YES at 0.01 on KXBTCD", valued at +0.64c/contract because it
credits us on the first >=100-contract print at 1c. That credit assumes we are AT THE FRONT of the
queue. We are not: we join behind whatever size is already resting at the level. This script
measures how much size that is, and what fraction of the qualifying lifts a 100-lot late joiner
actually fills through.

WHAT IS MEASURED, AND HOW
-------------------------
Depth at 1c. Kalshi's YES ask at 1c is the binary complement of a resting NO bid at 99c, so
  book.yes_ask_size when book.yes_ask == 0.01   -> contracts resting at the level (the queue)
  book.yes_ask > 0.01                           -> the 1c level is EMPTY (0 contracts ahead)
Both cases are read straight off the per-cycle snapshot; nothing is inferred.

Bursts. Qualifying prints are grouped into bursts (same ticker, consecutive prints <= --burst-gap
seconds apart) because a taker sweeping a level emits several prints and the queue only cares about
the total consumed. For a burst with lift volume L and depth D ahead of us at the prior snapshot, a
100-contract order that joined at that snapshot fills iff L >= D + 100.

TWO BOUNDS, BOTH REPORTED, NEITHER PRESENTED AS A POINT ESTIMATE
  LOWER (conservative): D = D_pre (every contract resting at the prior snapshot is still ahead of
     us at burst time). Kalshi publishes ONE aggregate size per level, so a cancel ahead of us is
     indistinguishable from a fill -- assuming zero cancels is the pessimistic end.
  UPPER: depth at burst time <= min(D_pre, D_post + L)  (the level after the burst is what survives
     of the pre-burst queue plus new joins, so depth_at_burst <= D_post + L). Caps how much of the
     pre-burst depth can have been cancelled away by the time the taker arrived.
A fill that clears the LOWER bound is a fill under any assumption; a fill that only clears the
UPPER bound is a fill only if pushes/cancels ahead of us happened first. The truth is in between
and only a multi-day capture narrows it.

CARRY. The edge itself is not re-derived here: EV/contract = +0.64c and the adverse-fill rate
(0.36%) are the pre-registered read's, taken as given. What this script adds is the FILL side:
EV per resting contract = 0.64c * p(fill), per 100-lot resting hour = EV/contract * 100 *
(fills per resting hour).

Python 3.9 compatible.
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "kalshi-1c-queue"
CELL = "0.0100"
EV_PER_CONTRACT = 0.0064          # pre-registered gate cell, dollars per contract
ADVERSE_RATE = 0.0036             # pre-registered, share of fills that settle against us at -99c
ORDER = 100.0                     # the order size the decision rule names
_TS_RE_CACHE = {}


def parse_ts(s):
    import re
    global _TS_RE_CACHE
    if "re" not in _TS_RE_CACHE:
        _TS_RE_CACHE["re"] = re.compile(
            r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})?$")
    m = _TS_RE_CACHE["re"].match(s.strip())
    if not m:
        raise ValueError("bad ts %r" % (s,))
    d, c, f, off = m.groups()
    f = ((f or "") + "000000")[:6]
    off = "+00:00" if off in (None, "Z") else off
    return datetime.fromisoformat("%sT%s.%s%s" % (d, c, f, off)).timestamp()


def depth_at_1c(level):
    """level = [ask_px, ask_sz, bid_px, bid_sz] -> contracts resting at the 1c YES ask."""
    if not level:
        return None
    px, sz = level[0], level[1]
    if px == CELL:
        try:
            return float(sz)
        except (TypeError, ValueError):
            return None
    if px is None:
        return None
    return 0.0  # best ask above 1c => nothing resting at 1c


def wilson(k, n, z=1.959963985):
    if n == 0:
        return (None, None, None)
    p = k / n
    d = 1.0 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (p, (c - r) / d, (c + r) / d)


def q(vals, p):
    if not vals:
        return None
    v = sorted(vals)
    i = min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))
    return v[i]


def load(data_dir):
    snaps = []
    for fp in sorted(glob.glob(str(data_dir / "snaps-*.jsonl.gz"))):
        with gzip.open(fp, "rt") as fh:
            for line in fh:
                try:
                    snaps.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # a torn last line from an in-flight append
    snaps.sort(key=lambda r: r["ts"])

    meta = {}
    for fp in sorted(glob.glob(str(data_dir / "markets-*.jsonl"))):
        for line in open(fp):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            for tk, mv in row.get("m", {}).items():
                prev = meta.get(tk)
                # a later row can be RICHER (open_time was added after the first capture run);
                # keep the most complete record rather than the first one seen.
                if prev is None or ("open_time" in mv and "open_time" not in prev):
                    meta[tk] = mv

    events = []
    seen_ids = set()
    for fp in sorted(glob.glob(str(data_dir / "events-*.jsonl"))):
        with open(fp) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tid = e.get("trade_id")
                if tid is not None:
                    if tid in seen_ids:
                        continue  # a restart re-reads the tape page; one row per trade, always
                    seen_ids.add(tid)
                events.append(e)
    events.sort(key=lambda r: r["event_ts"])

    coverage = []
    cov_fp = data_dir / "coverage.jsonl"
    if cov_fp.exists():
        for line in open(cov_fp):
            line = line.strip()
            if line:
                try:
                    coverage.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return snaps, events, coverage, meta


def build_series(snaps):
    """ticker -> [(ts_epoch, depth_at_1c, bid_px, bid_sz)] sorted, plus the last book per ticker."""
    series = defaultdict(list)
    lastbook = {}
    for s in snaps:
        t = parse_ts(s["ts"])
        for tk, lv in s["m"].items():
            d = depth_at_1c(lv)
            if d is None:
                continue
            series[tk].append((t, d, lv[2] if len(lv) > 2 else None, lv[3] if len(lv) > 3 else None))
            lastbook[tk] = lv
    for tk in series:
        series[tk].sort()
    return series, lastbook


def depth_before(series, tk, ts):
    """Last observation at or before ts -> ((depth, bid_px, bid_sz), age_seconds) or (None, None)."""
    obs = series.get(tk)
    if not obs:
        return None, None
    lo, hi = 0, len(obs) - 1
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if obs[mid][0] <= ts:
            best = obs[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        return None, None
    return best[1:], ts - best[0]


def level_after(series, tk, ts):
    """First observation strictly after ts -> (depth, bid_px, bid_sz) or None."""
    obs = series.get(tk)
    if not obs:
        return None
    for t, d, bpx, bsz in obs:
        if t > ts:
            return (d, bpx, bsz)
    return None


def depth_after(series, tk, ts):
    la = level_after(series, tk, ts)
    return la[0] if la else None


def bursts_of(events, gap):
    per = defaultdict(list)
    for e in events:
        per[e["ticker"]].append(e)
    out = []
    for tk, evs in per.items():
        evs.sort(key=lambda r: r["event_ts"])
        cur = []
        last = None
        for e in evs:
            t = parse_ts(e["event_ts"])
            if last is not None and t - last > gap:
                out.append((tk, cur))
                cur = []
            cur.append((t, e))
            last = t
        if cur:
            out.append((tk, cur))
    out.sort(key=lambda x: x[1][0][0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--burst-gap", type=float, default=2.0)
    ap.add_argument("--order", type=float, default=ORDER)
    ap.add_argument("--out", default=str(DATA / "kalshi-1c-queue-read.json"))
    args = ap.parse_args()

    data_dir = Path(args.data)
    snaps, events, coverage, meta = load(data_dir)
    if not events:
        print("no events in %s -- run scripts/kalshi-1c-queue-capture.py first" % data_dir)
        return 1
    series, lastbook = build_series(snaps)

    span = parse_ts(snaps[-1]["ts"]) - parse_ts(snaps[0]["ts"]) if len(snaps) > 1 else 0.0
    print("=" * 78)
    print("COVERAGE (quote every figure below with this)")
    print("=" * 78)
    print("snapshot cycles: %d   span: %.1f min (%.2f h)   tickers seen: %d"
          % (len(snaps), span / 60.0, span / 3600.0, len(series)))
    if coverage:
        c = coverage[-1]
        print("last run: %s -> %s  cycles=%s requests=%s errors=%s interval=%.1fs"
              % (c.get("run_started"), c.get("run_ended"), c.get("cycles"),
                 c.get("requests"), c.get("request_errors"), c.get("interval_s") or -1))
    else:
        print("last run: (no coverage row yet -- run still in flight)")
    print("1c lift prints recorded: %d over %d tickers   >=100-contract prints: %d"
          % (len(events), len({e["ticker"] for e in events}),
             sum(1 for e in events if e["contracts"] >= 100)))

    # ---------- 1. resting size at the 1c level, market-time weighted ----------
    print()
    print("=" * 78)
    print("1. HOW DEEP IS THE 1c LEVEL? (every snapshot observation, all open KXBTCD strikes)")
    print("=" * 78)
    grid = []
    states = {"queue": 0, "absent": 0, "cross": 0}
    for s in snaps:
        for tk, lv in s["m"].items():
            d = depth_at_1c(lv)
            if d is None:
                continue
            grid.append(d)
            if d > 0:
                states["queue"] += 1
            elif len(lv) > 2 and lv[2] == CELL:
                states["cross"] += 1
            else:
                states["absent"] += 1
    nz = [d for d in grid if d > 0]
    print("observations: %d   at 1c: %d (%.1f%%)   empty 1c level: %d (%.1f%%)"
          % (len(grid), len(nz), 100.0 * len(nz) / max(1, len(grid)),
             len(grid) - len(nz), 100.0 * (len(grid) - len(nz)) / max(1, len(grid))))
    tot_states = max(1, sum(states.values()))
    print("  of which: YES asks resting (we QUEUE) %.1f%% | level absent (we would be ALONE) %.1f%%"
          " | YES bid resting (we CROSS and fill) %.1f%%"
          % (100.0 * states["queue"] / tot_states, 100.0 * states["absent"] / tot_states,
             100.0 * states["cross"] / tot_states))
    if nz:
        print("contracts resting at 1c when non-empty: p10=%.0f p25=%.0f median=%.0f p75=%.0f p90=%.0f max=%.0f"
              % (q(nz, .10), q(nz, .25), q(nz, .50), q(nz, .75), q(nz, .90), q(nz, 1.0)))
    for thr in (100, 1000, 5000, 20000):
        print("  share of non-empty observations with depth <= %6d: %5.1f%%"
              % (thr, 100.0 * sum(1 for d in nz if d <= thr) / max(1, len(nz))))

    # ---------- 2. bursts and the fill test ----------
    print()
    print("=" * 78)
    print("2. FILL TEST -- a %d-contract order joining at the prior snapshot" % args.order)
    print("=" * 78)
    rows = []
    for tk, burst in bursts_of(events, args.burst_gap):
        t0 = burst[0][0]
        lift = sum(e["contracts"] for _, e in burst)
        biggest = max(e["contracts"] for _, e in burst)
        pre_row, age = depth_before(series, tk, t0)
        if pre_row is None:
            continue
        pre, bid_px, bid_sz = pre_row
        post = depth_after(series, tk, parse_ts(burst[-1][1]["event_ts"]))
        post_book = None
        for _, e in burst:
            if e.get("post") and "yes_ask_1c" in e["post"]:
                post_book = e["post"]["yes_ask_1c"]
                break
        # fresh (orderbook-endpoint) size of the 1c YES bid right after the burst, when captured:
        # the markets list can lag a tick, so prefer the per-market book for the capacity question
        bid_after_fresh = None
        for _, e in burst:
            pb = e.get("post") or {}
            if "yes_bid_1c" in pb:
                try:
                    bid_after_fresh = float(pb["yes_bid_1c"])
                except (TypeError, ValueError):
                    bid_after_fresh = None
                break
        d_post = post_book if post_book is not None else post
        lb_depth = pre
        ub_depth = pre if d_post is None else min(pre, d_post + lift)
        # which channel is the 1c level in at the prior snapshot?
        #   cross : a YES BID rests at 1c -> our sell-yes-at-1c CROSSES it, fills on arrival,
        #           capped by that bid's size (the print itself is somebody else hitting it)
        #   queue : YES ASKS rest at 1c -> we join behind them, need lift >= depth + order
        #   alone : no 1c order either side -> we are the only resting seller, any 1c buyer hits us
        try:
            bid_sz_f = float(bid_sz) if bid_sz not in (None, "") else 0.0
        except (TypeError, ValueError):
            bid_sz_f = 0.0
        if bid_px == CELL:
            state = "cross"
            fill_lower = fill_upper = bid_sz_f >= args.order
        elif lb_depth > 0:
            state = "queue"
            fill_lower = lift >= lb_depth + args.order
            fill_upper = lift >= ub_depth + args.order
        else:
            state = "alone"
            fill_lower = fill_upper = lift >= args.order
        ct = (meta.get(tk) or {}).get("close_time")
        mtc = None
        if ct:
            try:
                mtc = (parse_ts(ct) - t0) / 60.0
            except ValueError:
                mtc = None
        # CROSS-CHANNEL CAPACITY CHECK. A displayed 1c YES bid is only real capacity if it
        # DECREMENTS when hit. Compare the displayed size before and after the burst: a level
        # that refills to the identical size every time is a quote we cannot count on, and the
        # "fills on arrival" claim would be an upper bound rather than a measurement.
        bid_after = None
        la = level_after(series, tk, parse_ts(burst[-1][1]["event_ts"]))
        if la is not None and la[1] == CELL:
            try:
                bid_after = float(la[2])
            except (TypeError, ValueError):
                bid_after = None
        row_bid_drop = None
        if bid_after is not None and bid_sz_f:
            row_bid_drop = bid_sz_f - bid_after
        row_bid_drop_fresh = None
        if bid_after_fresh is not None and bid_sz_f:
            row_bid_drop_fresh = bid_sz_f - bid_after_fresh
        rows.append({
            "ticker": tk,
            "burst_ts": burst[0][1]["event_ts"],
            "burst_end": burst[-1][1]["event_ts"],
            "prints": len(burst),
            "lift": lift,
            "biggest_print": biggest,
            "state": state,
            "bid_size_1c": bid_sz_f,
            "bid_size_1c_after": bid_after,
            "bid_size_1c_after_fresh": bid_after_fresh,
            "bid_drop_after": row_bid_drop,
            "bid_drop_after_fresh": row_bid_drop_fresh,
            "depth_pre": lb_depth,
            "depth_post": d_post,
            "minutes_to_close": mtc,
            "strike": (meta.get(tk) or {}).get("strike"),
            "snap_age_s": age,
            "fill_lower": fill_lower,
            "fill_upper": fill_upper,
            "qualifying": biggest >= 100.0,
        })
    print("bursts evaluated: %d   (qualifying, biggest print >=100: %d)"
          % (len(rows), sum(1 for r in rows if r["qualifying"])))
    ages = [r["snap_age_s"] for r in rows]
    print("snapshot age at burst start: p50=%.2fs p90=%.2fs max=%.2fs"
          % (q(ages, .5), q(ages, .9), q(ages, 1.0)))

    def table(rs, label):
        if not rs:
            return
        k_lo = sum(1 for r in rs if r["fill_lower"])
        k_hi = sum(1 for r in rs if r["fill_upper"])
        p_lo, lo_lo, hi_lo = wilson(k_lo, len(rs))
        p_hi, lo_hi, hi_hi = wilson(k_hi, len(rs))
        print("  %-34s n=%4d  fill(LOWER) %5.1f%% [%.1f,%.1f]   fill(UPPER) %5.1f%% [%.1f,%.1f]"
              % (label, len(rs), 100 * p_lo, 100 * lo_lo, 100 * hi_lo,
                 100 * p_hi, 100 * lo_hi, 100 * hi_hi))

    print()
    print("  p(fill | depth ahead, lift size) -- decision rule needs LOWER >= 25%:")
    buckets = [(0.0, 0.0, "depth 0 (we are first)"), (0.0, 100.0, "depth 1-100"),
               (100.0, 1000.0, "depth 100-1000"), (1000.0, 5000.0, "depth 1000-5000"),
               (5000.0, 1e18, "depth >5000")]
    qual = [r for r in rows if r["qualifying"]]
    for lo, hi, label in buckets:
        sel = [r for r in qual if (r["depth_pre"] == 0.0 if (lo == 0 and hi == 0)
                                   else lo < r["depth_pre"] <= hi)]
        table(sel, label)
    print()
    print("  ALL qualifying bursts:")
    table(qual, "all, biggest print >=100")
    print()
    print("  SENSITIVITY -- same test at a looser print threshold (the card fixes 100; this shows")
    print("  whether the answer is an artifact of that cut):")
    for thr in (100, 50, 30, 1):
        sel = [r for r in rows if r["biggest_print"] >= thr]
        table(sel, "biggest print >= %d" % thr)
    print()
    print("  lift-size split (qualifying):")
    for lo, hi in ((100, 500), (500, 2000), (2000, 1e18)):
        table([r for r in qual if lo <= r["lift"] < hi], "lift %d-%s" % (lo, "inf" if hi > 1e17 else int(hi)))

    print()
    print("  CHANNEL split (qualifying) -- which side of the 1c level held the resting order:")
    for st, label in (("cross", "cross: 1c YES bid rested (fill on arrival)"),
                      ("queue", "queue: 1c YES asks rested (fill needs the sweep)")):
        table([r for r in qual if r["state"] == st], label)
    print("  (channel states over ALL qualifying bursts: cross=%d queue=%d alone=%d)"
          % (sum(1 for r in qual if r["state"] == "cross"),
             sum(1 for r in qual if r["state"] == "queue"),
             sum(1 for r in qual if r["state"] == "alone")))

    cross_known = [r for r in qual if r["state"] == "cross" and r["bid_drop_after"] is not None]
    cross_fresh = [r for r in qual if r["state"] == "cross" and r["bid_drop_after_fresh"] is not None]
    print()
    print("  CROSS-channel capacity check -- does the displayed 1c bid actually decrement when hit?")
    if cross_known:
        unch = sum(1 for r in cross_known if r["bid_drop_after"] <= 0.0)
        part = sum(1 for r in cross_known if 0.0 < r["bid_drop_after"] < r["lift"])
        full = sum(1 for r in cross_known if r["bid_drop_after"] >= r["lift"])
        print("    markets-list before vs after (n=%d): unchanged %d, shrank < lift %d, shrank >= lift %d"
              % (len(cross_known), unch, part, full))
    if cross_fresh:
        unch_f = sum(1 for r in cross_fresh if r["bid_drop_after_fresh"] <= 0.0)
        gone = sum(1 for r in cross_fresh if (r["bid_size_1c_after_fresh"] or 0.0) == 0.0)
        print("    FRESH orderbook 0.3s after the print (n=%d): 1c bid unchanged %d, gone entirely %d"
              % (len(cross_fresh), unch_f, gone))
        print("      -> a 1c bid that is still displayed after the print is capacity a crossing sell")
        print("         can count on; one that is gone was already consumed. Neither proves the")
        print("         fill SIZE at sub-second resolution.")
    if not cross_known and not cross_fresh:
        print("    no cross-channel burst has both a before and an after observation yet")

    print()
    print("  minutes-to-close split (qualifying) -- the pre-registered adverse fills were 1-4 min out:")
    mtc_known = [r for r in qual if r["minutes_to_close"] is not None]
    print("  (minutes-to-close known for %d of %d qualifying bursts)" % (len(mtc_known), len(qual)))
    for lo, hi, label in ((0, 5, "<=5 min to close"), (5, 30, "5-30 min"),
                          (30, 120, "30-120 min"), (120, 1e9, ">120 min")):
        table([r for r in mtc_known if lo <= r["minutes_to_close"] < hi], label)

    # ---------- 3. economic translation ----------
    print()
    print("=" * 78)
    print("3. WHAT IT IS WORTH (0.64c/contract is taken from the pre-registered read, not re-derived)")
    print("=" * 78)
    p_lo = sum(1 for r in qual if r["fill_lower"]) / len(qual) if qual else 0.0
    p_hi = sum(1 for r in qual if r["fill_upper"]) / len(qual) if qual else 0.0
    hours = span / 3600.0
    qual_per_h = len(qual) / hours if hours else 0
    strikes_per_cycle = q([len(s["m"]) for s in snaps], .5) or 0
    per_strike_h = (qual_per_h / strikes_per_cycle) if strikes_per_cycle else 0
    ev_per_fill_c = EV_PER_CONTRACT * args.order * 100.0          # cents, per 100-lot that fills
    print("qualifying bursts per hour, family-wide (all open strikes): %.1f" % qual_per_h)
    print("open strikes per snapshot (median): %s  ->  %.3f qualifying bursts per strike-hour"
          % (strikes_per_cycle, per_strike_h))
    print("one 100-lot fill is worth 0.64c x 100 = %.0fc, and one order takes ONE fill per contract" % ev_per_fill_c)
    for name, p in (("LOWER", p_lo), ("UPPER", p_hi)):
        ev_burst = ev_per_fill_c * p
        print("  %s: p(fill|burst)=%.3f -> %.1fc per qualifying burst, %.2fc per strike-hour of resting"
              % (name, p, ev_burst, ev_burst * per_strike_h))
    collateral = (1.0 - float(CELL)) * args.order                  # $0.99 per contract x order size
    fills_h_capped = 10 * per_strike_h * p_lo                      # ~10 concurrent 100-lots in $990
    print("\ncapital: a 100-lot short YES at 1c holds %.0fc x 100 = $%.0f of collateral."
          % ((1.0 - float(CELL)) * 100.0, collateral))
    print("  at the lane's $1,000 base exposure cap that is ~10 resting 100-lots, so the family")
    print("  would see ~%.2f fills/hour -> $%.2f/hour gross before the adverse tail, which is"
          % (fills_h_capped, fills_h_capped * ev_per_fill_c / 100.0))
    print("  %.1f%%/day gross on $990 and NOT a claim this card makes: throughput is Lane A's call."
          % (fills_h_capped * 24 * ev_per_fill_c / 100.0 / 990.0 * 100.0))
    print("\nadverse-fill share assumed %.2f%% (pre-registered): -99c on %.2f%% of fills is already"
          % (ADVERSE_RATE * 100, ADVERSE_RATE * 100))
    print("inside the +0.64c; it is NOT double-counted here.")
    print("CAVEAT: burst arrival is strongly non-stationary (it clusters in the last minutes before")
    print("        each hourly close), so a flat bursts/hour EXTRAPOLATES an activity-weighted window")
    print("        to a full hour. See the minutes-to-close split above before sizing on this row.")

    # ---------- 4. market-level survival (right-censored, flagged) ----------
    print()
    print("=" * 78)
    print("4. WHOLE-MARKET VIEW (right-censored: the capture sees only part of each market's life)")
    print("=" * 78)
    ev_by_tk = defaultdict(list)
    for e in events:
        ev_by_tk[e["ticker"]].append((parse_ts(e["event_ts"]), e["contracts"]))
    filled_lo = filled_hi = observed = 0
    win_hours = []
    full_life = 0
    win_ok = []
    for tk, obs in series.items():
        if not obs:
            continue
        observed += 1
        t_join = obs[0][0]
        d_join = obs[0][1]
        span_h = (obs[-1][0] - t_join) / 3600.0
        win_hours.append(span_h)
        # only markets whose observation covers most of their life can answer the whole-life
        # question; the rest are right-censored and stay out of the headline
        mv = meta.get(tk) or {}
        life = None
        if mv.get("open_time") and mv.get("close_time"):
            try:
                life = (parse_ts(mv["close_time"]) - parse_ts(mv["open_time"])) / 3600.0
            except ValueError:
                life = None
        if life is None or life <= 0 or span_h < 0.8 * life:
            continue
        full_life += 1
        win_ok.append(span_h)
        cum = 0.0
        ok_lo = ok_hi = False
        for t, c in sorted(ev_by_tk.get(tk, [])):
            if t < t_join:
                continue
            before = depth_before(series, tk, t)[0]
            cum += c
            # LOWER: the queue we joined behind still stands in front of us
            if cum >= d_join + args.order:
                ok_lo = True
            # UPPER: depth at each moment can be at most min(d_join, observed depth)
            d_burst = d_join if before is None else min(d_join, before[0])
            if cum >= d_burst + args.order:
                ok_hi = True
        filled_lo += ok_lo
        filled_hi += ok_hi
    observed = full_life
    if observed:
        p_lo, lo_lo, hi_lo = wilson(filled_lo, observed)
        p_hi, lo_hi, hi_hi = wilson(filled_hi, observed)
        print("markets observed for >=80%% of their life: %d   median window: %.0f min"
              % (observed, 60.0 * (q(win_ok, .5) or 0.0)))
        print("  100-lot joined at first sight, filled by cumulative 1c lift: LOWER %d (%.1f%% "
              "[%.1f,%.1f])   UPPER %d (%.1f%% [%.1f,%.1f])"
              % (filled_lo, 100 * p_lo, 100 * lo_lo, 100 * hi_lo,
                 filled_hi, 100 * p_hi, 100 * lo_hi, 100 * hi_hi))
    else:
        print("no market was observed for >=80%% of its life in this window (median observed "
              "span %.0f min) -- the whole-life fill rate needs a capture that spans a close"
              % (60.0 * (q(win_hours, .5) or 0)))
    print("NOTE: only markets seen across most of their life count here; a partially observed")
    print("      market can only under-count lifts, so it is excluded rather than reported low.")

    out = {
        "generated_from": str(data_dir),
        "span_hours": round(hours, 3),
        "snapshot_cycles": len(snaps),
        "events": len(events),
        "qualifying_prints": sum(1 for e in events if e["contracts"] >= 100),
        "bursts": len(rows),
        "qualifying_bursts": len(qual),
        "depth_grid": {
            "observations": len(grid),
            "nonempty_at_1c": len(nz),
            "median_nonempty": q(nz, .5),
            "p90_nonempty": q(nz, .90),
        },
        "fill_lower_all": wilson(sum(1 for r in rows if r["fill_lower"]), len(rows)),
        "fill_upper_all": wilson(sum(1 for r in rows if r["fill_upper"]), len(rows)),
        "fill_lower_qualifying": wilson(sum(1 for r in qual if r["fill_lower"]), len(qual)),
        "fill_upper_qualifying": wilson(sum(1 for r in qual if r["fill_upper"]), len(qual)),
        "by_channel_qualifying": {
            st: {
                "n": len([r for r in qual if r["state"] == st]),
                "fill_lower": wilson(sum(1 for r in qual if r["state"] == st and r["fill_lower"]),
                                     len([r for r in qual if r["state"] == st])),
            }
            for st in ("cross", "queue", "alone")
        },
        "by_depth_qualifying": {
            label: {
                "n": len(sel),
                "fill_lower": wilson(sum(1 for r in sel if r["fill_lower"]), len(sel)),
                "fill_upper": wilson(sum(1 for r in sel if r["fill_upper"]), len(sel)),
            }
            for (lo, hi, label), sel in [
                (b, [r for r in qual if (r["depth_pre"] == 0.0 if (b[0] == 0 and b[1] == 0)
                                         else b[0] < r["depth_pre"] <= b[1])])
                for b in buckets]
        },
        "assumptions": {
            "ev_per_contract": EV_PER_CONTRACT,
            "adverse_rate": ADVERSE_RATE,
            "order_size": args.order,
            "burst_gap_s": args.burst_gap,
            "edge_source": "pre-registered gate cell, taken as given (not re-derived)",
        },
        "burst_rows": rows,
    }
    Path(args.out).write_text(json.dumps(out, indent=1))
    print("\nwrote ->", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
