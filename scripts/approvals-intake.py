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
#
# 2026-11-11: the first version tested `marker in blob` on the uppercased title+note. That closes a
# card whenever the CONTRARY text appears anywhere in it, and the corpus is full of it: "NOTHING
# APPLIED -- AWAITING A ONE-WORD CHOICE", "PROPOSED 2026-10-27, NOTHING APPLIED", "REFUTED IF <=52%"
# (a pre-registered kill clause present in almost every Lane A proposal). Measured on the live board:
# 40 cards carried a pending tag, 29 were dropped, and at least 6 of the 29 say in plain text that no
# decision was made. Closure evidence is now restricted to STAMPS, and negated/conditional text is
# rejected. Anything else stays pending, which is the safe direction: a hidden decision never gets made.
CLOSED_MARKERS = ("APPLIED", "DONE 2026", "CLOSED 2026", "REFUTED", "WITHDRAWN")
# "REFUTED IF ..." / "DONE IF ..." is a pre-registered condition, not a verdict.
CONDITIONAL = re.compile(r"^[\s\-—:]*IF\b", re.I)
# A title that opens with a verdict, or names one after the em-dash ("... esports bleed — NO CUT (...)"
# or "... 2 -> 24 (APPROVED 2026-10-23; ...)"), is closed regardless of note prose.
TITLE_VERDICT = re.compile(
    r"(?:^|[—–:]\s*|\()"
    r"(DONE|CLOSED|APPLIED|REFUTED|WITHDRAWN|SHIPPED|NO\s+CUT|NO\s+CHANGE|REFUSED|DECLINED|APPROVED)\b",
    re.I,
)
# A tag that asserts work finished. Prefix match so "shipped-2026-10-27" counts.
CLOSED_TAGS = ("done", "closed", "withdrawn", "activated", "shipped", "applied", "refuted", "refused", "declined")


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


def closure_evidence(card):
    """Why this card counts as decided, or '' when it is still a pending decision.

    Returns an auditable string, not a bare bool: the queue has to be able to say WHY a card it
    dropped is not a decision. Structural signals (tag, title verdict) win; note prose only counts
    when the marker is a stamp -- not negated and not a "… IF" clause.
    """
    tags = tags_of(card)
    for prefix in CLOSED_TAGS:
        hit = sorted(t for t in tags if t == prefix or t.startswith(prefix))
        if hit:
            return f"tag:{hit[0]}"
    title = str(card.get("title") or "")
    m = TITLE_VERDICT.search(title)
    if m:
        return f"title:{m.group(1).upper()}"
    # Note prose: only a STAMP counts, i.e. a segment that opens with the marker
    # ("--- APPLIED AND VERIFIED 2026-10-22"). A marker buried mid-sentence is prose about some other
    # thing that shipped -- measured on the live board, "APPLIED"/"SHIPPED" mid-sentence were the
    # single most common false-closure signal (ml1-price-baseline-drift: instrument shipped, BAR
    # pending; category-seats-never-released: the C-200 half shipped, the seat release did not).
    # 2026-11-12 FIX — the separator class used to be `+`, i.e. a stamp had to be PRECEDED by one of
    # those characters. But the splitter above consumes whitespace (`\s+` after a sentence, `\n` for a
    # line), so no segment ever BEGINS with whitespace: a note line that opens exactly on the stamp
    # ("...not claimed falsely.\n\nDONE 2026-11-09 (Lane B ...)") could never match, and only stamps
    # behind a literal dash/marker ("--- APPLIED ...") did. Measured consequence: card
    # polyterm-p1-provenance-persistence sat in column Done with a `needs-approval` tag after its work
    # shipped and verified, entered the queue as a PENDING decision, and the operator's approve on it
    # spawned a kanban task for work already committed — a real decision slot spent on a closed card.
    # The separator is now OPTIONAL, which changes nothing about what counts as a stamp (still a
    # segment-leading verdict, still not a "… IF" clause): re-measured across the 41 pending-tagged
    # cards, this closes exactly that one card and leaves the other 40 untouched.
    STAMP = re.compile(r"^[\s\-—–:|*]*(" + "|".join(CLOSED_MARKERS) + r")\b")
    for seg in re.split(r"(?<=[.;])\s+|\n", str(card.get("note") or "")):
        up = seg.strip().upper()
        if not up:
            continue
        m2 = STAMP.match(up)
        if not m2:
            continue
        after = up[m2.end():]
        if CONDITIONAL.match(after):
            continue              # "REFUTED IF <=52%" is a kill criterion, not a verdict
        return f"note:{m2.group(1)}"
    return ""


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
        # A missing board is not "no blocked cards": four of the thirty pending items come from here,
        # and before 2026-11-11 this returned [] so the board half of the queue vanished silently.
        print(f"FATAL: kanban board missing at {KANBAN_DB}; refusing to write a queue that omits it",
              file=sys.stderr)
        raise SystemExit(1)
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
        # 2026-11-11: this used to print to stderr and return [], i.e. a renamed column or a locked DB
        # silently erased the board half of the queue while the run still exited 0. The roadmap half
        # cannot detect the loss, so fail the whole intake.
        print(f"FATAL: kanban source unreadable ({exc}); refusing to write a queue that omits "
              f"{KANBAN_DB}", file=sys.stderr)
        raise SystemExit(1)

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
    items, skipped_closed, added, kept = [], [], 0, 0

    for card in cards:
        tags = tags_of(card)
        if not (tags & PENDING_TAGS):
            continue
        reason = closure_evidence(card)
        if reason:
            # 2026-11-12 LABEL FIX: a DECIDED item is the record of the operator's choice, not pending
            # noise. Exclusion belongs to cards that closed before anyone decided them. Applying it to a
            # decided card archived the decision under "excluded" -- with a reason about the card's
            # downstream state, not his choice -- and made the page's Approved count lie: two approvals
            # (ledger-price-side-repair, wallet-category-fit-class-swap) vanished the moment their cards
            # were tagged applied after the approved work landed. Decided items are never excluded.
            prior_decided = existing.get(f"apr-{card.get('id')}")
            if prior_decided is not None and str(prior_decided.get("status")) in ("approved", "declined"):
                items.append(prior_decided)
                kept += 1
                continue
            skipped_closed.append({
                "id": f"apr-{card.get('id')}",
                "card": str(card.get("id") or ""),
                "title": first_sentence(card.get("title"), 120),
                "column": str(card.get("column") or ""),
                "reason": reason,
            })
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
    #
    # 2026-11-11: this block used to re-append EVERY roadmap item that was not rebuilt, so a card that
    # closed after intake had added it could never leave the queue -- the queue only ever grew. Two
    # cards that are shipped and tagged done (`profit-stop-060-carry`, `standard-maturity-size-factor`)
    # were still sitting there as pending decisions. A roadmap-sourced item whose card is now closed,
    # or whose card no longer exists, is retired instead of resurrected.
    rebuilt = {i["id"] for i in items}
    retired = []
    for iid, it in existing.items():
        if iid in rebuilt:
            continue
        if str(it.get("source") or "").startswith("roadmap:"):
            # Not rebuilt => the roadmap no longer asserts it as a pending decision (closed, tag
            # removed after an approval, or the card is gone). Either way it must leave the queue --
            # unless it was DECIDED, in which case it stays as the record of that decision.
            if str(it.get("status")) in ("approved", "declined"):
                items.append(it)
                continue
            retired.append({"id": iid, "card": str(it.get("source")).split(":", 1)[1],
                            "status": it.get("status"),
                            "why": "card closed, de-tagged or absent from the roadmap"})
            continue
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

    # Retirement history is kept: the queue must be able to show, days later, which decisions it
    # dropped and why. Without this a retirement is invisible the moment the store is rewritten.
    retired_history = []
    if os.path.exists(STORE):
        try:
            with open(STORE) as fh:
                retired_history = (json.load(fh).get("retired") or [])[-40:]
        except Exception:
            retired_history = []
    seen = {r.get("id") for r in retired_history}
    for r in retired:
        r["at"] = now
        if r["id"] not in seen:
            retired_history.append(r)

    store = {
        "version": 1,
        "updatedAt": now,
        "counts": {
            "pending": len(pending),
            "approved": sum(1 for i in items if i.get("status") == "approved"),
            "declined": sum(1 for i in items if i.get("status") == "declined"),
            "excluded": len(skipped_closed),
            "retired": len(retired_history),
        },
        "items": items,
        # Every tagged card this run dropped, with the reason it was dropped. Before 2026-11-11 the
        # count was printed and the names were not, so a wrong exclusion was unfalsifiable.
        "excluded": skipped_closed,
        "retired": retired_history,
    }
    tmp = STORE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(store, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, STORE)

    print(f"approvals-intake: {len(items)} items | pending {store['counts']['pending']} "
          f"| new {added} | refreshed {kept} | excluded {len(skipped_closed)} | retired {len(retired)}")
    for e in skipped_closed:
        print(f"  excluded [{e['reason']}] {e['card']} ({e['column'] or 'no column'})")
    return 0


