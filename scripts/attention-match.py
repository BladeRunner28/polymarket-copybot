#!/usr/bin/env python3
"""Stage 1 of the attention->price lead test: entity -> market matcher + YIELD report.

Answers one question and nothing else: **do news events and live Polymarket markets overlap enough
to make a salience router worth building?** (design: drafts/attention-lead-test-design-20260918.md,
go/no-go = >=15 usable events/day at >=85% precision.)

Precision-first by construction (house doctrine — return nothing rather than guess):
  * a story is admitted only if it carries >=1 named entity AND >=1 further content token that also
    appears in the market's question; entity-only overlap is explicitly rejected as too weak
  * ambiguity guard: if an entity matches more than AMBIGUITY_MAX live markets at that moment, the
    story is dropped (Donald Trump matches hundreds of markets — that is not a signal)
  * auto-generated market families (daily temperature ladders and similar) are excluded: they are
    38.8% of the market universe and cannot be moved by news
  * the market must be genuinely live at the event: a snapshot within +/-LIVE_WINDOW_H with
    timeToResolution >= MIN_TTR_H and a mid price strictly inside (0.02, 0.98)

Event time for this retro pass is the collector's `ts` (6-hourly), because `story_date` is day-only and
`processed_at` only starts landing from Stage 0 onward. That is fine for a yield measurement and is
reported as a caveat; Stage 2 uses the tighter anchor.

Read-only. Writes data/attention-events.jsonl, data/attention-yield.json, data/attention-audit-sample.jsonl
"""
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = f"file:{os.path.join(ROOT, 'prisma', 'dev.db')}?mode=ro"
NEWS = os.path.join(ROOT, "data", "gdelt-shadow.jsonl")
EVENTS_OUT = os.path.join(ROOT, "data", "attention-events.jsonl")
YIELD_OUT = os.path.join(ROOT, "data", "attention-yield.json")
AUDIT_OUT = os.path.join(ROOT, "data", "attention-audit-sample.jsonl")

AMBIGUITY_MAX = 3          # an entity matching more live markets than this is not a signal
LIVE_WINDOW_H = 12         # snapshot must be this close to the event time
MIN_TTR_H = 24             # market must have at least a day left to resolve
AUDIT_N = 50

STOP = set("""a an the and or but if then than that this these those for from with without into onto of on in
at by to as is are was were be been being will would shall should can could may might must do does did done not
no nor new says say said report reports reported after before over under again more most less least up down out
off about against between during through above below first second third its it his her their our your my
""".split())
# Market families that no news story can move (auto-generated ladders / daily series).
NOISE_PATTERNS = [
    r"highest temperature", r"lowest temperature", r"temperature in .* be ",
    r"approval rating be between", r"how many .* be (above|below|between)",
]


def content_tokens(text):
    toks = re.findall(r"[A-Za-z][A-Za-z'\-]+", (text or "").lower())
    return {t for t in toks if len(t) >= 3 and t not in STOP}


def proper_phrases(text):
    """Capitalised 1-3 word phrases from a headline — the entity fallback when the API gives none."""
    out = set()
    words = re.findall(r"[A-Z][A-Za-z'\-]+(?:\s+(?:of|the|and|for|de|da|van|al)?\s*[A-Z][A-Za-z'\-]+){0,2}", text or "")
    for w in words:
        w = w.strip()
        if len(w) >= 4:
            out.add(w)
    return out


def load_markets(cur):
    """(marketId, question) -> tokens, from the most recent snapshot of each market."""
    rows = cur.execute("""
        SELECT m.marketId, m.question, m.collectedAt, m.yesPrice, m.timeToResolution
        FROM MarketSnapshot m
        JOIN (SELECT marketId, MAX(collectedAt) c FROM MarketSnapshot GROUP BY marketId) t
          ON t.marketId = m.marketId AND t.c = m.collectedAt
        WHERE m.question IS NOT NULL AND length(m.question) > 10
    """).fetchall()
    markets = {}
    for mid, question, collected, yes, ttr in rows:
        ql = (question or "").lower()
        if any(re.search(p, ql) for p in NOISE_PATTERNS):
            continue
        markets[(mid, question)] = {
            "tokens": content_tokens(question),
            "marketId": mid,
            "question": question,
            "collectedAt": collected,
            "yesPrice": yes,
            "ttr": ttr,
        }
    return markets


def build_index(markets):
    idx = defaultdict(set)
    for key, m in markets.items():
        for tok in m["tokens"]:
            idx[tok].add(key)
    return idx


def snapshot_at(cur, market_id, t_ms, cache):
    """Nearest snapshot to t_ms for a market (cached) — the live/price check."""
    if market_id in cache:
        return cache[market_id]
    rows = cur.execute("""
        SELECT collectedAt, yesPrice, timeToResolution FROM MarketSnapshot
        WHERE marketId = ? ORDER BY ABS(collectedAt - ?) LIMIT 1
    """, (market_id, t_ms)).fetchall()
    cache[market_id] = rows[0] if rows else None
    return cache[market_id]


