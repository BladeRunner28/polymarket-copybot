#!/usr/bin/env python3
"""Kalshi x Polymarket BTC up/down read (complementary-Kalshi workstream).

WHY THIS PAIR AND NOT THE OTHERS
--------------------------------
The temperature and oil cross-venue reads died on ONTOLOGY (a one-degree bucket-grid
offset; "above 84.99" vs integer strikes) so they produce zero exact-alignment rows.
The 15-minute BTC up/down pair is structurally different: both venues list a BINARY
proposition over the SAME wall-clock window. Measured 2026-10-12/13 on the 8:45-9:00 PM
ET window:

  Kalshi   KXBTC15M-26OCT122100-00  "BTC price up in next 15 mins?"  open 00:45Z close 01:00Z
           resolves on the simple AVERAGE of sixty seconds of CF Benchmarks' BRTI before
           9:00 PM EDT vs the average of the sixty seconds before 8:45 PM EDT
  Poly     btc-updown-15m-1791852300 "Bitcoin Up or Down - 8:45PM-9:00PM ET"
           resolves "Up" if the Chainlink BTC/USD 60s TWAP over the range >= the price at
           the start of the range

So the SHAPE and the WINDOW align exactly, but the ORACLES DIFFER (CF Benchmarks BRTI vs
Chainlink BTC/USD TWAP). That means any cross-venue gap is not free money until the
oracle basis is measured — and that is exactly what `--outcomes` measures, before anyone
prices anything.

MODES
-----
  --outcomes N   the decisive test: for the last N 15-minute windows, did the two venues
                 resolve the SAME direction? A pair whose oracles disagree is not a pair.
  --live         side-by-side quotes on the CURRENT window (both keyless), with the fee
                 arithmetic and an explicit "no claim" unless the exact-alignment rows say
                 otherwise.

READ-ONLY: public endpoints only, no key, no order surface, nothing written to the book.

Usage:
  python3 scripts/kalshi-pm-btc-updown-read.py --outcomes 96
  python3 scripts/kalshi-pm-btc-updown-read.py --live
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
UA = {"User-Agent": "copybot-kalshi-pm-updown/1.0"}
BUCKET = 900  # 15 minutes
SERIES = "KXBTC15M"


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
    raise RuntimeError("request failed: %s (%s)" % (url, last))


def fnum(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def kalshi_fee(p):
    """Taker fee per contract on a standard series: 0.07 * P * (1-P)."""
    return 0.07 * p * (1.0 - p)


def kalshi_settled_by_close(max_pages=10):
    """close_time (ISO) -> {result, last_price} for the series' settled markets."""
    out = {}
    cursor = None
    for _ in range(max_pages):
        url = "%s/markets?series_ticker=%s&status=settled&limit=1000" % (KALSHI, SERIES)
        if cursor:
            url += "&cursor=" + urllib.parse.quote(cursor, safe="")
        payload = get_json(url)
        page = payload.get("markets") or []
        if not page:
            break
        for m in page:
            close = m.get("close_time")
            if not close:
                continue
            out[close] = {
                "ticker": m.get("ticker"),
                "result": (m.get("result") or "").lower(),
                "last_price": fnum(m.get("last_price_dollars")),
                "volume": fnum(m.get("volume_fp")),
            }
        cursor = payload.get("cursor")
        if not cursor:
            break
    return out


