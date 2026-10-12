#!/usr/bin/env python3
"""Kalshi keyless venue-tape capture (complementary-Kalshi workstream, option A).

WHY THIS EXISTS
---------------
Kalshi's public trade tape is keyless but it is a ROLLING window (verified
2026-10-12: data exists for 2026-08-15, nothing for 2026-07-25 — ~8 weeks). Any
study of Kalshi's microstructure loses history permanently unless it is captured
forward, so this job runs on a schedule and appends what it sees.

WHAT IT CAPTURES
----------------
1. venue-wide tape walk (`/markets/trades`, newest first, cursor pagination),
   filtered LOCALLY to the families in data/kalshi-tape-families.json;
2. per-minute BARS per ticker for those families (n, contracts, vwap, last,
   min/max, taker-side split, big-print contracts) — the artifact a maker study
   works from;
3. every print at/above --min-contracts as a VERBATIM row, gzipped per day
   (data/kalshi-tape/prints-<date>.jsonl.gz);
4. one COVERAGE row per run: pages/bytes, prints scanned vs kept, the captured
   window, `cap_hit`, and the unfilled hole since the previous run.

DUTY CYCLE (the sampling rule — quote it with any figure derived from this file)
--------------------------------------------------------------------------------
The venue tape is a firehose: measured 2026-10-12 at 183-188 prints/s venue-wide
(a 1,000-print page is ~300 KB). A run also takes roughly as long in WALL time as
the span it captures (paging is slower than the tape), so coverage is bounded by
(run wall time) / (cron interval) and cannot reach 100% with one process. POLICY
(user-overridden 2026-10-12): maximise coverage — the job runs every 15 minutes
with a 14-minute window (~93% duty, ~4-5 GB/day of transfer), leaving ~1 minute of
slack per tick so the next tick's lock is never skipped.

Because the covered span is now within a minute of the interval, windows can MEET
at the minute boundary, and bars are appended per run — so appending blindly would
emit duplicate (ticker, minute) rows. The dedupe guard below (skip minutes already
written for a ticker, per the ticker state) is what makes near-continuous coverage
safe: it is structural, not schedule-dependent. It is counted in every coverage row
as `bars_deduped`; a boundary minute whose bar was already written is dropped, so a
boundary bar can be very slightly truncated — `bars_deduped` is the size of that
effect and is never hidden.

coverage.jsonl records every window and the hole before it, so coverage is
MEASURED, never assumed. Never present a bar total as venue volume without the
coverage row beside it.

Python 3.9 compatible (runs under the system python3).
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTDIR = ROOT / "data" / "kalshi-tape"
FAMILIES_FILE = ROOT / "data" / "kalshi-tape-families.json"
STATE_FILE = OUTDIR / "state.json"
BARS_FILE = OUTDIR / "bars.jsonl"
COVERAGE_FILE = OUTDIR / "coverage.jsonl"
API = "https://api.elections.kalshi.com/trade-api/v2"
UA = {"User-Agent": "copybot-kalshi-tape/1.0"}
PAGE_LIMIT = 1000
ID_MEMORY = 20000  # trade_ids remembered for dedupe (FIFO)


def load_families():
    with FAMILIES_FILE.open() as fh:
        return set(json.load(fh)["families"].keys())


def load_state():
    if STATE_FILE.exists():
        try:
            with STATE_FILE.open() as fh:
                return json.load(fh)
        except Exception:
            pass
    return {"tickers": {}, "ids": [], "last_run": None}


def save_state(state):
    OUTDIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with tmp.open("w") as fh:
        json.dump(state, fh, indent=1)
    tmp.replace(STATE_FILE)


def get_json(url, timeout=30, retries=3):
    """Returns (status, nbytes, payload). Never fabricates: raises on hard failure."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return resp.status, len(raw), json.loads(raw.decode())
        except urllib.error.HTTPError as exc:
            last = "HTTP %s" % exc.code
            if exc.code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            break
        except Exception as exc:  # network/timeout/parse
            last = str(exc)[:160]
            time.sleep(1.0)
    raise RuntimeError("kalshi tape request failed: %s (%s)" % (url, last))


