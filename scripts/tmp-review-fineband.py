import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
con = sqlite3.connect('/Users/xsnyde2/polymarket-copybot/prisma/dev.db')
cur = con.cursor()

print("=== C200 finished legs, fine price bands (all-time) ===")
q = """
SELECT CASE WHEN entryPrice<0.05 THEN '0.00-0.05' WHEN entryPrice<0.10 THEN '0.05-0.10'
            WHEN entryPrice<0.20 THEN '0.10-0.20' WHEN entryPrice<0.30 THEN '0.20-0.30'
            WHEN entryPrice<0.40 THEN '0.30-0.40' WHEN entryPrice<0.60 THEN '0.40-0.60'
            WHEN entryPrice<0.80 THEN '0.60-0.80' ELSE '0.80+' END b,
 COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) cost, ROUND(AVG(simulatedPositionSize),2) avg,
 ROUND(SUM(realizedPnl),2) pnl,
 ROUND(100.0*SUM(realizedPnl)/NULLIF(SUM(simulatedPositionSize),0),2) roi,
 ROUND(100.0*SUM(CASE WHEN realizedPnl>0 THEN 1 ELSE 0 END)/COUNT(*),1) winpct
FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
GROUP BY b ORDER BY b;"""
for r in cur.execute(q): print(r)

print()
print("=== same, last 30 finished days ===")
cut = int(datetime(2026,10,6,tzinfo=timezone.utc).timestamp())*1000
q2 = """
SELECT CASE WHEN entryPrice<0.05 THEN '0.00-0.05' WHEN entryPrice<0.10 THEN '0.05-0.10'
            WHEN entryPrice<0.20 THEN '0.10-0.20' WHEN entryPrice<0.40 THEN '0.20-0.40'
            WHEN entryPrice<0.80 THEN '0.60-0.80' ELSE '0.80+' END b,
 COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) cost, ROUND(SUM(realizedPnl),2) pnl,
 ROUND(100.0*SUM(realizedPnl)/NULLIF(SUM(simulatedPositionSize),0),2) roi
FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
 AND COALESCE(closedAt,resolvedAt) > ?
GROUP BY b ORDER BY b;"""
for r in cur.execute(q2, (cut,)): print(r)

print()
print("=== book concentration: share of all-time PnL from top 10 legs ===")
q3 = """SELECT COUNT(*) n, ROUND(SUM(realizedPnl),2) total FROM PaperTrade
WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved');"""
print(cur.execute(q3).fetchone())
q4 = """SELECT ROUND(SUM(realizedPnl),2) FROM (SELECT realizedPnl FROM PaperTrade
WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
ORDER BY realizedPnl DESC LIMIT 10);"""
print("top10 legs sum:", cur.execute(q4).fetchone())

print()
print("=== daily report: roll-out math on settled gate ===")
vals = {'10-23':0.21,'10-24':-110.00,'10-25':-75.49,'10-26':-249.83,'10-27':-67.78,'10-28':-66.89,
        '10-29':968.67,'10-30':67.71,'10-31':21.07,'11-01':-121.32,'11-02':38.19,
        '11-03':1354.67,'11-04':326.33,'11-05':0.12}
win = ['10-27','10-28','10-29','10-30','10-31','11-01','11-02']
print('settled window 10-27..11-02 =', round(sum(vals[d] for d in win),2))
nxt = win[1:]+['11-03']
print('next window 10-28..11-03 =', round(sum(vals[d] for d in nxt),2), '(if 11-03 settles at mark)')
nxt2 = nxt[1:]+['11-04']
print('then 10-29..11-04 =', round(sum(vals[d] for d in nxt2),2))
nxt3 = nxt2[1:]+['11-05']
print('then 10-30..11-05 =', round(sum(vals[d] for d in nxt3),2))
print('ex-top2-day run-rate (10-29..11-04 minus 968.67 & 1354.67) /7 =', round((sum(vals[d] for d in nxt2)-968.67-1354.67)/7,2))
