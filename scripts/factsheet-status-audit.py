#!/usr/bin/env python3
"""factsheet-status-audit.py — read the typed input-health sidecar and answer its gate.

The card's gate (2026-11-09): "14-run clock starts on implementation; each run emits one typed row
per block and an audit count per state. After 14 runs read the JSONL — if >=1 block was
`gated_off` or `void`-with-rows in those runs and the same run's fact sheet carried no line about
it, promote the typed states into the fact-sheet header; else drop."

This script is that read. It prints, per run, the count of each state; then the runs that carried a
`gated_off` block or a `void`/`rate_limited` block WITH rows (the shape where a number was published
under an input that failed); then the gate verdict. A `no_results` state never fires the gate — it
is the honest quiet source the whole file exists to distinguish from a dead one.

Usage: python3 scripts/factsheet-status-audit.py [--runs 14] [--path FILE]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import factsheet_status  # noqa: E402

GATE_RUNS = 14


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=GATE_RUNS,
                    help="how many runs the gate counts (default %d)" % GATE_RUNS)
    ap.add_argument("--path", default=None, help="override the JSONL path (default: the live one)")
    a = ap.parse_args()

    path = Path(a.path) if a.path else factsheet_status.status_path()
    rows, bad = factsheet_status.load_rows(path)
    if not rows:
        print("input-health sidecar: %s" % path)
        print("  NO ROWS — the collector has not written since the writer was added"
              + ("" if not path.exists() else " (%d unparseable line(s) in the file)" % bad))
        print("  GATE: cannot fire — it needs >= %d runs with a typed row per block" % a.runs)
        return 1

    # Schema drift is reported, never swallowed: a row that no longer validates means the closed
    # key set moved without this reader.
    invalid = 0
    for r in rows:
        try:
            factsheet_status.validate_row(r)
        except Exception:  # noqa: BLE001 - any schema failure counts as drift, never a crash
            invalid += 1

    grouped = factsheet_status.runs(rows)
    order = list(grouped)
    print("input-health sidecar: %s" % path)
    print("  %d rows, %d run(s), %d unparseable line(s), %d row(s) failing the closed schema"
          % (len(rows), len(order), bad, invalid))
    if bad:
        print("  ! unparseable lines are a LOWER BOUND on the history — a torn write is missing, "
              "not absent")
    print()

    trigger_runs = []
    for run_id in order:
        rs = grouped[run_id]
        c = Counter(r.get("state") for r in rs)
        states = ", ".join("%s=%d" % (s, c.get(s, 0)) for s in factsheet_status.STATES)
        print("  %s  %d blocks — %s" % (run_id, len(rs), states))
        hot = [r for r in rs if r.get("state") == "gated_off"
               or (r.get("state") in ("void", "rate_limited") and (r.get("n") or 0) > 0)]
        if hot:
            trigger_runs.append((run_id, hot))
            for r in hot:
                print("      ! %s=%s n=%s (%s)" % (r.get("block"), r.get("state"),
                                                  r.get("n"), r.get("note") or "no note"))

    print()
    counted = order[-a.runs:] if len(order) > a.runs else order
    first = rows[0].get("run", "?")
    last = rows[-1].get("run", "?")
    print("  window: %s .. %s (%d of %d run(s) counted)"
          % (first, last, len(counted), len(order)))

    fired = [x for x in trigger_runs if x[0] in counted]
    print()
    if len(counted) < a.runs:
        print("GATE: NOT YET — %d/%d runs. Earliest fire: run %d."
              % (len(counted), a.runs, a.runs))
    elif fired:
        print("GATE: FIRED — %d run(s) inside the window carried a gated_off block or a "
              "void/rate_limited block with rows:" % len(fired))
        for run_id, hot in fired:
            print("  %s: %s" % (run_id, ", ".join(
                "%s=%s(n=%s)" % (r.get("block"), r.get("state"), r.get("n")) for r in hot)))
        print("  Next step (card): promote the typed states into the fact-sheet header. They are "
              "ALREADY named under '## Input health' on every run, so the promotion is the "
              "reader-facing sentence, not new plumbing.")
    else:
        print("GATE: DID NOT FIRE — no run in the window had a gated_off block or a "
              "void/rate_limited block carrying rows. Per the card: drop.")
    if invalid or bad:
        print("NOTE: the verdict above is over the parseable, schema-valid rows only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
