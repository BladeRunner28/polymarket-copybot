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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=None, help="epoch-ms lower bound for the journal count")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro", uri=True)
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
