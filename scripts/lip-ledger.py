#!/usr/bin/env python3
"""lip-ledger.py -- Kalshi LIP reward ledger, measured NET of adverse selection.

Answers one pre-registered question (roadmap card `lip-ledger-kalshi-reward`,
hard gate 2026-11-24):

    Is the LIP reward leg worth >= $0.0131 per contract-hour NET of adverse
    selection, over >= 50 counted program-hours?

Read-only.  Nothing here places an order, changes a rule, or writes to the DB.

WHY THIS SCRIPT EXISTS IN THIS SHAPE (three defects fixed 2026-11-09):

  1. THE FEED IS CURSOR-PAGINATED AND SILENTLY TRUNCATES AT 1,000/STATUS.
     `GET /incentive_programs?status=X&limit=1000` returns `next_cursor`; a fetcher that
     ignores it keeps 4,000 of 91,158 programs and reaches back ~12 days instead of to
     2026-03-12.  A base rate computed on the truncated page is a base rate on the most
     recent week, which is exactly where the short-window programs cluster.
  2. `target_size_fp` (and `discount_factor_bps`) are NULLABLE in the OpenAPI schema.
     A row without a target cannot be scored; it must be COUNTED and skipped, not
     allowed to raise KeyError and kill the run mid-ledger.
  3. `period_reward` is CENTI-CENTS.  Verified at the primary source, not inferred:
     docs.kalshi.com/openapi.yaml, components.schemas.IncentiveProgram.period_reward,
     "Total reward for the period in centi-cents" (read 2026-11-09).  The scale is
     DECISIVE for this gate -- reading it as cents multiplies every figure by 100 and
     flips the verdict -- so it is printed with every report, never defaulted silently.

THE THREE MEASUREMENTS, IN ORDER OF DECISIVENESS
------------------------------------------------
  A. CEILING   pool / (2 * target * hours) is a HARD UPPER BOUND on gross reward per
      contract-hour for a program -- what a single participant earns by resting the full
      Target Size on both sides and collecting 100% of the Time Period Reward.  It needs
      no book data and no fill model, so it decides eligibility for the whole feed.
      Derivation: snapshot score tops out at 1.0 per side, so a sole participant's share
      is 1; reward = pool; contract-hours = 2 * target * hours.  Resting LESS than target
      does not raise it: the qualifying set stops at Target Size, so reward/contract-hour
      stays pool/(total_size*hours) with total_size >= target.

  B. LEDGER    For programs we hold book snapshots for: our normalized share at each
      snapshot, valued at the program's own rate.  Snapshots are ~hourly, so the COUNTED
      hours are OBSERVED snapshots, never the program's calendar duration (the 2026-11-09
      draft of this file counted 1,284 program-hours out of 12 observations per program).

  C. ADVERSE   For every taker print inside the program window, the resting bid on the
      opposite side would have filled at the print price.  Reported separately:
        capture   fair_before - fill_px   (the half-spread a maker earns by resting)
        drift     fair_after - fair_before (the adverse move after the fill -- negative
                  is adverse for us; this is the number the card calls adverse selection)
        settle    payout - fill_px         (what the position is worth at resolution)
      The pre-2026-11-09 draft reported `mid_after - fill_px` as "adverse selection";
      that quantity CONTAINS the half-spread, so a legitimately adverse book could read
      as a gain.  Drift and capture are now booked separately.

MODEL (Kalshi filed LIP terms; help.kalshi.com "Liquidity Incentive Program", read
2026-11-09, and the CFTC rulebook filings):
  * a Snapshot is taken once per second; a Snapshot is EXCLUDED unless both sides carry
    resting orders sufficient to reach Target Size (two-sided test);
  * Reference Price = walking down from the best bid, the first level at which cumulative
    resting size >= Target Size / 5;
  * Qualifying Bids = levels walked down until cumulative size >= Target Size (the walk
    STOPS there);
  * score(bid) = DiscountFactor ** ticks_below_reference * size(bid), normalized within
    the side; a user's snapshot score is the sum over both sides (max 2.0);
  * reward = (our period score / all participants' period score) * Time Period Reward *
    (non-excluded snapshots / total snapshots), rounded down to the cent.

DATA (read-only):
  data/kalshi-lip-programs.jsonl.gz     paged incentive_programs feed (written by --fetch)
  data/kalshi-macro-quotes.jsonl        hourly book snapshots (top level only)
  data/kalshi-macro-settled.jsonl       settlement tape
  data/kalshi-tape/prints-*.jsonl.gz    venue print tape (whitelisted families only)

FLAGS (judgement calls; override on the command line):
  --unit centi-cents|mills|cents   scale of period_reward (default centi-cents, verified)
  --size N                         contracts we rest per side (default = Target Size, the
                                   smallest size that can qualify a snapshot alone)
  --placement improve|join         improve the touch by a tick (default) or join it
  --max-pages N                    page cap for --fetch (default 200 per status)

USAGE:
  python3 scripts/lip-ledger.py --fetch     # page the feed to exhaustion
  python3 scripts/lip-ledger.py             # full ledger + verdict
  python3 scripts/lip-ledger.py --unit cents   # sensitivity arm (100x)
"""
import argparse
import collections
import datetime
import glob
import gzip
import json
import os
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")
PROG_FILE = os.path.join(DATA, "kalshi-lip-programs.jsonl.gz")
LEGACY_PROG_FILE = os.path.join(DATA, "kalshi-incentive-programs.json")
QUOTES = os.path.join(DATA, "kalshi-macro-quotes.jsonl")
SETTLED = os.path.join(DATA, "kalshi-macro-settled.jsonl")
TAPE_GLOB = os.path.join(DATA, "kalshi-tape", "prints-*.jsonl.gz")
TAPE_FAMILIES = os.path.join(DATA, "kalshi-tape-families.json")
OUT_JSON = os.path.join(DATA, "lip-ledger.json")

