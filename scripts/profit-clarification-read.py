#!/usr/bin/env python3
"""Does a settlement clarification separate our winning legs from our losing ones?

Probe for the 2026-11-25 profit-research run. Polymarket published a keyless endpoint on
2026-11-25 (docs.polymarket.com/changelog.md):

    GET https://gamma-api.polymarket.com/market-clarifications
    "published clarifications, the notes that resolve ambiguity in how a market settles"

The question this answers: a clarification published AFTER we entered is a rules change we could
not have read at decision time. Is that class a loss source, large enough to price a gate?

Basis (identical to scripts/profit-path-research.py, so the cohorts reconcile with the daily read):
  cost   = PaperTrade.simulatedPositionSize  (dollars at risk, not notional)
  pnl    = realizedPnl, status IN ('closed','resolved')  (TR-15 OR)
  filter = isDemo=0
  dedupe = first leg per (botId, walletAddress, marketId, outcome)
  clock  = entry vintage (openedAt); a clarification is POST if its createdAt > openedAt
  CI     = market-clustered bootstrap (resample markets, 2,000 draws)

Join: PaperTrade.marketId -> conditionId (MarketSnapshot / ObservedTrade) -> gamma numeric market
id (/markets?condition_ids=..&closed=true) -> /market-clarifications?market_id=..

Read-only. Network caches under data/cache/ (delete to refresh). Writes nothing else.
"""
from __future__ import annotations

import collections
import datetime
import json
import os
import random
import sqlite3
import time
import urllib.parse
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(ROOT, "prisma", "dev.db")
CACHE_DIR = os.path.join(ROOT, "data", "cache")
GID_CACHE = os.path.join(CACHE_DIR, "gamma-condition-id-map.json")
CLAR_CACHE = os.path.join(CACHE_DIR, "gamma-market-clarifications.json")
GAMMA = "https://gamma-api.polymarket.com"

BASE = """
WITH legs AS (
  SELECT id, botId, walletAddress, marketId, outcome, entryPrice, realizedPnl,
         simulatedPositionSize, fillStatus, openedAt
  FROM PaperTrade
  WHERE isDemo=0 AND status IN ('closed','resolved') AND realizedPnl IS NOT NULL
), dedup AS (
  SELECT *, ROW_NUMBER() OVER (
      PARTITION BY botId, walletAddress, marketId, outcome ORDER BY openedAt) rn
  FROM legs
)
SELECT * FROM dedup WHERE rn=1
"""

QUESTION = {"will", "highest", "lowest", "elon"}
ESPORTS = {"cs2", "dota2", "lol", "lec", "val"}
SPORTS = {"ufc","atp","swe","fif","cbb","mlb","col","ucl","ere","unl","bel1","clf","us","bun",
          "itsb","por","lal","nhl","wta","crichundred","den","mls","itf","fl1","mex","bra",
          "elc","sea","fifwc","uel","arg","nfl","efl","wnba","cfb","epl","es2","scop","fr2","nba"}


def vertical(market_id):
    c = (market_id or "").lower().split("-")[0]
    if c in QUESTION: return "question"
    if c in ESPORTS: return "esports"
    if c in SPORTS: return "sports"
    return "other"


def iso(ms):
    return datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_json(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "profit-research/1.0"})
            with urllib.request.urlopen(req, timeout=30) as fh:
                return json.loads(fh.read().decode())
        except Exception as exc:                      # noqa: BLE001 - network, retried
            if i == tries - 1:
                print(f"  [warn] {url[:90]} … {exc}")
                return None
            time.sleep(1.5 * (i + 1))


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def cluster_ci(rows, iters=2000, seed=11):
    by = collections.defaultdict(list)
    for r in rows:
        by[r["marketId"]].append(r)
    keys = list(by)
    if len(keys) < 5:
        return None
    rng = random.Random(seed)
    out = []
    for _ in range(iters):
        cost = pnl = 0.0
        for _ in range(len(keys)):
            for r in by[keys[rng.randrange(len(keys))]]:
                cost += r["simulatedPositionSize"] or 0
                pnl += r["realizedPnl"] or 0
        if cost:
            out.append(100.0 * pnl / cost)
    out.sort()
    return [round(out[int(0.025 * len(out))], 1), round(out[int(0.975 * len(out))], 1)]


