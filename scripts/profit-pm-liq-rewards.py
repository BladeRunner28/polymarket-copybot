#!/usr/bin/env python3
"""Does Polymarket's Liquidity Rewards program pay anything on the markets WE trade?

Third Polymarket path, never measured before 2026-11-23. Unlike Kalshi's LIP (measured
EMPTY: 0 of 7,499 live programs above $0.0131/contract-hour), Polymarket publishes a
per-market DAILY RATE on the keyless CLOB endpoint `GET /sampling-markets`, and a third
party counted $66,933/day across 7,913 reward-eligible markets (2026-11-22).

This script answers the only question that matters before any rule: on our own traded
universe, what does the published pool pay per contract-hour and per dollar-at-risk, at
100% share (a CEILING, exactly the discipline used for the Kalshi LIP ledger)?

Basis:
  venue    = Polymarket CLOB /sampling-markets (keyless, no auth), rewards block per market
  rate     = rewards_daily_rate for USDC (0x2791...4174) only; other tokens counted separately
             because a non-USD token is not a dollar
  join     = PaperTrade.marketId == market_slug
  legs     = isDemo=0, status IN (closed,resolved)  (TR-15 OR), dedupe first leg per
             (botId,walletAddress,marketId,outcome); cost = simulatedPositionSize (dollars at risk)
  ceiling  = rate_usd / (min_size * hours_per_day) per SHARE held per hour, and
             rate_usd / (min_size * entry_price) per DOLLAR at risk per day
  caveat   = a pool is OFFERED, not earned; the ceiling assumes 100% share, no competition

Read-only. Writes data/pm-liquidity-rewards.json. Changes no rule.
"""
from __future__ import annotations

import collections
import json
import os
import time
import urllib.parse
import urllib.request

DB = os.path.join(os.path.dirname(__file__), "..", "prisma", "dev.db")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "pm-liquidity-rewards.json")
API = "https://clob.polymarket.com/sampling-markets"
USDC = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"   # USDC.e on Polygon
KALSHI_GATE_PCH = 0.0131                              # scale reference only, different venue
MAX_PAGES = 30


