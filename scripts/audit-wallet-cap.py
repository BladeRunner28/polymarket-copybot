#!/usr/bin/env python3
"""v58 per-wallet ceiling — the 7-day re-check (tuning review #30 rec 1).

Read-only. Prints the two things the rec's Verify line asks for, plus the
counterfactual that makes the gate's effect checkable:

  1. top-1 wallet share of C-200 open cost (target <= 25.0%, baseline 84.6%)
  2. `per-wallet cap` blocks in the monitor log vs DecisionJournal rows carrying
     the reason (they must be EQUAL — the log line is emitted per blocked leg,
     and only the C-200 book is gated, so 1 line == 1 row here)
  3. the concentration ladder (top-1 / top-3 / wallets) before vs now

Usage:  cd ~/polymarket-copybot && python3 scripts/audit-wallet-cap.py [--since <epoch_ms>]
"""
import argparse
import os
import re
import sqlite3
import subprocess
from collections import Counter

DB = os.path.join(os.path.dirname(__file__), "..", "prisma", "dev.db")
LOG = os.path.join(os.path.dirname(__file__), "..", "logs", "cron", "copybot-monitor-score.log")
BASELINE = os.path.join(os.path.dirname(__file__), "..", "data", "wallet-cap-baseline.json")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def live_ceiling(con):
    """The ceiling the scorer would compute on its next cycle, derived exactly as
    score-trades.ts does (same RuleSet fields, same equity-linked formula)."""
    import json

    rules = json.loads(
        con.execute("SELECT rulesJson FROM RuleSet WHERE active=1 ORDER BY version DESC LIMIT 1").fetchone()[0]
    )
    principal, realized = con.execute(
        "SELECT principal, realizedPnl FROM BotBankroll WHERE botId='BANKROLL_200'"
    ).fetchone()
    ddBasis = rules.get("ddBasis") or "mtm"
    unreal = con.execute(
        "SELECT COALESCE(SUM(unrealizedPnl),0) FROM PaperTrade WHERE botId='BANKROLL_200' AND status='open'"
    ).fetchone()[0]
    nw_realized = principal + realized
    nw_mtm = nw_realized + unreal
    nw = nw_realized if ddBasis == "realized" else min(nw_mtm, nw_realized) if ddBasis == "min" else nw_mtm
    base = rules.get("maxGrossExposureUsd") or 0
    cap = base + 0.5 * max(0.0, nw - principal) if principal > 0 and base > 0 else base
    pct = rules.get("maxWalletNotionalPctOfCap") or 0
    basis = "delta" if rules.get("walletCapBasis") == "delta" else "stock"
    baseline = json.load(open(BASELINE))["baseline"] if basis == "delta" else {}
    return cap, pct * cap, basis, baseline, ddBasis


