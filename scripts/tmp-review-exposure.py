import sqlite3
con = sqlite3.connect('/Users/xsnyde2/polymarket-copybot/prisma/dev.db')
cur = con.cursor()
print("=== open notional by bot ===")
for r in cur.execute("""SELECT botId, COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) notional
FROM PaperTrade WHERE status='open' AND isDemo=0 GROUP BY botId;"""):
    print(r)
print()
print("=== BotBankroll ===")
try:
    cols = [c[1] for c in cur.execute("PRAGMA table_info(BotBankroll)")]
    print("cols:", cols)
    for r in cur.execute("SELECT * FROM BotBankroll"):
        print(r)
except Exception as e:
    print("err", e)
print()
print("=== recent daily-loss / drawdown gate evidence (last 3 days of legs) ===")
for r in cur.execute("""SELECT botId, COUNT(*) n, ROUND(SUM(realizedPnl),2) pnl
FROM PaperTrade WHERE isDemo=0 AND status IN ('closed','resolved')
AND COALESCE(closedAt,resolvedAt) > strftime('%s','2026-11-01')*1000 GROUP BY botId"""):
    print(r)