def pm_event(bucket_start):
    """Polymarket event for a bucket; returns (winner, volume, raw) or (None, None, None)."""
    slug = "btc-updown-15m-%d" % bucket_start
    data = get_json("%s/events?slug=%s" % (GAMMA, slug))
    if not isinstance(data, list) or not data:
        return None, None, None
    event = data[0]
    markets = event.get("markets") or []
    if not markets:
        return None, None, event
    market = markets[0]
    outcomes = market.get("outcomes")
    prices = market.get("outcomePrices")
    try:
        outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
        prices = [float(x) for x in (json.loads(prices) if isinstance(prices, str) else prices or [])]
    except Exception:
        return None, None, event
    # A verdict requires the event to be CLOSED and a leg to be at settlement (1/0).
    # Counter-example this guard exists for, measured 2026-10-13: PM's 8:30-8:45 PM ET
    # event read prices 0.9995/0.0005 while still `closed: False` — a live last-trade
    # price near certainty, NOT a resolution — and treating it as a verdict manufactured
    # a fake oracle disagreement against Kalshi's settled "Down" for that window.
    winner = None
    closed = bool(event.get("closed"))
    if closed and outcomes and prices and len(outcomes) == len(prices):
        ranked = sorted(zip(outcomes, prices), key=lambda t: -t[1])
        if ranked[0][1] >= 0.999:
            winner = str(ranked[0][0]).lower()
    vol = None
    try:
        vol = float(market.get("volume") or 0)
    except Exception:
        pass
    return winner, vol, event


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_outcomes(n_buckets, json_path=None):
    now = int(time.time())
    start = now // BUCKET * BUCKET
    settled = kalshi_settled_by_close()
    print("Kalshi %s settled markets in the rolling window: %d" % (SERIES, len(settled)))
    agree = disagree = both_found = kalshi_only = pm_only = 0
    examples = []
    checked = 0
    # The 2x2 confusion matrix — WHY IT MATTERS: a cross-venue PAIRED position (buy Up on one
    # venue, buy Down on the other) loses the whole stake on EXACTLY ONE of the two disagreement
    # directions, and which one is fatal depends on the direction of the pair. The aggregate
    # disagreement rate is therefore not enough to price either leg; these cells are.
    cells = {"kalshi_up_pm_up": 0, "kalshi_up_pm_down": 0,
             "kalshi_down_pm_up": 0, "kalshi_down_pm_down": 0}
    for i in range(1, n_buckets + 1):
        b = start - i * BUCKET
        close_iso = iso(b + BUCKET)
        k = settled.get(close_iso)
        winner, vol, _ev = pm_event(b)
        checked += 1
        if k and winner:
            both_found += 1
            k_up = k["result"] == "yes"
            pm_up = winner == "up"
            cells["kalshi_%s_pm_%s" % ("up" if k_up else "down", "up" if pm_up else "down")] += 1
            if k_up == pm_up:
                agree += 1
            else:
                disagree += 1
                if len(examples) < 6:
                    examples.append((b, k["ticker"], k["result"], k["last_price"], winner, k["volume"], vol))
        elif k and not winner:
            kalshi_only += 1
        elif winner and not k:
            pm_only += 1
        if checked % 24 == 0:
            time.sleep(0.2)

    print("\nWINDOWS CHECKED: %d (last %d x 15 min = %.1f h)" % (checked, n_buckets, n_buckets * 0.25))
    print("  both venues resolved a verdict: %d" % both_found)
    print("  kalshi settled, PM no verdict found: %d" % kalshi_only)
    print("  PM verdict, kalshi not found: %d" % pm_only)
    if both_found:
        lo, hi = wilson(disagree, both_found)
        print("\nORACLE AGREEMENT: %d agree / %d disagree of %d = %.2f%% disagreement (95%% CI %.2f-%.2f%%)"
              % (agree, disagree, both_found, 100.0 * disagree / both_found, 100 * lo, 100 * hi))
        if disagree:
            print("\ndisagreeing windows (window start, kalshi ticker, kalshi result/last, PM winner, vol k/p):")
            for b, tick, res, last, win, kv, pv in examples:
                print("  %s  %-28s kalshi=%-3s last=%.2f | PM=%-4s  vol k=%.0f p=%.0f"
                      % (iso(b), tick, res, last, win, kv or 0, pv or 0))
        print("\n2x2 ORACLE MATRIX (rows = Kalshi verdict, cols = Polymarket verdict):")
        print("             PM up     PM down")
        print("  kalshi up  %6d    %6d   <- PM-down cell is FATAL to direction A (PM Up + K No)"
              % (cells["kalshi_up_pm_up"], cells["kalshi_up_pm_down"]))
        print("  kalshi dn  %6d    %6d   <- PM-up cell is FATAL to direction B (PM Down + K Yes)"
              % (cells["kalshi_down_pm_up"], cells["kalshi_down_pm_down"]))
        for label, key in (("A (PM Up + Kalshi No)", "kalshi_up_pm_down"),
                           ("B (PM Down + Kalshi Yes)", "kalshi_down_pm_up")):
            lo_c, hi_c = wilson(cells[key], both_found)
            print("  fatal rate for direction %-26s %d/%d = %.2f%% (95%% CI %.2f-%.2f%%)"
                  % (label, cells[key], both_found, 100.0 * cells[key] / both_found,
                     100 * lo_c, 100 * hi_c))
        print("\nREAD: the two venues resolve on DIFFERENT oracles (CF Benchmarks BRTI vs")
        print("Chainlink BTC/USD 60s TWAP) over the same window, so a disagreement rate")
        print("above ~0 means a cross-venue position carries oracle basis risk, not just")
        print("the usual spread. Quote the per-direction fatal cell with any pair cost the")
        print("--live mode or the paired sampler prints.")
        if json_path:
            payload = {
                "asOf": datetime.now(timezone.utc).isoformat(),
                "series": SERIES, "windows_checked": checked, "windows_with_both": both_found,
                "agree": agree, "disagree": disagree,
                "cells": cells,
                "disagreement_rate": (disagree / both_found) if both_found else None,
                "disagreement_ci95": list(wilson(disagree, both_found)) if both_found else None,
                "disagreeing_windows": [
                    {"window_start": iso(b), "kalshi_ticker": tick, "kalshi": res,
                     "kalshi_last": last, "pm": win, "vol_kalshi": kv, "vol_pm": pv}
                    for b, tick, res, last, win, kv, pv in examples],
            }
            with open(json_path, "w") as fh:
                json.dump(payload, fh, indent=1)
            print("wrote oracle matrix -> %s" % json_path)


