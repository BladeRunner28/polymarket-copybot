"""Spread maker (spread-maker-v5-12h-one-per-event): two-sided quotes one cent
inside wide spreads, before the event starts.

Plans: RESEARCH_LOG.md, "2026-10-22: Spread maker pilot", for v3
"2026-10-23: Spread maker v3" with its "changes after review", and for v5
"2026-10-30: Spread maker v5". For open markets in the allowed series whose
expected expiration is 4 to 24 hours away and whose spread is 8c or more,
quote a YES bid one cent above the best YES bid and a NO bid one cent above
the best NO bid, up to 2 contracts each (live/spread_policy.py), post-only,
expiring after 65 minutes, in at most one market per event. Only events
with a known start (ticker time, validated Kalshi milestone or per-series
offset; the earliest wins) are quoted, a new quote needs the start 85 minutes
to 12 hours away, and every quote is cancelled 20 minutes before it. Hold fills to
settlement; an order shrinks so that held plus resting contracts on one side
of a market never exceed the per-market cap.

Modes (``--auto`` picks live only when armed, else shadow):
- ``--shadow``: public data only. Writes the quotes it would post to
  STATE/shadow.jsonl and scores them later from Kalshi's public trade prints
  and results. No credentials, no orders.
- ``--live``: real orders, under the shared account lock, inside the shared
  account risk checks (live/shared_account_risk.py) and the pilot caps
  (live/spread_policy.py). Requires KALSHI_ENV=prod,
  ALLOW_PRODUCTION_TRADING=YES, SPREAD_AUTO_ARM=YES, shared-account mode and
  the owner-created marker /etc/market-maker-spread.enabled. The shadow
  ledger keeps running beside it.
- ``--status``: summary of both ledgers.
- ``--preflight``: signed GET-only readiness check (no orders).
- ``--reconcile``: owner-run, signed GET-only resolution of an ambiguous
  order: found in any status (accepted) or absent 10+ minutes later.

Every order and cancel is journaled before it is sent. An exchange HTTP 4xx
refusal is recorded as rejected only after a signed read finds no order with
that client id in any status; any other failure halts all bots until the
owner runs ``--reconcile``. A pass that halts first cancels this bot's
provably owned resting orders. A KILL file in STATE cancels them every pass.
"""

import argparse
import fcntl
import json
import math
import os
import random
import re
import signal
import time
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from kalshi import api as kalshi_api
from kalshi import shard_funding
from kalshi.trading import Order, TradingClient, TradingError

# Every module a pass can need is loaded when the process starts (including
# the two modules the shared account check loads), so a code release landing
# mid-pass cannot mix old and new code inside one pass.
from live import nfl_policy, prod_nba_auto, prod_nfl_auto, production_lock  # noqa: F401
from live import shared_account_risk as shared
from live import spread_policy as P

NY = ZoneInfo("America/New_York")
REQUIRED = {
    "KALSHI_ENV": "prod",
    "ALLOW_PRODUCTION_TRADING": "YES",
    "SPREAD_AUTO_ARM": "YES",
}


# --------------------------------------------------------------- journal


def write_event(path, data):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_events(path):
    if not path.exists():
        return []
    raw = path.read_text()
    if raw and not raw.endswith("\n"):
        raise TradingError("Incomplete spread journal: HALT")
    try:
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    except (ValueError, TypeError) as error:
        raise TradingError("Invalid spread journal: HALT") from error


def _intents(events):
    intents = {}
    for e in events:
        if e.get("event") != "intent":
            continue
        cid = e.get("client_order_id")
        if not cid or cid in intents:
            raise TradingError("Duplicate or incomplete spread intent: HALT")
        intents[cid] = e
    accepted = {}
    for e in events:
        if e.get("event") == "accepted":
            cid, oid = e.get("client_order_id"), e.get("order_id")
            if cid not in intents or not oid or cid in accepted:
                raise TradingError("Invalid spread acceptance: HALT")
            accepted[cid] = str(oid)
    return intents, accepted, shared.spread_rejected_ids(events)


def records(events):
    """Intents by client id, accepted order ids, and refused client ids.

    Halts while any order's outcome is unproven (an ``unknown_outcome`` or
    an intent with no reply) until the owner's ``--reconcile`` resolves it.
    """
    intents, accepted, refused = _intents(events)
    unknown = {
        e.get("client_order_id") for e in events if e.get("event") == "unknown_outcome"
    }
    if unknown - set(accepted) - refused:
        raise TradingError(
            "Ambiguous spread order: HALT, owner runs setup_spread_maker.sh --reconcile"
        )
    if set(intents) != set(accepted) | refused:
        raise TradingError("Unreconciled spread submission: HALT")
    return intents, accepted, refused


# ------------------------------------------------------------ the market


def _cents(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    cents = round(number * 100)
    return cents if abs(cents - number * 100) < 1e-6 else None


def excluded(ticker, other_tickers):
    return str(ticker).startswith(P.EXCLUDED_PREFIXES) or ticker in other_tickers


def quote_prices(yes_bid_cents, yes_ask_cents):
    """(YES bid price, NO bid price) one cent inside, or None if not eligible."""
    if yes_bid_cents is None or yes_ask_cents is None:
        return None
    if not 0 < yes_bid_cents < yes_ask_cents < 100:
        return None
    if yes_ask_cents - yes_bid_cents < P.MIN_SPREAD_CENTS:
        return None
    yes_price = yes_bid_cents + 1
    no_price = (100 - yes_ask_cents) + 1
    lo, hi = P.PRICE_RANGE_CENTS
    if not (lo <= yes_price <= hi and lo <= no_price <= hi):
        return None
    # Both stay strictly inside the spread: post-only, never crossing.
    if not (yes_price < yes_ask_cents and 100 - no_price > yes_bid_cents):
        return None
    return yes_price, no_price


# ------------------------------------------------------- event start times
# v2 quotes only before an event starts. Kalshi's expected expiration can be
# hours after the end (college football: 6 hours after kickoff), so the
# start comes from the event ticker or from Kalshi's milestones.
_TICKER_START = re.compile(
    r"^[A-Z0-9]+-(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})(?=[A-Z])"
)
_MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "JAN",
            "FEB",
            "MAR",
            "APR",
            "MAY",
            "JUN",
            "JUL",
            "AUG",
            "SEP",
            "OCT",
            "NOV",
            "DEC",
        ),
        start=1,
    )
}


def ticker_start(event_ticker):
    """The scheduled start written into an event ticker, in New York time:
    KXR6GAME-26OCT222000L5FAZE starts 20:00 New York time on 22 Oct 2026.
    None when the ticker carries no time. A wall time the clock change
    skips or repeats takes the earlier instant."""
    match = _TICKER_START.match(event_ticker or "")
    if not match:
        return None
    yy, month, day, hour, minute = match.groups()
    if month not in _MONTHS:
        return None
    try:
        local = datetime(
            2000 + int(yy), _MONTHS[month], int(day), int(hour), int(minute), tzinfo=NY
        )
    except ValueError:
        return None
    return min(local.replace(fold=f).astimezone(UTC) for f in (0, 1))


def _utc(value):
    when = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(when) else when.to_pydatetime()


def milestone_starts(event_ticker, expires, fetch_milestones):
    """(start, type) of each Kalshi milestone tied to this event whose start
    falls within MILESTONE_WINDOW_HOURS before the market's expected
    expiration (a tournament that began days earlier does not count)."""
    payload = fetch_milestones(event_ticker) or {}
    out = []
    for m in payload.get("milestones") or []:
        tickers = set(m.get("primary_event_tickers") or []) | set(
            m.get("related_event_tickers") or []
        )
        start = _utc(m.get("start_date"))
        if event_ticker not in tickers or start is None:
            continue
        if expires is not None and not (
            expires - timedelta(hours=P.MILESTONE_WINDOW_HOURS) <= start <= expires
        ):
            continue
        out.append((start, str(m.get("type") or "")))
    return out


def milestone_start(event_ticker, expires, fetch_milestones):
    """The earliest of those starts, or None."""
    found = milestone_starts(event_ticker, expires, fetch_milestones)
    return min(start for start, _ in found) if found else None


def event_start(event_ticker, starts=None):
    """The earliest known start: the ticker's, and a milestone's if found."""
    found = [
        t
        for t in (ticker_start(event_ticker), (starts or {}).get(event_ticker))
        if t is not None
    ]
    return min(found) if found else None


