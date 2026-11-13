#!/usr/bin/env python3
"""REC 1 re-read (2026-11-12) — Open-Meteo previous-runs as a wx2 feature, extended window.

Card: roadmap `ml-feed-openmeteo-previous-runs`. Proposal: drafts/ml-feed-openmeteo-previous-runs-20261112.md.
Prior proposal: drafts/ml-feed-openmeteo-previous-runs-20261029.md (94 settled days, REFUTED).
Fetcher it depends on: scripts/ml-openmeteo-previous-runs-measure.py (unchanged; run it with --fetch
and a fresh --cache first — this script reads that cache).

WHAT THIS ADDS over the 10-29 read (nothing is re-derived, only extended):
  T1  the prior draft's Option B gate, executed: NYC, sample hour <= 10:00, live brackets,
      max(Mh, F_debiased) vs persist(Mh), day-clustered bootstrap CI, day-ordered halves.
  T2  Panel B broken out per station and per hour band (was pooled only).
  T3  next-day cycle vs a CLIMATOLOGY baseline — the prior draft's stated revival condition.
  T4  next-day cycle vs the VENUE'S OWN LADDER — the comparator that decides a trading lane.
  T5  same-day morning vs the venue's own ladder.

Read-only. Writes nothing but stdout. Python 3.9+.

  python3 scripts/ml-openmeteo-previous-runs-measure.py --fetch \
      --cache ~/.hermes/cache/scratch/rec1-20261112 --start 2026-07-25 --end 2026-11-11
  python3 scripts/ml-openmeteo-previous-runs-reread.py --cache ~/.hermes/cache/scratch/rec1-20261112
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import statistics
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
W = 14                      # causal window, days
ET = ZoneInfo("America/New_York")

_spec = importlib.util.spec_from_file_location(
    "rec1", REPO / "scripts" / "ml-openmeteo-previous-runs-measure.py")
if _spec is None or _spec.loader is None:
    raise RuntimeError("cannot load scripts/ml-openmeteo-previous-runs-measure.py")
rec1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rec1)

VMAP = {"polymarket": {"nyc": "pm_nyc", "dfw": "pm_dfw"},
        "kalshi": {"nyc": "kalshi_nyc", "dfw": "kalshi_dfw"}}
SAMPLERS = (("weather-nowcast-samples.jsonl", "nyc"), ("weather-nowcast-samples-dfw.jsonl", "dfw"))


# ---------------------------------------------------------------- shared
def settled(cache: Path):
    out = {}
    for key in rec1.TZ:
        obs_by_day, _ = rec1.load(cache, key)
        for day, o in obs_by_day.items():
            if len(o) >= 20 and max(o) >= 21:      # wx2 settle filter
                out[(key, day)] = max(o.values())
    return out


def sampler_rows(SETTLED):
    """Every priced bracket row with a settled label, joined to its own sampler run's context."""
    rows = []
    for fn, city in SAMPLERS:
        ctx = {}
        for line in (REPO / "data" / fn).open():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("kind") == "context":
                ctx[(r.get("cycle_day"), r.get("ts"))] = r
                continue
            if r.get("kind") != "bracket" or r.get("et_hour") is None:
                continue
            st = VMAP.get(r.get("venue"), {}).get(city)
            day = r.get("cycle_day")
            if st is None or (st, day) not in SETTLED:
                continue
            c = ctx.get((day, r.get("ts")))
            if not c:
                continue
            o = (c.get("obs") or {}).get(rec1.OBSKEY[st]) or {}
            Mh, F = o.get("max_so_far_F"), c.get("forecast_F")
            if F is None:
                continue
            same_day = datetime.fromisoformat(r["ts"]).astimezone(ET).date().isoformat() == day
            rows.append({"st": st, "venue": r.get("venue"), "day": day, "ts": r["ts"],
                         "hour": r.get("et_hour"), "lo": r.get("bracket_low"), "hi": r.get("bracket_high"),
                         "Mh": Mh, "F": F, "A": SETTLED[(st, day)], "same_day": same_day,
                         "band": 0 if r["et_hour"] < 8 else (1 if r["et_hour"] < 12
                                                             else (2 if r["et_hour"] < 16 else 3)),
                         "yes_bid": r.get("yes_bid"), "yes_ask": r.get("yes_ask")})
    return rows


def debias_map(rows):
    """Causal mean(F - A) per station x day x band, and a trailing-window lookup."""
    err = {}
    for r in rows:
        if r["same_day"]:
            err.setdefault((r["st"], r["day"], r["band"]), []).append(r["F"] - r["A"])
    mean = {k: statistics.mean(v) for k, v in err.items()}
    days = {}
    for (st, d, _b) in mean:
        days.setdefault(st, set()).add(d)
    days = {st: sorted(v) for st, v in days.items()}

    def bias(st, day, band):
        ds = [d for d in days.get(st, []) if d < day][-W:]
        v = [mean[(st, d, band)] for d in ds if (st, d, band) in mean]
        return statistics.mean(v) if v else 0.0
    return bias