API = "https://api.elections.kalshi.com/trade-api/v2/incentive_programs"
STATUSES = ["all", "active", "upcoming", "closed", "paid_out"]
UNIT_DIVISOR = {"centi-cents": 10000.0, "mills": 1000.0, "cents": 100.0}
KEEP_FIELDS = ("id", "market_id", "market_ticker", "incentive_type", "incentive_description",
               "start_date", "end_date", "period_reward", "paid_out", "discount_factor_bps",
               "target_size_fp", "max_reward_per_account")
TICK = 0.01
GATE_USD_PER_CONTRACT_HOUR = 0.0131
GATE_MIN_PROGRAM_HOURS = 50


def parse_iso(s):
    s = s.replace("Z", "").split("+")[0].split(".")[0]
    return datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def hours_between(a, b):
    return (b - a).total_seconds() / 3600.0


# ---------------------------------------------------------------- program feed
def fetch_programs(max_pages, verbose=True):
    """Page every status filter to exhaustion and persist the union.

    `next_cursor` is the whole point: without it the store keeps 1,000 rows per status
    (~12 days) and the above-gate base rate is computed on the newest week alone.
    """
    rows, stats = {}, {}
    for st in STATUSES:
        cur, npages, n = None, 0, 0
        while npages < max_pages:
            q = {"status": st, "limit": 1000}
            if cur:
                q["cursor"] = cur
            req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q),
                                         headers={"User-Agent": "lip-ledger/1.0"})
            body = None
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=60) as r:
                        body = json.loads(r.read().decode())
                    break
                except Exception as e:                        # noqa: BLE001 - retried below
                    if verbose:
                        print("  fetch retry %d (%s): %s" % (attempt + 1, st, e))
                    time.sleep(1.5 * (attempt + 1))
            if body is None:
                raise RuntimeError("incentive_programs fetch failed for status=%s" % st)
            got = body.get("incentive_programs", [])
            if not got:
                break
            npages += 1
            n += len(got)
            for p in got:
                rec = {k: p.get(k) for k in KEEP_FIELDS if k in p}
                prev = rows.get(p["id"])
                if prev:
                    prev["_statuses"] = sorted(set(prev["_statuses"]) | {st})
                else:
                    rec["_statuses"] = [st]
                    rows[p["id"]] = rec
            cur = body.get("next_cursor")
            if not cur:
                break
            time.sleep(0.3)
        stats[st] = {"pages": npages, "rows": n, "exhausted": cur is None}
        if verbose:
            print("  status=%-8s pages=%3d rows=%6d exhausted=%s" % (st, npages, n, cur is None))

    payload = {
        "fetched_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": API,
        "unit": "centi-cents",
        "paged": True,
        "stats": stats,
    }
    with gzip.open(PROG_FILE, "wt") as f:
        f.write(json.dumps(payload) + "\n")
        for r in sorted(rows.values(), key=lambda p: (p["start_date"], p["market_ticker"])):
            f.write(json.dumps(r) + "\n")
    print("wrote %s (%d unique programs, %.1f MB)" %
          (PROG_FILE, len(rows), os.path.getsize(PROG_FILE) / 1e6))
    return payload, list(rows.values())


