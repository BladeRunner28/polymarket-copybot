import sqlite3

con = sqlite3.connect("prisma/dev.db")
print("-- unfilled rows with non-zero realizedPnl, by month --")
for r in con.execute("""
SELECT strftime('%Y-%m',(openedAt/1000)-21600,'unixepoch') m,
       COUNT(*) n_nonzero,
       ROUND(SUM(realizedPnl),2) pnl,
       MIN(datetime(openedAt/1000,'unixepoch','-6 hours')) first_row,
       MAX(datetime(openedAt/1000,'unixepoch','-6 hours')) last_row
FROM PaperTrade
WHERE botId='BANKROLL_200' AND isDemo=0 AND fillStatus='unfilled'
  AND realizedPnl IS NOT NULL AND realizedPnl <> 0
GROUP BY m ORDER BY m
"""):
    print("  %s  rows=%s pnl=%s  (%s .. %s)" % r)

print()
print("-- fillStatus counts by month (opened) --")
for r in con.execute("""
SELECT strftime('%Y-%m',(openedAt/1000)-21600,'unixepoch') m,
       COALESCE(fillStatus,'(null)') fs, COUNT(*) n
FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0
GROUP BY m, fs ORDER BY m, n DESC
"""):
    print("  %s %-9s %s" % r)
