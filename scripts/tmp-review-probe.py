import json, sqlite3
con = sqlite3.connect('/Users/xsnyde2/polymarket-copybot/prisma/dev.db')
cur = con.cursor()
rs = cur.execute("SELECT rulesJson FROM RuleSet WHERE version=71").fetchone()[0]
d = json.loads(rs)
print("--- key fields (RuleSet v71) ---")
for k in ['c200BandSizeFactor','c200BandSizeFactorRange','maxWalletNotionalPctOfCap','maxGrossExposureUsd','minConfidence','minCopyScore','kellyEnabled','maxEntryPrice','c200MaxEntryPrice']:
    print(k, '=', json.dumps(d.get(k)))
print("--- hour/band/cap/entry/kelly keys ---")
for k, v in sorted(d.items()):
    if any(s in k.lower() for s in ('hour','blackout','band','cap','expos','entry','kelly')):
        print(k, '=', json.dumps(v)[:150])

print()
print("--- recent closed/resolved C200 legs by local day ---")
q = """SELECT date((COALESCE(closedAt,resolvedAt)/1000)-21600,'unixepoch') d, status, COUNT(*) n,
ROUND(SUM(realizedPnl),2) pnl, MIN(datetime((COALESCE(closedAt,resolvedAt)/1000),'unixepoch')) first_close
FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND status IN ('closed','resolved')
AND (COALESCE(closedAt,resolvedAt)/1000) > strftime('%s','2026-11-01')-86400
GROUP BY d,status ORDER BY d DESC;"""
for r in cur.execute(q):
    print(r)

print()
print("--- open C200 legs ---")
for r in cur.execute("""SELECT datetime(openedAt/1000,'unixepoch') o, COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) size
FROM PaperTrade WHERE botId='BANKROLL_200' AND status='open' AND isDemo=0 GROUP BY o ORDER BY o DESC LIMIT 10;"""):
    print(r)

print()
print("--- C200 legs opened last 7 days ---")
for r in cur.execute("""SELECT date((openedAt/1000)-21600,'unixepoch') d, COUNT(*) n, ROUND(SUM(simulatedPositionSize),2) size
FROM PaperTrade WHERE botId='BANKROLL_200' AND isDemo=0 AND openedAt/1000 > strftime('%s','2026-10-29')
GROUP BY d ORDER BY d DESC;"""):
    print(r)