def parse_iso(iso_ts):
    """Python 3.9 fromisoformat rejects 4/5-digit fractional seconds; normalise first."""
    text = (iso_ts or "").replace("Z", "+00:00")
    if "." in text:
        head, rest = text.split(".", 1)
        frac = ""
        idx = 0
        while idx < len(rest) and rest[idx].isdigit():
            frac += rest[idx]
            idx += 1
        text = head + "." + (frac + "000000")[:6] + rest[idx:]
    return datetime.fromisoformat(text)


def floor_minute(iso_ts):
    return parse_iso(iso_ts).replace(second=0, microsecond=0)


def fnum(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def blank_bar():
    return {
        "n": 0,
        "contracts": 0.0,
        "yes_notional": 0.0,
        "last_yes": None,
        "pmin": None,
        "pmax": None,
        "taker_yes": 0,
        "taker_no": 0,
        "big_contracts": 0.0,
        "block_contracts": 0.0,
    }


def add_print(bar, price, count, taker, is_block, min_contracts):
    bar["n"] += 1
    bar["contracts"] += count
    bar["yes_notional"] += price * count
    bar["last_yes"] = price
    bar["pmin"] = price if bar["pmin"] is None else min(bar["pmin"], price)
    bar["pmax"] = price if bar["pmax"] is None else max(bar["pmax"], price)
    if taker == "yes":
        bar["taker_yes"] += 1
    elif taker == "no":
        bar["taker_no"] += 1
    if count >= min_contracts:
        bar["big_contracts"] += count
    if is_block:
        bar["block_contracts"] += count


def append_lines(path, rows, gz=False):
    """Append-only writer; gzip for the bulk verbatim-print file."""
    if not rows:
        return
    opener = gzip.open if gz else open
    with opener(str(path), "at") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")


def rotate_bars():
    """Roll the live bars file into a per-day gz.

    bars.jsonl is the LIVE append path (so a verifier can read one file without
    knowing the day), but at ~18 MB/day uncompressed it must not grow without
    bound — the artifacts are TRACKED IN GIT (user override 2026-10-12), and the
    nightly backup carries a 95 MB per-file guard. A date change gzips the finished
    day to bars-<date>.jsonl.gz (~3 MB) and starts the live file fresh.
    """
    if not BARS_FILE.exists() or BARS_FILE.stat().st_size == 0:
        return None
    day = None
    try:
        with BARS_FILE.open() as fh:
            last = None
            for last in fh:
                pass
        if last:
            day = json.loads(last).get("minute", "")[:10]
    except Exception:
        day = None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not day or day == today:
        return None
    dest = OUTDIR / ("bars-%s.jsonl.gz" % day)
    with BARS_FILE.open("rb") as src, gzip.open(str(dest), "ab") as dst:
        shutil.copyfileobj(src, dst)
    BARS_FILE.unlink()
    return dest.name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-minutes", type=float, default=3.0, help="length of the complete capture window")
    ap.add_argument("--max-pages", type=int, default=400, help="safety cap on pages per run")
    ap.add_argument("--max-bytes", type=int, default=250_000_000, help="safety cap on transfer per run")
    ap.add_argument("--min-contracts", type=float, default=100.0, help="verbatim-print size floor")
    ap.add_argument("--page-sleep", type=float, default=0.12)
    ap.add_argument("--chase-watermark", action="store_true", help="also walk back until the previous run's oldest ts (fills holes; costs transfer)")
    ap.add_argument("--dry-run", action="store_true", help="walk and report, write nothing")
    args = ap.parse_args()

    families = load_families()
    state = load_state()
    tickers_state = state.setdefault("tickers", {})
    known_ids = list(state.get("ids", []))
    known_set = set(known_ids)
    prev_run = state.get("last_run") or {}

    started = datetime.now(timezone.utc)
    window_start = started

    # seed the bar aggregation with any partial minute persisted by the last run
    bars = {}
    for tick, tstate in tickers_state.items():
        partial = tstate.get("partial")
        if partial and partial.get("minute"):
            bars[(tick, partial["minute"])] = partial["bar"]

    scanned = 0
    kept = 0
    pages = 0
    nbytes = 0
    fam_scanned = {}
    fam_kept = {}
    newest_ts = None
    oldest_ts = None
    prints_rows = []
    stop_reason = "cursor_exhausted"
    cursor = None

    while pages < args.max_pages and nbytes < args.max_bytes:
        url = "%s/markets/trades?limit=%d" % (API, PAGE_LIMIT)
        if cursor:
            url += "&cursor=" + urllib.parse.quote(cursor, safe="")
        _status, blen, payload = get_json(url)
        nbytes += blen
        pages += 1
        rows = payload.get("trades") or []
        if not rows:
            stop_reason = "no_rows"
            break
        for row in rows:
            scanned += 1
            ticker = row.get("ticker") or ""
            family = ticker.split("-")[0]
            ts = row.get("created_time") or ""
            if ts:
                if newest_ts is None or ts > newest_ts:
                    newest_ts = ts
                if oldest_ts is None or ts < oldest_ts:
                    oldest_ts = ts
            if family not in families:
                continue
            price = fnum(row.get("yes_price_dollars"))
            count = fnum(row.get("count_fp"))
            taker = row.get("taker_side")
            is_block = bool(row.get("is_block_trade"))
            fam_scanned[family] = fam_scanned.get(family, 0.0) + count
            key = (ticker, floor_minute(ts).isoformat())
            bar = bars.get(key)
            if bar is None:
                bar = blank_bar()
                bars[key] = bar
            add_print(bar, price, count, taker, is_block, args.min_contracts)
            fam_kept[family] = fam_kept.get(family, 0.0) + count
            trade_id = row.get("trade_id") or ""
            if count >= args.min_contracts and trade_id and trade_id not in known_set:
                known_set.add(trade_id)
                known_ids.append(trade_id)
                kept += 1
                prints_rows.append(
                    {
                        "ts": ts,
                        "ticker": ticker,
                        "family": family,
                        "trade_id": trade_id,
                        "contracts": count,
                        "yes_price": price,
                        "no_price": fnum(row.get("no_price_dollars")),
                        "taker_side": taker,
                        "is_block_trade": is_block,
                    }
                )
        cursor = payload.get("cursor")
        if not cursor:
            stop_reason = "cursor_exhausted"
            break
        if oldest_ts:
            if args.chase_watermark and prev_run.get("oldest_ts") and oldest_ts <= prev_run["oldest_ts"]:
                stop_reason = "watermark_reached"
                break
            age_min = (window_start - parse_iso(oldest_ts)).total_seconds() / 60.0
            if age_min >= args.window_minutes:
                stop_reason = "window_complete"
                break
        time.sleep(args.page_sleep)
    else:
        stop_reason = "cap_hit_pages" if pages >= args.max_pages else "cap_hit_bytes"

    # ---- emit bars for every CLOSED minute; the newest minute stays partial ----
    # DEDUPE GUARD: a minute already written for this ticker is never written again.
    # Windows can meet at the boundary at 93% duty, and an overlapping tick would
    # otherwise append a duplicate (ticker, minute) row (re-aggregated from the
    # prints it re-scanned). Skipped minutes are counted in every coverage row.
    now_min = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    bar_rows = []
    deduped = 0
    for (tick, minute), bar in bars.items():
        if parse_iso(minute) >= now_min:
            continue
        emitted_through = tickers_state.get(tick, {}).get("last_minute")
        if emitted_through and minute <= emitted_through:
            deduped += 1
            continue
        bar_rows.append(
            {
                "minute": minute,
                "ticker": tick,
                "family": tick.split("-")[0],
                "n": bar["n"],
                "contracts": round(bar["contracts"], 4),
                "vwap_yes": round(bar["yes_notional"] / bar["contracts"], 6) if bar["contracts"] else None,
                "last_yes": bar["last_yes"],
                "pmin": bar["pmin"],
                "pmax": bar["pmax"],
                "taker_yes": bar["taker_yes"],
                "taker_no": bar["taker_no"],
                "big_contracts": round(bar["big_contracts"], 4),
                "block_contracts": round(bar["block_contracts"], 4),
            }
        )
    bar_rows.sort(key=lambda r: r["minute"])
    partials = {}
    for (tick, minute), bar in bars.items():
        if parse_iso(minute) >= now_min:
            partials[tick] = {"minute": minute, "bar": bar}

    window_seconds = None
    if newest_ts and oldest_ts:
        window_seconds = round((parse_iso(newest_ts) - parse_iso(oldest_ts)).total_seconds(), 1)
    coverage = {
        "run_started": started.isoformat(),
        "pages": pages,
        "bytes": nbytes,
        "stop_reason": stop_reason,
        "cap_hit": stop_reason.startswith("cap_hit"),
        "window_requested_minutes": args.window_minutes,
        "window_captured_seconds": window_seconds,
        "prints_scanned": scanned,
        "prints_per_second": round(scanned / window_seconds, 1) if window_seconds else None,
        "prints_kept_verbatim": kept,
        "min_contracts_floor": args.min_contracts,
        "newest_ts": newest_ts,
        "oldest_ts": oldest_ts,
        "hole_minutes_before_window": round(
            (parse_iso(oldest_ts) - parse_iso(prev_run["newest_ts"])).total_seconds() / 60.0, 3
        )
        if oldest_ts and prev_run.get("newest_ts")
        else None,
        "families_scanned_contracts": {k: round(v, 2) for k, v in sorted(fam_scanned.items())},
        "families_kept_contracts": {k: round(v, 2) for k, v in sorted(fam_kept.items())},
        "bars_closed": len(bar_rows),
        "bars_deduped": deduped,
        "tickers_seen": len({t for t, _ in bars}),
    }

    print(
        "kalshi-tape: pages=%d bytes=%.1fMB window=%.0fs scanned=%d kept=%d bars=%d families=%d stop=%s%s"
        % (
            pages,
            nbytes / 1e6,
            window_seconds or 0.0,
            scanned,
            kept,
            len(bar_rows),
            len(fam_scanned),
            stop_reason,
            " ⚠️ CAP HIT — gap" if coverage["cap_hit"] else "",
        )
    )
    for fam, contracts in coverage["families_kept_contracts"].items():
        print("  %-16s captured %12.0f contracts" % (fam, contracts))

    if args.dry_run:
        print("  (dry run — nothing written)")
        return 0

    OUTDIR.mkdir(parents=True, exist_ok=True)
    # per-HOUR prints file: measured ~29 bytes/print gzipped and ~1.1M prints/day,
    # so a whole-day file is ~31 MB — fine today, but one busier day should not be
    # able to push a single tracked file toward the backup's 95 MB guard.
    stamp = started.strftime("%Y-%m-%dT%H")
    prints_file = OUTDIR / ("prints-%s.jsonl.gz" % stamp)
    rotated = rotate_bars()
    append_lines(BARS_FILE, bar_rows)
    append_lines(prints_file, prints_rows, gz=True)
    append_lines(COVERAGE_FILE, [coverage])

    for tick in set(list(tickers_state.keys()) + [t for t, _ in bars]):
        tstate = tickers_state.setdefault(tick, {})
        if tick in partials:
            tstate["partial"] = partials[tick]
        elif "partial" in tstate:
            del tstate["partial"]
        # emitted (closed) minutes only: including the still-partial minute here would
        # let the dedupe guard swallow that minute's bar once it closes.
        minutes = [m for t, m in bars if t == tick and parse_iso(m) < now_min]
        if minutes:
            prev = tstate.get("last_minute")
            tstate["last_minute"] = max(minutes) if not prev else max(prev, max(minutes))
    state["ids"] = known_ids[-ID_MEMORY:]
    state["last_run"] = {
        "started": started.isoformat(),
        "newest_ts": newest_ts,
        "oldest_ts": oldest_ts,
        "pages": pages,
        "stop_reason": stop_reason,
    }
    save_state(state)
    print(
        "  wrote %d bars%s, %d verbatim prints (>=%gc, gz) -> %s, coverage row%s"
        % (
            len(bar_rows),
            " (dedupe guard skipped %d already-written minutes)" % deduped if deduped else "",
            len(prints_rows),
            args.min_contracts,
            prints_file.name,
            " | rotated %s" % rotated if rotated else "",
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
