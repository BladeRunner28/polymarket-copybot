#!/usr/bin/env python3
"""Detection lag inside the TTR skip class — read-only replay (2026-11-26).

Question it answers
-------------------
The largest single skip class in the decision journal is the time-to-resolution
floor ("resolves in 0.0h < min 2h" is ~18% of the newest 400 rows). Two very
different worlds produce that line:

  (a) the wallet traded inside our 2h floor -> structurally uncopyable, the gate
      is doing its job;
  (b) the wallet traded with plenty of lead but OUR sweep saw it late -> a
      cadence/backlog defect that a tighter sweep could recover.

This script separates them on stored rows only (no venue calls, no writes):
    lag   = DecisionJournal.createdAt - ObservedTrade.timestamp   (our detection delay)
    ttr   = the value the gate printed in risksJson ("resolves in <ttr>h")
    lead  = ttr + lag                                             (the wallet's true lead)
A row is "cadence-recoverable" when lead >= 2h while ttr < 2h and lag <= 0.5h.

Adverse-selection check: ObservedTrade.detectedPrice - walletEntryPrice on the
late class. If late detection is expensive, copying later would have been worse.

Usage:  python3 scripts/det-lag-vs-ttr-read.py [--days 30] [--json out.json]
Basis:  prisma/dev.db, read-only URI. Paper-only stack — nothing here touches a lane.
Result (2026-11-26, 30 d): see data/det-lag-vs-ttr-read.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "prisma" / "dev.db"
PAT = re.compile(r"resolves in ([0-9.]+)h")


def quantiles(vals: list[float]) -> dict[str, float]:
    if not vals:
        return {}
    s = sorted(vals)
    n = len(s)
    q = lambda p: s[min(n - 1, int(p * n))]
    return {"n": n, "p10": round(q(.10), 3), "p25": round(q(.25), 3), "p50": round(q(.50), 3),
            "p75": round(q(.75), 3), "p90": round(q(.90), 3), "max": round(s[-1], 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", default=str(REPO / "data" / "det-lag-vs-ttr-read.json"))
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("""
        SELECT d.observedTradeId, d.createdAt, d.risksJson, o.timestamp,
               o.walletEntryPrice, o.detectedPrice
        FROM DecisionJournal d JOIN ObservedTrade o ON o.id = d.observedTradeId
        WHERE d.decision = 'skip' AND d.isDemo = 0
          AND d.createdAt > (strftime('%s','now') - ?*86400)*1000
    """, (a.days,))

    seen: set[str] = set()
    tagged = 0
    lags: list[float] = []
    buckets: dict[str, list[float | None]] = {"cadence<=0.5h": [], "mid0.5-2h": [], "late>2h": []}
    lead_cleared = 0
    for tid, created, risks, ts, wep, det in cur.fetchall():
        if tid in seen:
            continue
        seen.add(tid)
        try:
            rj = json.loads(risks or "[]")
        except Exception:
            continue
        hits = [PAT.search(str(x)) for x in rj]
        hits = [h for h in hits if h]
        if not hits:
            continue
        tagged += 1
        ttr = min(float(h.group(1)) for h in hits)
        lag = (created - ts) / 3_600_000.0
        lags.append(lag)
        if ttr + lag < 2.0:
            continue                      # wallet itself traded inside the floor
        lead_cleared += 1
        mv = (det - wep) if (wep is not None and det is not None) else None
        b = "cadence<=0.5h" if lag <= 0.5 else ("mid0.5-2h" if lag <= 2.0 else "late>2h")
        buckets[b].append(mv)

    out = {
        "ranAt": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "days": a.days,
        "ttr_tagged_skips": tagged,
        "lag_hours": quantiles(lags),
        "lead_cleared_count": lead_cleared,
        "lead_cleared_share": round(lead_cleared / tagged, 4) if tagged else None,
        "buckets": {},
    }
    for b, v in buckets.items():
        mvs = [x for x in v if x is not None]
        out["buckets"][b] = {
            "n": len(v),
            "share_of_tagged": round(len(v) / tagged, 4) if tagged else None,
            "priced": len(mvs),
            "entry_move_usd": quantiles(mvs) if mvs else {},
            "adverse_share": round(sum(1 for x in mvs if x > 0) / len(mvs), 3) if mvs else None,
        }
    out["conclusion"] = (
        "cadence lever REFUTED on this basis: the cadence-recoverable slice is small and the "
        "late (>2h) rows are backfill, not sweep latency"
        if out["buckets"]["cadence<=0.5h"]["share_of_tagged"] is not None
        and out["buckets"]["cadence<=0.5h"]["share_of_tagged"] < 0.05 else
        "cadence-recoverable slice >= 5% — a near-close sweep priority is worth pricing"
    )
    Path(a.json).write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
