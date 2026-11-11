#!/usr/bin/env python3
"""kalshi-maker-read.py -- pre-registered Kalshi MAKER read, net of adverse selection.

CARD: kalshi-maker-read-prereg (user-approved 2026-10-12, read-only).  This file is the
instrument the card owed; its decision rule below is the CARD'S, quoted verbatim, not a
rule invented here.

THE CARD'S GATE (verbatim, pre-registered 2026-10-12 BEFORE the tape existed)
-----------------------------------------------------------------------------
"PROMOTE ONLY IF: net-of-adverse-selection maker EV is positive with a 95% CI excluding
zero at the pre-registered sample size (per family, no pooling). Otherwise the lane
CLOSES and the negative result is recorded -- that is the expected outcome, since our
moat is wallet-copy + measurement, not microstructure. Rules fixed in advance: universe =
allowlisted families with >=500 captured bars; a fill requires a print AT the resting
price with the taker OPPOSING us (a print below your bid is NOT a fill -- measured error:
that proxy said 390 fills at 0.90 where the correct count is 2); because queue position
and unfilled remainder are unobservable on a keyless tape, credit min(1, our_size /
print_size) of each qualifying print and print the unfiltered count beside it; maker fee
$0 on standard series; every simulated fill marked to the market's settlement via Kalshi
/markets/{ticker}, reported as fill-time-to-settlement PnL. THIS is the test -- a lane
that only fills when the market is about to move against it shows a healthy fill count
and negative PnL."

OPERATIONAL CHOICES FIXED HERE, WRITTEN BEFORE THE FIRST LIVE RUN
-----------------------------------------------------------------
The card fixed every rule above but left four operational constants unnamed.  They are
fixed here, before the run, because choosing them after seeing PnL would be the same
lookahead this repo has already paid for twice:

  R1 OUR_SIZE = 100 contracts (the venue's own verbatim-print floor, so the credit rule
     min(1, our_size/print_size) is applied on the smallest print the tape carries).
  R2 RESTING POPULATION = every print is read as a fill of a resting order AT ITS OWN
     PRINTED PRICE on the side OPPOSING the taker.  A print at yes_price p with
     taker_side='no' (the taker SOLD) fills a resting YES bid at p; taker_side='yes'
     (the taker BOUGHT) fills a resting NO bid at (1-p).  One print can therefore fill
     exactly one side, and the read is a PER-PRICE PROFILE, not one order per market:
     it answers "if we had been resting at level p in this family, what did the fills at
     p pay?"  No book, queue position or cancel behaviour is claimed (see LIMITS).
  R3 PREREG SAMPLE SIZE per family = >=100 distinct settled tickers AND >=1,000 credited
     contracts.  The card required "the pre-registered sample size" without naming it;
     this is that number, fixed before the run.  A family below it is reported
     UNDERPOWERED and is NOT promoted (absence of evidence is not evidence of edge).
  R4 CI = cluster bootstrap over TICKER blocks (2,000 resamples, seed 20261111,
     percentile interval).  Prints inside one market share one settlement, so the ticker
     -- not the print -- is the independent unit; a print-level bootstrap would
     manufacture significance.

WHAT A POSITIVE READ WOULD MEAN, AND WHAT IT WOULD NOT
-----------------------------------------------------
Maker EV per contract here is E[settlement payoff] - fill price.  With no book in the
tape there is no half-spread term, so this is NOT "capture"; it is the calibration error
of the prices at which fills actually happen, i.e. exactly the adverse-selection channel
the card calls the whole question: makers are filled by takers, and a maker whose fills
sit at prices worse than fair is being selected against.  A positive number means fills
are priced better than fair; a negative one means the taker knew something.

LIMITS, STATED SO THEY TRAVEL WITH EVERY NUMBER
-----------------------------------------------
C1 PRINT FLOOR: the tape keeps verbatim prints at >=100 contracts (kalshi-tape-capture
   --min-contracts 100), so this read describes LARGE-PRINT fills only. Small prints --
   which are most of a maker's fills in practice -- are invisible.  Direction of bias is
   NOT assumed; it is unmeasured.
C2 NO BOOK: no bid/ask, no queue position, no unfilled remainder, no cancels.  A resting
   order that would have been filled earlier and larger is credited once, at the print.
C3 DUTY CYCLE: coverage.jsonl is the authority for how much of the clock is captured
   (~591 h over 2026-10-12..11-11 at the current 15-min/14-min cycle).  A family is only
   read over the minutes actually captured.
C4 SETTLEMENT is the venue's own `result` field from /markets?series_ticker=..&status=
   settled.  Markets whose result is not yet posted are counted UNSETTLED, never guessed,
   and never filled with a mark.
C5 OVERLAP WITH lip-ledger.py: that card measured resting fills inside LIP reward
   programs (quote universe, one side, cap_per_side) and reported capture/drift/settle.
   This read is the general allowlisted-family price profile; its numbers are NOT a
   re-derivation of the LIP result and must not be swapped for it.

USAGE
  python3 scripts/kalshi-maker-read.py                 # full read, writes the artifact
  python3 scripts/kalshi-maker-read.py --self-test     # detector proof, exits 1 on RED
  python3 scripts/kalshi-maker-read.py --limit-print-files 20 --no-fetch   # smoke
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import os
import random
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAPE = os.path.join(ROOT, "data", "kalshi-tape")
BARS_DAILY_GLOB = os.path.join(TAPE, "bars-*.jsonl.gz")
BARS_LIVE = os.path.join(TAPE, "bars.jsonl")
PRINTS_GLOB = os.path.join(TAPE, "prints-*.jsonl.gz")
COVERAGE = os.path.join(TAPE, "coverage.jsonl")
FAMILIES_FILE = os.path.join(ROOT, "data", "kalshi-tape-families.json")
SETTLE_CACHE = os.path.join(ROOT, "data", "kalshi-maker-settlements.json")
ARTIFACT = os.path.join(ROOT, "data", "kalshi-maker-read.json")
API = "https://api.elections.kalshi.com/trade-api/v2"

OUR_SIZE = 100.0          # R1
MIN_BARS = 500            # gate: universe = allowlisted families with >=500 captured bars
MIN_TICKERS = 100         # R3
MIN_CONTRACTS = 1000.0    # R3
BOOT_N = 2000             # R4
BOOT_SEED = 20261111      # R4
TAKER_FEE_BASE = 0.07     # published schedule: 0.07 * C * P * (1-P)


# ------------------------------------------------------------------ helpers
def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_families():
    with open(FAMILIES_FILE) as fh:
        return set(json.load(fh)["families"].keys())


def credit_frac(print_contracts):
    """Gate's credit rule: min(1, our_size / print_size) as a FRACTION of our order."""
    if not print_contracts or print_contracts <= 0:
        return 0.0
    return min(1.0, OUR_SIZE / float(print_contracts))