def load_programs():
    """Return (payload, usable_liquidity_rows, counters).

    A row is usable only if it is a liquidity program with a parseable target and a
    positive window.  Every reason a row is dropped is counted and printed -- a feed
    filter that silently disappears rows reads as "the venue pays nothing there".
    """
    if os.path.exists(PROG_FILE):
        with gzip.open(PROG_FILE, "rt") as f:
            payload = json.loads(f.readline())
            rows = [json.loads(line) for line in f if line.strip()]
    elif os.path.exists(LEGACY_PROG_FILE):
        d = json.load(open(LEGACY_PROG_FILE))
        payload = {k: d[k] for k in ("fetched_at", "source") if k in d}
        payload["paged"] = False
        rows = d["rows"]
        print("WARNING: %s is absent; falling back to the UNPAGED snapshot (%d rows, "
              "~12 days). Run --fetch before quoting any base rate." % (PROG_FILE, len(rows)))
    else:
        raise SystemExit("no program feed on disk -- run: python3 scripts/lip-ledger.py --fetch")

    counts = collections.Counter()
    usable = []
    for p in rows:
        counts["rows"] += 1
        if p.get("incentive_type") != "liquidity":
            counts["non_liquidity"] += 1
            continue
        if not p.get("target_size_fp"):
            counts["no_target_size"] += 1     # legal per schema; unscorable
            continue
        try:
            t = float(p["target_size_fp"])
            a, e = parse_iso(p["start_date"]), parse_iso(p["end_date"])
        except Exception:                      # noqa: BLE001 - malformed dates
            counts["bad_dates"] += 1
            continue
        h = hours_between(a, e)
        if t <= 0:
            counts["zero_target"] += 1
            continue
        if h <= 0:
            counts["non_positive_window"] += 1
            continue
        p["_start"], p["_end"], p["_target"], p["_hours"] = a, e, t, h
        p["_df"] = (p.get("discount_factor_bps") or 5000) / 10000.0
        p["_pool"] = p["period_reward"] / UNIT_DIVISOR["centi-cents"]
        p["_ceiling_pch"] = p["_pool"] / (2.0 * t * h)
        usable.append(p)
        counts["usable"] += 1
    return payload, usable, counts


def ceiling_of(prog, unit_divisor):
    """Hard upper bound on gross $/contract-hour, at 100% of the reward pool."""
    return (prog["period_reward"] / unit_divisor) / (2.0 * prog["_target"] * prog["_hours"])


# ---------------------------------------------------------------- market data
def quote_tickers():
    out = set()
    with open(QUOTES) as f:
        for line in f:
            out.add(json.loads(line)["ticker"])
    return out


def load_quotes(tickers):
    out = collections.defaultdict(list)
    with open(QUOTES) as f:
        for line in f:
            r = json.loads(line)
            if r["ticker"] in tickers:
                r["_dt"] = parse_iso(r["ts"])
                out[r["ticker"]].append(r)
    for t in out:
        out[t].sort(key=lambda r: r["_dt"])
    return out


def load_settled():
    out = {}
    if not os.path.exists(SETTLED):
        return out
    with open(SETTLED) as f:
        for line in f:
            r = json.loads(line)
            out[r["ticker"]] = r
    return out


def tape_families():
    import configparser  # noqa: F401  (kept out of module import path; not used)
    if not os.path.exists(TAPE_FAMILIES):
        return set()
    return set(json.load(open(TAPE_FAMILIES)).get("families", {}))


def load_prints(families):
    """Print tape rows for the whitelisted families.

    The capture writes bars+prints only for data/kalshi-tape-families.json, so a family
    absent from that file has NO tape at all.  Callers must distinguish "no fills" from
    "not captured" -- `tape_families()` is what separates the two.
    """
    out = collections.defaultdict(list)
    for path in sorted(glob.glob(TAPE_GLOB)):
        with gzip.open(path, "rt") as f:
            for line in f:
                i = line.find('"family":"')
                if i < 0:
                    continue
                j = line.find('"', i + 10)
                if line[i + 10:j] not in families:
                    continue
                r = json.loads(line)
                out[r["ticker"]].append(r)
    for t in out:
        out[t].sort(key=lambda r: r["ts"])
    return out