def replay(con, days: int) -> None:
    """Per-leg replay of the v58 predicate over the window (the 'how close did it
    come' read; the EXACT record of whether the rail fired is the journal count).

    For each C-200 leg that OPENED in the window, the wallet's notional HELD at
    that instant (open legs only) plus the leg's own size, against the live
    ceiling for that wallet. Caveat printed with the numbers: the ceiling is
    held at TODAY's value, and the cap rises with realized net worth, so a lower
    cap at decision time would raise every ratio here.
    """
    import datetime as dt

    cap, ceiling, basis, baseline, ddBasis = live_ceiling(con)
    now_ms = con.execute("SELECT (strftime('%s','now'))*1000").fetchone()[0]
    lo = now_ms - days * 86400 * 1000
    legs = con.execute(
        "SELECT walletAddress, simulatedPositionSize, openedAt, closedAt, resolvedAt FROM PaperTrade "
        "WHERE botId='BANKROLL_200' AND openedAt > ? ORDER BY openedAt",
        (lo,),
    ).fetchall()
    book = con.execute(
        "SELECT walletAddress, simulatedPositionSize, openedAt, closedAt, resolvedAt FROM PaperTrade "
        "WHERE botId='BANKROLL_200' ORDER BY openedAt"
    ).fetchall()
    print(
        f"\nREPLAY {days}d | live ceiling ${ceiling:.2f} = {100 * (ceiling / cap if cap else 0):.2f}% of cap "
        f"${cap:.2f} (ddBasis {ddBasis}, basis {basis}) | {len(legs)} legs, "
        f"{len({l[0] for l in legs})} wallets"
    )
    ranked = []
    for w, size, t, closed, resolved in legs:
        held = sum(
            b[1]
            for b in book
            if b[0] == w
            and b[2] <= t
            and not (b[3] is not None and b[3] <= t)
            and not (b[4] is not None and b[4] <= t)
        )
        proj = held + size
        ceil = ceiling + (baseline.get(w, 0) if basis == "delta" else 0)
        ranked.append((proj / ceil if ceil else 0, proj, ceil, w, t, size, held))
    ranked.sort(reverse=True)
    blocked = sum(1 for r in ranked if r[0] > 1.0)
    print(f"  max ratio {ranked[0][0]:.3f} ({ranked[0][3][:10]}… {dt.datetime.utcfromtimestamp(ranked[0][4] / 1000):%Y-%m-%d %H:%M})"
          f" | median {ranked[len(ranked) // 2][0]:.3f} | legs over the ceiling: {blocked}")
    for ratio, proj, ceil, w, t, size, held in ranked[:5]:
        print(
            f"   {ratio:5.3f}  proj ${proj:8.2f} vs ceiling ${ceil:8.2f}  clip ${size:7.2f} held ${held:8.2f}  "
            f"{w[:10]}… {dt.datetime.utcfromtimestamp(t / 1000):%Y-%m-%d %H:%M}"
        )
    print("  caveat: ceiling held at TODAY's value; the cap rises with realized NW, so a lower cap"
          " in-window raises every ratio above. Adjudicate 'did it fire' on the journal count, not on this.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=None, help="epoch-ms lower bound for the journal count")
    ap.add_argument("--replay", type=int, default=None, metavar="DAYS",
                    help="replay the v58 predicate over the last DAYS (how close the rail came)")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro", uri=True)
    if args.replay is not None:
        replay(con, args.replay)
        return
    rows = con.execute(
        "SELECT walletAddress, simulatedPositionSize FROM PaperTrade "
        "WHERE botId='BANKROLL_200' AND status='open' AND isDemo=0"
    ).fetchall()
    if not rows:
        print("no open C-200 rows")
        return
    book = sum(r[1] for r in rows)
    per_wallet = Counter()
    for w, s in rows:
        per_wallet[w] += s
    ranked = per_wallet.most_common()
    top1_w, top1 = ranked[0]
    top3 = sum(v for _, v in ranked[:3])
    print(f"C-200 open book: {len(rows)} rows / ${book:.2f} across {len(ranked)} wallets")
    print(f"top-1 {top1_w[:10]}… ${top1:.2f} = {100 * top1 / book:.1f}%  (target <= 25.0; baseline 84.6)")
    print(f"top-3 = {100 * top3 / book:.1f}% of open cost")
    for w, v in ranked[:5]:
        print(f"   {w[:10]}… {v:9.2f}  {100 * v / book:5.1f}%")

    # log lines (per blocked C-200 leg) vs journal rows (per decision)
    lines = 0
    with open(LOG, errors="replace") as fh:
        for line in fh:
            if "v58 per-wallet cap" in line:
                lines += 1
    where = "risksJson LIKE '%v58 per-wallet cap%'"
    if args.since:
        where += f" AND createdAt >= {args.since}"
    journal = con.execute(f"SELECT COUNT(*) FROM DecisionJournal WHERE {where}").fetchone()[0]
    print(f"\nblocks: log lines {lines} | journal rows {journal} | {'EQUAL ✅' if lines == journal else 'MISMATCH ❌'}")
    print("  (C-200-only gate => 1 line per blocked leg per decision; a mismatch means the")
    print("   journal write was lost, not that a leg went unlogged)")
    if journal:
        sample = con.execute(
            f"SELECT datetime(createdAt/1000,'unixepoch'), marketId, substr(risksJson,1,160) "
            f"FROM DecisionJournal WHERE {where} ORDER BY createdAt DESC LIMIT 3"
        ).fetchall()
        for ts, mkt, risk in sample:
            print(f"  {ts} {mkt}")
            print(f"      {re.sub(r'^.*v58 per-wallet cap', 'v58 per-wallet cap', risk)}")


if __name__ == "__main__":
    main()
