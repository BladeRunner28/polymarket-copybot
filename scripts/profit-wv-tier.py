#!/usr/bin/env python3
"""Is the taker-rebate ladder a lever for this book, or a number we can never reach?

New external facts (2026-11-22):
  GLOBAL Polymarket  wV = TradeSize * (1 - entryPrice); tiers Gold 10% at $200k wV/30d,
                     Platinum 25% @ $1M, Diamond 40% @ $4M, Obsidian 50% @ $10M, Onyx 60% @ $75M.
  US Polymarket      API takers: coefficient 0.0695 with a 70% rebate on those fees
                     (= effective 0.02085), 2026-11-21 -> 2026-12-31 only.

So the question is arithmetic: what is our 30-day weighted volume, how far is it from the first
rung, and what would the rung actually pay per dollar at risk if we reached it?

Basis (same as profit-path-research.py unless stated):
  cost = PaperTrade.simulatedPositionSize (dollars at risk); isDemo=0; status != 'open';
  dedupe first leg per (botId, walletAddress, marketId, outcome); clock = openedAt (entry vintage).
Read-only (mode=ro). Prints only; writes nothing.
"""
import os
import re
import sqlite3
import collections
from datetime import datetime, timedelta, timezone

DB = os.path.join(os.path.dirname(__file__), "..", "prisma", "dev.db")

Q = """
WITH legs AS (
  SELECT botId, walletAddress, marketId, outcome, entryPrice, simulatedPositionSize,
         realizedPnl, fillStatus, openedAt
  FROM PaperTrade
  WHERE isDemo=0 AND status != 'open'
), dedup AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY botId, walletAddress, marketId, outcome
                               ORDER BY openedAt) rn FROM legs
)
SELECT * FROM dedup WHERE rn=1
"""

TIERS = [("None", 0, 0.0), ("Gold", 200_000, 0.10), ("Platinum", 1_000_000, 0.25),
         ("Diamond", 4_000_000, 0.40), ("Obsidian", 10_000_000, 0.50),
         ("Onyx", 75_000_000, 0.60)]


def ts(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def cat(mid):
    m = re.match(r"^([a-z0-9]+)", (mid or "").lower())
    return m.group(1) if m else "?"


# global fee rate table, docs.polymarket.com/trading/fees (2026-11-20 23:59 UTC)
RATE = {"ufc": .05, "nba": .05, "nfl": .05, "nhl": .05, "mlb": .05, "cfb": .05, "cbb": .05,
        "atp": .05, "wta": .05, "itf": .05, "fif": .05, "swe": .05, "ucl": .05, "ere": .05,
        "lec": .05, "lol": .05, "cs2": .05, "dota2": .05, "val": .05,
        "will": .05, "highest": .01, "lowest": .01, "elon": .01}


def rate(c):
    return RATE.get(c, .05)  # "Other / General" = 0.05 is the venue's catch-all


con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(Q)]
con.close()

now = max([ts(r["openedAt"]) for r in rows if ts(r["openedAt"])] or [datetime.now(timezone.utc)])
cut = now - timedelta(days=30)

# --- 1. 30-day weighted volume, all legs and the fill-confirmed subset -------------
def wv(sel):
    return sum((r["simulatedPositionSize"] or 0) * (1 - (r["entryPrice"] or 0)) for r in sel)

d30 = [r for r in rows if ts(r["openedAt"]) and ts(r["openedAt"]) >= cut]
f30 = [r for r in d30 if r["fillStatus"] == "filled"]
f_all = [r for r in rows if r["fillStatus"] == "filled"]

print(f"reference 'now' = {now.isoformat()}  (30d window opens {cut.date()})")
print(f"30d legs {len(d30):5d}  notional-at-risk ${sum(r['simulatedPositionSize'] or 0 for r in d30):9.2f}"
      f"  wV ${wv(d30):9.2f}")
print(f"30d FILLED  {len(f30):5d}  notional-at-risk ${sum(r['simulatedPositionSize'] or 0 for r in f30):9.2f}"
      f"  wV ${wv(f30):9.2f}")
print(f"all-time FILLED {len(f_all):4d}  wV ${wv(f_all):9.2f}")

best = max([(t[1], t[0], t[2]) for t in TIERS if wv(d30) >= t[1]])
rung, need = best[1], None
nxt = [(t[1], t[0], t[2]) for t in TIERS if wv(d30) < t[1]]
if nxt:
    need = nxt[0][0]
print(f"\nrung reached on 30d wV: {rung}  ->  next rung needs ${need or 0:,.0f}"
      f"  (gap ${(need or 0) - wv(d30):,.0f}; {100.0*wv(d30)/(need or 1):.2f}% of it)")

