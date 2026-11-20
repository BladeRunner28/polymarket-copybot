#!/usr/bin/env python3
"""profit-fee-reprice-filled — what does the 2026-11-20 23:59 UTC fee repricing do to the class
we can PROVE we held?

WHY THIS EXISTS
  Every ROI this book publishes is GROSS: `PaperTrade` has no fee column, `realizedPnl` is the
  price path, and `src/lib/fee.ts` is explicitly "NOT WIRED". The venue's taker fee is therefore
  invisible in the scoreboard while it is paid in reality. Tonight the venue changes the
  coefficients for the first time in this book's life (docs.polymarket.com, page
  programs/fee-and-rebate-changes-november-2026.md, effective 2026-11-20T23:59Z):

      category                                  old    new
      crypto BTC 5m/15m up-down                0.07   0.05
      crypto, all other markets                0.07   0.01
      all sports (incl. NFL/CFB)               0.05   0.05
      finance / tech                           0.04   0.05
      politics - elections                     0.04   0.05
      politics - non-election                  0.04   0.01
      economics / culture / weather / mentions 0.05   0.01
      geopolitics                              0      0

  So the question this script answers is narrow and decision-relevant: does the repricing change
  the SIGN of any cell in the fill-confirmed book, i.e. does it reorder the levers? If it moves
  every cell by ~1-2pp against losses of 20-60pp, then the repricing is not a lever and the only
  thing to ship is the already-approved sizing cap plus the already-proposed rate-table fix.

FEE LAW (the repo's own; do not re-invent - src/lib/scoring/price-edge.ts takerFeePerShare)
  fee for C shares at price p = C * rate * p * (1-p)
  shares = dollars_at_risk / p   =>   fee / dollars_at_risk = rate * (1-p)
  (largest at cheap prices, ~zero at p -> 1: every ROI here is on dollars at risk)
  Exit fee is charged only on a real sell (status='closed'); a resolution pays no fee.
  Exit price implied exactly from the booked PnL: c = p * (1 + pnl/cost).

VERTICAL -> RATE MAP (stated, because prices alone cannot identify a category)
  question  : marketId prefix in {will, highest, lowest, elon}     -> non-election politics 0.04 -> 0.01
  sports    : the sports prefix set below                          -> "all sports"          0.05 -> 0.05
  esports   : {cs2, dota2, lol, lec, val}                          -> "other / general"     0.05 -> 0.05
  other     : everything else                                      -> "other / general"     0.05 -> 0.05
  The question class is the ONLY one whose coefficient moves, and it is mapped to the
  non-election bucket. Sensitivity arm prices it at the ELECTIONS coefficient (0.05 new) so the
  direction of that assumption cannot change the verdict - it is printed, not assumed.

BASIS (identical to scripts/profit-path-research.py so the lines are comparable)
  cost = simulatedPositionSize (dollars at risk); pnl = realizedPnl where status IN
  ('closed','resolved') (TR-15 OR); isDemo=0; dedupe = first leg per
  (botId, walletAddress, marketId, outcome); clock = entry vintage; CI = market-clustered
  bootstrap (resample markets, 2000 draws).

SECTIONS
  FR.1 fill-confirmed book, gross vs net, old and new schedule
  FR.2 by vertical (where the rate actually moves)
  FR.3 by entry band, with net-of-fee market-clustered CI and the fee-inclusive break-even rate
  FR.4 sign table - which cells change sign under the new schedule
  FR.5 forward flow: fee delta in $/day at the measured 30-day intent rate, vs the clip cap's range
  FR.6 sensitivity - question priced at the elections coefficient

READ-ONLY: opens prisma/dev.db immutable=1. Writes nothing. No RuleSet read or write.
RUN: python3 scripts/profit-fee-reprice-filled.py [--selftest]
"""
from __future__ import annotations

import collections
import math
import os
import random
import re
import sqlite3
import sys

DB = os.path.join(os.path.dirname(__file__), "..", "prisma", "dev.db")
GATE = None  # not a LIP script

