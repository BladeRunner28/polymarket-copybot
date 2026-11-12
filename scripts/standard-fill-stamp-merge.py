#!/usr/bin/env python3
"""Merge two standard-fill-stamp snapshots into ONE union snapshot (newer wins per leg id).

Standalone (read-only in, one file out):
    python3 scripts/standard-fill-stamp-merge.py OLD.jsonl NEW.jsonl OUT.jsonl

Why it exists: the STANDARD fill booth (scripts/standard-fill-stamp.ts) APPENDS a snapshot per
run. Each run only stamps the legs inside its own --since-ms window, so the newest line alone is
not the evidence set — the union is. This script folds the new snapshot into the union file
(data/standard-fill-stamp.jsonl) that scripts/standard-fill-aware-basis-split.py and
scripts/standard-fill-aware-rerebook.py read (both take the LAST snapshot line).

Rules
  * union by leg id: the newer snapshot wins — EXCEPT that a leg the new run could NOT stamp
    (book == null) never erases a stamp the old snapshot already had. Evidence beats absence;
    the alternative silently shrinks coverage whenever one tick misses the L2 window.
  * the merged line keeps the new snapshot's aggregate blocks (book/tape/refutation/coverage),
    because those describe ONE run, and declares what they cover via `aggregatesCover` so the
    file cannot be misread as aggregates over the whole union.
  * OLD missing/empty (first ever merge) => union = new.
  * the write is atomic (tmp + os.replace) so a crash cannot leave a torn union; OLD and OUT may
    be the same path.

Stdout: one human line, then one machine line the cron chain parses:
    MERGE old=<n> new=<n> union=<n> added=<n> addedStamped=<n> upgraded=<n> keptOldEvidence=<n> restamped=<n>
  added            leg ids the union did not have
  addedStamped     ... of which the new run stamped (book != null)
  upgraded         ids in both, old had no book, new does
  keptOldEvidence  ids in both, new had no book, old did (the rule above)
  restamped        ids in both with book on both sides whose firstAsk value changed
"""
import json
import os
import sys
import tempfile
from collections import Counter


def last_snap(p):
    if not p or not os.path.exists(p):
        return None
    last = None
    for line in open(p, encoding="utf8"):
        t = line.strip()
        if not t:
            continue
        try:
            o = json.loads(t)
        except json.JSONDecodeError:
            continue  # a torn line is not a snapshot
        if isinstance(o.get("legs"), list):
            last = o
    return last


def first_ask(leg):
    b = leg.get("book")
    return None if not b else b.get("firstAsk")


def main():
    if len(sys.argv) != 4:
        sys.exit("usage: standard-fill-stamp-merge.py OLD.jsonl NEW.jsonl OUT.jsonl")
    old_p, new_p, out_p = sys.argv[1], sys.argv[2], sys.argv[3]

    old, new = last_snap(old_p), last_snap(new_p)
    if new is None:
        sys.exit(f"[stamp-merge] no snapshot in {new_p} — nothing to merge")
    if old is None:
        old = {"legs": []}

    merged, stats = {}, Counter()
    for l in old["legs"]:
        if l.get("id"):
            merged[l["id"]] = dict(l, _src="old")
    old_ids = set(merged)

    for leg in new["legs"]:
        lid = leg.get("id")
        if not lid:
            continue
        fresh = dict(leg, _src="new")
        if lid not in merged:
            stats["added"] += 1
            if fresh.get("book"):
                stats["addedStamped"] += 1
            merged[lid] = fresh
            continue
        prev = merged[lid]
        if fresh.get("book"):
            if not prev.get("book"):
                stats["upgraded"] += 1
            elif first_ask(fresh) != first_ask(prev):
                stats["restamped"] += 1
            merged[lid] = fresh
        else:
            if prev.get("book"):
                stats["keptOldEvidence"] += 1
            # keep the old record either way: same absence, older provenance is the better trace
    # re-stamp provenance: a leg kept from the old snapshot is 'old', a leg replaced is 'new'
    legs = [dict(l) for l in merged.values()]

    out = dict(new)  # newest snapshot's book/tape/refutation/coverage blocks
    out["legs"] = legs
    out["mergedFrom"] = {"old": (old.get("ranAt")), "new": new.get("ranAt")}
    out["ranAt"] = new.get("ranAt")
    out["unionLegs"] = len(legs)
    out["aggregatesCover"] = {
        "note": "book/tape/refutation/coverage above describe the newest snapshot run ONLY, not the union",
        "legs": len(new["legs"]),
        "scopeSinceMs": (new.get("coverage") or {}).get("scopeSinceMs"),
        "ranAt": new.get("ranAt"),
    }
    out["mergeStats"] = dict(stats)

    d = os.path.dirname(os.path.abspath(out_p))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".stamp-merge-", suffix=".jsonl")
    try:
        with os.fdopen(fd, "w", encoding="utf8") as fh:
            fh.write(json.dumps(out) + "\n")
        os.chmod(tmp, 0o644)  # mkstemp creates 0600; the artifact is a shared repo file
        os.replace(tmp, out_p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    print(
        f"old legs {len(old['legs'])} · new legs {len(new['legs'])} · union {len(legs)} "
        f"· added {stats['added']} (stamped {stats['addedStamped']}) · upgraded {stats['upgraded']} "
        f"· kept old evidence {stats['keptOldEvidence']}"
    )
    print(
        "MERGE "
        f"old={len(old['legs'])} new={len(new['legs'])} union={len(legs)} "
        f"added={stats['added']} addedStamped={stats['addedStamped']} upgraded={stats['upgraded']} "
        f"keptOldEvidence={stats['keptOldEvidence']} restamped={stats['restamped']}"
    )
    print("per-source", Counter(l.get("_src") for l in legs))


if __name__ == "__main__":
    main()