def self_test():
    """Prove the closure filter can still say YES and still says NO to the traps.

    Every case here is a real shape from the live roadmap. The negative controls matter more than
    the positive one: an over-eager closure filter silently hides decisions, which is the failure
    direction the 2026-11-11 note rewrite was written against.
    """
    cases = [
        # (label, card, expect_closed)
        ("stamp opens a new note line (the 2026-11-12 fix)",
         {"id": "x", "title": "some card", "tags": ["needs-approval"],
          "note": "CONTEXT: this shipped nothing; the card exists so the claim is not false.\n\nDONE 2026-11-09 (Lane B instrument repair, commit 61487e1)."}, True),
        ("stamp behind a dash still closes",
         {"id": "x", "title": "some card", "tags": ["needs-approval"],
          "note": "measured, then:\n--- APPLIED AND VERIFIED 2026-10-22"}, True),
        ("pre-registered kill clause is not a verdict",
         {"id": "x", "title": "some card", "tags": ["awaiting-approval"],
          "note": "REFUTED IF the CI straddles zero. Nothing applied."}, False),
        ("'nothing applied' is not a closure",
         {"id": "x", "title": "some card", "tags": ["awaiting-approval"],
          "note": "PROPOSED 2026-10-27, NOTHING APPLIED -- awaiting a one-word choice."}, False),
        ("mid-sentence 'shipped' is prose, not a stamp",
         {"id": "x", "title": "some card", "tags": ["awaiting-approval"],
          "note": "The instrument shipped 2026-10-27; the bar change is still pending."}, False),
        ("a pending card with no closure text stays pending",
         {"id": "x", "title": "some card", "tags": ["lane-a"],
          "note": "Cheap to finish. Decision and refutation below."}, False),
    ]
    ok = True
    for label, card, expect in cases:
        got = bool(closure_evidence(card))
        flag = "ok " if got == expect else "FAIL"
        if got != expect:
            ok = False
        print(f"  [{flag}] {label}: expected {'closed' if expect else 'pending'}, got "
              f"{'closed' if got else 'pending'} ({closure_evidence(card) or 'no evidence'})")
    print(f"self-test: {'PASS' if ok else 'FAIL'} ({len(cases)} cases)")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        raise SystemExit(self_test())
    raise SystemExit(main())