BASE = """
WITH legs AS (
  SELECT id, botId, walletAddress, marketId, outcome, entryPrice, realizedPnl, status,
         simulatedPositionSize, openedAt, fillStatus
  FROM PaperTrade
  WHERE isDemo=0 AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL
), dedup AS (
  SELECT *, ROW_NUMBER() OVER (
      PARTITION BY botId, walletAddress, marketId, outcome ORDER BY openedAt) rn
  FROM legs
)
SELECT * FROM dedup WHERE rn=1 AND fillStatus='filled'
"""

FLOW = """
WITH legs AS (
  SELECT botId, walletAddress, marketId, outcome, entryPrice, simulatedPositionSize, openedAt
  FROM PaperTrade
  WHERE isDemo=0 AND openedAt >= ? AND simulatedPositionSize > 0
), dedup AS (
  SELECT *, ROW_NUMBER() OVER (
      PARTITION BY botId, walletAddress, marketId, outcome ORDER BY openedAt) rn
  FROM legs
)
SELECT * FROM dedup WHERE rn=1
"""

QUESTION = {"will", "highest", "lowest", "elon"}
ESPORTS = {"cs2", "dota2", "lol", "lec", "val"}
SPORTS = {"ufc", "atp", "swe", "fif", "cbb", "mlb", "col", "ucl", "ere", "unl", "bel1",
          "nfl", "nba", "wnba", "cfb", "epl", "efl", "sea", "fifwc", "uel", "arg", "es2",
          "itf", "wta", "nhl", "mls", "bun", "por", "lal", "den", "bra", "mex", "jpn",
          "kor", "aus", "ind", "pak", "rsa", "nz", "eng", "sco", "wal", "ire", "fra",
          "ger", "esp", "ita", "ned", "bel", "sui", "aut", "pol", "tur", "gre"}

OLD = {"question": 0.04, "sports": 0.05, "esports": 0.05, "other": 0.05}
NEW = {"question": 0.01, "sports": 0.05, "esports": 0.05, "other": 0.05}
NEW_ELECTION = dict(NEW, question=0.05)

BANDS = ((0.0, 0.1), (0.1, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01))


def pf(market_id):
    m = re.match(r"^([a-z0-9]+)", (market_id or "").lower())
    return m.group(1) if m else "?"


def vertical(market_id):
    p = pf(market_id)
    if p in QUESTION:
        return "question"
    if p in ESPORTS:
        return "esports"
    if p in SPORTS:
        return "sports"
    return "other"


def band(p):
    if p is None:
        return "?"
    for lo, hi in BANDS:
        if lo <= p < hi:
            return f"{lo:.2f}-{hi:.2f}"
    return "?"


def entry_fee(r, rates):
    p = r["entryPrice"] or 0.0
    if not (0.0 < p < 1.0):
        return 0.0
    rate = rates[r["vert"]]
    return (r["simulatedPositionSize"] or 0.0) * rate * (1.0 - p)


def exit_fee(r, rates):
    """A resolution pays no fee; a 'closed' leg is a sell at the implied exit price."""
    if r["status"] != "closed":
        return 0.0
    rate = rates[r["vert"]]
    p = r["entryPrice"] or 0.0
    cost = r["simulatedPositionSize"] or 0.0
    pnl = r["realizedPnl"] or 0.0
    if not (0.0 < p < 1.0) or cost <= 0:
        return 0.0
    c = p * (1.0 + pnl / cost)
    c = min(max(c, 0.0), 1.0)
    notional_exit = cost * (c / p)
    return notional_exit * rate * (1.0 - c)


def fee(r, rates):
    return entry_fee(r, rates) + exit_fee(r, rates)


def load():
    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(BASE)]
    con.close()
    for r in rows:
        r["vert"] = vertical(r["marketId"])
        r["band"] = band(r["entryPrice"])
    return rows


def ci_s(ci):
    return f"[{ci[0]}, {ci[1]}]" if ci else "n/a (<5 markets)"


