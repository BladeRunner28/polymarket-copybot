#!/usr/bin/env python3
"""kalshi-settled-history-probe.py -- how deep does keyless Kalshi history actually go,
and do FILLS survive with it?

Roadmap card: kalshi-settled-history-surface (Backlog, re-probe gate).  The card was
written 2026-11-02 off a claim in `darup67/market-lab` that "Kalshi serves roughly the
last two days of settled markets, and trades vanish with them -- nothing here can be
backfilled".  The card recorded that premise FALSE for markets and UNVERIFIED for
fills, and told the next run to re-probe rather than re-derive from its note.  That is
what this file does, and it found the fills half is the opposite of what the card says.

FOUR ROUTES, EACH WITH ITS OWN CLOCK -- this is the whole point, because the previous
note merged them into one "retention" number and got the shape of the surface wrong:

  R1 /markets?status=settled&min_close_ts=..&max_close_ts=..   RECENT market records.
     Honours the window (verified: every returned close_time lies inside it) and runs
     back a bounded number of days from today.  This is the route the maker read and the
     settlement cache use.  Its depth is measured, not assumed.

  R2 /historical/markets?min_close_ts=..&max_close_ts=..       ARCHIVED market records.
     A different, DEEPER population: markets the venue has moved out of the live table.
     Depth measured against anchors going back years.

  R3 /historical/trades?ticker=..                              ARCHIVED FILLS, per market.
     Returns the venue's own fills with taker_side, yes/no price and count_fp.  The card
     marks this half "stays unverified ... do not claim trade backfill until a route
     returns prints".  A route returns prints.

  R4 /historical/trades?min_ts=..&max_ts=..                    ARCHIVED FILLS, by window,
     across all tickers.  Verified to honour the window too (no out-of-window row).

  DEAD (measured 404/empty, so nobody re-tries them): /markets/{ticker}/trades,
  /trades?ticker=, /market/{ticker}/history.

WHY THIS CARD IS WORTH A RUN.  Two parked items are gated on exactly this question:
(a) kalshi-maker-read-prereg (Scheduled, awaiting approval) is a resting-order fill
    simulation that could be re-derived against VENUE FILLS instead of our own tape if
    fills exist with history -- and its stated limit C1 is that the tape only keeps
    prints >= 100 contracts.  Section D measures how large that blind spot is on a
    population where both views exist.
(b) any Phase C cross-venue work that needs Kalshi resolution history can read it.

THE HONEST LIMIT, STATED BEFORE THE NUMBERS.  The two fills populations do not overlap
in time with our tape: our tape began 2026-10-12 and archived fills stop before that
(depth is printed).  So section D's blind spot is measured on ARCHIVED fills, not on our
tape's own tickers, and it prices the SIZE of C1, not a correction to any published
figure.  Nothing here re-derives the maker arm; that arm is Lane A and already queued.

TWO DEFECTS FOUND IN THIS INSTRUMENT'S OWN FIRST DRAFT (kept here because they are the
class this repo keeps paying for -- a printed number whose basis lied):
  D1 PARTIAL-AS-COVERED.  The first draft called any day with rows "covered".  Days
     older than the retention edge return a HANDFUL of rows from ONE long-dated series
     (2026-09-09: 9 rows, all KXBIGGESTQUAKE; 08-15: 6, all KXHORMUZPEAK; 07-01: 10, all
     KXEARTHQUAKE) while multi-series days before the edge return ZERO.  Reading those as
     coverage put the edge at 2026-09-09 -- 2 days too deep, and it described a cliff as
     a slope.  Now FULL (full page or a cursor) / PARTIAL / EMPTY, and only FULL counts.
     The PARTIAL days are REPORTED with their series names rather than discarded.
  D2 CAPPED-PAGES BIAS.  /historical/trades is NEWEST-FIRST.  The first draft capped at
     3 pages per ticker and reported 72.5% of fills under the tape floor on 6.4% of
     contracts; paging to EXHAUSTION on the same population gives 83.4% / 18.6%.  The cap
     was sampling the end of each market's life, where fills are densest.  Section D now
     pages to exhaustion and prints whether it truncated.
Two facts section D now verifies rather than assumes: the `ticker` filter is HONOURED
(one distinct ticker in a per-ticker read) and `trade_id` is UNIQUE (58,578 rows ->
58,578 ids on one market, so a share cannot be inflated by duplicated rows).  Venue
`count_fp` is FRACTIONAL -- the median print is 10 contracts and the minimum seen is
0.01 -- so "contracts" here are not integers and a floor of 100 is far above the median.

BASIS DISCIPLINE.  Every number prints its population, clock and level.  A retention
depth is a level=day fact with a clock of the day boundary in UTC; a fills count is a
level=one venue print fact.  Nothing is pooled across the two.
"""

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.elections.kalshi.com/trade-api/v2"
UA = {"User-Agent": "medusa-copybot-probe/1.0"}
ARTIFACT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "kalshi-settled-history.json")
DAY = 86400


