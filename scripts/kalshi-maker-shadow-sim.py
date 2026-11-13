#!/usr/bin/env python3
"""kalshi-maker-shadow-sim.py -- would-be RESTING-ORDER fill simulation, net of adverse selection.

CARD: kalshi-maker-read-prereg (Lane A, proposal only).  This file is the offline instrument for
the arm the 2026-11-11 read proposed in its section (a), quoted verbatim from the card note:

    "a KALSHI MAKER SHADOW ARM, paper only. On every KXBTCD print at yes_price p, record a would-be
     resting NO bid at (1-p) - $0.01 for 100 contracts, 60s lifetime; when a later print fills it at
     that price, book the leg at the resting price with maker fee $0 and mark it to the venue's
     result."

WHY THIS IS NOT THE READ AGAIN
------------------------------
scripts/kalshi-maker-read.py answers "if we had been resting AT level p, what did the fills at p
pay?" -- every qualifying print is credited once, at its own price, with no queue, no lifetime and
no one-tick improvement.  That is a per-price PROFILE: it cannot lose a fill for arriving late and
it cannot charge the maker the tick he must give away to be queue-ahead of the print.

This instrument imposes the three things the profile cannot express, in the order they hurt:
  1. the order only exists for LIFETIME_S after its trigger print, and is consumed by its FIRST
     qualifying print (an unfilled order is a real outcome, not a dropped row);
  2. one live order per (ticker, price) -- a stream of prints at the same level does not stack
     orders, so the fill count is orders, not prints;
  3. the fill must be a LATER print at OUR resting price, i.e. the market has to come to us.

CONSTANTS FIXED BEFORE THE RUN (nothing below is tuned to the result)
--------------------------------------------------------------------
S1 OUR_SIZE    = 100 contracts (the tape's own verbatim-print floor; the card's (a) size).
S2 LIFETIME_S  = 60 s (the card's (a) constant, verbatim).
S3 TRIGGER     = every qualifying print in the family at yes_price p, regardless of taker side
                 (the card's (a) wording).  Target = yes price p + $0.01, i.e. a resting NO bid at
                 (1-p) - $0.01.  Trigger prices above 0.99 or at/below 0.01 emit no order.
S4 FILL (primary arm)  = a later print on the SAME ticker with taker_side='yes' (a taker BUY took
                 NO off us) at yes_price == OUR target, ts <= trigger + 60 s.  A print BELOW our
                 resting price is NOT a fill (the card's own measured error: 390 vs 2).
S5 FILL (sweep arm)    = same, but any print at yes_price >= our target fills us AT our target
                 (a taker sweeping several levels takes every resting bid it crosses).  Reported
                 as a SENSITIVITY only; it is not the pre-registered rule.
S5b FILL (one-level arm) = same, but a print that gaps through our price takes ONE order -- the
                 best-priced level it crossed -- and nothing deeper.  A resting order cannot
                 decline a print that crosses it, so this is the conservative version of the
                 realistic fill set, and it is the arm's central estimate.
S6 FILL (control arm)  = the same 60 s / one-live-order machinery, resting at the trigger print's
                 OWN implied NO price (1-p), filled by a later print at p.  This is the arm the
                 read's profile approximates; the gap between it and S4 is the 1-cent queue price.
S7 CREDIT      = min(1, OUR_SIZE / print_contracts) x OUR_SIZE, at OUR resting price; maker fee $0
                 (standard series, published schedule effective 2026-07-07).
S8 MARK        = the venue's own `result` from keyless /markets?status=settled.  Unsettled is
                 recorded as unsettled, never guessed and never marked.
S9 CI          = cluster bootstrap over TICKER blocks (2,000 resamples, seed 20261112, percentile).
                 Prints inside one market share one settlement, so the ticker is the unit.
S10 DECISION   = the card's rule, fixed 2026-10-12 before any data: graduate only if >=2,000 filled
                 legs AND fill-weighted EV > 0 with a 95% ticker-clustered CI excluding zero AND
                 >=60% of filled tickers positive.  Otherwise the lane CLOSES.

LIMITS (travel with every number)
---------------------------------
L1 PRINT FLOOR: the tape keeps only prints >=100 contracts, so this is a LARGE-PRINT fill model.
L2 NO BOOK: no queue position, no partial fills, no cancels, no competitor at our level.  The
   credit rule is the card's, and the unfiltered fill count is printed beside it.
L3 DUTY CYCLE: coverage.jsonl is the clock authority (~82% duty); a hole can only LOSE fills here,
   never create one, so the fill COUNT is a lower bound -- the EV is not, and neither is sorted.
L4 ONE-SIDED: only the NO side is simulated, because the card's (a) names the NO side.  The YES
   mirror of the same rule is the read's YES arm and is not re-derived here.
L5 NO EXECUTION: no Kalshi API key exists on this box.  This is paper by construction.

USAGE
  python3 scripts/kalshi-maker-shadow-sim.py --self-test          # detector proof, exits 1 on RED
  python3 scripts/kalshi-maker-shadow-sim.py --limit-print-files 5  # smoke
  python3 scripts/kalshi-maker-shadow-sim.py                       # full read, writes the artifact
"""

