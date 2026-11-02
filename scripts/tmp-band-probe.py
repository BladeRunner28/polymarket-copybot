import sqlite3
con = sqlite3.connect("prisma/dev.db")
print("-- settled notional/pnl by entry band, last 14d --")
for r in con.execute("""
SELECT CASE WHEN entryPrice<0.2 THEN '0-0.20'
            WHEN entryPrice<0.4 THEN '0.20-0.40'
            WHEN entryPrice<0.6 THEN '0.40-0.60'
            WHEN entryPrice<0.8 THEN '0.60-0.80' ELSE '0.80+' END band,
       COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) notional,
       ROUND(SUM(realizedPnl),2) pnl,
       ROUND(AVG(simulatedPositionSize),2) avg_sz
FROM PaperTrade
WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
  AND COALESCE(closedAt,resolvedAt) > (strftime('%s','now')-14*86400)*1000
GROUP BY band ORDER BY band
"""):
    print("  %-10s n=%-4s notional=%-8s pnl=%-8s avgSize=%s" % r)

print()
print("-- all-time per band (settled) --")
for r in con.execute("""
SELECT CASE WHEN entryPrice<0.2 THEN '0-0.20'
            WHEN entryPrice<0.4 THEN '0.20-0.40'
            WHEN entryPrice<0.6 THEN '0.40-0.60'
            WHEN entryPrice<0.8 THEN '0.60-0.80' ELSE '0.80+' END band,
       COUNT(*) n, ROUND(SUM(simulatedPositionSize),0) notional,
       ROUND(SUM(realizedPnl),2) pnl,
       ROUND(SUM(realizedPnl)/SUM(simulatedPositionSize)*100,1) roi
FROM PaperTrade
WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
GROUP BY band ORDER BY band
"""):
    print("  %-10s n=%-5s notional=%-8s pnl=%-9s roi=%s%%" % r)
