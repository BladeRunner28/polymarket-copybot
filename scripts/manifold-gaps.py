#!/usr/bin/env python3
"""
Manifold gap detector (Phase Data-1, SHADOW ONLY).

Cross-platform probability gap detection: for the most liquid active
Polymarket markets (from MarketSnapshot), search Manifold Markets (keyless
API) for the same question and log probability gaps > threshold.

The gap is a relative-value signal: if Polymarket says 0.48 and Manifold says
0.55 on the same question, at least one venue is mispriced. Shadow-only — logs
to data/manifold-gaps.jsonl; nothing touches the live pipeline.

Usage:
  python3 scripts/manifold-gaps.py                # scan + append new pairs
  python3 scripts/manifold-gaps.py --limit 50     # fewer markets (faster)
"""
import argparse
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "manifold-gaps.jsonl")
DB = os.path.join(ROOT, "prisma", "dev.db")

API = "https://api.manifold.markets"
GAP_THRESHOLD = 0.10      # log pairs with |gap| >= 10pp
MIN_LIQUIDITY = 500       # only markets with real depth
TOP_MARKETS = 200         # how many Polymarket markets to attempt
DELAY_S = 0.5             # polite rate limit (keyless)

STOPWORDS = set("""
a an and are as at be but by for from has have if in into is it its of on or
that the their this to was were will with what when where which who whom why
how over under vs versus and or not no do does did will would should can
total pts point points game match day week month year 2025 2026 2027 2028
""".split())


def tokenize(q: str) -> list[str]:
    toks = re.findall(r"[a-z0-9']+", q.lower())
    return [t for t in toks if t not in STOPWORDS and len(t) > 2]


def get_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def latest_pm_markets(limit: int):
    """Latest MarketSnapshot per marketId, liquidity-filtered, from SQLite (RO)."""
    uri = "file:{}?mode=ro".format(DB)
    con = sqlite3.connect(uri, uri=True)
    con.execute("PRAGMA busy_timeout=8000")
    rows = con.execute(
        """
        SELECT m.marketId, m.question, m.yesPrice, m.liquidity
        FROM MarketSnapshot m
        JOIN (SELECT marketId, MAX(collectedAt) AS mx FROM MarketSnapshot GROUP BY marketId) latest
          ON latest.marketId = m.marketId AND latest.mx = m.collectedAt
        WHERE m.liquidity >= ? AND m.question != '' AND m.question IS NOT NULL
          AND m.question NOT LIKE '[DEMO]%' AND m.isDemo = 0
          AND latest.mx >= ?  -- snapshot fresh = market still monitored/active
        ORDER BY m.liquidity DESC
        LIMIT ?
        """,
        (MIN_LIQUIDITY, int(time.time() * 1000) - 24 * 3600 * 1000, limit),
    ).fetchall()
    con.close()
    return [{"marketId": r[0], "question": r[1], "yesPrice": r[2], "liquidity": r[3]} for r in rows]


def similarity(qtoks: list[str], mtoks: list[str]) -> float:
    if not qtoks or not mtoks:
        return 0.0
    inter = len(set(qtoks) & set(mtoks))
    return inter / max(1, min(len(set(qtoks)), len(set(mtoks))))


def existing_pairs():
    """(pmMarketId, manifoldId) already logged — dedupe across runs."""
    pairs = set()
    if os.path.exists(OUT):
        with open(OUT) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        r = json.loads(line)
                        pairs.add((r["pmMarketId"], r["manifoldId"]))
                    except Exception:
                        pass
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=TOP_MARKETS)
    ap.add_argument("--gap", type=float, default=GAP_THRESHOLD)
    ap.add_argument("--force", action="store_true", help="re-log pairs already seen")
    args = ap.parse_args()

    markets = latest_pm_markets(args.limit)
    print(f"Polymarket candidates: {len(markets)} (liquidity ≥ ${MIN_LIQUIDITY}, snapshot fresh)")
    if not markets:
        print("No markets found — is prisma/dev.db populated?")
        return

    seen = set() if args.force else existing_pairs()
    found = 0
    rows = []
    for m in markets:
        qtoks = tokenize(m["question"])
        if len(qtoks) < 3:
            continue
        query = " ".join(qtoks[:5])
        try:
            res = get_json(f"{API}/v0/search-markets?term={urllib.parse.quote(query)}&limit=5&filter=open")
        except Exception as e:
            print(f"  search error: {e}")
            time.sleep(1.0)
            continue
        best = None
        for cand in res if isinstance(res, list) else []:
            if cand.get("outcomeType") != "BINARY":
                continue
            mtoks = tokenize(cand.get("question", ""))
            sim = similarity(qtoks, mtoks)
            if sim >= 0.5 and (best is None or sim > best[0]):
                best = (sim, cand)
        time.sleep(DELAY_S)
        if not best:
            continue
        sim, cand = best
        mp = cand.get("probability")
        if mp is None or m["yesPrice"] is None:
            continue
        gap = mp - m["yesPrice"]
        if abs(gap) < args.gap:
            continue
        key = (m["marketId"], cand["id"])
        if key in seen:
            continue
        seen.add(key)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pmMarketId": m["marketId"],
            "pmQuestion": m["question"][:160],
            "pmProb": round(m["yesPrice"], 3),
            "manifoldId": cand["id"],
            "manifoldQuestion": cand.get("question", "")[:160],
            "manifoldProb": round(mp, 3),
            "gap": round(gap, 3),
            "similarity": round(sim, 2),
            "pmLiquidity": m["liquidity"],
        }
        rows.append(row)
        found += 1
        print(f"  GAP {gap:+.3f}  sim={sim:.2f}  | {m['question'][:60]}…")

    if rows:
        with open(OUT, "a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    print(f"\nLogged {found} new gap pair(s) -> {OUT}")


if __name__ == "__main__":
    main()