def cluster_ci(rows, scorefn, iters=2000, seed=7):
    """Market-clustered bootstrap of a per-leg score: resample MARKETS, not legs."""
    by_market = collections.defaultdict(list)
    for r in rows:
        by_market[r["marketId"]].append(r)
    keys = list(by_market)
    if len(keys) < 5:
        return None
    rng = random.Random(seed)
    out = []
    for _ in range(iters):
        pick = [keys[rng.randrange(len(keys))] for _ in range(len(keys))]
        num = den = 0.0
        for k in pick:
            for r in by_market[k]:
                den += r["simulatedPositionSize"] or 0.0
                num += scorefn(r)
        if den:
            out.append(100.0 * num / den)
    out.sort()
    if not out:
        return None
    return [round(out[int(0.025 * len(out))], 1), round(out[int(0.975 * len(out))], 1)]


def agg(rows, rate_old, rate_new):
    cost = sum(r["simulatedPositionSize"] or 0 for r in rows)
    pnl = sum(r["realizedPnl"] or 0 for r in rows)
    fo = sum(fee(r, rate_old) for r in rows)
    fn = sum(fee(r, rate_new) for r in rows)
    return {
        "n": len(rows), "cost": cost, "pnl": pnl,
        "gross": 100.0 * pnl / cost if cost else 0.0,
        "fee_old": fo, "fee_new": fn,
        "net_old": 100.0 * (pnl - fo) / cost if cost else 0.0,
        "net_new": 100.0 * (pnl - fn) / cost if cost else 0.0,
    }


def selftest():
    ok = 0
    R5 = {"other": 0.05}
    checks = []
    # 1. fee law: $100 at p=0.50, rate=0.05 -> 100*0.05*0.5 = $2.50
    r = {"entryPrice": 0.5, "simulatedPositionSize": 100.0, "status": "resolved",
         "realizedPnl": 100.0, "vert": "other"}
    checks.append(("entry fee p=.50 r=.05 on $100 == 2.50", abs(entry_fee(r, R5) - 2.50) < 1e-9))
    # 2. fee -> 0 as p -> 1
    r2 = dict(r, entryPrice=0.99)
    checks.append(("fee at p=.99 < 0.06", entry_fee(r2, R5) < 0.06))
    # 3. fee largest per at-risk dollar at cheap prices: rate*(1-p)
    r3 = dict(r, entryPrice=0.10)
    checks.append(("fee at p=.10 == 4.50", abs(entry_fee(r3, R5) - 4.50) < 1e-9))
    # 4. resolution pays no exit fee
    checks.append(("resolved => exit fee 0", exit_fee(r, R5) == 0.0))
    # 5. closed leg: pnl=+400 on $100 at p=0.2 -> c=1.0 -> exit fee 0
    r5 = {"entryPrice": 0.2, "simulatedPositionSize": 100.0, "status": "closed",
          "realizedPnl": 400.0, "vert": "other"}
    checks.append(("exit at c=1.0 -> 0", exit_fee(r5, R5) == 0.0))
    # 6. closed leg at flat mark pnl=0 -> c=p -> fee = cost*rate*(1-p)
    r6 = dict(r5, realizedPnl=0.0)
    checks.append(("flat exit fee == cost*rate*(1-p)",
                   abs(exit_fee(r6, R5) - 100.0 * 0.05 * 0.8) < 1e-9))
    # 7. the vertical map routes a politics market away from the sports rate
    checks.append(("vertical routing", vertical("will-trump-2027") == "question"
                   and vertical("nba-lal-bos-2026") == "sports"
                   and vertical("dota2-xyz-2026") == "esports"))
    # 8. bands partition (0,1)
    checks.append(("bands cover 0.001..0.999",
                   all(band(x) != "?" for x in (0.001, 0.05, 0.15, 0.3, 0.5, 0.7, 0.9, 0.999))))
    for name, good in checks:
        print(("PASS " if good else "FAIL ") + name)
        ok += bool(good)
    print(f"selftest {ok}/{len(checks)}")
    return 0 if ok == len(checks) else 1


