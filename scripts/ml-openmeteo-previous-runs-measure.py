#!/usr/bin/env python3
"""Open-Meteo previous-runs NWP as a weather feature — REC 1 measurement (Lane A, read-only).

Card: roadmap `ml-feed-openmeteo-previous-runs`. Draft: drafts/ml-feed-openmeteo-previous-runs-20261029.md.

WHAT IT DOES
------------
Fetches (keyless) the AS-ISSUED forecast of each settlement station's daily maximum at leads 1 and 2
from Open-Meteo previous-runs, and the settled daily maximum from routine hourly METAR (IEM ASOS
report_type=3 — the product the wx2 sampler pins as the oracle basis), then scores settlement-direction
accuracy for three predictors:

  persist  pred = max-so-far                       (the day's max is what we have seen)
  clim     pred = max-so-far + median diurnal rise  (obs-only, no forecast input — the baseline that matters)
  nwp{1,2} pred = max(max-so-far, as-issued peak + bias)   bias = causal trailing-14-day mean error

Direction accuracy is scored on LIVE thresholds (max-so-far+1 .. +12): thresholds at or below max-so-far
are already decided by monotonicity and would inflate every predictor equally.

LEAK WARNING (why lead 0 is excluded)
-------------------------------------
In the previous-runs API the unsuffixed `temperature_2m` is the LATEST model run, so for a past timestamp
it is an analysis that has assimilated observations. A "lead 0" built from it scores 95.65% direction
accuracy here — it is not a forecast. `--show-leaky-lead0` prints it, for audit only. Leak-free leads are
`temperature_2m_previous_day1..7`.

USAGE
-----
  python3 scripts/ml-openmeteo-previous-runs-measure.py --fetch     # cache HTTP (2 requests/station)
  python3 scripts/ml-openmeteo-previous-runs-measure.py --analyze   # tables
  python3 scripts/ml-openmeteo-previous-runs-measure.py --analyze --show-leaky-lead0

Writes only inside its cache dir (default: ~/.hermes/cache/scratch/rec1). Python 3.9+.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import statistics
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PREV = "https://previous-runs-api.open-meteo.com/v1/forecast"
IEM = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
UA = {"User-Agent": "copybot-rec1-previous-runs/1.0 (read-only measurement)"}
MODELS = ["gfs_seamless", "ecmwf_ifs025", "icon_seamless"]

# Settlement stations pinned by the wx1/wx2 cards: never pooled across venues, never shared across cities.
STATIONS = [
    # key, IEM ASOS id, lat, lon, tz
    ("pm_nyc", "LGA", "40.7769", "-73.8740", "America/New_York"),      # Polymarket NYC = KLGA METAR
    ("kalshi_nyc", "NYC", "40.7789", "-73.9692", "America/New_York"),  # Kalshi NYC = CLINYC (Central Park proxy)
    ("pm_dfw", "DAL", "32.8471", "-96.8517", "America/Chicago"),       # Polymarket DFW = KDAL Love Field
    ("kalshi_dfw", "DFW", "32.8975", "-97.0403", "America/Chicago"),   # Kalshi DFW = CLIDFW (DFW airport proxy)
]
TZ = {k: tz for k, _, _, _, tz in STATIONS}
OBSKEY = {"pm_nyc": "klga", "kalshi_nyc": "kalshi_cp", "pm_dfw": "kdal", "kalshi_dfw": "kalshi_dfw"}
HOURS = [6, 9, 12, 15, 18]     # decision hours, local civil time
CORE = (9, 12, 15)             # the window where a same-day decision still has real uncertainty
W = 14                         # causal bias/climatology window, days


def _get(url: str, tries: int = 4) -> bytes:
    last = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2.0 * (i + 1))
    raise last  # type: ignore[misc]


def _cached(path: Path, fn):
    if path.exists() and path.stat().st_size > 200:
        return json.loads(path.read_text())
    obj = fn()
    path.write_text(json.dumps(obj))
    return obj


# ---------------------------------------------------------------- fetch
def fetch(cache: Path, start: date, end: date) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    for key, iem, lat, lon, _tz in STATIONS:
        def _prev(lat=lat, lon=lon):
            q = urllib.parse.urlencode({
                "latitude": lat, "longitude": lon,
                "start_date": start.isoformat(), "end_date": end.isoformat(),
                "hourly": "temperature_2m,temperature_2m_previous_day1,temperature_2m_previous_day2",
                "models": ",".join(MODELS),
            })
            d = json.loads(_get(f"{PREV}?{q}"))
            if d.get("error"):
                raise RuntimeError(d.get("reason"))
            return d

        def _obs(iem=iem):
            q = urllib.parse.urlencode({
                "station": iem, "data": "tmpf",
                "year1": start.year, "month1": start.month, "day1": start.day,
                "year2": end.year, "month2": end.month, "day2": end.day,
                "tz": "UTC", "format": "onlycomma", "latlon": "no",
                "missing": "M", "trace": "T", "direct": "no", "report_type": "3",
            })
            txt = _get(f"{IEM}?{q}").decode("utf-8", "replace")
            rows = []
            for row in csv.DictReader(io.StringIO(txt)):
                v = (row.get("tmpf") or "").strip()
                if v and (v[0].isdigit() or v[0] == "-"):
                    rows.append([row["valid"], float(v)])
            return rows

        prev = _cached(cache / f"prev_{key}.json", _prev)
        obs = _cached(cache / f"obs_{key}.json", _obs)
        print(f"{key:<11} {iem:<4} series={len(prev['hourly']) - 1:<2} hours={len(prev['hourly']['time']):<5}"
              f" obs_rows={len(obs):<5} {prev['hourly']['time'][0]} -> {prev['hourly']['time'][-1]}")


# ---------------------------------------------------------------- data
def c2f(v):
    return None if v is None else v * 9.0 / 5.0 + 32.0


def load(cache: Path, key: str):
    prev = json.loads((cache / f"prev_{key}.json").read_text())
    obs = json.loads((cache / f"obs_{key}.json").read_text())
    tz = ZoneInfo(TZ[key])

    def local(ts: str) -> datetime:
        return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).astimezone(tz)

    obs_by_day: dict = {}
    for ts, f in obs:
        d = local(ts if "T" in ts else ts.replace(" ", "T"))
        obs_by_day.setdefault(d.date().isoformat(), {})[d.hour] = f
    fc: dict = {}
    for k, vals in prev["hourly"].items():
        if k == "time":
            continue
        for ts, v in zip(prev["hourly"]["time"], vals):
            f = c2f(v)
            if f is not None:
                fc.setdefault(k, {}).setdefault(local(ts).date().isoformat(), {})[local(ts).hour] = f
    return obs_by_day, fc


def build(cache: Path, leads=(1, 2)):
    rows, settled = [], {}
    for key in TZ:
        obs_by_day, fc = load(cache, key)
        for day, o in sorted(obs_by_day.items()):
            if len(o) < 20 or max(o) < 21:      # not a fully observed (settled) day
                continue
            A = max(o.values())
            settled[(key, day)] = A
            for h in HOURS:
                sofar = [v for hh, v in o.items() if hh < h]
                if len(sofar) < 3:
                    continue
                f = {}
                for lead in leads:
                    per_model = {}
                    for m in MODELS:
                        k = f"temperature_2m_{m}" if lead == 0 else f"temperature_2m_previous_day{lead}_{m}"
                        rest = [v for hh, v in fc.get(k, {}).get(day, {}).items() if hh >= h]
                        if len(rest) >= 6:
                            per_model[m] = max(rest)
                    if len(per_model) == 3:
                        f[lead] = per_model
                rows.append({"station": key, "day": day, "hour": h, "A": A, "Mh": max(sofar), "fc": f})
    return rows, settled


# ---------------------------------------------------------------- scoring
def params_for(history):
    clim, bias = {}, {}
    for st in TZ:
        for h in HOURS:
            v = [r["A"] - r["Mh"] for r in history if r["station"] == st and r["hour"] == h]
            if v:
                clim[(st, h)] = statistics.median(v)
    for lead in (0, 1, 2):
        for m in MODELS:
            for st in TZ:
                e = [r["A"] - r["fc"][lead][m] for r in history if r["station"] == st and lead in r["fc"]]
                if e:
                    bias[(lead, m, st)] = statistics.mean(e)
    return clim, bias


def predictors(clim, bias):
    def persist(r):
        return r["Mh"]

    def clim_p(r):
        return r["Mh"] + clim.get((r["station"], r["hour"]), 0.0)

    def nwp(lead):
        def p(r):
            pm = r["fc"].get(lead)
            if not pm:
                return None
            bs = [bias[(lead, m, r["station"])] for m in MODELS if (lead, m, r["station"]) in bias]
            if not bs:
                return None
            return max(r["Mh"], statistics.median(pm.values()) + statistics.mean(bs))
        return p
    out = {"persist": persist, "clim": clim_p}
    for lead in (0, 1, 2):
        out[f"nwp{lead}" if lead else "nwp0_LEAKY"] = nwp(lead)
    return out


def direction(p, rows):
    hit = tot = 0
    for r in rows:
        v = p(r)
        if v is None:
            continue
        for thr in range(int(r["Mh"]) + 1, int(r["Mh"]) + 13):
            tot += 1
            hit += (v >= thr) == (r["A"] >= thr)
    return (100.0 * hit / tot, tot) if tot else (float("nan"), 0)


def analyze(cache: Path, show_leaky=False):
    rows, settled = build(cache, leads=(0, 1, 2) if show_leaky else (1, 2))
    days = sorted({r["day"] for r in rows})
    cut = len(days) // 2
    halves = {"H1": set(days[:cut]), "H2": set(days[cut:])}
    print(f"\nPanel A  (station,day,hour) rows={len(rows)}  station-days="
          f"{len({(r['station'], r['day']) for r in rows})}  settled days={len(days)}  {days[0]}..{days[-1]}")
    by_day: dict = {}
    for r in rows:
        by_day.setdefault(r["day"], []).append(r)
    order = sorted(days)
    cache_params = {}
    for i, d in enumerate(order):
        hist = [r for dd in order[max(0, i - W):i] for r in by_day[dd]]
        cache_params[d] = params_for(hist)

    print(f"causal trailing-{W}-day fit — direction accuracy on live thresholds (Mh+1..Mh+12)")
    print(f"{'half':<5}{'hour':<6}{'n':>6}{'persist':>9}{'clim':>8}{'nwp1':>8}{'d1':>7}{'nwp2':>8}{'d2':>7}")
    res = {}
    for hname, ds in halves.items():
        sel = [r for r in rows if r["day"] in ds]
        for h in [None] + HOURS:
            s = [r for r in sel if h is None or r["hour"] == h]
            vals = {}
            for name in ("persist", "clim", "nwp1", "nwp2"):
                hit = tot = 0
                for r in s:
                    v = predictors(*cache_params[r["day"]])[name](r)
                    if v is None:
                        continue
                    for thr in range(int(r["Mh"]) + 1, int(r["Mh"]) + 13):
                        tot += 1
                        hit += (v >= thr) == (r["A"] >= thr)
                vals[name] = (100.0 * hit / tot if tot else float("nan"), tot)
            res[(hname, h)] = vals
            c = vals["clim"][0]
            print(f"{hname:<5}{str(h or 'ALL'):<6}{vals['clim'][1]:>6}{vals['persist'][0]:>9.2f}{c:>8.2f}"
                  f"{vals['nwp1'][0]:>8.2f}{vals['nwp1'][0]-c:>7.2f}{vals['nwp2'][0]:>8.2f}{vals['nwp2'][0]-c:>7.2f}")
    print("\nsign stability of the delta vs the obs+diurnal baseline (card refutation test):")
    for k in ("nwp1", "nwp2"):
        a = res[("H1", None)][k][0] - res[("H1", None)]["clim"][0]
        b = res[("H2", None)][k][0] - res[("H2", None)]["clim"][0]
        ref = "REFUTED" if (a * b < 0 or min(abs(a), abs(b)) < 2.0) else "not refuted"
        print(f"  {k}: H1 {a:+.2f}pp  H2 {b:+.2f}pp  -> {ref}")
    if show_leaky:
        print("\nLEAKY lead-0 (latest run = analysis for past hours; audit only, never evidence):")
        for hname, ds in halves.items():
            s = [r for r in rows if r["day"] in ds]
            hit = tot = 0
            for r in s:
                v = predictors(*cache_params[r["day"]])["nwp0_LEAKY"](r)
                if v is None:
                    continue
                for thr in range(int(r["Mh"]) + 1, int(r["Mh"]) + 13):
                    tot += 1
                    hit += (v >= thr) == (r["A"] >= thr)
            print(f"  {hname}: {100.0 * hit / max(tot, 1):.2f}%  n={tot}")
    analyze_panel_b(settled, params_for(rows)[0])


def analyze_panel_b(settled, clim):
    repo = Path(__file__).resolve().parent.parent
    files = [("weather-nowcast-samples.jsonl", {"polymarket": "pm_nyc", "kalshi": "kalshi_nyc"}),
             ("weather-nowcast-samples-dfw.jsonl", {"polymarket": "pm_dfw", "kalshi": "kalshi_dfw"})]
    pb = []
    for fn, vmap in files:
        p = repo / "data" / fn
        if not p.exists():
            continue
        ctx = {}
        for line in p.open():
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if r.get("kind") == "context":
                ctx[(r.get("cycle_day"), r.get("ts"))] = r
                continue
            if r.get("kind") != "bracket":
                continue
            st = vmap.get(r.get("venue"))
            day = r.get("cycle_day")
            if not st or not day:
                continue
            A = settled.get((st, day))
            c = ctx.get((day, r.get("ts")))          # same sampler run, never another run of the day
            if A is None or not c:
                continue
            o = (c.get("obs") or {}).get(OBSKEY[st]) or {}
            Mh, F = o.get("max_so_far_F"), c.get("forecast_F")
            if Mh is None or F is None:
                continue
            lo, hi = r.get("bracket_low"), r.get("bracket_high")
            yes = (A >= lo if lo is not None else True) and (A <= hi if hi is not None else True)
            live = not ((hi is not None and Mh > hi) or (lo is not None and hi is None and Mh >= lo))
            pb.append({"station": st, "day": day, "hour": r.get("et_hour", r.get("hour_local")),
                       "lo": lo, "hi": hi, "yes": int(yes), "Mh": Mh, "F": F,
                       "ens": (c.get("ensemble") or {}).get("mean"), "live": live})
    if not pb:
        print("\nPanel B skipped: sampler files not found.")
        return
    live = [r for r in pb if r["live"]]

    def bscore(fn, sel):
        hit = tot = 0
        for r in sel:
            p = fn(r)
            if p is None:
                continue
            tot += 1
            py = (p >= r["lo"] if r["lo"] is not None else True) and (p <= r["hi"] if r["hi"] is not None else True)
            hit += int(py) == r["yes"]
        return (100.0 * hit / tot, tot) if tot else (float("nan"), 0)

    fns = {"persist(Mh)": lambda r: r["Mh"],
           "max(Mh, ens_mean)": lambda r: max(r["Mh"], r["ens"]) if r["ens"] is not None else None,
           "event forecast_F (raw)": lambda r: r["F"],
           "max(Mh, F) (raw)": lambda r: max(r["Mh"], r["F"])}

    # causal debias of the captured forecast: mean(F - A) over days STRICTLY BEFORE the scored day,
    # same station x hour band. This is the fair form — the grid cell is not the station.
    def band(h):
        return 0 if h < 8 else (1 if h < 12 else (2 if h < 16 else 3))

    err: dict = {}
    for r in pb:
        err.setdefault((r["station"], r["day"], band(r["hour"])), []).append(r["F"] - settled[(r["station"], r["day"])])
    err_mean = {k: statistics.mean(v) for k, v in err.items()}
    days_st: dict = {}
    for (st, day, _b) in err_mean:
        days_st.setdefault(st, set()).add(day)
    days_sorted = {st: sorted(v) for st, v in days_st.items()}

    def causal_bias(st, day, b):
        ds = [d for d in days_sorted.get(st, []) if d < day][-W:]
        v = [err_mean[(st, d, b)] for d in ds if (st, d, b) in err_mean]
        return statistics.mean(v) if v else 0.0

    fns["event forecast_F (debiased)"] = lambda r: r["F"] - causal_bias(r["station"], r["day"], band(r["hour"]))
    fns["max(Mh, F) (debiased)"] = lambda r: max(r["Mh"], r["F"] - causal_bias(r["station"], r["day"], band(r["hour"])))

    print(f"\nPanel B  real venue ladders: rows={len(pb)} live={len(live)} "
          f"city-days={len({(r['station'], r['day']) for r in pb})}")
    for name, fn in fns.items():
        a, n = bscore(fn, live)
        print(f"  {name:<28} live bracket direction {a:6.2f}%  n={n}")
    print("  by sample-hour band (live rows, debiased forecast):")
    for nm, a0, b0 in (("00-08", 0, 8), ("08-12", 8, 12), ("12-16", 12, 16), ("16-24", 16, 24)):
        s = [r for r in live if a0 <= r["hour"] < b0]
        if not s:
            continue
        p_, n_ = bscore(fns["persist(Mh)"], s)
        f_, _ = bscore(fns["max(Mh, F) (debiased)"], s)
        print(f"    {nm:<6} n={n_:5d} persist {p_:6.2f}%  max(Mh,F_deb) {f_:6.2f}%  d {f_-p_:+.2f}pp")
    print("  recorded mean(F - A) degF by station:",
          {st: round(statistics.mean([r["F"] - settled[(r["station"], r["day"])]
                                      for r in pb if r["station"] == st]), 2)
           for st in TZ if any(r["station"] == st for r in pb)})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--show-leaky-lead0", action="store_true")
    ap.add_argument("--cache", default=str(Path.home() / ".hermes" / "cache" / "scratch" / "rec1"))
    ap.add_argument("--start", default="2026-07-25")
    ap.add_argument("--end", default=(date.today() - __import__("datetime").timedelta(days=1)).isoformat())
    a = ap.parse_args()
    cache = Path(a.cache)
    if a.fetch or not (cache / "prev_pm_nyc.json").exists():
        fetch(cache, date.fromisoformat(a.start), date.fromisoformat(a.end))
    if a.analyze or True:
        analyze(cache, show_leaky=a.show_leaky_lead0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
