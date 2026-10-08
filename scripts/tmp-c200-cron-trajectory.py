#!/usr/bin/env python3
"""Trailing-window PnL stats for the C-200 report: local-day buckets (UTC-5, matching
query_bankroll.js convention), streak counts, and settlement-window framing."""
import sqlite3
import statistics

con = sqlite3.connect("prisma/dev.db")
rows = con.execute(
    """SELECT date((COALESCE(closedAt, resolvedAt)/1000) - 18000, 'unixepoch') AS d,
              COUNT(*) AS legs, ROUND(SUM(realizedPnl), 2) AS pnl
       FROM PaperTrade
       WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
       GROUP BY d ORDER BY d DESC LIMIT 45"""
).fetchall()

print("local-day realized (query_bankroll convention), newest first:")
for d, legs, pnl in rows[:21]:
    flag = "  >=500" if (pnl or 0) >= 500 else ""
    print(f"  {d}  legs={legs:3d}  pnl=${pnl:9.2f}{flag}")

# Settled basis: exclude the 3 most recent days while they settle
settled = rows[3:17]  # last 14 settled days
vals = [p for _, _, p in settled]
print(f"\nlast 14 settled days: n={len(vals)} sum=${sum(vals):.2f} mean=${statistics.mean(vals):.2f}"
      f" median=${statistics.median(vals):.2f}")
for k in (7, 14):
    v = vals[:k]
    print(f"  settled last {k}d: sum=${sum(v):.2f} mean=${sum(v)/len(v):.2f}"
          f" days>=500={sum(1 for x in v if x >= 500)}")

allday = [p for _, _, p in rows]
print(f"\n45d window: days>=500 = {sum(1 for x in allday if x >= 500)}/{len(allday)};"
      f" mean=${statistics.mean(allday):.2f} median=${statistics.median(allday):.2f}")
non_outlier = [x for x in allday if x < 1000]
print(f"45d ex-best-day-like (>1000): n={len(non_outlier)} mean=${statistics.mean(non_outlier):.2f}"
      f" median=${statistics.median(non_outlier):.2f}")

# streak of consecutive days >= 500 in the raw (T+0) read
streak = 0
for _, _, p in rows:
    if (p or 0) >= 500:
        streak += 1
    else:
        break
print(f"\ncurrent consecutive T+0 days >=500 (most recent backwards): {streak}")
print("note: 3 most recent days are still provisional/settling")