# ---------------------------------------------------------------- the LIP score model
def side_score(ref_price, levels, target, df, our_size, our_price=None):
    """Our normalized score on one side of one snapshot.

    `levels` is the visible depth, best first.  The quote file carries the TOP LEVEL ONLY,
    so callers pass at most one level; the qualifying walk therefore cannot be replayed
    past the touch.  Two consequences, both stated rather than hidden:
      * when top-level size < Target Size the snapshot is (correctly) excluded -- the real
        book may hold deeper qualifying size we cannot see, so a survivor fraction is a
        LOWER bound;
      * when top-level size >= Target Size the walk stops at the touch and the visible
        level IS the qualifying set, so the denominator is exact for that snapshot.
    """
    if ref_price is None or ref_price >= 1.0 - 1e-9:
        return 0.0, 0.0, False
    entries = []
    if our_price is not None and our_size > 0:
        entries.append((our_price, our_size, True))
    for p, s in levels:
        if s and s > 0:
            entries.append((p, s, False))
    if not entries:
        return 0.0, 0.0, False
    ref = max(p for p, _, _ in entries)
    total = mine = qsize = 0.0
    for p, s, is_ours in entries:
        ticks = int(round((ref - p) / TICK))
        w = (df ** max(ticks, 0)) * s
        total += w
        qsize += s
        if is_ours:
            mine += w
    if qsize < target - 1e-9 or total <= 0:
        return 0.0, qsize, False
    return mine / total, qsize, True


def best_placements(snap, placement):
    """Where a maker could rest on each side without crossing."""
    b, a = snap["yes_bid"], snap["yes_ask"]
    out = {"yes": None, "no": None}
    if b is None or a is None:
        return out
    if placement == "improve" and b > 0 and b + TICK < a - 1e-9:
        out["yes"] = round(b + TICK, 4)
    elif b > 0:
        out["yes"] = round(b, 4)
    elif a - TICK >= TICK - 1e-9:
        out["yes"] = round(a - TICK, 4)
    no_best, no_ask = 1.0 - a, 1.0 - b
    if placement == "improve" and no_best > 0 and no_best + TICK < no_ask - 1e-9:
        out["no"] = round(no_best + TICK, 4)
    elif no_best > 0:
        out["no"] = round(no_best, 4)
    elif no_ask - TICK >= TICK - 1e-9:
        out["no"] = round(no_ask - TICK, 4)
    return out


def score_snapshot(snap, target, df, size, placement):
    pl = best_placements(snap, placement)
    yes_price, no_price = pl["yes"], pl["no"]

    y_score, y_q, y_qual = side_score(
        snap["yes_bid"] if snap["yes_bid"] > 0 else yes_price,
        [(snap["yes_bid"], snap["bid_size"])] if snap["yes_bid"] > 0 else [],
        target, df, size, yes_price)

    no_ref = (1.0 - snap["yes_ask"]) if snap["yes_ask"] is not None else None
    n_score, n_q, n_qual = side_score(
        no_ref,
        [(1.0 - snap["yes_ask"], snap["ask_size"])] if snap["yes_ask"] else [],
        target, df, size, no_price)

    survive = bool(y_qual and n_qual)
    return {
        "share": ((y_score + n_score) / 2.0) if survive else 0.0,
        "survives": survive,
        "placeable_yes": yes_price is not None,
        "placeable_no": no_price is not None,
        "yes_qual": y_qual, "no_qual": n_qual,
        "yes_price": yes_price, "no_price": no_price,
        # top-of-book depth carried for the reference-price check (target/5 rule)
        "yes_top": snap["bid_size"] or 0.0, "no_top": snap["ask_size"] or 0.0,
        "rested": (size if yes_price is not None else 0) + (size if no_price is not None else 0),
    }


