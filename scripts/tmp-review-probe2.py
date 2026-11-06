import sqlite3, json, os
con = sqlite3.connect('/Users/xsnyde2/polymarket-copybot/prisma/dev.db')
cur = con.cursor()
print("=== C200 legs opened, last 14 local days, by band ===")
q = """
SELECT CASE WHEN entryPrice<0.20 THEN 'a 0.00-0.20' WHEN entryPrice<0.40 THEN 'b 0.20-0.40'
            WHEN entryPrice<0.60 THEN 'c 0.40-0.60' WHEN entryPrice<0.80 THEN 'd 0.60-0.80'
            ELSE 'e 0.80+' END band,
       COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) size, ROUND(AVG(simulatedPositionSize),2) avgsize
FROM PaperTrade
WHERE botId='BANKROLL_200' AND isDemo=0 AND openedAt > (strftime('%s','2026-10-22')*1000)
GROUP BY band ORDER BY band;"""
for r in cur.execute(q):
    print(r)

print()
print("=== C200 settled/closed legs last 21 days, by band (realized) ===")
q2 = """
SELECT CASE WHEN entryPrice<0.20 THEN 'a 0.00-0.20' WHEN entryPrice<0.40 THEN 'b 0.20-0.40'
            WHEN entryPrice<0.60 THEN 'c 0.40-0.60' WHEN entryPrice<0.80 THEN 'd 0.60-0.80'
            ELSE 'e 0.80+' END band,
       COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) cost, ROUND(SUM(realizedPnl),2) pnl,
       ROUND(100.0*SUM(realizedPnl)/NULLIF(SUM(simulatedPositionSize),0),2) roi
FROM PaperTrade
WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
  AND COALESCE(closedAt,resolvedAt) > (strftime('%s','2026-10-15')*1000)
GROUP BY band ORDER BY band;"""
for r in cur.execute(q2):
    print(r)

print()
print("=== C200 legs opened last 7d by hour ET ===")
q3 = """
SELECT CAST(strftime('%H', datetime(openedAt/1000 - 21600,'unixepoch')) AS INT) hr,
       COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) size
FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND openedAt > (strftime('%s','2026-10-29')*1000)
GROUP BY hr ORDER BY hr;"""
for r in cur.execute(q3):
    print(r)

print()
print("=== top one-day contributions (settled local days) ===")
q4 = """
SELECT date((COALESCE(closedAt,resolvedAt)/1000)-21600,'unixepoch') d, COUNT(*) n, ROUND(SUM(realizedPnl),2) pnl
FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
  AND COALESCE(closedAt,resolvedAt) > (strftime('%s','2026-10-01')*1000)
GROUP BY d ORDER BY ABS(SUM(realizedPnl)) DESC LIMIT 8;"""
for r in cur.execute(q4):
    print(r)

for f in ['data/wallet-cap-shadow-summary.json','data/lowconf-shadow-summary.json']:
    p='/Users/xsnyde2/polymarket-copybot/'+f
    print()
    print('===',f,'mtime', __import__('datetime').datetime.fromtimestamp(os.path.getmtime(p)).isoformat() if os.path.exists(p) else 'MISSING')
    if os.path.exists(p):
        j=json.load(open(p))
        print(json.dumps(j)[:1200])
