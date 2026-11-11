#!/usr/bin/env python3
"""approvals-intake -- normalise the three approval tag vocabularies into one store.

WHY THIS EXISTS
---------------
On 2026-11-11 the roadmap carried 64 `awaiting-approval`, 10 `needs-approval` and 30 `lane-a` cards.
The approval-alert job keys only on the first and `lane-a`, so the `needs-approval` cards had never
pinged. Approvals were a presentation concern in four places and a state concern in none.

This script is the ONE writer of `data/approvals.json`. It is cron-driven so the queue exists whether
or not a session remembers to build it.

DECISION STICKINESS: an item already `approved` or `declined` keeps its status, decision time and
kanban task id forever. Re-running intake only ever ADDS pending items and refreshes their text.

READ: data/roadmap.json only.  WRITE: data/approvals.json only.
"""
from __future__ import annotations

import json
import os
import re
import sys
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROADMAP = os.path.join(ROOT, "data", "roadmap.json")
STORE = os.path.join(ROOT, "data", "approvals.json")

PENDING_TAGS = {"awaiting-approval", "needs-approval", "lane-a"}

# The board is a SECOND source: a blocked card is a decision nobody made. Its approve action differs
# from a roadmap item's (unblock vs create), so each item carries `origin`.
KANBAN_DB = os.path.expanduser("~/.hermes/kanban/boards/medusa/kanban.db")

# A card whose note records its own closure is not a pending decision, whatever its tags say.
CLOSED_MARKERS = (
    "APPLIED", "DONE 2026", "CLOSED 2026", "REFUTED", "WITHDRAWN", "CORRECTED AND CLOSED",
    "NOTHING APPLIED",  # a proposal that was explicitly never applied is still OPEN, see below
)
# "NOTHING APPLIED" means the decision is still open, so it must NOT be treated as closed.
CLOSED_MARKERS = tuple(m for m in CLOSED_MARKERS if m != "NOTHING APPLIED")


def tags_of(card):
    t = card.get("tags")
    if isinstance(t, list):
        return {str(x).strip().lower() for x in t}
    if isinstance(t, str):
        return {x.strip().strip("'\"").lower() for x in t.strip("[]").split(",") if x.strip()}
    return set()


def first_sentence(text, limit=320):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return cut.rsplit(" ", 1)[0] + " …"


def extract(note, keys):
    """Pull the first line whose text mentions any of `keys`; empty when absent."""
    for raw in re.split(r"(?<=[.;])\s+|\n", str(note or "")):
        low = raw.lower()
        if any(k in low for k in keys):
            return first_sentence(raw, 400)
    return ""


def build_item(card):
    cid = str(card.get("id") or "").strip()
    if not cid:
        return None
    title = str(card.get("title") or cid).strip()
    note = card.get("note") or ""
    tags = tags_of(card)
    lane = "A" if ("lane-a" in tags or "LANE A" in title.upper()) else "B"
    return {
        "id": f"apr-{cid}",
        "lane": lane,
        "status": "pending",
        "title": first_sentence(title, 200),
        "proposal": first_sentence(note, 700) or first_sentence(title, 300),
        "evidence": extract(note, ("measured", "before:", "after:", "refutation", "decision rule")),
        "revert": extract(note, ("revert", "rollback", "undo", "reversib", "reversal")),
        "source": f"roadmap:{cid}",
        "createdAt": None,
        "decidedAt": None,
        "decidedVia": None,
        "kanbanTaskId": None,
        "_card_dates": str(card.get("dates") or ""),
        "_column": str(card.get("column") or ""),
    }


