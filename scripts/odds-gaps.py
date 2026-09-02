#!/usr/bin/env python3
"""
Odds API sports-gap detector (Phase Data-1, SHADOW ONLY).

Compares sportsbook-implied probabilities (The Odds API — free tier, key via
email at https://the-odds-api.com) against Polymarket prices for the same
events. Sports is the highest-volume market class + the short-TTR lane; when a
book says 55% and Polymarket says 48%, at least one venue is mispriced.

SHADOW ONLY: logs to data/odds-gaps.jsonl; nothing touches the live pipeline.

Setup:
  1. Grab a free API key: https://the-odds-api.com (email signup)
  2. Add to /Users/xsnyde2/polymarket-copybot/.env:  ODDS_API_KEY=...
  3. Run: python3 scripts/odds-gaps.py

Usage:
  python3 scripts/odds-gaps.py                      # scan soccer (default)
  python3 scripts/odds-gaps.py --sport basketball   # other sports
  python3 scripts/odds-gaps.py --list-sports        # available sports
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
OUT = os.path.join(ROOT, "data", "odds-gaps.jsonl")
DB = os.path.join(ROOT, "prisma", "dev.db")

API = "https://api.the-odds-api.com/v4"
GAP_THRESHOLD = 0.10  # log |implied - pm| >= 10pp
REGIONS = "eu,uk,us"  # free tier: 1 region per key; adjust to your key's region


def get_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def key():
    k = os.environ.get("ODDS_API_KEY")
    if not k:
        # allow .env fallback (load manually — don't import dotenv)
        env_path = os.path.join(ROOT, ".env")
        if os.path.exists(env_path):
            for line in open(env_path):
                if line.strip().startswith("ODDS_API_KEY="):
                    k = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="baseball_mlb")
    ap.add_argument("--list-sports", action="store_true")
    ap.add_argument("--gap", type=float, default=GAP_THRESHOLD)
    args = ap.parse_args()

    k = key()
    if not k:
        print(
            "No ODDS_API_KEY found. Grab a free key at https://the-odds-api.com "
            "(email signup) and add ODDS_API_KEY=... to polymarket-copybot/.env"
        )
        return

    if args.list_sports:
        sports = get_json(f"{API}/sports/?apiKey={k}")
        for s in sports:
            print(f"{s.get('key'):<14} {s.get('title')}")
        return

    print(f"Fetching {args.sport} odds…")
    events = get_json(
        f"{API}/sports/{urllib.parse.quote(args.sport)}/odds/"
        f"?apiKey={k}&regions={REGIONS}&oddsFormat=decimal"
    )
    print(f"Events: {len(events)}")

    # Build a lookup of Polymarket sports questions (active markets from
    # MarketSnapshot) to match event names against.
    uri = "file:{}?mode=ro".format(DB)
    con = sqlite3.connect(uri, uri=True)
    con.execute("PRAGMA busy_timeout=8000")
    pm_rows = con.execute(
        """
        SELECT m.marketId, m.question, m.yesPrice
        FROM MarketSnapshot m
        JOIN (SELECT marketId, MAX(collectedAt) AS mx FROM MarketSnapshot GROUP BY marketId) l
          ON l.marketId = m.marketId AND l.mx = m.collectedAt
        WHERE m.question != '' AND m.question NOT LIKE '[DEMO]%' AND m.isDemo = 0
          AND m.liquidity >= 500
          AND l.mx >= ?
        """,
        (int(time.time() * 1000) - 24 * 3600 * 1000,),
    ).fetchall()
    con.close()
    pm_by_lower = {}
    for mid, q, p in pm_rows:
        pm_by_lower.setdefault(q.lower().strip(), []).append((mid, p))
    print(f"Active Polymarket questions: {len(pm_by_lower)}")

    # Sportsbook "Arsenal @ Chelsea" vs Polymarket "Will Arsenal beat
    # Chelsea on 2026-09-01?" — match by team-token containment.
    GENERIC = {"fc", "cf", "club", "ac", "sc", "afc", "de", "del", "the", "bk", "sk"}
    def team_tokens(name: str) -> list[str]:
        return [t for t in re.findall(r"[a-z']+", name.lower()) if len(t) > 2 and t not in GENERIC]

    def find_pm_matches(home: str, away: str):
        ht, at = team_tokens(home), team_tokens(away)
        if not ht or not at:
            return []
        out = []
        for key, entries in pm_by_lower.items():
            if all(t in key for t in ht) and all(t in key for t in at):
                out.extend(entries)
                if len(out) >= 3:
                    break
        return out

    found = 0
    rows = []
    for ev in events:
        home = ev.get("home_team", "")
        away = ev.get("away_team", "")
        teams = f"{home} {away}".strip()
        if not teams:
            continue
        matches = find_pm_matches(home, away)
        if not matches:
            continue
        # Median bookmaker implied prob for the home team, rejecting
        # degenerate placeholder quotes (decimal price <= 1.01 is impossible;
        # >= 30 is noise). Median is robust to single-book outliers.
        implieds = []
        for bk in ev.get("bookmakers", []):
            for mkt in bk.get("markets", []):
                if mkt.get("key") != "h2h":
                    continue
                for oc in mkt.get("outcomes", []):
                    if oc.get("name", "").lower() != home.lower():
                        continue
                    price = float(oc["price"])
                    if 1.01 < price < 30:
                        implieds.append(1.0 / price)
        if not implieds:
            continue
        implieds.sort()
        best_implied = implieds[len(implieds) // 2]
        for mid, pm_p in matches[:3]:
            # Skip resolved/live-game extremes and near-extreme variant
            # markets (run-lines etc.) — untradeable noise for h2h gaps.
            if not (0.05 < pm_p < 0.95):
                continue
            gap = best_implied - pm_p
            if abs(gap) < args.gap:
                continue
            rows.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": ev.get("home_team", "") + " @ " + ev.get("away_team", ""),
                "sport": args.sport,
                "pmMarketId": mid,
                "pmProb": round(pm_p, 3),
                "bookImplied": round(best_implied, 3),
                "gap": round(gap, 3),
                "commenceTime": ev.get("commence_time"),
            })
            found += 1
            print(f"  GAP {gap:+.3f}  {teams[:50]}  PM={pm_p:.3f} book={best_implied:.3f}")

    if rows:
        with open(OUT, "a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    print(f"\nLogged {found} new gap pair(s) -> {OUT}")


if __name__ == "__main__":
    main()
