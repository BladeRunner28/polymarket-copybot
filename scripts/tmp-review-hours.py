import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
con = sqlite3.connect('/Users/xsnyde2/polymarket-copybot/prisma/dev.db')
cur = con.cursor()
rows = cur.execute("""SELECT openedAt, entryPrice, simulatedPositionSize, status, realizedPnl,
 COALESCE(closedAt,resolvedAt) FROM PaperTrade
 WHERE botId='BANKROLL_200' AND isDemo=0 AND openedAt > ?""",
 ((int(datetime(2026,10,1,tzinfo=timezone.utc).timestamp())*1000),)).fetchall()
print("legs since 2026-10-01 UTC:", len(rows))
from collections import defaultdict
by_hour = defaultdict(lambda: [0,0.0,0.0,0.0])   # n, size, settled_n, pnl
for o,p,s,st,pnl,c in rows:
    h = datetime.fromtimestamp(o/1000, tz=timezone.utc).astimezone(ET).hour
    b = by_hour[h]; b[0]+=1; b[1]+= s or 0
    if st in ('closed','resolved'):
        b[2]+=1; b[3]+= pnl or 0
print("hour ET | legs | size | settled | realized")
for h in sorted(by_hour):
    n,sz,sn,pn = by_hour[h]
    print(f"{h:02d}  n={int(n):3d} size=${sz:8.2f} settled={int(sn):3d} pnl=${pn:8.2f}")
print()
# check specifically gated hours over last 45 days
for target in (8,19,20,23):
    n = sum(1 for o,*_ in rows if datetime.fromtimestamp(o/1000,tz=timezone.utc).astimezone(ET).hour==target)
    print(f"{target:02d}:00 ET legs since 2026-10-01 = {n}")
print()
print("last 3 C200 opens:", [datetime.fromtimestamp(r[0]/1000,tz=timezone.utc).astimezone(ET).isoformat() for r in cur.execute("SELECT openedAt FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 ORDER BY openedAt DESC LIMIT 3")])
