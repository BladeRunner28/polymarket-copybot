#!/usr/bin/env python3
"""Audit trades booked as LOSSES whose outcome label is not YES/NO.

Why: the Polymarket adapter derives resolution as
`winningOutcome = yesPrice > 0.5 ? "YES" : "NO"` (src/lib/adapters/polymarket.ts),
but sports/esports/handicap/total markets carry token labels like "Dynasty",
"Under", "9z". A trade on such a token can therefore never satisfy
`winningOutcome === trade.outcome`, so resolvePaperTrade books every one of them
as a full-stake loss no matter what actually happened.

This script asks the keyless CLOB for each market's tokens + winner and
classifies each booked loss:
  PHANTOM_LOSS     the bought label IS a winning token -> should have been a WIN
  correct_loss     the bought label was a losing token
  unresolvable     market/conditionId not resolvable (404 / no tokens)
  ambiguous        winner not published yet or label unmatched

Usage:  python3 scripts/audit-misresolved-trades.py [--bot BANKROLL_200] [--limit N]
Read-only (opens the SQLite DB in read-only mode, only GETs from CLOB).
"""
import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import defaultdict

DB = "file:/Users/xsnyde2/polymarket-copybot/prisma/dev.db?mode=ro"
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
}


def norm(s: str) -> str:
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def fetch(url: str):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"__http": e.code}
    except Exception as e:  # noqa: BLE001
        return {"__err": type(e).__name__}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    con = sqlite3.connect(DB, uri=True)
    q = """
      SELECT t.botId, t.outcome, o.conditionId, o.marketQuestion, t.realizedPnl, t.simulatedPositionSize, t.id
      FROM PaperTrade t
      JOIN DecisionJournal d ON d.id = t.decisionJournalId
      JOIN ObservedTrade o ON o.id = d.observedTradeId
      WHERE t.status = 'resolved' AND t.outcome NOT IN ('YES','NO')
    """
    if a.bot:
        q += f" AND t.botId = '{a.bot}'"
    rows = con.execute(q).fetchall()
    con.close()
    if a.limit:
        rows = rows[: a.limit]

    by_cond = defaultdict(list)
    for r in rows:
        by_cond[r[2]].append(r)

    print(f"auditing {len(rows)} booked losses across {len(by_cond)} distinct markets\n", flush=True)
    verdicts = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    per_bot = defaultdict(lambda: defaultdict(lambda: {"n": 0, "pnl": 0.0}))
    phantom_rows = []

    for i, (cond, trades) in enumerate(by_cond.items(), 1):
        d = fetch(f"https://clob.polymarket.com/markets/{cond}")
        winners, losers = [], []
        status = "ok"  # ok | unresolvable | ambiguous
        if "__http" in d or "__err" in d:
            status = "unresolvable"
        else:
            toks = d.get("tokens") or []
            if not toks:
                status = "unresolvable"
            else:
                for t in toks:
                    (winners if t.get("winner") else losers).append(t.get("outcome"))
                if not winners:
                    status = "ambiguous"  # closed=false or winner not published
        for bot, outcome, c, question, pnl, size, tid in trades:
            if status == "unresolvable":
                v = "unresolvable"
            elif status == "ambiguous":
                v = "ambiguous"
            elif any(norm(w) and (norm(w) == norm(outcome) or norm(w) in norm(outcome) or norm(outcome) in norm(w)) for w in winners):
                v = "PHANTOM_LOSS"
            elif any(norm(l) == norm(outcome) or norm(l) in norm(outcome) or norm(outcome) in norm(l) for l in losers):
                v = "correct_loss"
            else:
                v = "ambiguous"
            verdicts[v]["n"] += 1
            verdicts[v]["pnl"] += pnl
            per_bot[bot][v]["n"] += 1
            per_bot[bot][v]["pnl"] += pnl
            if v == "PHANTOM_LOSS":
                phantom_rows.append((bot, outcome, winners, pnl, size, question[:60]))
        if i % 25 == 0:
            print(f"  …{i}/{len(by_cond)} markets", flush=True)

    print("\n=== verdicts ===")
    for v, s in sorted(verdicts.items(), key=lambda x: x[1]["pnl"]):
        print(f"  {v:14} n={s['n']:4}  booked_pnl={s['pnl']:9.2f}")
    print("\n=== by bot ===")
    for bot, m in per_bot.items():
        for v, s in sorted(m.items(), key=lambda x: x[1]["pnl"]):
            print(f"  {bot:14} {v:14} n={s['n']:4} booked_pnl={s['pnl']:9.2f}")

    if phantom_rows:
        print(f"\n=== sample phantom losses ({len(phantom_rows)} total) ===")
        for bot, outcome, winners, pnl, size, q in phantom_rows[:12]:
            print(f"  {bot} bought {outcome!r} (winner={winners}) booked {pnl:+.2f} size ${size:.2f} | {q}")

    json.dump(
        {
            "verdicts": {k: v for k, v in verdicts.items()},
            "by_bot": {b: dict(m) for b, m in per_bot.items()},
            "phantom_rows": [
                {"bot": b, "bought": o, "winners": w, "pnl": p, "size": s, "question": q}
                for b, o, w, p, s, q in phantom_rows
            ],
        },
        open("/tmp/misresolved-audit.json", "w"),
        indent=2,
    )
    print("\nwrote /tmp/misresolved-audit.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
