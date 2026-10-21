"""Gate probe for card paper-trader-archived-fee-reprice.

DECISION RULE (pre-registered, user-approved 2026-10-21): adopt `fd` as the fee
input only if it resolves >=90% of conditionIds AND re-pricing moves aggregate fee
>=$25 or flips a leg's net PnL sign. If coverage is <90% the field is not a usable
source and the card closes with that null.

This script measures COVERAGE ONLY (read-only, keyless). It answers: does CLOB
/markets/<conditionId> expose a usable `fd` for ARCHIVED markets, and what shape
does it take?
"""
import json
import random
import sqlite3
import time
import urllib.error
import urllib.request

DB = "/Users/xsnyde2/polymarket-copybot/prisma/dev.db"
CLOB = "https://clob.polymarket.com/markets/"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
# Archived = finished legs. Dedupe to distinct markets.
# PaperTrade.marketId is a LOCAL slug (and demo rows use "demo-market-*"), NOT a
# conditionId -- calling CLOB /markets/<marketId> 404s on 57/60. The real key is
# ObservedTrade.conditionId, reached through DecisionJournal.
rows = con.execute("""
SELECT DISTINCT o.conditionId AS cid
FROM PaperTrade p
JOIN DecisionJournal d ON d.id = p.decisionJournalId
JOIN ObservedTrade o ON o.id = d.observedTradeId
WHERE (p.resolvedAt IS NOT NULL OR p.closedAt IS NOT NULL)
  AND p.isDemo = 0
  AND o.conditionId IS NOT NULL AND o.conditionId != ''
""").fetchall()
ids = [r["cid"] for r in rows]
print("distinct finished markets in DB: %d" % len(ids))
random.seed(21)
sample = random.sample(ids, min(60, len(ids)))
print("sampling %d for the coverage gate\n" % len(sample))

ok = miss = err = 0
fd_present = []
shapes = {}
t0 = time.time()
for i, cid in enumerate(sample, 1):
    url = CLOB + cid
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "copybot-fee-probe/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode())
        ok += 1
        has = "fd" in d
        val = d.get("fd")
        if has and val not in (None, {}, "", 0):
            fd_present.append((cid, val))
            shapes[json.dumps(val, sort_keys=True)[:80]] = shapes.get(json.dumps(val, sort_keys=True)[:80], 0) + 1
        elif not has:
            miss += 1
        else:
            miss += 1
            shapes.setdefault("fd present but empty: %r" % (val,), 0)
            shapes["fd present but empty: %r" % (val,)] += 1
    except urllib.error.HTTPError as e:
        err += 1
        shapes["HTTP %s" % e.code] = shapes.get("HTTP %s" % e.code, 0) + 1
    except Exception:
        err += 1
    if i % 15 == 0:
        print("  %d/%d  resolved=%d  no-fd=%d  err=%d" % (i, len(sample), len(fd_present), miss, err))

print("\nelapsed %.1fs" % (time.time() - t0))
print("rows fetched OK      : %d / %d" % (ok, len(sample)))
print("fd usable (non-empty): %d / %d  = %.1f%%" % (len(fd_present), len(sample), 100.0 * len(fd_present) / max(len(sample), 1)))
print("no usable fd         : %d" % miss)
print("fetch errors         : %d" % err)
print("\nshapes seen:")
for k, v in sorted(shapes.items(), key=lambda kv: -kv[1])[:8]:
    print("  %-70s x%d" % (k, v))
if fd_present:
    print("\nsample fd values:")
    for cid, val in fd_present[:5]:
        print("  %s -> %s" % (cid[:20], json.dumps(val)[:110]))
cov = 100.0 * len(fd_present) / max(len(sample), 1)
print("\nGATE: coverage %.1f%% vs required 90%% -> %s" % (cov, "PASS (proceed to re-pricing)" if cov >= 90 else "FAIL (close card with this null)"))
