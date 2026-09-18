#!/usr/bin/env python3
"""Kalshi coverage probe — does a Kalshi counterpart even EXIST for our markets?

The 2026-09-17 daily report asked for a revive-or-park call on the cross-venue
lane. Its shadow book says "verified cross-listings = 0 (0%)" and calls matcher
coverage the binding constraint — but before funding a better matcher we need the
CEILING: how many of our C-200 markets have a Kalshi listing at all? If the answer
is ~0, the matcher is not the constraint and the honest call is to park the lane.

Method: pull every OPEN Kalshi market (keyless trade-api v2, cursor-paged), index
its title/subtitle/ticker tokens, then score our in-window C-200 questions against
it with a deliberately STRICTER-than-sidecar matcher:
  - Jaccard overlap over content tokens (numbers/entities preserved), not
    overlap/min(len) — the loose denominator is what let "Will Bursaspor win on
    2026-09-13?" match a Texas election event at 0.67.
  - a match must ALSO share a distinctive token (len >= 5, not a stopword).
Reports the score distribution and the best candidates for eyeball verification.

Usage: python3 scripts/kalshi-coverage-probe.py [--days 7] [--pages 30] [--top 15]
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
OUT = os.path.join(ROOT, "data", "kalshi-coverage-probe.json")
BASE = "https://api.elections.kalshi.com/trade-api/v2"

STOP = {
    "will", "the", "a", "an", "of", "in", "on", "at", "by", "to", "for", "be",
    "is", "are", "was", "were", "and", "or", "if", "than", "then", "this", "that",
    "with", "from", "as", "it", "its", "any", "all", "no", "not", "yes", "win",
    "wins", "winning", "finish", "finished", "game", "market", "marketclose",
    "close", "day", "week", "month", "year", "2024", "2025", "2026", "2027",
    "before", "after", "during", "above", "below", "more", "less", "most",
    "least", "atleast", "most", "end", "ends", "over", "under", "between",
    "reach", "hit", "exceed", "exceeds", "greater", "higher", "lower",
}

# Month names fold into numbers so "September 17" and "SEP17" agree.
MONTHS = {
    "jan": "01", "january": "01", "feb": "02", "february": "02", "mar": "03", "march": "03",
    "apr": "04", "april": "04", "may": "05", "jun": "06", "june": "06", "jul": "07", "july": "07",
    "aug": "08", "august": "08", "sep": "09", "september": "09", "oct": "10", "october": "10",
    "nov": "11", "november": "11", "dec": "12", "december": "12",
}


def tokens(text: str) -> set[str]:
    text = (text or "").lower()
    # fold "september 17" / "sep17" / "09-17" into a common ordinal token
    for name, num in MONTHS.items():
        text = re.sub(rf"\b{name}\s*([0-3]?\d)\b", f"{num}-\\1", text)
    text = text.replace("-", " ")
    raw = re.findall(r"[a-z0-9\.]+", text)
    out = set()
    for w in raw:
        w = w.strip(".")
        if not w or w in STOP:
            continue
        if re.fullmatch(r"\d+\.\d+", w):  # decimals like 0.5 carry no identity
            continue
        out.add(w)
    return out


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def distinctive(tok: str) -> bool:
    return len(tok) >= 5 and not tok.isdigit()


def fetch_markets(pages: int):
    """Every OPEN Kalshi market: title + subtitle + ticker, cursor-paged."""
    out, cursor, seen = [], None, 0
    for p in range(pages):
        q = {"limit": "1000", "status": "open"}
        if cursor:
            q["cursor"] = cursor
        url = f"{BASE}/markets?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"accept": "application/json",
                                                  "user-agent": "copybot-research/0.1 (paper-only)"})
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.load(r)
                break
            except Exception as e:  # 429s are common on deep walks
                if attempt == 3:
                    print(f"  page {p}: giving up ({e})", file=sys.stderr)
                    return out
                time.sleep(1.5 * attempt)
        ms = (data or {}).get("markets", [])
        for m in ms:
            out.append({
                "ticker": m.get("ticker", ""),
                "title": m.get("title", ""),
                "subtitle": m.get("subtitle") or "",
                "event": m.get("event_ticker", ""),
                "yes_bid": m.get("yes_bid"),
                "volume": m.get("volume"),
            })
        cursor = data.get("cursor")
        seen += len(ms)
        if not cursor or not ms:
            break
        time.sleep(0.12)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--pages", type=int, default=30)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--min-score", type=float, default=0.30)
    args = ap.parse_args()

    since_ms = int((time.time() - args.days * 86400) * 1000)
    con = sqlite3.connect(DB)
    rows = con.execute(
        """SELECT t.marketId, o.marketQuestion FROM PaperTrade t
           JOIN DecisionJournal d ON d.id = t.decisionJournalId
           JOIN ObservedTrade o ON o.id = d.observedTradeId
           WHERE t.botId='BANKROLL_200' AND t.isDemo=0 AND t.openedAt >= ?
           GROUP BY t.marketId""",
        (since_ms,),
    ).fetchall()
    con.close()

    print(f"kalshi-coverage-probe — {len(rows)} distinct C-200 markets opened in the last {args.days}d")
    markets = fetch_markets(args.pages)
    print(f"  fetched {len(markets)} open Kalshi markets")
    if not markets:
        print("  no Kalshi data — aborting")
        return 1

    idx = []
    for m in markets:
        toks = tokens(f"{m['title']} {m['subtitle']}")
        if toks:
            idx.append((toks, m))

    scored = []
    for market_id, question in rows:
        qt = tokens(question)
        if not qt:
            scored.append({"marketId": market_id, "question": question, "score": 0.0, "match": None})
            continue
        best, best_m = 0.0, None
        for toks, m in idx:
            inter = qt & toks
            if not any(distinctive(t) for t in inter):
                continue  # a match that shares only generic tokens is noise
            s = jaccard(qt, toks)
            if s > best:
                best, best_m = s, m
        scored.append({
            "marketId": market_id,
            "question": (question or "")[:110],
            "score": round(best, 3),
            "match": None if best_m is None else {
                "ticker": best_m["ticker"], "title": best_m["title"][:100],
                "shared": sorted(t for t in (qt & tokens(f"{best_m['title']} {best_m['subtitle']}")) if distinctive(t))[:6],
            },
        })

    scored.sort(key=lambda r: -r["score"])
    bands = Counter()
    for r in scored:
        s = r["score"]
        bands["0.00 (no shared distinctive token)" if r["match"] is None else
              "0.01-0.29" if s < 0.30 else "0.30-0.49" if s < 0.50 else
              "0.50-0.69" if s < 0.70 else ">=0.70"] += 1

    print("\ncoverage ceiling (score = Jaccard over content tokens, distinctive token required):")
    for band in ["0.00 (no shared distinctive token)", "0.01-0.29", "0.30-0.49", "0.50-0.69", ">=0.70"]:
        n = bands.get(band, 0)
        print(f"  {band:38} {n:>4}  ({100.0*n/max(1,len(scored)):5.1f}%)")

    above = [r for r in scored if r["score"] >= args.min_score]
    print(f"\n{len(above)} of {len(scored)} markets clear {args.min_score} — top {args.top} for eyeball verification:")
    for r in above[: args.top]:
        print(f"  {r['score']:.2f}  {r['question'][:66]}")
        if r["match"]:
            print(f"        -> {r['match']['ticker']:28} {r['match']['title'][:60]}")
            print(f"           shared: {', '.join(r['match']['shared'])}")

    with open(OUT, "w") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "windowDays": args.days, "kalshiOpenMarkets": len(markets),
            "ourMarkets": len(scored), "minScore": args.min_score,
            "bands": dict(bands), "clearMinScore": len(above), "rows": scored,
        }, f, indent=2)
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