def boot_ci(per_day, iters=4000):
    random.seed(20261112)
    n = len(per_day)
    m = sorted(statistics.mean([per_day[random.randrange(n)] for _ in range(n)]) for _ in range(iters))
    return m[int(0.025 * iters)], m[int(0.975 * iters)]


def bracket_dir_ok(r, pred):
    py = (pred >= r["lo"] if r["lo"] is not None else True) and (pred <= r["hi"] if r["hi"] is not None else True)
    ay = (r["A"] >= r["lo"] if r["lo"] is not None else True) and (r["A"] <= r["hi"] if r["hi"] is not None else True)
    return int(py) == int(ay)


def live(r):
    """Bracket still undecided at sample time by monotonicity (same rule as the wx2 prereg)."""
    if r["Mh"] is None:
        return False
    if r["hi"] is not None and r["Mh"] > r["hi"]:
        return False
    if r["lo"] is not None and r["hi"] is None and r["Mh"] >= r["lo"]:
        return False
    return True


# ---------------------------------------------------------------- tests
def t1_option_b(rows, bias):
    print("\nT1 — prior draft's Option B gate: NYC, sample hour <= 10:00, live brackets")
    sel = [r for r in rows if r["same_day"] and r["st"] in ("pm_nyc", "kalshi_nyc")
           and r["hour"] <= 10 and live(r)]
    days = sorted({r["day"] for r in sel})
    print(f"  rows={len(sel)}  settled city-days={len({(r['st'], r['day']) for r in sel})}  "
          f"days {days[0]}..{days[-1]}")
    cut = days[len(days) // 2]
    for st in ("pm_nyc", "kalshi_nyc"):
        s = [r for r in sel if r["st"] == st]
        pd, fd = {}, {}
        for r in s:
            Fd = r["F"] - bias(r["st"], r["day"], r["band"])
            pd.setdefault(r["day"], []).append(int(bracket_dir_ok(r, r["Mh"])))
            fd.setdefault(r["day"], []).append(int(bracket_dir_ok(r, max(r["Mh"], Fd))))
        dd = sorted(pd)
        per = [statistics.mean(fd[d]) - statistics.mean(pd[d]) for d in dd]
        p = 100 * statistics.mean([v for d in dd for v in pd[d]])
        f = 100 * statistics.mean([v for d in dd for v in fd[d]])
        lo, hi = boot_ci(per) if len(per) > 2 else (float("nan"), float("nan"))
        h1 = 100 * (statistics.mean([v for d in dd if d < cut for v in fd[d]]) -
                    statistics.mean([v for d in dd if d < cut for v in pd[d]]))
        h2 = 100 * (statistics.mean([v for d in dd if d >= cut for v in fd[d]]) -
                    statistics.mean([v for d in dd if d >= cut for v in pd[d]]))
        print(f"    {st:<11} days={len(dd):<3} n={len(s):<5} persist {p:6.2f}%  forecast {f:6.2f}%  "
              f"delta {f-p:+6.2f}pp  day-clustered 95%CI [{100*lo:+.2f},{100*hi:+.2f}]  "
              f"H1 {h1:+.2f}  H2 {h2:+.2f}")


def t2_panel_b_by_station(rows, bias):
    print("\nT2 — Panel B by station and hour band (same-day rows, live brackets)")
    print(f"    {'station':<11}{'scope':<8}{'n':>7}{'days':>6}{'persist':>9}{'forecast':>10}{'delta':>8}   95%CI")
    for st in list(rec1.TZ) + ["ALL"]:
        for name, cond in (("all", lambda r: True), ("<=10h", lambda r: r["hour"] <= 10),
                           ("16h+", lambda r: r["hour"] >= 16)):
            sel = [r for r in rows if r["same_day"] and live(r) and (st == "ALL" or r["st"] == st) and cond(r)]
            if not sel:
                continue
            pd, fd = {}, {}
            for r in sel:
                Fd = r["F"] - bias(r["st"], r["day"], r["band"])
                pd.setdefault(r["day"], []).append(int(bracket_dir_ok(r, r["Mh"])))
                fd.setdefault(r["day"], []).append(int(bracket_dir_ok(r, max(r["Mh"], Fd))))
            dd = sorted(pd)
            per = [statistics.mean(fd[d]) - statistics.mean(pd[d]) for d in dd]
            p = 100 * statistics.mean([v for d in dd for v in pd[d]])
            f = 100 * statistics.mean([v for d in dd for v in fd[d]])
            lo, hi = boot_ci(per) if len(per) > 2 else (float("nan"), float("nan"))
            print(f"    {st:<11}{name:<8}{len(sel):>7}{len(dd):>6}{p:>8.2f}%{f:>9.2f}%{f-p:>+7.2f}pp   "
                  f"[{100*lo:+.2f},{100*hi:+.2f}]")


def next_day_vs_climatology(cache, SETTLED):
    """T3 — tomorrow's cycle: as-issued leads 1/2 vs a trailing-climatology rule (Mh does not exist)."""
    print("\nT3 — next-day cycle vs CLIMATOLOGY (the prior draft's revival condition)")
    grid = {}
    for st in rec1.TZ:
        obs_by_day, fc = rec1.load(cache, st)
        days = sorted(d for d, o in obs_by_day.items() if len(o) >= 20 and max(o) >= 21)
        A = {d: max(obs_by_day[d].values()) for d in days}
        for i, day in enumerate(days):
            hist = days[max(0, i - W):i]
            if len(hist) < 7:
                continue
            f = {}
            for lead in (1, 2):
                per = {}
                for m in rec1.MODELS:
                    vals = [v for _h, v in fc.get(f"temperature_2m_previous_day{lead}_{m}", {}).get(day, {}).items()]
                    if vals:
                        per[m] = max(vals)
                if len(per) == len(rec1.MODELS):
                    f[lead] = per
            grid[(st, day)] = {"A": A[day], "clim": statistics.median([A[d] for d in hist]),
                               "f": f, "hist": hist}

    def bias(st, day, lead):
        hist = grid[(st, day)]["hist"][-W:]
        e = [grid[(st, d)]["A"] - statistics.median(grid[(st, d)]["f"][lead].values())
             for d in hist if (st, d) in grid and lead in grid[(st, d)]["f"]]
        return statistics.mean(e) if e else 0.0

    def acc(pred, sel):
        hit = tot = 0
        for (st, day), g in sel:
            p = pred(st, day, g)
            if p is None:
                continue
            for thr in range(round(g["clim"]) - 6, round(g["clim"]) + 7):    # grid anchored on climate
                tot += 1
                hit += (p >= thr) == (g["A"] >= thr)
        return (100.0 * hit / tot, tot) if tot else (float("nan"), 0)

    rows = sorted(grid.items())
    days = sorted({d for (_s, d) in grid})
    cut = days[len(days) // 2]
    halves = {"H1": [r for r in rows if r[0][1] < cut], "H2": [r for r in rows if r[0][1] >= cut]}
    nwp = lambda lead: (lambda st, day, g: statistics.median(g["f"][lead].values()) + bias(st, day, lead)
                        if lead in g["f"] else None)
    print(f"    station-days={len(grid)} days={len(days)} {days[0]}..{days[-1]} split at {cut}")
    print(f"    {'scope':<12}{'n':>7}{'clim':>8}{'nwp1':>8}{'d1':>7}{'nwp2':>8}{'d2':>7}")
    for name, sel in [("ALL", rows)] + list(halves.items()):
        c, n = acc(lambda st, day, g: g["clim"], sel)
        a1, _ = acc(nwp(1), sel)
        a2, _ = acc(nwp(2), sel)
        print(f"    {name:<12}{n:>7}{c:>8.2f}{a1:>8.2f}{a1-c:>+7.2f}{a2:>8.2f}{a2-c:>+7.2f}")
    for st in rec1.TZ:
        sel = [r for r in rows if r[0][0] == st]
        if not sel:
            continue
        c, n = acc(lambda s2, d2, g: g["clim"], sel)
        a1, _ = acc(nwp(1), sel)
        print(f"      {st:<11} n={n:<6} clim {c:6.2f}  nwp1 {a1:6.2f} ({a1-c:+.2f})")
    mae = lambda lead: statistics.mean(abs(g["A"] - statistics.median(g["f"][lead].values()))
                                       for _k, g in rows if lead in g["f"])
    print(f"    substrate MAE on the daily max: lead1 {mae(1):.2f} F  lead2 {mae(2):.2f} F  "
          f"climatology {statistics.mean(abs(g['A']-g['clim']) for _k, g in rows):.2f} F")


def _modal(r):
    b, a = r["yes_bid"], r["yes_ask"]
    if b is not None and a is not None:
        return (b + a) / 2
    return b if b is not None else a


def ladder_test(rows, bias, same_day, label, contested=False):
    """T4/T5 — the venue's own ladder vs the forecast, per bracket (symmetric metric).

    Every priced bracket row is scored as a YES/NO call:
      mkt      YES iff the bracket's mid > 0.5
      fc       YES iff the causally-debiased forecast falls inside the bracket
      maxMhFc  same, floored at max-so-far (same-day only; no anchor exists next-day)
      persist  YES iff max-so-far falls inside the bracket (same-day only)

    contested=True keeps only brackets priced 0.20-0.80, where the venue is genuinely unsure
    and a direction call carries information (outside that band both sides agree trivially).
    """
    sel = []
    for r in rows:
        if r["same_day"] != same_day:
            continue
        if same_day and (r["hour"] > 10 or not live(r)):
            continue
        mv0 = _modal(r)
        if mv0 is None:
            continue
        if contested and not (0.20 <= mv0 <= 0.80):
            continue
        sel.append(r)
    print(f"\n{label}: {len(sel)} priced bracket rows, "
          f"{len({(r['st'], r['day']) for r in sel})} station-days, {len({r['day'] for r in sel})} distinct days")
    print(f"    {'scope':<12}{'rows':>7}{'days':>6}{'market':>9}{'fc':>8}"
          f"{'maxMhFc':>9}{'persist':>9}{'d(maxMhFc-mkt)':>16}")

    def ins(p, r):
        return (p >= r["lo"] if r["lo"] is not None else True) and \
               (p <= r["hi"] if r["hi"] is not None else True)

    def yes(r):
        return (r["A"] >= r["lo"] if r["lo"] is not None else True) and \
               (r["A"] <= r["hi"] if r["hi"] is not None else True)

    for st in (None,) + tuple(rec1.TZ):
        s = [r for r in sel if st is None or r["st"] == st]
        if not s:
            continue
        acc = {k: [] for k in ("mkt", "fc", "maxMhFc", "persist")}
        per_day = {}
        for r in s:
            Fd = r["F"] - bias(r["st"], r["day"], r["band"])
            Mh = r["Mh"] if r["Mh"] is not None else 0.0
            mv = _modal(r) or 0.0
            calls = {"mkt": 1 if mv > 0.5 else 0,
                     "fc": int(ins(Fd, r)),
                     "maxMhFc": int(ins(max(Mh, Fd), r)) if same_day else None,
                     "persist": int(ins(Mh, r)) if same_day else None}
            t = int(yes(r))
            for k, v in calls.items():
                if v is None:
                    continue
                hit = int(v == t)
                acc[k].append(hit)
                per_day.setdefault((r["day"], k), []).append(hit)
        days = sorted({d for (d, _k) in per_day})
        dk = "maxMhFc" if same_day else "fc"
        dd = []
        for d in days:
            if (d, dk) in per_day and (d, "mkt") in per_day:
                dd.append(statistics.mean(per_day[(d, dk)]) - statistics.mean(per_day[(d, "mkt")]))
        lo, hi = boot_ci(dd) if len(dd) > 2 else (float("nan"), float("nan"))
        pct = {k: (100 * statistics.mean(v) if v else float("nan")) for k, v in acc.items()}
        dlt = pct[dk] - pct["mkt"]
        print(f"    {st or 'ALL':<12}{len(s):>7}{len(days):>6}{pct['mkt']:>8.2f}%{pct['fc']:>7.2f}%"
              f"{pct['maxMhFc']:>8.2f}%{pct['persist']:>8.2f}%{dlt:>+15.2f}pp  CI[{100*lo:+.1f},{100*hi:+.1f}]")
    return sel


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(Path.home() / ".hermes" / "cache" / "scratch" / "rec1-20261112"))
    a = ap.parse_args()
    cache = Path(a.cache)
    SETTLED = settled(cache)
    print(f"settled station-days={len(SETTLED)} days={len({d for (_s, d) in SETTLED})} "
          f"{min(d for (_s, d) in SETTLED)}..{max(d for (_s, d) in SETTLED)}")
    rows = sampler_rows(SETTLED)
    bias = debias_map(rows)
    print(f"sampler bracket rows joined={len(rows)} (same-day {sum(r['same_day'] for r in rows)})")
    t1_option_b(rows, bias)
    t2_panel_b_by_station(rows, bias)
    next_day_vs_climatology(cache, SETTLED)
    ladder_test(rows, bias, same_day=False, label="T4 — next-day cycle vs the VENUE'S OWN LADDER")
    ladder_test(rows, bias, same_day=False, contested=True,
                label="T4c — next-day cycle, CONTESTED brackets only (mid 0.20-0.80)")
    ladder_test(rows, bias, same_day=True, label="T5 — same-day morning (hour <= 10:00) vs the ladder")
    ladder_test(rows, bias, same_day=True, contested=True,
                label="T5c — same-day morning, CONTESTED brackets only (mid 0.20-0.80)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