def kanban_blocked_items(existing):
    """Blocked board cards are pending decisions. Read-only; sqlite is opened immutable."""
    import sqlite3

    if not os.path.exists(KANBAN_DB):
        return []
    out = []
    try:
        con = sqlite3.connect(f"file:{KANBAN_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, title, body, block_kind, COALESCE(last_failure_error,'') AS err "
            "FROM tasks WHERE status='blocked' ORDER BY COALESCE(started_at, 0) DESC"
        ).fetchall()
        con.close()
    except Exception as exc:
        print(f"kanban source unavailable ({exc}); roadmap items only", file=sys.stderr)
        return []

    for r in rows:
        iid = f"apr-{r['id']}"
        body = str(r["body"] or "")
        kind = str(r["block_kind"] or "")
        out.append({
            "id": iid,
            "lane": "A" if ("LANE A" in str(r["title"]).upper() or "APPROVAL" in str(r["title"]).upper()) else "B",
            "status": "pending",
            "title": first_sentence(r["title"], 200),
            "proposal": first_sentence(body, 700) or first_sentence(r["title"], 300),
            "evidence": extract(body, ("measured", "before:", "after:", "decision rule", "refutation")),
            "revert": extract(body, ("revert", "rollback", "undo", "reversib", "reversal")),
            "source": f"kanban:{r['id']}",
            "origin": "kanban",
            "blockKind": kind,
            "createdAt": None, "decidedAt": None, "decidedVia": None, "kanbanTaskId": r["id"],
        })
    return out


def main():
    with open(ROADMAP) as fh:
        raw = json.load(fh)
    cards = raw if isinstance(raw, list) else raw.get("cards", [])

    existing = {}
    if os.path.exists(STORE):
        try:
            with open(STORE) as fh:
                prior = json.load(fh)
            for it in prior.get("items", []):
                if it.get("id"):
                    existing[it["id"]] = it
        except Exception as exc:  # a corrupt store must not silently wipe decisions
            print(f"REFUSING TO CONTINUE: {STORE} is unreadable ({exc}). Decisions live here.", file=sys.stderr)
            return 1

    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    items, skipped_closed, added, kept = [], 0, 0, 0

    for card in cards:
        tags = tags_of(card)
        if not (tags & PENDING_TAGS):
            continue
        blob = f"{card.get('title','')} {card.get('note','')}".upper()
        if any(m in blob for m in CLOSED_MARKERS):
            skipped_closed += 1
            continue
        item = build_item(card)
        if not item:
            continue
        prior = existing.get(item["id"])
        if prior:
            # Sticky decisions: never reset what the operator already answered.
            for key in ("status", "decidedAt", "decidedVia", "kanbanTaskId"):
                item[key] = prior.get(key)
            item["createdAt"] = prior.get("createdAt") or now
            kept += 1
        else:
            item["createdAt"] = now
            added += 1
        items.append(item)

    # Items created directly (not from a roadmap card) survive intake untouched.
    for iid, it in existing.items():
        if not any(i["id"] == iid for i in items):
            items.append(it)

    # Second source: blocked board cards. Sticky decisions apply here too.
    for item in kanban_blocked_items(existing):
        prior = existing.get(item["id"])
        if prior and prior.get("status") in ("approved", "declined"):
            item.update({k: prior.get(k) for k in ("status", "decidedAt", "decidedVia")})
        else:
            item["status"] = "pending"
        item["createdAt"] = (prior or {}).get("createdAt") or now
        if not any(i["id"] == item["id"] for i in items):
            items.append(item)

    order = {"pending": 0, "approved": 1, "declined": 2}
    items.sort(key=lambda i: (order.get(i.get("status"), 3), str(i.get("createdAt") or "")))
    pending = [i for i in items if i.get("status") == "pending"]

    store = {
        "version": 1,
        "updatedAt": now,
        "counts": {
            "pending": len(pending),
            "approved": sum(1 for i in items if i.get("status") == "approved"),
            "declined": sum(1 for i in items if i.get("status") == "declined"),
        },
        "items": items,
    }
    tmp = STORE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(store, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, STORE)

    print(f"approvals-intake: {len(items)} items | pending {store['counts']['pending']} "
          f"| new {added} | refreshed {kept} | skipped-closed {skipped_closed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