def run_live():
    now = int(time.time())
    b = now // BUCKET * BUCKET
    print("current 15-min window: %s .. %s (bucket %d)" % (iso(b), iso(b + BUCKET), b))

    kd = get_json("%s/markets?series_ticker=%s&status=open&limit=200" % (KALSHI, SERIES))
    kmarkets = []
    for m in kd.get("markets") or []:
        try:
            if datetime.fromisoformat((m.get("close_time") or "").replace("Z", "+00:00")).timestamp() != b + BUCKET:
                continue
        except Exception:
            continue
        kmarkets.append(m)
    print("kalshi markets closing at %s: %d" % (iso(b + BUCKET), len(kmarkets)))
    for m in kmarkets:
        yb, ya = fnum(m.get("yes_bid_dollars")), fnum(m.get("yes_ask_dollars"))
        bs, as_ = fnum(m.get("yes_bid_size_fp")), fnum(m.get("yes_ask_size_fp"))
        mid = (yb + ya) / 2.0 if (yb and ya) else None
        print("  %-30s up=%.2f/%.2f (size %.0f/%.0f) target %s%s"
              % (m.get("ticker"), yb, ya, bs, as_, (m.get("yes_sub_title") or "").replace("Target Price: ", ""),
                 " | mid %.3f" % mid if mid else ""))
        if mid:
            print("     kalshi taker fee at %.3f = %.4f/contract (maker 0 on standard series)" % (mid, kalshi_fee(mid)))

    winner, vol, ev = pm_event(b)
    print("\nPolymarket event btc-updown-15m-%d:" % b)
    if not ev:
        print("  (no event at this bucket)")
    else:
        for m in ev.get("markets") or []:
            print("  %-30s bestBid=%s bestAsk=%s spread=%s vol=%s"
                  % (m.get("slug"), m.get("bestBid"), m.get("bestAsk"), m.get("spread"), m.get("volume")))
            print("     outcomes=%s outcomePrices=%s" % (m.get("outcomes"), m.get("outcomePrices")))
            print("     resolution: %s" % (m.get("resolutionSource") or "")[:110])
        if vol is not None:
            print("  event volume: %.2f" % vol)

    print("\nNOT A CLAIM: a cross-venue gap on this pair is only meaningful net of (a) the")
    print("oracle basis measured by --outcomes, (b) both venues' spreads, (c) taker fee at")
    print("the price you would cross. Run --outcomes before reading any number above.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outcomes", type=int, default=0, help="check the last N 15-min windows for oracle agreement")
    ap.add_argument("--live", action="store_true", help="side-by-side quotes on the current window")
    ap.add_argument("--json", default=None,
                    help="write the 2x2 oracle matrix here (the paired read's gate needs it: "
                         "data/kalshi-pm-btc-oracle.json)")
    args = ap.parse_args()
    if not args.outcomes and not args.live:
        args.outcomes = 96
    if args.outcomes:
        run_outcomes(args.outcomes, json_path=args.json)
        print()
    if args.live:
        run_live()
    return 0


if __name__ == "__main__":
    sys.exit(main())
