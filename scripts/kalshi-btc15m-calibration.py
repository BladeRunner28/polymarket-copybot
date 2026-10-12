#!/usr/bin/env python3
"""KXBTC15M tail-calibration read (complementary-Kalshi workstream, option A).

WHAT IT ANSWERS
---------------
Kalshi's 15-minute BTC up/down markets are the busiest family on the venue — measured
from our own tape capture, this family alone printed 1,500,158 contracts inside a
single 4-minute window on 2026-10-12. "Buy the cheap tail" is the obvious first
hypothesis, so this script settles it from keyless public data before anyone builds
anything: for every SETTLED market in the rolling window, bucket the LAST PRINTED
PRICE and compare it to the realized outcome. (No per-day venue-volume estimate is
quoted here on purpose: extrapolating a captured window to 24h spans a volatility
regime, and the number is not needed to read the table below.)

Measured 2026-10-12 (6,438 settled markets, window 2026-08-06 -> 2026-10-12):
  implied < 0.02  -> n=3,211, realized YES 0.0000 (implied mean 0.0010)
  implied > 0.98  -> n=3,222, realized YES 1.0000 (implied mean 0.9990)
  99.9% of the sample sits in those two tails.
i.e. the LAST print is calibrated to the cent in the tails, and the entire family
lives in the tails, so the edge question is INSIDE the window (the intra-window tape
captured by scripts/kalshi-tape-capture.py), never at settlement. This is the read
that kills the naive version of the hypothesis; it is a negative result, kept so the
cheap hypothesis is not re-proposed.

Read-only: no writes, no API key, no order endpoints.

Python 3.9 compatible.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.elections.kalshi.com/trade-api/v2"
UA = {"User-Agent": "copybot-kalshi-btc15m-cal/1.0"}
BUCKETS = [(0.0, 0.02), (0.02, 0.10), (0.10, 0.50), (0.50, 0.90), (0.90, 0.98), (0.98, 1.01)]


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
    raise RuntimeError("kalshi request failed: %s (%s)" % (url, last))


def fnum(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="KXBTC15M")
    ap.add_argument("--max-markets", type=int, default=10000)
    args = ap.parse_args()

    rows = []
    cursor = None
    while len(rows) < args.max_markets:
        url = "%s/markets?series_ticker=%s&status=settled&limit=1000" % (API, args.series)
        if cursor:
            url += "&cursor=" + urllib.parse.quote(cursor, safe="")
        payload = get_json(url)
        page = payload.get("markets") or []
        if not page:
            break
        rows.extend(page)
        cursor = payload.get("cursor")
        if not cursor:
            break

    stats = {b: {"n": 0, "yes": 0, "implied": 0.0} for b in BUCKETS}
    unlabelled = 0
    for m in rows[: args.max_markets]:
        result = (m.get("result") or "").lower()
        if result not in ("yes", "no"):
            unlabelled += 1
            continue
        price = fnum(m.get("last_price_dollars"))
        for b in BUCKETS:
            if b[0] - 1e-9 <= price < b[1]:
                stats[b]["n"] += 1
                stats[b]["yes"] += 1 if result == "yes" else 0
                stats[b]["implied"] += price
                break

    labelled = sum(v["n"] for v in stats.values())
    closes = sorted(m.get("close_time") or "" for m in rows if m.get("close_time"))
    print("%s settled markets fetched: %d (labelled %d, unlabelled %d)" % (args.series, len(rows), labelled, unlabelled))
    if closes:
        print("rolling-window coverage: %s -> %s" % (closes[0], closes[-1]))
    print("%-14s %7s %10s %10s %9s" % ("implied bucket", "n", "realized", "implied", "gap"))
    for b in BUCKETS:
        v = stats[b]
        if not v["n"]:
            continue
        realized = v["yes"] / v["n"]
        implied = v["implied"] / v["n"]
        print("%-14s %7d %10.4f %10.4f %+9.4f" % ("%.2f-%.2f" % b, v["n"], realized, implied, realized - implied))
    low, high = stats[BUCKETS[0]], stats[BUCKETS[-1]]
    if labelled:
        tails = 100.0 * (low["n"] + high["n"]) / labelled
        print("\nTAILS: that is %.1f%% of the labelled sample; the family is a race to the finish," % tails)
        print("so a settlement-time 'buy the cheap tail' read has no sample to work with.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
