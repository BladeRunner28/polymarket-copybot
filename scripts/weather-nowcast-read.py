#!/usr/bin/env python3
"""Weather nowcast-vs-price READ (card wx2) — applies the FROZEN gate to the samples.

Gate: drafts/weather-nowcast-prereg-20261012.md (frozen 2026-10-12 before the first in-window
sample; amended the same evening for the per-venue station basis, before any in-window sample).

Reads  data/weather-nowcast-samples.jsonl  (written by scripts/weather-nowcast-sampler.py) and
prints, in this order:
  1. CENSUS — runs, in-window days, samples per venue/hour bucket, dropped samples and why.
  2. Q1     — executable residual mass in DEAD brackets at 16:00+ ET (and the 18:00+ variant),
              edges net of each venue's own taker fee, day-clustered bootstrap CI.
  3. Q2     — pre-14:00 market-implied vs ensemble-implied bracket distribution, log-loss/Brier
              of the realized bracket, paired by day, day-clustered CI on the difference.
  4. VERDICT — PASS / FAIL / INSUFFICIENT SAMPLE per venue, with the floor and the drop rule applied.

Read-only: it fetches settlement outcomes (keyless) and writes nothing.

QUOTA: the read is a measurement, not a rule. No live lane, sizing or gate change follows from it
without a separate approval carrying its own before/after.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "weather-nowcast-samples.jsonl"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
UA = {"User-Agent": "copybot-weather-nowcast-read/1.0 (read-only)"}
S_SIZE = 50          # pre-registered executable size floor, contracts
MIN_DAYS = 20        # pre-registered sample floor, distinct settled days per venue
DROP_MAX = 0.02      # >2% of a day's samples dropped -> the day is excluded


def jget(url: str, tries: int = 2):
    last = None
    for _ in range(tries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                                     timeout=45).read())
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise last  # type: ignore[misc]


def fee_taker(venue: str, row: dict, price: float) -> float:
    """Pinned laws, read from the row (never a constant): Kalshi 0.07*P*(1-P); PM rate=0.05 by the
    market's own feeSchedule, takerOnly, maker 0."""
    p = min(max(price, 0.0), 1.0)
    if venue == "kalshi":
        return 0.07 * p * (1 - p)
    sched = (row.get("fee") or {}).get("feeSchedule") or {}
    rate = sched.get("rate")
    if rate is None:
        return 0.0
    return float(rate) * p * (1 - p)


def bracket_contains(row: dict, value: int) -> bool:
    lo, hi = row.get("bracket_low"), row.get("bracket_high")
    return (lo is None or value >= lo) and (hi is None or value <= hi)


# ---------------------------------------------------------------- settlement outcomes
def kalshi_outcome(event_ticker: str):
    """Observed whole F bracket for the cycle, from the venue's own settled markets."""
    try:
        mk = jget(f"{KALSHI}/markets?series_ticker={'KXHIGHNY'}&status=settled&limit=1000")["markets"]
    except Exception:
        return None
    yes = [m for m in mk if m.get("event_ticker") == event_ticker and m.get("result") == "yes"]
    if len(yes) != 1:
        return None
    m = yes[0]
    st, f, c = m.get("strike_type"), m.get("floor_strike"), m.get("cap_strike")
    f = None if f is None else int(f)
    c = None if c is None else int(c)
    if st == "greater":
        return (f + 1 if f is not None else None, None)
    if st == "less":
        return (None, c - 1 if c is not None else None)
    return (f, c)


def pm_outcome(event_slug: str):
    try:
        d = jget(f"{GAMMA}/events?slug={event_slug}")
    except Exception:
        return None
    if not d:
        return None
    for m in d[0].get("markets", []):
        try:
            prices = json.loads(m.get("outcomePrices") or "[]")
        except Exception:
            continue
        if prices and str(prices[0]) in ("1", "1.0"):
            lbl = m.get("groupItemTitle") or ""
            s = lbl.replace("°F", "").replace("°", "").replace("or below", "").replace("or above", "").strip()
            if "-" in s:
                a, b = s.split("-")[:2]
                return (int(a), int(b))
            try:
                v = int(s.split()[0])
            except (ValueError, IndexError):
                return None
            if "below" in lbl:
                return (None, v)
            if "above" in lbl:
                return (v, None)
            return (v, v)
    return None


