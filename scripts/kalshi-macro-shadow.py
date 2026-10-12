#!/usr/bin/env python3
"""Kalshi MACRO shadow lane (complementary-Kalshi workstream, option B).

WHAT IT IS
----------
A read-only, forward-only instrument. It snapshots Kalshi's macro families
(CPI / Fed / U3 / GDP / NBER recession / payrolls) and, when those markets
settle, records the outcome so the lane can be scored as a CALIBRATION curve:
"what did the venue's implied probability say at H hours to close, and what
happened?" Nothing here trades, sizes or touches the Polymarket book — and note
Kalshi publishes no wallet attribution at all, so this can never become a copy
lane; it is a venue-quality measurement.

Each run appends:
  data/kalshi-macro-quotes.jsonl    one row per open market per run
  data/kalshi-macro-settled.jsonl   one row per market the moment we first see a result
  data/kalshi-macro-news.jsonl      per-run GDELT story counts per family (context column)

PRE-REGISTERED READ (written before the data existed — do not move it)
---------------------------------------------------------------------
At n >= 20 SETTLED markets in a family, each with a quote at >= 24h to close and
another at <= 6h to close, report implied-vs-realized by horizon bucket. The lane
"prices the venue" only if the 24h bucket's |realized - implied| clears its
binomial 95% CI; until then every figure is DESCRIPTIVE and no rule may be
changed off it. Sample accrues slowly by design: macro families are event-driven
(KXCPI ~44 open markets, KXGDP 36, KXU3 28), so expect weeks, not days.

Python 3.9 compatible.
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTDIR = ROOT / "data"
QUOTES_FILE = OUTDIR / "kalshi-macro-quotes.jsonl"
SETTLED_FILE = OUTDIR / "kalshi-macro-settled.jsonl"
NEWS_FILE = OUTDIR / "kalshi-macro-news.jsonl"
GDELT_DIR = OUTDIR / "gdelt-bulk"
API = "https://api.elections.kalshi.com/trade-api/v2"
UA = {"User-Agent": "copybot-kalshi-macro/1.0"}

FAMILIES = {
    "KXCPI": ["inflation", "cpi", "consumer price", "prices rose", "price index"],
    "KXFED": ["fed", "fomc", "powell", "rate cut", "rate hike", "federal reserve"],
    "KXU3": ["unemployment", "jobless", "u-3", "labor market"],
    "KXGDP": ["gdp", "economic growth", "recession"],
    "KXRECSSNBER": ["recession", "nber", "downturn"],
    "KXPAYROLLS": ["payroll", "nonfarm", "jobs report", "job growth"],
}

# Keyword matching is WORD-BOUNDARY, not substring. Measured 2026-10-12 on the first
# run: a bare substring match on "cpi" counted Indian CPIM party stories as US CPI
# stories (top story: "delhi protests cpim rajya sabha mp ..."). The context column is
# a count, so a match on a different subject is a wrong number, not a near miss.
KEY_RES = {fam: re.compile("|".join(r"\b%s\b" % re.escape(k) for k in keys)) for fam, keys in FAMILIES.items()}

# GDELT's title_derived sometimes carries a raw filename instead of a headline
# ("article e0fedfa8 e864 51e1 a251 93b361877bad.html", the KXFED top story on the
# first run). Never let one of those be the family's representative headline.
GARBLED_TITLE = re.compile(r"^(article\s+)?[0-9a-f]{8}([\s-][0-9a-f]{4})+|^article\s+[0-9a-f]{8}")


def get_json(url, timeout=30, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            last = "HTTP %s" % exc.code
            if exc.code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            break
        except Exception as exc:
            last = str(exc)[:160]
            time.sleep(1.0)
    raise RuntimeError("kalshi macro request failed: %s (%s)" % (url, last))


def fnum(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_iso(text):
    s = (text or "").replace("Z", "+00:00")
    if "." in s:
        head, rest = s.split(".", 1)
        frac = ""
        idx = 0
        while idx < len(rest) and rest[idx].isdigit():
            frac += rest[idx]
            idx += 1
        s = head + "." + (frac + "000000")[:6] + rest[idx:]
    return datetime.fromisoformat(s)


def append_rows(path, rows, gz=False):
    if not rows:
        return
    opener = gzip.open if gz else open
    with opener(str(path), "at") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")


def tail_rows(path, limit=20000):
    """Read the newest jsonl rows (plain file). Returns list of dicts."""
    if not path.exists():
        return []
    from collections import deque

    out = deque(maxlen=limit)
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    return list(out)


def gdelt_counts(day_stamp):
    """Story counts per family keyword set from the newest GDELT bulk capture."""
    path = GDELT_DIR / ("%s.jsonl.gz" % day_stamp)
    if not path.exists():
        candidates = sorted(glob.glob(str(GDELT_DIR / "*.jsonl.gz")))
        if not candidates:
            return None, None
        path = Path(candidates[-1])
    counts = {fam: 0 for fam in FAMILIES}
    us_counts = {fam: 0 for fam in FAMILIES}
    top = {fam: None for fam in FAMILIES}
    hashes = {fam: set() for fam in FAMILIES}
    total = 0
    with gzip.open(str(path), "rt") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except Exception:
                continue
            total += 1
            title = (row.get("title") or row.get("title_derived") or "").lower()
            text = (row.get("url") or "") + "|" + title
            for fam in FAMILIES:
                if KEY_RES[fam].search(title):
                    # dedupe: the same story is syndicated across outlets, so a raw
                    # headline count is an OUTLET count, not a story count.
                    key = row.get("item_id") or text
                    if key in hashes[fam]:
                        continue
                    hashes[fam].add(key)
                    counts[fam] += 1
                    if (row.get("action_country") or "") in ("USA", "US"):
                        us_counts[fam] += 1
                    if top[fam] is None and not GARBLED_TITLE.match(title):
                        top[fam] = (row.get("title") or row.get("title_derived") or "")[:110]
    return (
        {
            "source_file": path.name,
            "match_rule": "word_boundary_headline_v2",
            "stories_total": total,
            "counts": counts,
            "us_country_counts": us_counts,
            "top": top,
        },
        path.name,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle-lookback-days", type=int, default=45, help="how far back to resolve unsettled tickers we hold")
    ap.add_argument("--max-settle-lookups", type=int, default=40, help="cap per run on per-ticker settlement lookups")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    quotes = []
    open_by_family = {}
    for fam in sorted(FAMILIES):
        d = get_json("%s/markets?series_ticker=%s&status=open&limit=200" % (API, fam))
        ms = d.get("markets") or []
        open_by_family[fam] = len(ms)
        for m in ms:
            yb, ya = fnum(m.get("yes_bid_dollars")), fnum(m.get("yes_ask_dollars"))
            close = m.get("close_time") or m.get("expiration_time") or ""
            hours = None
            if close:
                try:
                    hours = round((parse_iso(close) - now).total_seconds() / 3600.0, 3)
                except Exception:
                    hours = None
            quotes.append(
                {
                    "ts": now.isoformat(),
                    "family": fam,
                    "ticker": m.get("ticker"),
                    "title": (m.get("title") or "")[:160],
                    "yes_bid": yb,
                    "yes_ask": ya,
                    "mid": round((yb + ya) / 2.0, 4) if (yb or ya) else None,
                    "spread": round(ya - yb, 4) if (yb and ya) else None,
                    "bid_size": fnum(m.get("yes_bid_size_fp")),
                    "ask_size": fnum(m.get("yes_ask_size_fp")),
                    "last": fnum(m.get("last_price_dollars")),
                    "volume": fnum(m.get("volume_fp")),
                    "volume_24h": fnum(m.get("volume_24h_fp")),
                    "open_interest": fnum(m.get("open_interest_fp")),
                    "close_time": close,
                    "hours_to_close": hours,
                }
            )
        time.sleep(0.25)

    # ---- settlement pass: resolve tickers we have quoted but not yet settled ----
    seen = {}
    for row in tail_rows(QUOTES_FILE, limit=40000):
        t = row.get("ticker")
        if not t:
            continue
        prev = seen.get(t)
        if prev is None or row.get("ts", "") < prev.get("ts", ""):
            seen[t] = row  # earliest quote we hold for that ticker
    already = {r.get("ticker") for r in tail_rows(SETTLED_FILE, limit=40000) if r.get("ticker")}
    pending = []
    for tick, row in seen.items():
        if tick in already:
            continue
        close = row.get("close_time") or ""
        if not close:
            continue
        try:
            if (now - parse_iso(close)).total_seconds() < 1800:
                continue  # not clearly closed yet
            if (now - parse_iso(close)).days > args.settle_lookback_days:
                continue
        except Exception:
            continue
        pending.append((close, tick))
    pending.sort()
    pending = pending[: args.max_settle_lookups]

    settled_rows = []
    for _close, tick in pending:
        try:
            d = get_json("%s/markets/%s" % (API, urllib.parse.quote(tick, safe="")))
            m = d.get("market") or {}
        except Exception as exc:
            print("  settle lookup failed for %s: %s" % (tick, exc))
            continue
        result = m.get("result")
        if result not in ("yes", "no"):
            continue
        first = seen.get(tick) or {}
        last_quote = None
        for row in tail_rows(QUOTES_FILE, limit=40000):
            if row.get("ticker") == tick:
                last_quote = row
        settled_rows.append(
            {
                "ts": now.isoformat(),
                "family": (tick.split("-")[0] if tick else None),
                "ticker": tick,
                "title": (m.get("title") or first.get("title") or "")[:160],
                "result": result,
                "last_price": fnum(m.get("last_price_dollars")),
                "expiration_value": (m.get("expiration_value") or "")[:60],
                "close_time": m.get("close_time") or first.get("close_time"),
                "first_quote_ts": first.get("ts"),
                "first_quote_mid": first.get("mid"),
                "first_quote_hours_to_close": first.get("hours_to_close"),
                "last_quote_ts": (last_quote or {}).get("ts"),
                "last_quote_mid": (last_quote or {}).get("mid"),
                "last_quote_hours_to_close": (last_quote or {}).get("hours_to_close"),
            }
        )
        time.sleep(0.25)

    news, news_file = gdelt_counts(now.strftime("%Y%m%d"))

    print("kalshi-macro-shadow: families=%d quotes=%d settled_now=%d pending_lookups=%d" % (len(FAMILIES), len(quotes), len(settled_rows), len(pending)))
    for fam in sorted(FAMILIES):
        fam_quotes = [q for q in quotes if q["family"] == fam]
        spreads = [q["spread"] for q in fam_quotes if q["spread"] is not None]
        oi = sum(q["open_interest"] for q in fam_quotes)
        print(
            "  %-14s open=%3d oi=%10.0f median_spread=%s"
            % (fam, len(fam_quotes), oi, ("%.3f" % sorted(spreads)[len(spreads) // 2]) if spreads else "n/a")
        )
    if news:
        print("  GDELT context (%s, %d stories): %s" % (news_file, news["stories_total"], ", ".join("%s=%d" % (k, v) for k, v in sorted(news["counts"].items()))))

    # ---- descriptive calibration from everything we hold so far ----
    all_settled = tail_rows(SETTLED_FILE, limit=40000) + settled_rows
    if all_settled:
        print("  settled book (all history): %d rows" % len(all_settled))
        for fam in sorted(FAMILIES):
            rows = [r for r in all_settled if r.get("family") == fam and r.get("first_quote_mid") is not None]
            if not rows:
                continue
            yes = [r for r in rows if r.get("result") == "yes"]
            imp = sum(r["first_quote_mid"] for r in rows) / len(rows)
            print(
                "    %-14s n=%3d  first-quote mean implied=%.3f  realized YES rate=%.3f  (descriptive; pre-registered read at n>=20 per horizon bucket)"
                % (fam, len(rows), imp, len(yes) / float(len(rows)))
            )

    if args.dry_run:
        print("  (dry run — nothing written)")
        return 0
    append_rows(QUOTES_FILE, quotes)
    append_rows(SETTLED_FILE, settled_rows)
    if news:
        append_rows(NEWS_FILE, [{"ts": now.isoformat(), **news}])
    print("  appended %d quote rows, %d settled rows%s" % (len(quotes), len(settled_rows), ", 1 news row" if news else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
