#!/usr/bin/env python3
"""standard-longshot-concentration -- the instrument the t_d8ec3c64 card cites but never shipped.

WHY THIS FILE EXISTS
--------------------
The card "APPROVAL NEEDED (Lane A): per-position cap vs concurrent-long-shot limit" cites
`scripts/kelly-concentration-test.py`, `data/kelly-concentration-test.json` and
`drafts/kelly-concentration-prereg-20261029.md`. None of the three has ever existed in git history
on 2026-11-09 -- so its headline numbers (median $334.99 / p90 $890.91 / max $1,120.52, 16 breach
days, STANDARD 12.2% of NW) cannot be re-derived by anyone, including the session that approved a
cap on them. That is an instrument defect: a rail whose evidence base is prose only.

WHAT IT MEASURES (read-only; file:prisma/dev.db?mode=ro)
  S1  the OPEN book right now, per lane: long-shot vs other, cost basis = simulatedPositionSize
  S2  the DAILY PEAK concurrent long-shot cost as % of that lane's net worth, replayed from history
  S3  the COUNTERFACTUAL: replay STANDARD entries in order and block any long-shot entry that would
      push concurrent long-shot cost above pct x net worth. Report what those blocked legs actually
      realised -- a veto count is not a cost, and a cap that blocks winners is not a cap that helps.
  S4  a pct sensitivity sweep, so the LEVEL is chosen on measurement instead of argued

BASIS NOTES (both stated because each can flip a level)
  * cost basis is `simulatedPositionSize` = DOLLARS AT RISK, never size x price (that understates
    every cheap leg, and the cheap band is the whole argument).
  * net worth is REALIZED-ONLY over time: principal + realised PnL of legs closed before the entry.
    Unrealised marks would RAISE net worth and LOOSEN the cap, so this basis is the strict one.
  * a leg counts as a long-shot at `entryPrice < longshotMaxPrice` read from the ACTIVE RuleSet.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import datetime

DB = "prisma/dev.db"
LANES = ("STANDARD", "BANKROLL_200")


def ms(v):
    """Prisma DATETIME is Unix-ms in this DB."""
    return None if v is None else int(v) / 1000.0


def iso(t):
    return "open" if t is None else datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")


def active_rules(con):
    row = con.execute(
        "SELECT version, rulesJson FROM RuleSet WHERE active=1 ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if not row:
        raise SystemExit("no active RuleSet")
    return row["version"], json.loads(row["rulesJson"])


def bankrolls(con):
    out = {}
    for r in con.execute("SELECT botId, principal, cashBalance, realizedPnl FROM BotBankroll"):
        out[r["botId"]] = {
            "principal": r["principal"] or 0.0,
            "cash": r["cashBalance"] or 0.0,
            "realized": r["realizedPnl"] or 0.0,
        }
    return out


def legs(con, lane):
    q = """
    SELECT id, entryPrice, simulatedPositionSize AS ntl, realizedPnl AS pnl, status,
           openedAt, closedAt, resolvedAt, outcome, marketId
    FROM PaperTrade
    WHERE botId = ? AND simulatedPositionSize > 0 AND openedAt IS NOT NULL
    ORDER BY openedAt
    """
    out = []
    for r in con.execute(q, (lane,)):
        d = dict(r)
        d["open_s"] = ms(r["openedAt"])
        close = ms(r["closedAt"]) or ms(r["resolvedAt"])
        d["close_s"] = close
        out.append(d)
    return out


def is_longshot(leg, thr):
    p = leg["entryPrice"]
    return p is not None and p < thr


def s1_open_book(con, thr, br, rules, version):
    print("=" * 78)
    print(f"S1  OPEN BOOK NOW  (long-shot = entryPrice < {thr}  from ACTIVE RuleSet v{version})")
    print("=" * 78)
    for lane in LANES:
        rows = con.execute(
            "SELECT entryPrice, simulatedPositionSize AS ntl FROM PaperTrade "
            "WHERE botId=? AND status='open'",
            (lane,),
        ).fetchall()
        ls = [r for r in rows if r["entryPrice"] is not None and r["entryPrice"] < thr]
        nw = br.get(lane, {}).get("principal", 0.0) + br.get(lane, {}).get("realized", 0.0)
        ls_ntl = sum(r["ntl"] for r in ls)
        all_ntl = sum(r["ntl"] for r in rows)
        pct = (ls_ntl / nw * 100) if nw else 0.0
        print(
            f"  {lane:13s} open legs {len(rows):5d}  cost ${all_ntl:10.2f} | "
            f"long-shot legs {len(ls):4d} cost ${ls_ntl:9.2f} | "
            f"NW ${nw:10.2f} | long-shot = {pct:5.2f}% of NW"
        )


def replay(con, lane, thr, pct, br, cap_on=True, verbose=False):
    """Chronological replay. Returns (rows_with_decision, peak_pct_by_day, blocked)."""
    rows = legs(con, lane)
    principal = br.get(lane, {}).get("principal", 0.0)
    if not rows:
        return [], {}, []
    t0, t1 = rows[0]["open_s"], rows[-1]["open_s"]
    horizon = max(30.0, (t1 - t0) / 86400.0)
    # realised-only net worth as it stood before each entry
    events = []
    for r in rows:
        close = r["close_s"] if r["close_s"] is not None else float("inf")
        events.append((close, r["pnl"] or 0.0))
    events.sort(key=lambda x: x[0])

    live = []          # (close_s, cost) of admitted long-shot legs
    cum_realized = 0.0
    ei = 0
    blocked = []
    peak_by_day = {}
    for r in rows:
        t = r["open_s"]
        while ei < len(events) and events[ei][0] <= t:
            cum_realized += events[ei][1]
            ei += 1
        nw = principal + cum_realized
        live = [(c, n) for (c, n) in live if c is None or c > t]
        open_cost = sum(n for _, n in live)
        day = datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d")
        cur_pct = (open_cost / nw * 100) if nw > 0 else 0.0
        if cur_pct > peak_by_day.get(day, 0.0):
            peak_by_day[day] = cur_pct

        ls = is_longshot(r, thr)
        r["_longshot"] = ls
        r["_decision"] = "admitted"
        if ls and cap_on and pct > 0 and nw > 0:
            ceiling = pct / 100.0 * nw
            if open_cost + r["ntl"] > ceiling:
                r["_decision"] = "BLOCKED"
                blocked.append(r)
                continue
        if ls:
            live.append((r["close_s"], r["ntl"]))
    return rows, peak_by_day, blocked


def s2_peaks(peak_by_day, lane, pct):
    if not peak_by_day:
        print(f"  {lane:13s} no history")
        return
    vals = sorted(peak_by_day.values())
    n = len(vals)
    over = sum(1 for v in vals if v > pct)
    print(
        f"  {lane:13s} days {n:4d} | peak% median {vals[n // 2]:5.2f} | p90 {vals[min(n - 1, int(n * 0.9))]:5.2f} "
        f"| max {vals[-1]:5.2f} | days > {pct}%: {over} ({over / n * 100:.0f}%)"
    )
    worst = sorted(peak_by_day.items(), key=lambda kv: -kv[1])[:3]
    print("               worst days: " + " · ".join(f"{d} {v:.1f}%" for d, v in worst))


def s3_counterfactual(rows, blocked, thr, pct):
    admitted_ls = [r for r in rows if r["_longshot"] and r["_decision"] == "admitted"]
    blocked_ls = blocked
    print()
    print("=" * 78)
    print(f"S3  COUNTERFACTUAL at {pct:.1f}% of net worth -- what the cap would have BLOCKED")
    print("=" * 78)

    def summarise(label, rs):
        n = len(rs)
        ntl = sum(r["ntl"] for r in rs)
        pnl = sum(r["pnl"] or 0.0 for r in rs)
        roi = (pnl / ntl * 100) if ntl else 0.0
        print(f"  {label:26s} n={n:5d}  cost ${ntl:9.2f}  realised ${pnl:+9.2f}  ROI {roi:+6.2f}%")
        return pnl

    pnl_adm = summarise("admitted long-shot legs", admitted_ls)
    pnl_blk = summarise("BLOCKED long-shot legs", blocked_ls)
    print()
    print(f"  net effect of the cap on realised PnL: ${-pnl_blk:+.2f} "
          f"({'SAVES' if pnl_blk < 0 else 'COSTS'} money)")
    if blocked_ls:
        dates = sorted({datetime.datetime.fromtimestamp(r["open_s"]).strftime("%Y-%m-%d") for r in blocked_ls})
        print(f"  blocked entries fall on {len(dates)} day(s): {', '.join(dates[:8])}{' …' if len(dates) > 8 else ''}")
        big = sorted(blocked_ls, key=lambda r: -(r["pnl"] or 0))[:3]
        print("  largest blocked WINNERS: " + " · ".join(
            f"{r['marketId'][:18]} {r['entryPrice']:.3f} ${r['ntl']:.2f} -> {r['pnl']:+.2f}" for r in big))
    return pnl_adm, pnl_blk


def main():
    pcts = [8.0, 10.0, 12.0, 15.0, 20.0]
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    version, rules = active_rules(con)
    thr = float(rules.get("longshotMaxPrice", 0.20))
    br = bankrolls(con)

    s1_open_book(con, thr, br, rules, version)

    print()
    print("=" * 78)
    print(f"S2  DAILY PEAK concurrent long-shot cost as % of net worth (whole history, no cap)")
    print("=" * 78)
    for lane in LANES:
        rows, peaks, _ = replay(con, lane, thr, 0.0, br, cap_on=False)
        s2_peaks(peaks, lane, 10.0)

    print()
    print("=" * 78)
    print("S4  LEVEL SENSITIVITY -- STANDARD, cap ON at each pct")
    print("=" * 78)
    print(f"  {'pct':>6} {'blocked':>9} {'blocked $':>11} {'blocked PnL':>13} {'net effect':>12}")
    for p in pcts:
        rows, peaks, blocked = replay(con, "STANDARD", thr, p, br, cap_on=True)
        ntl = sum(r["ntl"] for r in blocked)
        pnl = sum(r["pnl"] or 0.0 for r in blocked)
        print(f"  {p:5.1f}% {len(blocked):9d} {ntl:11.2f} {pnl:+13.2f} {-pnl:+12.2f}")

    print()
    print("=" * 78)
    print("S3  detail at the approved level (10% of net worth)")
    print("=" * 78)
    rows, peaks, blocked = replay(con, "STANDARD", thr, 10.0, br, cap_on=True)
    s3_counterfactual(rows, blocked, thr, 10.0)
    con.close()


if __name__ == "__main__":
    main()