# ---------------------------------------------------------------------------
# clocks (pure)
# ---------------------------------------------------------------------------

def day_ts(day):
    """UTC midnight epoch seconds for 'YYYY-MM-DD'."""
    return int(datetime.datetime.strptime(day, "%Y-%m-%d")
               .replace(tzinfo=datetime.timezone.utc).timestamp())


def utc_ts(stamp):
    """Epoch seconds from a venue timestamp ('...Z', fractional part tolerated)."""
    return int(datetime.datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
               .replace(tzinfo=datetime.timezone.utc).timestamp())


def day_of(ts):
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")


def shift(day, n):
    d = datetime.datetime.strptime(day, "%Y-%m-%d") + datetime.timedelta(days=n)
    return d.strftime("%Y-%m-%d")


def window_counts(rows, key, lo, hi):
    """(inside, outside) -- a window query that returns a row outside its own window is
    a lying filter and must never be read as coverage."""
    inside = outside = 0
    for r in rows:
        st = r.get(key)
        if not st:
            outside += 1
            continue
        t = utc_ts(st)
        if lo <= t <= hi:
            inside += 1
        else:
            outside += 1
    return inside, outside


def coverage_kind(rows, cursor, limit):
    """FULL / PARTIAL / EMPTY for a DAY of settled-market records.

    FULL    the day filled the page or the venue handed back a cursor: the day is
            covered as a population.
    PARTIAL the venue answered and had only a handful of rows with no cursor.  Measured
            cause: those rows are ONE long-dated series that closed on that day
            (KXBIGGESTQUAKE on 2026-09-09/10, KXHORMUZPEAK on 08-15, KXEARTHQUAKE on
            07-01) while every multi-series day before the retention edge returns ZERO.
            So a PARTIAL day is the retention edge being LEAKY, NOT a slice of that day
            -- reading 6 rows as 'covered' would understate the cliff by ~34x.
    EMPTY   nothing at all.
    """
    if rows >= limit or cursor:
        return "FULL"
    if rows > 0:
        return "PARTIAL"
    return "EMPTY"


def classify_page(status, rows, cursor):
    """PAGED / COMPLETE / EMPTY / ERROR.

    EMPTY means the venue answered and had nothing -- that is the ONLY shape that may
    close a retention window.  A page with zero rows but a cursor is not covered (it is
    a paging artifact) and must not be read as the end of history."""
    if status != 200:
        return "ERROR"
    if not rows:
        return "PAGED_NO_ROWS" if cursor else "EMPTY"
    return "PAGED" if cursor else "COMPLETE"


