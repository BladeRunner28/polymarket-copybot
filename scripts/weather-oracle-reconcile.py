#!/usr/bin/env python3
"""Weather-market oracle reconciliation + data-source availability probe (READ-ONLY).

Question it answers: can FREE, KEYLESS public data reproduce the weather markets'
own settlement verdicts — and is there enough history to backtest a predictive edge?

Measured here (no venue keys, no writes outside the cache dir):
  1. KALSHI KXHIGHNY (NYC daily high) settled markets  vs  GHCN-Daily Central Park TMAX
  2. POLYMARKET "highest temperature in NYC" closed events  vs  IEM ASOS hourly METAR @ KLGA
     — reported per slug era, because PM reused year-less slugs in 2025 (slug/year trap)
  3. the SAME PM verdicts against the wrong products (GHCN daily vs hourly METAR; LGA vs
     Central Park) — this is the trap: using the daily summary drops the match rate to ~55%
  4. availability/depth of the forward-looking side (forecast + ensemble + archived forecast
     runs) and of venue price history (Kalshi candlesticks, PM prices-history)

CITY TABLE (added 2026-10-27, card weather-city-dfw-set1): the same four measurements are carried per
city -- never a copy of this file per city. `--city dfw` reconciles Kalshi KXHIGHTDAL against GHCN
DFW-airport daily TMAX and Polymarket "highest temperature in Dallas" against hourly METAR at KDAL
(Love Field), with the wrong-station/wrong-product controls built in for that city. It also prints the
CONSECUTIVE reconciled days, which is the Set-2 gate condition ("5 consecutive days, zero mismatches")
and which no single run can substitute for.

Usage:  python3 scripts/weather-oracle-reconcile.py [--city nyc|dfw] [--json /tmp/out.json]
Exit code is always 0 unless the network is unreachable; a low match rate is a FINDING, not an error.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import statistics
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

UA = {"User-Agent": "medusa-weather-recon/1.0 (read-only research)"}
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
IEM = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
GHCN = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access"
CP_STATION = "USW00094728"   # Central Park  (Kalshi CLINYC oracle)
LGA_STATION = "USW00014732"  # LaGuardia     (Polymarket oracle)
DFW_STATION = "USW00003927"  # DFW airport   (Kalshi CLIDFW oracle)

CITIES = {
    # NYC — the published read. Every value here is the pre-2026-10-27 hardcode.
    "nyc": {
        "kalshi_series": "KXHIGHNY",
        "pm_slug_prefix": "highest-temperature-in-nyc",
        "kalshi_ghcn": ("Central Park", CP_STATION),
        "pm_ghcn": ("LaGuardia", LGA_STATION),
        "pm_iem_station": "LGA",
        "iem_alt_station": "NYC",
        "iem_span": ((2025, 9, 28), (2026, 10, 12)),
        "tz": "America/New_York",
        "lat": "40.7769", "lon": "-73.8740",
        "nws_station": "KLGA",
        "pm_probes": [("2026-10", 2026, 10, 11), ("2025-10", 2025, 10, 11)],
    },
    # DFW — card weather-city-dfw-set1. PM settles at KDAL (Love Field) from hourly routine METAR;
    # Kalshi settles at CLIDFW (DFW airport) from a TWC DAILY summary published in degF. Different
    # airports, different products — so the PM arm's controls are the OTHER airport (DFW) and the
    # DAILY product at DFW, and there is no GHCN Love Field series (Love Field is not a GHCN station;
    # the IEM ASOS hourly record IS the PM oracle, so it needs no proxy).
    "dfw": {
        "kalshi_series": "KXHIGHTDAL",
        "pm_slug_prefix": "highest-temperature-in-dallas",
        "kalshi_ghcn": ("DFW airport", DFW_STATION),
        "pm_ghcn": None,
        "pm_iem_station": "DAL",
        "iem_alt_station": "DFW",
        "iem_span": ((2026, 9, 1), (2026, 10, 27)),
        "tz": "America/Chicago",
        "lat": "32.8471", "lon": "-96.8517",
        "nws_station": "KDAL",
        "pm_probes": [("2026-10", 2026, 10, 26), ("2026-09", 2026, 9, 30)],
    },
}
F = lambda c: c * 9 / 5 + 32


def get(url: str, tries: int = 3) -> bytes:
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("unreachable")


# ---------------------------------------------------------------- station data
def ghcn_daily(station: str, cache: Path) -> dict[str, float]:
    """{iso_date: TMAX in F}. GHCN raw TMAX is TENTHS of degC — reading it as F is the classic
    unit bug (206.0 = 20.6C = 69F), and it silently ruins any reconciliation."""
    p = cache / f"{station}.csv"
    if not p.exists() or time.time() - p.stat().st_mtime > 86400:
        p.write_bytes(get(f"{GHCN}/{station}.csv"))
    out: dict[str, float] = {}
    with p.open() as fh:
        for row in csv.DictReader(fh):
            t = (row.get("TMAX") or "").strip()
            if t:
                out[row["DATE"]] = F(int(t) / 10.0)
    return out


def iem_hourly(station: str, y1: int, m1: int, d1: int, y2: int, m2: int, d2: int,
               tz_name: str = "America/New_York") -> dict[str, float]:
    """Daily MAX of the routine hourly METAR tmpf (= the 'Temp' column NWS shows, whole F)."""
    url = (f"{IEM}?station={station}&data=tmpf&year1={y1}&month1={m1}&day1={d1}"
           f"&year2={y2}&month2={m2}&day2={d2}&tz={tz_name.replace('/', '%2F')}&format=onlycomma"
           f"&latlon=no&missing=M&trace=T&direct=no&report_type=3")
    txt = get(url).decode("utf-8", "replace")
    d: dict[str, float] = {}
    for row in csv.DictReader(io.StringIO(txt)):
        v = (row.get("tmpf") or "").strip()
        if not v or not (v[0].isdigit() or v[0] == "-"):
            continue
        day, val = row["valid"][:10], float(v)
        if day not in d or val > d[day]:
            d[day] = val
    return d


# ---------------------------------------------------------------- Polymarket
def pm_verdict(slug: str) -> dict | None:
    d = json.loads(get(f"{GAMMA}/events?slug={slug}"))
    if not d:
        return None
    e = d[0]
    yes = [m.get("groupItemTitle") for m in e.get("markets", [])
           if json.loads(m.get("outcomePrices") or "[]")[:1] in (["1"], [1], [1.0])]
    return {"slug": e["slug"], "obs_day": e["endDate"][:10], "yes": yes,
            "n_markets": len(e.get("markets", [])), "volume": e.get("volume")}


def bracket(label: str) -> tuple[int | None, int | None]:
    s = label.replace("°F", "").replace("°", "").replace("or below", "").replace("or above", "").strip()
    if "-" in s:
        a, b = s.split("-")[:2]
        return int(a), int(b)
    v = int(s.split()[0])
    if "below" in label:
        return None, v
    if "above" in label:
        return v, None
    return v, v


def fits(obs: float | None, rng: tuple[int | None, int | None]) -> bool | None:
    if obs is None:
        return None
    lo, hi = rng
    return (lo is None or obs >= lo) and (hi is None or obs <= hi)


MONTHS = ["january", "february", "march", "april", "may", "june",
          "july", "august", "september", "october", "november", "december"]


def pm_days(year: int, month: int, n: int, slug_prefix: str) -> dict[str, dict]:
    """PM daily high-temp NYC events for `month`, `n` days. 2026 era slugs carry the year
    (`...-on-october-5-2026`); the 2025 era reused a YEAR-LESS slug, so the same URL returns the
    2025 market whatever year you have in mind — the event's own endDate is the only honest key."""
    out = {}
    for d in range(1, n + 1):
        slug = f"{slug_prefix}-on-{MONTHS[month - 1]}-{d}" + (f"-{year}" if year >= 2026 else "")
        try:
            v = pm_verdict(slug)
        except Exception:
            v = None
        if v and v["yes"]:
            out[v["obs_day"]] = v
    return out