# ---------------------------------------------------------------- adverse selection
def snapshot_at_or_before(snaps, ts):
    lo, hi = 0, len(snaps) - 1
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if snaps[mid]["_dt"] <= ts:
            best = snaps[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def snapshot_after(snaps, ts, max_gap_h=2.5):
    for s in snaps:
        if s["_dt"] > ts:
            return s if hours_between(ts, s["_dt"]) <= max_gap_h else None
    return None


def adverse_selection(prog, snaps, prints, settled_row, cap_per_side=None):
    """Maker fills inside the program window, decomposed into capture / drift / settle.

    A print with taker_side == 'no' is a taker BUYING NO, i.e. a resting YES bid at
    yes_price fills us.  taker_side == 'yes' fills a resting NO bid at (1 - yes_price).
    We fill at the print price only when it is no better than where we would have rested:
    a YES bid at +P fills on prints at yes_price <= P, a NO bid at +N on (1-yes) <= N.

    `cap_per_side` stops accumulating a side once we have been filled for that many
    contracts.  It is the honest bound for a resting order: we cannot be filled for more
    than we are resting at any instant, and without the cap a busy book shows a fill
    volume that dwarfs the capital the reward is paid on.  The uncapped count is returned
    separately so the reader can see how much flow the cap discards.
    """
    start, end = prog["_start"], prog["_end"]
    in_win = [s for s in snaps if start <= s["_dt"] <= end]
    fills = []
    filled_by_side = collections.defaultdict(float)
    raw_contracts = 0.0
    for pr in prints:
        ts = parse_iso(pr["ts"])
        if not (start <= ts <= end):
            continue
        prior = snapshot_at_or_before(in_win, ts)
        if prior is None:
            continue
        pl = best_placements(prior, "improve")
        side = "no" if pr["taker_side"] == "yes" else "yes"
        px = pr["yes_price"] if side == "yes" else pr["no_price"]
        limit = pl[side]
        if limit is None or px is None or px > limit + 1e-9:
            continue
        raw_contracts += pr["contracts"]
        if cap_per_side is not None:
            room = cap_per_side - filled_by_side[side]
            if room <= 1e-9:
                continue
            cts = min(pr["contracts"], room)
        else:
            cts = pr["contracts"]
        filled_by_side[side] += cts
        after = snapshot_after(in_win, ts)
        fair_before = prior["mid"] if side == "yes" else (1.0 - prior["mid"])
        fair_after = None
        if after is not None:
            fair_after = after["mid"] if side == "yes" else (1.0 - after["mid"])
        fills.append({
            "ts": pr["ts"], "side": side, "contracts": cts, "px": px,
            "capture": round(fair_before - px, 4),
            "drift": None if fair_after is None else round(fair_after - fair_before, 4),
            "markout_to_after": None if fair_after is None else round(fair_after - px, 4),
        })
    settle_pnl = None
    if settled_row and fills:
        win_yes = 1.0 if settled_row["result"] == "yes" else 0.0
        settle_pnl = 0.0
        for f in fills:
            payoff = win_yes if f["side"] == "yes" else (1.0 - win_yes)
            settle_pnl += f["contracts"] * (payoff - f["px"])
    return fills, settle_pnl, (settled_row["result"] if settled_row else None), raw_contracts


# ---------------------------------------------------------------- ledger
def build(args):
    payload, programs, counts = load_programs()
    div = UNIT_DIVISOR[args.unit]
    # The loader values pools at the verified centi-cent scale; the flag must be able to
    # move them, or a sensitivity arm reads identical to the base case (it did, 2026-11-09).
    for p in programs:
        p["_pool"] = p["period_reward"] / div
    print("feed: fetched_at=%s paged=%s" % (payload.get("fetched_at"), payload.get("paged")))
    print("rows %d | usable liquidity programs %d | dropped:" % (counts["rows"], counts["usable"]))
    for k in ("non_liquidity", "no_target_size", "bad_dates", "zero_target", "non_positive_window"):
        if counts[k]:
            print("   %-22s %d" % (k, counts[k]))
    print("unit: period_reward read as %s (divisor %.0f)" % (args.unit, div))

    # ---- A. structural ceiling across the whole feed ------------------------
    ceilings = sorted(ceiling_of(p, div) for p in programs)
    above = [p for p in programs if ceiling_of(p, div) >= GATE_USD_PER_CONTRACT_HOUR]
    buckets = collections.defaultdict(list)
    for p in programs:
        h = p["_hours"]
        k = "<=2h" if h <= 2 else "2-8h" if h <= 8 else "8-24h" if h <= 24 else "24-48h" if h <= 48 else ">48h"
        buckets[k].append(ceiling_of(p, div))
    pct = {}
    for q in (0, .1, .25, .5, .75, .9, .99, 1.0):
        i = min(len(ceilings) - 1, int(q * (len(ceilings) - 1))) if ceilings else 0
        pct["p%g" % (q * 100)] = ceilings[i] if ceilings else None

    print("\n--- A. STRUCTURAL CEILING  pool/(2*target*hours), 100% of pool, both sides ---")
    print("programs %d | above gate $%.4f: %d (%.2f%%) | pool in above-gate programs $%.0f of $%.0f (%.1f%%)"
          % (len(programs), GATE_USD_PER_CONTRACT_HOUR, len(above),
             100.0 * len(above) / max(1, len(programs)),
             sum(p["_pool"] for p in above), sum(p["_pool"] for p in programs),
             100.0 * sum(p["_pool"] for p in above) / max(1e-9, sum(p["_pool"] for p in programs))))
    print("ceiling percentiles: " + "  ".join("%s=%.6f" % (k, v) for k, v in pct.items() if v is not None))
    print("%-8s %7s %11s %11s %9s" % ("window", "n", "median", "p90", ">=gate"))
    for k in ("<=2h", "2-8h", "8-24h", "24-48h", ">48h"):
        v = sorted(buckets.get(k, []))
        if not v:
            continue
        print("%-8s %7d %11.6f %11.6f %8.1f%%" % (
            k, len(v), v[len(v) // 2], v[int(0.9 * (len(v) - 1))],
            100.0 * sum(1 for x in v if x >= GATE_USD_PER_CONTRACT_HOUR) / len(v)))
    fam = collections.Counter(p["market_ticker"].split("-")[0] for p in above)
    print("above-gate families: " + ", ".join("%s:%d" % (f, n) for f, n in fam.most_common(12)))

    qt = quote_tickers()
    tf = tape_families()
    q_over = [p for p in programs if p["market_ticker"] in qt]
    q_above = [p for p in q_over if ceiling_of(p, div) >= GATE_USD_PER_CONTRACT_HOUR]
    tape_above = [p for p in above if p["market_ticker"].split("-")[0] in tf]
    print("capture overlap: quote universe %d tickers -> %d programs (%d above gate, max ceiling %.6f)"
          % (len(qt), len(q_over), len(q_above), max([ceiling_of(p, div) for p in q_over] or [0.0])))
    print("                 tape whitelist %d families -> %d above-gate programs (%.1f%% of them)"
          % (len(tf), len(tape_above), 100.0 * len(tape_above) / max(1, len(above))))

    # ---- B. measured ledger on the quote universe --------------------------
    measured = [p for p in programs if p["market_ticker"] in qt]
    quotes = load_quotes(set(p["market_ticker"] for p in measured))
    settled = load_settled()
    prints = load_prints(tf & set(p["market_ticker"].split("-")[0] for p in measured))

    rows = []
    tot = collections.defaultdict(float)
    settled_n = 0
    for p in sorted(measured, key=lambda x: (x["_start"], x["market_ticker"])):
        snaps = quotes.get(p["market_ticker"], [])
        in_win = [s for s in snaps if p["_start"] <= s["_dt"] <= p["_end"]]
        if not in_win:
            continue
        size = args.size if args.size else p["_target"]
        scored = [score_snapshot(s, p["_target"], p["_df"], size, args.placement) for s in in_win]
        n = len(scored)
        # POLICY: we rest Target Size on BOTH sides.  A snapshot where either side cannot be
        # placed is not a snapshot we rest through, so it earns nothing and costs no
        # contract-hours.  Keeping those rows in the denominator is what let four programs
        # print a gross above their own ceiling (one-sided resting halves the capital while
        # the reward formula still pays half the pool).
        usable = [x for x in scored if x["survives"] and x["placeable_yes"] and x["placeable_no"]]
        surv = len(usable)
        frac = surv / n
        mean_share = (sum(x["share"] for x in usable) / surv) if surv else 0.0
        # COVERAGE: a program's reward is paid across its WHOLE period and we can only earn
        # it while actually resting inside it -- which we observe at our snapshots only.
        # Each snapshot stands for at most one hour of resting (and never for more than the
        # window itself), so a 168-hour program observed 12 times is 12 counted hours, not
        # 168.  Valuing the full pool against those 12 hours is the bug that made a
        # $100/168h program print $0.0041/contract-hour against a $0.0003 ceiling.
        cover_h = min(1.0, p["_hours"] / n) if n else 0.0
        counted_hours = surv * cover_h
        counted_frac = (counted_hours / p["_hours"]) if p["_hours"] else 0.0
        payout = p["_pool"] * counted_frac * mean_share
        rested = (sum(x["rested"] for x in usable) / surv) if surv else 0.0
        contract_hours = rested * counted_hours
        gross = payout / contract_hours if contract_hours else 0.0

        fills, settle_pnl, result, raw_contracts = adverse_selection(
            p, snaps, prints.get(p["market_ticker"], []), settled.get(p["market_ticker"]), size)
        filled = sum(f["contracts"] for f in fills)
        drift_usd = sum(f["contracts"] * (f["drift"] or 0.0) for f in fills)
        capture_usd = sum(f["contracts"] * f["capture"] for f in fills)
        # SIGN: drift is the mid move AFTER the fill signed for our side, so an adverse
        # (losing) move is NEGATIVE and belongs ADDED to the reward, not subtracted from it.
        net = ((payout + drift_usd) / contract_hours) if contract_hours else 0.0
        net_full = ((payout + capture_usd + drift_usd) / contract_hours) if contract_hours else 0.0

        rows.append({
            "ticker": p["market_ticker"], "start": p["start_date"], "end": p["end_date"],
            "window_hours": round(p["_hours"], 2), "counted_hours": round(counted_hours, 2),
            "observed_snapshots": n, "survivor_frac": round(frac, 3),
            "target": p["_target"], "df": p["_df"], "pool_usd": round(p["_pool"], 2),
            "ceiling_pch": round(ceiling_of(p, div), 7),
            "mean_share": round(mean_share, 4), "payout_usd": round(payout, 4),
            "contract_hours": round(contract_hours, 1),
            "gross_pch": gross, "net_pch": net,
            "fills": len(fills), "filled_contracts": round(filled, 1),
            "capture_usd": round(capture_usd, 4), "drift_usd": round(drift_usd, 4),
            "net_full_pch": net_full,
            "settle_pnl_usd": None if settle_pnl is None else round(settle_pnl, 4),
            "settled_result": result,
            "top_size_meets_target_frac": round(
                sum(1 for x in scored if x["yes_top"] >= p["_target"] and x["no_top"] >= p["_target"]) / n, 3),
        })
        tot["counted_hours"] += surv
        tot["window_hours"] += p["_hours"]
        tot["payout_usd"] += payout
        tot["contract_hours"] += contract_hours
        tot["drift_usd"] += drift_usd
        tot["capture_usd"] += capture_usd
        tot["filled"] += filled
        if settle_pnl is not None:
            tot["settle_pnl_usd"] += settle_pnl
            settled_n += 1

    print("\n--- B. MEASURED LEDGER (quote universe only) ---")
    print("%-24s %-10s %5s %6s %6s %7s %9s %11s" %
          ("ticker", "start", "obs", "count", "surv", "share", "payout$", "gross/ch"))
    for r in rows:
        print("%-24s %-10s %5d %6.1f %6.2f %7.3f %9.3f %11.7f" % (
            r["ticker"], r["start"][:10], r["observed_snapshots"], r["counted_hours"],
            r["survivor_frac"], r["mean_share"], r["payout_usd"], r["gross_pch"]))
    ch = tot["contract_hours"]
    print("programs %d | counted hours %.1f [gate >= %d] | window hours %.0f | contract-hours %.0f"
          % (len(rows), tot["counted_hours"], GATE_MIN_PROGRAM_HOURS, tot["window_hours"], ch))
    print("payout $%.4f  capture $%.4f  adverse drift $%.4f  fills %d (%.1f contracts)  settle PnL $%s (%d programs)"
          % (tot["payout_usd"], tot["capture_usd"], tot["drift_usd"], sum(r["fills"] for r in rows),
             tot["filled"], ("%.2f" % tot["settle_pnl_usd"]) if settled_n else "n/a", settled_n))

    # ---- C. adverse selection detail ---------------------------------------
    allfills = []
    for p in measured:
        fl, sp, res, raw = adverse_selection(
            p, quotes.get(p["market_ticker"], []), prints.get(p["market_ticker"], []),
            settled.get(p["market_ticker"]), (args.size if args.size else p["_target"]))
        for f in fl:
            f["ticker"] = p["market_ticker"]
            allfills.append(f)
    print("\n--- C. ADVERSE SELECTION (fills inside program windows) ---")
    if allfills:
        cw = sum(f["contracts"] for f in allfills)
        cap = sum(f["contracts"] * f["capture"] for f in allfills) / cw
        dr = [f for f in allfills if f["drift"] is not None]
        dcw = sum(f["contracts"] for f in dr)
        drv = sum(f["contracts"] * f["drift"] for f in dr) / dcw if dcw else 0.0
        print("fills %d, %.0f contracts | capture/contract %+.4f | drift/contract %+.4f (n=%d, %.0f contracts)"
              % (len(allfills), cw, cap, drv, len(dr), dcw))
        byside = collections.defaultdict(lambda: [0.0, 0.0, 0])
        for f in dr:
            b = byside[f["side"]]
            b[0] += f["contracts"] * f["drift"]
            b[1] += f["contracts"]
            b[2] += 1
        for s, (v, c, k) in byside.items():
            print("   side %-3s fills %3d  contracts %8.0f  drift/contract %+.4f" % (s, k, c, v / c if c else 0))
        print("   (drift is mid movement AFTER the fill, signed for our side; negative = adverse)")
    else:
        print("no taker prints inside any program window for the measured tickers")

    # ---- D. verdict --------------------------------------------------------
    # Three arms, because "net of adverse selection" is ambiguous and the sign of the
    # drift decides more than the third decimal:
    #   reward only   -- the card's gross figure
    #   net(adverse)  -- reward + drift (the card's rule: subtract adverse selection)
    #   net(markout)  -- reward + capture + drift (a maker that also books its half-spread)
    gross_pch = (tot["payout_usd"] / ch) if ch else 0.0
    net_pch = ((tot["payout_usd"] + tot["drift_usd"]) / ch) if ch else 0.0
    net_full_pch = ((tot["payout_usd"] + tot["capture_usd"] + tot["drift_usd"]) / ch) if ch else 0.0
    hours_met = tot["counted_hours"] >= GATE_MIN_PROGRAM_HOURS
    pch_met = net_pch >= GATE_USD_PER_CONTRACT_HOUR
    verdict = "KEEP" if (hours_met and pch_met) else "CLOSE"
    best_ceiling = max([r["ceiling_pch"] for r in rows] or [0.0])
    print("\n--- D. VERDICT (pre-registered rule) ---")
    print("reward only          %+.7f $/contract-hour" % gross_pch)
    print("net of adverse drift %+.7f $/contract-hour   [gate >= %.4f]   counted hours %d [gate >= %d]"
          % (net_pch, GATE_USD_PER_CONTRACT_HOUR, tot["counted_hours"], GATE_MIN_PROGRAM_HOURS))
    print("net incl. capture    %+.7f $/contract-hour   (maker books its half-spread too)"
          % net_full_pch)
    print("ceiling of the best measured program $%.6f/contract-hour -> %s"
          % (best_ceiling,
             "capable of clearing the gate" if best_ceiling >= GATE_USD_PER_CONTRACT_HOUR
             else "STRUCTURALLY BELOW the gate even at 100%% share (%.1fx)"
                  % (GATE_USD_PER_CONTRACT_HOUR / best_ceiling if best_ceiling else float("inf"))))
    print("DECISION: %s" % verdict)

    summary = {
        "unit": args.unit, "placement": args.placement, "size_per_side": args.size or "target",
        "feed": {"rows": counts["rows"], "usable": counts["usable"],
                 "above_gate": len(above), "paged": payload.get("paged"),
                 "fetched_at": payload.get("fetched_at"), "ceiling_percentiles": pct,
                 "window_buckets": {k: {"n": len(v),
                                        "median": sorted(v)[len(v) // 2],
                                        "above_gate": sum(1 for x in v if x >= GATE_USD_PER_CONTRACT_HOUR)}
                                    for k, v in buckets.items()}},
        "capture_overlap": {"quote_tickers": len(qt), "quote_programs": len(q_over),
                            "quote_above_gate": len(q_above),
                            "tape_families": sorted(tf), "tape_above_gate": len(tape_above)},
        "measured": {"programs": len(rows), "counted_hours": tot["counted_hours"],
                     "window_hours": round(tot["window_hours"], 1),
                     "contract_hours": round(ch, 1),
                     "payout_usd": round(tot["payout_usd"], 4),
                     "capture_usd": round(tot["capture_usd"], 4),
                     "drift_usd": round(tot["drift_usd"], 4),
                     "settle_pnl_usd": round(tot["settle_pnl_usd"], 4) if settled_n else None,
                     "settled_programs": settled_n,
                     "gross_pch": gross_pch, "net_pch": net_pch, "net_full_pch": net_full_pch,
                     "rows": rows},
        "gate": {"pch": GATE_USD_PER_CONTRACT_HOUR, "min_hours": GATE_MIN_PROGRAM_HOURS,
                 "hours_met": hours_met, "pch_met": pch_met, "verdict": verdict},
    }
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--max-pages", type=int, default=200)
    ap.add_argument("--unit", default="centi-cents", choices=sorted(UNIT_DIVISOR))
    ap.add_argument("--size", type=float, default=0.0)
    ap.add_argument("--placement", default="improve", choices=["improve", "join"])
    args = ap.parse_args()
    if args.fetch:
        fetch_programs(args.max_pages)
    s = build(args)
    with open(OUT_JSON, "w") as f:
        json.dump(s, f, indent=1)
    print("\nwrote %s" % OUT_JSON)


if __name__ == "__main__":
    main()