from __future__ import annotations

import argparse
import glob
import gzip
import heapq
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAPE = os.path.join(ROOT, "data", "kalshi-tape")
PRINTS_GLOB = os.path.join(TAPE, "prints-*.jsonl.gz")
COVERAGE = os.path.join(TAPE, "coverage.jsonl")
ARTIFACT = os.path.join(ROOT, "data", "kalshi-maker-shadow-sim.json")
SETTLE_SHARED = os.path.join(ROOT, "data", "kalshi-maker-settlements.json")
SETTLE_OWN = os.path.join(ROOT, "data", "kalshi-maker-shadow-settlements.json")

# ---- fixed before the run (S1..S10)
OUR_SIZE = 100.0
LIFETIME_S = 60.0
TICK = 0.01
BOOT_N = 2000
BOOT_SEED = 20261112
MAKER_FEE = 0.0
TAKER_FEE_BASE = 0.07
MIN_LEGS = 2000           # card (c)
MIN_POSITIVE_TICKER_SHARE = 0.60
TICKERS = ("KXBTCD", "KXBTC15M", "KXETH15M")   # primary + the other two families that promoted
BANDS = ((0.0, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 0.90), (0.90, 1.01))


def _load_read_module():
    """Reuse the read's own statistics + settlement fetcher instead of re-deriving them."""
    path = os.path.join(ROOT, "scripts", "kalshi-maker-read.py")
    spec = importlib.util.spec_from_file_location("kalshi_maker_read", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


READ = _load_read_module()


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_epoch(iso):
    """'2026-10-12T21:50:25.662469Z' -> epoch seconds (float).

    The tape carries fractional seconds of 2-6 digits ('...21.04152Z' appears in ~10% of rows and
    datetime.fromisoformat REJECTS 5 digits), so the fraction is normalised to 6 digits before
    parsing.  Dropping those rows silently is the bug this function exists to prevent -- it cost
    9.9% of the KXBTCD prints on the first run of this instrument.
    """
    s = iso[:-1] + "+00:00" if iso.endswith("Z") else iso
    if "." in s:
        head, tail = s.split(".", 1)
        off = ""
        for sep in ("+", "-"):
            idx = tail.find(sep)
            if idx > 0:
                off = tail[idx:]
                tail = tail[:idx]
                break
        s = head + "." + (tail + "000000")[:6] + off
    return datetime.fromisoformat(s).timestamp()


def credit_frac(print_contracts):
    return READ.credit_frac(print_contracts)


def no_pnl_per_contract(no_price, result):
    """NO leg: payoff 1 if the venue said NO, else 0, minus the price we paid."""
    if result == "no":
        return 1.0 - no_price
    if result == "yes":
        return -no_price
    return None


# ------------------------------------------------------------------ the simulator
class TickerState:
    """Live orders for one ticker.  One entry per resting price (S2/S3)."""

    __slots__ = ("live", "heap")

    def __init__(self):
        self.live = {}      # target_yes_price -> (deadline_epoch, trigger_epoch)
        self.heap = []      # (deadline, target) lazy expiry

    def expire(self, now):
        heap = self.heap
        live = self.live
        while heap and heap[0][0] < now:
            dl, tgt = heapq.heappop(heap)
            cur = live.get(tgt)
            if cur is not None and cur[0] == dl:
                del live[tgt]

    def add(self, target, deadline, trigger_ts):
        if target in self.live:
            return False
        self.live[target] = (deadline, trigger_ts)
        heapq.heappush(self.heap, (deadline, target))
        return True

    def take(self, target):
        cur = self.live.pop(target, None)
        return cur  # (deadline, trigger_ts) or None


def run_sim(families, limit_files=None, verbose=True, max_files=None):
    """One streaming pass over the tape, three arms, ordered per ticker by print ts."""
    files = sorted(glob.glob(PRINTS_GLOB))
    if limit_files:
        files = files[:limit_files]
    if max_files:
        files = files[-max_files:]

    fam_keys = tuple('"family":"%s"' % f for f in families)
    state = {}          # ticker -> {"A": TickerState, "B": TickerState}
    fam_of = {}
    arms = {a: {"legs": [], "orders": 0, "dedupe_skips": 0}
            for a in ("A_at", "A_one", "A_sweep", "B_print", "R_print")}
    n_rows = 0
    n_files = 0
    parse_failures = 0
    t0 = time.time()

    for i, path in enumerate(files):
        rows = []
        with gzip.open(path, "rt") as fh:
            for line in fh:
                if '"family":"' not in line:
                    continue
                if not any(k in line for k in fam_keys):
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                fam = r.get("family")
                if fam not in families:
                    continue
                try:
                    rows.append((ts_epoch(r["ts"]), r["ticker"], fam,
                                 float(r["yes_price"]), r.get("taker_side"),
                                 float(r.get("contracts") or 0.0)))
                except (KeyError, ValueError, TypeError):
                    parse_failures += 1
                    continue
        n_rows += len(rows)
        n_files += 1
        rows.sort(key=lambda x: x[0])

        for ts, tick, fam, p, taker, cts in rows:
            st = state.get(tick)
            if st is None:
                st = state[tick] = {"A": TickerState(), "B": TickerState(), "O": TickerState()}
                fam_of[tick] = fam
            # 1. fill first (an order cannot be filled by the print that created it)
            if taker == "yes":
                s = st["A"]
                s.expire(ts)
                hit = s.take(p)
                if hit is not None:
                    # our resting NO price = 1 - the yes price the taker paid us at
                    leg = (tick, fam, ts, hit[1], OUR_SIZE, credit_frac(cts), round(1.0 - p, 4))
                    arms["A_at"]["legs"].append(leg)
                    arms["A_one"]["legs"].append(leg)
                # sweep arm: every live target at or below the printed yes price
                for t in sorted([t for t in s.live if t <= p + 1e-9]):
                    cur = s.take(t)
                    if cur is not None:
                        arms["A_sweep"]["legs"].append(
                            (tick, fam, ts, cur[1], OUR_SIZE, credit_frac(cts), round(1.0 - t, 4)))
                # one-level arm: a print that gaps THROUGH our price takes the BEST-priced
                # resting level it crossed and nothing deeper (the conservative sweep model)
                o = st["O"]
                o.expire(ts)
                o_hit = o.take(p)
                if o_hit is None:
                    lower = [t for t in o.live if t < p - 1e-9]
                    if lower:
                        best = max(lower)
                        o_hit = o.take(best)
                        if o_hit is not None:
                            arms["A_one"]["legs"].append(
                                (tick, fam, ts, o_hit[1], OUR_SIZE, credit_frac(cts),
                                 round(1.0 - best, 4)))
                s = st["B"]
                s.expire(ts)
                hit = s.take(p)
                if hit is not None:
                    arms["B_print"]["legs"].append(
                        (tick, fam, ts, hit[1], OUR_SIZE, credit_frac(cts), round(1.0 - p, 4)))
                # read-equivalent arm: no order, no queue, no lifetime -- every opposing
                # print credits a NO fill at its own implied price (validation control)
                arms["R_print"]["legs"].append(
                    (tick, fam, ts, ts, OUR_SIZE, credit_frac(cts), round(1.0 - p, 4)))
            else:
                st["A"].expire(ts)
                st["B"].expire(ts)
                st["O"].expire(ts)

            # 2. generate the would-be order from THIS print (S3)
            if TICK < p < 1.0:
                deadline = ts + LIFETIME_S
                target_a = round(p + TICK, 2)
                if target_a <= 0.99:
                    if st["A"].add(target_a, deadline, ts):
                        arms["A_at"]["orders"] += 1
                        arms["A_sweep"]["orders"] += 1
                    else:
                        arms["A_at"]["dedupe_skips"] += 1
                    if st["O"].add(target_a, deadline, ts):
                        arms["A_one"]["orders"] += 1
                target_b = round(p, 2)
                if 0.0 < target_b <= 0.99:
                    if st["B"].add(target_b, deadline, ts):
                        arms["B_print"]["orders"] += 1
                    else:
                        arms["B_print"]["dedupe_skips"] += 1
        if verbose and (i + 1) % 50 == 0:
            print("  files %d/%d  rows %d  arms A=%d B=%d  %.0fs"
                  % (i + 1, len(files), n_rows, len(arms["A_at"]["legs"]),
                     len(arms["B_print"]["legs"]), time.time() - t0), flush=True)
    return arms, n_rows, n_files, parse_failures, fam_of, time.time() - t0


# ------------------------------------------------------------------ statistics
def band_of(p):
    for lo, hi in BANDS:
        if lo <= p < hi:
            return "%0.2f-%0.2f" % (lo, min(hi, 1.0))
    return "?"


def summarise_arm(legs, settle, family, split_ts=None, band_ci=False):
    """Fill-weighted EV per contract + ticker-clustered CI + the card's verdict tests."""
    per_ticker = {}
    band = {}
    lat = {}
    pnl = 0.0
    contracts = 0.0
    unsettled = 0
    lat_vals = []
    h1 = [0.0, 0.0]
    h2 = [0.0, 0.0]
    band_ticker = {} if band_ci else None
    for tick, fam, ts, trig_ts, our, frac, no_price in legs:
        if fam != family:
            continue
        res = settle.get(tick)
        if res not in ("yes", "no"):
            unsettled += 1
            continue
        cred = frac * our
        ev = no_pnl_per_contract(no_price, res)
        p = cred * ev
        pnl += p
        contracts += cred
        if split_ts is not None:
            h = h1 if ts < split_ts else h2
            h[0] += p
            h[1] += cred
        pt = per_ticker.setdefault(tick, [0.0, 0.0, 0])
        pt[0] += p
        pt[1] += cred
        pt[2] += 1
        b = band.setdefault(band_of(no_price), [0.0, 0.0, 0])
        b[0] += p
        b[1] += cred
        b[2] += 1
        if band_ticker is not None:
            bt = band_ticker.setdefault(band_of(no_price), {})
            e = bt.setdefault(tick, [0.0, 0.0])
            e[0] += p
            e[1] += cred
        if trig_ts is not None:
            d = ts - trig_ts
            lat_vals.append(d)
            key = ("0-2s" if d <= 2 else "2-10s" if d <= 10 else "10-30s" if d <= 30 else "30-60s")
            lb = lat.setdefault(key, [0.0, 0.0, 0])
            lb[0] += p
            lb[1] += cred
            lb[2] += 1
    pt_list = [(v[0], v[1]) for v in per_ticker.values() if v[1] > 0]
    lo, hi = READ.bootstrap_ci(pt_list, n=BOOT_N, seed=BOOT_SEED) if pt_list else (None, None)
    pos = sum(1 for v in pt_list if v[0] > 0)
    ev_per_ticker = sorted((v[0] / v[1]) for v in pt_list if v[1] > 0)
    leg_count = len([l for l in legs if l[1] == family])
    legs_per_ticker = sorted(v[2] for v in per_ticker.values())

    def breadth(min_legs):
        sel = [v for v in per_ticker.values() if v[2] >= min_legs and v[1] > 0]
        if not sel:
            return None, 0
        return round(sum(1 for v in sel if v[0] > 0) / len(sel), 4), len(sel)

    b_all = breadth(1)
    b5 = breadth(5)
    b20 = breadth(20)
    pnl_sorted = sorted((v[0] for v in per_ticker.values()), reverse=True)
    top10 = sum(pnl_sorted[:10])
    cred_top10 = sum(v[1] for v in sorted(per_ticker.values(), key=lambda v: -v[0])[:10])
    cred_rest = contracts - cred_top10
    # per-band ticker-clustered CI (only when asked: it costs a bootstrap per band)
    if band_ticker is not None:
        for k, v in band_ticker.items():
            pts = [(x[0], x[1]) for x in v.values() if x[1] > 0]
            if len(pts) >= 30:
                blo, bhi = READ.bootstrap_ci(pts, n=BOOT_N, seed=BOOT_SEED)
                band[k].append(None if blo is None else round(blo, 5))
                band[k].append(None if bhi is None else round(bhi, 5))
                band[k].append(len(pts))

    out = {
        "legs": leg_count,
        "settled_legs": leg_count - unsettled,
        "unsettled_legs": unsettled,
        "credited_contracts": round(contracts, 2),
        "pnl": round(pnl, 4),
        "ev_per_contract": round(pnl / contracts, 5) if contracts > 0 else None,
        "ci95": [None if lo is None else round(lo, 5), None if hi is None else round(hi, 5)],
        "tickers": len(pt_list),
        "positive_ticker_share": b_all[0],
        "positive_ticker_share_min5_legs": b5[0],
        "positive_ticker_share_min20_legs": b20[0],
        "tickers_min20_legs": b20[1],
        "ticker_ev_median": round(ev_per_ticker[len(ev_per_ticker) // 2], 5) if ev_per_ticker else None,
        "ticker_ev_trimmed_mean_5pct": (
            round(sum(ev_per_ticker[max(1, len(ev_per_ticker) // 20):len(ev_per_ticker) - max(1, len(ev_per_ticker) // 20)])
                  / max(1, len(ev_per_ticker) - 2 * max(1, len(ev_per_ticker) // 20)), 5)
            if len(ev_per_ticker) > 20 else None),
        "legs_per_ticker_median": legs_per_ticker[len(legs_per_ticker) // 2] if legs_per_ticker else None,
        "legs_per_ticker_p90": legs_per_ticker[int(0.9 * (len(legs_per_ticker) - 1))] if legs_per_ticker else None,
        "pnl_ex_top10_tickers": round(pnl - top10, 2),
        "ev_ex_top10_tickers": (round((pnl - top10) / cred_rest, 5) if cred_rest > 0 else None),
        "top10_share_of_pnl": (round(top10 / pnl, 4) if pnl else None),
        "halves": ({"ev_first_half": round(h1[0] / h1[1], 5) if h1[1] else None,
                    "ev_second_half": round(h2[0] / h2[1], 5) if h2[1] else None,
                    "split_ts_utc": (datetime.fromtimestamp(split_ts, timezone.utc)
                                     .strftime("%Y-%m-%dT%H:%M:%SZ") if split_ts else None)}
                   if split_ts is not None else None),
        "bands": {k: {"legs": v[2], "contracts": round(v[1], 2),
                      "ev_per_contract": round(v[0] / v[1], 5) if v[1] else None,
                      "ci95": ([v[3], v[4]] if len(v) > 4 else None),
                      "band_tickers": (v[5] if len(v) > 5 else None)}
                  for k, v in sorted(band.items())},
        "latency_buckets": {k: {"legs": v[2], "contracts": round(v[1], 2),
                                "ev_per_contract": round(v[0] / v[1], 5) if v[1] else None}
                            for k, v in sorted(lat.items())},
        "latency_median_s": (round(sorted(lat_vals)[len(lat_vals) // 2], 2) if lat_vals else None),
    }
    # the card's three pre-registered tests, applied verbatim (c)
    if out["legs"] < MIN_LEGS:
        out["verdict"] = "UNDERPOWERED"
        out["reason"] = "%d legs (<%d)" % (out["legs"], MIN_LEGS)
    elif out["ev_per_contract"] is None:
        out["verdict"] = "NO SETTLEMENT"
        out["reason"] = "no settled leg"
    elif out["ev_per_contract"] > 0 and (lo or 0) > 0 and (out["positive_ticker_share"] or 0) >= MIN_POSITIVE_TICKER_SHARE:
        out["verdict"] = "GRADUATES"
        out["reason"] = "EV>0, CI excludes zero (lo=%.5f), %.1f%% of tickers positive" % (
            lo, 100 * out["positive_ticker_share"])
    else:
        failed = []
        if not (out["ev_per_contract"] > 0):
            failed.append("EV<=0 (%.5f)" % out["ev_per_contract"])
        if not ((lo or 0) > 0):
            failed.append("CI includes zero (lo=%s)" % lo)
        if (out["positive_ticker_share"] or 0) < MIN_POSITIVE_TICKER_SHARE:
            failed.append("%.1f%% of tickers positive (<%.0f%%)"
                          % (100 * (out["positive_ticker_share"] or 0), 100 * MIN_POSITIVE_TICKER_SHARE))
        out["verdict"] = "CLOSE"
        out["reason"] = "; ".join(failed)
    return out


def latency_profile(legs, family):
    """Fill latency vs EV -- the adverse-selection footprint (S8's fill-time-to-settlement)."""
    return None


# ------------------------------------------------------------------ self-test
def self_test():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))
        print("  %-62s %s" % (name, "PASS" if cond else "FAIL"))

    # build a tiny tape: KXT prints at 0.40 then a later YES-buy at 0.41 within 60s
    def row(ts, tick, p, taker, cts=100.0, fam="KXT"):
        return (ts, tick, fam, p, taker, cts)

    # --- 0. timestamp normalisation: the tape mixes 2-6 fractional digits and
    #        datetime.fromisoformat rejects 5, which silently dropped ~10% of prints before this
    #        check existed.
    check("5-digit fractional seconds parse (the row that cost 10% of the tape)",
          abs(ts_epoch("2026-10-12T21:50:21.04152Z")
              - datetime(2026, 10, 12, 21, 50, 21, 41520, tzinfo=timezone.utc).timestamp()) < 1e-6)
    check("2-digit and 6-digit fractions agree with a manual epoch",
          abs(ts_epoch("2026-10-12T21:50:21.04Z") - ts_epoch("2026-10-12T21:50:21.040000Z")) < 1e-9)
    check("no fraction and an explicit offset both parse",
          abs(ts_epoch("2026-10-12T21:50:21Z") - ts_epoch("2026-10-12T21:50:21+00:00")) < 1e-9)
    check("a Z timestamp is UTC, not naive local time (a 5 h shift would break every join)",
          abs(ts_epoch("2026-10-12T21:50:21Z")
              - datetime(2026, 10, 12, 21, 50, 21, tzinfo=timezone.utc).timestamp()) < 1e-9)

    # --- 1. exact-at-price: a print BELOW our resting price is not a fill
    st = TickerState()
    st.add(0.41, 100 + LIFETIME_S, 100.0)
    check("print BELOW the resting price does not fill (card's 390-vs-2 error)",
          st.take(0.40) is None)
    check("print AT the resting price fills", st.take(0.41) is not None and 0.41 not in st.live)

    # --- 2. lifetime: an order is dead after LIFETIME_S
    st = TickerState()
    st.add(0.41, 100 + LIFETIME_S, 100.0)
    st.expire(100 + LIFETIME_S + 0.5)
    check("order expires 0.5 s past its 60 s lifetime", 0.41 not in st.live)
    st = TickerState()
    st.add(0.41, 100 + LIFETIME_S, 100.0)
    st.expire(100 + LIFETIME_S - 0.5)
    check("order is still live 0.5 s before its deadline", 0.41 in st.live)

    # --- 3. one live order per level: repeated triggers do not stack
    st = TickerState()
    added = [st.add(0.41, 100 + LIFETIME_S, 100.0) for _ in range(5)]
    check("five triggers at the same level create ONE order", sum(added) == 1)

    # --- 3b. a gap-through print takes ONLY the best-priced level it crossed (one-level arm)
    st = TickerState()
    st.add(0.45, 100 + LIFETIME_S, 100.0)
    st.add(0.50, 100 + LIFETIME_S, 100.0)
    lower = [t for t in st.live if t < 0.55 - 1e-9]
    best = max(lower) if lower else None
    took = st.take(best) if best is not None else None
    check("gap print at 0.55 takes the BEST crossed level (0.50) and leaves 0.45 resting",
          took is not None and 0.50 not in st.live and 0.45 in st.live)

    # --- 4. credit rule (card's) and the maker fee
    check("100-contract fill credits the full 100", abs(credit_frac(100.0) * OUR_SIZE - 100.0) < 1e-9)
    check("400-contract fill credits 25 (min(1,100/400))", abs(credit_frac(400.0) * OUR_SIZE - 25.0) < 1e-9)
    check("maker fee on a standard series is zero", MAKER_FEE == 0.0)

    # --- 5. PnL signs on the NO leg
    check("NO @0.59 settling NO is +0.41/contract", abs(no_pnl_per_contract(0.59, "no") - 0.41) < 1e-12)
    check("NO @0.59 settling YES is -0.59/contract", abs(no_pnl_per_contract(0.59, "yes") + 0.59) < 1e-12)
    check("unsettled market yields None, never a guess", no_pnl_per_contract(0.59, None) is None)

    # --- 6. end-to-end on a synthetic tape: the arm must book exactly one leg at our price
    legs = []
    st = TickerState()
    tape = [row(100.0, "KXT-A", 0.40, "no"),          # trigger -> rest NO at 0.59 (yes target .41)
            row(100.5, "KXT-A", 0.40, "yes"),         # taker buys YES at .40: below .41, NOT a fill
            row(101.0, "KXT-A", 0.41, "yes", 100.0),  # taker buys YES at .41 -> fills us at NO .59
            row(101.2, "KXT-A", 0.41, "yes", 100.0)]  # order already consumed: no second fill
    for ts, tick, fam, p, taker, cts in tape:
        st.expire(ts)
        if taker == "yes":
            cur = st.take(p)
            if cur is not None:
                legs.append((tick, fam, ts, cur[1], OUR_SIZE, credit_frac(cts),
                             round(1.0 - p, 4)))
        if TICK < p < 1.0 and round(p + TICK, 2) <= 0.99:
            st.add(round(p + TICK, 2), ts + LIFETIME_S, ts)
    check("synthetic tape books exactly ONE leg (consumed order cannot refill)", len(legs) == 1)
    check("that leg is booked at OUR resting price (0.59 NO), not the print's",
          bool(legs) and abs(legs[0][6] - 0.59) < 1e-9)
    check("that leg carries its trigger time (fill latency is measurable)",
          bool(legs) and abs(legs[0][3] - 100.0) < 1e-9 and abs(legs[0][2] - 101.0) < 1e-9)

    # --- 7. settlement marks the leg and the verdict plumbing is not hard-coded
    s_nowin = summarise_arm(legs, {"KXT-A": "yes"}, "KXT")
    s_win = summarise_arm(legs, {"KXT-A": "no"}, "KXT")
    check("same leg, NO settlement -> positive EV", (s_win["ev_per_contract"] or 0) > 0)
    check("same leg, YES settlement -> negative EV", (s_nowin["ev_per_contract"] or 0) < 0)
    check("underpowered family cannot GRADUATE", s_win["verdict"] != "GRADUATES")

    # --- 8. unsettled legs are excluded, never marked at zero
    s_un = summarise_arm(legs, {}, "KXT")
    check("unsettled legs are counted unsettled, never marked at zero",
          s_un["unsettled_legs"] == 1 and s_un["pnl"] == 0.0 and s_un["ev_per_contract"] is None)

    failed = [n for n, ok in checks if not ok]
    print("\n  self-test: %d/%d passed" % (len(checks) - len(failed), len(checks)))
    if failed:
        print("  RED: %s" % "; ".join(failed))
        return 1
    return 0


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--limit-print-files", type=int, default=None)
    ap.add_argument("--last-print-files", type=int, default=None)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--json", default=ARTIFACT)
    ap.add_argument("--dump-legs", default=None,
                    help="write the A_at legs as JSONL for an independent re-check")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    print("kalshi-maker-shadow-sim -- resting-order fill simulation (card kalshi-maker-read-prereg)")
    print("rule: rest NO at (1-p)-0.01 for %d ct, %ds lifetime, fill by a LATER opposing print at our price"
          % (OUR_SIZE, LIFETIME_S))

    cov_rows, hours = READ.tape_hours()
    print("tape clock: %.1f captured hours over %d coverage rows" % (hours, cov_rows))

    arms, n_rows, n_files, parse_failures, fam_of, elapsed = run_sim(
        set(TICKERS), limit_files=args.limit_print_files,
        max_files=args.last_print_files, verbose=not args.quiet)
    print("prints read: %d qualifying rows from %d files in %.0fs (%d unparseable rows)"
          % (n_rows, n_files, elapsed, parse_failures))

    settle = {}
    if os.path.exists(SETTLE_SHARED):
        with open(SETTLE_SHARED) as fh:
            settle = json.load(fh)
    own = {}
    if os.path.exists(SETTLE_OWN):
        try:
            with open(SETTLE_OWN) as fh:
                own = json.load(fh)
        except ValueError:
            own = {}
    settle.update(own)
    if not args.no_fetch:
        for s in TICKERS:
            try:
                got = READ.fetch_series_settlements(s, own, verbose=True)
                print("  settle %s: +%d" % (s, got))
            except Exception as exc:                       # noqa: BLE001 - loud, then continue
                print("  settle %s: FETCH FAILED (%s) -- cached cells only" % (s, exc))
        tmp = SETTLE_OWN + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(own, fh)
        os.replace(tmp, SETTLE_OWN)
        settle.update(own)
    print("settlement cache: %d tickers" % len(settle))

    families = {}
    all_ts = [l[2] for l in arms["A_at"]["legs"]]
    split_ts = ((min(all_ts) + max(all_ts)) / 2.0) if all_ts else None
    for fam in TICKERS:
        fam_out = {}
        for arm in ("A_at", "A_one", "A_sweep", "B_print", "R_print"):
            fam_out[arm] = summarise_arm(arms[arm]["legs"], settle, fam, split_ts=split_ts,
                                         band_ci=(fam == "KXBTCD" and arm in ("A_at", "A_one")))
            fam_out[arm]["orders_generated"] = arms[arm]["orders"]
            fam_out[arm]["dedupe_skips"] = arms[arm]["dedupe_skips"]
            o = fam_out[arm]["orders_generated"]
            fam_out[arm]["fill_rate"] = (round(fam_out[arm]["legs"] / o, 4) if o else None)
        families[fam] = fam_out

    hdr = ("%-9s %-9s %8s %10s %11s %9s %-20s %7s %6s %5s %5s  %s"
           % ("family", "arm", "legs", "contracts", "pnl", "ev/ct", "ci95", "tickers",
              "pos%", "5+", "20+", "verdict"))
    print("\n" + hdr)
    for fam in TICKERS:
        for arm in ("A_at", "A_one", "A_sweep", "B_print", "R_print"):
            r = families[fam][arm]
            ci = r["ci95"]
            def pc(v):
                return "-" if v is None else "%.0f" % (100 * v)
            print("%-9s %-9s %8d %10.0f %11.2f %9s [%s,%s] %7d %6s %5s %5s  %s"
                  % (fam, arm, r["legs"], r["credited_contracts"], r["pnl"],
                     "-" if r["ev_per_contract"] is None else "%+.3fc" % (100 * r["ev_per_contract"]),
                     "-" if ci[0] is None else "%+.3f" % (100 * ci[0]),
                     "-" if ci[1] is None else "%+.3f" % (100 * ci[1]),
                     r["tickers"], pc(r["positive_ticker_share"]),
                     pc(r["positive_ticker_share_min5_legs"]),
                     pc(r["positive_ticker_share_min20_legs"]),
                     r["verdict"]))
    print("\nverdict reasons (primary family, primary arm):")
    print("  KXBTCD A_at: %s -- %s" % (families["KXBTCD"]["A_at"]["verdict"],
                                       families["KXBTCD"]["A_at"]["reason"]))
    print("bands (KXBTCD, A_at / A_one) with ticker-clustered CIs where n>=30 tickers:")
    for arm in ("A_at", "A_one"):
        for k, v in families["KXBTCD"][arm]["bands"].items():
            ci = v.get("ci95")
            ci_s = ("[%+.3f,%+.3f]" % (100 * ci[0], 100 * ci[1])
                    if ci and ci[0] is not None and ci[1] is not None else "[-, -]")
            print("  %-8s %-11s legs=%7d ct=%10.0f ev=%s ci=%s n_tick=%s"
                  % (arm, k, v["legs"], v["contracts"],
                     "-" if v["ev_per_contract"] is None else "%+.3fc" % (100 * v["ev_per_contract"]),
                     ci_s, v.get("band_tickers")))

    artifact = {
        "generated_at": now_utc(),
        "card": "kalshi-maker-read-prereg",
        "instrument": "scripts/kalshi-maker-shadow-sim.py",
        "pre_registration": {
            "source": "card note (a), verbatim: rest a NO bid at (1-p)-$0.01 for 100 ct, 60s lifetime, "
                      "fill by a LATER print at that price, maker fee $0, mark to the venue result",
            "our_size_contracts": OUR_SIZE,
            "lifetime_seconds": LIFETIME_S,
            "tick": TICK,
            "maker_fee_per_contract": MAKER_FEE,
            "credit_rule": "min(1, our_size/print_contracts) * our_size at OUR resting price",
            "fill_rule_primary": "later print, same ticker, taker_side=yes, yes_price == our target, "
                                 "ts <= trigger+60s; a print BELOW our price is NOT a fill",
            "fill_rule_sweep": "later print at yes_price >= our target fills at OUR target (sensitivity)",
            "control_arm": "same machinery resting at the trigger print's own implied NO price (1-p)",
            "bootstrap": {"unit": "ticker", "n": BOOT_N, "seed": BOOT_SEED,
                          "interval": "percentile 2.5/97.5"},
            "decision_rule": {
                "min_legs": MIN_LEGS,
                "ev_positive": True,
                "ci95_excludes_zero": True,
                "min_positive_ticker_share": MIN_POSITIVE_TICKER_SHARE,
                "quote": "card (c): graduate only if >=2,000 filled legs AND fill-weighted EV>0 with a "
                        "95% ticker-clustered CI excluding zero AND >=60% of filled tickers positive; "
                        "otherwise the lane CLOSES",
            },
        },
        "tape": {"print_file_glob": "data/kalshi-tape/prints-*.jsonl.gz", "files_read": n_files,
                 "qualifying_print_rows": n_rows, "unparseable_print_rows": parse_failures,
                 "coverage_rows": cov_rows,
                 "captured_hours": round(hours, 2), "print_size_floor_contracts": 100,
                 "note": "L1 large-print fills only; L3 a hole can only lose fills"},
        "settlement": {"cached_tickers": len(settle)},
        "families": families,
        "limits": ["L1 print floor 100 contracts", "L2 no book/queue/partials/cancels",
                   "L3 duty cycle: holes lose fills, never create them",
                   "L4 NO side only (card (a)); L5 paper only, no key exists"],
        "runtime_seconds": round(elapsed, 1),
    }
    with open(args.json, "w") as fh:
        json.dump(artifact, fh, indent=1)
    print("\nwrote %s" % args.json)

    if args.dump_legs:
        n = 0
        with open(args.dump_legs, "w") as fh:
            for tick, fam, ts, trig, our, frac, no_price in arms["A_at"]["legs"]:
                res = settle.get(tick)
                fh.write(json.dumps({"ticker": tick, "family": fam, "fill_ts": ts,
                                     "trigger_ts": trig, "our_size": our,
                                     "credit_frac": frac, "no_price": no_price,
                                     "result": res}) + "\n")
                n += 1
        print("wrote %d A_at legs to %s" % (n, args.dump_legs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