def credited_contracts(print_contracts):
    return credit_frac(print_contracts) * OUR_SIZE


def maker_side_and_price(row):
    """R2: the resting side the taker traded against, and the price that side paid."""
    if row.get("taker_side") == "yes":
        return "NO", round(float(row["no_price"]), 4)
    return "YES", round(float(row["yes_price"]), 4)


def payoff_yes(result):
    if result == "yes":
        return 1.0
    if result == "no":
        return 0.0
    return None


def pnl_per_contract(side, price, result):
    y = payoff_yes(result)
    if y is None:
        return None
    return (y - price) if side == "YES" else ((1.0 - y) - price)


def taker_fee_per_contract(price):
    return TAKER_FEE_BASE * price * (1.0 - price)


# ------------------------------------------------------------------ stage 1: universe
def bars_census():
    counts = {}
    tickers = {}
    for path in sorted(glob.glob(BARS_DAILY_GLOB)) + ([BARS_LIVE] if os.path.exists(BARS_LIVE) else []):
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                fam = r.get("family")
                if not fam:
                    continue
                counts[fam] = counts.get(fam, 0) + 1
                tickers.setdefault(fam, set()).add(r.get("ticker"))
    return counts, {k: len(v) for k, v in tickers.items()}


def tape_hours():
    hours = 0.0
    rows = 0
    if os.path.exists(COVERAGE):
        with open(COVERAGE) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                rows += 1
                hours += float(r.get("window_captured_seconds") or 0.0) / 3600.0
    return rows, hours


