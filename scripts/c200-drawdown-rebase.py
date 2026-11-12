#!/usr/bin/env python3
"""C-200 realized drawdown watermark: measure, and (with --apply) rebase.

WHY THIS EXISTS
  data/c200-drawdown.json holds the drawdown gate's high-water mark. The gate
  (scripts/score-trades.ts) computes NW = principal + BotBankroll.realizedPnl
  (+ open unrealized on the MTM basis) and HALTS all C-200 entries when
  (peak - NW) / peak > rules.maxDrawdownPct. The peak only ever RATCHETS UP, so
  it cannot fall when a ledger repair lowers realizedPnl: the lane halts and
  cannot restart itself.

  This script recomputes what that watermark WOULD have been if the corrected
  ledger values had always been in force: principal + cumulative realizedPnl
  over every finished C-200 leg, ordered by the leg's own end time
  (closedAt, else resolvedAt). Its maximum is the honest peak.

USAGE
  python3 scripts/c200-drawdown-rebase.py                 # dry run, writes nothing
  python3 scripts/c200-drawdown-rebase.py --apply --confirm 7987.32
                                                          # operator-only; writes the state file

  --apply refuses unless --confirm matches the computed peak to the cent, the
  corrected drawdown after the rebase is BELOW the gate (i.e. it actually
  un-halts), and the target is not so far above NW that it would mask a real
  fall. It writes data/c200-drawdown.json.bak-<ts> first.

READ-ONLY otherwise: opens prisma/dev.db with mode=ro and never touches the DB.
"""
import argparse
import datetime
import json
import os
import shutil
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "prisma", "dev.db")
STATE = os.path.join(ROOT, "data", "c200-drawdown.json")
BOT = "BANKROLL_200"


def utc(ms):
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def iso_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def load():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=20)
    q = con.execute
    br = q(
        "SELECT principal, cashBalance, realizedPnl FROM BotBankroll WHERE botId=?", (BOT,)
    ).fetchone()
    principal, cash, realized = br[0] or 0.0, br[1] or 0.0, br[2] or 0.0
    legs, notional, unreal = q(
        "SELECT COUNT(*), COALESCE(SUM(simulatedPositionSize),0), COALESCE(SUM(unrealizedPnl),0) "
        "FROM PaperTrade WHERE botId=? AND status='open'",
        (BOT,),
    ).fetchone()
    rows = q(
        "SELECT COALESCE(closedAt, resolvedAt), realizedPnl FROM PaperTrade "
        "WHERE botId=? AND status IN ('closed','resolved') AND COALESCE(closedAt,resolvedAt) IS NOT NULL "
        "ORDER BY COALESCE(closedAt,resolvedAt) ASC",
        (BOT,),
    ).fetchall()
    row_sum = q(
        "SELECT COALESCE(SUM(realizedPnl),0) FROM PaperTrade WHERE botId=? AND status IN ('closed','resolved')",
        (BOT,),
    ).fetchone()[0]
    last_open = q(
        "SELECT MAX(openedAt) FROM PaperTrade WHERE botId=?", (BOT,)
    ).fetchone()[0]
    con.close()
    return {
        "principal": principal,
        "cash": cash,
        "realized": realized,
        "open_legs": legs,
        "open_notional": notional,
        "open_unreal": unreal,
        "curve": rows,
        "row_sum": row_sum,
        "last_open_ms": last_open,
    }


def ruleset():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=20)
    r = con.execute(
        "SELECT version, rulesJson FROM RuleSet WHERE active=1 ORDER BY version DESC LIMIT 1"
    ).fetchone()
    con.close()
    if not r:
        return None, {}
    return r[0], json.loads(r[1])


def curve_stats(principal, rows, since_ms=None):
    """Order-invariant realised equity curve: cumulative at each distinct end time."""
    groups = {}
    for e, pnl in rows:
        groups[e] = groups.get(e, 0.0) + (pnl or 0.0)
    cum = 0.0
    peak = principal
    peak_at = None
    max_dd = 0.0
    max_dd_at = None
    max_dd_peak = None
    dd_series = []
    for e in sorted(groups):
        cum += groups[e]
        nw = principal + cum
        if nw > peak:
            peak, peak_at = nw, e
        dd = (peak - nw) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd, max_dd_at, max_dd_peak = dd, e, peak
        if since_ms is None or e >= since_ms:
            dd_series.append((e, dd))
    return {
        "peak": peak,
        "peak_at": peak_at,
        "end_nw": principal + cum,
        "groups": len(groups),
        "rows": len(rows),
        "max_dd": max_dd,
        "max_dd_at": max_dd_at,
        "max_dd_peak": max_dd_peak,
        "dd_series": dd_series,
    }


