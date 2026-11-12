#!/usr/bin/env python3
"""[report-only] C-200 drawdown attribution: real drawdown, or a restatement artifact?

Run this whenever the realized drawdown gate trips (or is holding entries halted).
It answers one question: is the gap between `realizedPeak` and current realized NW
the product of SETTLED LOSSES, or of a one-off restatement of the ledger?

Three arms, all read-only (sqlite opened with mode=ro, the monitor log only read):

  S1  State: principal, BotBankroll.realizedPnl, the PaperTrade ledger sum, the
      watermark in data/c200-drawdown.json, the drawdown and the clearing line.
  S2  Watermark provenance: what cumulative realized PnL the watermark IMPLIES,
      against the highest cumulative realized PnL the repaired ledger has ever
      produced. An excess is a peak ratcheted above anything the book earned.
  S3  Discontinuity scan of the monitor's own [DRAWDOWN-SHADOW] series: the
      biggest one-cycle steps in realized NW. A restatement shows up as a single
      step larger than any settlement batch; real losses do not arrive in one tick.

Exit codes: 0 = read completed (verdict printed), 1 = a required artifact missing.
Nothing here writes: no DB write, no state file, no rule.

Usage:
  python3 scripts/c200-drawdown-attribution.py
  python3 scripts/c200-drawdown-attribution.py --log logs/cron/copybot-monitor-score.log --top 10
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
DD_FILE = os.path.join(ROOT, "data", "c200-drawdown.json")
DEFAULT_LOG = os.path.join(ROOT, "logs", "cron", "copybot-monitor-score.log")

BOT = "BANKROLL_200"


def iso(ms):
    return datetime.datetime.utcfromtimestamp(ms / 1000.0).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_ms(value):
    """PaperTrade DATETIME columns hold unix milliseconds (see references/data-notes.md)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value)
    # tolerate a stray ISO string rather than crashing on it
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return int(dt.replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    return None


def connect():
    if not os.path.exists(DB):
        print("MISSING: %s" % DB)
        sys.exit(1)
    return sqlite3.connect("file:%s?mode=ro" % DB, uri=True)


def load_events(con):
    """Settled C-200 legs with a settlement stamp, as (ms, pnl), sorted."""
    rows = con.execute(
        "SELECT realizedPnl, closedAt, resolvedAt FROM PaperTrade "
        "WHERE botId=? AND status IN ('closed','resolved')",
        (BOT,),
    ).fetchall()
    ev = []
    for pnl, ca, ra in rows:
        ms = to_ms(ca) if ca is not None else to_ms(ra)
        if ms is None:
            continue
        ev.append((ms, float(pnl or 0.0)))
    ev.sort()
    return ev


def correct_peak(events, principal):
    """Running high-water mark of principal + cumulative settled PnL, and the max drawdown."""
    cum = 0.0
    peak = principal
    peak_cum = 0.0
    peak_at = None
    worst = (0.0, None, None, None)
    for ms, pnl in events:
        cum += pnl
        nw = principal + cum
        if nw > peak:
            peak, peak_at, peak_cum = nw, ms, cum
        dd = (peak - nw) / peak if peak > 0 else 0.0
        if dd > worst[0]:
            worst = (dd, ms, nw, peak)
    return {"peak": peak, "peak_at": peak_at, "peak_cum": peak_cum, "now": principal + cum,
            "cum": cum, "worst": worst}


def era_slice(events, principal, era_ms):
    """Same curve restricted to settle events on/after era_ms (the basis declaration)."""
    cum = 0.0
    peak = principal
    worst = (0.0, None, None, None)
    n = 0
    for ms, pnl in events:
        cum += pnl
        if ms < era_ms:
            continue
        n += 1
        nw = principal + cum
        if nw > peak:
            peak = nw
        dd = (peak - nw) / peak if peak > 0 else 0.0
        if dd > worst[0]:
            worst = (dd, ms, nw, peak)
    return {"n": n, "worst": worst}


def scan_log(path, top):
    run_re = re.compile(r"^=== run (\S+) ===")
    nw_re = re.compile(r"realized NW \$(-?[\d.]+)")
    series = []
    cur = None
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            m = run_re.match(line)
            if m:
                cur = [m.group(1), None]
                series.append(cur)
                continue
            if cur is None or "DRAWDOWN-SHADOW" not in line:
                continue
            hit = nw_re.search(line)
            if hit:
                cur[1] = float(hit.group(1))
    pts = [(ts, nw) for ts, nw in series if nw is not None]
    steps = []
    for (ta, a), (tb, b) in zip(pts, pts[1:]):
        steps.append((b - a, ta, a, tb, b))
    steps.sort(key=lambda x: x[0])
    return pts, steps[:top]


def main():
    global DB, DD_FILE
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--db", default=DB, help="override the sqlite path (testing)")
    ap.add_argument("--dd-file", default=DD_FILE, help="override data/c200-drawdown.json (testing)")
    args = ap.parse_args()

    DB, DD_FILE = args.db, args.dd_file
    con = connect()
    bank = con.execute(
        "SELECT principal, realizedPnl, cashBalance FROM BotBankroll WHERE botId=?", (BOT,)
    ).fetchone()
    if bank is None:
        print("MISSING: no BotBankroll row for %s" % BOT)
        sys.exit(1)
    principal, realized, cash = float(bank[0]), float(bank[1]), float(bank[2])

    state = {}
    if os.path.exists(DD_FILE):
        state = json.load(open(DD_FILE))
    else:
        print("MISSING: %s" % DD_FILE)
        sys.exit(1)

    events = load_events(con)
    ledger = sum(p for _, p in events)
    realized_nw = principal + realized
    basis = state.get("basis", "mtm")
    rpeak = float(state.get("realizedPeak") or 0.0)
    dd = max(0.0, (rpeak - realized_nw) / rpeak) if rpeak else 0.0

    print("S1  STATE")
    print("    principal              $%10.2f" % principal)
    print("    BotBankroll.realizedPnl $%10.2f   cash $%.2f" % (realized, cash))
    print("    PaperTrade ledger sum   $%10.2f   (%d settled legs)" % (ledger, len(events)))
    print("    drift (row vs ledger)   $%10.2f   <- non-zero means the row is not the sum of its rows"
          % (realized - ledger))
    print("    declared basis          %s   (basisDeclaredAt %s)" % (basis, state.get("basisDeclaredAt")))
    print("    watermark realizedPeak  $%10.2f   (peak mtm $%.2f, updatedAt %s)"
          % (rpeak, float(state.get("peak") or 0.0), state.get("updatedAt")))
    print("    realized NW             $%10.2f" % realized_nw)
    print("    drawdown on that basis  %6.1f%%   gate at 20.0%%" % (dd * 100))
    if rpeak > 0:
        print("    clears when NW >=       $%10.2f   (gap $%.2f)" % (rpeak * 0.8, rpeak * 0.8 - realized_nw))

    cp = correct_peak(events, principal)
    print("\nS2  WATERMARK PROVENANCE (repaired ledger, current realizedPnl values)")
    print("    watermark implies cumulative realized PnL      $%10.2f" % (rpeak - principal))
    print("    ledger peak cumulative PnL                    $%10.2f  (at %s)"
          % (cp["peak_cum"], iso(cp["peak_at"]) if cp["peak_at"] else "n/a"))
    print("    ledger current cumulative PnL                  $%10.2f" % cp["cum"])
    print("    corrected high-water mark NW                  $%10.2f" % cp["peak"])
    print("    corrected drawdown today                            %6.2f%%" % (
        max(0.0, (cp["peak"] - realized_nw) / cp["peak"]) * 100 if cp["peak"] else 0.0))
    excess = (rpeak - principal) - cp["peak_cum"]
    print("    watermark ABOVE the ledger's own high-water mark     $%10.2f" % excess)
    if excess > 1.0:
        print("    VERDICT: the watermark is inflated by $%.2f — the drawdown it reports is an" % excess)
        print("             artifact of a ledger restatement, not settled losses.")
    elif dd > 0.20:
        print("    VERDICT: the watermark is inside the ledger's own range — treat the drawdown as REAL")
        print("             and read S3 for which settlements produced it.")
    else:
        print("    VERDICT: watermark consistent with the ledger; gate is not the binding issue.")

    era_ms = None
    declared = state.get("basisDeclaredAt")
    if declared:
        era_ms = to_ms(declared)
    if era_ms:
        era = era_slice(events, principal, era_ms)
        w = era["worst"]
        print("\n    realized-basis era (since %s): %d settle events, corrected max drawdown %.2f%% at %s"
              % (declared, era["n"], w[0] * 100, iso(w[1]) if w[1] else "n/a"))
        print("    -> on a clean ledger the gate %s have fired in this era." %
              ("WOULD NOT" if w[0] <= 0.20 else "WOULD"))
        if cp["worst"][1]:
            print("    whole-life corrected max drawdown %.2f%% at %s (before the era this gate read MTM)"
                  % (cp["worst"][0] * 100, iso(cp["worst"][1])))

    if os.path.exists(args.log):
        pts, steps = scan_log(args.log, args.top)
        print("\nS3  DISCONTINUITY SCAN  (%s, %d runs with a shadow line)" % (os.path.basename(args.log), len(pts)))
        print("    %-20s %12s %12s %12s" % ("boundary (local)", "from", "to", "step"))
        for d, ta, a, tb, b in steps:
            print("    %-20s %12.2f %12.2f %+12.2f   [%s]" % (ta, a, b, d, tb))
        if len(steps) >= 2:
            biggest, second = abs(steps[0][0]), abs(steps[1][0]) if len(steps) > 1 else 0.0
            print("    largest step is %.1fx the next largest -> %s" % (
                (biggest / second) if second else 0.0,
                "a single-event discontinuity (restatement or re-basing), not a settlement batch"
                if second and biggest > 4 * second else "no dominant discontinuity"))
    else:
        print("\nS3  skipped: log not found at %s" % args.log)


if __name__ == "__main__":
    main()