# ------------------------------------------------------------------ stage 2: prints
def sweep_prints(universe, limit_files=None, verbose=True):
    """Aggregate qualifying (ticker, side, price) fills.  Read-only over the tape."""
    cells = {}          # (ticker, side, price) -> [fills, credited_contracts]
    naive = {}          # (ticker, side, price) -> count under the REJECTED <= proxy
    fam_of = {}
    n_rows = 0
    files = sorted(glob.glob(PRINTS_GLOB))
    if limit_files:
        files = files[:limit_files]
    t0 = time.time()
    for i, path in enumerate(files):
        with gzip.open(path, "rt") as fh:
            for line in fh:
                if '"family":"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                fam = r.get("family")
                if fam not in universe:
                    continue
                n_rows += 1
                tick = r.get("ticker") or ""
                side, price = maker_side_and_price(r)
                cts = float(r.get("contracts") or 0.0)
                key = (tick, side, price)
                cell = cells.get(key)
                if cell is None:
                    cells[key] = [1, credited_contracts(cts)]
                else:
                    cell[0] += 1
                    cell[1] += credited_contracts(cts)
                fam_of[tick] = fam
        if verbose and (i + 1) % 100 == 0:
            print("  prints: %d/%d files, %d rows, %d cells, %.0fs"
                  % (i + 1, len(files), n_rows, len(cells), time.time() - t0), flush=True)
    return cells, n_rows, len(files), fam_of


def naive_proxy_count(cells, levels):
    """The REJECTED proxy, kept only as a negative control in --self-test."""
    out = {}
    for (tick, side, price), (n, _c) in cells.items():
        for lv in levels:
            if price <= lv:
                out[(tick, side, lv)] = out.get((tick, side, lv), 0) + n
    return out


# ------------------------------------------------------------------ stage 3: settlement
def fetch_series_settlements(series, cache, max_pages=220, verbose=True):
    """Venue truth for one series: ticker -> result.  Cursor-paged, cached, fail-loud."""
    got = 0
    cursor = None
    seen_cursors = set()
    for _page in range(max_pages):
        q = {"series_ticker": series, "status": "settled", "limit": 1000}
        if cursor:
            q["cursor"] = cursor
        url = API + "/markets?" + urllib.parse.urlencode(q)
        body = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "copybot-kalshi-maker-read/1.0"})
                with urllib.request.urlopen(req, timeout=45) as resp:
                    body = json.loads(resp.read().decode())
                break
            except Exception as exc:                      # noqa: BLE001 - retried, then loud
                if attempt == 2:
                    raise RuntimeError("settlement fetch failed for %s: %s" % (series, exc))
                time.sleep(1.5 * (attempt + 1))
        markets = body.get("markets") or []
        for m in markets:
            t = m.get("ticker")
            res = m.get("result")
            if t and res in ("yes", "no"):
                cache[t] = res
                got += 1
        # Kalshi returns its paging token as `cursor`.  `next_cursor` is the lip-ledger
        # shape for a DIFFERENT endpoint; using it here silently capped every series at
        # ONE page (999 tickers/series, measured 2026-11-11) and left 71% of cells
        # unsettled.  Accept both keys and guard against a token that does not advance.
        cursor = body.get("next_cursor") or body.get("cursor")
        if not markets or not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        time.sleep(0.25)
    if verbose:
        print("  settle: %-12s +%d tickers" % (series, got), flush=True)
    return got


def load_settle_cache():
    if os.path.exists(SETTLE_CACHE):
        try:
            with open(SETTLE_CACHE) as fh:
                return json.load(fh)
        except ValueError:
            return {}
    return {}


def save_settle_cache(cache):
    tmp = SETTLE_CACHE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cache, fh)
    os.replace(tmp, SETTLE_CACHE)


