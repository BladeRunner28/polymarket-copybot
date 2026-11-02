import sqlite3

con = sqlite3.connect("prisma/dev.db")

print("-- unfilled rows: side/status/pnl profile (14d) --")
q = """
SELECT side, status, COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) sz,
       SUM(CASE WHEN realizedPnl IS NOT NULL THEN 1 ELSE 0 END) with_pnl,
       ROUND(SUM(COALESCE(realizedPnl,0)),2) pnl
FROM PaperTrade
WHERE botId='BANKROLL_200' AND isDemo=0 AND fillStatus='unfilled'
  AND openedAt > (strftime('%s','now')-14*86400)*1000
GROUP BY side, status
"""
for r in con.execute(q):
    print("  side=%s status=%s n=%s notional=%s withPnl=%s pnl=%s" % r)

print()
print("-- all unfilled rows ever (not just 14d) --")
for r in con.execute("""
SELECT COUNT(*), ROUND(SUM(simulatedPositionSize),2),
       MIN(datetime(openedAt/1000,'unixepoch','-6 hours')),
       MAX(datetime(openedAt/1000,'unixepoch','-6 hours'))
FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND fillStatus='unfilled'
"""):
    print("  n=%s notional=%s first=%s last=%s" % r)

print()
print("-- unfilled: currentPrice (settlement) distribution --")
for r in con.execute("""
SELECT currentPrice, COUNT(*) FROM PaperTrade
WHERE botId='BANKROLL_200' AND isDemo=0 AND fillStatus='unfilled'
  AND openedAt > (strftime('%s','now')-14*86400)*1000
GROUP BY currentPrice ORDER BY COUNT(*) DESC LIMIT 6
"""):
    print("  cur=%s n=%s" % r)
