#!/usr/bin/env python3
"""Regression for scripts/backup-exclusion-ledger.py.

The defect it prevents: the nightly backup unstages a file that crossed the 95 MB guard,
prints one ⚠️ line, and then prints "✅ backed up N files". Nothing recorded that the
exclusion was repeating, so a tracked tape could sit on disk only for weeks while the job
read clean. Measured 2026-11-02: data/wallet-sells.jsonl (101 MB) excluded, run still ✅.

Every case below is a way the counter could lie:
  * double counting a re-run on the same day (nights must move once per DATE)
  * resetting to night 1 when the ledger is unreadable (must be a loud error, exit 2)
  * never closing an entry when the file fits again (must DROP and say so)
  * printing INCOMPLETE when nothing is excluded (0 excluded must print nothing)

Run: python3 scripts/test-backup-exclusion-ledger.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(HERE, "backup-exclusion-ledger.py")
FAILS = []


def run(ledger, *args):
    env = dict(os.environ, BACKUP_EXCLUSION_LEDGER=ledger)
    p = subprocess.run([sys.executable, HELPER, *args], capture_output=True, text=True, env=env)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   [{detail}]"))
    if not cond:
        FAILS.append(name)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="excl-ledger-")
    ledger = os.path.join(tmp, "backup-exclusions.json")
    big = "data/wallet-sells.jsonl"

    rc, out, err = run(ledger, "--today", "2026-11-02", f"{big}:101000000")
    check("night 1 records the exclusion", rc == 0 and "excluded 1 night(s) since 2026-11-02" in out, out or err)
    check("night 1 announces INCOMPLETE", "backup INCOMPLETE" in out, out)
    doc = json.load(open(ledger))
    check("ledger holds one entry with nights=1", doc.get(big, {}).get("nights") == 1, doc)

    rc, out, _ = run(ledger, "--today", "2026-11-02", f"{big}:101500000")
    doc = json.load(open(ledger))
    check("re-run on the SAME day does not double count", doc.get(big, {}).get("nights") == 1, doc)
    check("re-run refreshes the measured size", doc.get(big, {}).get("bytes") == 101500000, doc)

    rc, out, _ = run(ledger, "--today", "2026-11-03", f"{big}:108871261")
    doc = json.load(open(ledger))
    check("next day increments to night 2", doc.get(big, {}).get("nights") == 2, doc)
    check("first-excluded date is preserved", doc.get(big, {}).get("first") == "2026-11-02", doc)
    check("night 2 line names 2 nights", "excluded 2 night(s) since 2026-11-02" in
          run(ledger, "--today", "2026-11-03", f"{big}:108871261")[1], "")

    rc, out, _ = run(ledger, "--today", "2026-11-04")
    doc = json.load(open(ledger))
    check("an entry that fits again is DROPPED", doc == {}, doc)
    check("and says CLOSED with the count", "CLOSED" in out and "2 night(s)" in out, out)
    check("nothing excluded prints no INCOMPLETE line", "INCOMPLETE" not in out, out)

    with open(ledger, "w") as fh:
        fh.write('{"data/wallet-sells.jsonl": "not-a-record"}')
    rc, out, err = run(ledger)
    check("malformed ledger is a loud error, not a silent reset", rc == 2 and "not empty" not in out, (rc, out, err))
    check("malformed ledger keeps the file untouched",
          json.load(open(ledger)) == {big: "not-a-record"}, open(ledger).read())

    os.unlink(ledger)
    rc, out, _ = run(ledger)
    check("missing ledger = nothing excluded (exit 0, silent)", rc == 0 and out == "", (rc, out))

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: {FAILS}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
