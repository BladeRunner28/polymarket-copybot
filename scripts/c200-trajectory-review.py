#!/usr/bin/env python3
"""C-200 trajectory review instrument (ladder trajectory + sizing counterfactuals).

Reproduces every figure the daily review quotes for the $5k/day path:
  * rolling 7-SETTLED-day sums (GOAL POLICY v2 gate basis), stepped day by day
  * month / trailing-14d rates on LOCAL calendar days (closedAt ?? resolvedAt)
  * October concentration and the full-clip ("Kelly", size>=50) split
  * counterfactuals: clip x1.5, per-local-day full-clip admit cap, and both

Basis notes: LOCAL days are (ts/1000 - 18000) so a leg closing 02:00 UTC lands
on the previous local day (this is why a UTC-basis read disagrees by a few legs).
Cost basis is simulatedPositionSize (dollars at risk), never size*entryPrice.
Populations are botId='BANKROLL_200', isDemo=0, status IN ('closed','resolved').

Usage: python3 scripts/c200-trajectory-review.py [as-of YYYY-MM-DD]
"""
import sqlite3
import datetime
import collections
import sys

DB = '/Users/xsnyde2/polymarket-copybot/prisma/dev.db'
BASE = '2026-10-01'          # month under review
WIN_START, WIN_END = '2026-10-11', '2026-10-17'   # the gate window being reported


def load(as_of):
    con = sqlite3.connect(DB)
    rows = con.execute("""
      SELECT id, openedAt, COALESCE(closedAt,resolvedAt) AS t, realizedPnl,
             simulatedPositionSize, entryPrice,
             date((openedAt/1000)-18000,'unixepoch') AS opened_day,
             date((COALESCE(closedAt,resolvedAt)/1000)-18000,'unixepoch') AS close_day
      FROM PaperTrade
      WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
        AND date((COALESCE(closedAt,resolvedAt)/1000)-18000,'unixepoch') BETWEEN ? AND ?
        AND realizedPnl IS NOT NULL
    """, (BASE, as_of)).fetchall()
    return rows


def main():
    as_of = sys.argv[sys.argv.index('as-of') + 1] if 'as-of' in sys.argv else '2026-10-20'
    end = datetime.date.fromisoformat(as_of)
    rows = load(as_of)

    daily = collections.defaultdict(float)
    dlegs = collections.defaultdict(int)
    for r in rows:
        daily[r[7]] += r[3]
        dlegs[r[7]] += 1

    def window_sum(end_day, n=7):
        days = [(end_day - datetime.timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]
        return sum(daily.get(d, 0.0) for d in days), sum(dlegs.get(d, 0) for d in days), days

    print('=== rolling 7-SETTLED-day SUM (gate basis = trailing 7 settled days), stepped daily ===')
    for off in range(3, 15):
        s, n, days = window_sum(end - datetime.timedelta(days=off))
        print(f'  window {days[0]} .. {days[-1]}  ${s:>10,.2f}   legs={n}')

    mtd_days = sorted({r[7] for r in rows})
    total = sum(r[3] for r in rows)
    print(f'\n=== rates (LOCAL days) ===')
    print(f'  MTD {BASE}..{as_of}: {len(rows)} legs over {len(mtd_days)} settled days '
          f'${total:,.2f}  = ${total/len(mtd_days):,.2f}/day')
    last14 = [(end - datetime.timedelta(days=i)).isoformat() for i in range(16, 2, -1)]
    p14 = sum(daily.get(d, 0.0) for d in last14)
    print(f'  trailing 14 settled ({last14[0]}..{last14[-1]}): ${p14:,.2f} = ${p14/14:,.2f}/day')

    kelly = [r for r in rows if r[4] >= 50]
    rest = [r for r in rows if r[4] < 50]
    kw = sum(1 for r in kelly if r[3] > 0)
    print(f'\n=== full-clip split (size >= $50 = the Kelly clip) ===')
    print(f'  full-clip: {len(kelly)} legs ({kw} wins) ${sum(r[3] for r in kelly):,.2f} '
          f'avg ${sum(r[3] for r in kelly)/max(len(kelly),1):,.2f}')
    print(f'  rest:      {len(rest)} legs ${sum(r[3] for r in rest):,.2f}')

    pnls = sorted((r[3] for r in rows), reverse=True)
    print('\n=== concentration (MTD) ===')
    for k in (1, 2, 3, 5):
        print(f'  top-{k} legs = ${sum(pnls[:k]):,.2f} ({sum(pnls[:k])/total*100:.0f}% of total)')

    def cap_day(rs, cap):
        byd = collections.defaultdict(list)
        for r in rs:
            byd[r[6]].append(r)
        kept, dropped = [], []
        for d, v in byd.items():
            v.sort(key=lambda x: x[1])
            kept += v[:cap]
            dropped += v[cap:]
        return kept, dropped

    print('\n=== counterfactuals on MTD settled PnL ===')
    base = total
    a = sum(r[3] * 1.5 for r in kelly) + sum(r[3] for r in rest)
    print(f'  A clip x1.5 (kellyMaxSizeUsd 100->150): ${a:,.2f}  (delta ${a-base:+,.2f})')
    for cap in (1, 2):
        kept, dropped = cap_day(kelly, cap)
        b = sum(r[3] for r in kept) + sum(r[3] for r in rest)
        print(f'  B cap {cap} full-clip admit/local day: ${b:,.2f} (delta ${b-base:+,.2f}); '
              f'dropped {len(dropped)} legs ${sum(r[3] for r in dropped):+,.2f} '
              f'({sum(1 for r in dropped if r[3] > 0)} wins)')
        ab = sum(r[3] * 1.5 for r in kept) + sum(r[3] for r in rest)
        print(f'  A+B (clip 150, cap {cap}/day): ${ab:,.2f} (delta ${ab-base:+,.2f})')

    w = [r for r in rows if WIN_START <= r[7] <= WIN_END]
    wk = [r for r in w if r[4] >= 50]
    print(f'\n=== reported gate window {WIN_START}..{WIN_END} ===')
    print(f'  {len(w)} legs ${sum(r[3] for r in w):,.2f}; full-clip {len(wk)} legs '
          f'${sum(r[3] for r in wk):,.2f}; rest ${sum(r[3] for r in w if r[4] < 50):,.2f}')
    print(f'  A (x1.5): ${sum(r[3]*1.5 for r in wk) + sum(r[3] for r in w if r[4] < 50):,.2f}')
    for cap in (1, 2):
        kept, _ = cap_day(wk, cap)
        print(f'  B cap {cap}/day: ${sum(r[3] for r in kept) + sum(r[3] for r in w if r[4] < 50):,.2f}')


if __name__ == '__main__':
    main()