# --- 2. what a rung is worth per dollar at risk ----------------------------------
print("\nvalue of each rung on THIS book (rebate = share x fee; fee = rate*(1-p)):")
for name, floor, share in TIERS:
    if not share:
        continue
    # per-dollar-of-at-risk: fee = rate*(1-p) dollars per dollar at risk -> multiply by rebate share
    tot_fee = sum((r["simulatedPositionSize"] or 0) * rate(cat(r["marketId"])) *
                  (1 - (r["entryPrice"] or 0)) for r in f_all)
    cost = sum(r["simulatedPositionSize"] or 0 for r in f_all)
    fee_pp = 100.0 * tot_fee / cost
    print(f"  {name:9s} floor ${floor:>10,.0f}  rebate {int(share*100):2d}%  ->"
          f" {share*fee_pp:5.2f}pp of at-risk  (${share*tot_fee:7.2f} on the ${cost:,.0f} filled book)")

# --- 3. the US venue's API arm --------------------------------------------------
print("\nUS venue (QCX) API arm, effective 2026-11-21..12-31:")
coef, reb = 0.0695, 0.70
print(f"  gross coefficient {coef} -> net {coef*(1-reb):.5f} of (1-p) per dollar at risk")
for c in ("sports", "will", "other"):
    pass
us_pp = 100.0 * sum((r["simulatedPositionSize"] or 0) * coef * (1 - reb) * (1 - (r["entryPrice"] or 0))
                    for r in f_all) / max(1e-9, sum(r["simulatedPositionSize"] or 0 for r in f_all))
glob_pp = 100.0 * sum((r["simulatedPositionSize"] or 0) * rate(cat(r["marketId"])) *
                      (1 - (r["entryPrice"] or 0)) for r in f_all) / max(1e-9, sum(r["simulatedPositionSize"] or 0 for r in f_all))
cost = sum(r["simulatedPositionSize"] or 0 for r in f_all)
print(f"  on our filled book: global-live {glob_pp:.2f}pp (${cost*glob_pp/100:.2f}) vs US-API {us_pp:.2f}pp"
      f" (${cost*us_pp/100:.2f})  -> saves {glob_pp-us_pp:.2f}pp (${cost*(glob_pp-us_pp)/100:.2f})")
print("  note: program window ends 2026-12-31, i.e. two days before the 2027-01-02 go-live anchor.")

# --- 4. what the ladder would need to pay to matter ------------------------------
mean_1mp = (sum((r["simulatedPositionSize"] or 0) * (1 - (r["entryPrice"] or 0)) for r in f_all)
            / cost)
print("\nbreak-even check: the approved item 1 target is a >=5pp ROI gain from not crossing the spread.")
max_global = 0.60 * 0.05 * mean_1mp * 100        # Onyx share x highest global rate x mean (1-p)
max_us = 0.70 * 0.0695 * mean_1mp * 100          # US API arm: 70% of 0.0695
print(f"  mean (1-p) on the filled book = {mean_1mp:.3f}")
print(f"  best global rung (Onyx 60% of a 0.05 market) = {max_global:.2f}pp of at-risk")
print(f"  best anywhere right now (US API 70% of 0.0695) = {max_us:.2f}pp, expiring 2026-12-31")
print(f"  to clear 5pp at rate 0.05 you would need a {100*0.05/(0.05*mean_1mp):.0f}% rebate share -> impossible;"
      f" at the US gross 0.0695 you would need {100*0.05/(0.0695*mean_1mp):.0f}%")
print("  => no live rebate schedule in either venue can substitute for the execution gap.")

# --- 5. the ladder's incentive gradient points at the losing cell ----------------
print("\nwV earned per dollar at risk, and the ROI of that same cell (filled legs):")
bands = [("0.00-0.10", 0.0, 0.10), ("0.10-0.20", 0.10, 0.20), ("0.20-0.40", 0.20, 0.40),
         ("0.40-0.60", 0.40, 0.60), ("0.60-0.80", 0.60, 0.80), ("0.80-1.00", 0.80, 1.01)]
for name, lo, hi in bands:
    sel = [r for r in f_all if lo <= (r["entryPrice"] or 0) < hi]
    if not sel:
        continue
    c = sum(r["simulatedPositionSize"] or 0 for r in sel)
    p = sum(r["realizedPnl"] or 0 for r in sel)
    print(f"  px {name}  n={len(sel):3d}  wV per $ at risk {wv(sel)/c:.3f}  "
          f"|  ROI {100*p/c:7.1f}%")
print("  (wV = size x (1-p): the cheaper the ticket, the more rebate-tier credit per dollar —"
      "\n   i.e. the tier ladder pays most for exactly the class the approved cap removes.)")

# --- 6. does the ladder's own target volume even reach the first rung? ------------
print("\nscale test: at the C-200 ladder target of $5,000/day of dispatch, 30d size = $150,000;")
print(f"  at mean (1-p) {mean_1mp:.3f} that is wV ${150000*mean_1mp:,.0f} = "
      f"{100*150000*mean_1mp/200000:.0f}% of the Gold floor. Reaching Gold needs "
      f"${200000/(mean_1mp*30):,.0f}/day of dispatch")
print(f"  (current 30d wV ${wv(d30):,.0f} = {100*wv(d30)/200000:.2f}% of Gold; "
      f"current run-rate ${sum(r['simulatedPositionSize'] or 0 for r in d30)/30:,.0f}/day).")

