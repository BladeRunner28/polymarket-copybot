#!/usr/bin/env python3
"""Kalshi x Polymarket cross-venue read (complementary-Kalshi workstream, option C).

TARGETS the two families where the SAME underlying is listed on both venues:
  * NYC daily-high temperature  — Kalshi KXHIGHNY vs Polymarket
    `highest-temperature-in-nyc-on-<month>-<day>-<year>`
  * WTI crude oil — Kalshi KXWTI vs Polymarket's oil markets (LISTED for
    context only: the propositions do not line up, so no arb claim is made)

WHAT IT ANSWERS
---------------
1. Do the two venues' brackets even align? (They are offset by one degree by
   construction: Kalshi bins {69,70}, PM bins {70,71}, so most "same market"
   comparisons are FALSE MATCHES — the script states the alignment verdict per
   bucket mechanically rather than assuming it.)
2. Where they DO align exactly (the one-sided tails), what is the executable
   gap after each venue's own fee?
3. Interpolated full-ladder comparison at a coarse grid, CLEARLY labelled
   INTERPOLATED (uniform-within-bucket allocation), because that is the only way
   to compare offset ladders — never quote the interpolated column as a quote.

Pre-registered bar for any follow-up: the interpolated gap must exceed the sum
of both venues' spreads + fees at the same grid point before anything is called
a cross-venue edge; the exact-alignment rows are the only ones that can ever
support an execution claim.

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
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTDIR = ROOT / "data"
API = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
UA = {"User-Agent": "copybot-kalshi-crossvenue/1.0"}

MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
CITIES = {"nyc": "KXHIGHNY", "chicago": "KXHIGHCHI", "denver": "KXHIGHDEN", "miami": "KXHIGHMIA"}


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
                time.sleep(3.0 * (attempt + 1))
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


def kalshi_region(ticker, title):
    """Map a KXHIGHNY ticker/title to a temperature region (lo, hi) in deg F, or a half-line."""
    tail = ticker.split("-")[-1] if ticker else ""
    if tail.startswith("T"):
        # T69 = 'below 69'; T76 = 'above 76'
        val = int(float(tail[1:]))
        if "below" in (title or "").lower() or "<" in (title or ""):
            return (None, val - 1)
        if "above" in (title or "").lower() or ">" in (title or ""):
            return (val + 1, None)
        return (None, None)
    if tail.startswith("B"):
        centre = float(tail[1:])
        lo = int(centre - 0.5)
        return (lo, lo + 1)
    return (None, None)


def pm_region(label):
    """Map a Polymarket groupItemTitle ('70-71°F', '61°F or below', '80°F or higher')."""
    text = (label or "").replace("\u00b0F", "").replace("\u00b0", "").strip().lower()
    if "or below" in text:
        return (None, int(float(text.split("f")[0].split()[0])) if text.split() else None)
    if "or higher" in text:
        return (int(float(text.split("f")[0].split()[0])) if text.split() else None, None)
    if "-" in text:
        parts = text.split("-")
        try:
            return (int(parts[0]), int(parts[1]))
        except ValueError:
            return (None, None)
    return (None, None)


def region_label(reg):
    lo, hi = reg
    if lo is None and hi is None:
        return "?"
    if lo is None:
        return "<=%d" % hi
    if hi is None:
        return ">=%d" % lo
    return "%d-%d" % (lo, hi)


def region_mass_below(reg, x):
    """Share of the bucket at or above grid point x, uniform-within-bucket (INTERPOLATION)."""
    lo, hi = reg
    if lo is None and hi is None:
        return None
    if lo is None:
        return 0.0 if hi < x else 1.0
    if hi is None:
        return 1.0 if lo >= x else 0.0
    n = hi - lo + 1
    if x <= lo:
        return 1.0
    if x > hi:
        return 0.0
    return (hi - x + 1) / float(n)


def load_kalshi_temp(series, date_tokens):
    d = get_json("%s/markets?series_ticker=%s&status=open&limit=200" % (API, series))
    out = []
    for m in d.get("markets") or []:
        ticker = m.get("ticker") or ""
        if date_tokens and date_tokens not in ticker:
            continue
        yb, ya = fnum(m.get("yes_bid_dollars")), fnum(m.get("yes_ask_dollars"))
        two_sided = bool(yb and ya)
        out.append(
            {
                "venue": "kalshi",
                "ticker": ticker,
                "title": (m.get("title") or "")[:100],
                "region": kalshi_region(ticker, m.get("title")),
                "bid": yb or None,
                "ask": ya or None,
                # A mid is only meaningful with BOTH sides quoted. A bucket with no bid
                # (0.00/0.01 stalls) contributes 0 to a ladder sum; calling its mid 0.01
                # inflates the exhaustiveness check.
                "mid": round((yb + ya) / 2.0, 4) if two_sided else None,
                "one_sided": not two_sided,
                "bid_size": fnum(m.get("yes_bid_size_fp")),
                "ask_size": fnum(m.get("yes_ask_size_fp")),
                "spread": round(ya - yb, 4) if two_sided else None,
                "volume_24h": fnum(m.get("volume_24h_fp")),
                "open_interest": fnum(m.get("open_interest_fp")),
            }
        )
    return out


def load_pm_temp(city_slug, date_str):
    month = MONTHS[int(date_str[5:7]) - 1]
    day = int(date_str[8:10])
    slug = "highest-temperature-in-%s-on-%s-%d-%s" % (city_slug, month, day, date_str[:4])
    d = get_json("%s/events?slug=%s" % (GAMMA, urllib.parse.quote(slug, safe="")))
    if not d:
        return slug, []
    ev = d[0]
    out = []
    for m in ev.get("markets") or []:
        prices = m.get("outcomePrices")
        try:
            prices = json.loads(prices) if isinstance(prices, str) else (prices or [])
        except Exception:
            prices = []
        yes_last = fnum(prices[0]) if prices else None
        bid, ask = m.get("bestBid"), m.get("bestAsk")
        out.append(
            {
                "venue": "polymarket",
                "ticker": m.get("slug"),
                "title": (m.get("groupItemTitle") or m.get("question") or "")[:100],
                "region": pm_region(m.get("groupItemTitle") or m.get("question")),
                "bid": fnum(bid) or None,
                "ask": fnum(ask) or None,
                "mid": round((fnum(bid) + fnum(ask)) / 2.0, 4) if (bid and ask) else yes_last,
                "last": yes_last,
                "spread": m.get("spread"),
                "liquidity": fnum(m.get("liquidity")),
                "volume": fnum(m.get("volume")),
                "fee_schedule": m.get("feeSchedule"),
                "fee_type": m.get("feeType"),
            }
        )
    return slug, out


def fee_kalshi(p, taker=True):
    if p is None:
        return None
    rate = 0.07 if taker else 0.0175
    return round(rate * p * (1.0 - p), 4)


def fee_pm(p, schedule):
    if p is None or not schedule:
        return None
    rate = fnum(schedule.get("rate"))
    return round(rate * p * (1.0 - p), 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="nyc", choices=sorted(CITIES))
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: today, local)")
    ap.add_argument("--grid", default="66,68,70,72,74,76,78", help="coarse comparison grid in deg F")
    ap.add_argument("--oil", action="store_true", help="also list the WTI/PM oil shape (no arb claim)")
    ap.add_argument("--calibration", action="store_true", help="also run the settled-market calibration read for the Kalshi series")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    series = CITIES[args.city]
    date_tokens = "%s%s%s" % (date_str[2:4], MONTHS[int(date_str[5:7]) - 1][:3].upper(), date_str[8:10])

    kalshi = load_kalshi_temp(series, date_tokens)
    pm_slug, pm = load_pm_temp(args.city, date_str)
    time.sleep(0.5)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "city": args.city,
        "date": date_str,
        "kalshi_series": series,
        "kalshi_date_token": date_tokens,
        "pm_event_slug": pm_slug,
        "kalshi_ladder": kalshi,
        "pm_ladder": pm,
    }

    print("== %s high temperature, %s" % (args.city.upper(), date_str))
    print("   kalshi series %s (%d markets) | PM event %s (%d markets)" % (series, len(kalshi), pm_slug, len(pm)))
    if not kalshi or not pm:
        print("   ⚠️ one side is empty — NOT a comparison; no gap reported")

    kalshi_sum = sum(r["mid"] for r in kalshi if r["mid"])
    pm_sum = sum(r["mid"] for r in pm if r["mid"])
    k_excl = sum(1 for r in kalshi if r.get("mid") is None)
    print(
        "   exhaustiveness check (ladder mid sum, should be ~1.00): kalshi %.3f (%d one-sided bins excluded) | PM %.3f"
        % (kalshi_sum, k_excl, pm_sum)
    )

    # ---- side-by-side regions -------------------------------------------------
    keys = sorted({r["region"] for r in kalshi + pm if r["region"] != (None, None)}, key=lambda r: (r[0] is not None, r[0] if r[0] is not None else r[1]))
    lookup = {(r["venue"], r["region"]): r for r in kalshi + pm if r["region"] != (None, None)}
    print("\n   region      | kalshi mid (bid/ask, size)        | PM mid (bid/ask)                  | alignment")
    for reg in keys:
        k = lookup.get(("kalshi", reg))
        p = lookup.get(("polymarket", reg))
        km = ("%.3f (%.2f/%.2f, %s)" % (k["mid"], k["bid"] or 0, k["ask"] or 0, ("%.0f" % k["bid_size"]))) if k and k["mid"] is not None else "-"
        pmv = ("%.3f (%.2f/%.2f)" % (p["mid"], p["bid"] or 0, p["ask"] or 0)) if p and p["mid"] is not None else "-"
        align = "SAME-BIN" if (k and p) else ("kalshi-only" if k else "PM-only")
        print("   %-11s | %-33s | %-33s | %s" % (region_label(reg), km[:33], pmv[:33], align))

    # ---- exact-alignment rows: one-sided tails only ---------------------------
    print("\n   exact-alignment (half-line) rows — the only rows that can support an execution claim:")
    exact_rows = []
    for reg in keys:
        k, p = lookup.get(("kalshi", reg)), lookup.get(("polymarket", reg))
        if not (k and p):
            continue
        lo, hi = reg
        if not (lo is None or hi is None):
            continue
        k_fee = fee_kalshi(k["mid"])
        p_fee = fee_pm(p["mid"], (pm[0].get("fee_schedule") if pm else None))
        row = {
            "region": region_label(reg),
            "kalshi_mid": k["mid"],
            "pm_mid": p["mid"],
            "gap": round((k["mid"] or 0) - (p["mid"] or 0), 4),
            "kalshi_spread": k["spread"],
            "pm_spread": p["spread"],
            "kalshi_taker_fee": k_fee,
            "pm_taker_fee": p_fee,
        }
        exact_rows.append(row)
        print(
            "     %-8s kalshi=%.3f PM=%.3f gap=%+.4f | kalshi spread=%s fee=%s ; PM spread=%s fee=%s"
            % (row["region"], k["mid"], p["mid"], row["gap"], k["spread"], k_fee, p["spread"], p_fee)
        )
    if not exact_rows:
        print("     (none: these two ladders share no half-line contract — see the grid offset below)")

    # ---- grid offset finding --------------------------------------------------
    def dominant(ladder):
        best = max(ladder, key=lambda r: r["mid"] or 0, default=None)
        return best

    kdom, pdom = dominant(kalshi), dominant(pm)
    if kdom and pdom:
        klo = kdom["region"][0]
        plo = pdom["region"][0]
        offset = None if (klo is None or plo is None) else klo - plo
        print("\n   dominant bin: kalshi %s (%.3f) vs PM %s (%.3f) → bin-grid offset %s degree(s)"
              % (region_label(kdom["region"]), kdom["mid"] or 0, region_label(pdom["region"]), pdom["mid"] or 0, offset))
        payload["dominant"] = {
            "kalshi_region": region_label(kdom["region"]),
            "kalshi_mid": kdom["mid"],
            "pm_region": region_label(pdom["region"]),
            "pm_mid": pdom["mid"],
            "grid_offset_degrees": offset,
        }

    # ---- INTERPOLATED full-ladder comparison ---------------------------------
    grid = [int(g) for g in args.grid.split(",") if g.strip()]
    pm_schedule = (pm[0].get("fee_schedule") if pm else None)
    print("\n   INTERPOLATED P(T >= x) — uniform-within-bucket, NOT a quote:")
    print("     x   | kalshi P(>=x) | PM P(>=x) | gap      | sum of both spreads+fees at x")
    interp_rows = []
    for x in grid:
        kvals = [(r["mid"] or 0) * (region_mass_below(r["region"], x) or 0) for r in kalshi if r["region"] != (None, None)]
        pvals = [(r["mid"] or 0) * (region_mass_below(r["region"], x) or 0) for r in pm if r["region"] != (None, None)]
        kp, pp = sum(kvals), sum(pvals)
        # cost at this grid point: the two venues' spreads on the buckets that straddle x
        kstraddle = next((r for r in kalshi if r["region"] != (None, None) and r["region"][0] is not None and r["region"][1] is not None and r["region"][0] < x <= r["region"][1]), None)
        pstraddle = next((r for r in pm if r["region"] != (None, None) and r["region"][0] is not None and r["region"][1] is not None and r["region"][0] < x <= r["region"][1]), None)
        cost = None
        if kstraddle and pstraddle:
            cost = round(
                (kstraddle["spread"] or 0) + (pstraddle["spread"] or 0)
                + (fee_kalshi(kp) or 0) + (fee_pm(pp, pm_schedule) or 0),
                4,
            )
        interp_rows.append({"x": x, "kalshi_p_ge": round(kp, 4), "pm_p_ge": round(pp, 4), "gap": round(kp - pp, 4), "cost_estimate": cost, "exceeds_cost": (cost is not None and abs(kp - pp) > cost)})
        flag = ""
        if cost is not None:
            flag = "  ⚑ gap > spread+fees" if abs(kp - pp) > cost else "  (inside cost)"
        print("     %-4d| %13.3f | %9.3f | %+8.4f | %s%s" % (x, kp, pp, kp - pp, ("%.4f" % cost) if cost is not None else "n/a", flag))

    payload["exact_alignment_rows"] = exact_rows
    payload["interpolated_grid"] = interp_rows

    # ---- optional: strike-matched oil read (same proposition shape on both venues) ----
    if args.oil:
        import re as _re

        def _strike(text):
            m = _re.search(r"(\d{2,3}(?:\.\d+)?)", (text or "").replace(",", ""))
            return float(m.group(1)) if m else None

        kd = get_json("%s/markets?series_ticker=KXWTI&status=open&limit=200" % API)
        kmarkets = []
        for m in (kd.get("markets") or []):
            yb, ya = fnum(m.get("yes_bid_dollars")), fnum(m.get("yes_ask_dollars"))
            kmarkets.append(
                {
                    "ticker": m.get("ticker"),
                    "title": (m.get("title") or "")[:110],
                    "strike": _strike(m.get("title")),
                    "date_token": (m.get("ticker") or "").split("-")[-2] if "-" in (m.get("ticker") or "") else None,
                    "mid": round((yb + ya) / 2.0, 4) if (yb and ya) else None,
                    "bid": yb or None,
                    "ask": ya or None,
                    "volume_24h": fnum(m.get("volume_24h_fp")),
                    "close": (m.get("close_time") or "")[:16],
                }
            )
        time.sleep(0.5)
        pm_oil = []
        pm_event_slug = None
        try:
            sd = get_json("%s/public-search?q=WTI%%20Crude%%20Oil&limit_per_type=20" % GAMMA)
            for ev in (sd.get("events") or []):
                title = (ev.get("title") or "")
                if "closes above" in title.lower() and "october 12" in title.lower():
                    pm_event_slug = ev.get("slug")
                    break
            if pm_event_slug:
                evd = get_json("%s/events?slug=%s" % (GAMMA, urllib.parse.quote(pm_event_slug, safe="")))
                payload_ev = evd[0] if evd else {}
                for m in payload_ev.get("markets") or []:
                    prices = m.get("outcomePrices")
                    try:
                        prices = json.loads(prices) if isinstance(prices, str) else (prices or [])
                    except Exception:
                        prices = []
                    label = m.get("groupItemTitle") or m.get("question") or ""
                    bid, ask = m.get("bestBid"), m.get("bestAsk")
                    pm_oil.append(
                        {
                            "slug": m.get("slug"),
                            "label": label[:60],
                            "strike": _strike(label),
                            "mid": round((fnum(bid) + fnum(ask)) / 2.0, 4) if (bid and ask) else (fnum(prices[0]) if prices else None),
                            "bid": fnum(bid) or None,
                            "ask": fnum(ask) or None,
                            "fee_schedule": m.get("feeSchedule"),
                        }
                    )
        except Exception as exc:
            pm_oil = [{"error": str(exc)[:120]}]

        payload["oil_read"] = {"pm_event_slug": pm_event_slug, "kalshi": kmarkets, "polymarket": pm_oil}
        print("\n   WTI strike-matched read (same proposition shape: settlement above X):")
        print("     PM event: %s (%d thresholds) | kalshi KXWTI open markets: %d" % (pm_event_slug, len(pm_oil), len(kmarkets)))
        by_strike = {}
        for r in kmarkets:
            if r["strike"] is not None:
                by_strike.setdefault(r["strike"], r)
        matched = 0
        for p_row in sorted([r for r in pm_oil if r.get("strike") is not None], key=lambda r: r["strike"]):
            k = by_strike.get(p_row["strike"])
            if k is None:
                near = min(by_strike.items(), key=lambda kv: abs(kv[0] - p_row["strike"]), default=(None, None)) if by_strike else (None, None)
                print("     PM strike %-8s vs kalshi: NO exact strike match (nearest kalshi %s)" % (p_row["strike"], near[1]["title"][:60] if near[1] else "-"))
                continue
            matched += 1
            kp = k["mid"]
            pp = p_row["mid"]
            gap = None if (kp is None or pp is None) else round(kp - pp, 4)
            print(
                "     strike %-8s kalshi mid=%s (bid %s/ask %s) PM mid=%s (bid %s/ask %s) gap=%s | kalshi %s | PM %s"
                % (
                    p_row["strike"], kp, k["bid"], k["ask"], pp, p_row["bid"], p_row["ask"], gap,
                    k["title"][:44], p_row["label"][:28],
                )
            )
            if gap is not None and p_row["bid"] and p_row["ask"] and k["bid"] and k["ask"]:
                best = round(min(k["ask"], 1 - p_row["bid"]) - min(p_row["ask"], 1 - k["bid"]), 4)
                print("        round-trip on the SAME strike: buy kalshi ask %.2f / sell PM bid %.2f -> %+.4f per contract before fees" % (k["ask"], p_row["bid"], k["ask"] - p_row["bid"]))
        print("     exact-strike matches: %d of %d PM thresholds" % (matched, len(pm_oil)))

    # ---- optional: settled calibration for the Kalshi series ----------------
    if args.calibration:
        rowso = []
        cursor = None
        for _ in range(12):
            url = "%s/markets?series_ticker=%s&status=settled&limit=200" % (API, series)
            if cursor:
                url += "&cursor=" + urllib.parse.quote(cursor, safe="")
            d = get_json(url)
            for m in d.get("markets") or []:
                price = fnum(m.get("last_price_dollars"))
                if m.get("result") in ("yes", "no") and price > 0:
                    rowso.append((price, m.get("result") == "yes"))
            cursor = d.get("cursor")
            if not cursor:
                break
            time.sleep(0.3)
        payload["kalshi_settled_calibration"] = {"n": len(rowso)}
        print("\n   Kalshi %s settled calibration (last print vs outcome): n=%d" % (series, len(rowso)))
        for lo, hi in ((0, 0.02), (0.02, 0.10), (0.10, 0.30), (0.30, 0.70), (0.70, 0.90), (0.90, 0.98), (0.98, 1.01)):
            sub = [r for r in rowso if lo <= r[0] < hi]
            if not sub:
                continue
            rate = sum(1 for r in sub if r[1]) / float(len(sub))
            imp = sum(r[0] for r in sub) / len(sub)
            pnl = sum(((1 - r[0]) if r[1] else (-r[0])) for r in sub) / len(sub)
            print("     %.2f-%.2f n=%4d yes_rate=%.3f implied=%.3f buy-YES mean %+.4f/contract" % (lo, hi, len(sub), rate, imp, pnl))

    if args.dry_run:
        print("\n   (dry run — nothing written)")
        return 0
    out = OUTDIR / ("kalshi-crossvenue-%s-%s.json" % (args.city, date_str))
    with out.open("w") as fh:
        json.dump(payload, fh, indent=1)
    print("\n   wrote %s" % out.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
