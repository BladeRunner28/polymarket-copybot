#!/usr/bin/env python3
"""Idempotent roadmap-card appender for data/roadmap.json.

Usage:  python3 scripts/roadmap-add-card.py card.json     # card.json = one card object
        python3 scripts/roadmap-add-card.py --list         # ids + columns only
        python3 scripts/roadmap-add-card.py --audit        # report non-conforming cards (read-only)
        python3 scripts/roadmap-add-card.py --self-test    # arms for the type check

Rules this enforces (see the polymarket-copybot-ops skill):
  * backs up to data/roadmap.json.bak-<reason> before any write
  * ONE read-modify-write, idempotent by `id` (re-running cannot duplicate a card)
  * refuses a card whose id already exists with a DIFFERENT column unless --move is given
  * TYPE-CHECKS the card (added 2026-11-22, card roadmap-note-schema-defect): `note` must be a
    JSON string and `tags` a list of strings. Before this the writer only checked that the KEYS
    were present, so an array-valued `note` was accepted and landed in the file (one such legacy
    row, tr39-print-type-ingest-guard, crashed every reader that assumed a string). Readers are
    written against `note` being a str, so the hole belonged in the writer.
  * re-reads the file and asserts the append landed before exiting 0

CLEAN BASELINE: `--audit` prints `0 of N non-conforming` on the corpus as of 2026-11-22, because
the same pass re-shaped the legacy array `note` and added `tags: []` to the 7 cards that carried no
tags key (every reader resolves tags as `c.get("tags") or []`, so absent and [] are the same value
to all of them). That baseline is the point: any row `--audit` names from now on is a REAL defect
rather than one of eight permanently-known ones -- an alarm with standing reds gets ignored.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROADMAP = ROOT / "data" / "roadmap.json"
REQUIRED = ("id", "title", "column", "note", "tags")


def load() -> dict:
    with ROADMAP.open() as fh:
        d = json.load(fh)
    if "columns" not in d or "cards" not in d:
        sys.exit(f"unexpected roadmap shape: {list(d)}")
    return d


def card_problems(card) -> list[str]:
    """Every reason this card must not be written. Empty list == conforming.

    The checks are TYPE checks on purpose: a card can be worded any way at all, but a reader that
    does `' '.join(note)` or `for t in tags` needs the shape to hold. Each message names the key so
    a refusal is actionable rather than mysterious.
    """
    if not isinstance(card, dict):
        return ["card is not a JSON object (got %s)" % type(card).__name__]
    problems: list[str] = []
    for key in REQUIRED:
        if key not in card:
            problems.append(f"missing required key {key!r}")
    for key in ("id", "title", "column"):
        if key in card and (not isinstance(card[key], str) or not card[key].strip()):
            problems.append("`%s` must be a non-empty string, got %r" % (key, card[key]))
    if "note" in card and not isinstance(card["note"], str):
        problems.append(
            "`note` must be a JSON string, got %s — readers do ' '.join/.lower()/slicing on it"
            % type(card["note"]).__name__
        )
    if "tags" in card:
        tags = card["tags"]
        if not isinstance(tags, list):
            problems.append("`tags` must be a list of strings, got %s" % type(tags).__name__)
        else:
            bad = [t for t in tags if not isinstance(t, str)]
            if bad:
                problems.append("`tags` must be a list of strings; non-string entries: %r" % (bad[:3],))
    return problems


def audit() -> int:
    """Read-only scan of the live file. Prints non-conforming cards; never writes."""
    d = load()
    bad = []
    for c in d["cards"]:
        p = card_problems(c)
        if p:
            bad.append((c.get("id"), p))
    for cid, problems in bad:
        print(f"{cid}: " + "; ".join(problems))
    print(f"-- {len(bad)} of {len(d['cards'])} cards non-conforming (read-only, nothing written)")
    return 0


def self_test() -> int:
    arms = []

    def chk(name, cond, detail=""):
        arms.append((name, bool(cond), detail))

    good = {"id": "x", "title": "t", "column": "Done", "note": "a note", "tags": ["lane-b"]}
    chk("accepts a conforming card", card_problems(good) == [], str(card_problems(good)))
    # a note that merely LOOKS like a list must pass: the check is on type, not content
    chk("accepts a string note whose text looks like an array",
        card_problems({**good, "note": "['a','b']"}) == [])
    chk("accepts an empty tags list (absent tags read as [] everywhere)",
        card_problems({**good, "tags": []}) == [])
    # an empty note is still a STRING: content is the author's business, shape is the writer's
    chk("accepts an empty-string note (type-conforming; content is not this writer's job)",
        card_problems({**good, "note": ""}) == [])

    # Type-defect fixtures: every required KEY is present, only the SHAPE is wrong. These are the
    # cards the pre-2026-11-22 writer accepted and wrote into the file.
    type_rejects = [
        ("rejects an array note (the legacy tr39 shape)", {**good, "note": ["line one"]}),
        ("rejects a dict note", {**good, "note": {"a": 1}}),
        ("rejects a numeric note", {**good, "note": 12}),
        ("rejects a null note", {**good, "note": None}),
        ("rejects tags given as a bare string", {**good, "tags": "lane-b"}),
        ("rejects tags containing a non-string", {**good, "tags": ["lane-b", 7]}),
        ("rejects a null tags value", {**good, "tags": None}),
        ("rejects a non-string column", {**good, "column": ["Done"]}),
        ("rejects a blank id", {**good, "id": "   "}),
    ]
    # Key-defect fixtures: the pre-fix writer already refused these for the missing key alone.
    key_rejects = [
        ("rejects a missing note key", {k: v for k, v in good.items() if k != "note"}),
        ("rejects a missing tags key", {k: v for k, v in good.items() if k != "tags"}),
    ]

    for name, bad in type_rejects + key_rejects:
        chk(name, card_problems(bad) != [], str(card_problems(bad)[:1]))
        # A reject arm is only meaningful if the card differs from the accepted one in EXACTLY ONE
        # key. If a future arm drifts into a multi-defect fixture it could pass for the wrong reason.
        diff = {k for k in set(good) | set(bad) if good.get(k) != bad.get(k)}
        chk(name + " -- differs from the accepted card in one key only", len(diff) == 1, str(sorted(diff)))

    # MUTATION PROOF: the writer as it stood before 2026-11-22 checked PRESENCE only. Every
    # type-defect fixture must be ACCEPTED by that pre-fix logic and REJECTED by the new check,
    # otherwise an arm could be passing for an unrelated reason.
    def pre_fix_writer(card):
        return ["missing required key %r" % k for k in REQUIRED if k not in card]

    for name, bad in type_rejects:
        chk("MUTATION: pre-fix presence-only writer accepts " + name, pre_fix_writer(bad) == [],
            str(pre_fix_writer(bad)))
    chk("the new check catches all %d types the pre-fix writer let through" % len(type_rejects),
        all(card_problems(bad) != [] for _, bad in type_rejects))
    chk("MUTATION: pre-fix writer still refuses the missing-key fixtures (control)",
        all(pre_fix_writer(bad) != [] for _, bad in key_rejects))

    bad_arms = [a for a in arms if not a[1]]
    for name, _ok, detail in arms:
        if not _ok:
            print(f"RED  {name}  {detail}")
    print("-- %d/%d self-test arms green" % (len(arms) - len(bad_arms), len(arms)))
    return 1 if bad_arms else 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if args[0] == "--self-test":
        return self_test()
    if args[0] == "--audit":
        return audit()
    if args[0] == "--list":
        d = load()
        for c in d["cards"]:
            print(f"{c['column']:<12} {c['id']}")
        print(f"-- {len(d['cards'])} cards, columns: {d['columns']}")
        return 0

    card = json.loads(Path(args[0]).read_text())
    move = "--move" in args
    reason = "roadmap-add-card"
    if "--reason" in args:
        reason = args[args.index("--reason") + 1]

    problems = card_problems(card)
    if problems:
        sys.stderr.write("card refused -- schema is enforced before any write:\n")
        for p in problems:
            sys.stderr.write(f"  - {p}\n")
        return 2

    d = load()
    if card["column"] not in d["columns"]:
        sys.exit(f"unknown column {card['column']!r}; allowed: {d['columns']}")

    existing = next((c for c in d["cards"] if c["id"] == card["id"]), None)
    if existing is not None:
        if existing.get("column") == card["column"] and not move:
            print(f"idempotent: card {card['id']} already present in {card['column']} — no write")
            return 0
        if not move:
            sys.exit(
                f"card {card['id']} exists in {existing['column']} (want {card['column']}); "
                "re-run with --move to replace it"
            )
        # replace in place, preserving order
        idx = d["cards"].index(existing)
        d["cards"][idx] = card
        action = "moved/replaced"
    else:
        d["cards"].append(card)
        action = "appended"

    bak = ROADMAP.with_name(f"roadmap.json.bak-{reason}-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(ROADMAP, bak)
    # FORMAT-PRESERVING WRITE (fixed 2026-10-27). This used to hardcode indent=1 and
    # ensure_ascii=False, but data/roadmap.json is indent=2 with \uXXXX escapes: every run
    # rewrote all 743 KB, so a two-card edit arrived as a 7,292-line diff that hid the actual
    # change from review. Match the file's own formatting instead of imposing one.
    raw = ROADMAP.read_text()
    m = re.search(r'\n( +)"', raw)
    indent = len(m.group(1)) if m else 2
    trailing = "\n" if raw.endswith("\n") else ""
    # ENCODING is part of the format too (fixed 2026-10-31). The file flipped from \uXXXX
    # escapes to literal UTF-8 at some point; ensure_ascii=True then re-escaped all 570
    # em-dashes on the next card edit, and a two-card change arrived as a 704-line diff.
    # Match whatever the file already does.
    ensure_ascii = not any(ord(ch) > 127 for ch in raw)
    tmp = ROADMAP.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=indent, ensure_ascii=ensure_ascii) + trailing)
    tmp.replace(ROADMAP)

    back = load()
    ids = [c["id"] for c in back["cards"]]
    assert card["id"] in ids, "append did not land"
    assert back["columns"] == d["columns"], "columns changed"
    got = next(c for c in back["cards"] if c["id"] == card["id"])
    assert got == card, "stored card differs from input"
    print(f"{action}: {card['id']} -> {card['column']} | now {len(back['cards'])} cards | bak {bak.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
