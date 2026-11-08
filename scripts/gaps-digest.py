#!/usr/bin/env python3
"""
Weekly cross-platform gaps digest (Phase Data-1) — for Discord delivery.

Summarizes data/manifold-gaps.jsonl (+ data/odds-gaps.jsonl when present):
gaps logged this week, biggest divergences with direction, and totals since
start. Shadow data only — these are candidates for review, not trades.

Usage:  python3 scripts/gaps-digest.py
"""
import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFOLD = os.path.join(ROOT, "data", "manifold-gaps.jsonl")
ODDS = os.path.join(ROOT, "data", "odds-gaps.jsonl")

WEEK = timedelta(days=7)


def load(path):
    rows = []
    bad = 0
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        # 2026-11-08 (self-audit, Lane B): a truncated/torn last line used to be
                        # dropped in silence, so the digest's counts were a lower bound with the
                        # gap never stated. Count it and print it below.
                        bad += 1
    return rows, bad


def age_days(rows, now):
    """Days since the newest row, or None when the file is empty."""
    ts = max((r.get("ts", "") for r in rows), default="")
    if not ts:
        return None
    try:
        return (now - datetime.fromisoformat(ts)).days
    except ValueError:
        return None


def stale_note(rows, now, label, total):
    """0-new is only a measurement if the feed actually wrote something in the window."""
    a = age_days(rows, now)
    if a is None:
        return f"**{label}:** no rows at all yet — 0 new is UNMEASURED (the collector has never written)"
    return (f"⚠️ **{label}:** 0 new this week is NOT a measurement — the feed's newest row is "
            f"{a} day(s) old ({total} total). The collector is writing nothing, so nothing was "
            f"compared; this is a DEAD FEED, not a quiet week.")


def main():
    now = datetime.now(timezone.utc)
    cutoff = (now - WEEK).isoformat()

    m_rows, m_bad = load(MANIFOLD)
    o_rows, o_bad = load(ODDS)

    m_week = [r for r in m_rows if r.get("ts", "") >= cutoff]
    o_week = [r for r in o_rows if r.get("ts", "") >= cutoff]

    lines = ["🔭 **Cross-Platform Gaps Digest (weekly)**"]
    if m_bad or o_bad:
        lines.append(f"🟠 CORRUPT LINES SKIPPED: manifold {m_bad}, odds {o_bad} — counts below are a "
                     f"LOWER BOUND (an unparseable line was never compared)")

    if not m_rows and not o_rows:
        lines.append("No gap data yet — the Manifold scanner runs 6-hourly; first digest after a week of accumulation.")
        print("\n".join(lines))
        return

    if m_week:
        m_sorted = sorted(m_week, key=lambda r: abs(r.get("gap", 0)), reverse=True)
        lines.append(f"**Manifold ↔ Polymarket:** {len(m_week)} new gap(s) this week · {len(m_rows)} total")
        for r in m_sorted[:5]:
            direction = "PM cheaper" if r["gap"] > 0 else "PM dearer"
            lines.append(
                f"- {r['pmQuestion'][:55]}… gap {r['gap']:+.3f} "
                f"({direction}: PM {r['pmProb']:.2f} vs MF {r['manifoldProb']:.2f}, sim {r['similarity']:.2f})"
            )
    elif m_rows:
        lines.append(stale_note(m_rows, now, "Manifold ↔ Polymarket", len(m_rows)))
    else:
        lines.append("**Manifold ↔ Polymarket:** no data yet")

    if o_rows:
        if o_week:
            o_sorted = sorted(o_week, key=lambda r: abs(r.get("gap", 0)), reverse=True)
            lines.append(f"**Sportsbook ↔ Polymarket:** {len(o_week)} new this week · {len(o_rows)} total")
            for r in o_sorted[:3]:
                lines.append(f"- {r.get('event', '?')} gap {r['gap']:+.3f} (book {r.get('bookImplied', '?')} vs PM {r.get('pmProb', '?')})")
        else:
            lines.append(stale_note(o_rows, now, "Sportsbook ↔ Polymarket", len(o_rows)))
    else:
        lines.append("**Sportsbook ↔ Polymarket:** no data yet (needs ODDS_API_KEY)")

    lines.append("_Shadow feed — review candidates, not trades. Promote only after 2-week gate._")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
