#!/usr/bin/env python3
"""Binance data vs the two venues' BTC settlement oracles — keyless, read-only reconciliation.

WHY THIS EXISTS
---------------
"Does Binance have an API we can query for bitcoin data to enhance our PM/Kalshi trading?"
Answering it needs one distinction that a feature-list answer hides: is Binance the *oracle* the
venue settles on, or only a *proxy* correlated with it? That difference decides everything —
a pinned oracle can be reproduced exactly (settlement certainty), a proxy carries a measured error
rate that IS the risk of any position built on it.

WHAT IT MEASURES
----------------
  1. Reachability + rate-limit headers for every Binance host (the global API is geo-blocked here).
  2. Polymarket's Binance-settled families: reproduce the venue's OWN recorded outcome from the
     keyless archive. Hourly "above" ladders, hourly up-or-down, daily/monthly "hit" ladders,
     noon-close ranges.
  3. Kalshi KXBTC15M (CF Benchmarks BRTI, a composite that does NOT include Binance): how often a
     Binance-1s proxy reproduces Kalshi's recorded verdict, over every settled window on record.
  4. The knife-edge census and the decision curve — how often a window is already physically decided
     m minutes in, from the tape alone.

Python 3.9 compatible. Keyless. Writes nothing outside /tmp.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WORK = Path("/tmp/btc-oracle-recon")
CACHE = WORK / "cache"
UA = {"User-Agent": "copybot-btc-oracle-recon/1.0 (read-only measurement)"}
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
BV = "https://data-api.binance.vision"
ET = ZoneInfo("America/New_York")
# Asset universe: Polymarket's slug name -> the Binance spot symbol its own rules pin.
# Every entry was validated by reproducing the venue's recorded verdicts (see --assets).
ASSETS = {
    "bitcoin": "BTCUSDT",
    "ethereum": "ETHUSDT",
    "solana": "SOLUSDT",
    "xrp": "XRPUSDT",
    "dogecoin": "DOGEUSDT",
    "bnb": "BNBUSDT",
    "hyperliquid": "HYPEUSDT",
}
# HISTORY CAP: how far back the 1-SECOND archive may be pulled in one run. The 1s ZIP is ~2.3 MB per
# day (~70 MB/month); 1m is ~2.1 MB per MONTH. Backfills longer than the cap use 1m, and only windows
# actually in scope get 1s. Keeps a run bounded and the nightly backup's 95 MB guard untouched.
DEFAULT_HISTORY_DAYS = 90
HOSTS = [
    ("api.binance.com /ping", "https://api.binance.com/api/v3/ping"),
    ("fapi.binance.com /ping (futures)", "https://fapi.binance.com/fapi/v1/ping"),
    ("data-api.binance.vision /ping", "https://data-api.binance.vision/api/v3/ping"),
    ("api.binance.us /ping", "https://api.binance.us/api/v3/ping"),
]


def http(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def jget(url, tries=4):
    last = None
    for i in range(tries):
        try:
            return json.loads(http(url))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.2 * (i + 1))
    raise last


# ----------------------------------------------------------------- host reachability
def probe_hosts():
    out = []
    for name, url in HOSTS:
        t0 = time.time()
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20)
            r.read()
            out.append({"host": name, "http": r.status, "ms": round((time.time() - t0) * 1000),
                        "weight_used": r.headers.get("x-mbx-used-weight-1m")})
        except urllib.error.HTTPError as e:
            out.append({"host": name, "http": e.code, "ms": round((time.time() - t0) * 1000),
                        "note": e.read()[:80].decode("utf8", "replace")})
        except Exception as e:  # noqa: BLE001
            out.append({"host": name, "http": None, "note": f"{type(e).__name__}: {e}"})
    return out


# ----------------------------------------------------------------- futures (archive only)
def futures_check(day=None, verbose=True):
    """Futures data IS reachable from here — via the bulk archive, not the REST API.

    `fapi.binance.com` is geo-blocked (HTTP 451), so live funding/OI/mark price are unavailable. The
    archive on the non-blocked host serves the same content at T+1: funding history (monthly files),
    open interest + long/short ratios (daily files), and the UM/CM tape.
    """
    day = day or (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
    month = day[:7]
    # TRAP (measured): fundingRate exists ONLY as a MONTHLY file, and the current month's file is not
    # published until the month closes (2026-10 -> HTTP 404 on 2026-10-13; 2026-08/2026-09 -> 200).
    # metrics exists ONLY as a DAILY file (monthly/metrics -> 404). Probe the last COMPLETE month so a
    # run never reports a 404 that is really just "the month is still open".
    prev_month = (datetime.now(timezone.utc).replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    out = {}
    probes = {
        "um_klines_1m": f"https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/1m/BTCUSDT-1m-{day}.zip",
        "funding_rate": f"https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-{prev_month}.zip",
        "metrics_oi_ls": f"https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-{day}.zip",
        "um_aggTrades": f"https://data.binance.vision/data/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-{day}.zip",
        "cm_klines": f"https://data.binance.vision/data/futures/cm/daily/klines/BTCUSD_PERP/1m/BTCUSD_PERP-1m-{day}.zip",
    }
    for name, url in probes.items():
        try:
            blob = http(url, 180)
        except urllib.error.HTTPError as e:
            out[name] = {"http": e.code}
            if verbose:
                print(f"  {name:<16} HTTP {e.code}")
            continue
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            with z.open(z.namelist()[0]) as fh:
                rows = list(csv.reader(io.TextIOWrapper(fh, "utf-8")))
        out[name] = {"rows": len(rows), "header": rows[0],
                     "first": rows[1] if len(rows) > 1 else None}
        if verbose:
            print(f"  {name:<16} rows={len(rows):>6}  cols={len(rows[0])}  {','.join(rows[0][:6])}")
    if verbose:
        print("  NOTE: REST futures endpoints are 451 here; this is archive (T+1), not a live feed.")
    return out


# ----------------------------------------------------------------- Binance tape
TAPE_STATS = {"archive_days": 0, "api_windows": 0, "oldest_pulled": None}


def day_tape(day):
    """{epoch_ms: close} for one UTC day from the keyless daily zip, or None if not published."""
    TAPE_STATS["archive_days"] += 1
    if TAPE_STATS["oldest_pulled"] is None or day < TAPE_STATS["oldest_pulled"]:
        TAPE_STATS["oldest_pulled"] = day
    p = CACHE / f"BTCUSDT-1s-{day}.zip"
    if p.exists():
        src = p.read_bytes()
    else:
        try:
            src = http(f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1s/BTCUSDT-1s-{day}.zip", 180)
            p.write_bytes(src)
        except urllib.error.HTTPError as e:
            if e.code == 404:                      # today's file is not published until the day ends
                return None
            raise
    out = {}
    with zipfile.ZipFile(io.BytesIO(src)) as z:
        with z.open(z.namelist()[0]) as fh:
            for row in csv.reader(io.TextIOWrapper(fh, "utf-8")):
                if not row or row[0] == "open_time":
                    continue
                t = int(row[0])
                if t > 10 ** 14:   # TRAP: the archive CSV is MICROSECONDS, the klines API is MILLISECONDS
                    t //= 1000
                out[t] = float(row[4])
    return out


def api_tape(s_ms, e_ms):
    key = CACHE / f"api-{s_ms}-{e_ms}.json"
    if key.exists():
        return {int(k): v for k, v in json.loads(key.read_text()).items()}
    out, cur = {}, s_ms
    while cur < e_ms:
        b = jget(f"{BV}/api/v3/klines?symbol=BTCUSDT&interval=1s&startTime={cur}&endTime={e_ms}&limit=1000")
        if not b:
            break
        for k in b:
            out[int(k[0])] = float(k[4])
        nxt = b[-1][6] + 1
        if nxt <= cur:
            break
        cur = nxt
        if len(b) < 1000:
            break
    key.write_text(json.dumps(out))
    return out


def mean_level(tape, t_end_ms, span_ms=60_000):
    """Simple average of 1s closes over the 60s before t_end_ms — looked up BY TIMESTAMP.

    Never by list position: one missing second would shift every later sample and silently
    mis-pair a window with its verdict (this exact bug produced a 50.9% "agreement" first run).
    """
    vals = [tape[t] for t in range(t_end_ms - span_ms, t_end_ms, 1000) if t in tape]
    return (statistics.fmean(vals), len(vals)) if vals else (None, 0)


# ----------------------------------------------------------------- Kalshi: BRTI proxy
def kalshi_windows(max_pages=40):
    rows, cur, pages = [], None, 0
    while pages < max_pages:
        u = f"{KALSHI}/markets?series_ticker=KXBTC15M&status=settled&limit=200" + (f"&cursor={cur}" if cur else "")
        d = jget(u)
        ms = d.get("markets", [])
        rows += ms
        pages += 1
        cur = d.get("cursor")
        if not cur or not ms:
            break
    return rows


def kalshi_reconcile(verbose=True):
    mk = kalshi_windows()
    if verbose:
        print(f"[kalshi] {len(mk)} settled KXBTC15M markets")
    by_day = {}
    for r in mk:
        by_day.setdefault(r["close_time"][:10], []).append(r)
    cache, recs, curves = {}, [], []

    def tape_for(day):
        if day not in cache:
            cache[day] = day_tape(day)
        return cache[day]

    for day in sorted(by_day):
        prev = (datetime.fromisoformat(day) - timedelta(days=1)).strftime("%Y-%m-%d")
        tape = {}
        for d in (prev, day):                 # a window ending 00:00Z starts on the previous day
            t = tape_for(d)
            if t:
                tape.update(t)
        for r in by_day[day]:
            t = datetime.fromisoformat(r["close_time"].replace("Z", "+00:00"))
            end = int(t.timestamp() * 1000)
            start = end - 900_000
            src = tape
            if (end - 60_000) not in tape or (start - 60_000) not in tape:
                src = api_tape(start - 60_000, end)
            a_end, n_end = mean_level(src, end)
            a_start, n_start = mean_level(src, start)
            if a_end is None or a_start is None or n_end < 55 or n_start < 55:
                continue
            recs.append({"ticker": r["ticker"], "close": r["close_time"], "result": r.get("result"),
                         "delta": a_end - a_start, "proxy_yes": a_end >= a_start})
            row = {"result": r.get("result"), "crit": a_start, "px": {}}
            for m in range(0, 16):
                px = src.get(start + m * 60_000)
                if px is not None:
                    row["px"][m] = px
            curves.append(row)
        cache.pop(prev, None)
    return recs, curves


def summarise_kalshi(recs, curves, verbose=True):
    ok = [x for x in recs]
    dis = [x for x in ok if (x["proxy_yes"] and x["result"] != "yes") or (not x["proxy_yes"] and x["result"] != "no")]
    agg = (len(ok) - len(dis)) / len(ok) if ok else None
    if verbose:
        print(f"\n=== KALSHI KXBTC15M (CF BRTI composite) vs a Binance-1s proxy ===")
        print(f"  windows        : {len(ok)}  ({min(x['close'] for x in ok)[:10]} .. {max(x['close'] for x in ok)[:10]})")
        print(f"  AGREEMENT      : {len(ok)-len(dis)}/{len(ok)} = {100*agg:.3f}%   disagreements {len(dis)}")
        if dis:
            dd = sorted(abs(x["delta"]) for x in dis)
            print(f"  |delta| at disagreements: min ${dd[0]:.2f} median ${statistics.median(dd):.2f} max ${dd[-1]:.2f}")
        ad = sorted(abs(x["delta"]) for x in ok)
        q = lambda p: ad[min(len(ad) - 1, int(p * (len(ad) - 1)))]
        print(f"  |proxy delta| : p05 ${q(.05):.2f} | median ${q(.50):.2f} | p95 ${q(.95):.2f}")
        for thr in (1, 5, 10, 25, 50, 100):
            n = sum(1 for x in ok if abs(x["delta"]) < thr)
            print(f"    within +/-${thr:>3} of the knife edge: {n:>5} ({100*n/len(ok):5.2f}%)")
        print(f"\n=== DECISION CURVE — calling a window off the tape m minutes in ===")
        print(f"  {'min':>4} | {'acc':>7} {'|marg| med':>11} | " + " | ".join(f"${d}" for d in (25, 50, 100, 200)))
        for m in (0, 1, 2, 4, 6, 8, 10, 12, 13, 14):
            use = [(c["px"][m], c["crit"], c["result"]) for c in curves
                   if c["px"].get(m) is not None and c.get("crit") and c.get("result") in ("yes", "no")]
            if not use:
                continue
            def acc(sub):
                return (None, 0) if not sub else (
                    sum(1 for px, cr, res in sub if (px >= cr) == (res == "yes")) / len(sub), len(sub))
            a_all, _ = acc(use)
            margs = [abs(px - cr) for px, cr, _ in use]
            cells = []
            for d in (25, 50, 100, 200):
                a, n = acc([x for x in use if abs(x[0] - x[1]) >= d])
                cells.append(f"{'--' if a is None else f'{a:.1%}'}({n})")
            print(f"  {m:>4} | {a_all:7.1%} {statistics.median(margs):11.2f} | " + " | ".join(f"{c:<10}" for c in cells))
    return {"windows": len(ok), "agreement": agg, "disagreements": len(dis)}


# ----------------------------------------------------------------- Polymarket: Binance IS the oracle
def strike_of(label):
    lab = label or ""
    s = lab.replace(",", "").replace("↑", "").replace("↓", "").strip()
    if "-" in s and not s.startswith("-"):
        a, b = s.split("-")[:2]
        try:
            return (float(a), float(b)), "range"
        except ValueError:
            return None, None
    if s.startswith("<"):
        return float(s[1:]), "lt"
    if s.startswith(">"):
        return float(s[1:]), "gt"
    try:
        v = float(s)
    except ValueError:
        return None, None
    return v, ("down" if "↓" in lab else "up" if "↑" in lab else "eq")


def outcome_of(market):
    try:
        prices = json.loads(market.get("outcomePrices") or "[]")
        outs = json.loads(market.get("outcomes") or "[]")
        if not prices:
            return None
        i = max(range(len(prices)), key=lambda j: float(prices[j]))
        return outs[i] if i < len(outs) else str(i)
    except Exception:  # noqa: BLE001
        return None


def klines(symbol, interval, start_ms, end_ms):
    key = CACHE / f"{symbol}-{interval}-{start_ms}-{end_ms}.json"
    if key.exists():
        return json.loads(key.read_text())
    out, cur = [], start_ms
    while cur < end_ms:
        try:
            batch = jget(f"{BV}/api/v3/klines?symbol={symbol}&interval={interval}"
                         f"&startTime={cur}&endTime={end_ms}&limit=1000")
        except urllib.error.HTTPError:
            break
        if not batch:
            break
        for k in batch:
            out.append({"open_ms": k[0], "open": float(k[1]), "high": float(k[2]),
                        "low": float(k[3]), "close": float(k[4])})
        nxt = batch[-1][6] + 1
        if nxt <= cur:
            break
        cur = nxt
        if len(batch) < 1000:
            break
    key.write_text(json.dumps(out))
    return out


def bar(bars, anchor_ms, bar_ms):
    """The candle ENDING at anchor_ms (open = anchor - bar_ms)."""
    for b in bars:
        if b["open_ms"] == anchor_ms - bar_ms:
            return b
    return None


def pm_reconcile(days_back=3, verbose=True, assets=None):
    """Reproduce the venue's OWN recorded verdict for every Binance-settled family in scope.

    Families (all pinned to Binance by the market's own rule text):
      hourly above-ladder  {asset}-above-on-<mon>-<d>-<year>-<h><am|pm>-et   -> 1m candle closing at the hour
      hourly up-or-down    {asset}-up-or-down-...                            -> 1h candle BEGINNING at the hour
      daily hit-ladder     what-price-will-{asset}-hit-on-<date>             -> up-arrow reads High, down reads Low
      noon-close ranges    {asset}-price-on-<date> / {asset}-above-on-<date> -> noon 1m Close
    """
    assets = assets or list(ASSETS)
    days = [(datetime.now(timezone.utc) - timedelta(days=k)).astimezone(ET) for k in range(1, days_back + 1)]
    tally = {}

    def note(key, ok):
        a, b = tally.get(key, (0, 0))
        tally[key] = (a + (1 if ok else 0), b + 1)

    def closed_event(slug):
        try:
            r = jget(f"{GAMMA}/events?slug={slug}")
        except Exception:  # noqa: BLE001
            return None
        return r[0] if r and r[0].get("closed") else None

    for asset in assets:
        sym = ASSETS[asset]
        for d in days:
            ds = d.strftime("%Y-%m-%d")
            ld = f"{d.strftime('%B').lower()}-{d.day}-{d.year}"

            # ---- daily hit ladder: up-arrow = any 1m High >= strike, down-arrow = any 1m Low <= strike
            e = closed_event(f"what-price-will-{asset}-hit-on-{ld}")
            if e:
                o0 = datetime.fromisoformat(f"{ds}T00:00:00").replace(tzinfo=ET).astimezone(timezone.utc)
                bars = klines(sym, "1m", int(o0.timestamp() * 1000), int((o0 + timedelta(days=1)).timestamp() * 1000))
                if bars:
                    hi = max(b["high"] for b in bars)
                    lo = min(b["low"] for b in bars)
                    for m in e["markets"]:
                        val, kind = strike_of(m.get("groupItemTitle"))
                        if val is None:
                            continue
                        ours = ("Yes" if lo <= val else "No") if kind == "down" else ("Yes" if hi >= val else "No")
                        note((asset, "hit_day"), ours == outcome_of(m))

            # ---- noon-close ranges
            for slug in (f"{asset}-price-on-{ld}", f"{asset}-above-on-{ld}"):
                e = closed_event(slug)
                if not e:
                    continue
                anchor = datetime.fromisoformat(f"{ds}T12:00:00").replace(tzinfo=ET).astimezone(timezone.utc)
                ams = int(anchor.timestamp() * 1000)
                b = bar(klines(sym, "1m", ams - 7200_000, ams), ams, 60_000)
                if b is None:
                    continue
                for m in e["markets"]:
                    val, kind = strike_of(m.get("groupItemTitle"))
                    if val is None:
                        continue
                    if kind == "range":
                        ours = "Yes" if val[0] < b["close"] <= val[1] else "No"
                    elif kind == "lt":
                        ours = "Yes" if b["close"] < val else "No"
                    elif kind == "gt":
                        ours = "Yes" if b["close"] > val else "No"
                    else:
                        continue
                    note((asset, "noon_close"), ours == outcome_of(m))

            # ---- hourly ladders + hourly up-or-down
            for hour in range(24):
                hr, ap = hour % 12 or 12, ("am" if hour < 12 else "pm")
                anchor = datetime.fromisoformat(f"{ds}T{hour:02d}:00:00").replace(tzinfo=ET).astimezone(timezone.utc)
                ams = int(anchor.timestamp() * 1000)
                e = closed_event(f"{asset}-above-on-{ld}-{hr}{ap}-et")
                if e:
                    b = bar(klines(sym, "1m", ams - 3 * 3600_000, ams), ams, 60_000)
                    if b is not None:
                        for m in e["markets"]:
                            val, kind = strike_of(m.get("groupItemTitle"))
                            if val is None:
                                continue
                            note((asset, "hourly_above"), ("Yes" if b["close"] > val else "No") == outcome_of(m))
                e = closed_event(f"{asset}-up-or-down-{ld}-{hr}{ap}-et")
                if e:
                    # TRAP: the 1h candle BEGINS at the stated hour (anchoring on the candle that ENDS
                    # there scored 43% - worse than a coin flip - before this was fixed).
                    b = next((x for x in klines(sym, "1h", ams - 3 * 3600_000, ams + 3600_000) if x["open_ms"] == ams), None)
                    if b is not None:
                        ours = "Up" if b["close"] >= b["open"] else "Down"
                        note((asset, "updown_1h"), ours == outcome_of(e["markets"][0]))

    if verbose:
        print(f"\n=== POLYMARKET (Binance IS the pinned resolution source) vs our own archive pull ===")
        print(f"  {'asset':<13}{'family':<14}{'ok':>7}{'n':>7}   rate")
        for (a, f) in sorted(tally):
            ok, n = tally[(a, f)]
            flag = "" if ok == n else "   <-- MISS"
            print(f"  {a:<13}{f:<14}{ok:>7}{n:>7}   {100*ok/n:6.2f}%{flag}" if n else "")
        tot_ok = sum(v[0] for v in tally.values())
        tot = sum(v[1] for v in tally.values())
        if tot:
            print(f"  {'TOTAL':<27}{tot_ok:>7}{tot:>7}   {100*tot_ok/tot:6.2f}%")
    return {"families": {f"{a}|{f}": list(v) for (a, f), v in tally.items()},
            "ok": sum(v[0] for v in tally.values()), "n": sum(v[1] for v in tally.values())}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--days", type=int, default=3, help="days back for the Polymarket leg")
    ap.add_argument("--assets", default="all", help="comma list of %s, or 'all'" % ",".join(ASSETS))
    ap.add_argument("--futures", action="store_true", help="also verify the futures ARCHIVE (funding, OI, L/S)")
    ap.add_argument("--days-futures", type=int, default=2, help="archive day to probe for futures")
    ap.add_argument("--max-archive-days", type=int, default=DEFAULT_HISTORY_DAYS,
                    help="HISTORY CAP: how far back the 1-second archive may be pulled per run")
    a = ap.parse_args()
    assets = list(ASSETS) if a.assets == "all" else [x.strip() for x in a.assets.split(",") if x.strip()]
    bad = [x for x in assets if x not in ASSETS]
    if bad:
        print(f"unknown asset(s): {bad}; known: {list(ASSETS)}")
        return 2
    WORK.mkdir(parents=True, exist_ok=True); CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print("=== 1. Binance host reachability from this host (keyless) ===")
    hosts = probe_hosts()
    for h in hosts:
        print(f"  {h['host']:<38} HTTP {h['http']} {h['ms']} ms " + (h.get("note", "") or ""))
    print("  (api.binance.com / fapi REST are 451 here -> no LIVE funding or open interest;"
          " the archive below is the workaround)")

    fut = None
    if a.futures:
        day = (datetime.now(timezone.utc) - timedelta(days=a.days_futures)).strftime("%Y-%m-%d")
        print(f"\n=== 2. futures ARCHIVE (non-blocked host; T+1, not a live feed) [{day}] ===")
        fut = futures_check(day)

    recs, curves = kalshi_reconcile()
    k = summarise_kalshi(recs, curves)
    print(f"\n=== VENUE SCOPE: Kalshi is a PROXY here, never an oracle ===")
    print(f"  settled on CF Benchmarks BRTI (composite; Binance is not a constituent), so this leg can")
    print(f"  only ever produce an ERROR RATE for a Binance-based signal - it is not a settlement source.")
    print(f"\n=== {len(assets)}-asset Polymarket leg (Binance IS the pinned oracle) ===")
    p = pm_reconcile(a.days, assets=assets)
    print(f"\nhistory cap: {a.max_archive_days} d of 1s archive per run | archive days pulled this run: "
          f"{TAPE_STATS['archive_days']} oldest {TAPE_STATS['oldest_pulled']}")
    print(f"total runtime {time.time()-t0:.0f}s")
    if a.json:
        Path(a.json).write_text(json.dumps({"hosts": hosts, "futures": fut, "kalshi": k,
                                            "polymarket": {"ok": p["ok"], "n": p["n"], "families": p["families"]},
                                            "history_cap_days": a.max_archive_days}, indent=1))
        print(f"wrote {a.json}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
