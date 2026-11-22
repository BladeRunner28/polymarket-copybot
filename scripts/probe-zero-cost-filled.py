#!/usr/bin/env python3
"""Three fill-confirmed legs fell out of every clip bucket in profit-path-research (299 of 302).
What are they? cost = simulatedPositionSize; a filled leg at $0 at risk is either a data defect
or a zero-size dispatch, and either way it silently moves the aggregate ROI.

Read-only (mode=ro). Prints only.
"""
import os
import sqlite3

DB = os.path.join(os.path.dirname(__file__), "..", "prisma", "dev.db")
q = """
WITH legs AS (
  SELECT id, botId, walletAddress, marketId, outcome, entryPrice, realizedPnl,
         simulatedPositionSize, fillStatus, fillBasis, fillResolvedAt, openedAt, closedAt, resolvedAt,
         intentPrice, status
  FROM PaperTrade
  WHERE isDemo=0 AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL
    AND fillStatus='filled'
), dedup AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY botId, walletAddress, marketId, outcome
                               ORDER BY openedAt) rn FROM legs
)
SELECT * FROM dedup WHERE rn=1
"""
con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(q)]
con.close()

print(f"filled deduped legs: {len(rows)}  cost=${sum(r['simulatedPositionSize'] or 0 for r in rows):.2f}  "
      f"pnl=${sum(r['realizedPnl'] or 0 for r in rows):.2f}")
zero = [r for r in rows if not (r["simulatedPositionSize"] or 0) > 0]
print(f"filled legs with cost<=0: {len(zero)}  pnl=${sum(r['realizedPnl'] or 0 for r in zero):.2f}")
for r in zero:
    print("  ", {k: r[k] for k in ("id", "botId", "marketId", "outcome", "entryPrice", "intentPrice",
                                   "simulatedPositionSize", "realizedPnl", "openedAt", "closedAt")})

allcost = sum(r["simulatedPositionSize"] or 0 for r in rows)
allpnl = sum(r["realizedPnl"] or 0 for r in rows)
print(f"ROI incl zero-cost: {100*allpnl/allcost:.1f}%   "
      f"ROI ex zero-cost: {100*sum(r['realizedPnl'] or 0 for r in rows if (r['simulatedPositionSize'] or 0)>0)/allcost:.1f}%")
