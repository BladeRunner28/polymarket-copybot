import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
con = sqlite3.connect('/Users/xsnyde2/polymarket-copybot/prisma/dev.db')
cur = con.cursor()
cut = int(datetime(2026,10,6,tzinfo=timezone.utc).timestamp())*1000

print("=== 19:00 ET C200 legs, last 60d ===")
cut60 = int(datetime(2026,9,6,tzinfo=timezone.utc).timestamp())*1000
rows = cur.execute("""SELECT openedAt, marketId, entryPrice, simulatedPositionSize, realizedPnl, status
FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
AND COALESCE(closedAt,resolvedAt) > ? ORDER BY realizedPnl ASC LIMIT 400""",(cut60,)).fetchall()
n=0; tot=0.0
for o,slug,p,s,pnl,st in rows:
    if datetime.fromtimestamp(o/1000,tz=timezone.utc).astimezone(ET).hour==19:
        n+=1; tot+=pnl or 0
        print(f"  {datetime.fromtimestamp(o/1000,tz=timezone.utc).astimezone(ET):%m-%d %H:%M} p={p:.3f} size={s:.2f} pnl={pnl:+.2f} {str(slug)[:20]}")
print("19h legs(60d):", n, "pnl:", round(tot,2))

print()
print("=== 0.05-0.20 settled legs last 30d: distribution ===")
rows = cur.execute("""SELECT openedAt, entryPrice, simulatedPositionSize, realizedPnl FROM PaperTrade
WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
AND COALESCE(closedAt,resolvedAt) > ? AND entryPrice>=0.05 AND entryPrice<0.20
ORDER BY realizedPnl DESC""",(cut,)).fetchall()
n=len(rows); tot=sum(r[3] or 0 for r in rows)
cost=sum(r[2] or 0 for r in rows)
wins=sum(1 for r in rows if (r[3] or 0)>0)
print(f"n={n} cost=${cost:.2f} pnl=${tot:.2f} roi={100*tot/cost:.1f}% win%[EXIT]={100*wins/n:.1f} avg=${cost/n:.2f}")
print("top3:", [round(r[3],2) for r in rows[:3]], "bottom3:", [round(r[3],2) for r in rows[-3:]])
print(f"ex-top3 pnl=${tot-sum(r[3] for r in rows[:3]):.2f} ex-top3 roi={100*(tot-sum(r[3] for r in rows[:3]))/cost:.1f}%")

print()
print("=== 0.60-0.80 last 30d: n and pnl detail ===")
r = cur.execute("""SELECT COUNT(*), ROUND(SUM(simulatedPositionSize),2), ROUND(SUM(realizedPnl),2),
 SUM(CASE WHEN realizedPnl>0 THEN 1 ELSE 0 END) FROM PaperTrade
WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
AND COALESCE(closedAt,resolvedAt) > ? AND entryPrice>=0.60 AND entryPrice<0.80""",(cut,)).fetchone()
print(r)
