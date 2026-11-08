#!/usr/bin/env python3
"""Persist and print the set of files the nightly git backup had to LEAVE OUT.

WHY: copybot-git-backup.sh has an oversize guard (GitHub hard-rejects any file over
100 MB, and the rejection kills the whole push). When it fires it unstages the file and
prints one ⚠️ line — then prints "✅ backed up N files" on the next line. Measured
2026-11-02: `data/wallet-sells.jsonl` passed 95 MB, was unstaged, and the run still
reported a clean ✅ for 197 files. That file is a TRACKED tape the user explicitly wants
in the repo; its backed-up copy is frozen at the 2026-11-01 commit (74.6 MB / 270,809
rows) while the file on disk is 108.9 MB / 395,616 rows. Every night from now on the
exclusion repeats, and nothing anywhere records how many nights it has been repeating.

This ledger is that record: one entry per excluded path with the date it was first
excluded, the number of nights it has been excluded, its last measured size, and the
last time the backup saw it. Nights are counted by DATE, not by run, so a re-run on the
same day cannot inflate the count — and it is counted, not guessed: `last` only moves
when a record for a different day arrives.

Contract:
  * no arguments -> print one line per currently-excluded path, then one INCOMPLETE line.
    Exit 0 even when the ledger is missing (nothing excluded is a valid state).
  * `--today YYYY-MM-DD path:bytes [path:bytes ...]` -> reconcile: record each given
    path (incrementing nights once per new day, bytes refreshed), DROP every entry not
    given (a file that fits again, or was untracked, must stop being reported as
    excluded), then print lines. An entry that is dropped prints a CLOSED line.
  * A malformed/unreadable ledger is an ERROR (exit 2), never silently reset to {} —
    resetting would restart every count at night 1 and hide a long exclusion.

Usage in the backup script: it passes the oversized paths it just unstaged.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 2026-11-08 (self-audit, Lane B): this defaulted to data/backup-exclusions.json, but the ONLY
# writer (scripts/cron-scripts/copybot-git-backup.sh) has always passed
# BACKUP_EXCLUSION_LEDGER=$repo/.backup-exclusions.json. So the documented invocation —
# `python3 scripts/backup-exclusion-ledger.py` with no args and no env — read a file that has
# never existed, found nothing, and printed NOTHING at all (silence, not "nothing excluded"),
# while the live ledger read `data/wallet-sells.jsonl ... nights: 5`. One source of truth now:
# the same path the backup writes. The env override is unchanged, so an explicit path still wins.
LEDGER = os.path.join(REPO, ".backup-exclusions.json")


def load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: expected a JSON object, got {type(doc).__name__}")
    for k, v in doc.items():
        if not isinstance(v, dict) or "first" not in v or "nights" not in v:
            raise ValueError(f"{path}: entry {k!r} is not a ledger record")
    return doc


def save(path: str, doc: dict) -> None:
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".excl-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(doc, fh, indent=1, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def mb(n: int) -> str:
    return f"{n / 1e6:.0f} MB"


def line_for(path: str, rec: dict) -> str:
    return (f"🗄️  backup EXCLUDED: {path} ({mb(int(rec.get('bytes') or 0))}) — on disk only, "
            f"excluded {rec['nights']} night(s) since {rec['first']}. "
            f"The last copy in git is from before {rec['first']}.")


def main(argv: list[str]) -> int:
    ledger = os.environ.get("BACKUP_EXCLUSION_LEDGER") or LEDGER
    args = list(argv[1:])
    today = None
    kept: dict[str, int] = {}
    if args and args[0] == "--today":
        if len(args) < 2:
            print("ERROR: --today needs a date", file=sys.stderr)
            return 2
        today = args[1]
        for spec in args[2:]:
            path, _, by = spec.rpartition(":")
            if not path or not by.isdigit():
                print(f"ERROR: bad path:bytes spec {spec!r}", file=sys.stderr)
                return 2
            kept[path] = int(by)
    elif args:
        print(f"ERROR: unknown arguments {args!r}", file=sys.stderr)
        return 2

    try:
        doc = load(ledger)
    except Exception as exc:
        print(f"ERROR: cannot read the exclusion ledger {ledger}: {exc} — the backup's "
              f"exclusion record is UNKNOWN, not empty", file=sys.stderr)
        return 2

    out: list[str] = []
    if today is not None:
        dropped = [p for p in doc if p not in kept]
        for p in sorted(dropped):
            out.append(f"✅ backup exclusion CLOSED: {p} is back inside the size guard "
                       f"(was excluded {doc[p]['nights']} night(s) since {doc[p]['first']})")
        new: dict[str, dict] = {}
        for p, by in kept.items():
            old = doc.get(p)
            if old is None:
                rec = {"first": today, "nights": 1, "bytes": by, "last": today}
            elif old.get("last") == today:
                rec = dict(old, bytes=by)          # re-run on the same day: no double count
            else:
                rec = {"first": old["first"], "nights": int(old["nights"]) + 1,
                       "bytes": by, "last": today}
            new[p] = rec
        try:
            save(ledger, new)
        except Exception as exc:
            print(f"ERROR: cannot write the exclusion ledger {ledger}: {exc}", file=sys.stderr)
            return 2
        doc = new

    for p in sorted(doc):
        out.append(line_for(p, doc[p]))
    if doc:
        out.append(f"⚠️  backup INCOMPLETE — {len(doc)} file(s) are on disk only; "
                   f"see the exclusion line(s) above.")
    elif today is None:
        # 2026-11-08 (self-audit, Lane B): the empty answer used to be a completely blank line,
        # which is indistinguishable from "the helper never ran" or "it read the wrong file".
        # Nothing excluded is a valid state; silence is not an answer.
        if os.path.exists(ledger):
            out.append(f"no exclusions recorded — ledger {ledger} is empty (the size guard has "
                       f"nothing unstaged)")
        else:
            out.append(f"no exclusions recorded — ledger {ledger} does not exist yet (the size "
                       f"guard has never unstaged a file)")
    if out:
        print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
