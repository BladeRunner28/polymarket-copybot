#!/usr/bin/env python3
"""Fixture DB for tests/fee-exit-basis.test.ts — three legs, two of them early exits.

Leg A  closed,  entered 0.57 and STEPPED OUT at 0.02  (the case the bug inflated ~12x)
Leg B  resolved at 0, no sale  -> entry fee only, never an exit fee
Leg C  closed,  entered 0.53 and left at 0.90
Category rate: "sports" -> CAT_RATE has no entry, keyword map falls to "other" -> 0.05,
so both arms of fee-sign-flip-test.py price at 0.05 and the arithmetic is checkable by hand.
"""
import os
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else "fee-exit-fixture.db"

LEGS = [
    # id, bot, market, entry, size, status, pnl, currentPrice
    ("legA", "STANDARD", "will-team-a-win-the-cup", 0.57, 10.0, "closed", -9.65, 0.02),
    ("legB", "STANDARD", "will-team-b-win-the-cup", 0.30, 5.0, "resolved", -5.0, 0.0),
    ("legC", "STANDARD", "will-team-c-win-the-cup", 0.53, 5.0, "closed", 3.49, 0.90),
]

if os.path.exists(DB):
    os.remove(DB)
con = sqlite3.connect(DB)
con.execute("""CREATE TABLE PaperTrade (
    id TEXT PRIMARY KEY, botId TEXT, marketId TEXT, entryPrice REAL, currentPrice REAL,
    simulatedPositionSize REAL, realizedPnl REAL, status TEXT, isDemo BOOLEAN,
    openedAt INTEGER, closedAt INTEGER, decisionJournalId TEXT)""")
con.execute("""CREATE TABLE DecisionJournal (id TEXT PRIMARY KEY, observedTradeId TEXT)""")
con.execute("""CREATE TABLE ObservedTrade (
    id TEXT PRIMARY KEY, conditionId TEXT, marketCategoryFine TEXT, marketCategoryClass TEXT)""")

for i, (tid, bot, mk, p, size, status, pnl, cp) in enumerate(LEGS):
    con.execute("INSERT INTO DecisionJournal VALUES (?,?)", ("j" + tid, "o" + tid))
    con.execute("INSERT INTO ObservedTrade VALUES (?,?,?,?)",
                ("o" + tid, "0xcond" + tid, "sports", "sports"))
    con.execute("INSERT INTO PaperTrade VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, bot, mk, p, cp, size, pnl, status, 0, 1793000000000,
                 1793609160543 if status == "closed" else None, "j" + tid))
con.commit()
con.close()
print("wrote %s with %d legs" % (DB, len(LEGS)))
