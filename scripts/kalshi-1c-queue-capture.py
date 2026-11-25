#!/usr/bin/env python3
"""Kalshi 1c-tail QUEUE-DEPTH capture (Lane B instrument, keyless).

WHY THIS EXISTS
---------------
The pre-registered maker read (data/kalshi-maker-read.json, drafts/kalshi-maker-read-20261029.md)
found exactly one gate cell that clears: passively selling YES at 0.01 on KXBTCD, +0.64c/contract
over 1,389 holdout fills. That number credits us on the FIRST qualifying >=100-contract print, and
it therefore assumes we are AT THE FRONT of the 1c queue. A print at 1c proves somebody was
resting there; it says nothing about how much size was resting AHEAD of a late-joining order.

Measured 2026-10-29 22:5xZ, live KXBTCD book, keyless:
    GET /markets/KXBTCD-26OCT2919-T90299.99/orderbook
      {"no_dollars": [["0.0100","139250.00"], ... , ["0.9900","39139.91"]]}
  i.e. 39,139.91 contracts resting as YES-ask at 1c on ONE strike; across the 123 open strikes
  quoting at 1c the median yes_ask_size was 12,572 contracts. The +0.64c is unreachable if that
  size is really in front of us, and fully reachable if it is MM size that pulls/refreshes before
  the lift. Only a forward capture can tell those two apart, because Kalshi publishes NO historical
  book and the v2 websocket refuses keyless clients:
      GET /trade-api/ws/v2 -> HTTP/1.1 401 Unauthorized
      {"code":"token_authentication_failure","message":"token authentication failure"}

WHAT THIS RECORDS (poll-only, ~2s cycle, no key)
-----------------------------------------------
1. SNAPSHOTS. Every cycle the family's open markets are listed in ONE call
   (GET /markets?series_ticker=KXBTCD&status=open&limit=1000, measured n=238, no cursor) and the
   resting size at the 1c YES ask is read off `yes_ask_size_fp` for every strike quoting 0.01.
   One snap row per cycle: {ts, m: {ticker: [ask_px, ask_sz, bid_px, bid_sz]}}.
2. EVENTS. Every new print on the venue tape with family KXBTCD, yes_price == 0.01,
   taker_side == yes and contracts >= --min-contracts (default 100) — the card's qualifying event.
   The tape is fetched newest-first (GET /markets/trades?limit=1000, measured 1000 prints = 5.5s of
   tape, so a 2s cycle never falls behind) and deduped by trade_id.
3. For each event: depth_before = size resting at 1c in the LAST SNAPSHOT at or before the print
   (this is "contracts ahead of a 100-lot order that joined at that snapshot"), the age of that
   snapshot, and an IMMEDIATE per-market orderbook call right after the print (depth_after_1c plus
   the whole post-print book), so the lift's effect on the level is measured, not inferred.

TWO KNOWN LIMITS, BOTH COUNTED, NEITHER HIDDEN
----------------------------------------------
* Poll lag. depth_before is stale by up to one cycle. `snap_age_ms` is stored on every event; the
  read-side script reports its distribution and drops events whose snapshot is older than
  --max-age-ms, so a fill probability computed here is never silently built on a stale book.
* Aggregation. Kalshi exposes ONE aggregate size per price level: a cancel AHEAD of us and a fill
  are indistinguishable in the book, and a cancel also ADVANCES our queue position. So the book
  gives a LOWER bound on fills (assume kills/cancels ahead = 0 -> every contract ahead of us must be
  lifted) and the tape gives the exact lift volume. Both are stored; the estimator reports the
  bound, not a point estimate dressed up as one.

OUTPUT (data/kalshi-1c-queue/)
------------------------------
  snaps-<date>.jsonl.gz      one row per cycle (full family book at 1c)
  events-<date>.jsonl        one row per qualifying print, with depth_before/after + post book
  coverage.jsonl             one row per run: cycles, span, requests, errors, events, tape lag

Duty cycle: the tape is a firehose (183-188 prints/s venue-wide on 2026-10-12) so this job must run
on a schedule for days to build a sample; a single run measures a WINDOW, not a rate. Every figure
derived from this file must be quoted with the coverage row that produced it.

Python 3.9 compatible (runs under the system python3). Read-only against the venue: GET only.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTDIR = ROOT / "data" / "kalshi-1c-queue"
STATE_FILE = OUTDIR / "state.json"
COVERAGE_FILE = OUTDIR / "coverage.jsonl"
API = "https://api.elections.kalshi.com/trade-api/v2"
UA = {"User-Agent": "copybot-kalshi-1c-queue/1.0"}
FAMILY = "KXBTCD"
CELL_LEVEL = "0.0100"  # yes ask / yes price, dollars, linear_cent structure
ID_MEMORY = 40000
_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})?$")

_stop = {"flag": False}


def _sigterm(_sig, _frm):
    _stop["flag"] = True


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_ts(s):
    """Kalshi emits BOTH '...123456Z' and '...4189+00:00' (4 fractional digits, which
    datetime.fromisoformat rejects on 3.9). Normalise to microseconds + explicit offset."""
    m = _TS_RE.match(s.strip())
    if not m:
        raise ValueError("unparseable Kalshi timestamp: %r" % (s,))
    date, clock, frac, off = m.groups()
    frac = (frac or "") + "000000"
    off = off or "+00:00"
    if off == "Z":
        off = "+00:00"
    return datetime.fromisoformat("%sT%s.%s%s" % (date, clock, frac[:6], off)).timestamp()


class Http:
    def __init__(self):
        self.n = 0
        self.err = 0

    def get(self, path):
        last = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(API + path, headers=UA)
                with urllib.request.urlopen(req, timeout=25) as fh:
                    body = json.load(fh)
                self.n += 1
                return body
            except urllib.error.HTTPError as exc:
                self.err += 1
                last = exc
                if exc.code in (429, 500, 502, 503, 504):
                    time.sleep(1.0 + 2.0 * attempt)
                    continue
                raise
            except Exception as exc:  # noqa: BLE001 - network flake, retry then raise
                self.err += 1
                last = exc
                time.sleep(0.5 + 2.0 * attempt)
        raise RuntimeError("GET %s failed after retries: %r" % (path, last))


def load_state():
    if STATE_FILE.exists():
        try:
            with STATE_FILE.open() as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001 - a corrupt state file must not stop a capture
            pass
    return {"seen_trade_ids": [], "last_cycle_ts": None}


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    with tmp.open("w") as fh:
        json.dump(state, fh)
    tmp.replace(STATE_FILE)


def append_jsonl(path, obj):
    with path.open("a") as fh:
        fh.write(json.dumps(obj, separators=(",", ":")) + "\n")


def append_gz_line(path, obj):
    with gzip.open(path, "at") as fh:
        fh.write(json.dumps(obj, separators=(",", ":")) + "\n")


def family_book(http):
    """One call -> {ticker: [ask_px, ask_sz, bid_px, bid_sz]} for every open KXBTCD market,
    plus the per-ticker metadata (close time, strike) that the read-side needs to place a burst
    in the market's life. Metadata is appended once per ticker, not once per cycle."""
    d = http.get("/markets?series_ticker=%s&status=open&limit=1000" % FAMILY)
    book = {}
    meta = {}
    for m in d.get("markets", []):
        tk = m["ticker"]
        book[tk] = [
            m.get("yes_ask_dollars"),
            m.get("yes_ask_size_fp"),
            m.get("yes_bid_dollars"),
            m.get("yes_bid_size_fp"),
        ]
        meta[tk] = {
            "close_time": m.get("close_time"),
            "open_time": m.get("open_time"),
            "status": m.get("status"),
            "strike": m.get("floor_strike"),
            "strike_type": m.get("strike_type"),
            "title": m.get("subtitle") or m.get("no_sub_title"),
            "event": m.get("event_ticker"),
        }
    return book, meta, len(d.get("markets", []))


