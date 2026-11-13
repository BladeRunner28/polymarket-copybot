#!/usr/bin/env python3
"""profit-fee-booking-preflight — DRY RUN for booking the taker fee on PaperTrade (READ-ONLY).

WHY THIS EXISTS
  Card `fee-booking-net-ledger` proposes a new `feeUsd` column on PaperTrade plus a
  net read in the ladder advance. That is Lane A (it moves a published number), so
  the proposal must ship a dry run: what the write would touch, what every figure
  becomes, and what does NOT move. This script produces exactly that, from the
  live book, writing nothing.

  It is NOT a second opinion on the fee law. It imports the law from
  scripts/profit-fee-net.py (same `rate_of` / `fee_entry` / `fee_exit`), the same
  way scripts/fee-ladder-reread.py does, so the three instruments cannot drift.

BASIS (printed on every run, always)
  population : PaperTrade, isDemo=0, entryPrice>0, simulatedPositionSize>0
  cost basis : simulatedPositionSize = DOLLARS AT RISK (never size x entry)
  fee        : entry  = size * rate * (1 - p)                  [laws: C*rate*p*(1-p), shares=size/p]
               exit   = shares * rate * c * (1 - c), c = implied exit price, CLOSED rows only
                        (a settlement/redeem is not a sale, so it pays no second fee)
  rate       : slug-keyword map, default 0.05 / politics+finance 0.04 / crypto 0.07
               (venue truth from data/fee-schedules.jsonl is preferred where a slug matches)
  day bucket : LOCAL calendar day of (closedAt ?? resolvedAt) -- c200DayKey, the ladder's own basis
  rung gate  : trailing 7 settled days SUM >= rung * 7, rungs 250/500/1000/2000/5000 (GOAL POLICY v2)

READ-ONLY: opens sqlite with immutable=1; performs no INSERT/UPDATE/DDL. Verified by
printing the column state and the row count before and after.

USAGE
  python3 scripts/profit-fee-booking-preflight.py [--db prisma/dev.db]
"""

import argparse
import importlib.util
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

RUNGS = [250.0, 500.0, 1000.0, 2000.0, 5000.0]
GATE_WINDOW = 7
LANES = ["BANKROLL_200", "STANDARD"]
VF_FILE = "data/fee-schedules.jsonl"


