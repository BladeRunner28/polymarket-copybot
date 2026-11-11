#!/usr/bin/env python3
"""
Deterministic signature of the PENDING set in the approvals STORE, for gating a cron job.

WHY THIS EXISTS (approved 2026-11-11, "yes, the 30 min alert should wake off of approvals.json"):
The alert used to key on roadmap tags via approval-queue-signature.py. Since 2026-11-11 the authority
on "what is waiting" is `data/approvals.json`, written hourly by `scripts/approvals-intake.py`, which
normalises THREE tag vocabularies (awaiting-approval, needs-approval, lane-a) plus blocked board cards.
Keying the wake on the old tag gate while the operator decides in the store means the store can change
without the alert ever firing -- and the old gate never saw the 10 cards tagged `needs-approval` at all.

CONTRACT (identical to the old gate so the monitor behaves the same way):
- one line per PENDING item, in a stable sorted order: `<id> | <lane> | <title>`
- empty stdout when nothing is pending -> the "queue clear" tick
- an absent or unreadable store prints a DETERMINISTIC token and exits 0: the cron monitor compares
  stdout between ticks, and a moving error string would look like a change on every run
- `no-resurface` outranks visibility: a card explicitly told not to re-surface stays in the store and
  stays decidable, but never pings again (exactly one card carries that tag today)

READ-ONLY. This script never writes the store.
"""
import json
import os
import sys


def _find_repo_root(start: str) -> str:
    """Walk up until data/roadmap.json exists, rather than counting dirname() levels."""
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
STORE = os.path.join(ROOT, "data", "approvals.json")
CARDS = os.path.join(ROOT, "data", "roadmap.json")


def _no_resurface_cards():
    """Card ids explicitly silenced. Absent/unreadable roadmap => empty set (fail open to VISIBLE)."""
    try:
        with open(CARDS) as fh:
            cards = json.load(fh).get("cards", [])
    except Exception:
        return set()
    out = set()
    for c in cards:
        if "no-resurface" in [str(t) for t in (c.get("tags") or [])]:
            out.add(str(c.get("id", "")))
    return out


def _source_card(item):
    """`roadmap:<card id>` or `kanban:<task id>` -> (kind, id)."""
    src = str(item.get("source") or "")
    if ":" in src:
        kind, _, ident = src.partition(":")
        return kind, ident
    return "", ""


def main() -> int:
    try:
        with open(STORE) as fh:
            store = json.load(fh)
    except Exception as e:  # never print a half-truth: a broken read is its own signal
        print("SIGNATURE-ERROR: cannot read approvals.json: %s" % e)
        return 0

    silenced = _no_resurface_cards()
    rows = []
    for item in store.get("items", []) or []:
        if str(item.get("status") or "pending") != "pending":
            continue
        kind, ident = _source_card(item)
        # no-resurface is a roadmap-card property; board cards have no such tag.
        if kind == "roadmap" and ident in silenced:
            continue
        rows.append(
            "%s | %s | %s"
            % (
                str(item.get("id", "")),
                str(item.get("lane") or "?"),
                str(item.get("title", ""))[:110],
            )
        )

    if not rows:
        print("")
        return 0

    for line in sorted(rows):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
