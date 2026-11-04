#!/usr/bin/env python3
"""Prove the fact-sheet's stock-clear exclusion is DERIVED, not a named date.

2026-11-04 (self-audit). The collector used `STOCK_CLEAR_DATE = "2026-10-24"`. Measured on the live
book at the fix it was still accurate (only one day in the trailing 45 clears the 100-closure bar),
but by construction it could not notice a NEW clear, and once 10-24 left the 7d window the
"EX-STOCK-CLEAR (2026-10-24 excluded)" line printed a date that was not in the window with numbers
identical to the blended line -- a control that cannot fail ON ITS OWN SUBJECT.

This test is about the property the hardcode lacked: a clear day the code has never heard of is
detected. Run: python3 scripts/test-bulk-close-days.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util

spec = importlib.util.spec_from_file_location(
    "research_collect", os.path.join(os.path.dirname(os.path.abspath(__file__)), "research-collect.py"))
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

STATUS_OK = "status IN ('closed','resolved')"
SCOL = "COALESCE(closedAt,resolvedAt)"
MS = 86400000
T0 = 1793000000000  # arbitrary epoch-ms anchor
CST = -5 * 3600 * 1000


def day_ms(day_index: int, hour: int = 12) -> int:
    """epoch-ms for local (CST) day `day_index` from the anchor."""
    return T0 + day_index * MS + hour * 3600000 - CST


def build() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE PaperTrade (botId TEXT, status TEXT, realizedPnl REAL, isDemo INT, "
        "closedAt INT, resolvedAt INT)")
    rows = []
    # ordinary day (day 1): 5 closures, split across lanes
    for i in range(3):
        rows.append(("STANDARD", "resolved", 10.0, 0, day_ms(1) + i, None))
    for i in range(2):
        rows.append(("BANKROLL_200", "resolved", 5.0, 0, day_ms(1) + i, None))
    # a NEW stock clear (day 2) the old code had never heard of: 150 STANDARD early exits
    for i in range(150):
        rows.append(("STANDARD", "closed", -1.0, 0, day_ms(2) + i, None))
    # the same day is ordinary for C-200 (4 resolutions) -- must NOT be a clear for that lane
    for i in range(4):
        rows.append(("BANKROLL_200", "resolved", -27.5, 0, day_ms(2) + i, None))
    # a demo leg that must be ignored when demo_ok is passed
    rows.append(("STANDARD", "closed", -999.0, 1, day_ms(2), None))
    # an OPEN leg (no clock value) that must never be counted as a closure
    rows.append(("STANDARD", "open", None, 0, None, None))
    con.executemany("INSERT INTO PaperTrade VALUES (?,?,?,?,?,?)", rows)
    return con


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got {got!r} want {want!r}")
    return ok


def main() -> int:
    con = build()
    cur = con.cursor()
    since = day_ms(0)
    ok = True

    clears = rc.bulk_close_days(cur, SCOL, STATUS_OK, " AND isDemo=0", since)
    # day 1 (5 closures) is ordinary; day 2 (150 STANDARD + 4 C-200 = 154 non-demo closures) is a
    # clear the code has never been told about
    ok &= check("blended: only the >={} day is flagged".format(rc.BULK_CLOSE_MIN_LEGS),
                [(n, pnl) for _, n, pnl in clears], [(154, -260.0)])
    ok &= check("blended: the flagged day is day 2", [d for d, _, _ in clears], ["2026-10-28"])

    ok &= check("per-lane C-200: the STANDARD clear is NOT a C-200 clear",
                rc.bulk_close_days(cur, SCOL, STATUS_OK, " AND isDemo=0", since, bot="BANKROLL_200"), [])
    ok &= check("per-lane STANDARD: its own clear IS flagged",
                [n for _, n, _ in rc.bulk_close_days(cur, SCOL, STATUS_OK, " AND isDemo=0", since,
                                                    bot="STANDARD")], [150])

    # window that contains no clear day -> [] so the caller must SAY "none" rather than reprint
    ok &= check("window with no clear day returns []",
                rc.bulk_close_days(cur, SCOL, STATUS_OK, " AND isDemo=0", day_ms(3)), [])

    # isDemo guard: the 1 demo leg is not counted (154, not 155) -- asserted above, restated here
    raw = rc.bulk_close_days(cur, SCOL, STATUS_OK, "", since)
    ok &= check("without the isDemo filter the demo leg perturbs the count",
                [n for _, n, _ in raw], [155])

    print("\n{}: {} assertion(s)".format("PASS" if ok else "FAIL",
                                         6 if ok else 0))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
