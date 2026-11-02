import sqlite3

con = sqlite3.connect("prisma/dev.db")
q = """
SELECT p.fillStatus,
       ROUND(AVG(p.intentPrice - p.entryPrice), 4) avg_intent_minus_fill,
       ROUND(AVG(p.intentPrice), 4) avg_intent,
       ROUND(AVG(p.entryPrice), 4) avg_entry,
       COUNT(*) n
FROM PaperTrade p
WHERE p.botId='BANKROLL_200' AND p.isDemo=0
  AND p.openedAt > (strftime('%s','now')-14*86400)*1000
  AND p.fillStatus IN ('filled','unfilled')
  AND p.intentPrice IS NOT NULL
GROUP BY p.fillStatus
"""
for r in con.execute(q):
    print("fillStatus=%s  intent-entry=%s  avgIntent=%s  avgEntry=%s  n=%s" % r)

print()
# unfilled rows: how far did the market move away from the intent?
q2 = """
SELECT p.marketId, ROUND(p.intentPrice,3) intent, ROUND(p.entryPrice,3) entry,
       ROUND(p.simulatedPositionSize,2) sz,
       ROUND(p.currentPrice,3) cur
FROM PaperTrade p
WHERE p.botId='BANKROLL_200' AND p.isDemo=0 AND p.fillStatus='unfilled'
  AND p.openedAt > (strftime('%s','now')-14*86400)*1000
ORDER BY p.intentPrice - p.entryPrice DESC LIMIT 12
"""
print("unfilled sample (intent vs entry/cur):")
for r in con.execute(q2):
    m, intent, entry, sz, cur = r
    d = (intent - entry) if (intent is not None and entry is not None) else None
    print(f"  {m[:44]:44s} intent={intent} entry={entry} cur={cur} size={sz} delta={d}")
