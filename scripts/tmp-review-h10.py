import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict
ET = ZoneInfo("America/New_York")
con = sqlite3.connect('/Users/xsnyde2/polymarket-copybot/prisma/dev.db')
cur = con.cursor()
cut = int(datetime(2026,10,6,tzinfo=timezone.utc).timestamp())*1000
rows = cur.execute("""SELECT openedAt, entryPrice, simulatedPositionSize, status, realizedPnl
FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND openedAt > ?""",(cut,)).fetchall()
agg = defaultdict(lambda: [0,0.0])
for o,p,s,st,pnl in rows:
    h = datetime.fromtimestamp(o/1000,tz=timezone.utc).astimezone(ET).hour
    b = 'L' if (p or 0)<0.20 else ('S' if (p or 0)<0.60 else 'H')
    k=(h,b); agg[k][0]+=1; agg[k][1]+= s or 0
print("hour ET, band L=<0.20 S=0.20-0.60 H=>=0.60 : n / total / avg size")
for k in sorted(agg):
    n,sz = agg[k]
    print(f"  {k[0]:02d} {k[1]}  n={n:3d} size=${sz:8.2f} avg=${sz/n:6.2f}")
# open legs since cut, hour 10 vs 11, compare
print()
print("hour 10 vs 11 vs 14-16 avg size, ALL bands last 30d:")
for target in (10,11,14,15,16):
    n = sum(agg[(target,b)][0] for b in 'LSH'); sz = sum(agg[(target,b)][1] for b in 'LSH')
    print(f"  {target:02d}: n={n} avg=${sz/n if n else 0:.2f}")