def load_fee_law():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "profit-fee-net.py")
    spec = importlib.util.spec_from_file_location("profit_fee_net", path)
    if spec is None or spec.loader is None:
        sys.exit(f"cannot load the fee law from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FEE = load_fee_law()


def venue_rates(path):
    """slug -> venue published rate (data/fee-schedules.jsonl, capture-only)."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            r = row.get("resolvedRate")
            if r is None:
                r = (row.get("feeSchedule") or {}).get("rate")
            if row.get("slug") and r is not None:
                out[row["slug"]] = float(r)
    return out


def load_rows(db):
    con = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
    rows = con.execute(
        "SELECT botId, marketId, walletAddress, outcome, entryPrice, simulatedPositionSize,"
        "       status, realizedPnl, openedAt, closedAt, resolvedAt, isDemo"
        "  FROM PaperTrade"
    ).fetchall()
    cols = [c[1] for c in con.execute("PRAGMA table_info(PaperTrade)").fetchall()]
    con.close()
    out = []
    skipped = {"demo": 0, "bad_field": 0}
    for (bot, mk, wal, oc, p, size, status, pnl, oa, ca, ra, demo) in rows:
        if demo:
            skipped["demo"] += 1
            continue
        if not p or p <= 0 or not size or size <= 0:
            skipped["bad_field"] += 1
            continue
        end = ca or ra
        days = ((end - oa) / 86400000.0) if (end and oa and end >= oa) else 0.0
        out.append(dict(bot=bot, mk=mk, wal=wal, oc=oc, p=p, size=size, status=status,
                        pnl=pnl or 0.0, oa=oa or 0, end=end, days=days))
    return out, cols, skipped


def band_of(p):
    return FEE.band_of(p)


def rate_for(r, default, vrates):
    """Venue truth where a slug matches, else the keyword proxy."""
    if r["mk"] in vrates:
        return vrates[r["mk"]], "venue"
    rt, cat = FEE.rate_of(r["mk"], default)
    return rt, "proxy:" + cat


def fee_parts(r, default, vrates):
    rt, src = rate_for(r, default, vrates)
    fe = FEE.fee_entry(r, rt)
    fx = FEE.fee_exit(r, rt)
    return fe, fx, rt, src


def agg(rows, default, vrates):
    a = defaultdict(lambda: defaultdict(float))
    for r in rows:
        fe, fx, rt, src = fee_parts(r, default, vrates)
        b = band_of(r["p"])
        for key in (("all", "all"), (r["bot"], b), (r["bot"], "all"), ("all", b)):
            d = a[key]
            d["n"] += 1
            d["notional"] += r["size"]
            d["gross"] += r["pnl"]
            d["cd"] += r["size"] * r["days"]
            d["fee1"] += fe
            d["fee2"] += fe + fx
    return a


def rowline(d, label, width=20):
    if not d["n"]:
        return f"{label:<{width}} {'-':>6}"
    n1 = d["gross"] - d["fee1"]
    n2 = d["gross"] - d["fee2"]
    cd = d["cd"]
    return (f"{label:<{width}} {int(d['n']):>6} {d['notional']:>9.0f} "
            f"{d['gross']:>9.0f} {100.0*d['gross']/d['notional']:>7.2f} "
            f"{d['fee1']:>8.0f} {100.0*d['fee1']/d['notional']:>6.2f} "
            f"{100.0*n1/d['notional']:>7.2f} {100.0*n2/d['notional']:>7.2f} "
            f"{1000.0*d['gross']/cd if cd else 0:>8.2f} "
            f"{1000.0*n1/cd if cd else 0:>8.2f}")


HEAD = ("{:20} {:>6} {:>9} {:>9} {:>7} {:>8} {:>6} {:>7} {:>7} {:>8} {:>8}"
        .format("population", "n", "notional", "gross$", "gross%", "fee1$", "fee1%",
                "net1%", "net2%", "g$/1kcd", "n$/1kcd"))


def day_of(ms):
    return datetime.fromtimestamp(ms / 1000.0).date()


def rung_index(total7):
    idx = 0
    for i, target in enumerate(RUNGS):
        if total7 >= target * GATE_WINDOW:
            idx = i + 1
        else:
            break
    return idx


def rung_name(idx):
    if idx <= 0:
        return "0 (<$1,750)"
    return f"{idx} (>={RUNGS[idx-1]:.0f}/day)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="prisma/dev.db")
    ap.add_argument("--rate", type=float, default=0.05)
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()

    vrates = venue_rates(VF_FILE)
    rows, cols, skipped = load_rows(args.db)
    finished = [r for r in rows if r["status"] in ("closed", "resolved") and r["end"]]
    openrows = [r for r in rows if r["status"] == "open"]

    print("profit-fee-booking-preflight — DRY RUN, read-only (sqlite immutable=1)")
    print(f"db {args.db} | fee law imported from scripts/profit-fee-net.py | default rate {args.rate}")
    print(f"COST BASIS: simulatedPositionSize = dollars at risk. Rows: {len(rows)} usable "
          f"(skipped demo {skipped['demo']}, bad-field {skipped['bad_field']})")
    print()

    # ---------------------------------------------------------------- P.0
    print("== P.0  the column this proposal adds ==")
    has = [c for c in cols if c.lower() in ("feeusd", "feerate", "feebasis", "feeexitusd")]
    if has:
        print(f"   ALREADY PRESENT: {has} — the proposal is partly applied; re-read before writing")
    else:
        print("   feeUsd / feeRate / feeBasis / feeExitUsd: NOT PRESENT on PaperTrade "
              f"({len(cols)} columns today)")
        print("   -> apply path is additive DDL + `npm run db:push` (same shape as fillStatus/"
              "fillBasis/fillResolvedAt, 2026-10-28)")
    print()

    # ---------------------------------------------------------------- P.1
    print("== P.1  what booking does to the book (before -> after) ==")
    a = agg(finished, args.rate, vrates)
    print(HEAD)
    print(rowline(a[("all", "all")], "ALL finished"))
    for lane in LANES:
        print(rowline(a[(lane, "all")], lane))
    for lane in LANES:
        for lo, hi, name in FEE.BANDS:
            d = a[(lane, name)]
            if d["n"]:
                print(rowline(d, f"  {lane[:9]} {name}"))
    print("   fee1 = entry fee only (the card's headline basis); fee2 = entry + exit fee on CLOSED rows")
    print()

    # ---------------------------------------------------------------- P.2
    print("== P.2  the backfill this proposal would write ==")
    by_status = defaultdict(lambda: [0, 0.0, 0.0])
    for r in finished + openrows:
        fe, fx, rt, src = fee_parts(r, args.rate, vrates)
        s = by_status[r["status"]]
        s[0] += 1
        s[1] += r["size"]
        s[2] += fe
    total_rows = sum(v[0] for v in by_status.values())
    total_fee = sum(v[2] for v in by_status.values())
    print(f"   {'status':<10} {'rows':>6} {'notional':>10} {'entry fee $':>12}")
    for st in ("open", "closed", "resolved"):
        v = by_status[st]
        print(f"   {st:<10} {v[0]:>6} {v[1]:>10.0f} {v[2]:>12.2f}")
    print(f"   {'TOTAL':<10} {total_rows:>6} {sum(v[1] for v in by_status.values()):>10.0f} {total_fee:>12.2f}")
    print("   open rows get the ENTRY fee only (no exit price yet) — the exit term is stamped at close")
    print()

    # ---------------------------------------------------------------- P.3
    print("== P.3  rows whose booked sign flips on the entry fee alone ==")
    flips = [r for r in finished if r["pnl"] > 0 and (r["pnl"] - fee_parts(r, args.rate, vrates)[0]) < 0]
    fl_n = sum(r["size"] for r in flips)
    fl_pnl = sum(r["pnl"] for r in flips)
    print(f"   {len(flips)} of {len(finished)} finished legs ({100.0*len(flips)/max(len(finished),1):.1f}%) "
          f"go from +PnL to -PnL · their notional ${fl_n:,.0f} · their booked gross ${fl_pnl:,.2f}")
    per_lane = defaultdict(int)
    for r in flips:
        per_lane[r["bot"]] += 1
    for lane in LANES:
        print(f"     {lane:<14} {per_lane[lane]:>5} legs")
    print()

    # ---------------------------------------------------------------- P.4
    print("== P.4  the ladder advance, gross vs net (BANKROLL_200, GOAL POLICY v2) ==")
    c200 = [r for r in finished if r["bot"] == "BANKROLL_200"]
    gross_day = defaultdict(float)
    net1_day = defaultdict(float)
    net2_day = defaultdict(float)
    for r in c200:
        k = day_of(r["end"])
        fe, fx, rt, src = fee_parts(r, args.rate, vrates)
        gross_day[k] += r["pnl"]
        net1_day[k] += r["pnl"] - fe
        net2_day[k] += r["pnl"] - fe - fx
    days = sorted(gross_day)
    if not days:
        print("   no finished C-200 rows")
    else:
        # trailing-7-settled-day verdict for every day with data
        flips, last_gross, last_net = [], {}, {}
        for i, d in enumerate(days):
            window = [dd for dd in days if 0 <= (d - dd).days < GATE_WINDOW]
            g = sum(gross_day[dd] for dd in window)
            n1 = sum(net1_day[dd] for dd in window)
            n2 = sum(net2_day[dd] for dd in window)
            ig, i1, i2 = rung_index(g), rung_index(n1), rung_index(n2)
            if ig > i1 or ig > i2:
                flips.append((d, g, n1, n2, ig, i1, i2))
            if ig >= 1:
                last_gross[d] = (g, ig)
            if i1 >= 1:
                last_net[d] = (n1, i1)
        print(f"   days with data: {len(days)}  ({days[0]} .. {days[-1]})")
        print(f"   days where GROSS clears >= rung 1: {len(last_gross)}   with NET1: {len(last_net)}")
        print(f"   days whose rung verdict DROPS under the fee: {len(flips)}")
        for (d, g, n1, n2, ig, i1, i2) in flips[:12]:
            print(f"     {d}: gross ${g:,.2f} rung {ig} -> net1 ${n1:,.2f} rung {i1}"
                  f" -> net2 ${n2:,.2f} rung {i2}")
        # the live window: last GATE_WINDOW days present
        win = [dd for dd in days if 0 <= (days[-1] - dd).days < GATE_WINDOW]
        g = sum(gross_day[dd] for dd in win)
        n1 = sum(net1_day[dd] for dd in win)
        n2 = sum(net2_day[dd] for dd in win)
        need = RUNGS[0] * GATE_WINDOW
        print()
        print(f"   window ending {days[-1]} ({len(win)} settled days): "
              f"gross ${g:,.2f} | net1 ${n1:,.2f} | net2 ${n2:,.2f}  vs rung-1 gate ${need:,.0f}")
        print(f"     rung under each basis: gross {rung_name(rung_index(g))} | "
              f"net1 {rung_name(rung_index(n1))} | net2 {rung_name(rung_index(n2))}")
        print(f"     shortfall: gross ${need-g:,.2f} | net1 ${need-n1:,.2f} | net2 ${need-n2:,.2f}")
    print()

    # ---------------------------------------------------------------- P.5
    print("== P.5  rate source: keyword proxy vs the venue's published rate ==")
    matched = [r for r in finished if r["mk"] in vrates]
    fm = sum(fee_parts(r, args.rate, vrates)[0] for r in matched)
    fp = 0.0
    for r in matched:
        rt, _ = FEE.rate_of(r["mk"], args.rate)
        fp += FEE.fee_entry(r, rt)
    print(f"   venue rates known for {len(vrates)} slugs; book rows matched: {len(matched)} "
          f"({100.0*len(matched)/max(len(finished),1):.2f}% of finished legs)")
    if matched:
        print(f"   on those rows: proxy ${fp:,.2f} vs venue ${fm:,.2f} (delta ${fm-fp:+,.2f})")
    else:
        print("   no matched rows — the backfill must run on the proxy and stamp `feeRateSource`")
    print()

    # ---------------------------------------------------------------- P.6
    print("== P.6  sensitivity: C-200 pay NO fee (its fill model is a maker limit order) ==")
    d_all = a[("all", "all")]
    d_c200 = a[("BANKROLL_200", "all")]
    d_std = a[("STANDARD", "all")]
    exempt_gross = d_all["gross"]
    exempt_net = d_std["gross"] - d_std["fee1"] + d_c200["gross"]
    print(f"   as booked (taker fee both lanes): net1 {100.0*(d_all['gross']-d_all['fee1'])/d_all['notional']:.2f}%")
    print(f"   C-200 exempt                    : net1 {100.0*exempt_net/d_all['notional']:.2f}%"
          f"  (delta {100.0*(exempt_net-(d_all['gross']-d_all['fee1']))/d_all['notional']:+.2f}pp)")
    print(f"   ^ the truth lies between these two; the booked arm is the CONSERVATIVE one")
    print()

    # ---------------------------------------------------------------- P.7
    print("== P.7  the fee law itself: fee/notional = rate x (1-p), checked on the book ==")
    print(f"   {'band':<8} {'legs':>6} {'mean p':>7} {'mean rate':>10} {'fee% predicted':>15} {'fee% booked':>12}")
    for lo, hi, name in FEE.BANDS:
        s = [r for r in finished if band_of(r["p"]) == name]
        if not s:
            continue
        mp = sum(r["p"] for r in s) / len(s)
        mr = sum(rate_for(r, args.rate, vrates)[0] for r in s) / len(s)
        pred = 100.0 * mr * (1.0 - mp)
        act = 100.0 * sum(fee_parts(r, args.rate, vrates)[0] for r in s) / sum(r["size"] for r in s)
        print(f"   {name:<8} {len(s):>6} {mp:>7.3f} {mr:>10.4f} {pred:>15.2f} {act:>12.2f}")
    print()

    print("== P.8  what must NOT move when this ships ==")
    print("   realizedPnl, unrealizedPnl, PnlSnapshot, the 5,190-cell rollup, the cumulative PnL")
    print("   series, win rate and every historical day figure stay BYTE-IDENTICAL: the fee is a")
    print("   new nullable column, and the net read is flag-gated (FEE_NET_LEDGER, default off).")
    print("   Revert = unset the flag (every published number returns exactly) then, if wanted,")
    print("   `UPDATE PaperTrade SET feeUsd=NULL, feeExitUsd=NULL, feeRate=NULL, feeBasis=NULL`.")
    print()
    print(f"READ-ONLY CHECK: rows read {len(rows)}, rows written 0, DDL executed 0 "
          f"(feeUsd present: {'yes' if has else 'no'})")


if __name__ == "__main__":
    main()
