#!/usr/bin/env python3
"""
Skip-reason level read — are the DECISION-level and ENTRY-level skip-reason
lists two populations, or one population printed twice?

WHY THIS EXISTS (2026-11-02, Lane B — instrument repair, not a rule change)
    scripts/research-collect.py prints a skip-reason mix twice, once "DECISION-level"
    and once "ENTRY-level", and on every observed run the two lines came out
    character-identical in their top five. The ENTRY-level caption asserts "these
    SUMS exceed the row count", which reads as a promise that the two levels differ.
    They cannot differ in the way the caption implies, and the DECISION-level
    caption ("one count per skipped decision") reads as if its counts sum to the
    decision count. Neither description survives a measurement.

WHAT IS ACTUALLY TRUE (and what this script prints every run)
    L1  rows / tagged rows / bare rows / distinct tags
    L2  tag ENTRIES (every risksJson element) vs ROWS — the real inflation,
        measured, not asserted
    L3  WITHIN-ROW DUPLICATE ENTRIES — the ONLY thing that can make the
        DECISION-level and ENTRY-level counts diverge, because DECISION level
        dedupes inside a row and nothing else
    L4  the top-N table at both levels side by side, with the tags whose counts
        disagree named explicitly (or "none")

    So the two lists are identical whenever L3 is zero. That is a measurement, not
    a construction: L3 is a real rate, and this script fails its own verdict if it
    cannot tell the two cases apart (see --self-test).

WHAT THIS IS NOT
    Not a gate census. Tags are per-VALUE ("confidence 0.54 < min 0.7" is a
    different key from "confidence 0.50 < min 0.7"), so the top-N mixes strength
    buckets with gate families. The family rollup is printed separately and is
    the block to read for "which gate refuses most".

READ-ONLY: opens the DB, reads DecisionJournal, prints. Writes nothing.

Run:
    python3 scripts/skip-reason-level-read.py                 # 30d, top 10
    python3 scripts/skip-reason-level-read.py --hours 24
    python3 scripts/skip-reason-level-read.py --self-test     # proves it can go RED
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter

DB = "prisma/dev.db"


def _levels(rows):
    """Return the measurement for a list of (risksJson, reasonsJson) tuples.

    L3 (within-row duplicates) is what separates the two levels. It is counted
    from the parsed keys, exactly as research-collect.py builds its counters, so
    the two implementations agree by measurement rather than by assumption.
    """
    ent: Counter = Counter()
    dec: Counter = Counter()
    entries = 0
    dups = 0
    multi = 0
    bare = 0
    for r in rows:
        items = []
        for raw in r:
            try:
                j = json.loads(raw or "[]")
            except Exception:  # noqa: BLE001
                continue
            cand = j if isinstance(j, list) else (
                list(j.values()) if isinstance(j, dict) else [])
            if cand:
                items = cand
                break
        if not items:
            bare += 1
            continue
        keys = [str(t)[:70] for t in items]
        entries += len(keys)
        if len(keys) > 1:
            multi += 1
        dup = len(keys) - len(set(keys))
        dups += dup
        for k in keys:
            ent[k] += 1
        for k in set(keys):
            dec[k] += 1
    return {
        "rows": len(rows),
        "bare": bare,
        "tagged": len(rows) - bare,
        "multi_tag_rows": multi,
        "entries": entries,
        "dups": dups,
        "ent": ent,
        "dec": dec,
    }


def _family(key: str) -> str:
    """Collapse a per-VALUE tag to its gate family, keeping the venue prefix."""
    venue = ""
    m = re.match(r"^(STANDARD|BANKROLL_200|C-200|C200):\s*", key)
    if m:
        venue = m.group(1) + ": "
        key = key[m.end():]
    if key.startswith("confidence "):
        return venue + "confidence (below min)"
    if key.startswith("resolves in "):
        return venue + "resolves-in (below min TTL)"
    if key.startswith("price drifted "):
        return venue + "price drifted (too late)"
    if key.startswith("coalesced into open copy"):
        return venue + "coalesced into open copy"
    if "blacklist category" in key:
        return venue + "blacklist category"
    return venue + key


def report(rows, top_n=10):
    m = _levels(rows)
    ent, dec = m["ent"], m["dec"]
    print("=== SKIP-REASON LEVELS ===")
    print(f"L1 population: refusals (DecisionJournal decision='skip'), {m['rows']} rows | "
          f"tagged {m['tagged']} | bare {m['bare']} | distinct tags {len(ent)}")
    print(f"L1 multi-tag rows: {m['multi_tag_rows']} of {m['tagged']} tagged rows "
          f"carry more than one risksJson entry")
    per_row = (m["entries"] / m["tagged"]) if m["tagged"] else 0.0
    print(f"L2 entries: {m['entries']} tag entries over {m['rows']} rows "
          f"({per_row:.2f} per tagged row) -> ENTRY-level totals "
          f"{'DO' if m['entries'] > m['rows'] else 'do NOT'} exceed the row count; "
          f"DECISION-level counts sum to {sum(dec.values())}, i.e. also "
          f"{'above' if sum(dec.values()) > m['rows'] else 'at'} the row count, "
          f"because one decision is counted once per distinct tag.")
    print(f"L3 within-row duplicate entries: {m['dups']} — this is the ONLY mechanism that can make "
          f"the two levels diverge.")
    disagree = [k for k in ent if ent[k] != dec.get(k, 0)]
    if m["dups"] == 0:
        print("VERDICT: levels AGREE on every tag (0 within-row duplicates). The two lists are the "
              "same numbers; DECISION level is the deduped view and here it dedupes nothing.")
    else:
        print(f"VERDICT: levels DIVERGE on {len(disagree)} tag(s): "
              + ", ".join(f"{k} dec={dec.get(k, 0)}/ent={ent[k]}" for k in disagree[:6]))
    print()
    print(f"--- top {top_n} by DECISION level ---")
    for k, v in dec.most_common(top_n):
        print(f"  {v:>6}  (entry {ent[k]:>6})  {k}")
    print(f"--- top {top_n} by ENTRY level ---")
    for k, v in ent.most_common(top_n):
        print(f"  {v:>6}  {k}")
    print()
    print("--- gate FAMILY rollup (decision level) — read THIS for 'which gate refuses most' ---")
    fam: Counter = Counter()
    for k, v in dec.items():
        fam[_family(k)] += v
    for k, v in fam.most_common(top_n):
        print(f"  {v:>6}  {k}")
    print()
    print("BASIS: every count above is refusal-level over the printed window on the printed "
          "level; per-tag keys are per-VALUE, so a per-tag count is not a gate count.")
    return m


def self_test() -> int:
    """A reconciliation that cannot report divergence is not a reconciliation.

    Case A: two decisions, one tag each, no repeats -> the levels must AGREE.
    Case B: one decision carrying the SAME tag twice -> DECISION 1, ENTRY 2, and
            the duplicate count must be exactly 1. If the detector cannot see
            this, its "0 duplicates" reading on live data means nothing.
    """
    a = _levels([(json.dumps(["price drifted 0.005 (too late)"]), None),
                 (json.dumps(["confidence 0.50 < min 0.7"]), None)])
    tag = 'v45 blacklist category "cs2"'
    b = _levels([(json.dumps([tag, tag]), None)])
    ok = (
        a["dups"] == 0
        and all(a["ent"][k] == a["dec"][k] for k in a["ent"])
        and b["dups"] == 1
        and b["ent"][tag] == 2
        and b["dec"][tag] == 1
        and b["entries"] == 2
        and b["rows"] == 1
    )
    seen = (b["dec"].get(tag), b["ent"].get(tag), b["dups"])
    print(f"self-test: no-repeat case agrees = {a['dups'] == 0}, "
          f"repeat case seen (dec/ent/dup) = {seen}")
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--hours", type=int, default=24 * 30)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    con = sqlite3.connect(a.db)
    since = int(time.time() * 1000) - a.hours * 3600 * 1000
    cols = [r[1] for r in con.execute("PRAGMA table_info(DecisionJournal)")]
    if not cols:
        print("DecisionJournal not found in", a.db)
        return 2
    print(f"window: {a.hours}h ending now, clock=DecisionJournal.createdAt (unix-ms), "
          f"level=refusal (decision='skip'), NO LIMIT (full window)")
    rows = con.execute(
        "SELECT risksJson, reasonsJson FROM DecisionJournal "
        "WHERE createdAt >= ? AND decision='skip' ORDER BY createdAt DESC", (since,)).fetchall()
    report(rows, a.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
