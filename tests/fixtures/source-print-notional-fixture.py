#!/usr/bin/env python3
"""
Fixture book for scripts/source-print-notional-read.py.

Builds the four tables the read touches (PaperTrade, DecisionJournal, ObservedTrade,
MarketSnapshot) with a book whose answer is known by construction:

    --plant  : 6 big-print legs at roi -0.40, 24 small-print legs at roi +0.10,
               every leg in the SAME matching cell (era v71+, entry 0.50, TTR 12h,
               stake $10) -> the matched gap MUST read +0.50/$1 (small - big).
    (no flag): identical book except the big legs also return +0.10 -> gap MUST
               read 0.00, which is the negative control for the sign convention.

Six wallets carry the legs so the wallet-clustered bootstrap has clusters.
"""
import sqlite3
import sys

DDL = """
CREATE TABLE PaperTrade (id TEXT PRIMARY KEY, botId TEXT, isDemo INTEGER, status TEXT,
  realizedPnl REAL, simulatedPositionSize REAL, walletAddress TEXT, marketId TEXT,
  outcome TEXT, entryPrice REAL, decisionJournalId TEXT, openedAt INTEGER);
CREATE TABLE DecisionJournal (id TEXT PRIMARY KEY, observedTradeId TEXT, ruleSetVersion INTEGER);
CREATE TABLE ObservedTrade (id TEXT PRIMARY KEY, walletAddress TEXT, marketId TEXT,
  outcome TEXT, side TEXT, size REAL, timestamp INTEGER, isDemo INTEGER, observationOnly INTEGER);
CREATE TABLE MarketSnapshot (id TEXT PRIMARY KEY, marketId TEXT, collectedAt INTEGER,
  timeToResolution REAL);
CREATE INDEX ObservedTrade_composite ON ObservedTrade
  (walletAddress, marketId, outcome, side, timestamp);
CREATE INDEX MarketSnapshot_m ON MarketSnapshot (marketId, collectedAt);
"""

T0 = 1793000000000  # 2026-10-26T..Z, comfortably after the card's 2026-09-04 epoch


def build(db, plant):
    con = sqlite3.connect(db)
    con.executescript(DDL)
    n_small, n_big = 24, 6
    for i in range(n_small + n_big):
        big = i >= n_small
        wallet = "0xw%02d" % (i % 6)
        market = "mkt-%02d" % i
        tid = "t%02d" % i
        ot = T0 + i * 60000
        print_usd = 500.0 if big else 20.0
        roi = -0.40 if (big and plant) else 0.10
        stake = 10.0
        con.execute("INSERT INTO ObservedTrade VALUES (?,?,?,?,?,?,?,?,?)",
                    ("o%02d" % i, wallet, market, "YES", "BUY", print_usd, ot, 0, 0))
        con.execute("INSERT INTO DecisionJournal VALUES (?,?,?)",
                    ("j%02d" % i, "o%02d" % i, 71))
        con.execute("INSERT INTO PaperTrade VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (tid, "BANKROLL_200", 0, "resolved", roi * stake, stake, wallet, market,
                     "YES", 0.50, "j%02d" % i, ot))
        con.execute("INSERT INTO MarketSnapshot VALUES (?,?,?,?)",
                    ("s%02d" % i, market, ot - 1000, 12.0))
    con.commit()
    con.close()


if __name__ == "__main__":
    db = sys.argv[1]
    plant = "--plant" in sys.argv
    build(db, plant)
    print("fixture written: %s (plant=%s)" % (db, plant))