# ------------------------------------------------------------------ stage 4: statistics
def bootstrap_ci(per_ticker, n=BOOT_N, seed=BOOT_SEED):
    """Cluster bootstrap over tickers.  per_ticker: list of (pnl, contracts)."""
    if len(per_ticker) < 2:
        return None, None
    rng = random.Random(seed)
    k = len(per_ticker)
    means = []
    for _ in range(n):
        sp = 0.0
        sc = 0.0
        for _i in range(k):
            p, c = per_ticker[rng.randrange(k)]
            sp += p
            sc += c
        if sc > 0:
            means.append(sp / sc)
    if not means:
        return None, None
    means.sort()
    lo = means[int(0.025 * (len(means) - 1))]
    hi = means[int(0.975 * (len(means) - 1))]
    return lo, hi


def summarise(cells, settlements, fam_of, universe, min_price_fills=1):
    """Per family x side totals, price profile and the pre-registered verdict."""
    per_fam = {}
    unsettled = 0
    settled_cells = 0
    fam_unsettled = {}
    fam_settled = {}
    for (tick, side, price), (n, cred) in cells.items():
        fam = fam_of.get(tick)
        if fam not in universe:
            continue
        res = settlements.get(tick)
        bucket = per_fam.setdefault(fam, {})
        side_b = bucket.setdefault(side, {"cells": {}, "per_ticker": {}, "fills": 0,
                                          "contracts": 0.0, "pnl": 0.0})
        ev = pnl_per_contract(side, price, res) if res else None
        if ev is None:
            unsettled += 1
            fam_unsettled[fam] = fam_unsettled.get(fam, 0) + 1
            continue
        settled_cells += 1
        fam_settled[fam] = fam_settled.get(fam, 0) + 1
        pnl = cred * ev
        side_b["fills"] += n
        side_b["contracts"] += cred
        side_b["pnl"] += pnl
        c = side_b["cells"].setdefault(price, [0, 0.0, 0.0])
        c[0] += n
        c[1] += cred
        c[2] += pnl
        pt = side_b["per_ticker"].setdefault(tick, [0.0, 0.0])
        pt[0] += pnl
        pt[1] += cred

    out = {}
    for fam, sides in per_fam.items():
        fam_out = {"sides": {}, "verdict": None, "reason": None,
                   "cells_settled": fam_settled.get(fam, 0),
                   "cells_unsettled": fam_unsettled.get(fam, 0)}
        for side, b in sides.items():
            pt = [(v[0], v[1]) for v in b["per_ticker"].values() if v[1] > 0]
            mean = (b["pnl"] / b["contracts"]) if b["contracts"] > 0 else None
            lo, hi = bootstrap_ci(pt)
            profile = []
            for price in sorted(b["cells"]):
                n, cred, pnl = b["cells"][price]
                if n < min_price_fills:
                    continue
                profile.append({"price": price, "fills": n, "contracts": round(cred, 2),
                                "pnl": round(pnl, 4),
                                "ev_per_contract": round(pnl / cred, 5) if cred else None,
                                "taker_fee_per_contract": round(taker_fee_per_contract(price), 5)})
            fam_out["sides"][side] = {
                "fills": b["fills"], "credited_contracts": round(b["contracts"], 2),
                "pnl": round(b["pnl"], 4),
                "ev_per_contract": None if mean is None else round(mean, 5),
                "ci95": [None if lo is None else round(lo, 5), None if hi is None else round(hi, 5)],
                "tickers": len(pt),
                "profile": profile,
            }
        # verdict per family: pool the two sides? NO -- the gate says per family, and a
        # maker rests one side per market; the sides are the same population mirrored, so
        # the family read is the CONTRACT-WEIGHTED union of both sides (stated, not hidden).
        tot_c = sum(v["credited_contracts"] for v in fam_out["sides"].values())
        tot_p = sum(v["pnl"] for v in fam_out["sides"].values())
        tot_t = sum(v["tickers"] for v in fam_out["sides"].values())
        fam_out["credited_contracts"] = round(tot_c, 2)
        fam_out["pnl"] = round(tot_p, 4)
        fam_out["ev_per_contract"] = round(tot_p / tot_c, 5) if tot_c > 0 else None
        lo_all, hi_all = None, None
        merged = {}
        for side, b in sides.items():
            for tick, v in b["per_ticker"].items():
                m = merged.setdefault(tick, [0.0, 0.0])
                m[0] += v[0]
                m[1] += v[1]
        if tot_c > 0:
            lo_all, hi_all = bootstrap_ci([(v[0], v[1]) for v in merged.values() if v[1] > 0])
        fam_out["ci95"] = [None if lo_all is None else round(lo_all, 5),
                           None if hi_all is None else round(hi_all, 5)]
        fam_out["tickers"] = len(merged)
        # CONCENTRATION -- a family total is only an edge if it is not one market's story.
        t_ev = sorted((v[0] / v[1]) for v in merged.values() if v[1] > 0)
        t_pnl = sorted((v[0] for v in merged.values()), reverse=True)
        if t_ev:
            fam_out["ticker_ev_median"] = round(t_ev[len(t_ev) // 2], 5)
            cut = max(1, int(0.05 * len(t_ev)))
            trimmed = t_ev[cut:len(t_ev) - cut] or t_ev
            fam_out["ticker_ev_trimmed_mean_5pct"] = round(sum(trimmed) / len(trimmed), 5)
        top10 = sum(t_pnl[:10])
        fam_out["pnl_ex_top10_tickers"] = round(tot_p - top10, 2)
        fam_out["top10_share_of_pnl"] = round(top10 / tot_p, 4) if tot_p else None
        if tot_t < MIN_TICKERS or tot_c < MIN_CONTRACTS:
            fam_out["verdict"] = "UNDERPOWERED"
            fam_out["reason"] = ("%d tickers (<%d) or %.0f credited contracts (<%.0f)"
                                 % (len(merged), MIN_TICKERS, tot_c, MIN_CONTRACTS))
        elif lo_all is not None and lo_all > 0:
            fam_out["verdict"] = "PROMOTE"
            fam_out["reason"] = "EV/contract > 0 with 95%% cluster CI excluding zero (lo=%.5f)" % lo_all
        elif hi_all is not None and hi_all < 0:
            fam_out["verdict"] = "CLOSE"
            fam_out["reason"] = "EV/contract < 0 with 95%% cluster CI excluding zero (hi=%.5f)" % hi_all
        else:
            fam_out["verdict"] = "CLOSE"
            fam_out["reason"] = "CI includes zero -- no edge detected at this sample"
        out[fam] = fam_out
    return out, unsettled, settled_cells


# ------------------------------------------------------------------ self-test
def self_test():
    """Proves the detector can go RED.  Every check exits 1 on failure."""
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))
        print("  %-58s %s" % (name, "PASS" if cond else "FAIL"))

    # 1. the gate's own measured error: a print below the resting price is NOT a fill
    row_hi = {"taker_side": "no", "yes_price": 0.90, "no_price": 0.10, "contracts": 100.0}
    row_lo = {"taker_side": "no", "yes_price": 0.85, "no_price": 0.15, "contracts": 100.0}
    cells = {}
    for r in (row_hi, row_lo):
        side, price = maker_side_and_price(r)
        key = ("T1", side, price)
        cell = cells.setdefault(key, [0, 0.0])
        cell[0] += 1
        cell[1] += credited_contracts(r["contracts"])
    exact_at_90 = cells.get(("T1", "YES", 0.90), [0, 0.0])[0]
    naive = naive_proxy_count(cells, [0.90])
    check("exact-at-price counts ONE fill at 0.90", exact_at_90 == 1)
    check("rejected <= proxy would count TWO at 0.90 (gate's 390-vs-2 error)",
          naive.get(("T1", "YES", 0.90)) == 2)

    # 2. side/price derivation is the OPPOSITE side to the taker
    s_yes, p_yes = maker_side_and_price({"taker_side": "no", "yes_price": 0.30, "no_price": 0.70})
    s_no, p_no = maker_side_and_price({"taker_side": "yes", "yes_price": 0.30, "no_price": 0.70})
    check("taker SELL fills the YES bid at yes_price", (s_yes, p_yes) == ("YES", 0.30))
    check("taker BUY fills the NO bid at no_price", (s_no, p_no) == ("NO", 0.70))

    # 3. settlement PnL signs
    check("YES @0.30 settling YES is +0.70/contract", abs(pnl_per_contract("YES", 0.30, "yes") - 0.70) < 1e-12)
    check("YES @0.30 settling NO is -0.30/contract", abs(pnl_per_contract("YES", 0.30, "no") + 0.30) < 1e-12)
    check("NO @0.70 settling NO is +0.30/contract", abs(pnl_per_contract("NO", 0.70, "no") - 0.30) < 1e-12)
    check("unsettled market yields None, never a guess", pnl_per_contract("YES", 0.30, None) is None)

    # 4. credit rule
    check("100-contract print credits a full 100", abs(credited_contracts(100.0) - 100.0) < 1e-9)
    check("400-contract print credits 25 (min(1,100/400))", abs(credited_contracts(400.0) - 25.0) < 1e-9)
    check("credit never exceeds our size", credited_contracts(50.0) <= OUR_SIZE)

    # 5. maker fee is zero and the taker reference is not
    check("taker fee at 0.25 is 0.013125/contract (>0)",
          abs(taker_fee_per_contract(0.25) - 0.013125) < 1e-9)

    # 6. bootstrap must EXCLUDE zero on a clean positive and INCLUDE it on noise
    pos = [(10.0, 100.0)] * 120
    lo, hi = bootstrap_ci(pos)
    check("bootstrap: 120 tickers all +0.10/contract -> CI lo > 0", lo is not None and lo > 0)
    rng = random.Random(7)
    noise = [(rng.choice([-10.0, 10.0]), 100.0) for _ in range(120)]
    lo2, hi2 = bootstrap_ci(noise)
    check("bootstrap: balanced noise -> CI straddles zero", lo2 is not None and lo2 <= 0 <= hi2)

    # 7. verdict plumbing is not hard-coded
    cells2 = {("TX", "YES", 0.50): [5, 500.0]}
    fams2 = {"TX": "FAM"}
    s_win, _u, _sc = summarise(cells2, {"TX": "yes"}, fams2, {"FAM"}, min_price_fills=1)
    s_lose, _u2, _sc2 = summarise(cells2, {"TX": "no"}, fams2, {"FAM"}, min_price_fills=1)
    check("same fills, won settlement -> positive EV", s_win["FAM"]["ev_per_contract"] > 0)
    check("same fills, lost settlement -> negative EV", s_lose["FAM"]["ev_per_contract"] < 0)
    s_un, _u3, _sc3 = summarise({("U1", "YES", 0.5): [1, 100.0]}, {}, {"U1": "FL"}, {"FL"})
    check("unsettled-only family reports no PnL rather than 0 edge",
          s_un["FL"]["ev_per_contract"] is None)

    failed = [n for n, ok in checks if not ok]
    print("\n  self-test: %d/%d passed" % (len(checks) - len(failed), len(checks)))
    if failed:
        print("  RED: %s" % "; ".join(failed))
        return 1
    return 0


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true", help="prove the detector can go RED")
    ap.add_argument("--limit-print-files", type=int, default=None, help="smoke: first N print files")
    ap.add_argument("--no-fetch", action="store_true", help="use the settlement cache only")
    ap.add_argument("--min-price-fills", type=int, default=1, help="drop profile levels below N fills")
    ap.add_argument("--json", default=ARTIFACT)
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    print("kalshi-maker-read -- pre-registered maker read (card kalshi-maker-read-prereg)")
    allow = load_families()
    counts, tick_counts = bars_census()
    universe = {f for f, n in counts.items() if n >= MIN_BARS and f in allow}
    print("universe: %d of %d allowlisted families have >=%d captured bars"
          % (len(universe), len(allow), MIN_BARS))
    for f in sorted(universe, key=lambda x: -counts[x]):
        print("   %-12s bars=%7d tickers=%6d" % (f, counts[f], tick_counts.get(f, 0)))

    cov_rows, hours = tape_hours()
    print("tape clock: %.1f captured hours over %d coverage rows" % (hours, cov_rows))

    cells, n_rows, n_files, fam_of = sweep_prints(universe, limit_files=args.limit_print_files)
    print("prints read: %d qualifying rows from %d files -> %d (ticker, side, price) cells"
          % (n_rows, n_files, len(cells)))

    settle = load_settle_cache()
    if not args.no_fetch:
        have = set(settle)
        needed_series = sorted(universe)
        print("settlements: cache %d tickers; sweeping %d series" % (len(have), len(needed_series)))
        for s in needed_series:
            fetch_series_settlements(s, settle)
        save_settle_cache(settle)

    out, unsettled, settled_cells = summarise(cells, settle, fam_of, universe,
                                              min_price_fills=args.min_price_fills)
    order = sorted(out, key=lambda f: -(out[f]["pnl"] or 0))
    print("\n%-12s %10s %12s %10s %10s %9s %8s  %s"
          % ("family", "contracts", "pnl", "ev/ct", "ci_lo", "ci_hi", "tickers", "verdict"))
    for f in order:
        r = out[f]
        print("%-12s %10.0f %12.2f %10.5f %10s %9s %8d  %s"
              % (f, r["credited_contracts"], r["pnl"],
                 -999 if r["ev_per_contract"] is None else r["ev_per_contract"],
                 r["ci95"][0], r["ci95"][1], r["tickers"], r["verdict"]))
    print("unsettled cells: %d (never guessed) | settled cells: %d" % (unsettled, settled_cells))
    print("settlement coverage of tape tickers (a family read below 100% is a SLICE):")
    for fam in sorted(universe, key=lambda f: -counts[f]):
        tt = sum(1 for t, f in fam_of.items() if f == fam)
        ss = sum(1 for t, f in fam_of.items() if f == fam and t in settle)
        print("   %-12s %6d/%6d tape tickers settled (%.1f%%)"
              % (fam, ss, tt, (100.0 * ss / tt) if tt else 0.0))

    artifact = {
        "generated_at": now_utc(),
        "card": "kalshi-maker-read-prereg",
        "pre_registration": {
            "gate_quoted_from_card": True,
            "our_size_contracts": OUR_SIZE,
            "min_bars_per_family": MIN_BARS,
            "min_tickers_per_family": MIN_TICKERS,
            "min_credited_contracts_per_family": MIN_CONTRACTS,
            "bootstrap": {"unit": "ticker", "n": BOOT_N, "seed": BOOT_SEED, "interval": "percentile 2.5/97.5"},
            "maker_fee_per_contract": 0.0,
            "taker_fee_law": "0.07 * P * (1-P) per contract (published schedule, quote-only reference)",
            "fill_rule": "print AT the resting price, taker opposing; a print strictly below the bid is NOT a fill",
        },
        "tape": {"print_file_glob": "data/kalshi-tape/prints-*.jsonl.gz", "files_read": n_files,
                 "qualifying_print_rows": n_rows, "coverage_rows": cov_rows,
                 "captured_hours": round(hours, 2),
                 "print_size_floor_contracts": 100, "note": "C1: large-print fills only"},
        "settlement_coverage_by_family": {
            fam: {"tape_tickers": sum(1 for t, f in fam_of.items() if f == fam),
                  "with_settlement": sum(1 for t, f in fam_of.items() if f == fam and t in settle)}
            for fam in sorted(universe)
        },
        "batches": {"universe": sorted(universe),
                    "bars": {f: counts[f] for f in sorted(universe)},
                    "tickers_with_bars": {f: tick_counts.get(f, 0) for f in sorted(universe)}},
        "settlement": {"cached_tickers": len(settle), "settled_cells": settled_cells,
                       "unsettled_cells": unsettled},
        "families": out,
    }
    with open(args.json, "w") as fh:
        json.dump(artifact, fh, indent=1)
    print("\nwrote %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
