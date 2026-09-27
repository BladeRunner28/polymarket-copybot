#!/usr/bin/env python3
"""Idempotent roadmap-card appender for data/roadmap.json.

Usage:  python3 scripts/roadmap-add-card.py card.json     # card.json = one card object
        python3 scripts/roadmap-add-card.py --list         # ids + columns only

Rules this enforces (see the polymarket-copybot-ops skill):
  * backs up to data/roadmap.json.bak-<reason> before any write
  * ONE read-modify-write, idempotent by `id` (re-running cannot duplicate a card)
  * refuses a card whose id already exists with a DIFFERENT column unless --move is given
  * re-reads the file and asserts the append landed before exiting 0
"""
from __future__ import annotations

import json
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


def main() -> int:
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
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

    missing = [k for k in REQUIRED if k not in card]
    if missing:
        sys.exit(f"card missing required keys: {missing}")

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
    tmp = ROADMAP.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
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