def _check_order(timed, now, active=frozenset()):
    """Events carrying a time to compare with milestones: first those that
    may have quotes resting (``active``), then one per series (the next to
    start that has not started), in an order that rotates every pass."""
    soon = now + timedelta(minutes=P.CANCEL_LEAD_MINUTES)
    upcoming = {e: x for e, x in timed.items() if ticker_start(e) >= soon}
    first_checks = [(e, upcoming[e]) for e in sorted(upcoming) if e in active]
    first = {}
    for event in sorted(upcoming):
        if event in active:
            continue
        series = event.split("-", 1)[0]
        if series not in first or ticker_start(event) < ticker_start(first[series]):
            first[series] = event
    picks = [(first[s], upcoming[first[s]]) for s in sorted(first)]
    if picks:
        shift = int(now.timestamp() // 600) % len(picks)
        picks = picks[shift:] + picks[:shift]
    return first_checks, picks


def _clean_types(raw, now):
    """The trust record, keeping only well-formed entries with past times."""
    out = {}
    if not isinstance(raw, dict):
        return out
    limit = (now + timedelta(minutes=5)).isoformat()
    for kind, entry in raw.items():
        if not kind or not isinstance(kind, str) or not isinstance(entry, dict):
            continue
        clean = {}
        for key in ("matched", "late"):
            seen = entry.get(key)
            clean[key] = {
                str(e): t
                for e, t in (seen.items() if isinstance(seen, dict) else ())
                if isinstance(t, str) and t <= limit
            }
        out[kind] = clean
    return out


def recent_events(state_dir, now):
    """Events of this bot's orders sent in the last ORDER_LIFETIME_MINUTES
    (their quotes may still rest). Empty if the journal cannot be read."""
    since = (now - timedelta(minutes=P.ORDER_LIFETIME_MINUTES)).isoformat()
    try:
        events = load_events(state_dir / "journal.jsonl")
    except Exception:
        return set()
    return {
        e.get("event_ticker")
        for e in events
        if e.get("event") == "intent" and str(e.get("utc", "")) >= since
    } - {None}


def _rotated(events, shift):
    events = sorted(events)
    if events:
        k = shift % len(events)
        events = events[k:] + events[:k]
    return events


def _read_order(timed, candidates, now, active=frozenset()):
    """(event, expiry) pairs in the order their milestones are read:

    1. events that may have quotes resting (with a ticker time, then without);
    2. MILESTONE_CHECKS ticker-timed events, one per series, rotating (the
       trust checks);
    3. untimed events in offset series (a milestone can only move their
       start earlier), then in MILESTONE_ONLY_SERIES (a milestone is their
       only start), each group rotating every pass.

    Untimed events in other series are never read: no trusted milestone
    type has ever dated them."""
    shift = int(now.timestamp() // 600)
    first_checks, picks = _check_order(timed, now, active)
    order = first_checks
    order += [(e, candidates[e]) for e in sorted(candidates) if e in active]
    order += picks[: P.MILESTONE_CHECKS]
    for group in (P.SERIES_START_OFFSET_HOURS, P.MILESTONE_ONLY_SERIES):
        rest = [
            e for e in candidates if e not in active and e.split("-", 1)[0] in group
        ]
        order += [(e, candidates[e]) for e in _rotated(rest, shift)]
    return order


def _offset_checks(timed, now, raw):
    """Series whose offset failed a live check in the last
    OFFSET_SUSPEND_DAYS: {series: {event: first seen}}, this pass's
    ticker-timed events included."""
    since = (now - timedelta(days=P.OFFSET_SUSPEND_DAYS)).isoformat()
    limit = (now + timedelta(minutes=5)).isoformat()
    out = {}
    for series, seen in raw.items() if isinstance(raw, dict) else ():
        if isinstance(series, str) and isinstance(seen, dict):
            kept = {
                str(e): t
                for e, t in seen.items()
                if isinstance(t, str) and since <= t <= limit
            }
            if kept:
                out[series] = kept
    for event, expires in timed.items():
        series = event.split("-", 1)[0]
        gap = P.SERIES_START_OFFSET_HOURS.get(series)
        if gap is None:
            continue
        estimate = expires - timedelta(hours=gap, minutes=P.START_OFFSET_MARGIN_MINUTES)
        if estimate > ticker_start(event):
            out.setdefault(series, {}).setdefault(event, now.isoformat())
    return out


def _clean_earliest(raw, now):
    """The earliest-start memory {event: start}, dropping malformed entries
    and starts more than two days past."""
    out = {}
    if not isinstance(raw, dict):
        return out
    old = now - timedelta(days=2)
    for event, value in raw.items():
        start = _utc(value) if isinstance(value, str) else None
        if isinstance(event, str) and event and start is not None and start >= old:
            out[event] = start
    return out


def prefetch_starts(
    listings, now, state_dir, fetch_milestones, deadline=None, active=frozenset()
):
    """Start times for events in the quoting window, beyond ticker times.

    - Events whose ticker carries a time: up to MILESTONE_CHECKS of them
      (one per series, rotating) and any with quotes resting are compared
      with Kalshi's milestones. Each comparison is remembered by milestone
      type for MILESTONE_TRUST_DAYS. A milestone earlier than the ticker time
      also counts as that event's start (the earlier start wins, which only
      ever quotes less). The series offsets never apply to them, but each
      one checks its series' offset: if the offset estimate would come after
      the ticker's start, the offset is suspended for OFFSET_SUSPEND_DAYS.
    - Events without a time are dated by a milestone from
      TRUSTED_MILESTONE_TYPES (validated on past events, and only while no
      milestone of that type has been seen later than a ticker time by more
      than MILESTONE_LATE_MINUTES in the last MILESTONE_TRUST_DAYS;
      NEVER_TRUSTED_MILESTONE_TYPES never count) and, for a series in
      SERIES_START_OFFSET_HOURS, by expected expiration - its gap - the
      margin. The start is the earliest of these and of any other milestone
      read for the event (of any type: it can only move a start earlier).
      With neither a trusted milestone nor an offset, the event has no known
      start and is not quoted. Only events in offset series and in
      MILESTONE_ONLY_SERIES are read (_read_order has the order).
    - The earliest start found for an event is remembered (two days), so a
      start can move earlier but never later, even when Kalshi moves an
      expiration later or a milestone cannot be read. The memory only lowers
      a start found this pass; it never supplies one on its own.
    - NO_START_SERIES are skipped: they are never quoted.

    Milestone answers are cached for START_CACHE_MINUTES; at most
    MAX_START_LOOKUPS_PER_PASS reads a pass and none after ``deadline``."""
    path = state_dir / "event_starts.json"
    try:
        cache = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    candidates, timed = {}, {}
    for series, markets in listings.items():
        if series in P.NO_START_SERIES:
            continue
        if P.ESPORTS_ONLY and series not in P.ESPORTS_SERIES:
            continue  # v7: never quoted, so no start reads are spent on them
        for m in markets:
            event = m.get("event_ticker")
            expires = _utc(m.get("expected_expiration_time"))
            if not event or expires is None:
                continue
            if event.split("-", 1)[0] in P.NO_START_SERIES:
                continue
            # Up to the end of the window: events with resting quotes stay
            # refreshed until their quotes are gone.
            hours = (expires - now).total_seconds() / 3600
            if not 0 <= hours <= P.WINDOW_HOURS[1]:
                continue
            group = timed if ticker_start(event) is not None else candidates
            group[event] = min(group.get(event, expires), expires)
    fresh = (now - timedelta(minutes=P.START_CACHE_MINUTES)).isoformat()
    future = (now + timedelta(minutes=5)).isoformat()
    starts = {}
    reads = {"done": 0, "failed": 0}

    def cached(hit):
        """A well-formed, fresh cache entry as a (start, type) list, else None."""
        if not isinstance(hit, dict):
            return None
        checked = str(hit.get("checked", ""))
        if not fresh <= checked <= future:
            return None
        out = []
        for pair in hit.get("milestones") or []:
            if not (isinstance(pair, list) and len(pair) == 2):
                return None
            start = _utc(pair[0])
            if start is None:
                return None
            out.append((start, str(pair[1] or "")))
        return out

    def read(event, expires):
        """Cached (start, type) list, or None if not available this pass."""
        hit = cached(cache.get(event))
        if hit is not None:
            return hit
        if reads["done"] >= P.MAX_START_LOOKUPS_PER_PASS or out_of_time(deadline):
            return None
        reads["done"] += 1
        try:
            found = milestone_starts(event, expires, fetch_milestones)
        except Exception:
            reads["failed"] += 1
            return None
        cache[event] = {
            "milestones": [[s.isoformat(), t] for s, t in found],
            "checked": now.isoformat(),
        }
        return found

    types = _clean_types(cache.get("types"), now)
    remembered = _clean_earliest(cache.get("earliest"), now)
    suspended = _offset_checks(timed, now, cache.get("offset_late"))
    found = {}
    for event, expires in _read_order(timed, candidates, now, active):
        hit = read(event, expires)
        if hit is not None:
            found[event] = hit
    # Trust checks: every ticker-timed event read this pass.
    for event in timed:
        if not found.get(event):
            continue
        written = ticker_start(event)
        for start, kind in found[event]:
            if not kind:
                continue  # a milestone without a type is never trusted
            gap = (start - written).total_seconds() / 60  # > 0: milestone later
            entry = types.setdefault(kind, {"matched": {}, "late": {}})
            if gap > P.MILESTONE_LATE_MINUTES:
                entry["late"][event] = now.isoformat()
            elif gap >= -P.MILESTONE_AGREE_MINUTES:
                entry["matched"][event] = now.isoformat()
        earliest = min(start for start, _ in found[event])
        if earliest < written:
            starts[event] = earliest
    since = (now - timedelta(days=P.MILESTONE_TRUST_DAYS)).isoformat()
    types = {
        kind: {
            key: {e: t for e, t in entry[key].items() if t >= since}
            for key in ("matched", "late")
        }
        for kind, entry in types.items()
    }
    trusted = {
        kind
        for kind in P.TRUSTED_MILESTONE_TYPES - P.NEVER_TRUSTED_MILESTONE_TYPES
        if not types.get(kind, {}).get("late")
    }
    counts = Counter()
    for event, expires in sorted(candidates.items()):
        series = event.split("-", 1)[0]
        milestones = found.get(event) or []
        dated = [start for start, kind in milestones if kind and kind in trusted]
        gap = None if series in suspended else P.SERIES_START_OFFSET_HOURS.get(series)
        offset = (
            None
            if gap is None
            else expires - timedelta(hours=gap, minutes=P.START_OFFSET_MARGIN_MINUTES)
        )
        if offset is not None:
            dated.append(offset)
        if not dated:
            counts["no_start"] += 1
            continue
        # Any milestone, trusted or not, may move a dated start earlier.
        start = min(dated + [start for start, _ in milestones])
        starts[event] = start
        counts["offset" if start == offset else "milestone"] += 1
        if offset is not None and event not in found:
            counts["offset_unread"] += 1
    # The memory: a start may move earlier, never later.
    for event in sorted(set(timed) | set(candidates)):
        current = event_start(event, starts)
        if current is None:
            continue  # the memory never supplies a start on its own
        earlier = remembered.get(event)
        if earlier is not None and earlier < current:
            starts[event] = earlier
            counts["kept_earlier"] += 1
        if event in starts:
            remembered[event] = starts[event]
    old = (now - timedelta(days=2)).isoformat()
    cache = {
        k: v
        for k, v in cache.items()
        if k not in ("types", "earliest", "offset_late")
        and isinstance(v, dict)
        and str(v.get("checked", "")) >= old
    }
    cache["types"] = {k: v for k, v in types.items() if v["matched"] or v["late"]}
    cache["earliest"] = {e: t.isoformat() for e, t in sorted(remembered.items())}
    cache["offset_late"] = suspended
    try:
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(cache, sort_keys=True))
        temporary.chmod(0o600)
        temporary.replace(path)
    except OSError:
        # The cache saves reads; for events already quoted, the live pass
        # also keeps the earliest start recorded in the journal.
        counts["cache_write_failed"] += 1
    return starts, {
        "events_without_ticker_time": len(candidates),
        "milestone_types_trusted": sorted(trusted),
        "milestone_types_late": sorted(k for k, v in types.items() if v["late"]),
        "milestone_reads": reads["done"],
        "milestone_read_failures": reads["failed"],
        "with_milestone_start": counts["milestone"],
        "with_series_offset_start": counts["offset"],
        "offset_dated_unread": counts["offset_unread"],
        "without_start": counts["no_start"],
        "kept_earlier_start": counts["kept_earlier"],
        "offset_series_suspended": sorted(suspended),
        "cache_write_failed": counts["cache_write_failed"],
        "earlier_than_ticker": sum(
            e in timed and starts[e] < ticker_start(e) for e in starts
        ),
    }


def eligible_markets(
    markets, series, now, other_tickers=frozenset(), starts=None, reasons=None
):
    """Open markets in the window with a wide two-sided quote whose event has
    a known start at least CANCEL_LEAD_MINUTES away. ``postable`` marks those
    far enough ahead (MIN_LEAD_MINUTES) for a new order; the others only
    keep quotes already resting."""
    reasons = Counter() if reasons is None else reasons
    rows = []
    for m in markets:
        ticker = m.get("ticker")
        if not ticker or excluded(ticker, other_tickers):
            continue
        if series in P.MAKER_FEE_SERIES or m.get("status") not in ("active", "open"):
            continue
        if series in P.NO_START_SERIES:
            reasons["no_start_series"] += 1
            continue
        if series in P.ESPORTS_SERIES and not P.QUOTE_ESPORTS:
            reasons["esports_off"] += 1
            continue
        if P.ESPORTS_ONLY and series not in P.ESPORTS_SERIES:
            reasons["not_esports"] += 1  # v7
            continue
        expires = pd.to_datetime(
            m.get("expected_expiration_time"), utc=True, errors="coerce"
        )
        if pd.isna(expires):
            continue
        hours = (expires.to_pydatetime() - now).total_seconds() / 3600
        if not P.WINDOW_HOURS[0] <= hours <= P.WINDOW_HOURS[1]:
            continue
        bid, ask = _cents(m.get("yes_bid_dollars")), _cents(m.get("yes_ask_dollars"))
        prices = quote_prices(bid, ask)
        if prices is None:
            continue
        start = event_start(m.get("event_ticker", ""), starts)
        if start is None:
            reasons["no_event_start"] += 1
            continue
        lead = (start - now).total_seconds() / 60
        if lead < P.CANCEL_LEAD_MINUTES:
            reasons["event_starting"] += 1
            continue
        too_far = lead > P.MAX_LEAD_HOURS * 60
        if too_far:
            reasons["start_too_far"] += 1
        rows.append(
            {
                "ticker": ticker,
                "series": series,
                "event_ticker": m.get("event_ticker", ""),
                "yes_bid": bid,
                "yes_ask": ask,
                "spread": ask - bid,
                "yes_price": prices[0],
                "no_price": prices[1],
                "expiration_utc": expires.isoformat(),
                "event_start_utc": start.isoformat(),
                "postable": lead >= P.MIN_LEAD_MINUTES and not too_far,
            }
        )
    return rows


def book_quote(book, own=()):
    """(best YES bid, best YES offer) in cents from a public order book, with
    our own resting quotes taken out so the bot never prices off itself.

    ``own`` holds (side, price_cents, count) for our resting quotes in that
    market. Our NO bid at q shows in the book's NO bids at q.
    """
    if not isinstance(book, dict):
        return None, None
    depth = {}
    for side in ("yes", "no"):
        levels = {}
        for entry in book.get(f"{side}_dollars") or []:
            try:
                price, quantity = _cents(entry[0]), float(entry[1])
            except (TypeError, ValueError, IndexError, KeyError):
                return None, None
            if price is None or not math.isfinite(quantity):
                return None, None
            levels[price] = levels.get(price, 0.0) + quantity
        depth[side] = levels
    for side, price, count in own:
        if price in depth.get(side, {}):
            depth[side][price] -= count
    yes = [p for p, q in depth["yes"].items() if q > 1e-9]
    no = [p for p, q in depth["no"].items() if q > 1e-9]
    return (max(yes) if yes else None), (100 - max(no) if no else None)


def _dollars(cents, default):
    return f"{(default if cents is None else cents) / 100:.2f}"


def universe(
    fetch_markets,
    now,
    other_tickers=frozenset(),
    own=None,
    fetch_book=None,
    unreadable=None,
    starts=None,
    reasons=None,
    seen_books=None,
):
    """Eligible markets, widest spread first.

    For markets where we already rest quotes (``own``: ticker -> list of
    (side, price_cents, count)), the listed best bid and offer may be ours, so
    the quote comes from the order book with our orders removed. A market
    whose book cannot be read is left out and added to ``unreadable``: the
    live pass keeps its quotes as they are and adds nothing there.
    """
    own = own or {}
    rows = []
    for series in P.SERIES:
        try:
            markets = fetch_markets(series, status="open") or []
        except Exception:  # one bad series must not stop the others
            continue
        adjusted = []
        for m in markets:
            ticker = m.get("ticker")
            if ticker in own:
                try:
                    book = fetch_book(ticker)
                except Exception:
                    book = None
                if not isinstance(book, dict):
                    if unreadable is not None:
                        unreadable.add(ticker)
                    continue
                bid, ask = book_quote(book, own[ticker])
                if seen_books is not None:
                    seen_books[ticker] = (bid, ask)  # our own orders taken out
                m = {
                    **m,
                    "yes_bid_dollars": _dollars(bid, 0),
                    "yes_ask_dollars": _dollars(ask, 100),
                }
            adjusted.append(m)
        rows.extend(
            eligible_markets(adjusted, series, now, other_tickers, starts, reasons)
        )
    return sorted(rows, key=lambda r: (-r["spread"], r["ticker"]))


# ---------------------------------------------------------------- shadow


def shadow_post(events, markets, now):
    """At most one shadow quote per market and side per hour."""
    recent = {}
    for e in events:
        if e.get("event") == "shadow_quote":
            key = (e["ticker"], e["side"])
            recent[key] = max(recent.get(key, ""), e["posted_utc"])
    cutoff = (now - timedelta(minutes=P.SHADOW_REPOST_MINUTES)).isoformat()
    new = []
    for m in markets:
        prices = {"yes": m["yes_price"], "no": m["no_price"]}
        for side in quoted_sides(m["ticker"], market_spread(m)):
            price = prices[side]
            if recent.get((m["ticker"], side), "") > cutoff:
                continue
            new.append(
                {
                    "event": "shadow_quote",
                    "id": str(uuid.uuid4()),
                    "ticker": m["ticker"],
                    "series": m["series"],
                    "event_ticker": m["event_ticker"],
                    "side": side,
                    "price_cents": price,
                    "contracts": order_size(m["ticker"]),
                    "spread": m["spread"],
                    "posted_utc": now.isoformat(),
                    "expires_utc": (
                        now + timedelta(minutes=P.SHADOW_REPOST_MINUTES)
                    ).isoformat(),
                    "market_expiration_utc": m["expiration_utc"],
                }
            )
    return new


def contracts_through(trades, side, price_cents, start, end):
    """Contracts a taker traded at or through our price in (start, end].

    A YES bid at p is hit by YES sellers (taker side "no") at p or below; a NO
    bid at q is a YES offer at 1 - q, hit by YES buyers at 1 - q or above. We
    were one cent inside, so trades at exactly our price count. Block trades
    never meet resting orders and are ignored.
    """
    total = 0.0
    level = price_cents / 100 if side == "yes" else (100 - price_cents) / 100
    for t in trades:
        if t.get("is_block_trade"):
            continue
        when = pd.to_datetime(t.get("created_time"), utc=True, errors="coerce")
        if pd.isna(when) or not start < when.to_pydatetime() <= end:
            continue
        taker = str(t.get("taker_outcome_side") or "").lower()
        price = t.get("yes_price")
        if price is None or not math.isfinite(float(price)):
            continue
        try:
            count = float(t.get("count") or 0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(count) or count <= 0:
            continue  # a print without a usable size counts for nothing
        if side == "yes" and taker == "no" and float(price) <= level + 1e-9:
            total += count
        if side == "no" and taker == "yes" and float(price) >= level - 1e-9:
            total += count
    return total


# The shadow ledger's reads (trade prints, then results) run after the live
# pass and the live measurements: at most MAX_SHADOW_READS_PER_PASS of each
# kind, none after SHADOW_DEADLINE_SECONDS from process start, each a single
# attempt (two endpoints, 30 s each), in shuffled order so a market that
# cannot be read never starves the rest. What is left waits a pass.
MAX_SHADOW_READS_PER_PASS = 20
SHADOW_DEADLINE_SECONDS = 150


def _capped(keys, deadline, limit, order):
    """``keys`` in shuffled (or ``order``) order, cut to ``limit``; iteration
    stops once ``deadline`` passes or a stop is requested."""
    keys = sorted(keys)
    (order or random.shuffle)(keys)
    for key in keys[: len(keys) if limit is None else limit]:
        if out_of_time(deadline):
            return
        yield key


def shadow_score(events, now, fetch_trades, deadline=None, limit=None, order=None):
    """Fill counts for shadow quotes whose hour has ended."""
    scored = {e["id"] for e in events if e.get("event") == "shadow_fill"}
    due = [
        e
        for e in events
        if e.get("event") == "shadow_quote"
        and e["id"] not in scored
        and e["expires_utc"] <= now.isoformat()
    ]
    out = []
    by_ticker = {}
    for e in due:
        by_ticker.setdefault(e["ticker"], []).append(e)
    for ticker in _capped(by_ticker, deadline, limit, order):
        quotes = by_ticker[ticker]
        start = min(datetime.fromisoformat(q["posted_utc"]) for q in quotes)
        end = max(datetime.fromisoformat(q["expires_utc"]) for q in quotes)
        try:
            trades = fetch_trades(ticker, int(start.timestamp()), int(end.timestamp()))
        except Exception:
            continue  # try again next pass
        for q in quotes:
            through = contracts_through(
                trades,
                q["side"],
                q["price_cents"],
                datetime.fromisoformat(q["posted_utc"]),
                datetime.fromisoformat(q["expires_utc"]),
            )
            out.append({"event": "shadow_fill", "id": q["id"], "through": through})
    return out


def shadow_settle(
    events, fetch_market, now=None, deadline=None, limit=None, order=None
):
    """Market results for shadow quotes that would have filled. With ``now``,
    only markets past their expected expiration are read."""
    filled = {
        e["id"]
        for e in events
        if e.get("event") == "shadow_fill" and float(e.get("through", 0)) >= 1
    }
    done = {e["ticker"] for e in events if e.get("event") == "shadow_result"}
    expiry = {}
    for e in events:
        if e.get("event") == "shadow_quote" and e["id"] in filled:
            when = str(e.get("market_expiration_utc") or "")
            expiry[e["ticker"]] = min(expiry.get(e["ticker"], when), when)
    if now is not None:
        stamp = now.isoformat()
        expiry = {t: w for t, w in expiry.items() if w <= stamp}
    out = []
    for ticker in _capped(set(expiry) - done, deadline, limit, order):
        try:
            market = fetch_market(ticker) or {}
        except Exception:
            continue
        result = market.get("result")
        if result in ("yes", "no"):
            out.append({"event": "shadow_result", "ticker": ticker, "result": result})
    return out


def expected_fill(through, flow, size):
    """Expected contracts filled, E[min(Binomial(through, flow), size)]: our
    share of the contracts traded through our price, capped at our size."""
    n = int(math.floor(through))
    if n <= 0 or size <= 0:
        return 0.0
    if flow >= 1:
        return float(min(n, size))
    pmf = math.exp(n * math.log1p(-flow))  # P(X = 0)
    below, total = 0.0, 0.0
    for k in range(1, int(size) + 1):  # E = sum over k of P(X >= k)
        below += pmf
        total += max(0.0, 1.0 - below)
        pmf *= (n - (k - 1)) / k * flow / (1 - flow)
    return total


def shadow_summary(events, flow=0.25):
    """Shadow ledger results: first in line (every contract traded through
    our price up to our size), and at the given flow share. Simulated."""
    quotes = {e["id"]: e for e in events if e.get("event") == "shadow_quote"}
    fills = {
        e["id"]: float(e["through"]) for e in events if e.get("event") == "shadow_fill"
    }
    results = {
        e["ticker"]: e["result"] for e in events if e.get("event") == "shadow_result"
    }
    rows = []
    for qid, through in fills.items():
        q = quotes.get(qid)
        if q is None:
            continue
        size = int(q.get("contracts", 1))
        result = results.get(q["ticker"])
        won = None if result is None else float(result == q["side"])
        rows.append(
            {
                "filled": through >= 1,
                "first": float(min(math.floor(through), size)),
                "expected": expected_fill(through, flow, size),
                "pnl": None if won is None else won - q["price_cents"] / 100,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return {"quotes": len(quotes), "scored": 0}
    settled = frame[frame.filled & frame.pnl.notna()]
    out = {
        "quotes": len(quotes),
        "scored": len(frame),
        "fill_rate": float(frame.filled.mean()),
        "filled": int(frame.filled.sum()),
        "settled_fills": len(settled),
    }
    if len(settled):
        first = (settled.pnl * settled["first"]).sum()
        out["contracts_first_in_line"] = float(settled["first"].sum())
        out["cents_per_contract"] = 100 * float(first / settled["first"].sum())
        out["dollars_first_in_line"] = round(float(first), 2)
        if settled.expected.sum() > 0:
            share = (settled.pnl * settled.expected).sum()
            out[f"cents_per_contract_flow_{flow:g}"] = 100 * float(
                share / settled.expected.sum()
            )
            out[f"dollars_flow_{flow:g}"] = round(float(share), 2)
    return out


def run_shadow(state_dir, now, public, markets=None, deadline=None):
    path = state_dir / "shadow.jsonl"
    events = load_events(path)
    trades = public.get("shadow_trades", public["fetch_trades"])
    for e in shadow_score(events, now, trades, deadline, MAX_SHADOW_READS_PER_PASS):
        write_event(path, e)
    events = load_events(path)
    results = public.get("shadow_market", public["fetch_market"])
    for e in shadow_settle(events, results, now, deadline, MAX_SHADOW_READS_PER_PASS):
        write_event(path, e)
    if markets is None:
        markets = universe(
            public["fetch_markets"], now, starts=public.get("event_starts")
        )
    # The shadow ledger follows the same rule: no new quote that could rest
    # into the event's start.
    markets = [m for m in markets if m.get("postable", True)]
    for e in shadow_post(load_events(path), markets, now):
        write_event(path, e)
    return shadow_summary(load_events(path))


# ------------------------------------------- live fill share (measurement)
# The backtest assumed we were first in line at our price. For every live
# order whose resting window has ended, count the contracts that public
# trade prints show traded at or through its price during that window (the
# same rule as the shadow ledger). Our share of those, up to the order's
# size, is the fill share: 1.0 is the backtest's first-in-line assumption.
# The cautious replay (each such contract reaches us with probability 0.25)
# implies a higher share than 0.25 on large windows, so it is computed on
# the same windows and reported next to it. Public data only; the result is
# read with the journal's fills and never added to profit.
WINDOW_SETTLE_MINUTES = 5  # let trade prints for a window arrive
MAX_WINDOW_TICKERS_PER_PASS = 10
# Scoring runs after the live pass and starts no new market 150 s after
# the process started (lock waits included): one more market's reads (two
# single attempts, 30 s timeout each) still end inside systemd's 240 s.
SCORING_DEADLINE_SECONDS = 150
CAUTIOUS_FLOW = 0.25
_SAME_PASS = timedelta(minutes=5)


def _first_times(events, kind, key):
    """Earliest ``utc`` of each ``kind`` event, by ``key`` (one journal scan)."""
    out = {}
    for e in events:
        if e.get("event") == kind and e.get(key) is not None and e.get("utc"):
            when = datetime.fromisoformat(e["utc"])
            k = str(e[key])
            out[k] = min(out.get(k, when), when)
    return out


def _refine(first, later):
    """The exchange reply's time when it plausibly belongs to the same
    pass as ``first`` (the pass's start time), else ``first``."""
    if later is not None and first <= later <= first + _SAME_PASS:
        return later
    return first


def live_windows(events, scored, now):
    """Finished, unscored resting windows of this bot's accepted orders."""
    intents = {
        e.get("client_order_id"): e for e in events if e.get("event") == "intent"
    }
    accepted = {
        e.get("client_order_id"): str(e.get("order_id"))
        for e in events
        if e.get("event") == "accepted" and e.get("order_id")
    }
    canceled = {}
    for e in events:
        if e.get("event") == "cancel_intent" and e.get("order_id"):
            when = datetime.fromisoformat(e["utc"])
            oid = str(e["order_id"])
            canceled[oid] = min(canceled.get(oid, when), when)
    accepted_at = _first_times(events, "accepted", "client_order_id")
    replied_at = _first_times(events, "cancel_accepted", "order_id")
    for oid, when in _first_times(events, "cancel_moot", "order_id").items():
        replied_at[oid] = min(replied_at.get(oid, when), when)
    out = []
    for cid, oid in accepted.items():
        intent = intents.get(cid)
        if intent is None or cid in scored:
            continue
        if intent.get("strategy_version") != P.STRATEGY_VERSION:
            continue  # each rule version is measured on its own orders
        sent = datetime.fromisoformat(intent["utc"])
        # Intent and cancel-intent times are the pass's start; the exchange
        # replies come later in the same pass and are closer to the truth.
        start = _refine(sent, accepted_at.get(cid))
        end = sent + timedelta(minutes=P.ORDER_LIFETIME_MINUTES)
        if _utc(intent.get("expires_utc")) is not None:
            end = min(end, _utc(intent["expires_utc"]))
        if oid in canceled:
            end = min(end, _refine(canceled[oid], replied_at.get(oid)))
        if end > now - timedelta(minutes=WINDOW_SETTLE_MINUTES):
            continue
        out.append(
            {
                "client_order_id": cid,
                "ticker": intent["ticker"],
                "side": intent["side"],
                "price_cents": int(intent["price_cents"]),
                "size": float(intent["count"]),
                "start": start,
                "end": end,
            }
        )
    return out


def score_live_windows(state_dir, now, fetch_trades, deadline=None, order=None):
    """Write a ``live_window`` record to the shadow file for each finished
    live order: contracts traded at or through its price while it rested.

    Call it only after a live pass has copied the exchange's fills into the
    journal, so every scored window's fills are already there. At most
    ``MAX_WINDOW_TICKERS_PER_PASS`` markets a pass, in shuffled order (a
    market whose prints cannot be read never starves the rest), and nothing
    new once ``deadline`` passes or a stop is requested."""
    journal, shadow = state_dir / "journal.jsonl", state_dir / "shadow.jsonl"
    if not journal.exists():
        return 0
    scored = {
        e.get("client_order_id")
        for e in load_events(shadow)
        if e.get("event") == "live_window"
    }
    by_ticker = {}
    for w in live_windows(load_events(journal), scored, now):
        by_ticker.setdefault(w["ticker"], []).append(w)
    written = 0
    tickers = sorted(by_ticker)
    (order or random.shuffle)(tickers)
    for ticker in tickers[:MAX_WINDOW_TICKERS_PER_PASS]:
        if out_of_time(deadline):
            break
        windows = by_ticker[ticker]
        start = min(w["start"] for w in windows)
        end = max(w["end"] for w in windows)
        try:
            trades = fetch_trades(
                ticker, int(start.timestamp()) - 1, int(end.timestamp()) + 1
            )
        except Exception:
            continue  # try again next pass
        for w in windows:
            through = contracts_through(
                trades, w["side"], w["price_cents"], w["start"], w["end"]
            )
            write_event(
                shadow,
                {
                    "event": "live_window",
                    "client_order_id": w["client_order_id"],
                    "ticker": ticker,
                    "side": w["side"],
                    "price_cents": w["price_cents"],
                    "size": w["size"],
                    "through": through,
                    "start_utc": w["start"].isoformat(),
                    "end_utc": w["end"].isoformat(),
                },
            )
            written += 1
    return written


def fill_share(journal_events, shadow_events):
    """Our share of the contracts that traded at or through our price, up to
    each order's size, over the scored live windows (a measurement, not P&L)."""
    oid_of = {
        e.get("client_order_id"): str(e.get("order_id"))
        for e in journal_events
        if e.get("event") == "accepted" and e.get("order_id")
    }
    filled, seen = {}, set()
    for e in journal_events:
        if e.get("event") != "fill" or e.get("fill_id") in seen:
            continue
        seen.add(e.get("fill_id"))
        raw = e.get("count_fp") if e.get("count_fp") is not None else e.get("count")
        try:
            filled[str(e.get("order_id"))] = filled.get(
                str(e.get("order_id")), 0.0
            ) + float(raw)
        except (TypeError, ValueError):
            continue
    version = {
        e.get("client_order_id"): e.get("strategy_version")
        for e in journal_events
        if e.get("event") == "intent"
    }
    windows = {}
    for e in shadow_events:
        cid = e.get("client_order_id")
        if e.get("event") != "live_window" or not cid:
            continue
        if version.get(cid) != P.STRATEGY_VERSION:
            continue  # each rule version is measured on its own orders
        windows[cid] = e  # one per order
    capacity = got = cautious = 0.0
    scored = traded_through = filled_when_traded = 0
    for cid, e in windows.items():
        try:
            size, through = float(e.get("size") or 0), float(e.get("through") or 0)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(size) and math.isfinite(through)):
            continue  # an unusable record is left out, never guessed
        scored += 1
        mine = min(filled.get(oid_of.get(cid), 0.0), size)
        room = min(through, size)
        capacity += room
        got += min(mine, room)
        cautious += min(expected_fill(through, CAUTIOUS_FLOW, size), room)
        if through > 0:
            traded_through += 1
            filled_when_traded += mine > 0
    return {
        "orders_scored": scored,
        "orders_traded_through": traded_through,
        "orders_filled_when_traded_through": filled_when_traded,
        "first_in_line_contracts": round(capacity, 2),
        "filled_contracts": round(got, 2),
        "fill_share": round(got / capacity, 3) if capacity else None,
        "cautious_replay_share": round(cautious / capacity, 3) if capacity else None,
        "note": (
            "1.0 = the backtest's first-in-line assumption; cautious_replay_share = "
            "what the flow-share-0.25 replay would have filled on these same windows"
        ),
    }


# ------------------------------------------- standing and markouts (measurement)
# RESEARCH_LOG.md, 2026-10-23, "Spread maker queue position and markouts".
# Is the bot at the front at its price, and does the price move against its
# fills soon after (stale quotes picked off)? Read-only. Stored in their own
# file and summarised each pass into MEASURE_SUMMARY; never used for trading.
MEASURE_FILE = "measurements.jsonl"
MEASURE_SUMMARY = "measurements_summary.json"
MARKOUT_HORIZONS = (10, 30, 60)  # minutes after each fill
MARKOUT_LATE_MINUTES = 12  # observed at the first pass after the horizon
PAIRED_WITHIN_MINUTES = 60  # an earlier opposite fill this close: "paired"


def iter_measurements(path):
    """The measurement file, one record at a time, skipping any line that is
    not a JSON object (a torn last line after a crash must not stop it)."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


def load_measurements(path):
    return list(iter_measurements(path))


def write_measurement(path, record):
    """Append one record, first ending a torn last line if there is one."""
    if path.exists() and path.stat().st_size:
        with path.open("rb") as f:
            f.seek(-1, os.SEEK_END)
            torn = f.read(1) != b"\n"
        if torn:
            with path.open("a", encoding="utf-8") as f:
                f.write("\n")
    write_event(path, record)


def _version_orders(events):
    """{client_order_id: intent} for this rule version, and order id -> cid."""
    intents = {
        e.get("client_order_id"): e
        for e in events
        if e.get("event") == "intent"
        and e.get("strategy_version") == P.STRATEGY_VERSION
    }
    cid_of = {
        str(e.get("order_id")): e.get("client_order_id")
        for e in events
        if e.get("event") == "accepted"
        and e.get("order_id")
        and e.get("client_order_id") in intents
    }
    return intents, cid_of


def _number_or_none(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fills(events, cid_of):
    """This rule version's fills, once per fill id: (fill, cid, contracts,
    fee in cents per contract)."""
    out, seen = [], set()
    for e in events:
        fid = e.get("fill_id")
        cid = cid_of.get(str(e.get("order_id")))
        if e.get("event") != "fill" or not fid or fid in seen or cid is None:
            continue
        seen.add(fid)
        count = _number_or_none(
            e.get("count_fp") if e.get("count_fp") is not None else e.get("count")
        )
        if count is None or count <= 0 or _utc(e.get("utc")) is None:
            continue
        fee = _number_or_none(e.get("fee_cost"))
        # A fill without a fee record counts as fee 0 (counted in the summary).
        out.append((e, cid, count, None if fee is None else 100 * fee / count))
    return out


def _resting_at(events, intents, cid_of, at):
    """(ticker, side, price) of this version's orders that were resting at
    ``at``: placed before it, not cancelled or fully filled before it."""
    stamp = at.isoformat()
    gone = set()
    for e in events:
        if e.get("event") in ("cancel_accepted", "cancel_moot") and e.get("order_id"):
            when = _utc(e.get("utc"))
            if when is not None and when < at:
                gone.add(str(e["order_id"]))
    filled = Counter()
    for fill, _, count, _ in _fills(events, cid_of):
        if _utc(fill["utc"]) < at:
            filled[str(fill.get("order_id"))] += count
    since = (at - timedelta(minutes=P.ORDER_LIFETIME_MINUTES)).isoformat()
    return {
        (intents[cid]["ticker"], intents[cid]["side"], int(intents[cid]["price_cents"]))
        for oid, cid in cid_of.items()
        if since <= str(intents[cid].get("utc", "")) < stamp
        and oid not in gone
        and filled[oid] < float(intents[cid].get("count", 0)) - 1e-9
    }


def _best_bid(quote, side):
    """(best bid on one side, YES bid, YES ask) of a listing, in cents."""
    bid = _cents((quote or {}).get("yes_bid_dollars"))
    ask = _cents((quote or {}).get("yes_ask_dollars"))
    if bid is None or ask is None or not 0 < bid < ask < 100:
        return None, None, None
    return (bid if side == "yes" else 100 - ask), bid, ask


def record_markouts(state_dir, now, listings):
    """Price after each fill, from the side bought, in cents, at
    MARKOUT_HORIZONS minutes, from the public listing taken at the start of
    this pass (``now``):

    - ``adverse_move_cents``: the side's midpoint then minus its midpoint
      when the quote was posted (< 0: the price moved against the fill);
    - ``realized_spread_cents``: the midpoint then minus the price paid and
      the fee per contract (it includes the half-spread earned at entry);
    - ``exit_move_cents``: the side's best bid then minus the price paid,
      left empty when that best bid was the bot's own resting quote.

    Returns the number of records written."""
    journal, path = state_dir / "journal.jsonl", state_dir / MEASURE_FILE
    if not journal.exists():
        return 0
    events = load_events(journal)
    intents, cid_of = _version_orders(events)
    fills = _fills(events, cid_of)
    oldest = max(MARKOUT_HORIZONS) + MARKOUT_LATE_MINUTES + 10
    recent = {
        f["fill_id"]
        for f, *_ in fills
        if (now - _utc(f["utc"])).total_seconds() < oldest * 60
    }
    done = {
        (e.get("fill_id"), e.get("horizon_minutes"))
        for e in iter_measurements(path)
        if e.get("event") == "markout" and e.get("fill_id") in recent
    }
    quotes = {m.get("ticker"): m for ms in (listings or {}).values() for m in ms}
    own = _resting_at(events, intents, cid_of, now)
    written = 0
    for fill, cid, count, fee in fills:
        if fill["fill_id"] not in recent:
            continue
        fee = fee or 0.0
        intent = intents[cid]
        side, paid = intent.get("side"), int(intent.get("price_cents", 0))
        spread = _number_or_none(intent.get("spread"))
        start = _utc(intent.get("event_start_utc"))
        age = (now - _utc(fill["utc"])).total_seconds() / 60
        for horizon in MARKOUT_HORIZONS:
            if (fill["fill_id"], horizon) in done or age < horizon:
                continue
            record = {
                "event": "markout",
                "fill_id": fill["fill_id"],
                "client_order_id": cid,
                "ticker": intent.get("ticker"),
                "side": side,
                "price_cents": paid,
                "contracts": count,
                "fee_cents_per_contract": round(fee, 4),
                "spread_cents": spread,
                "horizon_minutes": horizon,
                "observed_after_minutes": round(age, 1),
                "minutes_before_start": None
                if start is None
                else round((start - now).total_seconds() / 60, 1),
                "utc": now.isoformat(),
                "adverse_move_cents": None,
                "realized_spread_cents": None,
                "exit_move_cents": None,
                "exit_is_own_quote": False,
                "issue": None,
            }
            quote = quotes.get(intent.get("ticker"))
            best, bid, ask = _best_bid(quote, side)
            if age > horizon + MARKOUT_LATE_MINUTES:
                record["issue"] = "missed_observation_window"
            elif quote is None:
                record["issue"] = "quote_unavailable"
            elif best is None:
                record["issue"] = "invalid_quote"
            else:
                mid = (bid + ask) / 2 if side == "yes" else 100 - (bid + ask) / 2
                record["realized_spread_cents"] = round(mid - paid - fee, 4)
                if spread is not None:
                    # Posted one cent above the best bid of a quote this wide.
                    record["adverse_move_cents"] = mid - (paid - 1 + spread / 2)
                if (intent.get("ticker"), side, best) in own:
                    record["exit_is_own_quote"] = True
                else:
                    record["exit_move_cents"] = best - paid
            write_measurement(path, record)
            written += 1
    return written


def standing(resting_intents, seen_books):
    """At the start of a pass, before any requote: for each of this version's
    resting orders whose book was read (our own orders taken out), is another
    bid on its side better (outbid: someone is ahead), equal (joined: behind
    us in time), or worse (alone at the front)? Returns counts."""
    out = Counter()
    for _, intent, _ in resting_intents:
        if intent.get("strategy_version") != P.STRATEGY_VERSION:
            continue
        book = seen_books.get(intent.get("ticker"))
        if book is None:
            continue
        bid, ask = book
        other = (
            bid if intent.get("side") == "yes" else (None if ask is None else 100 - ask)
        )
        price = int(intent["price_cents"])
        out["orders_checked"] += 1
        if other is not None and other > price:
            out["outbid"] += 1
        elif other is not None and other == price:
            out["joined"] += 1
        else:
            out["alone"] += 1
    return out


def _weighted_t(values, weights, clusters):
    """Weighted mean and its t clustered by ``clusters`` (the formula of
    research.fill_sizing_replay.clustered_mean_t)."""
    total = sum(weights)
    if total <= 0:
        return None, None
    mean = sum(w * v for v, w in zip(values, weights)) / total
    groups = {}
    for v, w, c in zip(values, weights, clusters):
        groups[c] = groups.get(c, 0.0) + w * (v - mean)
    g = len(groups)
    if g < 2:
        return round(mean, 2), None
    se = math.sqrt(sum(x * x for x in groups.values()) * g / (g - 1)) / total
    return round(mean, 2), (round(mean / se, 2) if se > 0 else None)


def summarize_measurements(journal_events, measure_events, now=None):
    """The numbers the research plan reads, for --status and the export.

    Markouts by horizon, observed before the start, weighted by contracts:
    for all fills, and for one-sided fills (no opposite-side fill in the same
    market in the PAIRED_WITHIN_MINUTES before it; looking only backwards, so
    a later fill caused by the price moving does not reclassify it).
    Standing: share of order checks in which the bot was outbid."""
    intents, cid_of = _version_orders(journal_events)
    fills = _fills(journal_events, cid_of)
    by_market = {}
    for fill, cid, *_ in fills:
        by_market.setdefault(intents[cid]["ticker"], []).append(
            (intents[cid]["side"], _utc(fill["utc"]))
        )
    paired = set()
    window = timedelta(minutes=PAIRED_WITHIN_MINUTES)
    for fill, cid, *_ in fills:
        side, when = intents[cid]["side"], _utc(fill["utc"])
        if any(
            s != side and timedelta(0) <= when - w <= window
            for s, w in by_market[intents[cid]["ticker"]]
        ):
            paired.add(fill["fill_id"])
    rows = {
        h: {"all": [], "one_sided": [], "issues": Counter()} for h in MARKOUT_HORIZONS
    }
    stand = Counter()
    measured = set()
    for e in measure_events:
        if e.get("event") == "standing":
            if e.get("strategy_version") != P.STRATEGY_VERSION:
                continue  # each rule version is measured on its own orders
            for key in ("orders_checked", "outbid", "joined", "alone"):
                stand[key] += int(e.get(key) or 0)
            continue
        h = e.get("horizon_minutes")
        if e.get("event") != "markout" or h not in rows:
            continue
        if e.get("client_order_id") not in intents:
            continue
        measured.add(e.get("fill_id"))
        if e.get("issue"):
            rows[h]["issues"][e["issue"]] += 1
        elif (e.get("minutes_before_start") or 0) <= 0:
            rows[h]["issues"]["observed_after_start"] += 1
        elif e.get("adverse_move_cents") is not None:
            intent = intents[e["client_order_id"]]
            row = (
                float(e["contracts"]),
                float(e["adverse_move_cents"]),
                float(e["realized_spread_cents"]),
                intent.get("event_ticker") or intent.get("ticker"),
            )
            rows[h]["all"].append(row)
            if e.get("fill_id") not in paired:
                rows[h]["one_sided"].append(row)

    def weighted(values, k):
        total = sum(r[0] for r in values)
        return round(sum(r[0] * r[k] for r in values) / total, 2) if total else None

    def t_of(values, k):
        return _weighted_t(
            [r[k] for r in values], [r[0] for r in values], [r[3] for r in values]
        )[1]

    markouts = {}
    for h, v in rows.items():
        markouts[f"{h}m"] = {
            "one_sided_fills": len(v["one_sided"]),
            "one_sided_adverse_move_cents": weighted(v["one_sided"], 1),
            "one_sided_adverse_move_t": t_of(v["one_sided"], 1),
            "one_sided_realized_spread_cents": weighted(v["one_sided"], 2),
            "one_sided_realized_spread_t": t_of(v["one_sided"], 2),
            "all_fills": len(v["all"]),
            "all_adverse_move_cents": weighted(v["all"], 1),
            "all_realized_spread_cents": weighted(v["all"], 2),
            "not_used": dict(v["issues"]),
        }
    oldest = max(MARKOUT_HORIZONS) + MARKOUT_LATE_MINUTES + 10
    unmeasured = [
        f
        for f, *_ in fills
        if f["fill_id"] not in measured
        and (now is None or (now - _utc(f["utc"])).total_seconds() >= oldest * 60)
    ]
    checked = stand["orders_checked"]
    return {
        "rules": P.STRATEGY_VERSION,
        "standing_checks": checked,
        "outbid_share": round(stand["outbid"] / checked, 3) if checked else None,
        "joined_share": round(stand["joined"] / checked, 3) if checked else None,
        "markouts": markouts,
        "fills": len(fills),
        "fills_never_measured": len(unmeasured),
        "fills_without_fee_record": sum(1 for *_, fee in fills if fee is None),
        "note": "Live measurements, not P&L. Standing: at each pass, before "
        "requotes, the share of resting orders with a better bid ahead of them "
        "(outbid) or another order at their price behind them (joined). "
        "Standing is a rate per 10-minute pass: an outbid order is re-quoted. "
        "Markouts: cents from the side bought, observed before the start, "
        "weighted by contracts; adverse move < 0 means the price moved against "
        "the fill; realized spread is after the fill's fee.",
    }


def write_measure_summary(state_dir):
    """Recompute and save the summary (atomic, streaming the file); returns it."""
    summary = summarize_measurements(
        load_events(state_dir / "journal.jsonl"),
        iter_measurements(state_dir / MEASURE_FILE),
        datetime.now(UTC),
    )
    target = state_dir / MEASURE_SUMMARY
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    temporary.chmod(0o600)
    temporary.replace(target)
    return summary


# ------------------------------------------------------------------ live


def guard(env, client):
    for name, expected in REQUIRED.items():
        if env.get(name) != expected:
            raise TradingError(f"Unarmed spread maker: {name} must be {expected}")
    if not P.ARM_MARKER.exists():
        raise TradingError("Owner has not enabled the spread maker")
    if not shared.dual_mode(env):
        raise TradingError("Spread maker requires shared-account mode")
    if client.env != "prod" or client.dry_run or not client.can_sign:
        raise TradingError("Signed production execution client required")


def armed(env):
    return env.get("SPREAD_AUTO_ARM") == "YES" and P.ARM_MARKER.exists()


def held_cost(positions, open_lots):
    """Dollars at risk in held contracts, at the price paid.

    ``open_lots`` (from the fill ledger) gives the price of each contract
    still held. Where it does not match the exchange's position (for
    example a fill not yet listed), every contract counts as $1.
    """
    total = 0.0
    for ticker, qty in positions.items():
        lots = open_lots.get(ticker, [])
        net = sum(count if side == "yes" else -count for side, _, count in lots)
        if abs(net - qty) < 1e-6:
            total += sum(price * count for _, price, count in lots)
        else:
            total += abs(qty)
    return round(total, 4)


def event_of(ticker):
    """Kalshi market tickers are the event ticker plus one suffix."""
    return str(ticker).rsplit("-", 1)[0]


def one_market_per_event(markets, positions, resting=frozenset()):
    """At most MAX_MARKETS_PER_EVENT markets of each event (v5). None (v6)
    means no limit: every market passes, as in the v6 replay.

    A market already held comes first, then one with our resting quotes,
    then the input order (widest spread first). A market whose event is held
    through a different market is dropped, wherever that market is listed.
    """
    if P.MAX_MARKETS_PER_EVENT is None:
        return list(markets)
    held = {}
    for ticker, qty in positions.items():
        if abs(qty) > 1e-9:
            held.setdefault(event_of(ticker), set()).add(ticker)

    def rank(m):
        if abs(positions.get(m["ticker"], 0.0)) > 1e-9:
            return 0
        return 1 if m["ticker"] in resting else 2

    chosen, count = [], Counter()
    for m in sorted(markets, key=rank):  # stable: keeps widest-first order
        event = m.get("event_ticker") or event_of(m["ticker"])
        if event in held and m["ticker"] not in held[event]:
            continue
        if count[event] >= P.MAX_MARKETS_PER_EVENT:
            continue
        count[event] += 1
        chosen.append(m)
    return chosen


def series_of(ticker):
    """Kalshi tickers start with their series, then a hyphen."""
    return str(ticker).split("-", 1)[0]


def quoted_sides(ticker, spread=None):
    """("yes", "no"); ("no",) for a NO-only series (v6, NCAA 1H spreads) or,
    from v8, when the market's ``spread`` in cents is known and narrower than
    MIN_YES_SPREAD_CENTS."""
    if series_of(ticker) in P.NO_ONLY_SERIES:
        return ("no",)
    if spread is not None and spread < P.MIN_YES_SPREAD_CENTS:
        return ("no",)
    return ("yes", "no")


def market_spread(m):
    """A quotable market's spread in cents: its own field, else from our two
    prices, each one cent inside (YES bid + 1 and 100 - YES ask + 1)."""
    spread = m.get("spread")
    return 102 - m["yes_price"] - m["no_price"] if spread is None else spread


def order_size(ticker):
    """Largest order on this market: the series' own size, else CONTRACTS."""
    return P.SERIES_CONTRACTS.get(series_of(ticker), P.CONTRACTS)


def net_cap(ticker):
    """Held plus resting on one side: the series' own cap, else
    MAX_NET_PER_MARKET."""
    return P.SERIES_MAX_NET.get(series_of(ticker), P.MAX_NET_PER_MARKET)


def desired_quotes(markets, positions, resting=frozenset()):
    """{(ticker, side): (price, contracts)} after the inventory cap.

    A YES order is at most the room left before net YES reaches the cap
    (positive net = YES held), a NO order likewise; a side with no room is
    not quoted. v5 quoted one market per event; v6 quotes them all, and only
    the NO side of a NO-only series. v8: only the NO side where the spread
    is under MIN_YES_SPREAD_CENTS.
    """
    out = {}
    for m in one_market_per_event(markets, positions, resting):
        net = positions.get(m["ticker"], 0.0)
        cap = net_cap(m["ticker"])
        rooms = {
            "yes": math.floor(cap - net + 1e-9),
            "no": math.floor(cap + net + 1e-9),
        }
        prices = {"yes": m["yes_price"], "no": m["no_price"]}
        for side in quoted_sides(m["ticker"], market_spread(m)):
            size = int(min(order_size(m["ticker"]), rooms[side]))
            if size >= 1:
                out[(m["ticker"], side)] = (prices[side], size)
    return out


def remaining_count(order, intent, fills):
    """Contracts still resting on one of our orders: the exchange's
    remaining count, else the order size less its listed fills."""
    raw = order.get("remaining_count_fp", order.get("remaining_count"))
    size = float(intent["count"])
    if raw is None:
        done = 0.0
        for f in fills:
            if str(f.get("order_id")) == str(order.get("order_id")):
                try:
                    done += float(f.get("count_fp", f.get("count")))
                except (TypeError, ValueError) as error:
                    raise TradingError("Unreadable spread fill count: HALT") from error
        return max(0.0, size - done)
    try:
        left = float(raw)
    except (TypeError, ValueError) as error:
        raise TradingError("Unreadable spread resting count: HALT") from error
    if not math.isfinite(left) or left < 0 or left > size + 1e-9:
        raise TradingError("Spread resting count disagrees with journal: HALT")
    return left


def cancel_order(client, journal, order_id, ticker, reason, now, expected=None):
    """Cancel one owned quote. Returns "canceled"; "moot" when the order had
    already filled or expired (a signed read shows it is gone, or the
    exchange cancelled nothing); or "partial" when the exchange cancelled
    fewer contracts than ``expected`` were resting (or did not say how many):
    some filled after the account was read."""
    write_event(
        journal,
        {
            "event": "cancel_intent",
            "utc": now.isoformat(),
            "order_id": order_id,
            "ticker": ticker,
            "reason": reason,
        },
    )
    try:
        result = client.cancel(order_id, ticker=ticker)
    except Exception as error:
        # A quote can fill or expire between our read and the cancel. Accept
        # that only when a signed read shows the order is no longer resting.
        if is_http_4xx(error) is not None:
            still = [
                o
                for o in client.orders("resting", ticker=ticker)
                if str(o.get("order_id")) == str(order_id)
            ]
            if not still:
                write_event(
                    journal,
                    {
                        "event": "cancel_moot",
                        "utc": datetime.now(UTC).isoformat(),
                        "order_id": order_id,
                        "detail": str(error)[:200],
                    },
                )
                return "moot"
        raise TradingError("Cannot confirm spread cancellation: HALT") from error
    raw = result.get("reduced_by") if isinstance(result, dict) else None
    try:
        reduced = float(raw)
        if not math.isfinite(reduced):
            reduced = None
    except (TypeError, ValueError):
        reduced = None
    if reduced is not None and reduced <= 1e-9:
        outcome = "moot"
    elif expected is not None and (reduced is None or reduced < expected - 1e-9):
        outcome = "partial"
    else:
        outcome = "canceled"
    write_event(
        journal,
        {
            "event": "cancel_moot" if outcome == "moot" else "cancel_accepted",
            "utc": datetime.now(UTC).isoformat(),
            "order_id": order_id,
            "reduced_by": raw,
            "expected": expected,
            **({"detail": "reduced_by_zero"} if outcome == "moot" else {}),
        },
    )
    return outcome


def cancel_all_owned(client, journal, resting, reason, now):
    for order in resting:
        cancel_order(client, journal, order["order_id"], order["ticker"], reason, now)
    return len(resting)


def record_execution(journal, events, owned_orders, fills, settlements, tickers):
    """Copy this bot's fills and settlements into its journal (for --status)."""
    seen_fills = {e.get("fill_id") for e in events if e.get("event") == "fill"}
    seen_settled = {
        (e.get("ticker"), e.get("utc"))
        for e in events
        if e.get("event") == "settlement"
    }
    for fill in fills:
        oid = str(fill.get("order_id"))
        fid = fill.get("fill_id") or fill.get("trade_id")
        if not fid or str(fid) in seen_fills or oid not in owned_orders:
            continue
        write_event(
            journal,
            {
                "event": "fill",
                "fill_id": str(fid),
                "order_id": oid,
                "utc": fill.get("created_time"),
                "ticker": fill.get("ticker") or fill.get("market_ticker"),
                **{
                    key: fill[key]
                    for key in (
                        "side",
                        "action",
                        "outcome_side",
                        "book_side",
                        "count_fp",
                        "count",
                        "yes_price_dollars",
                        "no_price_dollars",
                        "fee_cost",
                        "is_taker",
                    )
                    if fill.get(key) is not None
                },
            },
        )
        seen_fills.add(str(fid))
    for item in settlements:
        ticker = item.get("market_ticker") or item.get("ticker")
        key = (ticker, str(item.get("settled_time", "")))
        if ticker not in tickers or key in seen_settled:
            continue
        write_event(
            journal,
            {
                "event": "settlement",
                "ticker": ticker,
                "utc": key[1],
                "market_result": item.get("market_result"),
                **nfl_policy.settlement_accounting(item),
            },
        )
        seen_settled.add(key)


def journal_ledger(events, now):
    """The fill ledger from the journal's own copies only (no exchange reads)."""
    return shared.spread_ledger(events, [], [], now)


def is_http_4xx(error):
    match = re.search(r"-> HTTP ([0-9]{3})", str(error))
    return int(match.group(1)) if match and match.group(1).startswith("4") else None


def find_order(client, ticker, client_order_id):
    """Our order with this client id in any status, from signed reads."""
    for status in ("resting", "executed", "canceled"):
        for order in client.orders(status, ticker=ticker):
            if order.get("client_order_id") == client_order_id:
                return order
    return None


CLIENT_ID_PREFIX = "smm-spread-"  # NBA/NFL ids are smm-<uuid4>: never "smm-s..."


def order_start(intent, starts=None):
    """The earliest start known for a resting order's event: the one
    recorded when it was placed, or a current one."""
    found = [
        t
        for t in (
            _utc(intent.get("event_start_utc")),
            event_start(intent.get("event_ticker", ""), starts),
        )
        if t is not None
    ]
    return min(found) if found else None


def with_recorded_starts(starts, intents, now):
    """``starts`` with each event's start lowered to the earliest one recorded
    with this bot's orders of the last two days: the journal is written
    before every order, so this survives a lost or unwritable start cache.
    It never supplies a start for an event that has none this pass."""
    since = (now - timedelta(days=2)).isoformat()
    recorded = {}
    for intent in intents:
        event = intent.get("event_ticker")
        if not isinstance(event, str) or not event:
            continue
        if str(intent.get("utc", "")) < since:
            continue
        try:
            when = datetime.fromisoformat(str(intent.get("event_start_utc")))
        except ValueError:
            continue
        if when.tzinfo is not None:
            recorded[event] = min(recorded.get(event, when), when)
    out = dict(starts or {})
    for event, when in recorded.items():
        current = event_start(event, out)
        if current is not None and when < current:
            out[event] = when
    return out


def quote_expiry(now, market):
    """65 minutes, and never later than CANCEL_LEAD_MINUTES before the start."""
    expires = now + timedelta(minutes=P.ORDER_LIFETIME_MINUTES)
    start = _utc(market.get("event_start_utc"))
    if start is not None:
        expires = min(expires, start - timedelta(minutes=P.CANCEL_LEAD_MINUTES))
    return expires


def place_quote(
    client, journal, market, side, price, now, require_shard, deadline=None, size=None
):
    """Journal, place, and record one post-only quote. Returns the outcome.

    Nothing before the intent sends an order, so a failed shard check only
    stops this pass's placements ("shard_check_failed"); from the intent on,
    anything but a proven outcome is an unknown outcome.
    """
    order = Order(
        ticker=market["ticker"],
        side=side,
        count=int(size or P.CONTRACTS),
        price_cents=int(price),
        expiration_ts=int(quote_expiry(now, market).timestamp()),
        post_only=True,
        client_order_id=f"{CLIENT_ID_PREFIX}{uuid.uuid4()}",
    )
    cost = round(order.count * price / 100, 2)
    try:
        order.exchange_index = require_shard(client, order.ticker, cost)
    except Exception as error:
        if str(error).startswith("SHARD_UNFUNDED_"):
            return "shard_unfunded"
        if isinstance(error, TradingError) and "HALT" in str(error):
            raise
        return "shard_check_failed"  # a read failed; no order was sent
    if out_of_time(deadline):
        return "out_of_time"
    write_event(
        journal,
        {
            "event": "intent",
            "utc": now.isoformat(),
            "client_order_id": order.client_order_id,
            "ticker": order.ticker,
            "series": market["series"],
            "event_ticker": market["event_ticker"],
            "event_start_utc": market.get("event_start_utc"),
            "side": side,
            "price_cents": int(price),
            "count": order.count,
            "cost": cost,
            "spread": market["spread"],
            "market_expiration_utc": market["expiration_utc"],
            "expires_utc": datetime.fromtimestamp(order.expiration_ts, UTC).isoformat(),
            "strategy_version": P.STRATEGY_VERSION,
        },
    )
    # From here on, anything but a proven outcome is an unknown outcome.
    try:
        try:
            result = client.place(order)
        except Exception as error:
            status = is_http_4xx(error)
            if status is None:
                raise
            # The exchange refused the request. Confirm with signed reads that
            # no such order exists in any status before treating it as never
            # placed.
            found = find_order(client, order.ticker, order.client_order_id)
            if found is None:
                write_event(
                    journal,
                    {
                        "event": "rejected_4xx",
                        "utc": datetime.now(UTC).isoformat(),
                        "client_order_id": order.client_order_id,
                        "http_status": status,
                        "evidence": shared.SPREAD_REJECTION_EVIDENCE,
                        "detail": str(error)[:200],
                    },
                )
                return "rejected"
            result = {"order_id": found.get("order_id")}
        if not isinstance(result, dict) or not result.get("order_id"):
            raise TradingError("Spread placement returned no order id")
    except Exception as error:
        write_event(
            journal,
            {
                "event": "unknown_outcome",
                "utc": datetime.now(UTC).isoformat(),
                "client_order_id": order.client_order_id,
                "type": type(error).__name__,
            },
        )
        raise TradingError(
            "Ambiguous spread submission: all bots halt until the owner runs "
            "setup_spread_maker.sh --reconcile"
        ) from error
    write_event(
        journal,
        {
            "event": "accepted",
            "utc": datetime.now(UTC).isoformat(),
            "client_order_id": order.client_order_id,
            "order_id": str(result["order_id"]),
        },
    )
    return "accepted"


class PassShardFunding:
    """``require_funded_shard`` with one balance read per pass.

    Kalshi refuses a balance read repeated within about a second, so the bot
    reads the per-shard balance once, then charges each order it sends this
    pass against its market's shard. The pass holds the shared account lock,
    so no other bot spends in between. Signed GETs only.
    """

    def __init__(self):
        self.breakdown = None
        self.reserved = {}

    def __call__(self, client, ticker, cost):
        from decimal import Decimal, InvalidOperation
        from urllib.parse import quote

        if not isinstance(ticker, str) or not ticker.startswith("KX"):
            raise TradingError("Invalid market ticker for shard routing")
        try:
            required = Decimal(str(cost))
        except (TypeError, InvalidOperation) as error:
            raise TradingError("Invalid reserved dollar amount") from error
        if not required.is_finite() or required <= 0:
            raise TradingError("Invalid reserved dollar amount")
        market = client._request("GET", f"/markets/{quote(ticker, safe='')}")
        shard = shard_funding.verify_market_shard(market)
        if market["market"].get("ticker") != ticker:
            raise TradingError("Market ticker mismatch in shard routing: HALT")
        if self.breakdown is None:
            self.breakdown = client._request("GET", "/portfolio/balance")
        used = self.reserved.get(shard, Decimal(0))
        if shard_funding.shard_balance(self.breakdown, shard) - used < required:
            raise TradingError(
                f"SHARD_UNFUNDED_{shard}: Kalshi account funds are not allocated "
                "to this matching engine; no order was sent."
            )
        self.reserved[shard] = used + required
        return shard


def fresh_prices(public, ticker, own=()):
    """Our quote prices from a fresh read of the book, without our own quotes."""
    market = public.get("quote_market", public["fetch_market"])(ticker) or {}
    if market.get("status") not in ("active", "open"):
        return None
    book = public.get("quote_orderbook", public["fetch_orderbook"])(ticker)
    return quote_prices(*book_quote(book, own))


# Set by SIGTERM (systemd's timeout): finish the order in flight, place no more.
STOP = {"requested": False}
PROCESS_START = time.monotonic()


def _request_stop(signum, frame):
    STOP["requested"] = True


def out_of_time(deadline):
    return STOP["requested"] or (deadline is not None and time.monotonic() > deadline)


def pass_live(client, env, now, state_dir, public, require_shard=None, deadline=None):
    """One live pass: (report for last_scan.json, eligible markets or None).

    Any halt first cancels this bot's provably owned resting orders.
    """
    guard(env, client)
    journal = state_dir / "journal.jsonl"
    try:
        return _pass_live(client, now, journal, public, require_shard, deadline)
    except Exception as error:
        if not transient(error):
            try:
                cancel_owned_on_kill(client, journal, reason="halt")
            except Exception:
                pass  # the original failure is what the owner needs to see
        raise


def transient(error):
    """A read that timed out or was throttled: quotes stay (they expire on
    the exchange within 65 minutes) and the next pass checks again. Any
    other failure, including every ambiguous order, cancels them."""
    if isinstance(error, OSError):
        return True
    return isinstance(error, TradingError) and bool(
        re.search(r"-> HTTP (429|5[0-9][0-9])\b", str(error))
    )


def _pass_live(client, now, journal, public, require_shard, deadline):
    require_shard = require_shard or PassShardFunding()
    events = load_events(journal)
    intents, accepted, _ = records(events)
    state, context = shared.state_for(client, "spread", now)
    order_to_cid = {oid: cid for cid, oid in accepted.items()}
    own_tickers = {i["ticker"] for i in intents.values()}
    record_execution(
        journal,
        events,
        set(order_to_cid),
        state["fills"],
        state["settlements"],
        own_tickers,
    )
    report = Counter()
    resting = [
        {**o, "order_id": str(o["order_id"]), "ticker": o.get("ticker")}
        for o in state["resting"]
    ]
    ledger = state["ledger"]
    if ledger.get("unavailable"):
        raise TradingError(f"Spread P&L unverifiable ({ledger['unavailable']})")
    daily, total = ledger["daily"], ledger["cumulative"]
    if daily <= -P.DAILY_LOSS_STOP + 1e-9 or total <= -P.CUMULATIVE_LOSS_STOP + 1e-9:
        report["canceled"] = cancel_all_owned(
            client, journal, resting, "loss_stop", now
        )
        return {
            "decision": "spread_loss_stop",
            "daily": daily,
            "total": total,
            **report,
        }, None
    if shared.account_loss_stop(context):
        report["canceled"] = cancel_all_owned(
            client, journal, resting, "account_loss_stop", now
        )
        return {"decision": "account_loss_stop", **report}, None
    others = {
        t for t, cohort in context["ownership"]["tickers"].items() if cohort != "spread"
    }
    resting_intents = []
    own = {}
    for order in resting:
        intent = intents.get(order_to_cid.get(order["order_id"]))
        if intent is None:
            raise TradingError("Resting order missing from spread journal: HALT")
        left = remaining_count(order, intent, state["fills"])
        resting_intents.append((order, intent, left))
        # Only what is still resting is in the book (after a partial fill).
        own.setdefault(intent["ticker"], []).append(
            (intent["side"], int(intent["price_cents"]), left)
        )
    unreadable = set()
    reasons = Counter()
    starts = with_recorded_starts(public.get("event_starts"), intents.values(), now)
    seen_books = {}
    markets = universe(
        public["fetch_markets"],
        now,
        others,
        own,
        public.get("quote_orderbook", public["fetch_orderbook"]),
        unreadable,
        starts,
        reasons,
        seen_books,
    )
    try:  # measurement only: whether anyone got ahead of our resting quotes
        counts = standing(resting_intents, seen_books)
        if counts:
            report.update({f"standing_{k}": v for k, v in counts.items()})
            write_measurement(
                journal.parent / MEASURE_FILE,
                {
                    "event": "standing",
                    "utc": now.isoformat(),
                    "strategy_version": P.STRATEGY_VERSION,
                    **counts,
                },
            )
    except Exception as error:
        report["standing_error"] = type(error).__name__
    by_ticker = {m["ticker"]: m for m in markets}
    positions = state["positions"]
    wanted = desired_quotes(
        markets, positions, {intent["ticker"] for _, intent, _ in resting_intents}
    )
    # Cancel quotes that are stale, too old, or no longer wanted.
    keep = {}
    just_filled = set()
    oldest = (now - timedelta(minutes=P.ORDER_LIFETIME_MINUTES - 5)).isoformat()
    unseen = 0.0  # contracts that may have filled since the account read
    cutoff = timedelta(minutes=P.CANCEL_LEAD_MINUTES)
    for order, intent, left in resting_intents:
        key = (intent["ticker"], intent["side"])
        start = order_start(intent, starts)
        if start is None or now >= start - cutoff:
            # Pregame only: nothing rests into an event's start, whatever the
            # book says (an order placed by v1 has no recorded start).
            outcome = cancel_order(
                client,
                journal,
                order["order_id"],
                intent["ticker"],
                "event_start",
                now,
                expected=left,
            )
            report["canceled"] += 1
            report["canceled_event_start"] += 1
            if outcome in ("moot", "partial"):
                just_filled.add(intent["ticker"])
                unseen += left * int(intent["price_cents"]) / 100
            continue
        if intent["ticker"] in unreadable and key not in keep:
            # Book unreadable this pass: leave the quote alone (it expires
            # on the exchange); nothing new goes into that market.
            keep[key] = (intent, left)
            report["held_book_unreadable"] += 1
            continue
        price, size = wanted.get(key, (None, 0))
        # Keep a quote at the right price whose remaining contracts still
        # fit the inventory room (a partly filled order keeps its place in
        # the queue and is not topped up).
        if (
            price == intent["price_cents"]
            and 0 < left <= size + 1e-9
            and intent["utc"] > oldest
            and key not in keep
        ):
            keep[key] = (intent, left)
            continue
        outcome = cancel_order(
            client,
            journal,
            order["order_id"],
            intent["ticker"],
            "requote",
            now,
            expected=left,
        )
        report["canceled"] += 1
        if outcome in ("moot", "partial"):
            # Some or all of it filled after the account read: positions are
            # stale for this market, so leave it until the next pass reads
            # them again, and count what may now be held.
            just_filled.add(intent["ticker"])
            unseen += left * int(intent["price_cents"]) / 100
    # Exposure: kept resting quotes at cost plus held contracts at cost.
    exposure = (
        sum(left * int(i["price_cents"]) / 100 for i, left in keep.values())
        + held_cost(positions, ledger["open"])
        + unseen
    )
    today = now.astimezone(NY).date()
    submitted_today = sum(
        datetime.fromisoformat(i["utc"]).astimezone(NY).date() == today
        for i in intents.values()
    )
    placed = 0
    # Our quotes resting in each market (kept, then placed this pass), taken
    # out of every fresh book read.
    mine = {}
    for (ticker, _), (intent, left) in keep.items():
        mine.setdefault(ticker, []).append(
            (intent["side"], int(intent["price_cents"]), left)
        )
    for (ticker, side), (price, size) in wanted.items():
        if (ticker, side) in keep:
            continue
        if not by_ticker[ticker].get("postable"):
            report["skip_near_start"] += 1  # resting quotes stay; no new one
            continue
        if ticker in just_filled:
            report["skip_just_filled"] += 1
            continue
        if out_of_time(deadline):
            report["skip_out_of_time"] += 1
            break
        if placed >= P.MAX_ORDERS_PER_PASS:
            report["skip_pass_cap"] += 1
            break
        if submitted_today + placed >= P.MAX_SUBMISSIONS_PER_DAY:
            report["skip_daily_cap"] += 1
            break
        cost = size * price / 100
        if exposure + cost > P.MAX_ACTIVE_COST + 1e-9:
            report["skip_active_cap"] += 1
            continue
        try:
            fresh = fresh_prices(public, ticker, mine.get(ticker, []))
        except Exception:
            fresh = None
        if fresh is None or fresh[0 if side == "yes" else 1] != price:
            report["skip_quote_moved"] += 1
            continue
        # The pass start time: expirations are then a little early, never late.
        outcome = place_quote(
            client,
            journal,
            by_ticker[ticker],
            side,
            price,
            now,
            require_shard,
            deadline,
            size,
        )
        report[outcome] += 1
        if outcome in ("shard_unfunded", "shard_check_failed", "out_of_time"):
            break
        placed += 1
        if outcome == "accepted":
            exposure += cost
            mine.setdefault(ticker, []).append((side, int(price), float(size)))
    report.update({f"markets_{k}": v for k, v in reasons.items()})
    return {
        "decision": "quoted",
        "eligible_markets": len(markets),
        "resting_kept": len(keep),
        "placed": placed,
        "exposure_dollars": round(exposure, 2),
        "realized_today": daily,
        "realized_total": total,
        **report,
    }, markets


def cancel_owned_on_kill(client, journal, reason="kill"):
    """Cancel every resting order this bot provably placed (by order id or
    client id in its journal, or this bot's client-id prefix); leave every
    other order alone. Works even when the journal cannot be read: then it
    cancels by prefix and writes nothing to the damaged journal."""
    try:
        events = load_events(journal)
    except TradingError:
        events = None
    ids = {str(e["order_id"]) for e in events or [] if e.get("event") == "accepted"}
    cids = {e["client_order_id"] for e in events or [] if e.get("event") == "intent"}
    now = datetime.now(UTC)
    canceled, failed = 0, []
    for item in client.orders("resting"):
        cid = str(item.get("client_order_id") or "")
        if (
            str(item.get("order_id")) not in ids
            and cid not in cids
            and not cid.startswith(CLIENT_ID_PREFIX)
        ):
            continue
        try:
            if events is None:
                client.cancel(item["order_id"], ticker=item["ticker"])
            else:
                cancel_order(
                    client, journal, item["order_id"], item["ticker"], reason, now
                )
            canceled += 1
        except Exception as error:  # one failure must not stop the rest
            if is_http_4xx(error) is None and not isinstance(error, TradingError):
                failed.append(type(error).__name__)
            elif is_http_4xx(error) is None:
                failed.append(str(error)[:80])
    print(f"SPREAD MAKER {reason.upper()}: canceled {canceled} owned resting orders")
    if failed:
        raise TradingError(f"Could not cancel {len(failed)} spread orders: {failed}")
    return canceled


def reconcile(client, journal, now):
    """Owner-run resolution of orders whose outcome the journal cannot prove.

    Signed GET only. An order found with the client id in any status is
    recorded as accepted; one absent from every status at least 10 minutes
    after its intent is recorded as never placed. Anything newer is left
    for a later run. Places and cancels nothing.
    """
    events = load_events(journal)
    intents, accepted, refused = _intents(events)
    summary = Counter()
    pending = [i for c, i in intents.items() if c not in accepted and c not in refused]
    for intent in sorted(pending, key=lambda i: i["utc"]):
        cid = intent["client_order_id"]
        found = find_order(client, intent["ticker"], cid)
        if found is not None and not found.get("order_id"):
            summary["found_without_order_id_check_by_hand"] += 1
            continue
        if found is not None:
            write_event(
                journal,
                {
                    "event": "accepted",
                    "utc": now.isoformat(),
                    "client_order_id": cid,
                    "order_id": str(found["order_id"]),
                    "reconciled": "owner_signed_lookup",
                },
            )
            summary["found_on_exchange"] += 1
            continue
        age = int((now - datetime.fromisoformat(intent["utc"])).total_seconds())
        if age < shared.SPREAD_ABSENT_MIN_AGE_SECONDS:
            summary["too_recent_try_again_later"] += 1
            continue
        write_event(
            journal,
            {
                "event": "reconciled_absent",
                "utc": now.isoformat(),
                "client_order_id": cid,
                "evidence": shared.SPREAD_ABSENT_EVIDENCE,
                "intent_age_seconds": age,
            },
        )
        summary["never_placed"] += 1
    try:
        records(load_events(journal))
        summary["bots_can_trade"] = True
    except TradingError as error:
        summary["bots_can_trade"] = False
        summary["still_blocked_by"] = str(error)
    return dict(summary)


# ------------------------------------------------------------------ main


def _quick(path):
    """One public read with a single attempt: used while holding the account
    lock, where a slow read must not eat into the other bots' time."""
    return kalshi_api.get_json(path, {}, retries=1)


def window_trades(ticker, min_ts, max_ts):
    """Trade prints for scoring live windows: single-attempt reads, so a
    slow or throttled endpoint costs one try and the window waits a pass."""
    rows = kalshi_api.trades(ticker, min_ts, max_ts, historical=False, retries=1)
    return rows or kalshi_api.trades(ticker, min_ts, max_ts, historical=True, retries=1)


def fetch_milestones(event_ticker):
    """Kalshi milestones tied to an event (public read, one attempt)."""
    return kalshi_api.get_json(
        "/milestones",
        {"related_event_ticker": event_ticker, "limit": 100},
        retries=1,
        timeout=10,
    )


def shadow_market(ticker):
    """A market's result for the shadow ledger: single attempts, live then
    historical endpoint."""
    for path in (f"/markets/{ticker}", f"/historical/markets/{ticker}"):
        payload = _quick(path)
        if payload and payload.get("market"):
            return payload["market"]
    return None


def quote_market(ticker):
    payload = _quick(f"/markets/{ticker}") or {}
    return payload.get("market")


def quote_orderbook(ticker):
    payload = _quick(f"/markets/{ticker}/orderbook") or {}
    book = payload.get("orderbook_fp")
    return book if isinstance(book, dict) else None


def exchange_paused(now, read_status=None):
    """Why to skip this pass's live part, or None (spread_policy
    KALSHI_MAINTENANCE; RESEARCH_LOG.md "Spread maker v7: esports only").

    Kalshi's weekly maintenance window by the clock, then (when given) its
    exchange status: anything but exchange_active and trading_active both
    true, or a status that cannot be read, skips the pass. Skipping sends
    nothing at all; resting quotes expire on the exchange within 65 minutes
    and the next pass, 10 minutes later, checks again."""
    if P.KALSHI_MAINTENANCE is not None:
        weekday, (h0, m0), (h1, m1) = P.KALSHI_MAINTENANCE
        local = now.astimezone(NY)
        minute = local.hour * 60 + local.minute
        if local.weekday() == weekday and h0 * 60 + m0 <= minute < h1 * 60 + m1:
            return "kalshi_weekly_maintenance"
    if read_status is None:
        return None
    try:
        status = read_status()
    except Exception:
        return "exchange_status_unreadable"
    if not isinstance(status, dict) or not (
        status.get("exchange_active") is True and status.get("trading_active") is True
    ):
        return "exchange_paused"
    return None


def exchange_status():
    """Kalshi's public exchange status (one attempt; no credentials)."""
    return kalshi_api.get_json("/exchange/status", {}, retries=1)


def public_api():
    return {
        "exchange_status": exchange_status,  # v7: skip passes while paused
        "fetch_markets": kalshi_api.fetch_markets,
        "fetch_market": kalshi_api.fetch_market,  # shadow results (any age)
        "fetch_orderbook": kalshi_api.fetch_orderbook,
        "fetch_trades": kalshi_api.fetch_trades,
        "window_trades": window_trades,  # live fill share, one attempt per read
        "shadow_trades": window_trades,  # shadow ledger, one attempt per read
        "shadow_market": shadow_market,
        "fetch_milestones": fetch_milestones,  # event start times (v2)
        "quote_market": quote_market,  # live quoting, under the lock
        "quote_orderbook": quote_orderbook,
    }


def write_report(state_dir, report):
    target = state_dir / "last_scan.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, default=str) + "\n")
    temporary.chmod(0o600)
    temporary.replace(target)


def preflight(client, env, now, state_dir, public):
    """Signed GET-only readiness check before arming. Never places or cancels.

    Checks production settings (except this bot's arm switch), that the
    spread journal reconciles, that all three bots' journals together own
    every order and position in the account, that the fill ledger accounts
    for every fill, and how many markets qualify right now. Prints counts
    only: no balances, ids or prices.
    """
    failures = []
    for name in ("KALSHI_ENV", "ALLOW_PRODUCTION_TRADING"):
        if env.get(name) != REQUIRED[name]:
            failures.append(f"{name} is not {REQUIRED[name]}")
    if not shared.dual_mode(env):
        failures.append("shared-account mode is off")
    if client.env != "prod" or not client.can_sign:
        failures.append("no signed production client")
    if failures:
        return {"ready": False, "failures": failures}
    journal = state_dir / "journal.jsonl"
    journal.touch(mode=0o600, exist_ok=True)
    intents, accepted, refused = records(load_events(journal))
    state, context = shared.state_for(client, "spread", now)
    for sport in ("nba", "nfl"):
        shared.state_for(client, sport, now)  # the other bots still reconcile
    if state["ledger"].get("unavailable"):
        return {"ready": False, "failures": [state["ledger"]["unavailable"]]}
    others = {
        t for t, cohort in context["ownership"]["tickers"].items() if cohort != "spread"
    }
    reasons = Counter()
    markets = universe(
        public["fetch_markets"],
        now,
        others,
        starts=public.get("event_starts"),
        reasons=reasons,
    )
    return {
        "ready": True,
        "failures": [],
        "armed": armed(env),
        "spread_orders_journaled": len(intents),
        "spread_resting": len(state["resting"]),
        "spread_markets_held": len(state["positions"]),
        "spread_fills": state["ledger"]["fills"],
        "account_loss_stop": bool(shared.account_loss_stop(context)),
        "eligible_markets_now": sum(bool(m.get("postable")) for m in markets),
        "wide_markets_without_event_start": reasons["no_event_start"],
        "wide_markets_starting_now": reasons["event_starting"],
        "milestone_check": public.get("milestone_check"),
    }


def milestone_check(public, now, limit=10, deadline=None):
    """Compare Kalshi's milestone starts with the time written in event
    tickers, for up to ``limit`` events in the window (one per series first):
    a check, before arming, that milestones give the scheduled start. Counts
    and minutes only. Run it before taking the account lock."""
    timed = {}
    for markets in (public.get("listings") or {}).values():
        for m in markets:
            event, expires = (
                m.get("event_ticker"),
                _utc(m.get("expected_expiration_time")),
            )
            if expires is None or ticker_start(event) is None:
                continue
            if 0 <= (expires - now).total_seconds() / 3600 <= P.WINDOW_HOURS[1]:
                timed[event] = min(timed.get(event, expires), expires)
    _, picks = _check_order(timed, now)
    picks += [p for p in sorted(timed.items()) if p not in picks]
    out = Counter()
    late, kinds = [], Counter()
    for event, expires in picks[:limit]:
        if out_of_time(deadline):
            break
        out["events_compared"] += 1
        try:
            found = milestone_starts(event, expires, public["fetch_milestones"])
        except Exception:
            found = []
        if not found:
            out["no_milestone"] += 1
            continue
        for start, kind in found:
            gap = (start - ticker_start(event)).total_seconds() / 60
            kinds[kind or "unknown"] += 1
            if gap > P.MILESTONE_LATE_MINUTES:
                out["later_than_ticker"] += 1
                late.append(gap)
            elif gap >= -P.MILESTONE_AGREE_MINUTES:
                out["matched"] += 1
            else:
                out["earlier_than_ticker"] += 1
    return {
        "events_compared": out["events_compared"],
        "no_milestone": out["no_milestone"],
        "matched": out["matched"],
        "later_than_ticker": out["later_than_ticker"],
        "earlier_than_ticker": out["earlier_than_ticker"],
        "largest_late_minutes": round(max(late), 1) if late else None,
        "milestone_types": dict(sorted(kinds.items())),
    }


def status(state_dir):
    """Offline summary from this bot's own files. Live and shadow results are
    reported separately and must never be added together."""
    events = load_events(state_dir / "journal.jsonl")
    count = Counter(e.get("event") for e in events)
    print(
        f"LIVE orders: {count['intent']} sent, {count['accepted']} accepted, "
        f"{count['rejected_4xx'] + count['reconciled_absent']} never placed, "
        f"{count['fill']} fills"
    )
    try:
        ledger = journal_ledger(events, datetime.now(UTC))
        print(
            f"LIVE realized P&L (from fills): today ${ledger['daily']:+.2f}, "
            f"total ${ledger['cumulative']:+.2f}; "
            f"{len(ledger['settled'])} markets settled, "
            f"{len(ledger['open'])} still held"
        )
    except TradingError as error:
        print(f"LIVE realized P&L unavailable: {error}")
    shadow_events = load_events(state_dir / "shadow.jsonl")
    share = fill_share(events, shadow_events)
    dash = "—"
    print(
        f"LIVE fill share: {dash if share['fill_share'] is None else share['fill_share']} "
        f"of {share['first_in_line_contracts']:g} contracts traded at or through our "
        f"price ({share['orders_scored']} finished orders scored; first in line = 1.0, "
        f"cautious replay = "
        f"{dash if share['cautious_replay_share'] is None else share['cautious_replay_share']})"
    )
    qm = summarize_measurements(events, iter_measurements(state_dir / MEASURE_FILE))

    def show(value, spec="+.2f"):
        return dash if value is None else f"{value:{spec}}"

    print(
        f"LIVE standing: {qm['standing_checks']} resting-order checks; outbid "
        f"{show(qm['outbid_share'], '.2f')}, joined {show(qm['joined_share'], '.2f')}"
    )
    print(
        "LIVE markouts (one-sided fills before the start, cents, < 0 = moved "
        "against the fill): "
        + "; ".join(
            f"{h} {show(m['one_sided_adverse_move_cents'])} "
            f"({m['one_sided_fills']} fills)"
            for h, m in qm["markouts"].items()
        )
    )
    print(
        "SHADOW (simulated, first in line unless flow-weighted):",
        json.dumps(shadow_summary(shadow_events)),
    )
    last = state_dir / "last_scan.json"
    if last.exists():
        print("Last pass:", last.read_text())


def prefetch(public):
    """Read every series' open markets once, before taking the account lock,
    so the other bots wait only for the signed part of a pass."""
    listings = {}
    for series in P.SERIES:
        if STOP["requested"]:
            break
        if series in P.NO_START_SERIES:
            continue  # never quoted (a resting quote there is cancelled)
        try:
            listings[series] = public["fetch_markets"](series, status="open") or []
        except Exception:  # one bad series must not stop the others
            continue
    return {
        **public,
        "listings": listings,
        "fetch_markets": lambda series, status="open": listings.get(series, []),
    }


def with_starts(public, now, state_dir, report=None):
    """Add milestone start times (``event_starts``) for the listed events. A
    failure leaves only the starts written in event tickers."""
    try:
        starts, counts = prefetch_starts(
            public.get("listings") or {},
            now,
            state_dir,
            public["fetch_milestones"],
            deadline=PROCESS_START + P.START_LOOKUP_SECONDS,
            active=recent_events(state_dir, now),
        )
    except Exception as error:
        starts, counts = {}, {"error": type(error).__name__}
    if report is not None:
        report["event_starts"] = counts
    return {**public, "event_starts": starts}


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    for flag in (
        "--shadow",
        "--live",
        "--auto",
        "--status",
        "--preflight",
        "--reconcile",
    ):
        mode.add_argument(flag, action="store_true")
    args = parser.parse_args()
    state_dir = P.STATE
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.status:
        status(state_dir)
        return
    journal = state_dir / "journal.jsonl"
    owner_command = args.preflight or args.reconcile
    with (state_dir / "lock").open("a+") as lock:
        # Owner commands wait for a running pass; a timer pass never queues.
        fcntl.flock(
            lock, fcntl.LOCK_EX if owner_command else fcntl.LOCK_EX | fcntl.LOCK_NB
        )
        if owner_command:
            public = None
            if args.preflight:
                # Public reads first, outside the account lock.
                public = prefetch(public_api())
                public = with_starts(public, datetime.now(UTC), state_dir)
                try:
                    public["milestone_check"] = milestone_check(
                        public,
                        datetime.now(UTC),
                        deadline=PROCESS_START + 2 * P.START_LOOKUP_SECONDS,
                    )
                except Exception as error:
                    public["milestone_check"] = {"error": type(error).__name__}
            with production_lock.account_lock():
                # Signed reads only: a dry-run client cannot send an order.
                client = TradingClient(dry_run=True, env="prod")
                now = datetime.now(UTC)
                if args.preflight:
                    result = preflight(client, os.environ, now, state_dir, public)
                else:
                    if not client.can_sign:
                        raise TradingError("Reconcile needs signed production reads")
                    result = reconcile(client, journal, now)
            label = "PREFLIGHT" if args.preflight else "RECONCILE"
            print(f"SPREAD {label}", json.dumps(result, sort_keys=True))
            if args.preflight and not result["ready"]:
                raise SystemExit(2)
            return
        signal.signal(signal.SIGTERM, _request_stop)
        deadline = PROCESS_START + P.PASS_DEADLINE_SECONDS
        live = args.live or (args.auto and armed(os.environ))
        if live:
            journal.touch(mode=0o600, exist_ok=True)
        # lexists: even a broken link named KILL counts as a kill switch.
        if os.path.lexists(state_dir / "KILL") and journal.exists():
            # Cancels only; works even after the owner disarms the bot.
            with production_lock.account_lock():
                client = TradingClient(dry_run=False, env="prod")
                if client.env != "prod" or not client.can_sign:
                    raise TradingError("KILL needs signed production credentials")
                cancel_owned_on_kill(client, journal)
            return
        started = datetime.now(UTC)
        report = {"run_utc": started.isoformat(), "mode": "live" if live else "shadow"}
        api = public_api()
        if live:
            paused = exchange_paused(started, api.get("exchange_status"))
            if paused:
                # v7: nothing is read or sent while Kalshi is not trading.
                report["live"] = {"decision": "exchange_paused", "reason": paused}
                write_report(state_dir, report)
                print("SPREAD MAKER", json.dumps(report, sort_keys=True, default=str))
                return
        public = prefetch(api)
        public = with_starts(public, started, state_dir, report)
        markets = None
        if live:
            try:
                with production_lock.account_lock():
                    client = TradingClient(dry_run=False, env="prod")
                    report["live"], markets = pass_live(
                        client,
                        os.environ,
                        datetime.now(UTC),
                        state_dir,
                        public,
                        deadline=deadline,
                    )
            except Exception as error:
                report["live"] = {"decision": "halt", "error": str(error)[:300]}
                write_report(state_dir, report)
                raise
        # Measurement only, after a completed live pass (which has just
        # copied the exchange's fills into the journal) and before the shadow
        # ledger, so the live numbers never wait behind it; a failure here
        # never affects trading.
        if live:
            try:
                report["markouts_recorded"] = record_markouts(
                    state_dir, started, public.get("listings")
                )
            except Exception as error:
                report["markouts_error"] = type(error).__name__
            try:
                write_measure_summary(state_dir)
            except Exception as error:
                report["measure_summary_error"] = type(error).__name__
            try:
                report["live_windows_scored"] = score_live_windows(
                    state_dir,
                    started,
                    public["window_trades"],
                    deadline=PROCESS_START + SCORING_DEADLINE_SECONDS,
                )
            except Exception as error:
                report["live_windows_error"] = type(error).__name__
        # The shadow ledger needs no lock: public reads and its own file only.
        try:
            report["shadow"] = run_shadow(
                state_dir,
                started,
                public,
                markets,
                deadline=PROCESS_START + SHADOW_DEADLINE_SECONDS,
            )
        except Exception as error:
            if not live:
                raise
            # Keep the live pass's report, then fail the unit visibly.
            report["shadow_error"] = type(error).__name__
            write_report(state_dir, report)
            raise
        write_report(state_dir, report)
        print("SPREAD MAKER", json.dumps(report, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