def fetch_all():
    markets, cursor, pages = {}, "MA==", 0
    while pages < MAX_PAGES:
        url = "%s?next_cursor=%s" % (API, urllib.parse.quote(cursor, safe="=+/"))
        req = urllib.request.Request(url, headers={"User-Agent": "copybot-research/1.0",
                                                   "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as fh:
                body = json.load(fh)
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode("utf-8", "replace")
            raise SystemExit("HTTP %s for %s :: %s" % (exc.code, url, detail))
        rows = body.get("data") or []
        for m in rows:
            slug = m.get("market_slug") or ""
            if slug:
                markets[slug] = m
        pages += 1
        nxt = body.get("next_cursor") or ""
        # the CLOB sends base64("-1") as its end sentinel; requesting it returns 400
        if not nxt or nxt in ("LTE=",) or nxt == cursor or not rows:
            break
        cursor = nxt
        time.sleep(0.2)
    return markets, pages


def reward_of(m):
    """(usdc_rate_per_day, other_token_rate_per_day, min_size, max_spread)."""
    r = m.get("rewards") or {}
    usdc = other = 0.0
    for rate in (r.get("rates") or []):
        try:
            v = float(rate.get("rewards_daily_rate") or 0)
        except (TypeError, ValueError):
            continue
        addr = (rate.get("asset_address") or "").lower()
        if addr == USDC:
            usdc += v
        else:
            other += v
    try:
        min_size = float(r.get("min_size") or 0)
    except (TypeError, ValueError):
        min_size = 0.0
    try:
        max_spread = float(r.get("max_spread") or 0)
    except (TypeError, ValueError):
        max_spread = 0.0
    return usdc, other, min_size, max_spread


def legs():
    import sqlite3
    con = sqlite3.connect("file:%s?mode=ro&immutable=1" % os.path.abspath(DB), uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("""
        WITH l AS (
          SELECT botId, walletAddress, marketId, outcome, entryPrice, realizedPnl,
                 simulatedPositionSize, openedAt
          FROM PaperTrade
          WHERE isDemo=0 AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL
        ), d AS (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY botId,walletAddress,marketId,outcome
                                       ORDER BY openedAt) rn FROM l
        )
        SELECT * FROM d WHERE rn=1""")]
    con.close()
    return rows


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return round(xs[i], 6)


def main():
    rows = legs()
    by_market = collections.defaultdict(list)
    for r in rows:
        by_market[r["marketId"]].append(r)
    markets, pages = fetch_all()

    print("=== PM LIQUIDITY REWARDS: universe (CLOB /sampling-markets, %d pages) ===" % pages)
    usdc_rates, other_ct, min_sizes, spreads, elig = [], 0, [], [], 0
    for slug, m in markets.items():
        u, o, ms, sp = reward_of(m)
        if o:
            other_ct += 1
        if u > 0:
            elig += 1
            usdc_rates.append(u)
            if ms:
                min_sizes.append(ms)
            spreads.append(sp)
    print("markets listed: %d   USDC-rate eligible: %d   non-USDC-rate markets: %d"
          % (len(markets), elig, other_ct))
    if not usdc_rates:
        print("NO USDC RATES RETURNED — nothing to price")
        return
    tot = sum(usdc_rates)
    print("published pool on this list: $%.2f/day   median $%.2f   p90 $%.2f   max $%.2f"
          % (tot, pct(usdc_rates, .5), pct(usdc_rates, .9), max(usdc_rates)))
    print("min_size: median %s   max_spread(c): median %s"
          % (pct(min_sizes, .5), pct(spreads, .5)))

    # --- our traded universe
    print("\n=== OUR TRADED UNIVERSE (settled deduped legs) ===")
    traded = [(slug, v) for slug, v in by_market.items()]
    have = [(slug, v, markets[slug]) for slug, v in traded if slug in markets]
    have_elig = [(slug, v, m) for slug, v, m in have if reward_of(m)[0] > 0]
    print("traded markets (all-time settled): %d   listed on sampling-markets: %d (%.1f%%)   "
          "reward-eligible: %d (%.1f%%)"
          % (len(traded), len(have), 100.0 * len(have) / max(1, len(traded)),
             len(have_elig), 100.0 * len(have_elig) / max(1, len(traded))))

    cells = []
    for slug, v, m in have_elig:
        rate, _, ms, sp = reward_of(m)
        px = sorted(r["entryPrice"] for r in v if r["entryPrice"])[len(v) // 2]
        cost = sum(r["simulatedPositionSize"] or 0 for r in v)
        pnl = sum(r["realizedPnl"] or 0 for r in v)
        pch = (rate / (ms * 24.0)) if ms else None            # $/share/hour at 100% share
        cap_side = (ms * px) if ms else None                  # $ to rest one side
        yld = (rate / (ms * px) * 100.0) if ms and px else None  # %/day on that capital
        cells.append({"slug": slug, "rate_day": rate, "min_size": ms, "max_spread_c": sp,
                      "entry_px": round(px, 3), "legs": len(v), "cost": round(cost, 2),
                      "pnl": round(pnl, 2), "capital_one_side_usd": round(cap_side, 2) if cap_side else None,
                      "pch_usd": round(pch, 6) if pch else None,
                      "yield_pct_day_ceiling": round(yld, 3) if yld else None})

    cells.sort(key=lambda c: -(c["pch_usd"] or 0))
    print("%-42s %7s %6s %7s %8s %8s" % ("market (ours, eligible)", "rate/d", "minsz", "$cap", "$/sh/hr", "%/d cap"))
    for c in cells[:20]:
        print("%-42s %7.2f %6.0f %7.0f %8.5f %8.3f"
              % (c["slug"][:42], c["rate_day"], c["min_size"], c["capital_one_side_usd"] or 0,
                 c["pch_usd"] or 0, c["yield_pct_day_ceiling"] or 0))

    pchs = [c["pch_usd"] for c in cells if c["pch_usd"]]
    ylds = [c["yield_pct_day_ceiling"] for c in cells if c["yield_pct_day_ceiling"] is not None]
    caps = [c["capital_one_side_usd"] for c in cells if c["capital_one_side_usd"]]
    cost_all = sum(r["simulatedPositionSize"] or 0 for r in rows)
    cost_elig = sum(c["cost"] for c in cells)
    print("\n  DOLLARS: our settled at-risk in reward-eligible markets $%.0f of $%.0f = %.2f%%"
          % (cost_elig, cost_all, 100.0 * cost_elig / max(1.0, cost_all)))
    # flow-relevant window: is the pool co-located with what we open NOW?
    import time as _t
    cut = int((_t.time() - 30 * 86400) * 1000)
    recent = [r for r in rows if (r["openedAt"] or 0) >= cut]
    rm = collections.defaultdict(list)
    for r in recent:
        rm[r["marketId"]].append(r)
    r_elig = [s for s in rm if s in markets and reward_of(markets[s])[0] > 0]
    r_cost = sum(x["simulatedPositionSize"] or 0 for s in r_elig for x in rm[s])
    r_all = sum(x["simulatedPositionSize"] or 0 for s in rm for x in rm[s])
    print("  LAST 30d: %d markets / %d legs / $%.0f at risk -> %d reward-eligible markets (%.1f%%), "
          "$%.0f (%.2f%%) of risk" % (len(rm), len(recent), r_all, len(r_elig),
                                      100.0 * len(r_elig) / max(1, len(rm)), r_cost,
                                      100.0 * r_cost / max(1.0, r_all)))
    print("\nour eligible cells: %d   median $/share/hr %.5f (p90 %.5f, max %.5f)"
          % (len(cells), pct(pchs, .5) or 0, pct(pchs, .9) or 0, max(pchs) if pchs else 0))
    print("  median ceiling yield %%/day on one-side capital: %.3f (p90 %.3f)"
          % (pct(ylds, .5) or 0, pct(ylds, .9) or 0))
    print("  median one-side capital to qualify: $%.0f (p90 $%.0f)" % (pct(caps, .5) or 0, pct(caps, .9) or 0))
    print("  Kalshi gate for scale: $%.4f/contract-hour (different venue, not a transfer target)"
          % KALSHI_GATE_PCH)

    # how many of ours clear the Kalshi gate purely on the reward ceiling?
    above = [c for c in cells if (c["pch_usd"] or 0) >= KALSHI_GATE_PCH]
    print("  our cells clearing $0.0131/share-hour on the ceiling: %d of %d" % (len(above), len(cells)))

    art = {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "basis": "CLOB /sampling-markets; rewards_daily_rate USDC; join marketId==market_slug; "
                    "ceiling = 100% pool share, no competition; offered not earned",
           "universe": {"listed": len(markets), "usdc_eligible": elig, "other_token": other_ct,
                        "pool_usd_day": round(tot, 2), "median_rate": pct(usdc_rates, .5),
                        "p90_rate": pct(usdc_rates, .9), "max_rate": max(usdc_rates),
                        "min_size_median": pct(min_sizes, .5), "max_spread_c_median": pct(spreads, .5)},
           "ours": {"traded_markets": len(traded), "listed": len(have),
                    "eligible": len(have_elig), "cells": cells,
                    "cost_all": round(cost_all, 2), "cost_eligible": round(cost_elig, 2),
                    "cost_eligible_pct": round(100.0 * cost_elig / max(1.0, cost_all), 2),
                    "last30d": {"markets": len(rm), "legs": len(recent), "cost": round(r_all, 2),
                                "eligible_markets": len(r_elig), "eligible_cost": round(r_cost, 2),
                                "eligible_cost_pct": round(100.0 * r_cost / max(1.0, r_all), 2)}},
           "summary": {"pch_median": pct(pchs, .5), "pch_p90": pct(pchs, .9),
                       "pch_max": max(pchs) if pchs else None,
                       "yield_median_pct_day": pct(ylds, .5), "yield_p90_pct_day": pct(ylds, .9),
                       "capital_median_usd": pct(caps, .5), "capital_p90_usd": pct(caps, .9),
                       "cells_above_kalshi_gate": len(above)}}
    with open(OUT, "w") as fh:
        json.dump(art, fh, indent=1)
    print("\nartifact -> %s" % os.path.relpath(OUT))


if __name__ == "__main__":
    import urllib.parse  # noqa: F401  (used in fetch_all)
    main()
