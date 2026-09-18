#!/usr/bin/env python3
"""Kalshi slug matcher — builds a COMPLETE event index and maps our markets to it.

Why this exists (2026-09-18): the daily report asked for a revive-or-park call on
the cross-venue lane, whose shadow book showed "verified cross-listings = 0 (0%)"
and blamed matcher coverage. Two probes showed the binding constraint is neither
the delta nor the matching algorithm — it is PAGINATION DEPTH:

  * Kalshi has >12,000 open EVENTS (the cursor is still not exhausted after 60
    pages x 200).
  * The Rust sidecar's `resolve_kalshi_match` walks `MAX_EVENT_PAGES` (8 pages x
    200 = 1,600 events) — roughly a tenth of the inventory — so real counterparts
    never enter the scoring set. Counterparts demonstrably exist: matching our own
    book by keyword finds 72 "fed" events, 40 "emmy", 40 "elon", 9 "valorant",
    2 Flávio-Bolsonaro events.
  * An earlier probe that capped at 25,000 MARKETS reproduced the same illusion
    (0 of 202 rows scored >= 0.3), so the ceiling cannot be measured from a
    truncated index.

This script:
  1. builds/refreshes the full open-event index (cursor walk, cached to
     data/kalshi-event-index.json, TTL --ttl-hours, default 12);
  2. scores every C-200 market in the window against it with a stricter matcher
     than the sidecar's (Jaccard over content tokens, and at least one shared
     distinctive token >= 5 chars) — the loose overlap/min(len) denominator is
     what let "Will Bursaspor win on 2026-09-13?" match a Texas election at 0.67;
  3. writes data/kalshi-slug-map.json (marketId -> ticker/title/score) for the
     sidecar or the venue-shadow to consume, and prints the coverage ceiling.

Usage:
  python3 scripts/kalshi-slug-matcher.py --days 7                 # build/refresh + score
  python3 scripts/kalshi-slug-matcher.py --refresh --max-pages 200
  python3 scripts/kalshi-slug-matcher.py --days 30 --min-score 0.25 --top 25
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
INDEX = os.path.join(ROOT, "data", "kalshi-event-index.json")
MAP = os.path.join(ROOT, "data", "kalshi-slug-map.json")
BASE = "https://api.elections.kalshi.com/trade-api/v2"

STOP = {
    "will", "the", "a", "an", "of", "in", "on", "at", "by", "to", "for", "be",
    "is", "are", "was", "were", "and", "or", "if", "than", "then", "this", "that",
    "with", "from", "as", "it", "its", "any", "all", "no", "not", "yes",
    "market", "marketclose", "close", "before", "after", "during", "above",
    "below", "more", "less", "most", "least", "over", "under", "between",
    "reach", "hit", "exceed", "exceeds", "greater", "higher", "lower", "end",
    "ends", "during", "happen", "happens", "occur", "occurs",
}
MONTHS = {
    "jan": "01", "january": "01", "feb": "02", "february": "02", "mar": "03", "march": "03",
    "apr": "04", "april": "04", "may": "05", "jun": "06", "june": "06", "jul": "07", "july": "07",
    "aug": "08", "august": "08", "sep": "09", "september": "09", "oct": "10", "october": "10",
    "nov": "11", "november": "11", "dec": "12", "december": "12",
}


def tokens(text: str) -> set:
    text = (text or "").lower()
    for name, num in MONTHS.items():
        text = re.sub(rf"\b{name}\.?\s*([0-3]?\d)\b", f"{num}-\\1", text)
    text = text.replace("-", " ").replace("'", "")
    out = set()
    for w in re.findall(r"[a-z0-9\.]+", text):
        w = w.strip(".")
        if not w or w in STOP or re.fullmatch(r"\d+\.\d+", w):
            continue
        out.add(w)
    return out


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def get(url: str, tries: int = 4):
    req = urllib.request.Request(url, headers={"accept": "application/json",
                                              "user-agent": "copybot-research/0.1 (paper-only)"})
    for a in range(1, tries + 1):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except Exception:
            if a == tries:
                raise
            time.sleep(1.5 * a)


def build_index(max_pages: int, refresh: bool, ttl_hours: float):
    if not refresh and os.path.exists(INDEX):
        age_h = (time.time() - os.path.getmtime(INDEX)) / 3600.0
        if age_h < ttl_hours:
            with open(INDEX) as f:
                idx = json.load(f)
            print(f"index cache: {len(idx['events'])} events, {age_h:.1f}h old (ttl {ttl_hours}h)")
            return idx
    events, cursor, pages = [], None, 0
    while pages < max_pages:
        q = {"status": "open", "limit": "200"}
        if cursor:
            q["cursor"] = cursor
        d = get(f"{BASE}/events?" + urllib.parse.urlencode(q))
        ev = d.get("events", [])
        for e in ev:
            events.append({"ticker": e.get("event_ticker", ""), "title": e.get("title", ""),
                           "category": e.get("category", ""), "series": e.get("series_ticker", "")})
        cursor = d.get("cursor")
        pages += 1
        if not cursor or not ev:
            break
        time.sleep(0.1)
    idx = {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "pages": pages, "cursorExhausted": not cursor, "events": events}
    with open(INDEX, "w") as f:
        json.dump(idx, f)
    print(f"index built: {len(events)} open events over {pages} pages (exhausted: {not cursor}) -> {INDEX}")
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--min-score", type=float, default=0.25)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--max-pages", type=int, default=200)
    ap.add_argument("--ttl-hours", type=float, default=12.0)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    idx = build_index(args.max_pages, args.refresh, args.ttl_hours)
    scored_idx = []
    for e in idx["events"]:
        t = tokens(e["title"])
        if t:
            scored_idx.append((t, e))
    print(f"  indexable events: {len(scored_idx)}")

    since_ms = int((time.time() - args.days * 86400) * 1000)
    con = sqlite3.connect(DB)
    rows = con.execute(
        """SELECT t.marketId, o.marketQuestion, ROUND(SUM(t.simulatedPositionSize),2) stake
           FROM PaperTrade t
           JOIN DecisionJournal d ON d.id = t.decisionJournalId
           JOIN ObservedTrade o ON o.id = d.observedTradeId
           WHERE t.botId='BANKROLL_200' AND t.isDemo=0 AND t.openedAt >= ?
           GROUP BY t.marketId ORDER BY stake DESC""",
        (since_ms,),
    ).fetchall()
    con.close()
    print(f"  our C-200 markets in the last {args.days}d: {len(rows)} (total stake ${sum(r[2] or 0 for r in rows):,.2f})")

    out = []
    for market_id, question, stake in rows:
        qt = tokens(question)
        best, best_e, shared = 0.0, None, set()
        for toks, e in scored_idx:
            inter = qt & toks
            if not inter or not any(len(t) >= 5 for t in inter):
                continue
            s = jaccard(qt, toks)
            if s > best:
                best, best_e, shared = s, e, inter
        out.append({"marketId": market_id, "question": (question or "")[:120], "stake": stake,
                    "score": round(best, 3),
                    "ticker": None if best_e is None else best_e["ticker"],
                    "eventTitle": None if best_e is None else best_e["title"],
                    "shared": sorted(t for t in shared if len(t) >= 5)[:6]})

    bands = Counter()
    for r in out:
        s = r["score"]
        bands["no shared distinctive token" if r["ticker"] is None else
              "0.01-0.24" if s < 0.25 else "0.25-0.39" if s < 0.40 else
              "0.40-0.59" if s < 0.60 else ">=0.60"] += 1
    matched = [r for r in out if r["score"] >= args.min_score]
    stake_all = sum(r["stake"] or 0 for r in out)
    stake_matched = sum(r["stake"] or 0 for r in matched)

    print("\ncoverage vs the COMPLETE index (distinctive-token rule + Jaccard):")
    for b in ["no shared distinctive token", "0.01-0.24", "0.25-0.39", "0.40-0.59", ">=0.60"]:
        n = bands.get(b, 0)
        print(f"  {b:30} {n:>4}  ({100.0*n/max(1,len(out)):5.1f}%)")
    print(f"\n  cleared {args.min_score}: {len(matched)}/{len(out)} markets "
          f"({100.0*len(matched)/max(1,len(out)):.1f}%) | "
          f"stake covered ${stake_matched:,.2f}/${stake_all:,.2f} "
          f"({100.0*stake_matched/max(1e-9,stake_all):.1f}%)")

    print(f"\ntop {args.top} by score (eyeball these before trusting the map):")
    for r in sorted(matched, key=lambda r: -r["score"])[: args.top]:
        print(f"  {r['score']:.2f}  ${r['stake']:>7.2f}  {r['question'][:62]}")
        print(f"        -> {r['ticker']:26} {(r['eventTitle'] or '')[:58]}")
        print(f"           shared: {', '.join(r['shared'])}")

    with open(MAP, "w") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "indexGeneratedAt": idx["generatedAt"], "indexEvents": len(idx["events"]),
                   "windowDays": args.days, "minScore": args.min_score,
                   "bands": dict(bands), "matched": len(matched), "markets": len(out),
                   "stakeCoveredUsd": round(stake_matched, 2), "stakeTotalUsd": round(stake_all, 2),
                   "map": {r["marketId"]: {"ticker": r["ticker"], "eventTitle": r["eventTitle"],
                                           "score": r["score"], "shared": r["shared"]}
                           for r in matched}}, f, indent=2)
    print(f"\nWrote {MAP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
