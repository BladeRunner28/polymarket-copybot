import sqlite3, json, os

con = sqlite3.connect("prisma/dev.db")
print("-- open book --")
for r in con.execute("""
SELECT marketId, outcome, ROUND(entryPrice,3) entry, ROUND(currentPrice,3) cur,
       ROUND(simulatedPositionSize,2) sz, ROUND(unrealizedPnl,2) upnl,
       datetime(openedAt/1000,'unixepoch','-6 hours') opened
FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND status='open'
ORDER BY openedAt DESC
"""):
    print("  %-42s %-4s entry=%s cur=%s sz=%s upnl=%s opened=%s" % r)

print()
print("-- gate windows recomputed from local-day buckets --")
q = """
WITH d AS (
  SELECT date((COALESCE(closedAt,resolvedAt)/1000)-21600,'unixepoch') day,
         SUM(realizedPnl) pnl
  FROM PaperTrade
  WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
  GROUP BY day
)
SELECT day, ROUND(pnl,2) FROM d ORDER BY day DESC LIMIT 12
"""
for r in con.execute(q):
    print("  %s  %s" % r)

print()
p = "data/calibration-analysis.json"
print("calibration json mtime:", os.path.getmtime(p), "size:", os.path.getsize(p))
cfg = json.load(open(p))
print("top-level keys:", ", ".join(list(cfg.keys()))[:300])
