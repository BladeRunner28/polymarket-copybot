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

  The target is the computed peak by default. --force makes --confirm the
  target instead (for an approved number that differs from the measured one),
  and every guard is then evaluated against THAT value:

  python3 scripts/c200-drawdown-rebase.py --apply --confirm 7548.21 --force

  --apply refuses unless the target clears the gate (i.e. it actually
  un-halts), sits strictly above current realized NW (else the ratchet lifts it
  on the next run), and -- when not --force'd -- matches the computed peak to
  the cent. It writes data/c200-drawdown.json.bak-<ts> first, verifies what it
  wrote, and restores the backup if the written value is not the target.

  basisDeclaredAt is NOT re-stamped: the basis does not change (realized ->
  realized, only the peak moves). The reset is recorded by peakResetAt,
  peakResetFrom and the appended note. Re-stamping the era baseline is what
  broke the instrument: every settlement predates the new stamp, so the
  `since basisDeclaredAt` series goes empty and the era statistics become a
  vacuous window.

READ-ONLY otherwise: opens the DB with mode=ro and never touches it.
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

TOL = 0.005  # half a cent


def utc(ms):
    if not ms:
        return "n/a"
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def iso_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def load(db_path):
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, timeout=20)
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


def ruleset(db_path):
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, timeout=20)
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
    ap.add_argument("--confirm", type=float, default=None,
                    help="the peak you intend to write")
    ap.add_argument("--force", action="store_true",
                    help="write --confirm itself as the target even if it differs from the computed peak")
    ap.add_argument("--db", default=DB, help="override prisma/dev.db (testing)")
    ap.add_argument("--state", default=STATE, help="override data/c200-drawdown.json (testing)")
    args = ap.parse_args()

    if args.force and args.confirm is None:
        print("REFUSED: --force needs --confirm <peak> — there is no target to write")
        return 2

    d = load(args.db)
    version, rules = ruleset(args.db)
    dd_gate = float(rules.get("maxDrawdownPct") or 0.0)
    dd_basis = rules.get("ddBasis") or ""

    mtm_nw = d["principal"] + d["realized"] + d["open_unreal"]
    realized_nw = d["principal"] + d["realized"]
    stats = curve_stats(d["principal"], d["curve"])
    computed = stats["peak"]

    try:
        state = json.load(open(args.state))
    except Exception as e:
        print("FATAL: cannot read %s: %s" % (args.state, e))
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

    # ---- target selection -------------------------------------------------
    # Default: the corrected ledger's own realised high-water mark.
    # --force: the operator's approved number, taken verbatim; every guard
    # below is evaluated against it (that is what the doc promises).
    if args.force and args.confirm is not None:
        target = round(args.confirm, 2)
        forced = True
    else:
        target = computed
        forced = False
    target_dd = max(0.0, (target - gate_nw) / target) if target else 0.0

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
    print("last C-200 open          : %s UTC" % utc(d["last_open_ms"]))
    print("realized NW              : $%.2f" % realized_nw)
    print("MTM NW                   : $%.2f" % mtm_nw)
    print("")
    print("corrected realised curve : %d finished legs, %d distinct end timestamps" % (
        stats["rows"], stats["groups"]))
    print("  high-water mark        : $%.2f at %s UTC" % (stats["peak"], utc(stats["peak_at"])))
    print("  current                : $%.2f  -> drawdown %s" % (
        stats["end_nw"], pct((stats["peak"] - stats["end_nw"]) / stats["peak"]) if stats["peak"] else "n/a"))
    print("  deepest (all history)  : %s at %s UTC (peak then $%.2f)" % (
        pct(stats["max_dd"]), utc(stats["max_dd_at"]), stats["max_dd_peak"] or 0.0))
    if since_basis:
        if not dds:
            # Guard: an empty era series must not crash the instrument (it did,
            # at dds[-1], when an apply re-stamped basisDeclaredAt forward).
            print("  since basisDeclaredAt  : 0 settle events since %s — era statistics unavailable"
                  % state.get("basisDeclaredAt"))
        else:
            print("  since basisDeclaredAt  : %d observations, median %s, p90 %s, max %s, over-20%% days %d" % (
                len(dds), pct(dds[len(dds) // 2]), pct(dds[int(0.9 * (len(dds) - 1))]),
                pct(dds[-1]), sum(1 for x in dds if x > 0.20)))
    print("")
    print("stored watermark         : $%.2f (updatedAt %s, basisDeclaredAt %s)" % (
        stored_peak, state.get("updatedAt"), state.get("basisDeclaredAt")))
    print("stored -> DD on %s basis : %s   gate %s  -> %s" % (
        dd_basis or "mtm", pct(stored_dd), pct(dd_gate), "HALTED" if stored_dd > dd_gate else "open"))
    print("  NW needed to clear it  : $%.2f (%s)" % (
        stored_peak * (1 - dd_gate),
        ("+$%.2f from inside the lane" % (stored_peak * (1 - dd_gate) - gate_nw))
        if stored_peak * (1 - dd_gate) > gate_nw
        else "already clear, $%.2f of room" % (gate_nw - stored_peak * (1 - dd_gate))))
    print("  exposure cap (NW-based): $%.2f  (unaffected by the peak)" % (
        float(rules.get("maxGrossExposureUsd") or 0) + 0.5 * max(0.0, gate_nw - d["principal"])))
    print("")
    print("PROPOSED watermark       : $%.2f  -> DD %s  gate %s -> %s" % (
        target, pct(target_dd), pct(dd_gate), "HALTED" if target_dd > dd_gate else "OPEN"))
    if forced:
        print("  target source          : --confirm (forced by operator): %.2f vs computed HWM %.2f (%+.2f)"
              % (target, computed, target - computed))
        print("  trip line vs computed  : $%.2f vs $%.2f (%+.2f of room)"
              % (target * (1 - dd_gate), computed * (1 - dd_gate),
                 (target - computed) * (1 - dd_gate)))
    else:
        print("  target source          : computed corrected-ledger high-water mark")
    print("  20%% trip line          : $%.2f" % (target * (1 - dd_gate)))
    print("  sticks?                : %s (NW $%.2f %s peak $%.2f)" % (
        "yes" if gate_nw < target else "NO - ratchets to NW next run",
        gate_nw, "<" if gate_nw < target else ">=", target))
    if not forced and state.get("peakResetAt") and abs(stored_peak - round(computed, 2)) > TOL:
        print("  NOTE                   : stored %.2f != computed %.2f and a reset is already recorded (%s) —"
              " the default target would RAISE the peak; use --confirm %.2f --force to keep the stored value."
              % (stored_peak, computed, state.get("peakResetAt"), stored_peak))
    print("")

    # ---- guards (evaluated against the target that would be written) ------
    checks = [
        ("target above current NW", gate_nw < target,
         "NW $%.2f < target $%.2f" % (gate_nw, target)),
        ("DD after rebase under gate", target_dd <= dd_gate,
         "%s vs %s gate" % (pct(target_dd), pct(dd_gate))),
    ]
    if args.confirm is None:
        checks.append(("confirm is the written target", None, "no --confirm given (dry run)"))
    else:
        checks.append(("confirm is the written target", abs(args.confirm - target) <= TOL,
                       "confirm %.2f vs target %.2f" % (args.confirm, target)))
    if not forced:
        if args.confirm is None:
            checks.append(("confirm matches the computed peak", None,
                           "computed peak $%.2f; pass --confirm to test it" % computed))
        elif abs(args.confirm - computed) <= TOL:
            checks.append(("confirm matches the computed peak", True,
                           "confirm == computed peak $%.2f" % computed))
        else:
            checks.append(("confirm matches the computed peak", False,
                           "confirm %.2f != computed peak $%.2f (use --force to write a different approved number)"
                           % (args.confirm, computed)))
    print("GUARDS")
    for name, ok, detail in checks:
        print("  [%s] %-34s %s" % ("PASS" if ok is True else ("--" if ok is None else "FAIL"), name, detail))
    print("")

    after = dict(state)
    after["realizedPeak"] = round(target, 2)
    after["peakResetAt"] = iso_now()
    after["peakResetFrom"] = round(stored_peak, 2)
    # basisDeclaredAt is deliberately NOT re-stamped: the basis is unchanged
    # (realized -> realized, only the peak moves), and moving the era baseline
    # forward empties the `since basisDeclaredAt` series — see the module docstring.
    note = (
        " | %s: realizedPeak rebased %.2f -> %.2f (Lane A, approved apr-c200-realized-peak-rebase;"
        " computed corrected-ledger HWM %.2f)."
        " The approved ledger repair d974287 removed $3,843.89 of C-200 realizedPnl that had been booked on"
        " sibling-complement prices; the old watermark was ratcheted on pre-repair prices and the gate cannot"
        " fall, so C-200 halted at 37.0%% and could not restart. New watermark = the corrected ledger's own"
        " realized high-water mark (principal + cumulative realizedPnl over finished legs, by leg end time),"
        " recomputed read-only by scripts/c200-drawdown-rebase.py. basisDeclaredAt kept at %s (basis unchanged)."
        " Revert: restore the value from the .bak-<ts> file beside this one."
        % (iso_now()[:10], stored_peak, target, computed, state.get("basisDeclaredAt"))
    )
    if forced:
        note += " Target was operator-forced via --confirm (not the computed HWM)."
    after["note"] = (state.get("note") or "").rstrip() + note
    print("proposed state file      :")
    print(json.dumps(after, indent=2))
    print("")

    if not args.apply:
        print("dry run: nothing written. Operator apply:")
        if forced:
            print("  python3 scripts/c200-drawdown-rebase.py --apply --confirm %.2f --force" % target)
        else:
            print("  python3 scripts/c200-drawdown-rebase.py --apply --confirm %.2f" % target)
        return 0

    # ---- apply path (operator only) ----
    if args.confirm is None:
        print("REFUSED: --apply needs --confirm <peak> — the target you intend to write")
        return 2
    if not all(ok is True for _, ok, _ in checks):
        print("REFUSED: failed guard(s): %s" % ", ".join(n for n, ok, _ in checks if ok is not True))
        return 2
    if stored_peak == round(target, 2) and state.get("peakResetAt"):
        print("already rebased to %.2f — nothing to do" % target)
        return 0

    bak = args.state + ".bak-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    shutil.copy2(args.state, bak)
    with open(args.state, "w") as f:
        json.dump(after, f, indent=2)
    print("wrote %s (backup %s)" % (args.state, bak))
    check = json.load(open(args.state))
    written = float(check["realizedPeak"])
    written_dd = max(0.0, (written - gate_nw) / written) if written else 0.0
    if abs(written - round(target, 2)) > TOL:
        # Never leave a value behind that the operator did not confirm.
        shutil.copy2(bak, args.state)
        print("REFUSED: wrote %.2f but target was %.2f — state file restored from backup" % (written, target))
        return 3
    if check.get("basisDeclaredAt") != state.get("basisDeclaredAt"):
        print("WARNING: basisDeclaredAt changed to %r — era baseline moved" % check.get("basisDeclaredAt"))
    print("verify: realizedPeak=%.2f  DD=%s  gate %s -> %s  basisDeclaredAt=%s" % (
        written, pct(written_dd), pct(dd_gate), "HALTED" if written_dd > dd_gate else "OPEN",
        check.get("basisDeclaredAt")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