# ---------------------------------------------------------------- Kalshi
def kalshi_settled(series: str) -> list[dict]:
    mk, cur = [], None
    while True:
        u = f"{KALSHI}/markets?series_ticker={series}&status=settled&limit=1000" + (f"&cursor={cur}" if cur else "")
        d = json.loads(get(u))
        mk += d.get("markets", [])
        cur = d.get("cursor")
        if not cur:
            return mk


def kalshi_inside(m: dict, v: int) -> bool:
    """Strike semantics, pinned by measurement: 'greater' (T-ticker, floor=87) reads '88 or above'
    -> obs >= floor+1; 'less' (T-ticker, cap=72) reads '71 or below' -> obs <= cap-1;
    'between' (B-ticker, floor/cap = 74/75) is INCLUSIVE. One convention for all three scores 384/396."""
    f, c, st = m.get("floor_strike"), m.get("cap_strike"), m.get("strike_type")
    if st == "greater":
        return f is None or v >= f + 1
    if st == "less":
        return c is None or v <= c - 1
    return (f is None or v >= f) and (c is None or v <= c)


def kalshi_day(et: str) -> str:
    fm = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}
    s = et.split("-")[-1]
    return f"20{s[0:2]}-{fm[s[2:5]]:02d}-{int(s[5:7]):02d}"