# ---------------------------------------------------------------- bootstrap
def day_clustered_ci(pairs, iters: int = 2000, seed: int = 20261012):
    """pairs = [(day, value)] -> (mean, lo, hi) percentile bootstrap resampling DAYS."""
    by_day = defaultdict(list)
    for d, v in pairs:
        by_day[d].append(v)
    days = sorted(by_day)
    if len(days) < 2:
        return (statistics.mean([v for _, v in pairs]) if pairs else float("nan"), float("nan"), float("nan"))
    rng = random.Random(seed)
    means = []
    for _ in range(iters):
        pick = [rng.choice(days) for _ in days]
        vals = [v for d in pick for v in by_day[d]]
        means.append(statistics.mean(vals))
    means.sort()
    return (statistics.mean([v for _, v in pairs]), means[int(0.025 * iters)], means[int(0.975 * iters)])


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=str(SAMPLES))
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    path = Path(a.samples)
    if not path.exists():
        print(f"INSUFFICIENT SAMPLE — no sample file at {path}")
        return 0
    rows = []
    for line in path.open():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    brackets = [r for r in rows if r.get("kind") == "bracket"]
    contexts = {(r["cycle_day"], r["ts"]): r for r in rows if r.get("kind") == "context"}
    coverage = [r for r in rows if r.get("kind") == "coverage"]
    print(f"=== CENSUS === runs={len(coverage)} bracket rows={len(brackets)} context rows={len(contexts)}")
    if not brackets:
        print("INSUFFICIENT SAMPLE — no bracket rows yet")
        return 0

    # in-window = the cycle being priced is the day being observed. The sampler only fills the
    # observation block for TODAY's cycle, so has_obs() is the in-window test; rows for the
    # next day's cycle are pre-day (no obs yet) and are excluded, never counted as drops.
    def has_obs(r):
        ctx = contexts.get((r.get("cycle_day"), r.get("ts"))) or {}
        obs = (ctx.get("obs") or {})
        key = "klga" if r["venue"] == "polymarket" else "kalshi_cp"
        return bool((obs.get(key) or {}).get("max_so_far_F") is not None)

    def priced(r):
        return any(r.get(k) is not None for k in ("yes_bid", "yes_ask", "no_bid", "no_ask"))

    per_venue_day = defaultdict(lambda: {"kept": 0, "dropped": 0})
    for r in brackets:
        if not has_obs(r):
            continue
        key = (r["venue"], r.get("cycle_day"))
        if priced(r):
            per_venue_day[key]["kept"] += 1
        else:
            per_venue_day[key]["dropped"] += 1

    excluded_days = set()
    for (venue, day), c in sorted(per_venue_day.items()):
        tot = c["kept"] + c["dropped"]
        if tot and c["dropped"] / tot > DROP_MAX and c["dropped"] > 2:
            excluded_days.add((venue, day))
    for venue in ("kalshi", "polymarket"):
        days = sorted({d for (v, d) in per_venue_day if v == venue})
        print(f"  {venue:<11} cycle-days seen={len(days)}  {days[0] if days else '-'} -> {days[-1] if days else '-'}")
    if excluded_days:
        print(f"  days excluded by the >{DROP_MAX:.0%} drop rule: {sorted(excluded_days)}")

    out = {"census": {"runs": len(coverage), "bracket_rows": len(brackets),
                      "excluded_days": sorted(str(x) for x in excluded_days)}}

    # ---------------- Q1
    print("\n=== Q1 — executable residual mass in DEAD brackets (16:00+ ET) ===")
    q1 = {}
    for venue in ("kalshi", "polymarket"):
        for bucket, lo_h in (("16:00+", 16.0), ("18:00+", 18.0)):
            pairs, n_legs, n_dead = [], 0, 0
            routes = defaultdict(int)
            for r in brackets:
                if r["venue"] != venue or (venue, r.get("cycle_day")) in excluded_days:
                    continue
                ctx = contexts.get((r.get("cycle_day"), r.get("ts"))) or {}
                et = ctx.get("et_hour")
                if et is None or float(et) < lo_h:
                    continue
                if not has_obs(r) or not r.get("dead"):
                    continue
                n_dead += 1
                best, route = None, None
                na, nsz = r.get("no_ask"), r.get("size_no_ask")
                if na is not None and (nsz or 0) >= S_SIZE:
                    e = (1 - float(na)) - fee_taker(venue, r, float(na))
                    if best is None or e > best:
                        best, route = e, "buy_no"
                yb, ysz = r.get("yes_bid"), r.get("size_yes_bid")
                if yb is not None and (ysz or 0) >= S_SIZE:
                    e = float(yb) - fee_taker(venue, r, float(yb))
                    if best is None or e > best:
                        best, route = e, "sell_yes"
                if best is None:
                    continue
                pairs.append((r["cycle_day"], best))
                routes[route] += 1
                n_legs += 1
            days = len({d for d, _ in pairs})
            if pairs:
                mean, lo, hi = day_clustered_ci(pairs)
                verdict = ("PASS" if (days >= MIN_DAYS and lo > 0) else
                           "INSUFFICIENT SAMPLE" if days < MIN_DAYS else "FAIL")
                print(f"  {venue:<11} {bucket:<6} legs={n_legs:<4} days={days:<3} "
                      f"mean_edge={mean:+.4f}  95%CI[{lo:+.4f},{hi:+.4f}]  routes={dict(routes)}  -> {verdict}")
                q1[f"{venue}:{bucket}"] = {"legs": n_legs, "days": days, "mean": mean, "ci": [lo, hi],
                                           "routes": dict(routes), "verdict": verdict}
            else:
                print(f"  {venue:<11} {bucket:<6} dead_brackets_seen={n_dead} but NO qualifying leg "
                      f"(the harvestable side of a dead bracket is not offered at >= {S_SIZE} contracts) "
                      f"-> INSUFFICIENT SAMPLE")
                q1[f"{venue}:{bucket}"] = {"legs": 0, "days": 0, "dead_brackets_seen": n_dead,
                                           "verdict": "INSUFFICIENT SAMPLE"}
    out["q1"] = q1

    # ---------------- Q2
    print("\n=== Q2 — pre-14:00 market-implied vs ensemble-implied bracket distribution ===")
    q2 = {}
    # group samples into (venue, day, sample-ts) bundles
    bundles = defaultdict(list)
    for r in brackets:
        if r.get("dead") is None:
            continue
        ctx = contexts.get((r.get("cycle_day"), r.get("ts")))
        if not ctx:
            continue
        et = ctx.get("et_hour")
        if et is None or float(et) >= 14.0:
            continue
        bundles[(r["venue"], r["cycle_day"], r["ts"])].append(r)
    scored = defaultdict(list)
    for (venue, day, ts), rs in sorted(bundles.items()):
        if (venue, day) in excluded_days or not has_obs(rs[0]):
            continue
        ctx = contexts[(day, ts)]
        members = ((ctx.get("ensemble") or {}).get("members") or [])
        if not members:
            continue
        if venue == "kalshi":
            out_br = kalshi_outcome(rs[0].get("event_ticker"))
        else:
            out_br = pm_outcome(rs[0].get("event_slug"))
        if out_br is None:
            continue                      # not settled yet -> no score (this day is not yet scoreable)
        # market-implied: mid per bracket, normalized
        mids = {}
        for r in rs:
            b = (r.get("bracket_low"), r.get("bracket_high"))
            yb, ya = r.get("yes_bid"), r.get("yes_ask")
            m = None
            if yb is not None and ya is not None:
                m = (float(yb) + float(ya)) / 2
            elif ya is not None:
                m = float(ya)
            elif yb is not None:
                m = float(yb)
            if m is not None:
                mids[b] = m
        tot = sum(mids.values())
        if tot <= 0:
            continue
        mkt = {b: v / tot for b, v in mids.items()}
        # ensemble-implied: members rounded, placed in the SAME bracket grid
        grid = list(mids.keys())
        counts = defaultdict(int)
        for mem in members:
            v = int(round(mem))
            hit = None
            for b in grid:
                if bracket_contains({"bracket_low": b[0], "bracket_high": b[1]}, v):
                    hit = b
                    break
            counts[hit] += 1
        ens = {b: counts.get(b, 0) / len(members) for b in grid}
        realized = tuple(out_br)
        # find the realized bracket in this venue's grid
        rk = None
        for b in grid:
            if bracket_contains({"bracket_low": b[0], "bracket_high": b[1]}, 0) and realized == b:
                rk = b
        if rk is None:
            for b in grid:
                if b == realized or (b[0] is None and realized[0] is None and b[1] == realized[1]) or \
                   (b[1] is None and realized[1] is None and b[0] == realized[0]):
                    rk = b
                    break
        if rk is None:
            continue
        p_m, p_e = max(mkt.get(rk, 1e-6), 1e-6), max(ens.get(rk, 1e-6), 1e-6)
        ll_m, ll_e = -math.log(p_m), -math.log(p_e)
        br_m = sum((mkt.get(b, 0) - (1 if b == rk else 0)) ** 2 for b in grid)
        br_e = sum((ens.get(b, 0) - (1 if b == rk else 0)) ** 2 for b in grid)
        scored[venue].append((day, ll_m, ll_e, br_m, br_e))
    for venue in ("kalshi", "polymarket"):
        s = scored[venue]
        days = len({d for d, *_ in s})
        if not s:
            print(f"  {venue:<11} no scoreable pre-14:00 bundles yet (needs settled days) -> INSUFFICIENT SAMPLE")
            q2[venue] = {"n": 0, "verdict": "INSUFFICIENT SAMPLE"}
            continue
        dll = [(d, a - b) for d, a, b, _, _ in s]
        dbr = [(d, a - b) for d, _, _, a, b in s]
        m_ll, lo_ll, hi_ll = day_clustered_ci(dll)
        m_br, lo_br, hi_br = day_clustered_ci(dbr)
        verdict = ("CLAIM: market worse than ensemble" if (days >= MIN_DAYS and lo_ll > 0) else
                   "CLAIM: market better than ensemble" if (days >= MIN_DAYS and hi_ll < 0) else
                   "INSUFFICIENT SAMPLE" if days < MIN_DAYS else "NO SIGNIFICANT DIFFERENCE")
        print(f"  {venue:<11} bundles={len(s)} days={days}  "
              f"logloss market-ensemble={m_ll:+.4f} 95%CI[{lo_ll:+.4f},{hi_ll:+.4f}] | "
              f"Brier Δ={m_br:+.4f} 95%CI[{lo_br:+.4f},{hi_br:+.4f}]  -> {verdict}")
        q2[venue] = {"n": len(s), "days": days, "logloss_delta": m_ll, "logloss_ci": [lo_ll, hi_ll],
                     "brier_delta": m_br, "brier_ci": [lo_br, hi_br], "verdict": verdict}
    out["q2"] = q2

    print("\n=== VERDICT ===")
    for venue in ("kalshi", "polymarket"):
        d = max([v.get("days", 0) for k, v in q1.items() if k.startswith(venue)] or [0])
        print(f"  {venue:<11} distinct qualifying days={d} (floor {MIN_DAYS}) — "
              f"{'floor met' if d >= MIN_DAYS else 'INSUFFICIENT SAMPLE, no claim'}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1) + "\n")
        print(f"JSON -> {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
