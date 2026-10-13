#!/usr/bin/env python3
"""Weather nowcast-vs-price sampler (card wx2 — measurement only, read-only, keyless).

WHAT IT IS
----------
One hourly pass over the CURRENT NYC daily-high cycles on both venues, recording the price
primitives the FROZEN pre-registration needs (drafts/weather-nowcast-prereg-20261012.md):

  data/weather-nowcast-samples.jsonl   one row per bracket per cycle per venue per run
                                       plus one `context` row per cycle (obs state + ensemble)
                                       plus one `coverage` row per run

Nothing here trades, sizes, or writes anywhere but that JSONL. No keys are used (Kalshi market data
and Polymarket Gamma/CLOB are public). Silent on success — stdout is an observability channel, not a
log (the wrapper's watchdog contract).

PRICE PRIMITIVES (do not change these semantics — a change voids the accumulated sample)
--------------------------------------------------------------------------------------
Binary mirror:  yes_ask = 1 - no_bid  and  no_ask = 1 - yes_bid.
  * Kalshi's orderbook publishes BID ladders only: `yes_dollars` = bids for YES, `no_dollars` = bids
    for NO. So yes_bid = max(yes ladder), yes_ask = 1 - max(no ladder), no_bid = max(no ladder),
    no_ask = 1 - max(yes ladder). Sizes come from the level used.
  * Polymarket's CLOB book is per-token: the YES token book gives yes_bid/yes_ask directly, and the
    NO token book gives no_bid/no_ask. `gamma.markets[].outcomes` and `.clobTokenIds` are PARALLEL
    arrays (verified 2026-10-12), so token[i] is outcome[i].
  * Deadness: a bracket with `bracket_high < max_so_far_F` is dead under the pinned oracle product
    (the daily maximum is monotone). max_so_far_F is computed from the SAME product the venues settle
    on — routine hourly METAR @ KLGA (IEM ASOS report_type=3) — never from 5-minute or daily data,
    because those read 2-3 F off and would mark live brackets dead.

Python 3.9 compatible.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "weather-nowcast-samples.jsonl"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
IEM = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
NWS = "https://api.weather.gov"
ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "copybot-weather-nowcast/1.0 (read-only measurement)"}
SERIES = "KXHIGHNY"
LGA = "KLGA"
# pinned laws (pre-registration); recorded on every row so a later re-read cannot mis-price
KALSHI_TAKER = "0.07*P*(1-P)"
KALSHI_MAKER = "0"


def get(url: str, tries: int = 3) -> bytes:
    last = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45).read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.0 * (i + 1))
    raise last  # type: ignore[misc]


def jget(url: str):
    return json.loads(get(url))


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- physical state
def hourly_state(station: str, cycle_day: str):
    """Daily MAX so far from routine hourly METAR at `station` — the pinned oracle product.
    Station matters: Polymarket settles on KLGA, Kalshi on CLINYC (Central Park). Measuring one
    venue's deadness on the other's series flags live brackets dead (observed 2026-10-12:
    KXHIGHNY-26OCT12 B69.5 bid 0.99 while the LGA series read max-so-far 71)."""
    y, m, d = (int(v) for v in cycle_day.split("-"))
    url = (f"{IEM}?station={station}&data=tmpf&year1={y}&month1={m}&day1={d}"
           f"&year2={y}&month2={m}&day2={d}&tz=America%2FNew_York&format=onlycomma&latlon=no"
           f"&missing=M&trace=T&direct=no&report_type=3")
    txt = get(url).decode("utf-8", "replace")
    vals = []
    for row in csv.DictReader(io.StringIO(txt)):
        v = (row.get("tmpf") or "").strip()
        if v and (v[0].isdigit() or v[0] == "-"):
            vals.append((row["valid"], float(v)))
    if not vals:
        return None
    vals.sort()
    return {"station": station, "max_so_far_F": max(v for _, v in vals), "obs_n": len(vals),
            "obs_first": vals[0][0], "obs_last": vals[-1][0], "obs_last_F": vals[-1][1]}


def nws_latest_context():
    """Recent KLGA observations (context only — NOT the deadness basis)."""
    try:
        f = jget(f"{NWS}/stations/{LGA}/observations?limit=6")["features"]
    except Exception:
        return []
    out = []
    for x in f:
        p = x.get("properties", {})
        t = (p.get("temperature") or {}).get("value")
        out.append({"time": p.get("timestamp"), "F": None if t is None else round(t * 9 / 5 + 32, 1)})
    return out


def ensemble_for(cycle_day: str):
    """31-member GFS ensemble daily max, per member — the ensemble-implied distribution."""
    url = ("https://ensemble-api.open-meteo.com/v1/ensemble?latitude=40.7769&longitude=-73.8740"
           "&daily=temperature_2m_max&temperature_unit=fahrenheit&timezone=America%2FNew_York"
           "&forecast_days=3&models=gfs_seamless")
    try:
        d = jget(url)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}
    try:
        idx = d["daily"]["time"].index(cycle_day)
    except (KeyError, ValueError):
        return {"error": "cycle_day not in ensemble horizon"}
    keys = [k for k in d["daily"] if k.startswith("temperature_2m_max")]
    members = [d["daily"][k][idx] for k in keys]
    members = [m for m in members if m is not None]
    return {"members": members, "n": len(members),
            "mean": round(sum(members) / len(members), 2) if members else None}


def forecast_for(cycle_day: str):
    try:
        d = jget("https://api.open-meteo.com/v1/forecast?latitude=40.7769&longitude=-73.8740"
                 "&daily=temperature_2m_max&temperature_unit=fahrenheit&timezone=America%2FNew_York"
                 "&forecast_days=3")
        return d["daily"]["temperature_2m_max"][d["daily"]["time"].index(cycle_day)]
    except Exception:
        return None


# ---------------------------------------------------------------- venue books
def kalshi_cycles() -> list:
    mk = jget(f"{KALSHI}/markets?series_ticker={SERIES}&status=open&limit=200")["markets"]
    groups: dict = {}
    for m in mk:
        groups.setdefault(m["event_ticker"], []).append(m)
    return [{"event_ticker": et, "markets": ms} for et, ms in sorted(groups.items())]


_MON = {"JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
        "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"}


def kalshi_cycle_day(event_ticker: str) -> str:
    """KXHIGHNY-26OCT13 -> 2026-10-13 (the day whose daily high settles the cycle)."""
    s = event_ticker.split("-")[-1]
    return f"20{s[0:2]}-{_MON[s[2:5]]}-{s[5:7]}"


def kalshi_bracket(m: dict):
    st, f, c = m.get("strike_type"), m.get("floor_strike"), m.get("cap_strike")
    f = None if f is None else int(f)
    c = None if c is None else int(c)
    if st == "greater":
        return (None if f is None else f + 1, None)
    if st == "less":
        return (None, None if c is None else c - 1)
    return (f, c)


def kalshi_book(ticker: str):
    """BID ladders only; derive the mirror side. Returns best (yes_bid, yes_ask, no_bid, no_ask)."""
    ob = jget(f"{KALSHI}/markets/{ticker}/orderbook?depth=10").get("orderbook_fp", {})
    yes: list = []
    for p, s in (ob.get("yes_dollars") or []):
        fp, fs = fnum(p), fnum(s)
        if fp is not None:
            yes.append((fp, fs))
    no: list = []
    for p, s in (ob.get("no_dollars") or []):
        fp, fs = fnum(p), fnum(s)
        if fp is not None:
            no.append((fp, fs))
    by = max(yes) if yes else None            # best bid for YES  -> mirror gives no_ask
    bn = max(no) if no else None              # best bid for NO   -> mirror gives yes_ask
    return {
        "yes_bid": by[0] if by else None, "size_yes_bid": by[1] if by else None,
        "no_bid": bn[0] if bn else None, "size_no_bid": bn[1] if bn else None,
        "yes_ask": round(1 - bn[0], 4) if bn else None, "size_yes_ask": bn[1] if bn else None,
        "no_ask": round(1 - by[0], 4) if by else None, "size_no_ask": by[1] if by else None,
        "levels": {"yes_bids": sorted(yes, reverse=True)[:10], "no_bids": sorted(no, reverse=True)[:10]},
    }


def pm_event_for(cycle_day: str):
    y, m, d = (int(v) for v in cycle_day.split("-"))
    months = ["january", "february", "march", "april", "may", "june",
              "july", "august", "september", "october", "november", "december"]
    slug = f"highest-temperature-in-nyc-on-{months[m-1]}-{d}-{y}"
    try:
        d0 = jget(f"{GAMMA}/events?slug={slug}")
    except Exception:
        return None
    if not d0:
        return None
    e = d0[0]
    if (e.get("endDate") or "")[:4] != str(y):      # slug/year trap guard
        return None
    return e


def pm_bracket(label: str):
    if not label:
        return (None, None)
    s = label.replace("°F", "").replace("°", "").replace("or below", "").replace("or above", "").strip()
    if "-" in s:
        a, b = s.split("-")[:2]
        try:
            return (int(a), int(b))
        except ValueError:
            return (None, None)
    try:
        v = int(s.split()[0])
    except (ValueError, IndexError):
        return (None, None)
    if "below" in label:
        return (None, v)
    if "above" in label:
        return (v, None)
    return (v, v)


def best_levels(book: dict, side: str):
    rows = book.get(side) or []
    out = []
    for r in rows:
        p, s = fnum(r.get("price")), fnum(r.get("size"))
        if p is not None:
            out.append((p, s))
    return out


def pm_books(market: dict):
    outcomes = json.loads(market.get("outcomes") or "[]")
    tokens = json.loads(market.get("clobTokenIds") or "[]")
    fees = {k: market.get(k) for k in ("feeType", "feeSchedule", "feesEnabled")}
    res = {"fees": fees, "outcomes": outcomes, "token_index_for_yes": None}
    try:
        i_yes = outcomes.index("Yes")
    except ValueError:
        i_yes = 0
    res["token_index_for_yes"] = i_yes
    for i, tok in enumerate(tokens):
        try:
            bk = jget(f"{CLOB}/book?token_id={tok}")
        except Exception as exc:  # noqa: BLE001
            res[f"token{i}_error"] = str(exc)[:100]
            continue
        bids = sorted(best_levels(bk, "bids"), reverse=True)
        asks = sorted(best_levels(bk, "asks"))
        res[f"token{i}"] = {
            "best_bid": bids[0] if bids else None, "best_ask": asks[0] if asks else None,
            "min_order_size": bk.get("min_order_size"), "tick_size": bk.get("tick_size"),
        }
    # map outcome index -> primitives
    yes = res.get(f"token{i_yes}") or {}
    no = res.get(f"token{1 - i_yes}") or {}
    res["yes_bid"] = (yes.get("best_bid") or [None])[0]
    res["size_yes_bid"] = (yes.get("best_bid") or [None, None])[1]
    res["yes_ask"] = (yes.get("best_ask") or [None])[0]
    res["size_yes_ask"] = (yes.get("best_ask") or [None, None])[1]
    res["no_bid"] = (no.get("best_bid") or [None])[0]
    res["size_no_bid"] = (no.get("best_bid") or [None, None])[1]
    res["no_ask"] = (no.get("best_ask") or [None])[0]
    res["size_no_ask"] = (no.get("best_ask") or [None, None])[1]
    return res


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--now", default=None, help="ISO timestamp override (testing)")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    now = datetime.fromisoformat(a.now).astimezone(ET) if a.now else datetime.now(ET)
    ts = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    et_hour = round(now.hour + now.minute / 60.0, 3)
    today = now.strftime("%Y-%m-%d")
    cycles = [today, (now + timedelta(days=1)).strftime("%Y-%m-%d")]

    rows, coverage = [], {"kind": "coverage", "ts": ts, "et_hour": et_hour,
                          "kalshi_cycles": 0, "kalshi_brackets": 0, "pm_cycles": 0, "pm_brackets": 0,
                          "errors": [], "dropped": []}

    # ---- context per cycle (physical state per STATION + ensemble)
    ctx = {}
    for day in cycles:
        if day == today:
            obs = {"klga": hourly_state("LGA", day), "kalshi_cp": hourly_state("NYC", day)}
        else:
            obs = {"klga": None, "kalshi_cp": None}
        ens = ensemble_for(day)
        ctx[day] = {"kind": "context", "ts": ts, "cycle_day": day, "et_hour": et_hour,
                    "obs": obs, "ensemble": ens, "forecast_F": forecast_for(day),
                    "nws_recent": nws_latest_context(),
                    "basis": {"polymarket": "hourly METAR @ KLGA (IEM ASOS report_type=3)",
                              "kalshi": "hourly METAR @ Central Park/NYC (IEM ASOS report_type=3),"
                                        " proxy for the CLINYC/TWC product"}}
        rows.append(ctx[day])

    def dead_basis(venue: str):
        day = today
        key = "klga" if venue == "polymarket" else "kalshi_cp"
        st = ((ctx.get(day) or {}).get("obs") or {}).get(key) or {}
        return st.get("max_so_far_F"), key

    def is_dead(venue: str, bracket_high, day):
        """Dead = bracket_high < max-so-far measured on THAT VENUE'S OWN settlement station."""
        if day != today or bracket_high is None:
            return None
        m, _key = dead_basis(venue)
        return None if m is None else bracket_high < m

    # ---- Kalshi
    try:
        for c in kalshi_cycles():
            et = c["event_ticker"]
            day = kalshi_cycle_day(et)
            if day not in cycles:
                continue
            coverage["kalshi_cycles"] += 1
            for m in c["markets"]:
                lo, hi = kalshi_bracket(m)
                try:
                    bk = kalshi_book(m["ticker"])
                except Exception as exc:  # noqa: BLE001
                    coverage["errors"].append(f"kalshi book {m['ticker']}: {str(exc)[:80]}")
                    continue
                row = {"kind": "bracket", "venue": "kalshi", "ts": ts, "cycle_day": day, "et_hour": et_hour,
                       "instrument": m["ticker"], "event_ticker": et, "label": m.get("yes_sub_title"),
                       "bracket_low": lo, "bracket_high": hi, "strike_type": m.get("strike_type"),
                       "dead": is_dead("kalshi", hi, day), "dead_basis_station": "CentralPark/NYC",
                       "yes_bid": bk["yes_bid"], "yes_ask": bk["yes_ask"],
                       "no_bid": bk["no_bid"], "no_ask": bk["no_ask"],
                       "size_yes_bid": bk["size_yes_bid"], "size_no_bid": bk["size_no_bid"],
                       "fee": {"taker": KALSHI_TAKER, "maker": KALSHI_MAKER}} | bk["levels"]
                rows.append(row)
                coverage["kalshi_brackets"] += 1
    except Exception as exc:  # noqa: BLE001
        coverage["errors"].append(f"kalshi pass: {str(exc)[:140]}")

    # ---- Polymarket
    for day in cycles:
        try:
            e = pm_event_for(day)
        except Exception as exc:  # noqa: BLE001
            coverage["errors"].append(f"pm event {day}: {str(exc)[:100]}")
            continue
        if not e:
            continue
        coverage["pm_cycles"] += 1
        for m in e.get("markets", []):
            if m.get("closed"):
                continue
            lo, hi = pm_bracket(m.get("groupItemTitle"))
            try:
                bk = pm_books(m)
            except Exception as exc:  # noqa: BLE001
                coverage["errors"].append(f"pm book {m.get('slug')}: {str(exc)[:80]}")
                continue
            rows.append({"kind": "bracket", "venue": "polymarket", "ts": ts, "cycle_day": day,
                         "et_hour": et_hour, "instrument": m.get("slug"), "event_slug": e.get("slug"),
                         "label": m.get("groupItemTitle"), "bracket_low": lo, "bracket_high": hi,
                         "strike_type": "range", "dead": is_dead("polymarket", hi, day),
                         "dead_basis_station": "KLGA",
                         "yes_bid": bk["yes_bid"], "yes_ask": bk["yes_ask"],
                         "no_bid": bk["no_bid"], "no_ask": bk["no_ask"],
                         "size_yes_bid": bk["size_yes_bid"], "size_no_bid": bk["size_no_bid"],
                         "token_index_for_yes": bk["token_index_for_yes"], "fee": bk["fees"],
                         "accepting_orders": m.get("acceptingOrders")})
            coverage["pm_brackets"] += 1

    if coverage["kalshi_brackets"] == 0 and coverage["pm_brackets"] == 0:
        print(f"🟠 weather-nowcast: no brackets captured this tick ({ts}) — errors={coverage['errors'][:2]}")
        return 0

    rows.append(coverage)
    path = Path(a.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    if a.verbose:
        dead = [r for r in rows if r.get("kind") == "bracket" and r.get("dead")]
        print(f"{ts} rows={len(rows)} kalshi={coverage['kalshi_brackets']} pm={coverage['pm_brackets']} "
              f"dead={len(dead)} errors={len(coverage['errors'])}")
        for r in dead[:6]:
            print(f"   DEAD {r['venue']:<10} {str(r['label']):<14} last={r['bracket_low']}-{r['bracket_high']} "
                  f"yb={r['yes_bid']} ya={r['yes_ask']} nb={r['no_bid']} na={r['no_ask']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"🔴 weather-nowcast sampler crashed: {type(exc).__name__}: {exc}")
        sys.exit(0)   # never fail the cron tick loudly; the wrapper's freshness check reports it