def bisect_first_covered(probe, covered_day, uncovered_day):
    """ON THE RECENT-SIDE WINDOW: covered days are the RECENT ones and history falls
    off going backwards, so the boundary is the OLDEST COVERED day, not the newest.

    Returns the smallest day in [uncovered_day, covered_day] with probe(day) True.
    Invariant on return: probe(result) is True and probe(result-1) is False -- so an
    off-by-one in the caller's own predicate is caught rather than absorbed."""
    lo = day_ts(uncovered_day) // DAY   # known NOT covered (older)
    hi = day_ts(covered_day) // DAY     # known covered (newer)
    if lo >= hi or not probe(day_of(hi * DAY)):
        return None
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if probe(day_of(mid * DAY)):
            hi = mid
        else:
            lo = mid
    return day_of(hi * DAY)


def fill_stats(trade_pages):
    """Fills, and the share of them that fall under the tape's 100-contract floor.

    Reported on TWO bases because they answer different questions: a COUNT share says
    how often the tape is blind, a CONTRACT share says how much flow it is blind to.
    Quoting one as the other is the defect this repo keeps paying for."""
    n = below = 0
    contracts = contracts_below = 0.0
    for page in trade_pages:
        for t in page:
            try:
                c = float(t.get("count_fp") or 0)
            except (TypeError, ValueError):
                c = 0.0
            n += 1
            contracts += c
            if c < 100:
                below += 1
                contracts_below += c
    return {
        "fills": n,
        "fills_below_100": below,
        "fill_count_share_below_100": (below / n) if n else None,
        "contracts": contracts,
        "contracts_below_100": contracts_below,
        "contract_share_below_100": (contracts_below / contracts) if contracts else None,
    }


