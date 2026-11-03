#!/usr/bin/env python3
"""fee-ladder-reread — the 30-day NET re-read of the C-200 ladder gate (READ-ONLY).

WHY THIS EXISTS
  The lane-A card `fee-booking-net-ledger` pre-registers its own acceptance test:

      adopt when the modelled fee is >= 10% of booked PnL (measured 27.1%)
      AND a 30-day net re-read flips the rung verdict on >= 1 day.

  scripts/profit-fee-net.py measures the first clause and the book-wide haircut.
  Nobody had measured the second clause. This script does, on the gate's own
  basis, and nothing else.

THE GATE (definition taken from src/app/page.tsx C200_PHASES / GOAL POLICY v2)
  ladder rungs: 250 / 500 / 1,000 / 2,000 / 5,000 $/day
  advance test : trailing 7-day SETTLED SUM >= rung * 7
  settled      : status in (closed, resolved) on botId BANKROLL_200
  day bucket   : LOCAL calendar day of (closedAt ?? resolvedAt)   [c200DayKey]
  rung verdict = the highest rung whose test passes

  This script recomputes that verdict twice for every day in the last 30:
    GROSS — on booked realizedPnl (what the ladder reads today)
    NET   — on realizedPnl - enter-fee (the proposed booking)
  A "flip" is a day where the NET rung index is lower than the GROSS rung index,
  i.e. the fee changes what the ladder would have said that day.

  Two population bases are printed because they answer different questions:
    LEG  — every finished row (what the gate actually sums; primary)
    BET  — first leg per wallet/market/outcome (what profit-fee-net.py's
           FN.1/FN.4 headline uses; de-duplicates copy re-entries)

  Also printed, because "no flip" can mean either "the fee is immaterial" or
  "the book is nowhere near a rung and nothing could flip":
    - distance of the trailing 7d sum to the nearest rung threshold, gross & net
    - the would-be rung at each day under both bases (so a reader can see 0 == 0)

FEE LAW
  fee for `shares` at price p = shares * rate * p * (1 - p)
  with shares = notional / p  =>  fee / notional = rate * (1 - p)
  rate: 0.05 default, 0.04 politics/finance, 0.07 crypto (slug-keyword map,
  single-sourced by importing scripts/profit-fee-net.py so the two instruments
  cannot drift). Exit fee is NOT charged here: the ladder reads realizedPnl and
  a settled market pays one taker fee, so entry fee is the conservative-for-net
  (smallest-fee) basis. profit-fee-net.py prints the two-fee bracket.

READ-ONLY: sqlite3 immutable=1, no writes, no RuleSet read or write, no prisma.

RUN
  python3 scripts/fee-ladder-reread.py --db prisma/dev.db
  python3 scripts/fee-ladder-reread.py --db ... --days 30
"""
import argparse
import importlib.util
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

RUNGS = [250.0, 500.0, 1000.0, 2000.0, 5000.0]
GATE_WINDOW = 7
BOT = "BANKROLL_200"