def stats(rows, k=3):
    n = len(rows)
    if not n:
        return {"n": 0}
    cost = sum(r["simulatedPositionSize"] or 0 for r in rows)
    pnl = sum(r["realizedPnl"] or 0 for r in rows)
    ordered = sorted((r["realizedPnl"] or 0 for r in rows), reverse=True)
    wins = [x for x in ordered if x > 0]
    losses = [x for x in ordered if x <= 0]
    aw = sum(wins) / len(wins) if wins else 0.0
    al = abs(sum(losses) / len(losses)) if losses else 0.0
    return {
        "n": n, "markets": len({r["marketId"] for r in rows}),
        "wallets": len({r["walletAddress"] for r in rows}),
        "cost": round(cost, 2), "pnl": round(pnl, 2),
        "roi": round(100.0 * pnl / cost, 1) if cost else None,
        "ex_topk_roi": round(100.0 * (sum(ordered[k:]) if n > k else 0.0) / cost, 1) if cost else None,
        "win_pct": round(100.0 * len(wins) / n, 1),
        "be_pct": round(100.0 * al / (aw + al), 1) if (aw + al) else None,
        "top": round(ordered[0], 2),
    }


def show(label, rows, k=3, ci=True):
    s: dict = dict(stats(rows, k))
    if not s["n"]:
        print(f"{label:30s} n=0")
        return s
    s["ci"] = cluster_ci(rows) if ci else None
    print(f"{label:30s} n={s['n']:5d} mkts={s['markets']:5d} cost=${s['cost']:9.0f} "
          f"pnl={s['pnl']:+9.0f} roi={s['roi']:+7.1f}% ex-top{k}={s['ex_topk_roi']:+7.1f}% "
          f"win={s['win_pct']:5.1f}% be={s['be_pct'] or 0:4.1f}% CI {s['ci']}")
    return s


def load_legs():
    con = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    legs = [dict(r) for r in con.execute(BASE)]
    mids = sorted({r["marketId"] for r in legs if r["marketId"]})
    cond = {}
    for ch in chunks(mids, 400):
        q = ("SELECT marketId, MAX(conditionId) FROM ObservedTrade WHERE conditionId IS NOT NULL "
             "AND marketId IN (%s) GROUP BY marketId" % ",".join("?" * len(ch)))
        cond.update({a: b for a, b in con.execute(q, ch)})
        q2 = ("SELECT marketId, MAX(conditionId) FROM MarketSnapshot WHERE conditionId IS NOT NULL "
              "AND marketId IN (%s) GROUP BY marketId" % ",".join("?" * len(ch)))
        for a, b in con.execute(q2, ch):
            cond.setdefault(a, b)
    con.close()
    return legs, mids, cond


