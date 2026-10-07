"""Does RETRIEVAL over our own resolved corpus add anything beyond the price?

Read-only. Answers the recurring ask "does a RAG pipeline improve anything for us" with our own legs
instead of a vendor's benchmark: a retrieval layer over the corpus would return, for a new leg, the
outcome base rate of legs that look like it (price bucket x category x wallet). That is measured here
against the price arm on the same held-out rows.

Verdict as of 2026-10-06 (2,910 resolved legs, 70/30 time-ordered split): NO. Price (detection mid)
Brier 0.2165 / AUC 0.7132 out of sample; per-price-decile base rate 0.2607 / 0.6221, +category
0.2595 / 0.6253, +wallet 0.2650 / 0.6613. The corpus's own base rates are non-stationary (75.7%
train-period win rate vs 52.9% out of sample) while the price is not.

Two caveats the numbers must travel with:
  * the label is `resolvedAt IS NOT NULL AND realizedPnl > 0`, and natural-resolution rows are
    winner-skewed because losers get closed early (printed as the survivorship block below), so the
    ABSOLUTE levels are not the book's true edge - the arm-to-arm comparison on identical rows is.
  * wallet/index dimensions are thin out of sample (282 of 874 test legs had an unseen
    (decile, wallet) key and fell back to the base rate), which is the real cost of retrieval.

Run: python3 scripts/rag-vs-price-baseline.py
"""

import sqlite3
import math

DB = "prisma/dev.db"
TEST_FRACTION = 0.30


def load():
    con = sqlite3.connect(DB)
    q = """
    SELECT p.openedAt, p.entryPrice, o.detectedPrice, o.marketCategoryFine,
           o.marketCategoryClass, p.walletAddress, p.realizedPnl, p.botId
    FROM PaperTrade p
    JOIN DecisionJournal d ON d.id = p.decisionJournalId
    JOIN ObservedTrade o ON o.id = d.observedTradeId
    WHERE p.isDemo = 0 AND p.resolvedAt IS NOT NULL AND p.realizedPnl IS NOT NULL
    ORDER BY p.openedAt ASC
    """
    rows = []
    for opened, entry, mid, cat_fine, cat_cls, wallet, pnl, bot in con.execute(q):
        cat = cat_fine or cat_cls or "unknown"
        price = mid if mid is not None else entry
        rows.append(
            {
                "t": opened,
                "entry": entry,
                "mid": price,
                "cat": str(cat).lower(),
                "wallet": wallet,
                "won": 1 if pnl > 0 else 0,
                "bot": bot,
            }
        )
    return rows


def brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ys)


def auc(ps, ys):
    pairs = sorted(zip(ps, ys))
    # rank-based AUC with tie handling
    ranks = []
    i = 0
    r = 1
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg = (r + (r + (j - i))) / 2
        for _ in range(i, j + 1):
            ranks.append(avg)
        r += j - i + 1
        i = j + 1
    pos = [rk for rk, (_, y) in zip(ranks, pairs) if y == 1]
    neg = [rk for rk, (_, y) in zip(ranks, pairs) if y == 0]
    if not pos or not neg:
        return None
    return (sum(pos) / len(pos) - (len(pos) + 1) / 2) / len(neg)


def decile(p, edges):
    for i, e in enumerate(edges):
        if p <= e:
            return i
    return len(edges) - 1


def bucket_arm(train, test, keys, priors=(2.0, 0.5)):
    """Freeze per-bucket win rates on train (Laplace-smoothed toward the train base rate)."""
    base = sum(r["won"] for r in train) / len(train)
    alpha, beta = priors
    table = {}
    for r in train:
        k = tuple(r[f] for f in keys)
        w, n = table.get(k, (0.0, 0))
        table[k] = (w + r["won"], n + 1)
    out = []
    for r in test:
        k = tuple(r[f] for f in keys)
        w, n = table.get(k, (0.0, 0))
        out.append((w + alpha * base) / (n + alpha + beta - 1) if n else base)
    return out


rows = load()
n = len(rows)
cut = int(n * (1 - TEST_FRACTION))
train, test = rows[:cut], rows[cut:]
print(f"resolved legs n={n}  train={len(train)}  test={len(test)}")
print(f"test window: {test[0]['t']} -> {test[-1]['t']}")
print(f"test base win rate {sum(r['won'] for r in test)/len(test):.4f}  (train {sum(r['won'] for r in train)/len(train):.4f})")

ys = [r["won"] for r in test]
edges = [0.1 * i for i in range(1, 10)]

arms = {
    "price_mid (detectedPrice)": [r["mid"] for r in test],
    "price_booked (entryPrice)": [r["entry"] for r in test],
}
# price-decile base rate, the cheapest 'retrieval over our own corpus' artifact
for r in rows:
    r["dec"] = decile(r["mid"], edges)
train_base = sum(r["won"] for r in train) / len(train)
tbl = {}
for r in train:
    w, c = tbl.get(r["dec"], (0, 0))
    tbl[r["dec"]] = (w + r["won"], c + 1)