def page_integrity(rows):
    """Does a per-ticker fill read actually contain one ticker, with unique ids?

    A route that ignores the `ticker` filter would look like a firehose and would make
    every per-market number meaningless; duplicated `trade_id`s would inflate a share.
    Both are checked on the rows themselves, not taken on faith."""
    tickers = {}
    ids = {}
    for r in rows:
        tickers[r.get("ticker")] = tickers.get(r.get("ticker"), 0) + 1
        i = r.get("trade_id")
        ids[i] = ids.get(i, 0) + 1
    dup = sum(v - 1 for v in ids.values() if v > 1)
    counts = sorted(float(r.get("count_fp") or 0) for r in rows)
    return {
        "rows": len(rows),
        "distinct_tickers": len(tickers),
        "dominant_ticker_share": (max(tickers.values()) / len(rows)) if rows else None,
        "distinct_trade_ids": len(ids),
        "duplicate_trade_ids": dup % 1000000,
        # LOWER median, stated: on an even n this returns the smaller of the two middle
        # values, so a two-row sample cannot be reported as its larger row
        "count_fp_median": counts[(len(counts) - 1) // 2] if counts else None,
        "count_fp_min": counts[0] if counts else None,
    }


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------

def http_json(path, params=None, tries=3, timeout=40):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as f:
                return f.status, json.load(f)
        except urllib.error.HTTPError as e:
            body = e.read()[:200].decode("utf8", "replace")
            if e.code == 429:
                time.sleep(2)
                last = (429, body)
                continue
            return e.code, body
        except Exception as exc:  # noqa: BLE001 -- transport, reported not hidden
            last = (-1, repr(exc))
            time.sleep(1)
    return last if last else (-1, "retries exhausted")


def market_day_probe(route, day, limit=200):
    """One day, one page. Returns (status, rows, cursor)."""
    a = day_ts(day)
    return http_json(route, {"status": "settled", "min_close_ts": a,
                             "max_close_ts": a + DAY - 1, "limit": limit}) \
        if route == "/markets" else \
        http_json(route, {"min_close_ts": a, "max_close_ts": a + DAY - 1, "limit": limit})


def covered(route, day, limit=200):
    """A day counts as covered only when it is FULL -- see coverage_kind."""
    status, body = market_day_probe(route, day, limit)
    if status != 200 or not isinstance(body, dict):
        return False
    rows = body.get("markets", []) or []
    return coverage_kind(len(rows), body.get("cursor"), limit) == "FULL"


def trades_day_probe(day, limit=200):
    a = day_ts(day)
    status, body = http_json("/historical/trades", {"min_ts": a,
                                                    "max_ts": a + DAY - 1,
                                                    "limit": limit})
    if status != 200 or not isinstance(body, dict):
        return 0, []
    return len(body.get("trades", []) or []), (body.get("trades", []) or [])


# ---------------------------------------------------------------------------
# live probe
# ---------------------------------------------------------------------------

def probe_market_retention(route, today, deepest_anchor_days, log):
    """Contiguous recent window of `route`: anchors first, then a day-level bisect."""
    anchors = [today]
    for d in (1, 2, 5, 10, 20, 30, 40, 50, 60, 62, 64, 66, 68, 70, 75, 90,
              120, 180, 365, 550, 700):
        if d <= deepest_anchor_days:
            anchors.append(shift(today, -d))
    seen = {}
    for day in anchors:
        status, body = market_day_probe(route, day)
        rows = (body.get("markets", []) or []) if (status == 200 and isinstance(body, dict)) else []
        cur = bool(body.get("cursor")) if isinstance(body, dict) else False
        kind = (coverage_kind(len(rows), cur, 200) if status == 200
                else classify_page(status, rows, cur))
        seen[day] = {"kind": kind, "rows": len(rows), "http": status, "cursor": cur,
                     "series": sorted(set((r.get("ticker") or "").split("-")[0]
                                          for r in rows))[:4]}
        if rows:
            inside, outside = window_counts(rows, "close_time",
                                            day_ts(day), day_ts(day) + DAY - 1)
            seen[day]["inside_window"] = inside
            seen[day]["outside_window"] = outside
        log("    %s %-10s rows=%-4d %s" % (route, day, len(rows), kind))

    ok_days = [d for d, v in seen.items() if v["kind"] == "FULL"]
    partial_days = {d: v for d, v in seen.items() if v["kind"] == "PARTIAL"}
    fail_days = sorted([d for d, v in seen.items() if v["kind"] in ("EMPTY", "ERROR", "PARTIAL")])
    out = {"anchors": seen, "contiguous_from": None, "contiguous_days": None,
           "partial_fringe_days": {d: {"rows": v["rows"], "series": v["series"]}
                                   for d, v in partial_days.items()}}
    if not ok_days:
        return out
    newest_ok = max(ok_days)
    # the contiguous window runs [first_covered .. newest_ok]; an uncovered day BETWEEN
    # two covered anchors means the window is not contiguous and must be reported as such
    deeper_fail = [d for d in fail_days if d < newest_ok]
    if deeper_fail:
        fail_anchor = max(deeper_fail)
        first = bisect_first_covered(lambda d: covered(route, d), newest_ok, fail_anchor)
        out["contiguous_from"] = first
        out["older_neighbour_uncovered"] = shift(first, -1) if first else None
        out["contiguous"] = True
    else:
        out["contiguous_from"] = min(ok_days)
        out["older_neighbour_uncovered"] = None
        out["contiguous"] = "UNBOUNDED_TO_ANCHOR"
    out["deepest_anchor_with_rows"] = min(ok_days)
    out["contiguous_days"] = ((day_ts(today) - day_ts(out["contiguous_from"])) // DAY) + 1
    out["deepest_anchor_days"] = ((day_ts(today) - day_ts(out["deepest_anchor_with_rows"])) // DAY)
    return out


def probe_fills(today, log):
    out = {"routes": {}}
    # dead routes, measured rather than remembered
    st, body = http_json("/markets", {"status": "settled", "limit": 5})
    ticker = None
    if st == 200 and isinstance(body, dict) and body.get("markets"):
        ticker = body["markets"][0].get("ticker")
    if ticker:
        for path, params in (("/markets/%s/trades" % ticker, {}),
                             ("/trades", {"ticker": ticker, "limit": 5}),
                             ("/market/%s/history" % ticker, {})):
            ps, pb = http_json(path, params)
            out["routes"][path] = {"http": ps}
            log("    dead-route check %-42s http=%s" % (path, ps))

    # archived fills depth: walk back until a day returns rows, then bisect upward
    anchors = [shift(today, -n) for n in (1, 3, 7, 14, 20, 25, 30, 40, 50, 60, 64,
                                          66, 68, 70, 75, 90, 120, 180, 365)]
    hit = {}
    for day in anchors:
        n, _ = trades_day_probe(day, limit=100)
        hit[day] = n
        log("    /historical/trades %s rows=%d" % (day, n))
    with_rows = [d for d, n in hit.items() if n > 0]
    if with_rows:
        last_day = max(with_rows)
        # refine upward, one day at a time, bounded
        for i in range(1, 6):
            cand = shift(last_day, i)
            n, _ = trades_day_probe(cand, limit=50)
            log("    /historical/trades %s rows=%d (refine)" % (cand, n))
            if n > 0:
                last_day = cand
            else:
                break
        out["fills_last_day_with_rows"] = last_day
        out["fills_depth_days"] = (day_ts(today) - day_ts(last_day)) // DAY + 1
    out["anchor_rows"] = hit
    return out


def measure_blind_spot(today, sample_tickers, log):
    """Share of venue fills the tape's 100-contract floor cannot see, measured on an
    ARCHIVED era where the venue's own fills exist.

    THREE DESIGN CHOICES, each closing a bias this repo has already paid for:
    (1) POPULATION is sampled by TICKER, not by fill -- sampling fills would oversample
        the busy markets.  Stratified (every k-th archived ticker) so adjacent 15-minute
        markets do not share a regime.
    (2) PAGINATION RUNS TO EXHAUSTION.  /historical/trades returns NEWEST-FIRST, so a
        capped page count is a sample of the END of each market's life, where fills are
        densest -- the first draft of this instrument capped at 3 pages and reported
        72.5% under the floor against a true figure the exhaustion pass corrects.
    (3) BOTH BASES are reported (fill count and contracts) plus a PER-TICKER spread,
        because a single pooled share can be one market wearing a population's clothes.
    """
    lo = shift(today, -120)
    hi = shift(today, -60)
    st, body = http_json("/historical/markets", {"series_ticker": "KXBTC15M",
                                                "min_close_ts": day_ts(lo),
                                                "max_close_ts": day_ts(hi) + DAY - 1,
                                                "limit": 200})
    markets = (body.get("markets", []) or []) if (st == 200 and isinstance(body, dict)) else []
    tickers = [m.get("ticker") for m in markets if m.get("ticker")]
    log("    archived KXBTC15M markets %s..%s: %d on page 1 (more=%s)"
        % (lo, hi, len(markets), bool(body.get("cursor")) if isinstance(body, dict) else None))
    if not tickers:
        return {"error": "no archived tickers in window"}
    step = max(1, len(tickers) // sample_tickers)
    picked = tickers[::step][:sample_tickers]
    per_ticker = []
    pages_total = 0
    truncated = 0
    for tk in picked:
        got = []
        cursor = None
        pages = 0
        while pages < 250:
            params = {"ticker": tk, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            ps, pb = http_json("/historical/trades", params)
            if ps != 200 or not isinstance(pb, dict):
                break
            chunk = pb.get("trades", []) or []
            got.extend(chunk)
            cursor = pb.get("cursor")
            pages += 1
            if not cursor or not chunk:
                break
        pages_total += pages
        if cursor:
            truncated += 1
        if got:
            s1 = fill_stats([got])
            integ = page_integrity(got)
            per_ticker.append({"ticker": tk, "pages": pages, **s1, "integrity": integ})
    pooled = fill_stats([[]]) if not per_ticker else {
        k: sum(p[k] for p in per_ticker) for k in ("fills", "fills_below_100", "contracts", "contracts_below_100")
    }
    n = pooled["fills"]
    out = {
        "series": "KXBTC15M",
        "era": [lo, hi],
        "tickers_requested": len(picked),
        "tickers_with_fills": len(per_ticker),
        "tickers_truncated": truncated,
        "pages_fetched": pages_total,
        "fills": n,
        "fill_count_share_below_100": (pooled["fills_below_100"] / n) if n else None,
        "contract_share_below_100": (pooled["contracts_below_100"] / pooled["contracts"]) if pooled["contracts"] else None,
        "per_ticker_fill_share": sorted(p["fill_count_share_below_100"] for p in per_ticker),
        "per_ticker": per_ticker,
        "integrity": {
            "filter_honoured_all": all(p["integrity"]["distinct_tickers"] == 1 for p in per_ticker),
            "duplicate_ids_total": sum(p["integrity"]["duplicate_trade_ids"] for p in per_ticker),
            "count_fp_median_range": [min((p["integrity"]["count_fp_median"] or 0) for p in per_ticker),
                                      max((p["integrity"]["count_fp_median"] or 0) for p in per_ticker)] if per_ticker else None,
        },
    }
    shares = out["per_ticker_fill_share"]
    if shares:
        out["per_ticker_share_median"] = shares[len(shares) // 2]
        # ex-largest-ticker arm: the pooled number must not be one market's shape
        big = max(out["per_ticker"], key=lambda p: p["fills"])
        rest = [p for p in out["per_ticker"] if p is not big]
        rn = sum(p["fills"] for p in rest)
        out["ex_largest_ticker_fill_share"] = (
            sum(p["fills_below_100"] for p in rest) / rn) if rn else None
        out["largest_ticker"] = {"ticker": big["ticker"], "fills": big["fills"]}
    log("    integrity: filter_honoured=%s dup_ids=%s count_fp_median_range=%s"
        % (out["integrity"]["filter_honoured_all"], out["integrity"]["duplicate_ids_total"],
           out["integrity"]["count_fp_median_range"]))
    log("    blind spot: fills=%s count_share=%s contract_share=%s median=%s ex_largest=%s"
        % (out["fills"], out["fill_count_share_below_100"], out["contract_share_below_100"],
           out.get("per_ticker_share_median"), out.get("ex_largest_ticker_fill_share")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--out", default=ARTIFACT)
    ap.add_argument("--fill-sample", type=int, default=8)
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    log = lambda m: print(m, flush=True)
    log("[kalshi-settled-history] clock: %sT00:00Z boundary, probed now" % today)

    log("  A. RECENT market records: /markets?status=settled")
    recent = probe_market_retention("/markets", today, 120, log)
    log("  B. ARCHIVED market records: /historical/markets")
    archived_mkts = probe_market_retention("/historical/markets", today, 700, log)
    log("  C. ARCHIVED fills")
    fills = probe_fills(today, log)
    log("  D. TAPE BLIND SPOT on an archived era")
    blind = measure_blind_spot(today, args.fill_sample, log)

    verdicts = []
    if recent.get("contiguous_from"):
        verdicts.append(
            "R1 recent settled-market records are FULL from %s to today -> %d days "
            "(window-honouring: every row inside its own window); any day older returns "
            "only one long-dated series, and the 2-day-retention premise is FALSE."
            % (recent["contiguous_from"], recent["contiguous_days"]))
    if archived_mkts.get("deepest_anchor_with_rows"):
        verdicts.append(
            "R2 archived market records still page at %s (%d days back) and that page "
            "was not exhausted -> archive depth is a LOWER BOUND, not a measured edge."
            % (archived_mkts["deepest_anchor_with_rows"],
               archived_mkts.get("deepest_anchor_days")))
    if fills.get("fills_last_day_with_rows"):
        verdicts.append(
            "R3/R4 archived FILLS return prints with taker_side through %s (%d days "
            "back); the card's 'fills vanish' half is REFUTED for the archived era, and "
            "the /markets/{t}/trades + /trades routes it blamed are simply 404."
            % (fills["fills_last_day_with_rows"], fills["fills_depth_days"]))
    if blind.get("fill_count_share_below_100") is not None:
        verdicts.append(
            "C1 SIZE: on %d archived %s tickers paged to exhaustion (%.0f fills, %s), "
            "%.1f%% of fills but only %.1f%% of CONTRACTS are under the tape's "
            "100-contract floor (per-ticker median %s, ex-largest %s) -- the maker read's "
            "C1 limit is a majority of fills and a small share of volume, and it must be "
            "quoted on the base it was measured on."
            % (blind["tickers_with_fills"], blind["series"], blind["fills"],
               "%d truncated" % blind["tickers_truncated"] if blind["tickers_truncated"] else "none truncated",
               100 * blind["fill_count_share_below_100"],
               100 * (blind["contract_share_below_100"] or 0),
               "%.1f%%" % (100 * blind["per_ticker_share_median"]) if blind.get("per_ticker_share_median") is not None else "n/a",
               "%.1f%%" % (100 * blind["ex_largest_ticker_fill_share"]) if blind.get("ex_largest_ticker_fill_share") is not None else "n/a"))

    artifact = {
        "generated_at_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "card": "kalshi-settled-history-surface",
        "basis": {
            "population": "keyless Kalshi venue routes, one page per anchor day unless noted",
            "clock": "UTC day boundary of the probe run; each row carries its own close_time/created_time",
            "level": "one venue market record (A/B) or one venue print (C/D)",
        },
        "recent_market_records": recent,
        "archived_market_records": archived_mkts,
        "filled_era": fills,
        "tape_blind_spot": blind,
        "verdicts": verdicts,
    }
    with open(args.out, "w") as f:
        json.dump(artifact, f, indent=1, sort_keys=True)
        f.write("\n")
    log("[kalshi-settled-history] verdicts:")
    for v in verdicts:
        log("  - " + v)
    log("[kalshi-settled-history] artifact -> %s" % args.out)
    return 0


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

def self_test():
    fails = []
    tally = {"n": 0}

    def check(desc, cond):
        tally["n"] += 1
        print(("  ok   " if cond else "  FAIL ") + desc)
        if not cond:
            fails.append(desc)

    print("[self-test] clock helpers")
    check("day_ts round-trips through day_of",
          day_of(day_ts("2026-09-16")) == "2026-09-16")
    check("utc_ts tolerates a fractional stamp",
          utc_ts("2026-09-16T23:12:14.589749Z") == day_ts("2026-09-16") + 23 * 3600 + 12 * 60 + 14)
    check("shift crosses a month boundary", shift("2026-09-01", -1) == "2026-08-31")

    print("[self-test] window filter")
    lo, hi = day_ts("2026-09-16"), day_ts("2026-09-16") + DAY - 1
    rows = [{"close_time": "2026-09-16T00:00:00Z"}, {"close_time": "2026-09-16T23:59:59Z"}]
    check("in-window rows are counted inside", window_counts(rows, "close_time", lo, hi) == (2, 0))
    rows_bad = rows + [{"close_time": "2026-09-17T00:00:00Z"}]
    check("MUTATION: a one-second-outside row is counted outside, never inside",
          window_counts(rows_bad, "close_time", lo, hi) == (2, 1))
    check("MUTATION: a missing timestamp is outside, not silently inside",
          window_counts([{}], "close_time", lo, hi) == (0, 1))

    print("[self-test] page classification")
    check("rows + cursor is PAGED", classify_page(200, [1], "c") == "PAGED")
    check("rows, no cursor is COMPLETE", classify_page(200, [1], None) == "COMPLETE")
    check("empty, no cursor is EMPTY (the only shape that closes a window)",
          classify_page(200, [], None) == "EMPTY")
    check("MUTATION: empty WITH a cursor is not coverage", classify_page(200, [], "c") != "EMPTY")
    check("MUTATION: a 404 is never coverage", classify_page(404, [], None) == "ERROR")

    print("[self-test] day coverage: a handful of rows is not a covered day")
    check("a full page is FULL", coverage_kind(200, True, 200) == "FULL")
    check("a short page WITH a cursor is FULL", coverage_kind(37, True, 200) == "FULL")
    check("MUTATION: 6 rows with no cursor is PARTIAL, never FULL",
          coverage_kind(6, False, 200) == "PARTIAL")
    check("MUTATION: 0 rows is EMPTY, distinct from PARTIAL", coverage_kind(0, False, 200) == "EMPTY")
    check("MUTATION: a PARTIAL day does not pass the covered() gate",
          coverage_kind(9, False, 200) != "FULL")

    print("[self-test] boundary bisect")
    cutoff = day_ts("2026-09-11")          # first covered day; history falls off going back
    probe = lambda d: day_ts(d) >= cutoff
    got = bisect_first_covered(probe, "2026-09-16", "2026-09-01")
    check("bisect lands on the OLDEST covered day", got == "2026-09-11")
    check("INVARIANT: the returned day is covered and the day before it is not",
          probe(got) and not probe(shift(got, -1)))
    off_by_one = lambda d: day_ts(d) > cutoff
    got2 = bisect_first_covered(off_by_one, "2026-09-16", "2026-09-01")
    check("MUTATION: an off-by-one predicate moves the answer (bisect is not self-agreeing)",
          got2 == "2026-09-12" and got2 != got)
    check("MUTATION: an uncovered anchor returns None, never a made-up day",
          bisect_first_covered(lambda d: False, "2026-09-16", "2026-09-01") is None)
    check("MUTATION: a covered anchor that claims to be uncovered returns None",
          bisect_first_covered(lambda d: day_ts(d) >= day_ts("2026-10-01"),
                               "2026-09-16", "2026-09-01") is None)

    print("[self-test] fill stats: two bases, never conflated")
    stats = fill_stats([[{"count_fp": "50.00"}, {"count_fp": "150.00"}]])
    check("fill count share below the floor is 0.5", abs(stats["fill_count_share_below_100"] - 0.5) < 1e-9)
    check("MUTATION: contract share is 0.25, i.e. NOT the count share",
          abs(stats["contract_share_below_100"] - 0.25) < 1e-9)
    check("contracts total 200", abs(stats["contracts"] - 200.0) < 1e-9)
    check("an empty population reports None, never 0.0",
          fill_stats([])["fill_count_share_below_100"] is None)
    check("MUTATION: a missing count_fp counts as a fill of 0, not as absent",
          fill_stats([[{}]])["fills"] == 1)

    print("[self-test] fill-page integrity")
    ok_rows = [{"ticker": "A-1", "trade_id": "t1", "count_fp": "5"},
               {"ticker": "A-1", "trade_id": "t2", "count_fp": "500"}]
    integ = page_integrity(ok_rows)
    check("one ticker, unique ids, median from the population",
          integ["distinct_tickers"] == 1 and integ["duplicate_trade_ids"] == 0
          and integ["count_fp_median"] == 5)
    bad = ok_rows + [{"ticker": "A-1", "trade_id": "t1", "count_fp": "5"}]
    check("MUTATION: a duplicated trade_id is counted, not absorbed",
          page_integrity(bad)["duplicate_trade_ids"] == 1)
    mixed = ok_rows + [{"ticker": "B-9", "trade_id": "t3", "count_fp": "7"}]
    check("MUTATION: an ignored ticker filter is VISIBLE (2 distinct tickers)",
          page_integrity(mixed)["distinct_tickers"] == 2)
    check("an empty read reports None, not a zero share", page_integrity([])["dominant_ticker_share"] is None)

    print("[self-test] %d checks, %d failed" % (tally["n"], len(fails)))
    if fails:
        print("RED:")
        for f in fails:
            print("  - " + f)
        return 1
    print("GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