def load_fee_law():
    """Single-source the fee law from the existing instrument (same directory)."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "profit-fee-net.py")
    spec = importlib.util.spec_from_file_location("profit_fee_net", path)
    if spec is None or spec.loader is None:
        sys.exit(f"cannot load the fee law from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # module has a __main__ guard; import is inert
    return mod


FEE = load_fee_law()


def load_rows(db):
    con = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
    rows = con.execute(
        "SELECT marketId, walletAddress, outcome, entryPrice, simulatedPositionSize,"
        "       status, realizedPnl, openedAt, closedAt, resolvedAt, isDemo"
        "  FROM PaperTrade WHERE botId = ? AND status IN ('closed','resolved')",
        (BOT,),
    ).fetchall()
    con.close()
    out = []
    for (mk, wal, oc, p, size, status, pnl, oa, ca, ra, demo) in rows:
        if demo or not p or p <= 0 or not size or size <= 0:
            continue
        end = ca or ra
        if not end:
            continue
        out.append(dict(mk=mk, wal=wal, oc=oc, p=p, size=size, status=status,
                        pnl=pnl or 0.0, oa=oa or 0, end=end))
    return out


def dedupe(rows):
    seen = {}
    for r in rows:
        k = (r["wal"], r["mk"], r["oc"])
        if k not in seen or r["oa"] < seen[k]["oa"]:
            seen[k] = r
    return list(seen.values())


def fee_of(r, rate):
    rt, _ = FEE.rate_of(r["mk"], rate)
    return r["size"] * rt * (1.0 - r["p"])


def day_of(ms):
    return datetime.fromtimestamp(ms / 1000.0).date()  # local, matches c200DayKey


def rung_index(total7):
    idx = 0
    for i, rung in enumerate(RUNGS):
        if total7 >= rung * GATE_WINDOW:
            idx = i + 1
        else:
            break
    return idx


def nearest_rung_blocker(total7):
    """(rung name, gap) the trailing sum fails to clear, or ('—', 0) if all clear."""
    for rung in RUNGS:
        need = rung * GATE_WINDOW
        if total7 < need:
            return rung, need - total7
    return None, 0.0


def analyse(rows, days, label, rate):
    by_day_gross = defaultdict(float)
    by_day_fee = defaultdict(float)
    by_day_n = defaultdict(int)
    for r in rows:
        d = day_of(r["end"])
        by_day_gross[d] += r["pnl"]
        by_day_fee[d] += fee_of(r, rate)
        by_day_n[d] += 1

    today = date.today()
    out = []
    for k in range(days, 0, -1):  # oldest -> newest, all COMPLETE days
        d = today - timedelta(days=k)
        win = [d - timedelta(days=j) for j in range(GATE_WINDOW - 1, -1, -1)]
        g = sum(by_day_gross[x] for x in win)
        f = sum(by_day_fee[x] for x in win)
        n = sum(by_day_n[x] for x in win)
        gi = rung_index(g)
        ni = rung_index(g - f)
        out.append(dict(day=d, days_since_today=k, n=n, gross=g, fee=f, net=g - f,
                        gi=gi, ni=ni, flip=ni < gi,
                        day_gross=by_day_gross[d], day_fee=by_day_fee[d]))
    flips = [r for r in out if r["flip"]]
    print(f"\n== {label} — trailing {GATE_WINDOW}-day settled sum vs rung*{GATE_WINDOW} ==")
    print(f"{'window end':<12} {'legs':>5} {'gross7d':>10} {'fee7d':>9} {'net7d':>10} "
          f"{'rung G':>7} {'rung N':>7} {'flip':>5}")
    for r in out:
        print(f"{r['day'].isoformat():<12} {r['n']:>5} {r['gross']:>10.2f} {r['fee']:>9.2f} "
              f"{r['net']:>10.2f} {r['gi']:>7} {r['ni']:>7} {'YES' if r['flip'] else '-':>5}")
    print(f"\n   days with a rung-verdict FLIP: {len(flips)} of {len(out)}")
    if flips:
        for r in flips:
            print(f"     {r['day'].isoformat()}: gross {r['gross']:.2f} (rung {r['gi']}) -> "
                  f"net {r['net']:.2f} (rung {r['ni']})")
    # how far is the trailing sum from the nearest rung, and does the fee cross it?
    crossings = 0
    for r in out:
        rg, gap_g = nearest_rung_blocker(r["gross"])
        rn, gap_n = nearest_rung_blocker(r["net"])
        if rg is not None and rn is not None and rg != rn:
            crossings += 1
    best = max(out, key=lambda r: r["gross"]) if out else None
    if best:
        rg, gap_g = nearest_rung_blocker(best["gross"])
        rn, gap_n = nearest_rung_blocker(best["net"])
        print(f"   best window ({best['day'].isoformat()}): gross {best['gross']:.2f} "
              f"nearest blocker ${rg:,.0f}/day (gap ${gap_g:,.2f}); "
              f"net {best['net']:.2f} nearest blocker ${rn:,.0f}/day (gap ${gap_n:,.2f})")
        print(f"   windows whose nearest blocking rung CHANGES with the fee: {crossings}")
        print(f"   gross sum as % of the smallest rung gate (${RUNGS[0]*GATE_WINDOW:,.0f}): "
              f"{100*best['gross']/(RUNGS[0]*GATE_WINDOW):.2f}%  "
              f"(net {100*best['net']/(RUNGS[0]*GATE_WINDOW):.2f}%)")
    tot_g = sum(r["day_gross"] for r in out)
    tot_f = sum(r["day_fee"] for r in out)
    print(f"   {days}d totals: gross ${tot_g:,.2f}  fee ${tot_f:,.2f} "
          f"({100*tot_f/tot_g if tot_g else 0:.2f}% of gross)  net ${tot_g-tot_f:,.2f}")
    return out, flips


def daily_variant(rows, days, rate):
    """DIAGNOSTIC ONLY — per-day rung test (day PnL >= rung target).

    This is NOT the advance gate (GOAL POLICY v2 advances on the trailing 7-day
    SUM, not on a single day), and it is printed only because "the rung verdict
    on a day" can be misread as "did that day alone earn the rung". A rung is
    not earned by one day, so this never decides anything.
    """
    g = defaultdict(float)
    f = defaultdict(float)
    for r in rows:
        d = day_of(r["end"])
        g[d] += r["pnl"]
        f[d] += fee_of(r, rate)
    today = date.today()
    flips, n = [], 0
    for k in range(days, 0, -1):
        d = today - timedelta(days=k)
        n += 1
        gi = sum(1 for x in RUNGS if g[d] >= x)
        ni = sum(1 for x in RUNGS if g[d] - f[d] >= x)
        if ni < gi:
            flips.append((d, g[d], f[d], gi, ni))
    print(f"\n== DIAGNOSTIC (not the gate) — per-day rung test, last {n} complete days ==")
    print(f"   days whose per-day rung count drops when the fee is charged: {len(flips)} of {n}")
    for d, gg, ff, gi, ni in flips[:8]:
        print(f"     {d.isoformat()}: gross ${gg:,.2f} ({gi} rung) -> net ${gg-ff:,.2f} ({ni} rung)")
    if len(flips) > 8:
        print(f"     ... {len(flips)-8} more")
    return flips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="prisma/dev.db")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--rate", type=float, default=0.05)
    a = ap.parse_args()
    if not os.path.exists(a.db):
        sys.exit(f"db not found: {a.db} (run from the repo root, or pass --db)")
    rows = load_rows(a.db)
    bets = dedupe(rows)
    print(f"fee-ladder-reread — bot {BOT}, default rate {a.rate:.2f}, "
          f"window {GATE_WINDOW}d, last {a.days} complete local days")
    print(f"finished rows: {len(rows)} legs / {len(bets)} bets; db {a.db} (immutable)")
    print(f"rungs: {' / '.join(f'${r:,.0f}' for r in RUNGS)} $/day; "
          f"gate = sum over trailing {GATE_WINDOW} settled days >= rung*{GATE_WINDOW}")
    out_leg, flips_leg = analyse(rows, a.days, "LEG basis (the gate's own population)", a.rate)
    out_bet, flips_bet = analyse(bets, a.days, "BET basis (first leg per wallet/market/outcome)", a.rate)
    print("\n== VERDICT ==")
    print(f"   LEG: {len(flips_leg)} flip day(s)   BET: {len(flips_bet)} flip day(s)")
    if flips_leg or flips_bet:
        print("   -> the fee MOVES the ladder verdict on at least one day: the")
        print("      card's second acceptance clause is MET.")
    else:
        print("   -> no day in the window changes rung under the fee: the card's")
        print("      second acceptance clause is NOT met, so its pre-registered")
        print("      decision rule does not reach 'adopt' (see the draft).")
    daily_variant(rows, a.days, a.rate)


if __name__ == "__main__":
    main()