def pct(x):
    return "%.2f%%" % (x * 100.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the state file (operator only)")
    ap.add_argument("--confirm", type=float, default=None, help="the peak you intend to write")
    ap.add_argument("--force", action="store_true", help="write even if --confirm is not the computed peak")
    args = ap.parse_args()

    d = load()
    version, rules = ruleset()
    dd_gate = float(rules.get("maxDrawdownPct") or 0.0)
    dd_basis = rules.get("ddBasis") or ""

    mtm_nw = d["principal"] + d["realized"] + d["open_unreal"]
    realized_nw = d["principal"] + d["realized"]
    stats = curve_stats(d["principal"], d["curve"])

    try:
        state = json.load(open(STATE))
    except Exception as e:
        print("FATAL: cannot read %s: %s" % (STATE, e))
        return 2

    stored_peak = float(state.get("realizedPeak") or d["principal"])
    stored_peak = max(stored_peak, d["principal"])
    gate_nw = realized_nw if dd_basis == "realized" else mtm_nw
    stored_dd = max(0.0, (stored_peak - gate_nw) / stored_peak) if stored_peak else 0.0
    basis_ms = None
    if state.get("basisDeclaredAt"):
        try:
            basis_ms = int(
                datetime.datetime.strptime(
                    state["basisDeclaredAt"][:19], "%Y-%m-%dT%H:%M:%S"
                ).replace(tzinfo=datetime.timezone.utc).timestamp() * 1000
            )
        except Exception:
            basis_ms = None
    since_basis = curve_stats(d["principal"], d["curve"], basis_ms) if basis_ms else None
    series = (since_basis or stats)["dd_series"]
    dds = sorted(x[1] for x in series)

    target = stats["peak"]
    dict_nw = realized_nw if dd_basis == "realized" else mtm_nw
    target_dd = max(0.0, (target - dict_nw) / target) if target else 0.0

    print("== C-200 drawdown watermark: measurement ==")
    print("as of                    : %s UTC" % iso_now())
    print("RuleSet                  : v%s  maxDrawdownPct=%.2f  ddBasis=%r" % (version, dd_gate, dd_basis))
    print("principal                : $%.2f" % d["principal"])
    print("BotBankroll.realizedPnl  : $%.2f   (sum of finished rows $%.2f, offset $%.2f)" % (
        d["realized"], d["row_sum"], d["row_sum"] - d["realized"]))
    print("BotBankroll.cashBalance  : $%.2f   (principal + realized - open notional = $%.2f)" % (
        d["cash"], d["principal"] + d["realized"] - d["open_notional"]))
    print("open legs                : %d  notional $%.2f  unrealized $%.2f" % (
        d["open_legs"], d["open_notional"], d["open_unreal"]))
    print("last C-200 open          : %s UTC" % (utc(d["last_open_ms"]) if d["last_open_ms"] else "never"))
    print("realized NW              : $%.2f" % realized_nw)
    print("MTM NW                   : $%.2f" % mtm_nw)
    print("")
    print("corrected realised curve : %d finished legs, %d distinct end timestamps" % (
        stats["rows"], stats["groups"]))
    print("  high-water mark        : $%.2f at %s UTC" % (stats["peak"], utc(stats["peak_at"])))
    print("  current                : $%.2f  -> drawdown %s" % (stats["end_nw"], pct((stats["peak"] - stats["end_nw"]) / stats["peak"])))
    print("  deepest (all history)  : %s at %s UTC (peak then $%.2f)" % (
        pct(stats["max_dd"]), utc(stats["max_dd_at"]), stats["max_dd_peak"] or 0.0))
    if since_basis:
        print("  since basisDeclaredAt  : %d observations, median %s, p90 %s, max %s, over-20%% days %d" % (
            len(dds), pct(dds[len(dds) // 2]), pct(dds[int(0.9 * (len(dds) - 1))]),
            pct(dds[-1]), sum(1 for x in dds if x > 0.20)))
    print("")
    print("stored watermark         : $%.2f (updatedAt %s, basisDeclaredAt %s)" % (
        stored_peak, state.get("updatedAt"), state.get("basisDeclaredAt")))
    print("stored -> DD on %s basis : %s   gate %s  -> %s" % (
        dd_basis or "mtm", pct(stored_dd), pct(dd_gate), "HALTED" if stored_dd > dd_gate else "open"))
    print("  NW needed to clear it  : $%.2f (+$%.2f from inside the lane)" % (
        stored_peak * (1 - dd_gate), stored_peak * (1 - dd_gate) - gate_nw))
    print("  exposure cap (NW-based): $%.2f  (unaffected by the peak)" % (
        float(rules.get("maxGrossExposureUsd") or 0) + 0.5 * max(0.0, dict_nw - d["principal"])))
    print("")
    print("PROPOSED watermark       : $%.2f  -> DD %s  gate %s -> %s" % (
        target, pct(target_dd), pct(dd_gate), "HALTED" if target_dd > dd_gate else "OPEN"))
    print("  20%% trip line          : $%.2f" % (target * (1 - dd_gate)))
    print("  sticks?                : %s (NW $%.2f %s peak $%.2f)" % (
        "yes" if dict_nw < target else "NO - ratchets to NW next run",
        dict_nw, "<" if dict_nw < target else ">=", target))
    print("")

    after = dict(state)
    after["realizedPeak"] = round(target, 2)
    after["peakResetAt"] = iso_now()
    after["basisDeclaredAt"] = iso_now()
    after["note"] = (
        (state.get("note") or "").rstrip()
        + " | %s: realizedPeak rebased %.2f -> %.2f (Lane A, approved apr-c200-realized-peak-rebase)."
          " The approved ledger repair d974287 removed $3,843.89 of C-200 realizedPnl that had been booked on"
          " sibling-complement prices; the old watermark was ratcheted on pre-repair prices and the gate cannot"
          " fall, so C-200 halted at 37.0%% and could not restart. New watermark = the corrected ledger's own"
          " realized high-water mark (principal + cumulative realizedPnl over finished legs, by leg end time),"
          " recomputed read-only by scripts/c200-drawdown-rebase.py. Revert: restore the value from the"
          " .bak-<ts> file beside this one." % (iso_now()[:10], stored_peak, target)
    )
    print("proposed state file      :")
    print(json.dumps(after, indent=2))
    print("")

    if not args.apply:
        print("dry run: nothing written. Operator apply:")
        print("  python3 scripts/c200-drawdown-rebase.py --apply --confirm %.2f" % target)
        return 0

    # ---- apply path (operator only) ----
    if args.confirm is None:
        print("REFUSED: --apply needs --confirm <peak> matching the computed peak")
        return 2
    if not args.force and abs(args.confirm - target) > 0.005:
        print("REFUSED: --confirm %.2f != computed peak %.2f (use --force to override deliberately)" % (
            args.confirm, target))
        return 2
    if stored_peak == round(target, 2) and state.get("peakResetAt"):
        print("already rebased to %.2f — nothing to do" % target)
        return 0
    if target_dd > dd_gate:
        print("REFUSED: DD after rebase %s still exceeds the %s gate — this would not un-halt the lane" % (
            pct(target_dd), pct(dd_gate)))
        return 2
    if dict_nw >= target:
        print("REFUSED: NW $%.2f >= target $%.2f — the ratchet would move it on the next run" % (dict_nw, target))
        return 2

    bak = STATE + ".bak-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    shutil.copy2(STATE, bak)
    with open(STATE, "w") as f:
        json.dump(after, f, indent=2)
    print("wrote %s (backup %s)" % (STATE, bak))
    check = json.load(open(STATE))
    print("verify: realizedPeak=%.2f  DD=%s  gate %s -> %s" % (
        check["realizedPeak"],
        pct(max(0.0, (check["realizedPeak"] - gate_nw) / check["realizedPeak"])),
        pct(dd_gate),
        "HALTED" if max(0.0, (check["realizedPeak"] - gate_nw) / check["realizedPeak"]) > dd_gate else "OPEN"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