arms["bucket_price (decile base rate)"] = [((tbl.get(r["dec"], (0, 0))[0] + 2 * train_base) / (tbl.get(r["dec"], (0, 0))[1] + 3)) if tbl.get(r["dec"]) else train_base for r in test]
arms["bucket_cat (decile x category)"] = bucket_arm(train, test, ["dec", "cat"])
arms["bucket_wal (decile x wallet)"] = bucket_arm(train, test, ["dec", "wallet"])
# the retrieval arm's deck is mostly one wallet; show how thin the test buckets are
seen = {}
for r in test:
    seen.setdefault((r["dec"], r["wallet"]), 0)
    seen[(r["dec"], r["wallet"])] += 1
print(f"\nthin-bucket check: test legs whose (decile,wallet) key was unseen in train = "
      f"{sum(1 for r in test if (r['dec'], r['wallet']) not in {tuple(x[f] for f in ('dec','wallet')) for x in train})}/{len(test)}")

print(f"\n{'arm':34s} {'n':>5s} {'Brier':>8s} {'AUC':>7s}")
for name, ps in arms.items():
    print(f"{name:34s} {len(ps):5d} {brier(ps, ys):8.4f} {('%.4f' % auc(ps, ys)) if auc(ps, ys) is not None else '   n/a':>7s}")

bm = brier(arms["price_mid (detectedPrice)"], ys)
bb = brier(arms["price_booked (entryPrice)"], ys)
print("\ndelta vs price_mid (positive = retrieval is WORSE):")
for name, ps in arms.items():
    if name.startswith("price"):
        continue
    print(f"  {name:32s} {brier(ps, ys) - bm:+.4f}")
# calibration of the price arm itself, per decile (is price already the base rate?)
print("\nper-decile base rate in the FULL sample (price is a discretized base rate):")
for d in range(10):
    sub = [r for r in rows if r["dec"] == d]
    if not sub:
        continue
    prices = [r["mid"] for r in sub]
    print(f"  decile {d}  n={len(sub):5d}  mean price {sum(prices)/len(prices):.3f}  "
          f"win rate {sum(r['won'] for r in sub)/len(sub):.3f}")

# ---- survivorship block: what the label above is missing ----

con=sqlite3.connect("prisma/dev.db")
# 1) survivorship: closed (early exit) vs resolved (natural) win rates, by lane
q = """SELECT p.botId,
   SUM(CASE WHEN p.resolvedAt IS NOT NULL THEN 1 ELSE 0 END) resolved,
   SUM(CASE WHEN p.closedAt IS NOT NULL AND p.resolvedAt IS NULL THEN 1 ELSE 0 END) closed_only,
   SUM(CASE WHEN p.resolvedAt IS NOT NULL AND p.realizedPnl>0 THEN 1 ELSE 0 END) res_wins,
   SUM(CASE WHEN p.closedAt IS NOT NULL AND p.resolvedAt IS NULL AND p.realizedPnl>0 THEN 1 ELSE 0 END) clo_wins,
   SUM(CASE WHEN p.resolvedAt IS NOT NULL AND p.realizedPnl IS NULL THEN 1 ELSE 0 END) res_noPnL
   FROM PaperTrade p WHERE p.isDemo=0 GROUP BY p.botId"""
for r in con.execute(q):
    bot,res,clo,rw,cw,rnp = r
    print(f"{bot:10s} resolved={res:5d} (wins {rw}, pnl-null {rnp})  closed-only={clo:5d} (wins {cw})")
# 2) price-arm AUC by lane on ALL finished legs (not just resolved) using realizedPnl sign, point-in-time mid
def auc(ps,ys):
    pairs=sorted(zip(ps,ys)); ranks=[]; i=0; r=1
    while i<len(pairs):
        j=i
        while j+1<len(pairs) and pairs[j+1][0]==pairs[i][0]: j+=1
        avg=(r+(r+(j-i)))/2
        for _ in range(i,j+1): ranks.append(avg)
        r+=j-i+1; i=j+1
    pos=[k for k,(_,y) in zip(ranks,pairs) if y==1]; neg=[k for k,(_,y) in zip(ranks,pairs) if y==0]
    if not pos or not neg: return None
    return (sum(pos)/len(pos)-(len(pos)+1)/2)/len(neg)
def brier(ps,ys): return sum((p-y)**2 for p,y in zip(ps,ys))/len(ys)
q2="""SELECT p.botId, o.detectedPrice, p.entryPrice, p.realizedPnl
 FROM PaperTrade p JOIN DecisionJournal d ON d.id=p.decisionJournalId
 JOIN ObservedTrade o ON o.id=d.observedTradeId
 WHERE p.isDemo=0 AND p.realizedPnl IS NOT NULL AND p.resolvedAt IS NOT NULL"""
from collections import defaultdict
by=defaultdict(list)
for bot,mid,entry,pnl in con.execute(q2):
    by[bot].append((mid if mid is not None else entry, 1 if pnl>0 else 0))
print()
for bot,rows in by.items():
    ps=[p for p,_ in rows]; ys=[y for _,y in rows]
    print(f"{bot:10s} n={len(rows):5d}  price-mid Brier={brier(ps,ys):.4f}  AUC={auc(ps,ys):.4f}  base win {sum(ys)/len(ys):.3f}")