def main():
    cur = sqlite3.connect(DB, uri=True, timeout=120).cursor()
    cur.execute("PRAGMA busy_timeout=600000")

    markets = load_markets(cur)
    idx = build_index(markets)
    print(f"market universe (news-relevant, noise families removed): {len(markets):,}")

    stories = []
    for line in open(NEWS, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            stories.append(json.loads(line))
        except Exception:
            continue
    print(f"news rows loaded: {len(stories):,}")

    events, audit_pool = [], []
    drops = Counter()
    snap_cache = {}
    per_day = Counter()

    for s in stories:
        title = s.get("title") or ""
        ents = [e for e in (s.get("entity_refs") or []) if e]
        if not ents:
            ents = sorted(proper_phrases(title))
        if not ents:
            drops["no_entity"] += 1
            continue

        title_toks = content_tokens(title)
        ent_toks = {t for e in ents for t in content_tokens(e)}
        cand = set()
        for tok in ent_toks:
            cand |= idx.get(tok, set())
        if not cand:
            drops["no_market_token_overlap"] += 1
            continue

        scored = []
        for key in cand:
            m = markets[key]
            hit_ent = ent_toks & m["tokens"]
            hit_other = (title_toks - ent_toks) & m["tokens"]
            if not hit_ent:
                continue
            if not hit_other:
                drops["entity_only_overlap"] += 1
                continue
            scored.append((len(hit_ent) + len(hit_other), key, hit_ent, hit_other))
        if not scored:
            continue
        scored.sort(reverse=True)
        if len(scored) > AMBIGUITY_MAX:
            drops["ambiguous_entity"] += 1
            continue

        t_ms = None
        try:
            from datetime import datetime
            t_ms = int(datetime.fromisoformat(s["ts"]).timestamp() * 1000)
        except Exception:
            drops["bad_ts"] += 1
            continue

        for score, key, hit_ent, hit_other in scored[:1]:
            m = markets[key]
            snap = snapshot_at(cur, m["marketId"], t_ms, snap_cache)
            if not snap:
                drops["no_snapshot"] += 1
                continue
            collected, yes, ttr = snap
            if abs(collected - t_ms) > LIVE_WINDOW_H * 3_600_000:
                drops["not_live_at_event"] += 1
                continue
            if ttr is None or ttr < MIN_TTR_H:
                drops["ttr_too_short"] += 1
                continue
            if yes is None or not (0.02 < yes < 0.98):
                drops["price_at_bound"] += 1
                continue

            ev = {
                "ts": s["ts"],
                "story_id": s.get("item_id"),
                "title": title,
                "url": s.get("url"),
                "category": s.get("category"),
                "story_date": s.get("story_date", ""),
                "entities": ents,
                "article_count": s.get("article_count"),
                "significance": s.get("significance"),
                "geo": s.get("geo"),
                "marketId": m["marketId"],
                "market_question": m["question"],
                "matched_entity_tokens": sorted(hit_ent),
                "matched_other_tokens": sorted(hit_other),
                "snapshot_ts": collected,
                "snapshot_yes": yes,
                "ttr_hours": ttr,
            }
            events.append(ev)
            per_day[s["ts"][:10]] += 1
            audit_pool.append(ev)

    with open(EVENTS_OUT, "w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")

    days = len({e["ts"][:10] for e in stories}) or 1
    uniq_markets = len({e["marketId"] for e in events})
    uniq_entities = len({x for e in events for x in e["entities"]})
    summary = {
        "generated_from": "data/gdelt-shadow.jsonl",
        "stories": len(stories),
        "days_covered": days,
        "events_matched": len(events),
        "events_per_day": round(len(events) / days, 2),
        "distinct_markets": uniq_markets,
        "distinct_entities": uniq_entities,
        "gate_events_per_day_15": len(events) / days >= 15,
        "gate_precision": "see data/attention-audit-sample.jsonl (hand-labelled)",
        "drop_reasons": dict(drops.most_common()),
        "events_per_day_series": dict(sorted(per_day.items())),
    }
    with open(YIELD_OUT, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    with open(AUDIT_OUT, "w", encoding="utf-8") as fh:
        for e in audit_pool[:AUDIT_N]:
            fh.write(json.dumps({k: e[k] for k in ("ts", "title", "entities", "market_question",
                                                   "matched_entity_tokens", "matched_other_tokens")}) + "\n")

    print(f"\n=== YIELD ===")
    print(f"  stories {len(stories)} over {days} days = {len(stories)/days:.1f}/day")
    print(f"  matched events: {len(events)}  ({len(events)/days:.1f}/day)")
    print(f"  distinct markets {uniq_markets} | distinct entities {uniq_entities}")
    print(f"  gate (>=15/day): {'PASS' if len(events)/days >= 15 else 'FAIL'}")
    print("\n  drop reasons:")
    for k, v in drops.most_common(10):
        print(f"    {k:26} {v}")
    print(f"\nwrote {EVENTS_OUT}\n      {YIELD_OUT}\n      {AUDIT_OUT}")


if __name__ == "__main__":
    main()