def main():
    os.makedirs(CACHE_DIR, exist_ok=True)
    legs, mids, cond = load_legs()
    print(f"settled deduped legs: {len(legs)}   distinct markets: {len(mids)}   "
          f"conditionIds: {len(cond)}")

    gid = json.load(open(GID_CACHE)) if os.path.exists(GID_CACHE) else {}
    todo = [c for c in cond.values() if c not in gid]
    print(f"gamma market id lookups: {len(todo)}")
    for i, ch in enumerate(chunks(todo, 40)):
        url = GAMMA + "/markets?" + urllib.parse.urlencode(
            [("condition_ids", c) for c in ch] + [("closed", "true"), ("limit", "200")])
        for m in (http_json(url) or []):
            if m.get("conditionId"):
                gid[m["conditionId"]] = str(m.get("id"))
        if i % 25 == 0:
            json.dump(gid, open(GID_CACHE, "w"))
        time.sleep(0.1)
    json.dump(gid, open(GID_CACHE, "w"))

    gids = sorted({gid[c] for c in cond.values() if c in gid})
    clar = json.load(open(CLAR_CACHE)) if os.path.exists(CLAR_CACHE) else {}
    todo = [g for g in gids if g not in clar]
    print(f"markets resolved: {len(gids)}   clarification lookups: {len(todo)}")
    for i, ch in enumerate(chunks(todo, 40)):
        url = GAMMA + "/market-clarifications?" + urllib.parse.urlencode(
            [("market_id", g) for g in ch] + [("limit", "100")])
        got = collections.defaultdict(list)
        for row in (http_json(url) or []):
            got[str(row.get("marketId"))].append({
                "createdAt": row.get("createdAt"), "clearBook": row.get("clearBook"),
                "content": (row.get("content") or "")})
        for g in ch:
            clar[g] = got.get(g, [])
        if i % 25 == 0:
            json.dump(clar, open(CLAR_CACHE, "w"))
        time.sleep(0.1)
    json.dump(clar, open(CLAR_CACHE, "w"))

    for r in legs:
        g = gid.get(cond.get(r["marketId"], ""))
        rows = clar.get(g, []) if g else []
        r["_gid"] = g
        r["_nclar"] = len(rows)
        r["_post"] = None
        r["_clear"] = None
        if rows:
            first = min(rows, key=lambda x: x["createdAt"] or "")
            r["_post"] = (first["createdAt"] or "") > iso(r["openedAt"])
            r["_clear"] = bool(first.get("clearBook"))

    # content taxonomy over everything pulled: is this flag "dispute" or "rules copyedit"?
    texts = [x for rows in clar.values() for x in rows]
    boiler = sum(1 for x in texts if "rules have been updated for clarity" in
                 (x.get("content") or "").lower())
    clear = sum(1 for x in texts if x.get("clearBook"))
    print(f"\nclarification rows pulled {len(texts)} | clearBook {clear} "
          f"({100.0 * clear / max(len(texts), 1):.1f}%) | "
          f"'updated for clarity' boilerplate {boiler} ({100.0 * boiler / max(len(texts), 1):.1f}%)")

    print("\n=== A. CLARIFICATION EXPOSURE, all settled deduped (both lanes) ===")
    show("all settled", legs)
    show("has any clarification", [r for r in legs if r["_nclar"]])
    show("no clarification", [r for r in legs if not r["_nclar"] and r["_gid"]])
    show("no gamma id (unmapped)", [r for r in legs if not r["_gid"]])
    show("clarification AFTER entry", [r for r in legs if r["_post"]])
    show("clarification BEFORE entry", [r for r in legs if r["_post"] is False])
    show("post-entry & clearBook", [r for r in legs if r["_post"] and r["_clear"]])

    print("\n=== B. BY VERTICAL ===")
    for v in ("question", "sports", "esports", "other"):
        sub = [r for r in legs if vertical(r["marketId"]) == v]
        show(f"{v}: all", sub)
        show(f"{v}: clarified", [r for r in sub if r["_nclar"]])
        show(f"{v}: post-entry clar", [r for r in sub if r["_post"]])

    print("\n=== C. FILL-CONFIRMED (as stamped) ===")
    filled = [r for r in legs if r["fillStatus"] == "filled"]
    show("filled all", filled)
    show("filled clarified", [r for r in filled if r["_nclar"]], ci=False)
    show("filled not clarified", [r for r in filled if not r["_nclar"] and r["_gid"]])

    print("\n=== D. WHERE THE CLARIFIED PnL COMES FROM ===")
    tot = sum(r["realizedPnl"] or 0 for r in legs if r["_gid"])
    oncl = sum(r["realizedPnl"] or 0 for r in legs if r["_nclar"])
    print(f"booked PnL on clarified markets ${oncl:,.0f} of ${tot:,.0f} "
          f"({100.0 * oncl / tot if tot else 0:.1f}%)")
    fam = collections.Counter(r["marketId"].split("-")[0] for r in legs if r["_post"])
    print("post-entry clarification legs by family token:", fam.most_common(8))
    for r in sorted([r for r in legs if r["_post"]], key=lambda x: -(x["realizedPnl"] or 0))[:5]:
        print(f"   {iso(r['openedAt'])[:10]} {r['botId'][:12]:12s} {r['marketId'][:52]:52s} "
              f"{r['outcome'][:6]:6s} {r['entryPrice']:<8} ${r['simulatedPositionSize']:.2f} "
              f"{r['realizedPnl']:+.2f}")
    print("\nre-run: python3 scripts/profit-clarification-read.py   "
          "(delete data/cache/gamma-*.json to refresh the venue side)")


if __name__ == "__main__":
    main()