def one_side(levels, want):
    for px, sz in levels:
        if px == want:
            return float(sz)
    return 0.0


def orderbook_1c(http, ticker):
    """Immediate per-market book after a print. YES ask at 1c == resting NO bid at 0.99;
    YES bid at 1c == a resting YES bid level 0.01 (the size our sell would cross).
    Both are read from the FRESH book, not the (sometimes one-tick-stale) markets list."""
    try:
        ob = http.get("/markets/%s/orderbook?depth=100" % urllib.parse.quote(ticker))
    except Exception as exc:  # noqa: BLE001 - an event is worth keeping even without the post book
        return {"error": repr(exc)[:200]}
    fp = ob.get("orderbook_fp") or ob.get("orderbook") or {}
    yes = fp.get("yes_dollars") or fp.get("yes") or []
    no = fp.get("no_dollars") or fp.get("no") or []
    return {
        "yes_ask_1c": one_side(no, "0.9900"),   # complement: NO bid 99c == YES ask 1c
        "yes_bid_1c": one_side(yes, "0.0100"),  # resting YES bid at 1c: our sell crosses it
        "no_levels": len(no),
        "yes_levels": len(yes),
        "best_yes_bid": yes[0] if yes else None,
        "best_no_bid": no[0] if no else None,
        "book_bytes": len(json.dumps(fp)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--interval", type=float, default=1.5, help="seconds between cycles")
    ap.add_argument("--min-contracts", type=float, default=0.0,
                    help="record every 1c lift at/above this size (the card's qualifying set is 100)")
    ap.add_argument("--book-min-contracts", type=float, default=100.0,
                    help="size at/above which an immediate per-market orderbook call follows the print")
    ap.add_argument("--max-age-ms", type=float, default=6000.0,
                    help="events whose prior snapshot is older than this are flagged stale")
    ap.add_argument("--outdir", default=str(OUTDIR))
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    global STATE_FILE
    STATE_FILE = outdir / "state.json"

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    http = Http()
    state = load_state()
    seen = list(state.get("seen_trade_ids") or [])
    seen_set = set(seen)

    started = time.time()
    deadline = started + args.minutes * 60.0
    snaps = []          # (ts_iso, ts_epoch, book)
    cycles = 0
    events_kept = 0
    big_events = 0
    stale = 0
    prints_scanned = 0
    lag_samples = []
    err_note = None
    meta_seen = set()

    while not _stop["flag"] and time.time() < deadline:
        t_cycle = now_iso()
        cycle_start = time.time()
        try:
            book, meta, n_markets = family_book(http)
            # trade tape AFTER the book so every print can be attributed to a snapshot <= its ts
            tape = http.get("/markets/trades?limit=1000")
        except Exception as exc:  # noqa: BLE001 - log and keep the run alive
            err_note = repr(exc)[:300]
            time.sleep(args.interval)
            continue

        day = t_cycle[:10]
        new_meta = {tk: mv for tk, mv in meta.items() if tk not in meta_seen}
        if new_meta:
            meta_seen.update(new_meta.keys())
            append_jsonl(outdir / ("markets-%s.jsonl" % day), {"ts": t_cycle, "m": new_meta})
        snaps.append((t_cycle, parse_ts(t_cycle), book))
        if len(snaps) > 400:
            snaps = snaps[-400:]
        append_gz_line(outdir / ("snaps-%s.jsonl.gz" % day), {"ts": t_cycle, "n": n_markets, "m": book})

        new_events = []
        for tr in tape.get("trades", []):
            tid = tr.get("trade_id")
            if tid in seen_set:
                continue
            seen.append(tid)
            seen_set.add(tid)
            prints_scanned += 1
            tk = tr.get("ticker") or ""
            if not tk.startswith(FAMILY):
                continue
            if str(tr.get("yes_price_dollars")) != CELL_LEVEL or tr.get("taker_side") != "yes":
                continue
            try:
                contracts = float(tr.get("count_fp") or 0)
            except ValueError:
                continue
            if contracts < args.min_contracts:
                continue
            new_events.append((tr, contracts))

        # attribute depth from the last snapshot at or before the print
        booked_this_cycle = set()
        for tr, contracts in new_events:
            ets = parse_ts(tr["created_time"])
            ref = None
            for ts_iso, ts_e, book in reversed(snaps):
                if ts_e <= ets:
                    ref = (ts_iso, ts_e, book)
                    break
            tk = tr["ticker"]
            row = {
                "event_ts": tr["created_time"],
                "observed_ts": t_cycle,
                "ticker": tk,
                "contracts": contracts,
                "yes_price": tr.get("yes_price_dollars"),
                "taker_side": tr.get("taker_side"),
                "taker_book_side": tr.get("taker_book_side"),
                "trade_id": tr.get("trade_id"),
                "snap_ts": None, "snap_age_ms": None,
                "ask_px": None, "ask_sz": None, "bid_px": None, "bid_sz": None,
                "pre": None,
            }
            if ref is not None:
                snap_iso, snap_e, book = ref
                row["snap_ts"] = snap_iso
                row["snap_age_ms"] = round((ets - snap_e) * 1000.0, 1)
                lv = book.get(tk)
                if lv:
                    row["ask_px"], row["ask_sz"], row["bid_px"], row["bid_sz"] = lv
                    try:
                        row["pre"] = float(lv[1]) if lv[1] not in (None, "") else None
                    except ValueError:
                        row["pre"] = None
                if row["snap_age_ms"] is not None:
                    lag_samples.append(row["snap_age_ms"])
                    if row["snap_age_ms"] > args.max_age_ms:
                        stale += 1
                        row["stale"] = True
            if contracts >= args.book_min_contracts and tk not in booked_this_cycle:
                # one book per ticker per cycle: a burst of prints must not stall the poll loop
                booked_this_cycle.add(tk)
                time.sleep(0.25)
                row["post"] = orderbook_1c(http, tk)
            append_jsonl(outdir / ("events-%s.jsonl" % day), row)
            events_kept += 1
            if contracts >= args.min_contracts and contracts >= 100.0:
                big_events += 1

        cycles += 1
        if len(seen) > ID_MEMORY:
            seen = seen[-ID_MEMORY:]
            seen_set = set(seen)
        if cycles % 20 == 0:
            save_state({"seen_trade_ids": seen, "last_cycle_ts": t_cycle})

        spent = time.time() - cycle_start
        if args.interval > spent:
            time.sleep(args.interval - spent)

    ended = time.time()
    lag_samples.sort()

    def q(p):
        if not lag_samples:
            return None
        return lag_samples[min(len(lag_samples) - 1, int(p * len(lag_samples)))]

    cov = {
        "run_started": datetime.fromtimestamp(started, timezone.utc).isoformat(),
        "run_ended": datetime.fromtimestamp(ended, timezone.utc).isoformat(),
        "wall_seconds": round(ended - started, 1),
        "minutes_requested": args.minutes,
        "cycles": cycles,
        "interval_s": args.interval,
        "requests": http.n,
        "request_errors": http.err,
        "requests_per_s": round(http.n / max(1e-9, ended - started), 3),
        "events_kept": events_kept,
        "events_ge100": big_events,
        "events_stale": stale,
        "max_age_ms_threshold": args.max_age_ms,
        "snap_age_ms_p50": q(0.50), "snap_age_ms_p90": q(0.90), "snap_age_ms_max": q(0.999),
        "prints_scanned_new": prints_scanned,
        "min_contracts_floor": args.min_contracts,
        "family": FAMILY,
        "cell_level": CELL_LEVEL,
        "last_error": err_note,
        "stopped_early": bool(_stop["flag"]),
    }
    with (outdir / "coverage.jsonl").open("a") as fh:
        fh.write(json.dumps(cov, separators=(",", ":")) + "\n")
    print(json.dumps(cov, indent=1))
    print("\nwrote ->", outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
