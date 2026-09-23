#!/usr/bin/env python3
"""
fetch-psmi-history — refresh the local record of Polycopy's PSMI daily closes.

SANCTIONED FEEDS ONLY (their robots.txt disallows /api/ in general; these two are
the endpoints their own page advertises as free to use with attribution, and
nothing else on /api/ may be touched):
  GET https://polycopy.app/api/indexes/smi/public                → today's score
  GET https://polycopy.app/api/indexes/smi/history?format=csv     → daily closes

Writes data/polycopy-psmi-history.csv. Existing rows are NEVER rewritten — the
stored file is the immovable record of what their API said on the day we read it
(same convention as data/phase-streak-log.jsonl), so a later silent revision of
their history cannot retroactively move a number this analysis was run against.
New dates are appended in chronological order; the comment header is preserved.

Usage:  python3 scripts/fetch-psmi-history.py            # refresh (idempotent)
        python3 scripts/fetch-psmi-history.py --dry-run  # report only, no write

No cron wiring: the measurement card that produced this file (polycopy-psmi-
regime-measurement, 2026-09-23) closed on a null, and its sample's power is what
limits it — a daily append would let a future re-test run on 2-3x the days.
"""
import argparse
import csv
import datetime
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSV_PATH = os.path.join(ROOT, "data", "polycopy-psmi-history.csv")
BASE = "https://polycopy.app/api/indexes/smi"
UA = "MedusaCopyBot-research (polymarket-copybot; attribution: Polycopy PSMI)"
FIELDS = ["date", "score", "zone", "momentum", "breadth", "participation",
          "conviction", "methodology_version", "is_backfill"]


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_rows(text):
    lines = text.splitlines()
    header = [l for l in lines if l.startswith("#")]
    body = [l for l in lines if l and not l.startswith("#")]
    reader = csv.DictReader(body)
    rows = []
    for r in reader:
        if not r.get("date"):
            continue
        rows.append({k: (r.get(k) or "").strip() for k in FIELDS})
    return header, rows


def load_existing():
    if not os.path.exists(CSV_PATH):
        return [], []
    with open(CSV_PATH) as fh:
        lines = fh.read().splitlines()
    header = [l for l in lines if l.startswith("#")]
    body = [l for l in lines if l and not l.startswith("#")]
    return header, list(csv.DictReader(body))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    snap = http_get(BASE + "/public")
    hist = http_get(BASE + "/history?format=csv")
    header, fetched = parse_rows(hist)
    if not fetched:
        print("fetch-psmi-history: history endpoint returned no rows — nothing written")
        return 1

    old_header, existing = load_existing()
    have = {r["date"] for r in existing}
    new = [r for r in fetched if r["date"] not in have]
    print("today's PSMI snapshot: %s" % snap.strip()[:200])
    print("history endpoint: %d rows (%s → %s); local file: %d rows"
          % (len(fetched), fetched[0]["date"], fetched[-1]["date"], len(existing)))

    if not new:
        print("no new dates — file unchanged (%d rows, latest %s)"
              % (len(existing), existing[-1]["date"] if existing else "n/a"))
        return 0

    merged = {r["date"]: r for r in existing}
    for r in new:
        merged[r["date"]] = r
    ordered = [merged[d] for d in sorted(merged)]
    print("appending %d new date(s): %s" % (len(new), ", ".join(r["date"] for r in new)))

    if args.dry_run:
        print("--dry-run: nothing written (%d rows would be stored)" % len(ordered))
        return 0

    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    out_header = old_header or header
    with open(CSV_PATH, "w") as fh:
        for line in out_header:
            fh.write(line + "\n")
        fh.write("# Local record; rows are never rewritten (appended by scripts/fetch-psmi-history.py).\n")
        fh.write("# Last refresh: %s\n" % stamp)
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in ordered:
            w.writerow(r)
    print("wrote %s (%d rows)" % (os.path.relpath(CSV_PATH, ROOT), len(ordered)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