def main():
    rows = load()
    if not rows:
        print("no fill-confirmed legs")
        return 1

    print(f"fill-confirmed deduped legs: {len(rows)}  "
          f"markets: {len({r['marketId'] for r in rows})}")

    # --- FR.1 book ---
    a = agg(rows, OLD, NEW)
    ci_old = cluster_ci(rows, lambda r: (r["realizedPnl"] or 0) - fee(r, OLD))
    ci_new = cluster_ci(rows, lambda r: (r["realizedPnl"] or 0) - fee(r, NEW))
    print("\n=== FR.1 FILL-CONFIRMED BOOK, gross vs net of taker fee ===")
    print(f"  n={a['n']}  cost=${a['cost']:,.0f}  pnl=${a['pnl']:,.0f}")
    print(f"  GROSS                     {a['gross']:+7.2f}%")
    print(f"  fee @old ${a['fee_old']:,.0f} ({100*a['fee_old']/a['cost']:.2f}% of at-risk) -> "
          f"net {a['net_old']:+.2f}%  CI {ci_s(ci_old)}")
    print(f"  fee @new ${a['fee_new']:,.0f} ({100*a['fee_new']/a['cost']:.2f}% of at-risk) -> "
          f"net {a['net_new']:+.2f}%  CI {ci_s(ci_new)}")
    print(f"  repricing is worth {a['fee_old']-a['fee_new']:+,.1f} dollars on this book "
          f"({100*(a['fee_old']-a['fee_new'])/a['cost']:+.2f}pp of at-risk)")

    # --- FR.2 by vertical ---
    print("\n=== FR.2 by vertical (where the coefficient actually moves) ===")
    print(f"  {'vertical':<10}{'n':>5}{'cost':>9}{'gross%':>9}{'feeO%':>8}{'feeN%':>8}"
          f"{'netO%':>9}{'netN%':>9}{'ex-top3%':>10}")
    byv = collections.defaultdict(list)
    for r in rows:
        byv[r["vert"]].append(r)
    tot_cost = sum(r["simulatedPositionSize"] or 0 for r in rows)
    for v in sorted(byv):
        g = byv[v]
        x = agg(g, OLD, NEW)
        top = sorted(g, key=lambda r: r["realizedPnl"] or 0, reverse=True)[:3]
        drop = {(id(t), t["id"]) for t in top}
        rest = [r for r in g if (id(r), r["id"]) not in drop]
        rx = agg(rest, OLD, NEW) if rest else {"gross": 0.0}
        print(f"  {v:<10}{x['n']:>5}{x['cost']:>9,.0f}{x['gross']:>9.1f}"
              f"{100*x['fee_old']/x['cost']:>8.2f}{100*x['fee_new']/x['cost']:>8.2f}"
              f"{x['net_old']:>9.1f}{x['net_new']:>9.1f}{rx['gross']:>10.1f}")
    print(f"  (cost share by vertical: " + ", ".join(
        f"{v} {100*sum(r['simulatedPositionSize'] or 0 for r in byv[v])/tot_cost:.0f}%"
        for v in sorted(byv)) + ")")

    # --- FR.3 by band ---
    print("\n=== FR.3 by entry band: gross, fee both regimes, net, fee-inclusive BE hit rate ===")
    print(f"  {'band':<10}{'n':>5}{'cost':>8}{'gross%':>8}{'feeO$':>8}{'feeN$':>8}"
          f"{'netO%':>8}{'netN%':>8}{'CI(netN)':>18}{'hit%':>7}{'beN%':>7}")
    byb = collections.defaultdict(list)
    for r in rows:
        byb[r["band"]].append(r)
    for lo, hi in BANDS:
        k = f"{lo:.2f}-{hi:.2f}"
        g = byb.get(k) or []
        if not g:
            continue
        x = agg(g, OLD, NEW)
        ci = cluster_ci(g, lambda r: (r["realizedPnl"] or 0) - fee(r, NEW))
        hit = 100.0 * sum(1 for r in g if (r["realizedPnl"] or 0) > 0) / len(g)
        bem = sum((r["entryPrice"] or 0) * (1 + NEW[vertical(r["marketId"])] *
                  (1 - (r["entryPrice"] or 0))) for r in g) / len(g)
        print(f"  {k:<10}{x['n']:>5}{x['cost']:>8,.0f}{x['gross']:>8.1f}"
              f"{x['fee_old']:>8,.0f}{x['fee_new']:>8,.0f}{x['net_old']:>8.1f}{x['net_new']:>8.1f}"
              f"{str(ci):>18}{hit:>7.1f}{100*bem:>7.1f}")

    # --- FR.4 sign flips ---
    print("\n=== FR.4 sign table - does the repricing flip any cell? ===")
    flips = []
    for k, g in sorted(byb.items()):
        x = agg(g, OLD, NEW)
        if x["net_old"] and x["net_new"] and (x["net_old"] > 0) != (x["net_new"] > 0):
            flips.append((k, x))
    for k, g in sorted(byv.items()):
        x = agg(g, OLD, NEW)
        if x["net_old"] and x["net_new"] and (x["net_old"] > 0) != (x["net_new"] > 0):
            flips.append((k, x))
    if flips:
        for k, x in flips:
            print(f"  FLIP {k}: net old {x['net_old']:+.2f}% -> new {x['net_new']:+.2f}% "
                  f"(n={x['n']}, cost ${x['cost']:,.0f})")
    else:
        print("  none - no band and no vertical changes sign; the repricing is a level shift")

    # --- FR.5 forward flow ---
    print("\n=== FR.5 forward flow: fee delta $/day at the measured 30-day intent rate ===")
    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    start_ms = None
    end_ms = con.execute("SELECT MAX(openedAt) FROM PaperTrade WHERE isDemo=0").fetchone()[0]
    start_ms = end_ms - 30 * 86400 * 1000
    flow = [dict(r) for r in con.execute(FLOW, (start_ms,))]
    con.close()
    days = 30.0
    fy = collections.defaultdict(list)
    for r in flow:
        r["vert"] = vertical(r["marketId"])
        fy[r["vert"]].append(r)
    tot_intent = tot_delta = 0.0
    print(f"  window: last 30d of entry vintage, {len(flow)} deduped intents")
    print(f"  {'vertical':<10}{'intent$/d':>11}{'mean(1-p)':>11}{'dRate':>8}{'$/day':>9}")
    for v in sorted(fy):
        g = fy[v]
        intent = sum(r["simulatedPositionSize"] or 0 for r in g) / days
        m1p = sum(1 - (r["entryPrice"] or 0) for r in g) / len(g)
        dr = OLD[v] - NEW[v]
        d = intent * m1p * dr
        tot_intent += intent
        tot_delta += d
        print(f"  {v:<10}{intent:>11,.1f}{m1p:>11.3f}{dr:>8.3f}{d:>9.2f}")
    print(f"  TOTAL intent ${tot_intent:,.0f}/day | repricing saves ${tot_delta:+.2f}/day "
          f"({100*tot_delta/tot_intent if tot_intent else 0:+.2f}% of intent)")
    print(f"  For scale: the fill-confirmed book loses ${abs(a['pnl'])/days:,.2f}/day of GROSS pnl "
          f"on the same clock, and the $100 clip alone carries "
          f"${abs(sum(r['realizedPnl'] or 0 for r in rows if (r['simulatedPositionSize'] or 0) >= 90))/days:,.2f}/day.")

    # --- FR.6 sensitivity ---
    print("\n=== FR.6 sensitivity: question priced at the ELECTIONS coefficient (0.05 new) ===")
    b = agg(rows, OLD, NEW_ELECTION)
    print(f"  book net under worst-case mapping: {b['net_new']:+.2f}% "
          f"(vs {a['net_new']:+.2f}% on the non-election mapping) - "
          f"spread {b['net_new']-a['net_new']:+.2f}pp")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    raise SystemExit(main())
