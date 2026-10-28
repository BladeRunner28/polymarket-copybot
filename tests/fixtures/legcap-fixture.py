#!/usr/bin/env python3
"""Build a tiny deterministic PaperTrade DB for tests/permarket-leg-cap-read.test.ts.

Three settled markets plus one open market, chosen so every repaired defect is visible in the output:

  m-a  6 legs, ntl 100, pnl -20,-20,-20,-300,-300,-300, all settling day D1   -> the worst day
  m-b  2 legs, ntl 150, pnl +10,+10, settles D2                              -> never capped at N>=2
  m-d  6 legs, ntl  50, pnl +100 x6, settles D2                              -> capping FORGOES money
  m-c  1 open leg, ntl 500                                                   -> the open-book census

At cap 5 (the N the per-market table prints) the main table's dPnL is +200 (uncapped -340 -> -140). The
per-market column must therefore sum to +200: m-a +300, m-b 0, m-d -100. Under the pre-2026-10-28
convention the same column printed the dropped legs' PnL unsigned, so it read m-a -300 and m-d +100 — the
complete opposite sign to the table above it, for the same two markets.
"""
import os
import sqlite3
import sys

DAY = 86_400_000
D1 = 100 * DAY
D2 = 101 * DAY


def build(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)
    c = sqlite3.connect(path)
    c.execute(
        """CREATE TABLE PaperTrade (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             marketId TEXT, walletAddress TEXT, entryPrice REAL,
             simulatedPositionSize REAL, realizedPnl REAL,
             openedAt INTEGER, resolvedAt INTEGER, closedAt INTEGER,
             status TEXT, isDemo INTEGER)"""
    )
    rows = []
    for i, pnl in enumerate([-20, -20, -20, -300, -300, -300]):
        rows.append(("m-a", 100.0, float(pnl), D1 - DAY + i, D1, "resolved", 0))
    for i, pnl in enumerate([10, 10]):
        rows.append(("m-b", 150.0, float(pnl), D2 - DAY + i, D2, "resolved", 0))
    for i, pnl in enumerate([100] * 6):
        rows.append(("m-d", 50.0, float(pnl), D2 - DAY + i, D2, "resolved", 0))
    for market, ntl, pnl, opened, resolved, status, demo in rows:
        c.execute(
            "INSERT INTO PaperTrade (marketId, walletAddress, entryPrice, simulatedPositionSize,"
            " realizedPnl, openedAt, resolvedAt, closedAt, status, isDemo)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (market, "0xw", 0.5, ntl, pnl, opened, resolved, None, status, demo),
        )
    c.execute(
        "INSERT INTO PaperTrade (marketId, walletAddress, entryPrice, simulatedPositionSize,"
        " realizedPnl, openedAt, resolvedAt, closedAt, status, isDemo)"
        " VALUES ('m-c','0xw',0.5,500.0,NULL,?,NULL,NULL,'open',0)",
        (D2,),
    )
    c.commit()
    c.close()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/legcap-fixture.db"
    build(out)
    print(out)
