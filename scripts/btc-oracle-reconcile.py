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


# ----------------------------------------------------------------- Binance tape
def day_tape(day):
    """{epoch_ms: close} for one UTC day from the keyless daily zip, or None if not published."""
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


def pm_reconcile(days_back=3, verbose=True):
    days = [(datetime.now(timezone.utc) - timedelta(days=k)).astimezone(ET) for k in range(1, days_back + 1)]
    tally = {}
    def note(fam, ok, tot):
        a, b = tally.get(fam, (0, 0))
        tally[fam] = (a + (1 if ok else 0), b + 1)

    for d in days:
        ds, ld = d.strftime("%Y-%m-%d"), f"{d.strftime('%B').lower()}-{d.day}-{d.year}"
        # hourly ladders --------------------------------------------------------------
        for hour in range(24):
            hr, ap = hour % 12 or 12, ("am" if hour < 12 else "pm")
            anchor = datetime.fromisoformat(f"{ds}T{hour:02d}:00:00").replace(tzinfo=ET).astimezone(timezone.utc)
            ams = int(anchor.timestamp() * 1000)
            for fam, slug in (("above_ladder", f"bitcoin-above-on-{ld}-{hr}{ap}-et"),
                              ("updown_1h", f"bitcoin-up-or-down-{ld}-{hr}{ap}-et")):
                try:
                    r = jget(f"{GAMMA}/events?slug={slug}")
                except Exception:  # noqa: BLE001
                    continue
                if not r or not r[0].get("closed"):
                    continue
                e = r[0]
                if fam == "above_ladder":
                    bars1m = klines("BTCUSDT", "1m", ams - 3 * 3600_000, ams)
                    b = bar(bars1m, ams, 60_000)
                    for m in e["markets"]:
                        val, kind = strike_of(m.get("groupItemTitle"))
                        if b is None or val is None:
                            continue
                        ours = "Yes" if b["close"] > val else "No"
                        note(fam, ours == outcome_of(m), 1)
                else:
                    bars1h = klines("BTCUSDT", "1h", ams - 3 * 3600_000, ams + 3600_000)
                    b = next((x for x in bars1h if x["open_ms"] == ams), None)   # candle BEGINS at anchor
                    if b is None:
                        continue
                    ours = "Up" if b["close"] >= b["open"] else "Down"
                    note(fam, ours == outcome_of(e["markets"][0]), 1)
        # daily "hit" ladder (High for ↑, Low for ↓) ---------------------------------
        try:
            r = jget(f"{GAMMA}/events?slug=what-price-will-bitcoin-hit-on-{ld}")
        except Exception:  # noqa: BLE001
            r = None
        if r and r[0].get("closed"):
            day_open = datetime.fromisoformat(f"{ds}T00:00:00").replace(tzinfo=ET).astimezone(timezone.utc)
            bars = klines("BTCUSDT", "1m", int(day_open.timestamp() * 1000),
                          int((day_open + timedelta(days=1)).timestamp() * 1000))
            if bars:
                hi = max(b["high"] for b in bars)
                lo = min(b["low"] for b in bars)
                for m in r[0]["markets"]:
                    val, kind = strike_of(m.get("groupItemTitle"))
                    if val is None:
                        continue
                    ours = ("Yes" if lo <= val else "No") if kind == "down" else ("Yes" if hi >= val else "No")
                    note("hit_day", ours == outcome_of(m), 1)
        # noon-close ranges ----------------------------------------------------------
        for slug in (f"bitcoin-price-on-{ld}", f"bitcoin-above-on-{ld}"):
            try:
                r = jget(f"{GAMMA}/events?slug={slug}")
            except Exception:  # noqa: BLE001
                continue
            if not r or not r[0].get("closed"):
                continue
            anchor = datetime.fromisoformat(f"{ds}T12:00:00").replace(tzinfo=ET).astimezone(timezone.utc)
            ams = int(anchor.timestamp() * 1000)
            b = bar(klines("BTCUSDT", "1m", ams - 7200_000, ams), ams, 60_000)
            if b is None:
                continue
            for m in r[0]["markets"]:
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
                note("noon_close", ours == outcome_of(m), 1)

    if verbose:
        print(f"\n=== POLYMARKET (Binance IS the pinned resolution source) vs our own archive pull ===")
        tot_ok = tot = 0
        for fam in sorted(tally):
            ok, n = tally[fam]
            tot_ok += ok; tot += n
            print(f"  {fam:<14} {ok}/{n} = {100*ok/n:6.2f}%" if n else "")
        print(f"  {'TOTAL':<14} {tot_ok}/{tot} = {100*tot_ok/tot:6.2f}%" if tot else "  no markets captured")
    return {"families": tally, "ok": sum(v[0] for v in tally.values()), "n": sum(v[1] for v in tally.values())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--days", type=int, default=3, help="days back for the Polymarket leg")
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True); CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print("=== 1. Binance host reachability from this host (keyless) ===")
    hosts = probe_hosts()
    for h in hosts:
        print(f"  {h['host']:<38} HTTP {h['http']} {h['ms']} ms " + (h.get("note", "") or ""))

    recs, curves = kalshi_reconcile()
    k = summarise_kalshi(recs, curves)
    p = pm_reconcile(a.days)
    print(f"\ntotal runtime {time.time()-t0:.0f}s")
    if a.json:
        Path(a.json).write_text(json.dumps({"hosts": hosts, "kalshi": k,
                                            "polymarket": {"ok": p["ok"], "n": p["n"],
                                                           "families": {k2: list(v) for k2, v in p["families"].items()}}},
                                           indent=1))
        print(f"wrote {a.json}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