# ---------------------------------------------------------------- probes
def availability(cache: Path, city: dict) -> dict:
    out: dict[str, object] = {}
    lat, lon = city["lat"], city["lon"]
    tzq = city["tz"].replace("/", "%2F")
    try:
        d = json.loads(get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                           f"&daily=temperature_2m_max&temperature_unit=fahrenheit&timezone={tzq}&forecast_days=4"))
        out["forecast_openmeteo_daily_max"] = dict(zip(d["daily"]["time"], d["daily"]["temperature_2m_max"]))
    except Exception as e:
        out["forecast_openmeteo_daily_max"] = f"FAIL {e}"
    try:
        d = json.loads(get(f"https://ensemble-api.open-meteo.com/v1/ensemble?latitude={lat}&longitude={lon}"
                           f"&daily=temperature_2m_max&temperature_unit=fahrenheit&timezone={tzq}"
                           f"&forecast_days=3&models=gfs_seamless"))
        keys = [k for k in d["daily"] if k.startswith("temperature_2m_max")]
        out["ensemble_members"] = len(keys)
        out["ensemble_day0_mean_maxF"] = round(statistics.mean([v for v in d["daily"][keys[0]] if v is not None]), 1)
    except Exception as e:
        out["ensemble_members"] = f"FAIL {e}"
    for y in (2022, 2024):
        try:
            d = json.loads(get(f"https://historical-forecast-api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                               f"&start_date={y}-06-01&end_date={y}-06-03&daily=temperature_2m_max"
                               f"&temperature_unit=fahrenheit&timezone={tzq}"))
            out[f"archived_forecast_{y}"] = d["daily"]["temperature_2m_max"]
        except Exception as e:
            out[f"archived_forecast_{y}"] = f"FAIL {e}"
    try:
        st = city["nws_station"]
        n = len(json.loads(get(f"https://api.weather.gov/stations/{st}/observations?limit=5"))["features"])
        out[f"nws_obs_{st.lower()}_fetched"] = n
    except Exception as e:
        out[f"nws_obs_{city['nws_station'].lower()}_fetched"] = f"FAIL {e}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None, help="also write the numbers as JSON here")
    ap.add_argument("--cache", default="/tmp/weather-recon")
    ap.add_argument("--city", default="nyc", choices=sorted(CITIES),
                    help="city key from the CITY TABLE (default nyc — the published read)")
    a = ap.parse_args()
    city = CITIES[a.city]
    serie = city["kalshi_series"]
    cache = Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    rep: dict[str, object] = {"city": a.city}

    print(f"== station data (keyless) [{a.city}] ==")
    k_label, k_ghcn = city["kalshi_ghcn"]
    p_label, p_ghcn = city["pm_ghcn"] if city["pm_ghcn"] else (None, None)
    g_kalshi = ghcn_daily(k_ghcn, cache)
    g_pm = ghcn_daily(p_ghcn, cache) if p_ghcn else {}
    for nm, s in ((f"GHCN {k_label}", g_kalshi), (f"GHCN {p_label}", g_pm)):
        if not s:
            continue
        ks = sorted(s)
        print(f"  {nm:<18} rows={len(s):>6}  {ks[0]} -> {ks[-1]}")
    rep["ghcn"] = {n: ({"rows": len(s), "first": min(s), "last": max(s)} if s else {})
                   for n, s in (("kalshi_station", g_kalshi), ("pm_station", g_pm))}

    # ---------------------------------------------------------------- 1. Kalshi arm
    print(f"\n== 1. KALSHI {serie} settled verdicts vs GHCN {k_label} (tenths C -> F, nearest int) ==")
    mk = kalshi_settled(serie)
    byday: dict[str, list[dict]] = defaultdict(list)
    for m in mk:
        if m.get("result") in ("yes", "no"):
            byday[m["event_ticker"]].append(m)
    days_ok = days_bad = n_obs = tot = good = 0
    day_ok_map: dict[str, bool] = {}
    for et, ms in sorted(byday.items()):
        obs = g_kalshi.get(kalshi_day(et))
        if obs is None:
            n_obs += 1
            continue
        v = int(round(obs))
        day_ok = True
        for m in ms:
            tot += 1
            if kalshi_inside(m, v) == (m["result"] == "yes"):
                good += 1
            else:
                day_ok = False
        day_ok_map[kalshi_day(et)] = day_ok
        days_ok += day_ok
        days_bad += not day_ok
    streak_now = streak_max = 0
    for day in sorted(day_ok_map):
        streak_now = streak_now + 1 if day_ok_map[day] else 0
        streak_max = max(streak_max, streak_now)
    print(f"  settled markets={len(mk)}  event days={len(byday)}  "
          f"days without GHCN obs={n_obs}")
    print(f"  DAY-LEVEL   {days_ok}/{days_ok + days_bad} fully reconciled")
    print(f"  VERDICT-LEVEL {good}/{tot} brackets reproduced")
    print(f"  CONSECUTIVE reconciled days: current={streak_now} max={streak_max} "
          f"(the Set-2 gate asks for >= 5 with ZERO mismatches; a no-obs day breaks the run, "
          f"it is never counted as a match)")
    rep["kalshi_reconcile"] = {"markets": len(mk), "days": len(byday), "days_no_obs": n_obs,
                              "days_reconciled": days_ok, "days_checked": days_ok + days_bad,
                              "verdicts_reproduced": good, "verdicts_checked": tot,
                              "streak_now": streak_now, "streak_max": streak_max,
                              "last_day": max(day_ok_map) if day_ok_map else None}

    # ---------------------------------------------------------------- 2. PM arm
    print(f"\n== 2. POLYMARKET {city['pm_slug_prefix']} closed events vs hourly METAR @ "
          f"{city['pm_iem_station']} ==")
    (sy, sm, sd), (ey, em, ed) = city["iem_span"]
    hr_pm = iem_hourly(city["pm_iem_station"], sy, sm, sd, ey, em, ed, tz_name=city["tz"])
    hr_alt = iem_hourly(city["iem_alt_station"], sy, sm, sd, ey, em, ed, tz_name=city["tz"])
    srcs = {f"ASOS hourly {city['pm_iem_station']}": hr_pm,
            f"ASOS hourly {city['iem_alt_station']}": hr_alt}
    if g_kalshi and city["kalshi_ghcn"][1] != (p_ghcn or ""):
        srcs[f"GHCN daily {k_label}"] = g_kalshi
    if g_pm:
        srcs[f"GHCN daily {p_label}"] = g_pm
    pm_rep: dict[str, object] = {}
    detail_days: dict[str, dict] = {}
    for label, year, month, ndays in city["pm_probes"]:
        days = pm_days(year, month, ndays, city["pm_slug_prefix"])
        print(f"  -- {label} era: {len(days)} resolved days, slugs "
              f"{'year-suffixed' if year >= 2026 else 'YEAR-LESS (reused)'}")
        if year >= 2026:
            detail_days.update(days)
        for nm, s in srcs.items():
            h = mi = nb = 0
            for day, v in sorted(days.items()):
                r = fits(s.get(day), bracket(v["yes"][0]))
                if r is None:
                    nb += 1
                elif r:
                    h += 1
                else:
                    mi += 1
            print(f"       {nm:<26} {h}/{h + mi}" + (f"  (no obs {nb})" if nb else ""))
            pm_rep[f"{label}:{nm}"] = {"match": h, "checked": h + mi, "no_obs": nb}
    rep["pm_reconcile"] = pm_rep
    if detail_days:
        print(f"\n  PM verdict detail (current-era rule, {city['pm_iem_station']} hourly):")
        for day, v in sorted(detail_days.items()):
            alt = None if g_kalshi.get(day) is None else round(g_kalshi[day])
            print(f"       {day} PM={v['yes'][0]:<12} ASOS_hourly_{city['pm_iem_station']}="
                  f"{hr_pm.get(day)}  GHCN_{k_label}={alt}")

    # ---------------------------------------------------------------- 3. breadth
    print("\n== 3. forward-looking + price history (keyless?) ==")
    for k, v in availability(cache, city).items():
        print(f"  {k}: {v}")
    try:
        openmk = json.loads(get(f"{KALSHI}/markets?series_ticker={serie}&status=open&limit=200"))["markets"]
        print(f"  kalshi open {serie} markets={len(openmk)}  "
              f"cycles={sorted({m['ticker'].split('-')[1] for m in openmk})}")
        tk = openmk[0]["ticker"]
        now = int(time.time())
        c = json.loads(get(f"{KALSHI}/series/{serie}/markets/{tk}/candlesticks?start_ts={now - 86400}"
                           f"&end_ts={now}&period_interval=60"))
        print(f"  kalshi candlesticks on a LIVE market ({tk}): {len(c.get('candlesticks', []))} hourly candles")
    except Exception as e:
        print(f"  kalshi live probe FAIL {e}")
    try:
        label, year, month, ndays = city["pm_probes"][0]
        last_day = (max((v["obs_day"] for v in detail_days.values()), default=None)
                    or (dt.date.today() - dt.timedelta(days=1)).isoformat())
        yy, mm, dd = (int(x) for x in last_day.split("-"))
        slug = f"{city['pm_slug_prefix']}-on-{MONTHS[mm - 1]}-{dd}-{yy}"
        e = json.loads(get(f"{GAMMA}/events?slug={slug}"))[0]
        m = e["markets"][0]
        tok = json.loads(m["clobTokenIds"])[0]
        h = json.loads(get(f"{CLOB}/prices-history?market={tok}&interval=max&fidelity=60")).get("history", [])
        if h:
            f0 = dt.datetime.fromtimestamp(h[0]["t"], dt.timezone.utc)
            f1 = dt.datetime.fromtimestamp(h[-1]["t"], dt.timezone.utc)
            print(f"  PM prices-history keyless ({slug}): {len(h)} hourly points "
                  f"{f0:%Y-%m-%dT%H:%MZ} -> {f1:%Y-%m-%dT%H:%MZ} "
                  f"(acceptingOrders={m.get('acceptingOrders')}, venue endDate={m.get('endDate')})")
    except Exception as e:
        print(f"  PM price-history probe FAIL {e}")

    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=1) + "\n")
        print(f"\nJSON -> {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
