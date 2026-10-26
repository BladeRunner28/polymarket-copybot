#!/usr/bin/env python3
"""
Deterministic signature of the PENDING-APPROVAL set, for gating a cron job.

WHY: the user wants approval requests "as they come up" AND a 09:00/20:00 digest. A job that simply
runs often would notify on every tick whether or not anything changed. This prints ONLY the approval
queue, in a stable order, with no timestamps and no volatile fields — so a cron `monitor` can skip the
LLM run entirely while the set is unchanged and wake it the moment a NEW approval item appears.

An approval item is a roadmap card carrying the `awaiting-approval` tag. The worker adds that tag when
it finishes preparing a Lane A proposal; it never removes it. When the user says yes, the worker
retires the tag and records the decision, which is itself a signature change (correctly — an approval
leaving the queue is worth knowing about).

Output contract: one line per item, `<id> | <title>`; empty string when the queue is empty. Must stay
deterministic or every tick will look changed.
"""
import json
import os
import sys

def _find_repo_root(start: str) -> str:
    """Walk up until data/roadmap.json exists.

    The script lives in scripts/cron-gates/, so counting dirname() levels is fragile — the first
    version counted two and resolved to scripts/, where roadmap.json does not exist and the gate
    reported SIGNATURE-ERROR on a perfectly good repo. Search for the marker instead.
    """
    p = os.path.abspath(start)
    for _ in range(8):
        if os.path.isfile(os.path.join(p, "data", "roadmap.json")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return os.path.dirname(os.path.dirname(os.path.abspath(start)))


ROOT = _find_repo_root(os.path.dirname(os.path.abspath(__file__)))
CARD = os.path.join(ROOT, "data", "roadmap.json")


def main() -> int:
    try:
        with open(CARD) as f:
            d = json.load(f)
    except Exception as e:  # never print a half-truth: a broken read is its own signal
        print("SIGNATURE-ERROR: cannot read roadmap.json: %s" % e)
        return 0

    items = []
    for c in d.get("cards", []):
        tags = [str(t) for t in (c.get("tags") or [])]
        if "awaiting-approval" in tags:
            items.append((str(c.get("id", "")), str(c.get("title", ""))[:110]))

    if not items:
        print("")
        return 0

    for cid, title in sorted(items):
        print("%s | %s" % (cid, title))
    return 0


if __name__ == "__main__":
    sys.exit(main())
