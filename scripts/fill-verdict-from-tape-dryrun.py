#!/usr/bin/env python3
"""FILL VERDICT FROM TAPE — the row-level dry run for card `fill-verdict-from-tape` (LANE A, PROPOSE ONLY).

WHAT THIS ANSWERS
  For every settled, deduped leg opened >= 2026-09-01: did the venue's MIDPOINT ever come to the
  level we booked? And what does the book read under each candidate rule, one rule at a time?

  The grid is (horizon W) x (tolerance TAU) x (which side wins a disagreement):
    W   3600s  the card's literal window
        86400s the model-honest window — the paper ledger has NO CANCEL, so a bid that fills at
               hour 7 is still a position (profit-fill-tape S8 measures how much that is)
    TAU 0.001  strict touch: the midpoint printed at or below us (instrument default)
        0.005  half a 1c spread: our bid WAS the best bid (the series is a midpoint, not prints)
    POL resolver-first  the resolver's 'unfilled' stamp outvotes a tape touch
        tape-first      a tape touch outvotes the resolver's 'unfilled' stamp

WHY A SEPARATE SCRIPT
  scripts/profit-filled-decomp.py measures the *classes* (1h, strict touch). A read-path change
  hands a per-leg VERDICT to five surfaces, so the number that must be defensible is the book under
  the exact rule being shipped — including the 24h arm and the tolerance sweep, on one population,
  with the same dedupe/CI machinery. Every figure in the write-up comes from this run.

COST BASIS  PaperTrade.simulatedPositionSize = DOLLARS AT RISK (not shares). PnL = realizedPnl as
            stored (the exit rule is basis-independent). CIs market-clustered, 2,000 draws.
DEDUPE      first leg per bot|wallet|market|outcome (ppi.dedupe, same as every sibling instrument).
READ-ONLY   DB file:?mode=ro, no prisma write, no RuleSet read or write, no verdict store written,
            no fillStatus stamp, nothing cached except the HTTP tape (data/fill-tape-cache, gitignored).

RUN
  python3 scripts/fill-verdict-from-tape-dryrun.py
  python3 scripts/fill-verdict-from-tape-dryrun.py --min-rule 68
  python3 scripts/fill-verdict-from-tape-dryrun.py --selftest
"""
import argparse
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


ppi = _mod("ppi", os.path.join(HERE, "profit-postfix-integrity.py"))
ft = _mod("ft", os.path.join(HERE, "profit-fill-tape.py"))

WINDOWS = ((3600, "1h"), (86400, "24h"))
TAUS = ((0.001, "L+0.001 strict"), (0.005, "L+0.005 half-spread"))
POLS = (("resolver", "resolver-first"), ("tape", "tape-first"))
D = 86400000


def agg(ls):
    n = sum(l["simulatedPositionSize"] for l in ls)
    p = sum(l["realizedPnl"] or 0.0 for l in ls)
    return len(ls), n, p, (p / n * 100.0 if n else None)


def cistr(ls):
    if len(ls) < 2:
        return "n/a"
    lo, hi = ppi.cluster_ci(ls, lambda l: l["realizedPnl"] or 0.0)
    if lo is None:
        return "n/a"
    return "[%+.1f,%+.1f]" % (lo, hi)


def line(tag, ls, width=30):
    n, ntl, p, r = agg(ls)
    rr = "%+.1f%%" % r if r is not None else "   n/a"
    print("  %-*s %4d %9.0f %+10.1f %8s  %18s" % (width, tag, n, ntl, p, rr, cistr(ls)))


def days(ls):
    ts = [l["openedTs"] for l in ls if l.get("openedTs")]
    if len(ts) < 2:
        return 0.0
    return max((max(ts) - min(ts)) / float(D), 0.5)


def ex_top(ls, k):
    return sorted(ls, key=lambda l: -(l["realizedPnl"] or 0.0))[k:]


def touch24(l):
    """First t in (t0, t0+24h] whose midpoint <= trueP + TAU_MAX; None if never.

    24h series fetched once per leg (5-min fidelity, cached by profit-fill-tape.series24)."""
    if "h24" in l:
        return l["h24"]
    t0 = l["openedTs"] // 1000
    s = ft.series24(l["tape_token"], t0)
    l["h24"] = None
    if not s:
        l["h24"] = "no_tape"
        return l["h24"]
    l["h24"] = [(t, p) for t, p in s if t0 <= t <= t0 + 86400]
    return l["h24"]


def touched(l, W, tau):
    """Did the midpoint come to our level inside W at tolerance tau? None when the tape is silent."""
    L = l.get("trueP")
    if L is None or not l.get("tape_token"):
        return None
    t0 = l["openedTs"] // 1000
    if W <= 3600:
        s = l.get("tape_series") or []
        sub = [p for t, p in s if t0 <= t <= t0 + W]
        if not sub:
            return None
        return min(sub) <= L + tau + 1e-9
    s = touch24(l)
    if s in (None, "no_tape") or not s:
        return None
    return any(p <= L + tau + 1e-9 for _, p in s)


