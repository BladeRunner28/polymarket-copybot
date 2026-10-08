#!/usr/bin/env python3
"""Ad-hoc verification reads for the C-200 cron report (ET-hour grouping, open book)."""
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
con = sqlite3.connect("prisma/dev.db")
con.row_factory = sqlite3.Row

rows = con.execute(
    """SELECT id, walletAddress, marketId, outcome, entryPrice, simulatedPositionSize,
              realizedPnl, unrealizedPnl, status, openedAt
       FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0
       AND openedAt > (strftime('%s','now')-14*86400)*1000"""
).fetchall()

def et_dt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(ET)

by_hour = defaultdict(lambda: [0, 0.0, 0.0])
for r in rows:
    ms = r["openedAt"]
    if ms is None:
        continue
    # openedAt is stored as Unix-ms per project convention
    d = et_dt(int(ms))
    b = by_hour[d.hour]
    b[0] += 1
    b[1] += float(r["simulatedPositionSize"] or 0)
    b[2] += float(r["realizedPnl"] or 0)

print("opened-by-ET-hour, last 14d (n / notional / realized)")
for h in sorted(by_hour):
    n, notional, rp = by_hour[h]
    print(f"  {h:02d}:00 ET  n={n:3d}  notional=${notional:8.2f}  realized=${rp:8.2f}")

# 7d ET-hour mix for the two gated hours named in the standing inputs
print("\ngated-hour check (08:00 / 20:00 ET), last 7d:")
for target in (8, 20):
    sel = [r for r in rows if et_dt(int(r["openedAt"])).hour == target
           and int(r["openedAt"]) > (datetime.now(tz=timezone.utc).timestamp() - 7 * 86400) * 1000]
    print(f"  {target:02d}:00 ET  n={len(sel)}  ids={[r['id'][:12] for r in sel][:6]}")

print("\nopen book:")
op = [r for r in rows if r["status"] == "open"]
print(f"  legs={len(op)}  notional=${sum(float(r['simulatedPositionSize'] or 0) for r in op):.2f}"
      f"  unrealized=${sum(float(r['unrealizedPnl'] or 0) for r in op):.2f}")
for r in sorted(op, key=lambda x: -float(x["simulatedPositionSize"] or 0))[:8]:
    print(f"  {r['walletAddress'][:10]}  entry={float(r['entryPrice']):.3f}"
          f"  sz=${float(r['simulatedPositionSize']):.2f}  upnl=${float(r['unrealizedPnl'] or 0):.2f}"
          f"  opened={et_dt(int(r['openedAt'])).strftime('%m-%d %H:%M')}ET")
