import sqlite3
con = sqlite3.connect("prisma/dev.db")
for excl in ("", " AND fillStatus IS NOT 'unfilled'", " AND fillStatus = 'unfilled'"):
    q = f"""
    SELECT date((COALESCE(closedAt,resolvedAt)/1000)-21600,'unixepoch') day,
           COUNT(*), ROUND(SUM(realizedPnl),2)
    FROM PaperTrade
    WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved'){excl}
    GROUP BY day ORDER BY day DESC LIMIT 4
    """
    print("filter:", excl or "(none)")
    for r in con.execute(q):
        print("   ", r)
    print()