def verdict(l, W, tau, policy):
    """True = books, False = books zero, None = no evidence (falls back to the resolver stamp)."""
    stamp = l.get("fillStatus")
    t = touched(l, W, tau)
    if t is None:
        return None
    if policy == "tape":
        return bool(t) or stamp == "filled"
    # resolver-first: the resolver's negative wins, the tape only fills the gaps
    if stamp == "unfilled":
        return False
    if stamp == "filled":
        return True
    return bool(t)


def book(legs, W, tau, policy):
    ks, voids = [], []
    for l in legs:
        v = verdict(l, W, tau, policy)
        if v is None:
            # no evidence: keep today's behaviour (the resolver stamp decides, NULL books)
            (voids if l.get("fillStatus") == "unfilled" else ks).append(l)
        elif v:
            ks.append(l)
        else:
            voids.append(l)
    return ks, voids


def settled_between(ls, lo_ms, hi_ms):
    out = []
    for l in ls:
        t = l.get("closedTs") or l.get("resolvedTs")
        if t and lo_ms <= t < hi_ms:
            out.append(l)
    return out


def load_legs(since, dedupe=True):
    """ft.load's population, with the dedupe step optional.

    The measurement convention in every sibling instrument is "first leg per
    bot|wallet|market|outcome", but a SHIPPED read path sums ROWS. --rows runs the same rules over
    every finished leg so the number the operator will actually see is measured, not inferred."""
    legs = ppi.load_legs()
    if dedupe:
        legs = ppi.dedupe(legs)
    c = ft._con()
    cond = {r["id"]: r["conditionId"] for r in c.execute(
        "SELECT p.id AS id, o.conditionId AS conditionId FROM PaperTrade p "
        "JOIN DecisionJournal d ON d.id = p.decisionJournalId "
        "LEFT JOIN ObservedTrade o ON o.id = d.observedTradeId")}
    lo = ppi._ms(since)
    out = []
    for l in legs:
        if l["status"] == "open" or not l["openedTs"] or l["openedTs"] < lo:
            continue
        cid = cond.get(l["id"])
        if not cid:
            continue
        l["cid"] = cid
        out.append(l)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-rule", type=int, default=0)
    ap.add_argument("--since", default="2026-09-01")
    ap.add_argument("--rows", action="store_true",
                    help="no dedupe: every finished row, i.e. the population a shipped surface sums")
    a = ap.parse_args()
    rows_mode = a.rows

    print("=" * 96)
    print("FILL VERDICT FROM TAPE — row-level dry run (read-only; nothing is written)")
    print("=" * 96)
    legs = load_legs(a.since, dedupe=not rows_mode)
    for l in legs:
        l["closedTs"] = ppi._ms(l["closedAt"]) if l.get("closedAt") else None
        l["resolvedTs"] = ppi._ms(l["resolvedAt"]) if l.get("resolvedAt") else None
    legs = [l for l in legs if (l.get("rv") or 0) >= a.min_rule]
    print("\n  population: opened >= %s, non-demo, %s" %
          (a.since, "EVERY finished ROW (no dedupe — what a surface sums)" if rows_mode
           else "deduped first leg per bot|wallet|market|outcome"))
    print("  regime: DecisionJournal.ruleSetVersion >= %d -> %d legs" % (a.min_rule, len(legs)))
    print("  adjudicating (1h tape; 24h series fetched only for legs untouched in the hour) ...")
    ft.classify(legs, workers=8)
    notape = [l for l in legs if not l.get("tape_token") or l.get("tape_minp") is None]
    print("  no tape at all: %d legs (they fall back to the resolver stamp under every rule)" % len(notape))

    S = legs
    n, ntl, p, r = agg(S)
    print("\n  stored ledger (realizedPnl as booked): %d legs $%.0f %+.1f (%+.1f%%)" % (n, ntl, p, r))
    pos = [l for l in S if l.get("fillStatus") != "unfilled"]
    line("published basis (positions only)", pos)

    # ------------------------------------------------------------------ the grid
    print("\n" + "-" * 96)
    print("G1. THE GRID — one rule at a time, same population")
    print("-" * 96)
    print("  %-*s %4s %9s %10s %8s  %18s" % (30, "rule", "legs", "cost", "pnl", "ROI", "cluster CI"))
    for W, wl in WINDOWS:
        for tau, tl in TAUS:
            for pol, pl in POLS:
                ks, vd = book(S, W, tau, pol)
                line("%s %s %s" % (wl, tl, pl), ks, width=30)
    print("\n  READ: every arm voids the same thing (a level the market never came to inside W);")
    print("  they differ only on how much real exposure the window throws away with it.")

    # ------------------------------------------------------------------ voids by class
    print("\n" + "-" * 96)
    print("G2. WHAT EACH PIECE OF THE RULE ACTUALLY VOIDS (recommended rule: 24h, L+0.005, tape-first)")
    print("-" * 96)
    W, tau, pol = 86400, 0.005, "tape"
    ks, vd = book(S, W, tau, pol)
    for cls in ("filled", "unfilled", "NULL"):
        sub = [l for l in vd if (l.get("fillStatus") or "NULL") == cls]
        line("voided: resolver %s" % cls, sub)
    line("TOTAL voided", vd, width=30)
    for k in (1, 5, 10):
        e = ex_top(vd, k)
        n2, ntl2, p2, r2 = agg(e)
        print("  voided ex-top-%-2d %4d legs $%7.0f %+9.1f (%+.1f%%)" % (k, n2, ntl2, p2, r2))
    pos_n = sum(1 for l in vd if (l["realizedPnl"] or 0.0) > 0)
    print("  voided legs positive: %d of %d (%.0f%%) — a coin flip is what p(fill)=1 looks like"
          % (pos_n, len(vd), 100.0 * pos_n / len(vd) if vd else 0.0))
    line("BOOKS under the rule", ks, width=30)
    nn, nntl, npn, nr = agg(ks)
    dd = days(ks)
    if nntl:
        print("  rule book: %.1fd -> %+.1f $/day, %+.2f $/1k-capital-day" %
              (dd, npn / dd, npn / dd / nntl * 1000))
    print()
    for k in (1, 5, 10):
        e = ex_top(ks, k)
        n2, ntl2, p2, r2 = agg(e)
        print("  ex-top-%-2d %4d legs $%7.0f %+9.1f (%+.1f%%)" % (k, n2, ntl2, p2, r2))
    for lane in ("BANKROLL_200", "STANDARD"):
        line("  lane %s" % lane, [l for l in ks if l["botId"] == lane])
    print()
    print("  the voided class, by lane (what a LEDGER restatement would remove, if ever approved):")
    for lane in ("BANKROLL_200", "STANDARD"):
        line("  %s" % lane, [l for l in vd if l["botId"] == lane])

    # ------------------------------------------------------------------ the rung
    import time as _t
    now_ms = int(_t.time() * 1000)
    print("\n" + "-" * 96)
    print("G3. THE RUNG — settled days T-3..T-9 (query_bankroll.js SETTLE_DAYS=3, 7-day sum), bar +$1,750")
    print("-" * 96)
    lo, hi = now_ms - 10 * D, now_ms - 3 * D
    for label, pop in (("stored ledger", S), ("positions only (published)", pos),
                       ("rule book (24h/0.005/tape-first)", ks)):
        sub = settled_between(pop, lo, hi)
        n3, ntl3, p3, r3 = agg(sub)
        print("  %-32s %4d legs $%7.0f %+9.1f  %6.1f%% of the bar  (ex-top-1 %+.1f)" %
              (label, n3, ntl3, p3, p3 / 1750.0 * 100, agg(ex_top(sub, 1))[2]))

    # ------------------------------------------------------------------ live-regime arm
    if a.min_rule == 0:
        print("\n" + "-" * 96)
        print("G4. LIVE REGIME (v68+) ON THE SAME RULE — is the phantom a live problem?")
        print("-" * 96)
        live = [l for l in S if (l.get("rv") or 0) >= 68]
        ks2, vd2 = book(live, W, tau, pol)
        line("stored ledger", live)
        line("rule book", ks2)
        line("voided", vd2)
        n4, ntl4, p4, r4 = agg(vd2)
        sub = settled_between(vd2, lo, hi)
        print("  voided legs in the last 10d (settled): %d -> they are %s" %
              (len(sub), "HISTORICAL" if len(sub) == 0 else "still arriving"))

    print("\n" + "=" * 96)
    print("nothing written: no prisma row, no RuleSet, no verdict store, no fillStatus stamp")
    print("=" * 96)
    return 0


def selftest():
    L = {"trueP": 0.50, "openedTs": 1000 * 1000, "fillStatus": None, "tape_token": "T",
         "tape_series": [(1000, 0.60), (2000, 0.505)]}
    assert touched(L, 3600, 0.001) is False          # 0.505 > 0.501
    assert touched(L, 3600, 0.005) is True           # half-spread reaches our bid
    assert verdict(L, 3600, 0.005, "tape") is True
    L2 = dict(L, fillStatus="unfilled")
    assert verdict(L2, 3600, 0.005, "resolver") is False
    assert verdict(L2, 3600, 0.005, "tape") is True
    assert verdict({"trueP": 0.5, "openedTs": 1, "fillStatus": None, "tape_token": "T",
                    "tape_series": []}, 3600, 0.001, "tape") is None
    print("  selftest OK (tolerance, policy, no-evidence fallback)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main())
