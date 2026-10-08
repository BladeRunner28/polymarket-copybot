#!/usr/bin/env python3
"""Wallet/band concentration reads: where the 7d realized PnL and the >=$500 days come from."""
import sqlite3
from collections import defaultdict

con = sqlite3.connect("prisma/dev.db")

print("=== 7d realized by wallet (top 10) ===")
rows = con.execute(
    """SELECT walletAddress, COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) notional,
              ROUND(SUM(COALESCE(realizedPnl,0)),2) pnl, ROUND(AVG(entryPrice),3) avg_entry
       FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0
       AND openedAt > (strftime('%s','now')-7*86400)*1000
       GROUP BY walletAddress ORDER BY abs(SUM(COALESCE(realizedPnl,0))) DESC LIMIT 10"""
).fetchall()
tot = con.execute(
    """SELECT ROUND(SUM(COALESCE(realizedPnl,0)),2), COUNT(*) FROM PaperTrade
       WHERE botId='BANKROLL_200' AND isDemo=0
       AND openedAt > (strftime('%s','now')-7*86400)*1000"""
).fetchone()
print(f"  7d total realized on open-cohort basis: ${tot[0]} across {tot[1]} legs")
for w, n, notional, pnl, ae in rows:
    print(f"  {w[:12]}  n={n:3d}  notional=${notional:8.2f}  pnl=${pnl:8.2f}  avg_entry={ae}")

print("\n=== leg size distribution, 7d ===")
buckets = defaultdict(int)
for (sz,) in con.execute(
    """SELECT simulatedPositionSize FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0
       AND openedAt > (strftime('%s','now')-7*86400)*1000"""
):
    s = float(sz or 0)
    key = "$0-2" if s < 2 else "$2-5" if s < 5 else "$5-10" if s < 10 else "$10-25" if s < 25 else "$25-50" if s < 50 else "$50+"
    buckets[key] += 1
for k in ("$0-2", "$2-5", "$5-10", "$10-25", "$25-50", "$50+"):
    print(f"  {k:7s} {buckets.get(k,0)}")

print("\n=== biggest 7d realized legs (open-cohort) ===")
for w, ep, sz, pnl, st in con.execute(
    """SELECT walletAddress, ROUND(entryPrice,3), ROUND(simulatedPositionSize,2),
              ROUND(COALESCE(realizedPnl,0),2), status
       FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0
       AND openedAt > (strftime('%s','now')-7*86400)*1000
       ORDER BY abs(COALESCE(realizedPnl,0)) DESC LIMIT 8"""
):
    print(f"  {w[:12]}  entry={ep}  sz=${sz}  pnl=${pnl}  {st}")
