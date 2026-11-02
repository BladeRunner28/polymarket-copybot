import sqlite3

con = sqlite3.connect("prisma/dev.db")

print("-- delta histogram: intent - entry, by fillStatus (all-time) --")
for r in con.execute("""
SELECT fillStatus, ROUND(intentPrice-entryPrice,3) d, COUNT(*) n
FROM PaperTrade
WHERE botId='BANKROLL_200' AND isDemo=0 AND intentPrice IS NOT NULL
GROUP BY fillStatus, d ORDER BY fillStatus, n DESC
"""):
    print("  %-9s delta=%s n=%s" % r)

print()
print("-- one unfilled row in full --")
cols = [c[1] for c in con.execute("PRAGMA table_info(PaperTrade)")]
row = con.execute("""
SELECT * FROM PaperTrade
WHERE botId='BANKROLL_200' AND isDemo=0 AND fillStatus='unfilled' AND status='resolved'
ORDER BY openedAt DESC LIMIT 1""").fetchone()
for c, v in zip(cols, row):
    print(f"  {c} = {v}")

print()
print("-- settled pnl split by fillStatus, all-time --")
for r in con.execute("""
SELECT COALESCE(fillStatus,'(null)') fs, COUNT(*) n,
       ROUND(SUM(simulatedPositionSize),0) notional,
       ROUND(SUM(realizedPnl),2) pnl
FROM PaperTrade
WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
GROUP BY fs ORDER BY n DESC
"""):
    print("  %-9s n=%s notional=%s pnl=%s" % r)
