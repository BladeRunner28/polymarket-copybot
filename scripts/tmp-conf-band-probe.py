import sqlite3

con = sqlite3.connect("prisma/dev.db")

# Resolution proxy: latest settled PaperTrade per (marketId,outcome) carries currentPrice 0/1
con.execute("""
CREATE TEMP TABLE res AS
SELECT marketId, outcome, currentPrice AS res
FROM PaperTrade p
WHERE botId='BANKROLL_200' AND isDemo=0
  AND status IN ('closed','resolved')
  AND currentPrice IN (0.0,1.0)
  AND openedAt = (SELECT MAX(openedAt) FROM PaperTrade q
                  WHERE q.marketId=p.marketId AND q.outcome=p.outcome
                    AND q.botId='BANKROLL_200' AND q.isDemo=0
                    AND q.status IN ('closed','resolved') AND q.currentPrice IN (0.0,1.0))
GROUP BY marketId, outcome
""")

q = """
SELECT dj.createdAt, ot.marketId, ot.outcome, ot.walletEntryPrice probed, r.res
FROM DecisionJournal dj
JOIN ObservedTrade ot ON ot.id = dj.observedTradeId
JOIN res r ON r.marketId = ot.marketId AND r.outcome = ot.outcome
WHERE dj.isDemo=0 AND dj.decision='skip'
  AND dj.copyScore >= 80
  AND dj.confidence >= 0.50 AND dj.confidence < 0.70
  AND ot.walletEntryPrice < 0.20
"""
rows = con.execute(q).fetchall()
stake = 10.0
pnl = 0.0
wins = 0
n = 0
for ts, m, o, px, res in rows:
    if px is None or px <= 0 or px >= 1:
        continue
    n += 1
    if res == 1.0:
        wins += 1
        pnl += stake * (1.0 / px - 1.0)
    else:
        pnl -= stake
print(f"counterfactual: conf 0.50-0.70, copyScore>=80, entry<0.20, priced n={n}")
if n:
    print(f"  wins={wins} ({wins/n*100:.1f}%)  implied={sum(r[3] for r in rows if r[3])/max(n,1)*100:.1f}%")
    print(f"  hypothetical PnL on ${stake:.0f} tickets = {pnl:+.2f}  -> ROI {pnl/(n*stake)*100:+.1f}%")
    print(f"  avg PnL/trade {pnl/n:+.2f}")
